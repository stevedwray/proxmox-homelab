"""populate must not try to take an address that another VM holds as its primary IP.

NetBox answers that PATCH with a 400 ("Cannot reassign IP address while it is
designated as the primary IP for the parent object"), which aborted the whole
run when a guest existed on two nodes (live copy and stopped copy) with the
same address.
"""

import unittest
from unittest.mock import MagicMock

from test_populate_paths import SAMPLE_INVENTORY, SAMPLE_POPULATION_INTENT, SAMPLE_VMS, SITE, make_nb  # noqa: F401
import populate

ADDRESS = "192.168.1.10/24"


def _existing_ip(assigned_to=58, kind="virtualization.vminterface", holder_vm_id=58):
    return {"id": 80, "address": ADDRESS, "assigned_object_type": kind, "assigned_object_id": assigned_to,
            "assigned_object": {"id": assigned_to, "virtual_machine": {"id": holder_vm_id, "name": "x@pve-tiny"}}}


def _nb(existing_ip, holder_primary_ip=80):
    """A NetBox mock: our VM is x@pve (interface 10); the address already exists."""
    nb = make_nb()

    def get(path, **params):
        if path == populate.NB_IPAM_IP_ADDRESSES:
            return {"results": [existing_ip] if existing_ip else [], "count": 1}
        if path == populate.NB_VIRT_VIRTUAL_MACHINES and "id" in params:
            return {"results": [{"id": params["id"], "name": "x@pve-tiny", "primary_ip4": {"id": holder_primary_ip}}], "count": 1}
        if path == populate.NB_VIRT_VIRTUAL_MACHINES:
            return {"results": [{"id": 5, "name": "x@pve", "primary_ip4": None}], "count": 1}
        if path == populate.NB_VIRT_INTERFACES:
            return {"results": [{"id": 10, "name": "eth0"}], "count": 1}
        return {"results": [{"id": 1, "name": "mock", "primary_ip4": None}], "count": 1}

    nb.get.side_effect = get
    return nb


class HeldByOtherVmTest(unittest.TestCase):
    def test_primary_ip_of_another_vm_is_reported(self):
        self.assertEqual(populate._ip_held_by_other_vm(_nb(_existing_ip()), ADDRESS, 10), "x@pve-tiny")

    def test_same_interface_is_not_a_conflict(self):
        self.assertIsNone(populate._ip_held_by_other_vm(_nb(_existing_ip(assigned_to=10)), ADDRESS, 10))

    def test_other_vm_without_it_as_primary_may_still_be_moved(self):
        # NetBox allows this move, so behaviour is unchanged
        self.assertIsNone(populate._ip_held_by_other_vm(_nb(_existing_ip(), holder_primary_ip=999), ADDRESS, 10))

    def test_unassigned_or_unknown_address_is_not_a_conflict(self):
        self.assertIsNone(populate._ip_held_by_other_vm(_nb(None), ADDRESS, 10))
        unassigned = _existing_ip(assigned_to=None)
        self.assertIsNone(populate._ip_held_by_other_vm(_nb(unassigned), ADDRESS, 10))

    def test_address_on_a_device_interface_is_not_a_vm_conflict(self):
        self.assertIsNone(populate._ip_held_by_other_vm(_nb(_existing_ip(kind="dcim.interface")), ADDRESS, 10))


class PopulateIpamSkipsHeldAddressTest(unittest.TestCase):
    def _run(self, nb):
        populate.populate_ipam(nb, SITE, SAMPLE_VMS, SAMPLE_POPULATION_INTENT, SAMPLE_INVENTORY)

    def _ip_ensures(self, nb):
        return [c for c in nb.ensure.call_args_list if c.args[0] == populate.NB_IPAM_IP_ADDRESSES]

    def test_held_address_is_not_reassigned_and_primary_is_left_alone(self):
        nb = _nb(_existing_ip())
        self._run(nb)
        self.assertFalse([c for c in self._ip_ensures(nb) if c.args[1].get("address") == ADDRESS],
                         "must not ensure (and so PATCH) an address another VM holds as primary")
        primary_patches = [c for c in nb.patch_object.call_args_list
                           if len(c.args) > 2 and isinstance(c.args[2], dict) and "primary_ip4" in c.args[2]]
        self.assertEqual(primary_patches, [])

    def test_unheld_address_is_still_ensured_as_before(self):
        nb = _nb(None)
        self._run(nb)
        self.assertTrue([c for c in self._ip_ensures(nb) if c.args[1].get("address") == ADDRESS])


if __name__ == "__main__":
    unittest.main()
