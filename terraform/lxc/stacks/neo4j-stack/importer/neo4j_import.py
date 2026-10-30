#!/usr/bin/env python3
"""Rebuild the homelab threat-model graph in Neo4j from NetBox.

Sources (all read-only NetBox API calls):
  - config context 'threat-model'  (trust boundaries, external entities,
    processes, data stores, data flows -- written by netbox-populate's
    flows.py from stack.yaml / edge.yaml / network intent)
  - virtualization/virtual-machines  (+ primary IPv4)
  - ipam/services                     (VM-parented only)
  - ipam/prefixes, ipam/vlans

Every imported node carries the :Homelab label and a stable `key`. Each run
stamps nodes/relationships with `import_run` and, in the same transaction,
deletes :Homelab nodes and imported relationships the run didn't touch.
Hand-authored nodes (e.g. :Threat, :Mitigation) without the :Homelab label
are never pruned, so threat-modeling work layered on top survives re-import.

Standalone usage (stdlib only, no neo4j driver needed -- talks to Neo4j's
HTTP transaction API):
    NETBOX_URL=http://192.168.40.12:8080 NETBOX_TOKEN=... \\
    NEO4J_PASSWORD=... python3 neo4j_import.py            # import
    python3 neo4j_import.py --dry-run                     # print graph summary
"""

import argparse
import base64
import ipaddress
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid

THREAT_MODEL_CONTEXT_NAME = "threat-model"

# Labels/relationship types are interpolated into Cypher, so they come only
# from these fixed sets -- never from NetBox data.
NODE_LABELS = (
    "TrustBoundary",
    "ExternalEntity",
    "Process",
    "DataStore",
    "Zone",
    "Unresolved",
    "VirtualMachine",
    "IPAddress",
    "Service",
    "Prefix",
    "VLAN",
)
REL_TYPES = (
    "FLOWS_TO",
    "IN_ZONE",
    "HOSTED_ON",
    "RUNS_ON",
    "HAS_IP",
    "EXPOSES",
    "IN_PREFIX",
    "ON_VLAN",
)


# ---------------------------------------------------------------------------
# Graph building (pure -- no I/O, unit-tested)
# ---------------------------------------------------------------------------


def _clean_props(props):
    """Neo4j properties must be primitives or homogeneous primitive lists."""
    out = {}
    for k, v in props.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list) and all(isinstance(i, (str, int, float, bool)) for i in v):
            if len({type(i) for i in v}) == 1:
                out[k] = v
            else:
                out[k] = [str(i) for i in v]
        else:
            out[k] = json.dumps(v, sort_keys=True)
    return out


class Graph:
    def __init__(self):
        self.nodes = {}  # key -> (label, props)
        self.rels = {}  # (type, from, to, key) -> props

    def node(self, label, key, props=None):
        if label not in NODE_LABELS:
            raise ValueError(f"unknown node label {label!r}")
        existing = self.nodes.get(key)
        merged = dict(existing[1]) if existing else {}
        merged.update(_clean_props(props or {}))
        self.nodes[key] = (existing[0] if existing else label, merged)
        return key

    def rel(self, rel_type, src, dst, props=None, key=None):
        if rel_type not in REL_TYPES:
            raise ValueError(f"unknown relationship type {rel_type!r}")
        rel_key = key or f"{rel_type}:{src}->{dst}"
        self.rels[(rel_type, src, dst, rel_key)] = _clean_props(props or {})

    def summary(self):
        counts = {}
        for label, _ in self.nodes.values():
            counts[label] = counts.get(label, 0) + 1
        rel_counts = {}
        for rel_type, *_ in self.rels:
            rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1
        return {"nodes": dict(sorted(counts.items())), "relationships": dict(sorted(rel_counts.items()))}


def _zone_key(name):
    return f"zone:{name}"


def add_threat_model(graph, model):
    """Add the flows.py threat model (NetBox config context data) to the graph."""
    for tb in model.get("trust_boundaries", []):
        graph.node("TrustBoundary", tb["id"], tb)
    for ee in model.get("external_entities", []):
        graph.node("ExternalEntity", ee["id"], ee)
    for proc in model.get("processes", []):
        props = dict(proc)
        props["provides"] = [
            f"{p.get('service')}/{p.get('port')}/{p.get('protocol')}" for p in proc.get("provides", [])
        ]
        graph.node("Process", proc["id"], props)
        if proc.get("zone"):
            graph.node("Zone", _zone_key(proc["zone"]), {"name": proc["zone"]})
            graph.rel("IN_ZONE", proc["id"], _zone_key(proc["zone"]))
    for ds in model.get("data_stores", []):
        graph.node("DataStore", ds["id"], ds)
        if ds.get("host"):
            _ensure_endpoint(graph, ds["host"])
            graph.rel("HOSTED_ON", ds["id"], ds["host"])
    seen_ids = {}
    for flow in model.get("data_flows", []):
        src = _ensure_endpoint(graph, flow.get("from"))
        dst = _ensure_endpoint(graph, flow.get("to"))
        if not src or not dst:
            continue
        props = {k: v for k, v in flow.items() if k not in ("from", "to")}
        # flows.py reuses one id for every Traefik route to a multi-route
        # stack; suffix repeats so each route stays its own relationship.
        flow_id = flow.get("id")
        seen_ids[flow_id] = seen_ids.get(flow_id, 0) + 1
        key = flow_id if seen_ids[flow_id] == 1 else f"{flow_id}#{seen_ids[flow_id]}"
        graph.rel("FLOWS_TO", src, dst, props, key=key)


def _ensure_endpoint(graph, ref):
    """Return the node key for a flow endpoint, creating Zone/Unresolved nodes as needed."""
    if not ref:
        return None
    if ref in graph.nodes:
        return ref
    if ref.startswith("zone:"):
        return graph.node("Zone", ref, {"name": ref[len("zone:"):]})
    # Keep the flow rather than silently dropping it -- an Unresolved node is
    # itself a finding (a flow pointing at something the model doesn't define).
    return graph.node("Unresolved", ref, {"name": ref})


def add_inventory(graph, vms, services, prefixes, vlans):
    """Add NetBox VMs, primary IPs, services, prefixes and VLANs to the graph."""
    vlan_keys = {}
    for vlan in vlans:
        key = f"vlan:{vlan['id']}"
        group = (vlan.get("group") or {}).get("name")
        graph.node("VLAN", key, {"vid": vlan.get("vid"), "name": vlan.get("name"), "group": group})
        vlan_keys[vlan["id"]] = key

    prefix_nets = []
    for prefix in prefixes:
        cidr = prefix.get("prefix")
        if not cidr:
            continue
        key = f"prefix:{cidr}"
        graph.node("Prefix", key, {
            "prefix": cidr,
            "description": prefix.get("description"),
            "status": (prefix.get("status") or {}).get("value"),
        })
        prefix_nets.append((ipaddress.ip_network(cidr, strict=False), key))
        vlan = prefix.get("vlan") or {}
        if vlan.get("id") in vlan_keys:
            graph.rel("ON_VLAN", key, vlan_keys[vlan["id"]])

    process_by_name = {
        props.get("name"): key for key, (label, props) in graph.nodes.items() if label == "Process"
    }

    vm_keys = {}
    for vm in vms:
        key = f"vm:{vm['id']}"
        cluster = (vm.get("cluster") or {}).get("name")
        graph.node("VirtualMachine", key, {
            "name": vm.get("name"),
            "netbox_id": vm["id"],
            "cluster": cluster,
            "status": (vm.get("status") or {}).get("value"),
            "vcpus": vm.get("vcpus"),
            "memory": vm.get("memory"),
            "tags": [t.get("name") for t in vm.get("tags", []) if t.get("name")],
        })
        vm_keys[vm["id"]] = key
        # Process.name is the stack name, which is also the LXC hostname
        # NetBox records -- the join between the DFD and the inventory.
        if vm.get("name") in process_by_name:
            graph.rel("RUNS_ON", process_by_name[vm["name"]], key)
        address = (vm.get("primary_ip4") or {}).get("address")
        if address:
            ip_key = f"ip:{address}"
            graph.node("IPAddress", ip_key, {"address": address})
            graph.rel("HAS_IP", key, ip_key)
            iface = ipaddress.ip_interface(address)
            # Longest matching prefix only, so a /24 isn't also linked to a
            # covering /16 supernet.
            matches = [(net, pkey) for net, pkey in prefix_nets if iface.ip in net]
            if matches:
                graph.rel("IN_PREFIX", ip_key, max(matches, key=lambda m: m[0].prefixlen)[1])

    for svc in services:
        if svc.get("parent_object_type") != "virtualization.virtualmachine":
            continue
        vm_key = vm_keys.get(svc.get("parent_object_id"))
        if not vm_key:
            continue
        key = f"svc:{svc['id']}"
        graph.node("Service", key, {
            "name": svc.get("name"),
            "protocol": (svc.get("protocol") or {}).get("value"),
            "ports": svc.get("ports"),
            "description": svc.get("description"),
        })
        graph.rel("EXPOSES", vm_key, key)


def build_graph(model, vms, services, prefixes, vlans):
    graph = Graph()
    add_threat_model(graph, model)
    add_inventory(graph, vms, services, prefixes, vlans)
    return graph


# ---------------------------------------------------------------------------
# Cypher generation (pure -- unit-tested)
# ---------------------------------------------------------------------------


# Schema changes can't share a transaction with data writes, so this is
# committed on its own before build_statements' transaction.
SCHEMA_STATEMENTS = [
    {"statement": "CREATE CONSTRAINT homelab_key IF NOT EXISTS FOR (n:Homelab) REQUIRE n.key IS UNIQUE"},
]


def build_statements(graph, run_id):
    statements = []

    by_label = {}
    for key, (label, props) in graph.nodes.items():
        by_label.setdefault(label, []).append({"key": key, "props": props})
    for label in sorted(by_label):
        statements.append({
            "statement": (
                "UNWIND $rows AS row "
                "MERGE (n:Homelab {key: row.key}) "
                "SET n = row.props, n.key = row.key, n.import_run = $run "
                # Clear managed labels first so a node whose type changed
                # between runs (e.g. Unresolved -> Process) doesn't keep both.
                f"REMOVE n:{':'.join(NODE_LABELS)} "
                f"SET n:{label}"
            ),
            "parameters": {"rows": by_label[label], "run": run_id},
        })

    by_type = {}
    for (rel_type, src, dst, rel_key), props in graph.rels.items():
        by_type.setdefault(rel_type, []).append({"from": src, "to": dst, "key": rel_key, "props": props})
    for rel_type in sorted(by_type):
        statements.append({
            "statement": (
                "UNWIND $rows AS row "
                "MATCH (a:Homelab {key: row.from}) "
                "MATCH (b:Homelab {key: row.to}) "
                f"MERGE (a)-[r:{rel_type} {{key: row.key}}]->(b) "
                "SET r = row.props, r.key = row.key, r.import_run = $run"
            ),
            "parameters": {"rows": by_type[rel_type], "run": run_id},
        })

    # Prune last, in the same transaction: a failed run rolls back whole and
    # leaves the previous graph intact.
    statements.append({
        "statement": (
            "MATCH (:Homelab)-[r]->(:Homelab) "
            "WHERE r.import_run IS NOT NULL AND r.import_run <> $run DELETE r"
        ),
        "parameters": {"run": run_id},
    })
    statements.append({
        "statement": "MATCH (n:Homelab) WHERE n.import_run <> $run DETACH DELETE n",
        "parameters": {"run": run_id},
    })
    return statements


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _netbox_auth_header(token):
    # NetBox 4.5 v2 tokens (nbt_...) use Bearer; v1 tokens use Token.
    return f"Bearer {token}" if token.startswith("nbt_") else f"Token {token}"


def netbox_get_all(base_url, token, path, params=None):
    query = dict(params or {})
    query.setdefault("limit", 500)
    url = f"{base_url.rstrip('/')}/api{path}?{urllib.parse.urlencode(query)}"
    results = []
    while url:
        req = urllib.request.Request(url, headers={
            "Authorization": _netbox_auth_header(token),
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:  # nosonar: python:S5332 -- internal infra_seg HTTP, same as netbox-populate
            payload = json.load(resp)
        results.extend(payload.get("results", []))
        url = payload.get("next")
    return results


def fetch_sources(base_url, token):
    contexts = netbox_get_all(base_url, token, "/extras/config-contexts/", {"name": THREAT_MODEL_CONTEXT_NAME})
    if not contexts:
        raise RuntimeError(f"NetBox config context {THREAT_MODEL_CONTEXT_NAME!r} not found")
    return {
        "model": contexts[0].get("data") or {},
        "vms": netbox_get_all(base_url, token, "/virtualization/virtual-machines/"),
        "services": netbox_get_all(base_url, token, "/ipam/services/"),
        "prefixes": netbox_get_all(base_url, token, "/ipam/prefixes/"),
        "vlans": netbox_get_all(base_url, token, "/ipam/vlans/"),
    }


def neo4j_commit(neo4j_url, user, password, database, statements):
    url = f"{neo4j_url.rstrip('/')}/db/{database}/tx/commit"
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=json.dumps({"statements": statements}).encode(),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # nosonar: python:S5332 -- loopback to the local Neo4j container
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(f"Neo4j rejected the import: {payload['errors']}")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Rebuild the homelab threat-model graph in Neo4j from NetBox")
    parser.add_argument("--dry-run", action="store_true", help="Fetch from NetBox and print a graph summary; don't write Neo4j")
    args = parser.parse_args()

    netbox_url = os.environ["NETBOX_URL"]
    netbox_token = os.environ["NETBOX_TOKEN"]
    sources = fetch_sources(netbox_url, netbox_token)
    graph = build_graph(**sources)
    summary = graph.summary()

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return 0

    run_id = str(uuid.uuid4())
    neo4j = (
        os.environ.get("NEO4J_URL", "http://127.0.0.1:7474"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ["NEO4J_PASSWORD"],
        os.environ.get("NEO4J_DATABASE", "neo4j"),
    )
    neo4j_commit(*neo4j, SCHEMA_STATEMENTS)
    neo4j_commit(*neo4j, build_statements(graph, run_id))
    print(json.dumps({"run": run_id, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
