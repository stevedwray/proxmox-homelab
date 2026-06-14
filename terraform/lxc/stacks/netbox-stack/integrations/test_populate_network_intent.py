"""Focused tests for network-intent parsing in populate.py."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml


# Stub discovery dependency so populate imports without external integration setup.
discover_stub = MagicMock()
discover_stub.build_full_topology.return_value = {"vms": [], "network": {}}
sys.modules.setdefault("discover", discover_stub)

import populate  # noqa: E402


class TestNetworkIntentPathSelection(unittest.TestCase):
    def test_selects_pve_test_file_from_environment(self):
        with patch.dict(os.environ, {"NETBOX_NETWORK_ENV": "pve-test"}, clear=True):
            path = populate._select_network_intent_path()

        self.assertTrue(str(path).endswith("terraform/lxc/network/pve-test.yaml"))

    def test_selects_pve_file_from_environment(self):
        with patch.dict(os.environ, {"NETBOX_NETWORK_ENV": "pve"}, clear=True):
            path = populate._select_network_intent_path()

        self.assertTrue(str(path).endswith("terraform/lxc/network/pve.yaml"))

    def test_requires_environment_without_path_override(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "environment is ambiguous"):
                populate._select_network_intent_path()


class TestExtractRoutedPrefixes(unittest.TestCase):
    def test_extracts_prefixes_for_routed_segments(self):
        network_intent = {
            "attachments": {
                "lan": {
                    "type": "bridge",
                },
                "infra_seg": {
                    "type": "sdn_vnet",
                    "description": "Infra",
                    "sdn": {"subnet": "${lab_subnet_infra_cidr}"},
                },
                "seg_c": {
                    "type": "sdn_vnet",
                    "description": "Build",
                    "sdn": {"subnet": "${lab_subnet_build_cidr}"},
                },
            },
            "zones": {
                "infra_seg": {
                    "attachment": "infra_seg",
                    "description": "Infrastructure services",
                },
                "build_seg": {
                    "attachment": "seg_c",
                    "description": "CI build workloads",
                },
            },
        }

        with patch.dict(
            os.environ,
            {
                "LAB_SUBNET_INFRA_CIDR": "192.168.40.0/24",
                "LAB_SUBNET_BUILD_CIDR": "192.168.10.0/24",
            },
            clear=True,
        ):
            prefixes = populate._extract_routed_segment_prefixes(network_intent)

        self.assertEqual(len(prefixes), 2)
        self.assertIn("192.168.40.0/24", [p["prefix"] for p in prefixes])
        self.assertIn("192.168.10.0/24", [p["prefix"] for p in prefixes])

    def test_excludes_bridge_attachment_segments(self):
        network_intent = {
            "attachments": {
                "lan": {
                    "type": "bridge",
                    "sdn": {"subnet": "192.168.1.0/24"},
                },
            },
            "zones": {
                "legacy_lan": {
                    "attachment": "lan",
                    "description": "Legacy LAN",
                },
            },
        }

        prefixes = populate._extract_routed_segment_prefixes(network_intent)
        self.assertEqual(prefixes, [])


class TestProxmoxHostAddressDerivation(unittest.TestCase):
    def test_derives_host_cidr_from_environment_ip(self):
        with patch.dict(os.environ, {"LAB_IP_PROXMOX_HOST": "192.168.1.2"}, clear=True):
            address = populate._derive_proxmox_host_address()

        self.assertEqual(address, "192.168.1.2/24")

    def test_honors_explicit_host_cidr(self):
        with patch.dict(
            os.environ,
            {"NETBOX_PROXMOX_HOST_ADDRESS": "10.57.0.2/24", "LAB_IP_PROXMOX_HOST": "192.168.1.2"},
            clear=True,
        ):
            address = populate._derive_proxmox_host_address()

        self.assertEqual(address, "10.57.0.2/24")


class TestBuildPopulationIntent(unittest.TestCase):
    def test_builds_segment_aware_intent_from_file(self):
        intent_payload = {
            "proxmox": {
                "target_node": "pve-test",
            },
            "attachments": {
                "mgmt_seg": {
                    "type": "sdn_vnet",
                    "sdn": {"subnet": "${lab_subnet_mgmt_cidr}"},
                },
            },
            "zones": {
                "mgmt_seg": {
                    "attachment": "mgmt_seg",
                    "description": "Management plane",
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            intent_path = Path(tmpdir) / "intent.yaml"
            intent_path.write_text(yaml.safe_dump(intent_payload), encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "NETBOX_NETWORK_ENV": "pve-test",
                    "LAB_SUBNET_MGMT_CIDR": "192.168.20.0/24",
                    "LAB_IP_PROXMOX_HOST": "192.168.1.2",
                },
                clear=True,
            ):
                result = populate.build_population_intent(network_intent_path=str(intent_path))

        self.assertEqual(result["environment"], "pve-test")
        self.assertEqual(result["prefixes"][0]["prefix"], "192.168.20.0/24")
        self.assertEqual(result["proxmox_host"]["address"], "192.168.1.2/24")
        self.assertEqual(result["proxmox_host"]["device_name"], "pve-test")
        self.assertEqual(result["proxmox"]["target_node"], "pve-test")
        self.assertEqual(result["proxmox"]["cluster_name"], "pve-test-cluster")

    def test_uses_custom_environment_label_for_explicit_path_override(self):
        intent_payload = {
            "attachments": {
                "infra_seg": {
                    "type": "sdn_vnet",
                    "sdn": {"subnet": "192.168.40.0/24"},
                },
            },
            "zones": {
                "infra_seg": {
                    "attachment": "infra_seg",
                    "description": "Infrastructure services",
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            intent_path = Path(tmpdir) / "intent.yaml"
            intent_path.write_text(yaml.safe_dump(intent_payload), encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                result = populate.build_population_intent(network_intent_path=str(intent_path))

        self.assertEqual(result["environment"], "custom")
        self.assertEqual(result["prefixes"][0]["prefix"], "192.168.40.0/24")


class TestSharedInventoryIdentity(unittest.TestCase):
    def test_builds_environment_aware_inventory_context(self):
        population_intent = {
            "environment": "pve-test",
            "proxmox": {
                "target_node": "pve-test",
                "cluster_name": "pve-test-cluster",
            },
        }

        result = populate._build_inventory_context(population_intent)

        self.assertEqual(result["environment_tag"], "netbox-env-pve-test")
        self.assertEqual(result["hypervisor_device_name"], "pve-test")
        self.assertEqual(result["cluster_name"], "pve-test-cluster")
        self.assertTrue(result["legacy_name_migration_enabled"])

    def test_virtual_machine_name_is_scoped_by_source_node(self):
        inventory = {
            "environment": "pve",
            "target_node": "pve",
        }
        vm_def = {"name": "authentik-stack", "node": "pve"}

        result = populate._virtual_machine_name(vm_def, inventory)

        self.assertEqual(result, "authentik-stack@pve")

    def test_prod_inventory_does_not_use_legacy_bare_name_migration(self):
        inventory = {
            "environment": "pve",
            "target_node": "pve",
            "legacy_name_migration_enabled": False,
        }
        vm_def = {"name": "authentik-stack", "node": "pve"}

        result = populate._legacy_virtual_machine_lookups(vm_def, inventory)

        self.assertEqual(result, [])

    def test_discovered_proxmox_host_context_overrides_seed_address(self):
        population_intent = {
            "proxmox_host": {
                "device_name": "pve-test",
                "interface_name": "vmbr0",
                "address": "192.168.1.2/24",
            }
        }
        topology = {
            "proxmox": {
                "host_address": "192.168.1.40/24",
                "host_interface": "vmbr0",
            }
        }

        result = populate._apply_discovered_proxmox_host_context(population_intent, topology)

        self.assertEqual(result["proxmox_host"]["address"], "192.168.1.40/24")


if __name__ == "__main__":
    unittest.main()
