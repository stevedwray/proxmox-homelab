#!/usr/bin/env python3
"""Build a self-contained data-flow graph view from a Neo4j export.

    build_graph_view.py graph-export.json graph-view.html

The export is {"nodes": [[key, kind, name, zone, classification, trust_level,
status, cluster, node, protocol, ports, address, vid, tier]...],
"rels": [[from, to, type, protocol, port, auth_kind, encrypted, crosses_zone,
from_zone, to_zone, classification, trust_boundary, flow_type]...]}.
"""
import collections
import datetime
import json
import pathlib
import sys

src, out = sys.argv[1], sys.argv[2]
raw = open(src).read()
d = json.loads(raw[raw.index('{"nodes"'):])

N = {}
for n in d["nodes"]:
    N[n[0]] = dict(key=n[0], kind=n[1], name=n[2], zone=n[3], cls=n[4], trust=n[5], status=n[6],
                   cluster=n[7], node=n[8], ports=n[10], addr=n[11], vid=n[12], tier=n[13])
R = [dict(a=r[0], b=r[1], t=r[2], proto=r[3], port=r[4], auth=r[5], enc=r[6], cross=r[7],
          fz=r[8], tz=r[9], cls=r[10], tb=r[11], ft=r[12]) for r in d["rels"]]

KEEP = {"Process", "DataStore", "ExternalEntity", "Zone", "Unresolved"}

# Inventory detail hung on each Process: its VM, IP and service ports.
vm_of = {r["a"]: r["b"] for r in R if r["t"] == "RUNS_ON"}
ip_of = {r["a"]: r["b"] for r in R if r["t"] == "HAS_IP"}
svcs = collections.defaultdict(list)
for r in R:
    if r["t"] == "EXPOSES":
        s = N[r["b"]]
        svcs[r["a"]].append(f'{s["ports"][0] if s["ports"] else "?"}')


def label(n):
    name = n["name"] or n["key"]
    return name if len(name) <= 24 else name[:23] + "…"


def risky(r):
    return r["cross"] is True and r["enc"] is False and r["auth"] in ("none", "unknown")


nodes = []
for k, n in N.items():
    if n["kind"] not in KEEP:
        continue
    item = dict(id=k, kind=n["kind"], label=label(n), name=n["name"] or k, zone=n["zone"],
                cls=n["cls"], trust=n["trust"], tier=n["tier"])
    if n["kind"] == "Process":
        vm = N.get(vm_of.get(k))
        if vm:
            item["vm"] = dict(name=vm["name"], node=vm["node"], state=vm["status"], cluster=vm["cluster"],
                              ip=(N.get(ip_of.get(vm["key"])) or {}).get("addr"),
                              ports=sorted(set(svcs.get(vm["key"], [])), key=lambda p: int(p) if p.isdigit() else 0)[:14])
    nodes.append(item)
ids = {n["id"] for n in nodes}

# Merge parallel flows between the same ordered pair into one visual edge.
pairs = collections.OrderedDict()
links = []
for r in R:
    if r["a"] not in ids or r["b"] not in ids:
        continue
    if r["t"] == "FLOWS_TO":
        f = dict(proto=r["proto"], port=r["port"], auth=r["auth"], enc=r["enc"], cross=r["cross"],
                 fz=r["fz"], tz=r["tz"], cls=r["cls"], tb=r["tb"], zp=r["ft"] == "zone-policy", risky=risky(r))
        pairs.setdefault((r["a"], r["b"]), []).append(f)
    elif r["t"] in ("IN_ZONE", "HOSTED_ON"):
        links.append(dict(s=r["a"], t=r["b"], type=r["t"]))
for (a, b), fl in pairs.items():
    links.append(dict(s=a, t=b, type="FLOW", flows=fl, risky=any(f["risky"] for f in fl),
                      zp=all(f["zp"] for f in fl)))

all_flows = [f for (a, b), fl in pairs.items() for f in fl]
stats = dict(processes=sum(1 for n in nodes if n["kind"] == "Process"),
             flows=len([r for r in R if r["t"] == "FLOWS_TO"]),
             risky=sum(1 for f in all_flows if f["risky"]),
             unknown=sum(1 for f in all_flows if f["auth"] == "unknown"),
             vms=sum(1 for n in N.values() if n["kind"] == "VirtualMachine"),
             services=sum(1 for n in N.values() if n["kind"] == "Service"),
             unresolved=sum(1 for n in nodes if n["kind"] == "Unresolved"))
data = dict(nodes=nodes, links=links, stats=stats,
            generated=datetime.date.today().isoformat())

tpl = (pathlib.Path(__file__).resolve().parent / "graph_view.template.html").read_text()
# "</" escaped so no string from the model can close the page's <script> block
open(out, "w").write(tpl.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/")))
print(f"nodes={len(nodes)} links={len(links)} {stats}")
