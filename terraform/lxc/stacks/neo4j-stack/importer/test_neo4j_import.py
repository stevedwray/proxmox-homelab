"""Unit tests for neo4j_import graph building and Cypher generation."""

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "netbox-stack" / "integrations"))

import flows  # noqa: E402
import neo4j_import  # noqa: E402

MODEL = {
    "trust_boundaries": [{"id": "tb-mgmt-to-infra", "name": "mgmt_seg → infra_seg"}],
    "external_entities": [{"id": "ee-lan-user", "name": "LAN User", "trust_level": "medium"}],
    "processes": [
        {"id": "p-netbox", "name": "netbox-stack", "zone": "infra_seg", "vmid": 40012,
         "provides": [{"service": "netbox-http", "port": 8080, "protocol": "tcp"}]},
        {"id": "p-authentik", "name": "authentik-stack", "zone": "mgmt_seg"},
    ],
    "data_stores": [{"id": "ds-netbox-db", "name": "NetBox PostgreSQL", "host": "p-netbox", "encryption_at_rest": False}],
    "data_flows": [
        {"id": "df-a", "from": "p-authentik", "to": "p-netbox", "port": 8080, "ports": [8080, "8443"],
         "trust_boundary_crossing": "tb-mgmt-to-infra", "auth": None},
        {"id": "df-zone-policy-00", "from": "zone:build_seg", "to": "zone:mgmt_seg", "ports": []},
        {"id": "df-ghost", "from": "ee-lan-user", "to": "p-missing"},
    ],
}
VMS = [
    {"id": 7, "name": "netbox-stack", "cluster": {"name": "pve-cluster"}, "status": {"value": "active"},
     "primary_ip4": {"address": "192.168.40.12/24"}, "tags": [{"name": "netbox"}]},
    {"id": 8, "name": "orphan-lxc", "cluster": {"name": "pve-cluster"}, "primary_ip4": None, "tags": []},
]
SERVICES = [
    {"id": 3, "name": "netbox-http", "protocol": {"value": "tcp"}, "ports": [8080],
     "parent_object_type": "virtualization.virtualmachine", "parent_object_id": 7},
    {"id": 4, "name": "winbox", "protocol": {"value": "tcp"}, "ports": [8291],
     "parent_object_type": "dcim.device", "parent_object_id": 1},
]
PREFIXES = [
    {"prefix": "192.168.0.0/16", "vlan": None},
    {"prefix": "192.168.40.0/24", "vlan": {"id": 40}, "status": {"value": "active"}},
]
VLANS = [{"id": 40, "vid": 40, "name": "infra", "group": {"name": "hap-vlans"}}]


def _rels(graph, rel_type):
    return {(src, dst) for (t, src, dst, _), _p in graph.rels.items() if t == rel_type}


class BuildGraphTest(unittest.TestCase):
    def setUp(self):
        self.graph = neo4j_import.build_graph(MODEL, VMS, SERVICES, PREFIXES, VLANS)

    def test_threat_model_nodes_and_flows(self):
        self.assertEqual(self.graph.nodes["p-netbox"][0], "Process")
        self.assertEqual(self.graph.nodes["p-netbox"][1]["provides"], ["netbox-http/8080/tcp"])
        self.assertIn(("p-authentik", "p-netbox"), _rels(self.graph, "FLOWS_TO"))
        self.assertIn(("zone:build_seg", "zone:mgmt_seg"), _rels(self.graph, "FLOWS_TO"))
        self.assertIn(("ds-netbox-db", "p-netbox"), _rels(self.graph, "HOSTED_ON"))
        self.assertIn(("p-netbox", "zone:infra_seg"), _rels(self.graph, "IN_ZONE"))

    def test_unknown_flow_endpoint_becomes_unresolved_node(self):
        self.assertEqual(self.graph.nodes["p-missing"][0], "Unresolved")
        self.assertIn(("ee-lan-user", "p-missing"), _rels(self.graph, "FLOWS_TO"))

    def test_duplicate_flow_ids_kept_as_separate_relationships(self):
        model = {"processes": [{"id": "p-proxy"}, {"id": "p-ai"}], "data_flows": [
            {"id": "df-traefik-to-ai", "from": "p-proxy", "to": "p-ai", "port": 8081},
            {"id": "df-traefik-to-ai", "from": "p-proxy", "to": "p-ai", "port": 8082},
        ]}
        graph = neo4j_import.build_graph(model, [], [], [], [])
        keys = sorted(k for (t, _s, _d, k) in graph.rels if t == "FLOWS_TO")
        self.assertEqual(keys, ["df-traefik-to-ai", "df-traefik-to-ai#2"])

    def test_flow_props_are_neo4j_safe(self):
        props = next(p for (t, *_rest, k), p in self.graph.rels.items() if k == "df-a")
        self.assertEqual(props["ports"], ["8080", "8443"])  # mixed types coerced to strings
        self.assertNotIn("auth", props)  # None dropped
        self.assertEqual(props["trust_boundary_crossing"], "tb-mgmt-to-infra")

    def test_inventory_joins(self):
        self.assertIn(("p-netbox", "vm:7"), _rels(self.graph, "RUNS_ON"))
        self.assertIn(("vm:7", "ip:192.168.40.12/24"), _rels(self.graph, "HAS_IP"))
        # longest prefix only, not the covering /16
        self.assertEqual(_rels(self.graph, "IN_PREFIX"), {("ip:192.168.40.12/24", "prefix:192.168.40.0/24")})
        self.assertIn(("prefix:192.168.40.0/24", "vlan:40"), _rels(self.graph, "ON_VLAN"))
        self.assertEqual(_rels(self.graph, "EXPOSES"), {("vm:7", "svc:3")})  # device service skipped
        self.assertNotIn(("p-netbox", "vm:8"), _rels(self.graph, "RUNS_ON"))

    def test_real_derived_model_builds(self):
        model = flows.build_threat_model(env="pve")
        graph = neo4j_import.build_graph(model, [], [], [], [])
        summary = graph.summary()
        self.assertGreater(summary["nodes"]["Process"], 0)
        self.assertEqual(summary["relationships"]["FLOWS_TO"], len(model["data_flows"]))
        for _label, props in graph.nodes.values():
            for value in props.values():
                self.assertIsInstance(value, (str, int, float, bool, list))


class RunsOnJoinTest(unittest.TestCase):
    """NetBox VM names are '<stack>@<node>'; the join must strip the node."""

    @staticmethod
    def _vm(vm_id, name, cluster):
        return {"id": vm_id, "name": name, "cluster": {"name": cluster}, "primary_ip4": None, "tags": []}

    def _runs_on(self, vms, **kwargs):
        graph = neo4j_import.build_graph(MODEL, vms, [], [], [], **kwargs)
        return _rels(graph, "RUNS_ON")

    def test_node_suffix_is_stripped(self):
        vms = [self._vm(1, "netbox-stack@pve", "pve-cluster")]
        self.assertEqual(self._runs_on(vms), {("p-netbox", "vm:1")})

    def test_home_cluster_vm_wins_over_other_node(self):
        vms = [self._vm(1, "netbox-stack@pve-tiny", "pve-tiny-cluster"),
               self._vm(2, "netbox-stack@pve", "pve-cluster")]
        self.assertEqual(self._runs_on(vms), {("p-netbox", "vm:2")})

    def test_only_vm_on_another_node_is_accepted(self):
        # a stack that moved nodes still has exactly one VM
        vms = [self._vm(1, "netbox-stack@pve-tiny", "pve-tiny-cluster")]
        self.assertEqual(self._runs_on(vms), {("p-netbox", "vm:1")})

    def test_ambiguous_vms_none_at_home_gets_no_edge(self):
        vms = [self._vm(1, "netbox-stack@pve-tiny", "pve-tiny-cluster"),
               self._vm(2, "netbox-stack@pve-test", "pve-test-cluster")]
        self.assertEqual(self._runs_on(vms), set())

    def test_home_cluster_is_configurable(self):
        vms = [self._vm(1, "netbox-stack@pve-tiny", "pve-tiny-cluster"),
               self._vm(2, "netbox-stack@pve", "pve-cluster")]
        self.assertEqual(self._runs_on(vms, home_cluster="pve-tiny-cluster"), {("p-netbox", "vm:1")})

    def test_vm_without_a_process_is_not_linked(self):
        vms = [self._vm(1, "orphan-lxc@pve", "pve-cluster")]
        self.assertEqual(self._runs_on(vms), set())


class DerivedMetadataTest(unittest.TestCase):
    """Queryable forms derived from fields the model and NetBox already carry."""

    @staticmethod
    def _flow_props(graph, src, dst):
        return next(p for (t, s_, d, _), p in graph.rels.items() if t == "FLOWS_TO" and (s_, d) == (src, dst))

    def test_auth_kind_distinguishes_unknown_from_none(self):
        cases = {
            None: "unknown", "": "unknown", "none": "none",
            "forward-auth (Authentik per-request check)": "forward-auth",
            "oidc (Authentik)": "oidc", "acme-account-key": "token",
            "runner-registration-token": "token", "basic": "other",
        }
        for raw, expected in cases.items():
            self.assertEqual(neo4j_import._auth_kind(raw), expected, raw)

    def test_encrypted_is_tri_state(self):
        self.assertIs(neo4j_import._encrypted("tls"), True)
        self.assertIs(neo4j_import._encrypted("none"), False)
        self.assertIsNone(neo4j_import._encrypted(None))

    def test_flow_zone_and_crossing_props(self):
        graph = neo4j_import.build_graph(MODEL, VMS, SERVICES, PREFIXES, VLANS)
        cross = self._flow_props(graph, "p-authentik", "p-netbox")
        self.assertEqual((cross["from_zone"], cross["to_zone"], cross["crosses_zone"]), ("mgmt_seg", "infra_seg", True))
        self.assertEqual(cross["auth_kind"], "unknown")
        self.assertNotIn("encrypted", cross)  # transport not stated -> omitted, not False
        policy = self._flow_props(graph, "zone:build_seg", "zone:mgmt_seg")
        self.assertEqual((policy["from_zone"], policy["to_zone"], policy["crosses_zone"]), ("build_seg", "mgmt_seg", True))
        ghost = self._flow_props(graph, "ee-lan-user", "p-missing")
        self.assertEqual(ghost["from_zone"], "external")
        self.assertNotIn("to_zone", ghost)  # unresolved endpoint: zone unknown
        self.assertNotIn("crosses_zone", ghost)

    def test_same_zone_flow_does_not_cross(self):
        model = {"processes": [{"id": "p-a", "zone": "infra_seg"}, {"id": "p-b", "zone": "infra_seg"}],
                 "data_flows": [{"id": "df-x", "from": "p-a", "to": "p-b", "transport_security": "tls", "auth": "oidc (Authentik)"}]}
        graph = neo4j_import.build_graph(model, [], [], [], [])
        props = self._flow_props(graph, "p-a", "p-b")
        self.assertIs(props["crosses_zone"], False)
        self.assertIs(props["encrypted"], True)
        self.assertEqual(props["auth_kind"], "oidc")

    def test_model_supplied_value_is_not_overridden(self):
        model = {"processes": [{"id": "p-a", "zone": "x"}, {"id": "p-b", "zone": "y"}],
                 "data_flows": [{"id": "df-x", "from": "p-a", "to": "p-b", "auth_kind": "custom"}]}
        graph = neo4j_import.build_graph(model, [], [], [], [])
        self.assertEqual(self._flow_props(graph, "p-a", "p-b")["auth_kind"], "custom")

    def test_vm_service_and_ip_props(self):
        vms = [{"id": 1, "name": "netbox-stack@pve", "cluster": {"name": "pve-cluster"}, "disk": 8,
                "platform": {"name": "Debian 13"},
                "description": "Managed by Terraform\n [Status: running] [Source name: netbox-stack]",
                "primary_ip4": {"address": "192.168.40.12/24"}, "tags": []},
               {"id": 2, "name": "ext@pve", "cluster": {"name": "pve-cluster"},
                "primary_ip4": {"address": "8.8.8.8/32"}, "tags": []}]
        services = [{"id": 5, "name": "x-25565", "protocol": {"value": "tcp"}, "ports": [25565],
                     "description": "gaming-stack-lab | last-seen=2026-10-24T11:31:53Z",
                     "parent_object_type": "virtualization.virtualmachine", "parent_object_id": 1},
                    {"id": 6, "name": "y", "protocol": {"value": "tcp"}, "ports": [22], "description": "no timestamp",
                     "parent_object_type": "virtualization.virtualmachine", "parent_object_id": 1}]
        graph = neo4j_import.build_graph({}, vms, services, [], [])
        vm = graph.nodes["vm:1"][1]
        self.assertEqual((vm["node"], vm["observed_state"], vm["disk"], vm["platform"]),
                         ("pve", "running", 8, "Debian 13"))
        self.assertNotIn("observed_state", graph.nodes["vm:2"][1])
        self.assertEqual(graph.nodes["svc:5"][1]["last_seen"], "2026-10-24T11:31:53Z")
        self.assertNotIn("last_seen", graph.nodes["svc:6"][1])
        self.assertEqual(graph.nodes["ip:192.168.40.12/24"][1]["scope"], "private")
        self.assertEqual(graph.nodes["ip:8.8.8.8/32"][1]["scope"], "public")

    def test_runs_on_records_how_it_matched(self):
        def vm(i, name, cluster):
            return {"id": i, "name": name, "cluster": {"name": cluster}, "primary_ip4": None, "tags": []}
        graph = neo4j_import.build_graph(MODEL, [vm(1, "netbox-stack@pve", "pve-cluster")], [], [], [])
        self.assertEqual(next(p for (t, *_), p in graph.rels.items() if t == "RUNS_ON")["matched_by"], "home-cluster")
        graph = neo4j_import.build_graph(MODEL, [vm(1, "netbox-stack@pve-tiny", "pve-tiny-cluster")], [], [], [])
        self.assertEqual(next(p for (t, *_), p in graph.rels.items() if t == "RUNS_ON")["matched_by"], "only-vm")


class BuildStatementsTest(unittest.TestCase):
    def test_statements_use_only_whitelisted_labels_and_prune_last(self):
        graph = neo4j_import.build_graph(MODEL, VMS, SERVICES, PREFIXES, VLANS)
        statements = neo4j_import.build_statements(graph, "run-1")
        texts = [s["statement"] for s in statements]
        self.assertTrue(all("CONSTRAINT" not in t for t in texts))  # schema is a separate commit
        self.assertIn("DETACH DELETE", texts[-1])
        self.assertIn("DELETE r", texts[-2])
        merged_keys = {row["key"] for s in statements for row in s.get("parameters", {}).get("rows", []) if "props" in row and "from" not in row}
        self.assertEqual(merged_keys, set(graph.nodes))
        for s in statements:
            self.assertEqual(s.get("parameters", {}).get("run", "run-1"), "run-1")

    def test_unknown_label_rejected(self):
        with self.assertRaises(ValueError):
            neo4j_import.Graph().node("Threat", "x")

    def test_netbox_auth_header(self):
        self.assertEqual(neo4j_import._netbox_auth_header("nbt_abc.def"), "Bearer nbt_abc.def")
        self.assertEqual(neo4j_import._netbox_auth_header("0123abcd"), "Token 0123abcd")


if __name__ == "__main__":
    unittest.main()
