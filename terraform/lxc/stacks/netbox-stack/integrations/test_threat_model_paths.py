"""The derived threat model must let a request be traced from a user to a service.

Two guards: every flow endpoint resolves to a node the model defines, and the
LAN user reaches an app through Traefik, with Authentik's consumers visible.
"""

import tempfile
import unittest
from pathlib import Path

import yaml

import flows


def _write_stack(root, name, stack, edge=None):
    d = Path(root) / name
    d.mkdir()
    (d / "stack.yaml").write_text(yaml.safe_dump(stack))
    if edge is not None:
        (d / "edge.yaml").write_text(yaml.safe_dump(edge))


def _edge(stack, *routes):
    return {"spec": {"routes": [
        {"name": n, "host": f"{n}.lab", "backend": {"type": "url", "url": f"http://10.0.0.9:{p}"},
         "auth": {"mode": mode}} for n, p, mode in routes]}, "metadata": {"stack": stack}}


def _reachable(model, src, dst):
    adj = {}
    for f in model["data_flows"]:
        adj.setdefault(f["from"], set()).add(f["to"])
    seen, todo = {src}, [src]
    while todo:
        for nxt in adj.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return dst in seen


class FixtureModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = cls._tmp.name
        net = {"zone": "edge_seg"}
        _write_stack(root, "proxy-stack", {"hostname": "proxy-stack", "deployment_tier": "platform", "network": net})
        _write_stack(root, "authentik-stack", {"hostname": "authentik-stack", "deployment_tier": "platform",
                                               "network": {"zone": "mgmt_seg"}},
                     _edge("authentik-stack", ("authentik", 9000, "none")))
        # apps tier: used to be dropped, leaving its route flow dangling
        _write_stack(root, "media-lab", {"hostname": "media-lab", "deployment_tier": "apps",
                                         "network": {"zone": "media_seg"}},
                     _edge("media-lab", ("jellyfin", 8096, "oidc")))
        # no tier and no zone, but it has a route, so it still needs a process
        _write_stack(root, "legacy-ui", {"hostname": "legacy-ui"}, _edge("legacy-ui", ("legacy", 8080, "forwardAuth")))
        _write_stack(root, "scratch", {"hostname": "scratch", "deployment_tier": "test", "network": net})
        cls.model = flows.build_threat_model(env="pve", stacks_dir=root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_app_tier_and_routed_untiered_stacks_become_processes(self):
        stacks = {p["stack"] for p in self.model["processes"]}
        self.assertTrue({"media-lab", "legacy-ui"} <= stacks)
        self.assertNotIn("scratch", stacks)  # test tier stays out

    def test_oidc_app_gets_a_flow_to_authentik(self):
        dep = [f for f in self.model["data_flows"] if f["id"] == "df-media-lab-oidc-authentik"]
        self.assertEqual(len(dep), 1)
        self.assertEqual((dep[0]["from"], dep[0]["to"]), ("p-media-lab", "p-authentik"))
        self.assertEqual(dep[0]["flow_type"], "auth-dependency")
        self.assertTrue(dep[0]["needs_annotation"])
        self.assertNotIn("port", dep[0])  # not derivable, so not invented

    def test_forward_auth_app_gets_no_per_app_authentik_flow(self):
        ids = {f["id"] for f in self.model["data_flows"]}
        self.assertNotIn("df-legacy-ui-oidc-authentik", ids)

    def test_authentik_does_not_depend_on_itself(self):
        self.assertNotIn("df-authentik-oidc-authentik", {f["id"] for f in self.model["data_flows"]})

    def test_lan_user_reaches_the_app_through_traefik(self):
        self.assertTrue(_reachable(self.model, "ee-lan-user", "p-media-lab"))
        self.assertIn(("p-proxy", "p-media-lab"),
                      {(f["from"], f["to"]) for f in self.model["data_flows"]})


class RealModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = flows.build_threat_model(env="pve")

    def test_every_flow_endpoint_resolves(self):
        known = ({p["id"] for p in self.model["processes"]} | {e["id"] for e in self.model["external_entities"]}
                 | {d["id"] for d in self.model["data_stores"]})
        dangling = sorted({e for f in self.model["data_flows"] for e in (f["from"], f["to"])
                           if e not in known and not str(e).startswith("zone:")})
        self.assertEqual(dangling, [], "flows point at ids no process, entity or store defines")

    def test_static_flows_use_the_real_proxy_id(self):
        ids = {p["id"] for p in self.model["processes"]}
        self.assertIn("p-proxy", ids)
        self.assertNotIn("p-traefik", {e for f in self.model["data_flows"] for e in (f["from"], f["to"])})

    def test_lan_user_reaches_jellyfin_and_authentik_sees_its_consumers(self):
        self.assertTrue(_reachable(self.model, "ee-lan-user", "p-media-stack-lab"))
        into_authentik = {f["from"] for f in self.model["data_flows"] if f["to"] == "p-authentik"}
        self.assertTrue({"p-proxy", "p-media-stack-lab"} <= into_authentik)


if __name__ == "__main__":
    unittest.main()
