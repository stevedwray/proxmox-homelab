"""Tests for the exclusion logic in setup_scan_program.py (python-gvm is stubbed)."""
import json
import os
import sys
import tempfile
import types
import unittest

os.environ.setdefault("GVM_USERNAME", "x")
os.environ.setdefault("GVM_PASSWORD", "x")
for name in ("gvm", "gvm.connections", "gvm.protocols", "gvm.protocols.gmp", "gvm.transforms"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["gvm.connections"].UnixSocketConnection = object
sys.modules["gvm.protocols.gmp"].Gmp = object
sys.modules["gvm.transforms"].EtreeCheckCommandTransform = object

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_scan_program as sp  # noqa: E402


class FullVulnExcludesTests(unittest.TestCase):
    def test_managed_hosts_are_excluded(self):
        managed = {"ai_seg": ["192.168.50.12", "192.168.50.10"]}
        self.assertEqual(sp.full_vuln_excludes("ai_seg", managed, []), ["192.168.50.10", "192.168.50.12"])

    def test_fixtures_are_added(self):
        managed = {"pentest_seg": ["192.168.70.11"]}
        fixtures = sp.FIXTURE_EXCLUDE["pentest_seg"]
        out = sp.full_vuln_excludes("pentest_seg", managed, fixtures)
        self.assertIn("192.168.70.11", out)
        for f in fixtures:
            self.assertIn(f, out)

    def test_zone_with_no_managed_hosts_only_has_fixtures(self):
        self.assertEqual(sp.full_vuln_excludes("lan", {}, ["192.168.1.113"]),
                         sorted(["192.168.1.113", *sp.CREDENTIALED_ELSEWHERE["lan"]]))

    def test_mikrotik_stays_excluded_on_lan(self):
        self.assertIn("192.168.1.1", sp.full_vuln_excludes("lan", {"lan": ["192.168.1.2"]}, []))

    def test_uncovered_workstation_is_not_excluded(self):
        # On the managed list but gvm-scan cannot log in: it must stay scannable.
        out = sp.full_vuln_excludes("lan", {"lan": ["192.168.1.104", "192.168.1.2"]}, [])
        self.assertNotIn("192.168.1.104", out)
        self.assertIn("192.168.1.2", out)

    def test_gateways_are_never_excluded(self):
        managed = {"mgmt_seg": ["192.168.20.10"]}
        self.assertNotIn("192.168.20.1", sp.full_vuln_excludes("mgmt_seg", managed, []))

    def test_openbao_is_covered_by_the_managed_list(self):
        managed = {"mgmt_seg": ["192.168.20.16"]}
        self.assertIn("192.168.20.16", sp.full_vuln_excludes("mgmt_seg", managed, []))

    def test_every_zone_has_a_cidr_and_no_leftover_tier_a(self):
        for zone in sp.ZONES:
            self.assertIn("cidr", zone)
            self.assertNotIn("tier_a_exclude", zone)


class LoadManagedHostsTests(unittest.TestCase):
    def test_reads_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"lan": ["192.168.1.2"]}, handle)
        self.assertEqual(sp.load_managed_hosts(handle.name), {"lan": ["192.168.1.2"]})
        os.unlink(handle.name)

    def test_missing_file_raises_instead_of_scanning_everything(self):
        with self.assertRaises(FileNotFoundError):
            sp.load_managed_hosts("/nonexistent/managed-hosts.json")


if __name__ == "__main__":
    unittest.main()
