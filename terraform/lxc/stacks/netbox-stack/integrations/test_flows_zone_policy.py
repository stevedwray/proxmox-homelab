"""Tests for zone-policy flow derivation in flows.py."""

import unittest

import flows


class TestDeriveZonePolicyFlows(unittest.TestCase):
    def test_single_zone_policy_keeps_plain_id(self):
        out = flows.derive_zone_policy_flows({"policies": [
            {"from": "mgmt_seg", "to": "infra_seg", "protocol": "tcp", "ports": [443], "description": "d"},
        ]})
        self.assertEqual([f["id"] for f in out], ["df-zone-policy-00"])
        self.assertEqual(out[0]["trust_boundary_crossing"], "tb-mgmt-to-infra")

    def test_list_destination_expands_to_one_flow_per_zone(self):
        out = flows.derive_zone_policy_flows({"policies": [
            {"from": "mgmt_seg", "to": ["infra_seg", "build_seg"], "protocol": "all", "ports": []},
        ]})
        self.assertEqual([f["id"] for f in out], ["df-zone-policy-00-00", "df-zone-policy-00-01"])
        self.assertEqual([f["to"] for f in out], ["zone:infra_seg", "zone:build_seg"])

    def test_placeholder_zone_is_resolved_from_environment(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"LAB_IP_GREENBONE": "192.168.20.30"}):
            out = flows.derive_zone_policy_flows({"policies": [
                {"from": "${lab_ip_greenbone}", "to": ["infra_seg"], "protocol": "all", "ports": []},
            ]})
        self.assertEqual(out[0]["from"], "zone:192.168.20.30")


if __name__ == "__main__":
    unittest.main()
