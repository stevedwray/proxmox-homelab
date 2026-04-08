"""Path contract tests for populate.py.

These tests verify that each populate_* function calls the NetBox API with
the correct endpoint paths. Their primary purpose is to catch accidental path
changes during refactoring (e.g. extracting string literals to constants).

They do NOT test business logic or data transformation — only that the right
paths are called.

Run from this directory:
    python3 -m pytest test_populate_paths.py -v
    # or
    python3 -m unittest test_populate_paths -v
"""
import sys
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub out discover so tests don't need Proxmox/Portainer connectivity.
# ---------------------------------------------------------------------------
discover_stub = MagicMock()
discover_stub.build_full_topology.return_value = {"vms": [], "network": {}}
sys.modules.setdefault("discover", discover_stub)

import populate  # noqa: E402 — must come after discover stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_nb():
    """NetBoxClient mock with sensible default return values."""
    nb = MagicMock()
    nb.ensure.return_value = {"id": 1, "name": "mock", "display": "mock",
                              "primary_ip4": None}
    nb.get.return_value = {"results": [{"id": 1, "name": "mock",
                                        "primary_ip4": None}], "count": 1}
    nb.patch.return_value = {"id": 1}
    return nb


def ensure_paths(nb):
    return [c.args[0] for c in nb.ensure.call_args_list]


def get_paths(nb):
    return [c.args[0] for c in nb.get.call_args_list]


SITE = {"id": 1, "name": "Homelab"}

SAMPLE_VMS = [
    {
        "name": "test-vm",
        "status": "active",
        "vcpus": 2,
        "memory": 2048,
        "disk": 20,
        "description": "Test VM",
        "tags": ["web"],
        "ip": "192.168.1.10/24",
        "services": [{"name": "http", "port": 80, "protocol": "tcp"}],
    }
]

SAMPLE_NETWORK = {
    "router": {"identity": "mikrotik", "host": "192.168.1.1"},
    "interfaces": [{"name": "ether1", "type": "ether", "disabled": False}],
    "vlans": [{"vlan-id": "10", "name": "LAN"}],
    "ip_addresses": [{"address": "192.168.1.1/24", "interface": "ether1"}],
}


# ---------------------------------------------------------------------------
# populate_foundation
# ---------------------------------------------------------------------------

class TestPopulateFoundationPaths(unittest.TestCase):

    def setUp(self):
        self.nb = make_nb()
        self.site = populate.populate_foundation(self.nb)

    def test_creates_site(self):
        self.assertIn("/dcim/sites/", ensure_paths(self.nb))

    def test_creates_manufacturers(self):
        self.assertIn("/dcim/manufacturers/", ensure_paths(self.nb))

    def test_creates_platforms(self):
        self.assertIn("/dcim/platforms/", ensure_paths(self.nb))

    def test_creates_cluster_types(self):
        self.assertIn("/virtualization/cluster-types/", ensure_paths(self.nb))

    def test_creates_device_roles(self):
        self.assertIn("/dcim/device-roles/", ensure_paths(self.nb))

    def test_creates_device_types(self):
        self.assertIn("/dcim/device-types/", ensure_paths(self.nb))

    def test_looks_up_manufacturer_for_device_type(self):
        self.assertIn("/dcim/manufacturers/", get_paths(self.nb))

    def test_returns_site_object(self):
        self.assertEqual(self.site["id"], 1)


# ---------------------------------------------------------------------------
# populate_physical
# ---------------------------------------------------------------------------

class TestPopulatePhysicalPaths(unittest.TestCase):

    def setUp(self):
        self.nb = make_nb()
        populate.populate_physical(self.nb, SITE)

    def test_creates_devices(self):
        self.assertIn("/dcim/devices/", ensure_paths(self.nb))

    def test_creates_interfaces(self):
        self.assertIn("/dcim/interfaces/", ensure_paths(self.nb))

    def test_creates_clusters(self):
        self.assertIn("/virtualization/clusters/", ensure_paths(self.nb))

    def test_looks_up_device_roles(self):
        self.assertIn("/dcim/device-roles/", get_paths(self.nb))

    def test_looks_up_device_types(self):
        self.assertIn("/dcim/device-types/", get_paths(self.nb))

    def test_looks_up_platforms(self):
        self.assertIn("/dcim/platforms/", get_paths(self.nb))

    def test_looks_up_cluster_types(self):
        self.assertIn("/virtualization/cluster-types/", get_paths(self.nb))


# ---------------------------------------------------------------------------
# populate_virtual
# ---------------------------------------------------------------------------

class TestPopulateVirtualPaths(unittest.TestCase):

    def setUp(self):
        self.nb = make_nb()
        populate.populate_virtual(self.nb, SAMPLE_VMS)

    def test_creates_virtual_machines(self):
        self.assertIn("/virtualization/virtual-machines/", ensure_paths(self.nb))

    def test_creates_vm_interfaces(self):
        self.assertIn("/virtualization/interfaces/", ensure_paths(self.nb))

    def test_creates_tags(self):
        self.assertIn("/extras/tags/", ensure_paths(self.nb))

    def test_looks_up_cluster(self):
        self.assertIn("/virtualization/clusters/", get_paths(self.nb))

    def test_looks_up_platform(self):
        self.assertIn("/dcim/platforms/", get_paths(self.nb))

    def test_no_ensure_calls_for_empty_vm_list(self):
        nb = make_nb()
        populate.populate_virtual(nb, [])
        # cluster and platform lookups still happen; no ensure calls
        nb.ensure.assert_not_called()


# ---------------------------------------------------------------------------
# populate_ipam
# ---------------------------------------------------------------------------

class TestPopulateIpamPaths(unittest.TestCase):

    def setUp(self):
        self.nb = make_nb()
        populate.populate_ipam(self.nb, SITE, SAMPLE_VMS)

    def test_creates_prefix(self):
        self.assertIn("/ipam/prefixes/", ensure_paths(self.nb))

    def test_creates_ip_addresses(self):
        self.assertIn("/ipam/ip-addresses/", ensure_paths(self.nb))

    def test_creates_services(self):
        self.assertIn("/ipam/services/", ensure_paths(self.nb))

    def test_looks_up_devices(self):
        self.assertIn("/dcim/devices/", get_paths(self.nb))

    def test_looks_up_dcim_interfaces(self):
        self.assertIn("/dcim/interfaces/", get_paths(self.nb))

    def test_looks_up_virtual_machines(self):
        self.assertIn("/virtualization/virtual-machines/", get_paths(self.nb))

    def test_looks_up_vm_interfaces(self):
        self.assertIn("/virtualization/interfaces/", get_paths(self.nb))

    def test_patches_primary_ip4_for_device_without_one(self):
        self.assertTrue(self.nb.patch.called)

    def test_no_ip_vm_skipped(self):
        # VM without ip is skipped — no services created, and ip-addresses
        # count stays at 1 (only the module-level DEVICES entry for pve).
        nb = make_nb()
        populate.populate_ipam(nb, SITE, [{"name": "no-ip-vm"}])
        ip_calls = [c for c in nb.ensure.call_args_list
                    if c.args[0] == "/ipam/ip-addresses/"]
        self.assertEqual(len(ip_calls), 1)
        self.assertNotIn("/ipam/services/", ensure_paths(nb))


# ---------------------------------------------------------------------------
# populate_network
# ---------------------------------------------------------------------------

class TestPopulateNetworkPaths(unittest.TestCase):

    def setUp(self):
        self.nb = make_nb()
        populate.populate_network(self.nb, SITE, SAMPLE_NETWORK)

    def test_creates_router_device(self):
        self.assertIn("/dcim/devices/", ensure_paths(self.nb))

    def test_creates_router_interfaces(self):
        self.assertIn("/dcim/interfaces/", ensure_paths(self.nb))

    def test_creates_vlan_group(self):
        self.assertIn("/ipam/vlan-groups/", ensure_paths(self.nb))

    def test_creates_vlans(self):
        self.assertIn("/ipam/vlans/", ensure_paths(self.nb))

    def test_creates_ip_addresses(self):
        self.assertIn("/ipam/ip-addresses/", ensure_paths(self.nb))

    def test_looks_up_device_roles(self):
        self.assertIn("/dcim/device-roles/", get_paths(self.nb))

    def test_looks_up_device_types(self):
        self.assertIn("/dcim/device-types/", get_paths(self.nb))


class TestPopulateNetworkSkipsWithoutRouter(unittest.TestCase):

    def test_no_ensure_calls_when_router_is_none(self):
        nb = make_nb()
        populate.populate_network(nb, SITE, {"router": None})
        nb.ensure.assert_not_called()

    def test_no_ensure_calls_when_router_key_absent(self):
        nb = make_nb()
        populate.populate_network(nb, SITE, {})
        nb.ensure.assert_not_called()

    def test_skips_interface_with_no_name(self):
        nb = make_nb()
        network = {**SAMPLE_NETWORK, "interfaces": [{"type": "ether"}]}
        populate.populate_network(nb, SITE, network)
        # /dcim/interfaces/ ensure should not be called for nameless interface
        self.assertNotIn("/dcim/interfaces/", ensure_paths(nb))

    def test_skips_vlan_with_no_vlan_id(self):
        nb = make_nb()
        network = {**SAMPLE_NETWORK, "vlans": [{"name": "no-id"}]}
        populate.populate_network(nb, SITE, network)
        self.assertNotIn("/ipam/vlans/", ensure_paths(nb))


# ---------------------------------------------------------------------------
# WIPE_ORDER / clean
# ---------------------------------------------------------------------------

class TestWipeOrder(unittest.TestCase):

    EXPECTED_PATHS = {
        "/ipam/services/",
        "/ipam/ip-addresses/",
        "/ipam/vlans/",
        "/ipam/vlan-groups/",
        "/ipam/prefixes/",
        "/virtualization/interfaces/",
        "/virtualization/virtual-machines/",
        "/virtualization/clusters/",
        "/virtualization/cluster-types/",
        "/dcim/interfaces/",
        "/dcim/devices/",
        "/dcim/device-types/",
        "/dcim/device-roles/",
        "/dcim/platforms/",
        "/dcim/manufacturers/",
        "/dcim/sites/",
        "/extras/tags/",
    }

    def test_wipe_order_contains_all_expected_paths(self):
        self.assertEqual(set(populate.WIPE_ORDER), self.EXPECTED_PATHS)

    def test_wipe_order_has_no_duplicates(self):
        self.assertEqual(len(populate.WIPE_ORDER), len(set(populate.WIPE_ORDER)))


class TestClean(unittest.TestCase):

    def _make_nb_with_one_item_per_path(self):
        nb = MagicMock()
        nb.get.side_effect = (
            [{"results": [{"id": 1, "name": "obj", "display": "obj",
                           "address": None, "prefix": None}]},
             {"results": []}]
            * len(populate.WIPE_ORDER)
        )
        return nb

    def test_deletes_one_object_per_path(self):
        nb = self._make_nb_with_one_item_per_path()
        populate.clean(nb)
        self.assertEqual(nb.delete.call_count, len(populate.WIPE_ORDER))

    def test_continues_on_delete_error(self):
        nb = self._make_nb_with_one_item_per_path()
        nb.delete.side_effect = RuntimeError("conflict")
        # Should not raise
        populate.clean(nb)

    def test_stops_paginating_when_results_empty(self):
        nb = MagicMock()
        nb.get.return_value = {"results": []}
        populate.clean(nb)
        nb.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
