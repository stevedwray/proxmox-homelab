"""Tests for the Technitium parity-zone renderer."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "docs" / "provisioning-refactor" / "fixtures"
VALID_DIR = FIXTURES_DIR / "valid"
INVALID_DIR = FIXTURES_DIR / "invalid"
RENDER_MODULE_PATH = Path(__file__).resolve().parent / "render-edge-technitium.py"
SPEC = importlib.util.spec_from_file_location("render_edge_technitium", RENDER_MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
os.environ["LAB_IP_PROXY"] = "10.57.2.10"
SPEC.loader.exec_module(MODULE)

render_technitium_dry_run = MODULE.render_technitium_dry_run


class TestRenderEdgeTechnitium(unittest.TestCase):
    def test_preserves_unresolved_seed_placeholders_in_source_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            seed = tmp / "seed.zone"
            output_records = tmp / "records.json"
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m
@ IN NS ns1.lab.gibbsgreatly.xyz.
ns1 IN A ${LAB_IP_DNS}
grafana A ${LAB_IP_MONITORING}
""",
                encoding="utf-8",
            )

            previous_dns = os.environ.pop("LAB_IP_DNS", None)
            previous_monitoring = os.environ.pop("LAB_IP_MONITORING", None)
            try:
                result = render_technitium_dry_run(
                    manifest_paths=[VALID_DIR / "grafana.yaml"],
                    seed_zone_path=seed,
                    output_records_path=output_records,
                )
            finally:
                if previous_dns is not None:
                    os.environ["LAB_IP_DNS"] = previous_dns
                if previous_monitoring is not None:
                    os.environ["LAB_IP_MONITORING"] = previous_monitoring

        self.assertTrue(result.ok)
        self.assertEqual("lab.gibbsgreatly.xyz", result.zone)
        record_map = {record.name: record.ip for record in result.records}
        self.assertEqual("${LAB_IP_TECHNITIUM}", record_map["dns"])
        self.assertEqual("${LAB_IP_TECHNITIUM}", record_map["ns1"])
        self.assertEqual("10.57.2.10", record_map["grafana"])

    def test_renders_generated_browser_record_and_preserves_non_browser_seed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            seed = tmp / "seed.zone"
            output_records = tmp / "records.json"
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

            result = render_technitium_dry_run(
                manifest_paths=[VALID_DIR / "grafana.yaml"],
                seed_zone_path=seed,
                output_records_path=output_records,
            )

        self.assertTrue(result.ok)
        record_map = {record.name: record.ip for record in result.records}
        self.assertEqual("${LAB_IP_TECHNITIUM}", record_map["dns"])
        self.assertEqual("${LAB_IP_TECHNITIUM}", record_map["ns1"])
        self.assertEqual("10.57.1.11", record_map["step-ca"])
        self.assertEqual("10.57.2.10", record_map["grafana"])
        self.assertNotEqual("10.57.1.12", record_map["grafana"])

    def test_fails_when_validator_rejects_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            seed = tmp / "seed.zone"
            output_records = tmp / "records.json"
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m
@ IN NS ns1.lab.gibbsgreatly.xyz.
ns1 IN A 10.57.1.13
""",
                encoding="utf-8",
            )

            result = render_technitium_dry_run(
                manifest_paths=[INVALID_DIR / "bad-domain.yaml"],
                seed_zone_path=seed,
                output_records_path=output_records,
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
            output_records = tmp / "records.json"
            manifest.write_text(manifest_template, encoding="utf-8")
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m
@ IN NS ns1.lab.gibbsgreatly.xyz.
ns1 IN A 10.57.1.13
""",
                encoding="utf-8",
            )

            result = render_technitium_dry_run(
                manifest_paths=[manifest],
                seed_zone_path=seed,
                output_records_path=output_records,
            )

        self.assertFalse(result.ok)
        self.assertIn("TDR200", {issue.code for issue in result.issues})
