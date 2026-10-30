"""Tests for flows.derive_zone_policy_flows list-valued from/to handling."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flows  # noqa: E402


class DeriveZonePolicyFlowsTest(unittest.TestCase):
    def test_scalar_policy_keeps_original_id(self):
        result = flows.derive_zone_policy_flows(
            {"policies": [{}, {}, {"from": "build_seg", "to": "mgmt_seg", "ports": [9000]}]}
        )
        policy_flow = result[2]
        self.assertEqual(policy_flow["id"], "df-zone-policy-02")
        self.assertEqual(policy_flow["from"], "zone:build_seg")
        self.assertEqual(policy_flow["to"], "zone:mgmt_seg")
        self.assertEqual(policy_flow["trust_boundary_crossing"], "tb-build-to-mgmt")

    def test_list_destination_fans_out_one_flow_per_pair(self):
        result = flows.derive_zone_policy_flows(
            {"policies": [{"from": "${lab_ip_greenbone}", "to": ["build_seg", "192.168.1.0/24"], "protocol": "all"}]}
        )
        self.assertEqual([f["id"] for f in result], ["df-zone-policy-00-00", "df-zone-policy-00-01"])
        self.assertEqual([f["to"] for f in result], ["zone:build_seg", "zone:192.168.1.0/24"])
        self.assertTrue(all(f["trust_boundary_crossing"] is None for f in result))

    def test_real_pve_intent_derives_without_error(self):
        model = flows.build_threat_model(env="pve")
        self.assertTrue(any(f.get("flow_type") == "zone-policy" for f in model["data_flows"]))


if __name__ == "__main__":
    unittest.main()
