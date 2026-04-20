"""Tests for the Traefik dynamic config renderer."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "docs" / "provisioning-refactor" / "fixtures"
VALID_DIR = FIXTURES_DIR / "valid"
RENDER_MODULE_PATH = Path(__file__).resolve().parent / "render-edge-traefik.py"
SPEC = importlib.util.spec_from_file_location("render_edge_traefik", RENDER_MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

render_traefik_dry_run = MODULE.render_traefik_dry_run


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


if __name__ == "__main__":
    unittest.main()
