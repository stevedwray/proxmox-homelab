"""Tests for the secret-free managed-host export in gvm_fleet_targets_generate.py."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gvm_fleet_targets_generate as g  # noqa: E402


class ManagedHostsTests(unittest.TestCase):
    def test_groups_sorts_and_dedupes_by_zone(self):
        hosts = [
            {"name": "b", "host": "192.168.20.12", "zone": "mgmt_seg"},
            {"name": "a", "host": "192.168.20.10", "zone": "mgmt_seg"},
            {"name": "dup", "host": "192.168.20.10", "zone": "mgmt_seg"},
            {"name": "c", "host": "192.168.1.2", "zone": "lan"},
        ]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "nested" / "managed.json"
            g.write_managed_hosts(out, hosts)
            self.assertEqual(
                json.loads(out.read_text(encoding="utf-8")),
                {"lan": ["192.168.1.2"], "mgmt_seg": ["192.168.20.10", "192.168.20.12"]},
            )

    def test_output_has_only_zone_to_ip_lists(self):
        hosts = [{"name": "x", "host": "192.168.50.10", "zone": "ai_seg",
                  "ansible_user": "root", "secret": "should-never-appear"}]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.json"
            g.write_managed_hosts(out, hosts)
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("should-never-appear", text)
            self.assertNotIn("root", text)


if __name__ == "__main__":
    unittest.main()
