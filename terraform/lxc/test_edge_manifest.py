"""Tests for edge manifest discovery and validation."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "docs" / "provisioning-refactor" / "fixtures"
VALID_DIR = FIXTURES_DIR / "valid"
INVALID_DIR = FIXTURES_DIR / "invalid"
MODULE_PATH = Path(__file__).resolve().parent / "edge_manifest.py"
SPEC = importlib.util.spec_from_file_location("edge_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
discover_edge_manifests = MODULE.discover_edge_manifests
extract_legacy_routes = MODULE.extract_legacy_routes
validate_manifests = MODULE.validate_manifests


class TestDiscoverEdgeManifests(unittest.TestCase):
    def test_discovers_only_stacks_edge_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stacks_dir = Path(tmpdir) / "stacks"
            (stacks_dir / "stack-a").mkdir(parents=True)
            (stacks_dir / "stack-b").mkdir(parents=True)
            (stacks_dir / "stack-a" / "edge.yaml").write_text("kind: EdgeManifest\n", encoding="utf-8")
            (stacks_dir / "stack-a" / "not-edge.yaml").write_text("ignored: true\n", encoding="utf-8")
            (stacks_dir / "stack-b" / "edge.yaml").write_text("kind: EdgeManifest\n", encoding="utf-8")

            discovered = discover_edge_manifests(stacks_dir)

            self.assertEqual(
                discovered,
                [stacks_dir / "stack-a" / "edge.yaml", stacks_dir / "stack-b" / "edge.yaml"],
            )


class TestValidateEdgeManifests(unittest.TestCase):
    def test_valid_fixtures_pass(self):
        manifest_paths = sorted(VALID_DIR.glob("*.yaml"))
        result = validate_manifests(manifest_paths)
        self.assertTrue(result.ok)
        self.assertEqual(0, len(result.issues))

    def test_duplicate_host_fixtures_fail_with_emv001(self):
        manifest_paths = [
            INVALID_DIR / "duplicate-host-a.yaml",
            INVALID_DIR / "duplicate-host-b.yaml",
        ]
        result = validate_manifests(manifest_paths)
        self.assertFalse(result.ok)
        self.assertIn("EMV001", {issue.code for issue in result.issues})

    def test_invalid_fixture_codes(self):
        cases = [
            ("bad-domain.yaml", "EMV002"),
            ("missing-backend.yaml", "EMV003"),
            ("bad-auth-mode.yaml", "EMV004"),
            ("authentik-self-forward-auth.yaml", "EMV005"),
            ("harbor-forward-auth.yaml", "EMV006"),
            ("bad-url-scheme.yaml", "EMV007"),
            ("invalid-traefik-service.yaml", "EMV008"),
        ]

        for fixture_name, expected_code in cases:
            with self.subTest(fixture=fixture_name, expected_code=expected_code):
                result = validate_manifests([INVALID_DIR / fixture_name])
                self.assertFalse(result.ok)
                self.assertIn(expected_code, {issue.code for issue in result.issues})

    def test_duplicate_route_name_across_manifests_fails_with_emv009(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            a = tmp_path / "a.yaml"
            b = tmp_path / "b.yaml"
            a.write_text(
                """apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: stack-a-edge
  stack: stack-a
spec:
  routes:
    - name: shared-route
      host: stack-a.lab.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.1.50:8080
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
""",
                encoding="utf-8",
            )
            b.write_text(
                """apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: stack-b-edge
  stack: stack-b
spec:
  routes:
    - name: shared-route
      host: stack-b.lab.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.1.51:8080
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
""",
                encoding="utf-8",
            )

            result = validate_manifests([a, b])

        self.assertFalse(result.ok)
        self.assertIn("EMV009", {issue.code for issue in result.issues})


class TestExtractLegacyRoutes(unittest.TestCase):
    def test_current_playbook_has_no_legacy_routes(self):
        playbook_path = (
            REPO_ROOT
            / "terraform"
            / "lxc"
            / "ansible"
            / "playbooks"
            / "deploy-proxy-stack.yml"
        )

        result = extract_legacy_routes(playbook_path)

        self.assertTrue(result.ok)
        extracted = {route.router: route.host for route in result.routes}
        self.assertEqual({}, extracted)

    def test_reports_malformed_host_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            playbook = Path(tmpdir) / "deploy-proxy-stack.yml"
            playbook.write_text(
                """http:
  routers:
    bad-router:
      rule: \"Host(bad.lab.gibbsgreatly.xyz)\"
""",
                encoding="utf-8",
            )

            result = extract_legacy_routes(playbook)

        self.assertFalse(result.ok)
        self.assertIn("LRI101", {issue.code for issue in result.issues})

    def test_reports_unresolvable_host_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            playbook = Path(tmpdir) / "deploy-proxy-stack.yml"
            playbook.write_text(
                """http:
  routers:
    templated-router:
      rule: \"Host(`{{ custom_edge_host }}`)\"
""",
                encoding="utf-8",
            )

            result = extract_legacy_routes(playbook)

        self.assertFalse(result.ok)
        self.assertIn("LRI102", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
