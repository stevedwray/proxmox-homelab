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

    def test_no_values_ever(self):
        # The exporter never receives values; make sure nothing but names/numbers is emitted.
        for line in self.text.splitlines():
            if line.startswith("#"):
                continue
            self.assertRegex(line, r'^[a-z_]+(\{[a-z_]+="[A-Za-z0-9/_.-]+"(,[a-z_]+="[A-Za-z0-9/_.-]+")*\})? [0-9.e+]+$')


if __name__ == "__main__":
    unittest.main()
