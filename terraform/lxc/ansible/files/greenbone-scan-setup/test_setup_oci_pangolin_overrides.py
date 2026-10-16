"""Tests for setup_oci_pangolin_overrides.py (python-gvm is stubbed)."""
import os
import sys
import types
import unittest
import xml.etree.ElementTree as ET

os.environ.setdefault("GVM_USERNAME", "x")
os.environ.setdefault("GVM_PASSWORD", "x")
for name in ("gvm", "gvm.connections", "gvm.protocols", "gvm.protocols.gmp", "gvm.transforms"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["gvm.connections"].UnixSocketConnection = object
sys.modules["gvm.protocols.gmp"].Gmp = object
sys.modules["gvm.transforms"].EtreeCheckCommandTransform = object

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_oci_pangolin_overrides as ov  # noqa: E402


def response(*rows):
    root = ET.Element("get_overrides_response")
    for oid, host, port in rows:
        o = ET.SubElement(root, "override")
        ET.SubElement(o, "nvt", oid=oid)
        ET.SubElement(o, "hosts").text = host
        ET.SubElement(o, "port").text = port
    return root


class OverrideTests(unittest.TestCase):
    def test_all_missing_on_empty(self):
        self.assertEqual(len(ov.missing_overrides(ov.existing_keys(response()))), len(ov.OVERRIDES))

    def test_existing_override_is_not_recreated(self):
        oid = ov.OVERRIDES[0][0]
        present = ov.existing_keys(response((oid, ov.TARGET_IP, ov.PORT)))
        self.assertNotIn(oid, [o for o, _ in ov.missing_overrides(present)])
        self.assertEqual(len(ov.missing_overrides(present)), len(ov.OVERRIDES) - 1)

    def test_same_nvt_on_other_host_or_port_does_not_count(self):
        oid = ov.OVERRIDES[0][0]
        present = ov.existing_keys(response((oid, "192.168.1.5", ov.PORT), (oid, ov.TARGET_IP, "80/tcp")))
        self.assertEqual(len(ov.missing_overrides(present)), len(ov.OVERRIDES))

    def test_scope_is_one_host_one_port(self):
        self.assertEqual(ov.TARGET_IP, "192.9.191.163")
        self.assertEqual(ov.PORT, "443/tcp")
        self.assertEqual(ov.FALSE_POSITIVE, -1)


if __name__ == "__main__":
    unittest.main()
