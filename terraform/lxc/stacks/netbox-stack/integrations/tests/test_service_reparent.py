import unittest
from unittest.mock import MagicMock, patch

import populate


class TestServiceReparenting(unittest.TestCase):

    def test_reprobe_appended_vm_populates_services(self):
        nb = MagicMock()
        vms = []

        stacks = {
            "portainer-stack": {
                "docker_socket_proxy_targets": ["10.0.0.5"],
                "cores": 1,
                "memory": 512,
                "rootfs_size": 8,
                "description": "portainer",
                "tags": [],
                "proxmox": {"target_node": "pve-test"},
            }
        }

        def live_get_side_effect(path, **kwargs):
            if path == populate.NB_IPAM_IP_ADDRESSES and kwargs.get("address") == "10.0.0.5":
                return {"results": [{"assigned_object_type": "virtualization.vminterface", "assigned_object_id": 101}], "count": 1}
            return {"results": [], "count": 0}

        def get_side_effect(path, **kwargs):
            if path == populate.NB_VIRT_INTERFACES and kwargs.get("id") == 101:
                return {"results": [{"virtual_machine": {"id": 201}}], "count": 1}
            if path == populate.NB_VIRT_VIRTUAL_MACHINES and kwargs.get("id") == 201:
                return {"results": [{"id": 201, "name": "portainer-stack@pve"}], "count": 1}
            return {"results": [], "count": 0}

        nb.live_get.side_effect = live_get_side_effect
        nb.get.side_effect = get_side_effect

        with patch.dict("os.environ", {"DOCKER_SOCKET_PROXY_URL_TEMPLATE": "http://{guest_ip}:2375"}):
            with patch("populate._build_socket_proxy_services") as mock_probe:
                mock_probe.return_value = [{"name": "portainer-agent-9001", "port": 9001, "protocol": "tcp", "source": "socket-proxy"}]
                populate._augment_vms_with_declared_socket_proxy_targets(nb, vms, stacks)

        self.assertEqual(len(vms), 1)
        self.assertEqual(len(vms[0].get("services", [])), 1)
        self.assertEqual(vms[0]["services"][0]["name"], "portainer-agent-9001")

    def test_try_reparent_runtime_service_patches_unique_match(self):
        nb = MagicMock()
        vm = {"id": 201, "name": "portainer-stack"}
        vm_env = "pve-test"
        svc_def = {"name": "svc1-8080", "port": 8080, "protocol": "tcp", "source": "socket-proxy"}

        existing_service = {
            "id": 999,
            "name": "svc1-8080",
            "protocol": "tcp",
            "ports": [8080],
            "parent_object_type": "virtualization.virtualmachine",
            "parent_object_id": 123,
            "tags": [{"slug": populate.MANAGED_TAG_SLUG}, {"slug": "runtime-source-socket-proxy"}],
        }

        nb.get.return_value = {"results": [existing_service], "count": 1}

        with patch.dict("os.environ", {"REPARENT_RUNTIME_SOCKET_PROXY": "true"}):
            res = populate._try_reparent_runtime_service(nb, vm, svc_def, vm_env)

        self.assertTrue(res)
        nb.patch_object.assert_called_once()


if __name__ == "__main__":
    unittest.main()
