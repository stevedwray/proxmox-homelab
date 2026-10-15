"""Unit tests for the OpenBao inventory exporter (pure functions only)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "openbao_inventory.py"
SPEC = importlib.util.spec_from_file_location("openbao_inventory", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["openbao_inventory"] = MODULE
SPEC.loader.exec_module(MODULE)


class TimestampTests(unittest.TestCase):
    def test_nanoseconds_and_z(self):
        self.assertAlmostEqual(MODULE.parse_rfc3339("2026-09-27T20:03:11.123456789Z"), 1790539391.123456789, places=5)

    def test_no_fraction_and_offset(self):
        self.assertEqual(MODULE.parse_rfc3339("2026-09-27T20:03:11+00:00"), 1790539391.0)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            MODULE.parse_rfc3339("yesterday")


class BuildMetricsTests(unittest.TestCase):
    LIVE = {
        "services/harbor": {"version": 1, "updated": 100.0},
        "services/graylog": {"version": 2, "updated": 200.0},
        "hosts/pve": {"version": 1, "updated": 300.0},
        "services/stray": {"version": 1, "updated": 400.0},
    }
    MANIFEST = {
        "services/harbor": {"fields": ["A", "B", "C"]},
        "services/graylog": {"fields": ["X", "Y"]},
        "hosts/pve": {"fields": ["T"]},
        "shared/platform": {"fields": ["P1", "P2"]},
    }

    def setUp(self):
        self.text = MODULE.build_metrics(self.LIVE, self.MANIFEST, 999.0)

    def test_entries_per_category(self):
        self.assertIn('openbao_kv_entries{category="services"} 3', self.text)
        self.assertIn('openbao_kv_entries{category="hosts"} 1', self.text)
        self.assertIn('openbao_kv_entries{category="shared"} 0', self.text)

    def test_fields_only_count_entries_present(self):
        self.assertIn('openbao_kv_fields{category="services"} 5', self.text)
        self.assertIn('openbao_kv_fields{category="shared"} 0', self.text)

    def test_per_entry_rows(self):
        self.assertIn('openbao_kv_entry_version{entry="services/graylog",category="services"} 2', self.text)
        self.assertIn('openbao_kv_entry_fields{entry="services/stray",category="services"} 0', self.text)
        self.assertIn('openbao_kv_entry_updated_timestamp_seconds{entry="hosts/pve",category="hosts"} 300', self.text)

    def test_drift(self):
        self.assertIn('openbao_kv_manifest_drift{kind="missing_in_openbao"} 1', self.text)
        self.assertIn('openbao_kv_manifest_drift{kind="missing_in_manifest"} 1', self.text)

    def test_drift_entries_are_named(self):
        self.assertIn('openbao_kv_manifest_drift_entry{entry="shared/platform",kind="missing_in_openbao"} 1', self.text)
        self.assertIn('openbao_kv_manifest_drift_entry{entry="services/stray",kind="missing_in_manifest"} 1', self.text)

    def test_manifest_source_defaults_local_and_reports_remote(self):
        self.assertIn('openbao_manifest_source{source="local"} 1', self.text)
        remote = MODULE.build_metrics(self.LIVE, self.MANIFEST, 999.0, "remote", "abc123def456")
        self.assertIn('openbao_manifest_source{source="remote"} 1', remote)
        self.assertIn('openbao_manifest_source{source="local"} 0', remote)
        self.assertIn('openbao_manifest_info{sha="abc123def456"} 1', remote)

    def test_timestamps_keep_full_precision(self):
        # %g's default 6 significant digits would round a unix time by hours.
        text = MODULE.build_metrics({"a/b": {"version": 1, "updated": 1792086901.4}}, {}, 1792086999.0)
        self.assertIn('openbao_kv_entry_updated_timestamp_seconds{entry="a/b",category="a"} 1792086901.4', text)
        self.assertIn("openbao_inventory_last_success_timestamp_seconds 1792086999", text)

    def test_no_values_ever(self):
        # The exporter never receives values; make sure nothing but names/numbers is emitted.
        for line in self.text.splitlines():
            if line.startswith("#"):
                continue
            self.assertRegex(line, r'^[a-z_]+(\{[a-z_]+="[A-Za-z0-9/_.-]+"(,[a-z_]+="[A-Za-z0-9/_.-]+")*\})? [0-9.e+]+$')


class LoadManifestTests(unittest.TestCase):
    BODY = b'{"entries": {"a/b": {"fields": ["X"]}}}'

    def test_remote_preferred(self):
        entries, source, sha = MODULE.load_manifest(fetch=lambda: self.BODY, local=Path("/nonexistent"))
        self.assertEqual((list(entries), source, len(sha)), (["a/b"], "remote", 12))

    def test_falls_back_to_local_when_fetch_fails(self):
        import tempfile

        def boom():
            raise OSError("no route")

        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / "manifest.json"
            local.write_bytes(self.BODY)
            entries, source, _ = MODULE.load_manifest(fetch=boom, local=local)
        self.assertEqual((list(entries), source), (["a/b"], "local"))

    def test_malformed_remote_is_an_error_not_silent_drift(self):
        with self.assertRaises(ValueError):
            MODULE.load_manifest(fetch=lambda: b'{"entries": []}', local=Path("/nonexistent"))


if __name__ == "__main__":
    unittest.main()
