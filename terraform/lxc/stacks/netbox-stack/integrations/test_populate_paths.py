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
    nb.patch_object.return_value = {"id": 1, "name": "mock", "primary_ip4": 1}
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

SAMPLE_VMS_WITH_PROTOCOL_VARIANTS = [
    {
        "name": "gluetun-stack",
        "status": "active",
        "vcpus": 2,
        "memory": 2048,
        "disk": 20,
        "description": "Gluetun",
        "tags": ["vpn"],
        "ip": "192.168.1.20/24",
        "services": [
            {"name": "gluetun-6881", "port": 6881, "protocol": "tcp"},
            {"name": "gluetun-6881", "port": 6881, "protocol": "udp"},
        ],
    }
]

SAMPLE_NETWORK = {
    "router": {"identity": "mikrotik", "host": "192.168.1.1"},
    "interfaces": [{"name": "ether1", "type": "ether", "disabled": False}],
    "vlans": [{"vlan-id": "10", "name": "LAN"}],
    "ip_addresses": [{"address": "192.168.1.1/24", "interface": "ether1"}],
}

SAMPLE_POPULATION_INTENT = {
    "environment": "pve-test",
    "network_intent_path": "/tmp/pve-test.yaml",
    "proxmox": {
        "target_node": "pve-test",
        "cluster_name": "pve-test-cluster",
    },
    "prefixes": [
        {
            "name": "infra_seg",
            "prefix": "192.168.40.0/24",
            "description": "Infrastructure services",
        },
        {
            "name": "mgmt_seg",
            "prefix": "192.168.20.0/24",
            "description": "Management services",
        },
    ],
    "proxmox_host": {
        "device_name": "pve-test",
        "interface_name": "vmbr0",
        "address": "192.168.1.2/24",
    },
}

SAMPLE_INVENTORY = populate._build_inventory_context(SAMPLE_POPULATION_INTENT)


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
        populate.populate_physical(self.nb, SITE, SAMPLE_INVENTORY)

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
        populate.populate_virtual(self.nb, SAMPLE_VMS, SAMPLE_INVENTORY)

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
        populate.populate_virtual(nb, [], SAMPLE_INVENTORY)
        # cluster and platform lookups still happen; no ensure calls
        nb.ensure.assert_not_called()


# ---------------------------------------------------------------------------
# populate_ipam
# ---------------------------------------------------------------------------

class TestPopulateIpamPaths(unittest.TestCase):

    def setUp(self):
        self.nb = make_nb()
        populate.populate_ipam(self.nb, SITE, SAMPLE_VMS, SAMPLE_POPULATION_INTENT, SAMPLE_INVENTORY)

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
        self.assertTrue(self.nb.patch_object.called)

    def test_patches_primary_ip4_when_existing_assignment_differs(self):
        nb = make_nb()
        nb.get.return_value = {
            "results": [{"id": 1, "name": "mock", "primary_ip4": {"id": 999}}],
            "count": 1,
        }

        populate.populate_ipam(nb, SITE, SAMPLE_VMS, SAMPLE_POPULATION_INTENT, SAMPLE_INVENTORY)

        self.assertTrue(nb.patch_object.called)

    def test_deletes_stale_managed_hypervisor_ip_on_same_interface(self):
        nb = make_nb()
        host_address = "192.168.1.40/24"

        def get_side_effect(path, **kwargs):
            if path == populate.NB_DCIM_DEVICES and kwargs.get("name") == "pve-test":
                return {"results": [{"id": 1, "name": "pve-test", "primary_ip4": None}], "count": 1}
            if path == populate.NB_DCIM_INTERFACES and kwargs.get("device_id") == 1 and kwargs.get("name") == "vmbr0":
                return {"results": [{"id": 1, "name": "vmbr0", "primary_ip4": None}], "count": 1}
            if path == populate.NB_IPAM_IP_ADDRESSES and kwargs.get("address") == host_address:
                return {
                    "results": [
                        {
                            "id": 8,
                            "address": "192.168.1.2/24",
                            "tags": [{"slug": "managed-by-proxmox-homelab"}, {"slug": "netbox-env-pve-test"}],
                        },
                        {
                            "id": 23,
                            "address": host_address,
                            "assigned_object_type": "dcim.interface",
                            "assigned_object_id": 1,
                            "tags": [{"slug": "managed-by-proxmox-homelab"}, {"slug": "netbox-env-pve-test"}],
                        },
                    ],
                    "count": 2,
                }
            if path == populate.NB_VIRT_VIRTUAL_MACHINES and kwargs.get("name") == "test-vm@pve-test":
                return {"results": [{"id": 1, "name": "test-vm@pve-test", "primary_ip4": None}], "count": 1}
            if path == populate.NB_VIRT_INTERFACES and kwargs.get("virtual_machine_id") == 1 and kwargs.get("name") == "eth0":
                return {"results": [{"id": 1, "name": "eth0", "primary_ip4": None}], "count": 1}
            if path == populate.NB_IPAM_IP_ADDRESSES and kwargs.get("assigned_object_type") == "dcim.interface" and kwargs.get("assigned_object_id") == 1:
                return {
                    "results": [
                        {
                            "id": 8,
                            "address": "192.168.1.2/24",
                            "tags": [{"slug": "managed-by-proxmox-homelab"}, {"slug": "netbox-env-pve-test"}],
                        },
                        {
                            "id": 23,
                            "address": host_address,
                            "tags": [{"slug": "managed-by-proxmox-homelab"}, {"slug": "netbox-env-pve-test"}],
                        },
                    ],
                    "count": 2,
                }
            return {"results": [], "count": 0}

        nb.get.side_effect = get_side_effect
        nb.ensure.return_value = {"id": 23, "address": "192.168.1.40/24"}

        intent = {
            **SAMPLE_POPULATION_INTENT,
            "proxmox_host": {
                **SAMPLE_POPULATION_INTENT["proxmox_host"],
                "address": "192.168.1.40/24",
            },
        }

        populate.populate_ipam(nb, SITE, SAMPLE_VMS, intent, SAMPLE_INVENTORY)

        nb.delete_object.assert_called_once()

    def test_no_ip_vm_skipped(self):
        # VM without ip is skipped — no VM IPs or services are created, but the
        # host IP lookup still runs for canonical host reconciliation.
        nb = make_nb()
        populate.populate_ipam(nb, SITE, [{"name": "no-ip-vm"}], SAMPLE_POPULATION_INTENT, SAMPLE_INVENTORY)
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

    def test_sets_primary_ip4_for_private_router_ip(self):
        nb = make_nb()
        populate.populate_network(nb, SITE, SAMPLE_NETWORK)
        self.assertTrue(nb.patch_object.called)


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

    def test_does_not_set_primary_ip4_for_public_router_ip(self):
        nb = make_nb()
        network = {
            **SAMPLE_NETWORK,
            "ip_addresses": [{"address": "121.99.1.1/24", "interface": "ether1"}],
        }
        populate.populate_network(nb, SITE, network)
        self.assertFalse(nb.patch_object.called)

class TestPopulateNetworkDeterminism(unittest.TestCase):
    def test_duplicate_vlan_discovery_aggregates_by_vid(self):
        nb = make_nb()
        network = {
            "router": {"identity": "mikrotik", "host": "192.168.1.1"},
            "interfaces": [{"name": "ether1", "type": "ether", "disabled": False}],
            "vlans": [
                {"vlan-id": "10", "name": "vlan10-build"},
                {"vlan-id": "10", "name": "vlan10-alt"},
            ],
            "ip_addresses": [],
        }

        populate.populate_network(nb, SITE, network)

        vlan_calls = [c for c in nb.ensure.call_args_list if c.args[0] == "/ipam/vlans/"]
        # ensure should be called exactly once per unique VID
        self.assertEqual(len(vlan_calls), 1)

    def test_primary_ip4_selection_prefers_mgmt_and_patches_once(self):
        nb = make_nb()

        addr_map = {}
        next_id = {"n": 1000}

        def ensure_side_effect(path, lookup, defaults=None, **kwargs):
            # Return unique ids for IP address ensures so we can assert which
            # IP was chosen for primary_ip4.
            if path == "/ipam/ip-addresses/":
                next_id["n"] += 1
                addr = lookup.get("address")
                addr_map[addr] = next_id["n"]
                return {"id": next_id["n"], "address": addr}
            return {"id": 1, "name": "mock", "display": "mock", "primary_ip4": None}

        nb.ensure.side_effect = ensure_side_effect

        network = {
            "router": {"identity": "mikrotik", "host": "192.168.1.1"},
            "interfaces": [{"name": "ether1", "type": "ether", "disabled": False}],
            "vlans": [],
            "ip_addresses": [
                {"address": "192.168.40.2/24", "interface": "ether1"},
                {"address": "192.168.1.50/24", "interface": "ether1"},
            ],
        }

        populate.populate_network(nb, SITE, network)

        # Should patch the router device primary_ip4 once, preferring the
        # management LAN (192.168.1.x) address.
        nb.patch_object.assert_called_once()
        changes = nb.patch_object.call_args[0][2]
        expected_id = addr_map["192.168.1.50/24"]
        self.assertEqual(changes, {"primary_ip4": expected_id})

    def test_primary_ip4_selection_prefers_router_host_if_present(self):
        nb = make_nb()

        addr_map = {}
        next_id = {"n": 3000}

        def ensure_side_effect(path, lookup, defaults=None, **kwargs):
            if path == "/ipam/ip-addresses/":
                next_id["n"] += 1
                addr = lookup.get("address")
                addr_map[addr] = next_id["n"]
                return {"id": next_id["n"], "address": addr}
            return {"id": 1, "name": "mock", "display": "mock", "primary_ip4": None}

        nb.ensure.side_effect = ensure_side_effect

        network = {
            "router": {"identity": "mikrotik", "host": "192.168.1.251"},
            "interfaces": [{"name": "ether1", "type": "ether", "disabled": False}],
            "vlans": [],
            "ip_addresses": [
                {"address": "192.168.40.2/24", "interface": "ether1"},
                {"address": "192.168.1.50/24", "interface": "ether1"},
                {"address": "192.168.1.251/24", "interface": "ether1"},
            ],
        }

        populate.populate_network(nb, SITE, network)

        # Should patch the router device primary_ip4 once, preferring the
        # discovered router host address when present among discovered IPs.
        nb.patch_object.assert_called_once()
        changes = nb.patch_object.call_args[0][2]
        expected_id = addr_map["192.168.1.251/24"]
        self.assertEqual(changes, {"primary_ip4": expected_id})

    def test_primary_ip4_selection_numeric_fallback_deterministic(self):
        nb = make_nb()

        addr_map = {}
        next_id = {"n": 4000}

        def ensure_side_effect(path, lookup, defaults=None, **kwargs):
            if path == "/ipam/ip-addresses/":
                next_id["n"] += 1
                addr = lookup.get("address")
                addr_map[addr] = next_id["n"]
                return {"id": next_id["n"], "address": addr}
            return {"id": 1, "name": "mock", "display": "mock", "primary_ip4": None}

        nb.ensure.side_effect = ensure_side_effect

        network = {
            "router": {"identity": "mikrotik", "host": "192.168.1.1"},
            "interfaces": [{"name": "ether1", "type": "ether", "disabled": False}],
            "vlans": [],
            "ip_addresses": [
                {"address": "192.168.40.3/24", "interface": "ether1"},
                {"address": "192.168.40.2/24", "interface": "ether1"},
            ],
        }

        populate.populate_network(nb, SITE, network)

        # Should select the numerically lowest internal IP when no router host
        # candidate or mgmt LAN address is present.
        nb.patch_object.assert_called_once()
        changes = nb.patch_object.call_args[0][2]
        expected_id = addr_map["192.168.40.2/24"]
        self.assertEqual(changes, {"primary_ip4": expected_id})


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
        nb.url = "http://netbox.test"
        nb.live_get.return_value = {"count": 1, "results": [{"id": 1, "slug": populate.MANAGED_TAG_SLUG}]}
        nb.get.side_effect = (
            [{"results": [{"id": 1, "name": "obj", "display": "obj",
                           "address": None, "prefix": None}]},
             {"results": []}]
            * len(populate.WIPE_ORDER)
        )
        return nb

    def test_deletes_one_object_per_path(self):
        nb = self._make_nb_with_one_item_per_path()
        populate.clean(nb, SAMPLE_INVENTORY)
        self.assertEqual(nb.delete.call_count, len(populate.WIPE_ORDER))

    def test_continues_on_delete_error(self):
        nb = self._make_nb_with_one_item_per_path()
        nb.delete.side_effect = RuntimeError("conflict")
        # Should not raise
        populate.clean(nb, SAMPLE_INVENTORY)

    def test_stops_paginating_when_results_empty(self):
        nb = MagicMock()
        nb.url = "http://netbox.test"
        nb.live_get.return_value = {"count": 1, "results": [{"id": 1, "slug": populate.MANAGED_TAG_SLUG}]}
        nb.get.return_value = {"results": []}
        populate.clean(nb, SAMPLE_INVENTORY)
        nb.delete.assert_not_called()

    def test_skips_managed_tag_filtered_paths_when_tag_missing_live(self):
        nb = MagicMock()
        nb.url = "http://netbox.test"
        nb.live_get.return_value = {"count": 0, "results": []}
        nb.get.return_value = {"results": []}

        populate.clean(nb, SAMPLE_INVENTORY)

        filtered_paths = {
            call.args[0]
            for call in nb.get.call_args_list
            if call.kwargs.get("tag") == populate.MANAGED_TAG_SLUG
        }
        self.assertEqual(filtered_paths, set())
        self.assertEqual(nb.live_get.call_count, 2)


class TestReportStaleManagedObjects(unittest.TestCase):

    def test_returns_zero_without_live_managed_tag(self):
        nb = MagicMock()
        nb.dry_run = True
        nb.live_get.return_value = {"count": 0, "results": []}

        stale_total = populate.report_stale_managed_objects(nb, SAMPLE_INVENTORY)

        self.assertEqual(stale_total, 0)
        nb.find_stale.assert_not_called()

    def test_reports_stale_objects_when_live_tag_exists(self):
        nb = MagicMock()
        nb.dry_run = False
        nb.live_get.side_effect = [
            {"count": 1, "results": [{"id": 1, "slug": populate.MANAGED_TAG_SLUG}]},
            {"count": 1, "results": [{"id": 2, "slug": SAMPLE_INVENTORY["environment_tag"]}]},
        ]
        nb.find_stale.side_effect = [
            [{"id": 11, "name": "stale-site"}],
        ] + [[] for _ in range(
            len(populate.SHARED_STALE_TRACKED_PATHS) + len(populate.ENV_STALE_TRACKED_PATHS) - 1
        )]

        stale_total = populate.report_stale_managed_objects(nb, SAMPLE_INVENTORY)

        self.assertEqual(stale_total, 1)
        self.assertEqual(
            nb.find_stale.call_count,
            len(populate.SHARED_STALE_TRACKED_PATHS) + len(populate.ENV_STALE_TRACKED_PATHS),
        )


class TestPopulateIpamServiceLookup(unittest.TestCase):

    def test_service_lookup_includes_protocol(self):
        nb = make_nb()
        populate.populate_ipam(
            nb,
            SITE,
            SAMPLE_VMS_WITH_PROTOCOL_VARIANTS,
            SAMPLE_POPULATION_INTENT,
            SAMPLE_INVENTORY,
        )
        service_calls = [
            call.args[1]
            for call in nb.ensure.call_args_list
            if call.args[0] == "/ipam/services/"
        ]
        self.assertEqual(len(service_calls), 2)
        self.assertCountEqual(
            [call["protocol"] for call in service_calls],
            ["tcp", "udp"],
        )

    def test_service_defaults_include_last_seen_description(self):
        nb = make_nb()
        populate.populate_ipam(
            nb,
            SITE,
            SAMPLE_VMS,
            SAMPLE_POPULATION_INTENT,
            SAMPLE_INVENTORY,
        )
        service_defaults = [
            call.args[2]
            for call in nb.ensure.call_args_list
            if call.args[0] == "/ipam/services/"
        ]
        self.assertEqual(len(service_defaults), 1)
        self.assertIn("last-seen=", service_defaults[0]["description"])

    def test_deletes_stale_managed_service_not_seen_in_runtime(self):
        nb = make_nb()
        def get_side_effect(path, **kwargs):
            if path == populate.NB_DCIM_DEVICES and kwargs.get("name") == "pve-test":
                return {"results": [{"id": 1, "name": "pve-test", "primary_ip4": None}], "count": 1}
            if path == populate.NB_DCIM_INTERFACES and kwargs.get("device_id") == 1 and kwargs.get("name") == "vmbr0":
                return {"results": [{"id": 1, "name": "vmbr0", "primary_ip4": None}], "count": 1}
            if path == populate.NB_IPAM_IP_ADDRESSES and kwargs.get("address") == "192.168.1.40/24":
                return {"results": [], "count": 0}
            if path == populate.NB_VIRT_VIRTUAL_MACHINES and kwargs.get("name") == "test-vm@pve-test":
                return {"results": [{"id": 1, "name": "test-vm@pve-test", "primary_ip4": None}], "count": 1}
            if path == populate.NB_VIRT_INTERFACES and kwargs.get("virtual_machine_id") == 1 and kwargs.get("name") == "eth0":
                return {"results": [{"id": 1, "name": "eth0", "primary_ip4": None}], "count": 1}
            if path == populate.NB_IPAM_SERVICES and kwargs.get("parent_object_type") == "virtualization.virtualmachine" and kwargs.get("parent_object_id") == 1:
                return {
                    "results": [
                        {
                            "id": 51,
                            "name": "old-http",
                            "protocol": {"value": "tcp", "label": "TCP"},
                            "ports": [8080],
                            "tags": [
                                {"slug": "managed-by-proxmox-homelab"},
                                {"slug": "netbox-env-pve-test"},
                            ],
                        }
                    ],
                    "count": 1,
                }
            return {"results": [], "count": 0}

        nb.get.side_effect = get_side_effect

        populate.populate_ipam(
            nb,
            SITE,
            [
                {
                    **SAMPLE_VMS[0],
                    "services": [],
                }
            ],
            SAMPLE_POPULATION_INTENT,
            SAMPLE_INVENTORY,
        )

        nb.delete_object.assert_called_once()
        self.assertEqual(nb.delete_object.call_args.args[0], "/ipam/services/")


if __name__ == "__main__":
    unittest.main()
