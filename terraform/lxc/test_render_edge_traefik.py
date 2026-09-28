"""Tests for the Traefik dynamic config renderer."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
import os

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "docs" / "provisioning-refactor" / "fixtures"
VALID_DIR = FIXTURES_DIR / "valid"
RENDER_MODULE_PATH = Path(__file__).resolve().parent / "render-edge-traefik.py"
SPEC = importlib.util.spec_from_file_location("render_edge_traefik", RENDER_MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
os.environ["LAB_IP_PROXY"] = "10.57.2.10"
SPEC.loader.exec_module(MODULE)

render_traefik_dry_run = MODULE.render_traefik_dry_run
render_pangolin_traefik_dry_run = MODULE.render_pangolin_traefik_dry_run


class TestRenderEdgeTraefik(unittest.TestCase):
    def setUp(self) -> None:
        self.legacy_playbook = (
            REPO_ROOT / "terraform" / "lxc" / "ansible" / "playbooks" / "deploy-proxy-stack.yml"
        )

    def _write_fixture_with_replacement(
        self,
        fixture_name: str,
        replacement_hosts: list[str],
    ) -> Path:
        fixture = VALID_DIR / fixture_name
        with fixture.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)

        document["intendedReplacement"] = [{"hostname": host} for host in replacement_hosts]
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            yaml.safe_dump(document, handle, sort_keys=False)
            return Path(handle.name)

    def test_fails_when_legacy_inventory_has_issues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = Path(tmpdir) / "deploy-proxy-stack.yml"
            legacy_path.write_text(
                """http:
  routers:
    bad-router:
      rule: \"Host(bad.lab.gibbsgreatly.xyz)\"
""",
                encoding="utf-8",
            )

            result = render_traefik_dry_run([VALID_DIR / "authentik.yaml"], legacy_path)

        self.assertFalse(result.ok)
        self.assertIn("LRI101", {issue.code for issue in result.issues})

    def test_fails_collision_without_intended_replacement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = Path(tmpdir) / "deploy-proxy-stack.yml"
            legacy_path.write_text(
                """http:
  routers:
    traefik-dashboard:
      rule: \"Host(`traefik.lab.gibbsgreatly.xyz`)\"
""",
                encoding="utf-8",
            )

            result = render_traefik_dry_run([VALID_DIR / "traefik-dashboard.yaml"], legacy_path)

        self.assertFalse(result.ok)
        self.assertIn("RTR200", {issue.code for issue in result.issues})
        self.assertTrue(any(issue.host == "traefik.lab.gibbsgreatly.xyz" for issue in result.issues))

    def test_allows_exact_intended_replacement(self):
        manifest_path = self._write_fixture_with_replacement(
            fixture_name="traefik-dashboard.yaml",
            replacement_hosts=["traefik.lab.gibbsgreatly.xyz"],
        )
        try:
            result = render_traefik_dry_run([manifest_path], self.legacy_playbook)
        finally:
            manifest_path.unlink(missing_ok=True)

        self.assertTrue(result.ok)
        self.assertEqual(1, len(result.rendered))

    def test_fails_when_multiple_intended_replacements_are_set(self):
        manifest_path = self._write_fixture_with_replacement(
            fixture_name="traefik-dashboard.yaml",
            replacement_hosts=[
                "traefik.lab.gibbsgreatly.xyz",
                "grafana.lab.gibbsgreatly.xyz",
            ],
        )
        try:
            result = render_traefik_dry_run([manifest_path], self.legacy_playbook)
        finally:
            manifest_path.unlink(missing_ok=True)

        self.assertFalse(result.ok)
        self.assertIn("RTR201", {issue.code for issue in result.issues})

    def test_fails_when_intended_replacement_mismatch(self):
        manifest_path = self._write_fixture_with_replacement(
            fixture_name="traefik-dashboard.yaml",
            replacement_hosts=["wrong.lab.gibbsgreatly.xyz"],
        )
        try:
            result = render_traefik_dry_run([manifest_path], self.legacy_playbook)
        finally:
            manifest_path.unlink(missing_ok=True)

        self.assertFalse(result.ok)
        self.assertIn("RTR202", {issue.code for issue in result.issues})

    def test_traefik_service_backend_renders_without_load_balancer(self):
        manifest_path = self._write_fixture_with_replacement(
            fixture_name="traefik-dashboard.yaml",
            replacement_hosts=["traefik.lab.gibbsgreatly.xyz"],
        )
        try:
            result = render_traefik_dry_run([manifest_path], self.legacy_playbook)
        finally:
            manifest_path.unlink(missing_ok=True)

        self.assertTrue(result.ok)
        stack = result.rendered[0]
        routers = stack.config["http"]["routers"]
        self.assertEqual("api@internal", routers["traefik-dashboard"]["service"])
        self.assertEqual(["authentik"], routers["traefik-dashboard"]["middlewares"])
        self.assertNotIn("services", stack.config["http"])

    def test_pangolin_renderer_emits_only_explicit_public_route(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write(
                """apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: nextcloud-stack-edge
  stack: nextcloud-stack
spec:
  routes:
    - name: nextcloud
      host: nextcloud.lab.gibbsgreatly.xyz
      pangolin:
        public_host: nextcloud.pan.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.120.10:8080
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: oidc
"""
            )
            manifest_path = Path(handle.name)
        try:
            lan_result = render_traefik_dry_run([manifest_path], self.legacy_playbook)
            pangolin_result = render_pangolin_traefik_dry_run([manifest_path])
        finally:
            manifest_path.unlink(missing_ok=True)

        self.assertTrue(lan_result.ok)
        self.assertEqual("Host(`nextcloud.lab.gibbsgreatly.xyz`)", lan_result.rendered[0].config["http"]["routers"]["nextcloud"]["rule"])
        self.assertTrue(pangolin_result.ok)
        self.assertEqual(1, len(pangolin_result.rendered))
        self.assertEqual(
            "Host(`nextcloud.pan.gibbsgreatly.xyz`)",
            pangolin_result.rendered[0].config["http"]["routers"]["nextcloud"]["rule"],
        )

    def test_pangolin_renderer_emits_explicit_client_only_route(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write(
                """apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-edge
  stack: authentik-stack
spec:
  routes:
    - name: authentik
      host: authentik.lab.gibbsgreatly.xyz
      pangolin:
        private_host: true
      backend:
        type: url
        url: http://10.57.20.10:9000
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: none
"""
            )
            manifest_path = Path(handle.name)
        try:
            result = render_pangolin_traefik_dry_run([manifest_path])
        finally:
            manifest_path.unlink(missing_ok=True)

        self.assertTrue(result.ok)
        routers = result.rendered[0].config["http"]["routers"]
        self.assertEqual(
            "Host(`authentik.lab.gibbsgreatly.xyz`)",
            routers["authentik-private"]["rule"],
        )

    def test_write_rendered_files_removes_stale_orphaned_stack_file(self):
        # Real bug, found live 2026-09-25: authentik-stack's route was
        # removed from EdgeManifest, but its previously-rendered
        # authentik-stack.yml was never deleted from the generated
        # directory, so deploy-pangolin-proxy.yml's own remove-then-
        # republish step (which only looks at what's in this directory)
        # would have faithfully recreated the live route on the very next
        # redeploy.
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            stale_path = output_dir / "authentik-stack.yml"
            stale_path.write_text("http:\n  routers: {}\n", encoding="utf-8")

            rendered = (
                MODULE.RenderedStack(
                    stack="nextcloud-stack",
                    manifest="nextcloud.yaml",
                    config={"http": {"routers": {}}},
                ),
            )
            written = MODULE.write_rendered_files(rendered, output_dir)

            self.assertFalse(stale_path.exists())
            self.assertEqual([output_dir / "nextcloud-stack.yml"], written)
            self.assertEqual(["nextcloud-stack.yml"], [p.name for p in output_dir.glob("*.yml")])


if __name__ == "__main__":
    unittest.main()
