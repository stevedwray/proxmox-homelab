"""Focused tests for declared docker_socket_proxy_targets augmentation.

These tests validate that each declared candidate address is processed and
mapped independently and that existing skip semantics are preserved.
"""
import unittest
from unittest.mock import MagicMock

import populate


class TestPopulateSocketProxyTargets(unittest.TestCase):

    def test_maps_multiple_candidates_independently(self):
        nb = MagicMock()
        vms = []

        # Two declared candidates mapping to two different VM/interface ids.
        stacks = {
            "stack-a": {
                "docker_socket_proxy_targets": ["10.0.0.5", "10.0.0.6"],
                "cores": 1,
                "memory": 512,
                "rootfs_size": 8,
                "description": "stack-a",
                "tags": [],
                "proxmox": {"target_node": "pve-test"},
            }
        }

        def get_side_effect(path, **kwargs):
            # IPAM lookup for 10.0.0.5
            if path == populate.NB_IPAM_IP_ADDRESSES and kwargs.get("address") == "10.0.0.5":
                return {"results": [{"assigned_object_type": "virtualization.vminterface", "assigned_object_id": 101}], "count": 1}
            if path == populate.NB_IPAM_IP_ADDRESSES and kwargs.get("address") == "10.0.0.6":
                return {"results": [{"assigned_object_type": "virtualization.vminterface", "assigned_object_id": 102}], "count": 1}

            if path == populate.NB_VIRT_INTERFACES and kwargs.get("id") == 101:
                return {"results": [{"virtual_machine": {"id": 201}}], "count": 1}
            if path == populate.NB_VIRT_INTERFACES and kwargs.get("id") == 102:
                return {"results": [{"virtual_machine": {"id": 202}}], "count": 1}

            if path == populate.NB_VIRT_VIRTUAL_MACHINES and kwargs.get("id") == 201:
                return {"results": [{"id": 201, "name": "a@pve-test"}], "count": 1}
            if path == populate.NB_VIRT_VIRTUAL_MACHINES and kwargs.get("id") == 202:
                return {"results": [{"id": 202, "name": "b@pve-test"}], "count": 1}

            return {"results": [], "count": 0}

        nb.get.side_effect = get_side_effect

        populate._augment_vms_with_declared_socket_proxy_targets(nb, vms, stacks)

        # Expect two vm defs appended, one per candidate mapping
        self.assertEqual(len(vms), 2)
        names = {v["name"] for v in vms}
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_skips_stack_when_name_already_discovered(self):
        nb = MagicMock()
        # vms already contains a VM named 'stack-a' (discovered), so augmentation should skip
        vms = [{"name": "stack-a", "ip": "10.0.0.5/24"}]
        stacks = {
            "stack-a": {"docker_socket_proxy_targets": ["10.0.0.5"], "proxmox": {"target_node": "pve-test"}}
        }

        nb.get.return_value = {"results": [], "count": 0}
        populate._augment_vms_with_declared_socket_proxy_targets(nb, vms, stacks)
        # No additional vm defs should be appended
        self.assertEqual(len(vms), 1)


if __name__ == "__main__":
    unittest.main()
