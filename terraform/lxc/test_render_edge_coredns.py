"""Tests for the CoreDNS zone renderer."""

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
RENDER_MODULE_PATH = Path(__file__).resolve().parent / "render-edge-coredns.py"
SPEC = importlib.util.spec_from_file_location("render_edge_coredns", RENDER_MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

render_coredns_dry_run = MODULE.render_coredns_dry_run


class TestRenderEdgeCoreDNS(unittest.TestCase):
    def test_renders_generated_browser_record_and_preserves_non_browser_seed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            seed = tmp / "seed.zone"
            output_zone = tmp / "rendered.zone"
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m
@ IN SOA ns1.lab.gibbsgreatly.xyz. admin.lab.gibbsgreatly.xyz. (
  2026041802 1h 15m 30d 5m
)
@ IN NS ns1.lab.gibbsgreatly.xyz.
ns1 IN A 10.57.1.13
step-ca A 10.57.1.11
grafana A 10.57.1.12
""",
                encoding="utf-8",
            )

            result = render_coredns_dry_run(
                manifest_paths=[VALID_DIR / "grafana.yaml"],
                seed_zone_path=seed,
                output_zone_path=output_zone,
            )

        self.assertTrue(result.ok)
        self.assertIn("step-ca A 10.57.1.11", result.rendered_zone)
        self.assertNotIn("grafana A 10.57.1.12", result.rendered_zone)
        self.assertIn("grafana         5m   IN  A   10.57.2.10", result.rendered_zone)
        self.assertIn("Generated browser edge records", result.rendered_zone)
        self.assertIn("@@", result.diff)

    def test_fails_when_validator_rejects_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            seed = tmp / "seed.zone"
            output_zone = tmp / "rendered.zone"
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m
@ IN NS ns1.lab.gibbsgreatly.xyz.
ns1 IN A 10.57.1.13
""",
                encoding="utf-8",
            )

            result = render_coredns_dry_run(
                manifest_paths=[INVALID_DIR / "bad-domain.yaml"],
                seed_zone_path=seed,
                output_zone_path=output_zone,
            )

        self.assertFalse(result.ok)
        self.assertIn("EMV002", {issue.code for issue in result.issues})

    def test_rejects_duplicate_generated_records(self):
        manifest_template = """apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: duplicate-host-edge
  stack: duplicate-stack
spec:
  routes:
    - name: route-a
      host: duplicate.lab.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.1.90:8080
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
    - name: route-b
      host: duplicate.lab.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.1.91:8080
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "edge.yaml"
            seed = tmp / "seed.zone"
            output_zone = tmp / "rendered.zone"
            manifest.write_text(manifest_template, encoding="utf-8")
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m
@ IN NS ns1.lab.gibbsgreatly.xyz.
ns1 IN A 10.57.1.13
""",
                encoding="utf-8",
            )

            result = render_coredns_dry_run(
                manifest_paths=[manifest],
                seed_zone_path=seed,
                output_zone_path=output_zone,
            )

        self.assertFalse(result.ok)
        self.assertIn("CDR200", {issue.code for issue in result.issues})


if __name__ == "__main__":
    unittest.main()
