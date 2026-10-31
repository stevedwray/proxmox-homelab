"""Asset facts on process nodes: platforms, base images, container privilege, exposure, dependencies.

They are derived from what stack.yaml, docker-compose.yml and edge.yaml already declare, so a later analysis
(threat-informed defence against MITRE ATT&CK) can start from the model instead of from hand-written claims.
"""

import tempfile
import unittest
from pathlib import Path

import yaml

import flows


class ImageRepo(unittest.TestCase):
    def test_every_image_form_used_in_the_repo(self):
        cases = {
            "${REGISTRY_HOST}/dockerhub/library/postgres:16-alpine": "postgres",
            "${REGISTRY_HOST}/dockerhub/library/redis:alpine": "redis",
            "${REGISTRY_HOST}/ghcr/goauthentik/server:${AUTHENTIK_IMAGE_VERSION:-2026.2.4}": "goauthentik/server",
            "${REGISTRY_HOST}/ghcr/google/cadvisor:v0.60.5": "google/cadvisor",
            "${REGISTRY_HOST}/dockerhub/tecnativa/docker-socket-proxy:latest": "tecnativa/docker-socket-proxy",
            "harbor.lab.example.com/dockerhub/library/nginx:1.27-alpine": "nginx",
            "ghcr.io/goauthentik/server@sha256:abc": "goauthentik/server",
            "nginx": "nginx",
        }
        for image, expected in cases.items():
            self.assertEqual(flows._image_repo(image), expected, image)

    def test_non_images_are_none(self):
        for bad in (None, "", 42):
            self.assertIsNone(flows._image_repo(bad))


class ComposeFacts(unittest.TestCase):
    def test_privilege_facts_are_counted_per_container(self):
        f = flows._compose_facts({"services": {
            "a": {"image": "x/a:1", "privileged": True, "user": "1000", "cap_drop": ["ALL"], "read_only": True},
            "b": {"image": "x/b:1", "network_mode": "host", "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"]},
            "c": {"image": "x/a:2"},
        }})
        self.assertEqual((f["containers"], f["containers_privileged"], f["containers_host_network"],
                          f["containers_docker_sock"], f["containers_user_set"], f["containers_cap_drop"],
                          f["containers_read_only"]), (3, 1, 1, 1, 1, 1, 1))
        self.assertEqual(f["technologies"], ["x/a", "x/b"])

    def test_no_compose_means_no_container_facts(self):
        self.assertEqual(flows._compose_facts(None)["containers"], 0)


def _write(root, name, stack, compose=None, edge=None):
    d = Path(root) / name
    d.mkdir()
    (d / "stack.yaml").write_text(yaml.safe_dump(stack))
    if compose is not None:
        (d / "docker-compose.yml").write_text(yaml.safe_dump(compose))
    if edge is not None:
        (d / "edge.yaml").write_text(yaml.safe_dump(edge))


class DerivedProcessFacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = cls._tmp.name
        net = {"zone": "mgmt_seg"}
        _write(root, "proxy-stack", {"hostname": "proxy-stack", "deployment_tier": "platform", "network": net})
        _write(root, "web-stack", {"hostname": "web-stack", "deployment_tier": "platform", "network": net,
                                   "depends_on": ["proxy-stack", "not-modelled-stack"],
                                   "enable_docker_socket_proxy": True, "docker_socket_proxy_listen_port": 2375,
                                   "host_bind_mounts": [{"a": 1}, {"b": 2}], "device_passthrough": [{"x": 1}]},
               compose={"services": {"app": {"image": "${REGISTRY_HOST}/dockerhub/library/nginx:1"}}},
               edge={"spec": {"routes": [{"name": "w", "host": "w.lab", "backend": {"type": "url", "url": "http://10.0.0.9:80"},
                                          "auth": {"mode": "forwardAuth"}},
                                         {"name": "i", "host": "i.lab", "backend": {"type": "traefikService"}, "auth": {"mode": "none"}}]}})
        cls.model = flows.build_threat_model(env="pve", stacks_dir=root)
        cls.by = {p["stack"]: p for p in cls.model["processes"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_docker_hosts_get_the_containers_platform(self):
        self.assertEqual(self.by["web-stack"]["platforms"], ["Containers", "Linux"])
        self.assertEqual(self.by["proxy-stack"]["platforms"], ["Linux"])

    def test_images_and_container_facts(self):
        web = self.by["web-stack"]
        self.assertEqual((web["technologies"], web["containers"]), (["nginx"], 1))
        self.assertNotIn("containers", self.by["proxy-stack"])

    def test_exposure_from_the_edge_manifest_ignoring_internal_routes(self):
        self.assertTrue(self.by["web-stack"]["routed"])
        self.assertEqual(self.by["web-stack"]["route_auth_modes"], ["forwardAuth"])
        self.assertFalse(self.by["proxy-stack"]["routed"])
        self.assertNotIn("route_auth_modes", self.by["proxy-stack"])

    def test_dependencies_become_process_ids_and_drop_unmodelled_stacks(self):
        self.assertEqual(self.by["web-stack"]["depends_on"], ["p-proxy"])
        self.assertNotIn("depends_on", self.by["proxy-stack"])
        self.assertNotIn("_depends_on_stacks", self.by["web-stack"])

    def test_socket_proxy_and_host_access_facts(self):
        web = self.by["web-stack"]
        self.assertEqual((web["docker_socket_proxy"], web["docker_socket_proxy_port"]), (True, 2375))
        self.assertEqual((web["host_bind_mounts"], web["device_passthrough"]), (2, True))
        self.assertNotIn("docker_socket_proxy", self.by["proxy-stack"])


class RealModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = flows.build_threat_model(env="pve")
        cls.procs = {p["id"]: p for p in cls.model["processes"]}

    def test_every_process_has_platforms_and_valid_dependencies(self):
        for p in self.procs.values():
            self.assertTrue(p["platforms"], p["id"])
            for dep in p.get("depends_on", []):
                self.assertIn(dep, self.procs, f"{p['id']} depends on an unmodelled {dep}")

    def test_values_stay_simple_enough_for_the_graph(self):
        for p in self.procs.values():
            for key, value in p.items():
                if key == "provides":
                    continue
                self.assertIsInstance(value, (str, int, float, bool, list, type(None)), f"{p['id']}.{key}")

    def test_authentik_matches_what_its_files_say(self):
        a = self.procs["p-authentik"]
        self.assertIn("Containers", a["platforms"])
        self.assertTrue({"goauthentik/server", "postgres"} <= set(a["technologies"]))
        self.assertTrue({"p-harbor", "p-step-ca"} <= set(a["depends_on"]))
        self.assertTrue(a["docker_socket_proxy"])


if __name__ == "__main__":
    unittest.main()
