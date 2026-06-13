"""Tests for multi-source inventory: proxmox_nodes list and static_hosts."""

import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

discover_stub = MagicMock()
discover_stub.build_full_topology.return_value = {"vms": [], "network": {}, "proxmox": {}}
discover_stub.build_topology.return_value = []
discover_stub.build_network_topology.return_value = {"router": None, "interfaces": [], "vlans": [], "ip_addresses": []}
discover_stub.build_proxmox_context.return_value = {}
sys.modules.setdefault("discover", discover_stub)

import populate  # noqa: E402


class TestLoadInventorySources(unittest.TestCase):
    def test_returns_empty_defaults_when_no_inventory_section(self):
        result = populate._load_inventory_sources({})
        self.assertEqual(result["proxmox_nodes"], [])
        self.assertEqual(result["static_hosts"], [])

    def test_extracts_proxmox_nodes_and_static_hosts(self):
        intent = {
            "inventory": {
                "proxmox_nodes": [{"host": "pve-test.example.com", "token_id_env": "A", "token_secret_env": "B"}],
                "static_hosts": [{"name": "my-desktop", "role": "workstation", "ip": "192.168.1.50"}],
            }
        }
        result = populate._load_inventory_sources(intent)
        self.assertEqual(len(result["proxmox_nodes"]), 1)
        self.assertEqual(result["proxmox_nodes"][0]["host"], "pve-test.example.com")
        self.assertEqual(len(result["static_hosts"]), 1)
        self.assertEqual(result["static_hosts"][0]["name"], "my-desktop")

    def test_proxmox_nodes_defaults_to_empty_when_absent(self):
        result = populate._load_inventory_sources({"inventory": {"static_hosts": []}})
        self.assertEqual(result["proxmox_nodes"], [])

    def test_static_hosts_defaults_to_empty_when_absent(self):
        result = populate._load_inventory_sources({"inventory": {"proxmox_nodes": []}})
        self.assertEqual(result["static_hosts"], [])


class TestBuildTopologyFromNodes(unittest.TestCase):
    def test_calls_discover_per_node_and_merges_vms(self):
        fake_proxmox_data = {"nodes": [], "containers": [], "storage": [], "networks": {}}
        nodes = [
            {"host": "pve-test.example.com", "token_id_env": "TID1", "token_secret_env": "TSEC1"},
            {"host": "pve2.example.com", "token_id_env": "TID2", "token_secret_env": "TSEC2"},
        ]
        with patch("populate.discover_from_proxmox", return_value=fake_proxmox_data) as mock_disc, \
             patch("populate.build_topology", side_effect=[
                 [{"name": "vm1@pve-test", "ip": "192.168.40.10"}],
                 [{"name": "vm2@pve2", "ip": "192.168.40.20"}],
             ]), \
             patch("populate.build_network_topology", return_value={"router": None}), \
             patch("populate.build_proxmox_context", return_value={}), \
             patch.dict(os.environ, {"TID1": "tok1", "TSEC1": "sec1", "TID2": "tok2", "TSEC2": "sec2"}):
            result = populate._build_topology_from_nodes(nodes)

        self.assertEqual(len(result["vms"]), 2)
        self.assertIn("vm1@pve-test", [v["name"] for v in result["vms"]])
        self.assertIn("vm2@pve2", [v["name"] for v in result["vms"]])
        self.assertEqual(mock_disc.call_count, 2)

    def test_skips_node_with_unresolvable_host(self):
        nodes = [{"host": "${MISSING_VAR}", "token_id_env": "TID", "token_secret_env": "TSEC"}]
        with patch("populate.discover_from_proxmox") as mock_disc, \
             patch("populate.build_network_topology", return_value={"router": None}), \
             patch("populate.build_proxmox_context", return_value={}), \
             patch.dict(os.environ, {}, clear=True):
            result = populate._build_topology_from_nodes(nodes)
        self.assertEqual(result["vms"], [])
        mock_disc.assert_not_called()

    def test_skips_failed_node_and_continues(self):
        fake_proxmox_data = {"nodes": [], "containers": [], "storage": [], "networks": {}}
        nodes = [
            {"host": "bad-host.example.com", "token_id_env": "TID1", "token_secret_env": "TSEC1"},
            {"host": "pve2.example.com", "token_id_env": "TID2", "token_secret_env": "TSEC2"},
        ]
        with patch("populate.discover_from_proxmox", side_effect=[RuntimeError("refused"), fake_proxmox_data]), \
             patch("populate.build_topology", return_value=[{"name": "vm1@pve2", "ip": "10.0.0.1"}]), \
             patch("populate.build_network_topology", return_value={"router": None}), \
             patch("populate.build_proxmox_context", return_value={}), \
             patch.dict(os.environ, {"TID1": "tok1", "TSEC1": "sec1", "TID2": "tok2", "TSEC2": "sec2"}):
            result = populate._build_topology_from_nodes(nodes)

        self.assertEqual(len(result["vms"]), 1)
        self.assertEqual(result["vms"][0]["name"], "vm1@pve2")

    def test_uses_correct_url_and_credentials(self):
        fake_proxmox_data = {"nodes": [], "containers": [], "storage": [], "networks": {}}
        nodes = [{"host": "pve-test.example.com", "token_id_env": "MY_TOKEN_ID", "token_secret_env": "MY_TOKEN_SEC"}]
        with patch("populate.discover_from_proxmox", return_value=fake_proxmox_data) as mock_disc, \
             patch("populate.build_topology", return_value=[]), \
             patch("populate.build_network_topology", return_value={"router": None}), \
             patch("populate.build_proxmox_context", return_value={}), \
             patch.dict(os.environ, {"MY_TOKEN_ID": "automation@pve!terraform", "MY_TOKEN_SEC": "test-token-value"}):
            populate._build_topology_from_nodes(nodes)

        mock_disc.assert_called_once()
        kw = mock_disc.call_args.kwargs
        self.assertEqual(kw["url"], "https://pve-test.example.com:8006")
        self.assertEqual(kw["token_id"], "automation@pve!terraform")
        self.assertEqual(kw["token_secret"], "test-token-value")


class TestPopulateStaticHosts(unittest.TestCase):
    def _make_nb(self):
        nb = MagicMock()
        nb.get.side_effect = lambda path, **kw: {
            "count": 1,
            "results": [{"id": 99, "name": kw.get("model") or kw.get("slug") or "generic"}],
        }
        nb.ensure.side_effect = lambda path, lookup, defaults=None, **kw: {"id": 1, **lookup, **(defaults or {})}
        return nb

    def test_skips_empty_list(self):
        nb = self._make_nb()
        site = {"id": 1}
        populate.populate_static_hosts(nb, site, [])
        nb.ensure.assert_not_called()

    def test_skips_entry_with_no_name(self):
        nb = self._make_nb()
        site = {"id": 1}
        populate.populate_static_hosts(nb, site, [{"role": "workstation", "ip": "192.168.1.50"}])
        nb.ensure.assert_not_called()

    def test_creates_device_with_role_and_ip(self):
        nb = self._make_nb()
        site = {"id": 42}
        hosts = [{"name": "my-desktop", "role": "workstation", "ip": "192.168.1.50"}]
        populate.populate_static_hosts(nb, site, hosts)

        # Device role ensured
        role_calls = [c for c in nb.ensure.call_args_list if NB_DCIM_DEVICE_ROLES in str(c)]
        self.assertTrue(any("workstation" in str(c) for c in role_calls))

        # Device ensured
        device_calls = [c for c in nb.ensure.call_args_list if populate.NB_DCIM_DEVICES in str(c)]
        self.assertGreaterEqual(len(device_calls), 1)
        self.assertIn("my-desktop", str(device_calls[0]))

    def test_ip_without_prefix_gets_slash24(self):
        nb = self._make_nb()
        site = {"id": 1}
        populate.populate_static_hosts(nb, site, [{"name": "pi", "role": "iot", "ip": "192.168.1.99"}])

        ip_calls = [c for c in nb.ensure.call_args_list if populate.NB_IPAM_IP_ADDRESSES in str(c)]
        self.assertTrue(any("192.168.1.99/24" in str(c) for c in ip_calls))

    def test_ip_with_existing_prefix_not_doubled(self):
        nb = self._make_nb()
        site = {"id": 1}
        populate.populate_static_hosts(nb, site, [{"name": "pi", "role": "iot", "ip": "192.168.1.99/28"}])

        ip_calls = [c for c in nb.ensure.call_args_list if populate.NB_IPAM_IP_ADDRESSES in str(c)]
        self.assertTrue(any("192.168.1.99/28" in str(c) for c in ip_calls))
        self.assertFalse(any("192.168.1.99/28/24" in str(c) for c in ip_calls))

    def test_no_ip_skips_interface_and_address(self):
        nb = self._make_nb()
        site = {"id": 1}
        populate.populate_static_hosts(nb, site, [{"name": "headless", "role": "server"}])

        ip_calls = [c for c in nb.ensure.call_args_list if populate.NB_IPAM_IP_ADDRESSES in str(c)]
        iface_calls = [c for c in nb.ensure.call_args_list if populate.NB_DCIM_INTERFACES in str(c)]
        self.assertEqual(len(ip_calls), 0)
        self.assertEqual(len(iface_calls), 0)


NB_DCIM_DEVICE_ROLES = populate.NB_DCIM_DEVICE_ROLES
