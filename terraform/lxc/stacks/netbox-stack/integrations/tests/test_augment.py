
from populate import _augment_vms_with_declared_socket_proxy_targets
from populate import NB_IPAM_IP_ADDRESSES, NB_VIRT_INTERFACES, NB_VIRT_VIRTUAL_MACHINES


class FakeNB:
    def live_get(self, path, **params):
        if path == NB_IPAM_IP_ADDRESSES and params.get("address") == "192.168.20.20":
            return {
                "count": 1,
                "results": [
                    {
                        "address": "192.168.20.20/24",
                        "assigned_object_type": "virtualization.vminterface",
                        "assigned_object_id": 23,
                    }
                ],
            }
        return {"count": 0, "results": []}

    def get(self, path, **params):
        # Interface lookup by id
        if path == NB_VIRT_INTERFACES and params.get("id") == 23:
            return {"count": 1, "results": [{"id": 23, "virtual_machine": {"id": 23}}]}
        if path == NB_VIRT_VIRTUAL_MACHINES and params.get("id") == 23:
            return {"count": 1, "results": [{"id": 23, "name": "portainer-stack@pve"}]}
        return {"count": 0, "results": []}


def test_augment_portainer_mapping(monkeypatch):
    # Ensure token resolution works for ${lab_ip_portainer}
    monkeypatch.setenv("LAB_IP_PORTAINER", "192.168.20.20")

    stacks = {
        "portainer-stack": {
            "ip_address": "${lab_ip_portainer}/24",
            "docker_socket_proxy_targets": ["${lab_ip_portainer}"],
            "cores": 1,
            "memory": 512,
            "rootfs_size": 8,
            "tags": [],
            "vmid": 20020,
        }
    }

    vms = []
    nb = FakeNB()
    _augment_vms_with_declared_socket_proxy_targets(nb, vms, stacks)

    # Expect the portainer-stack VM to be appended with IP including /24
    assert any(vm.get("name") == "portainer-stack" and vm.get("ip", "").startswith("192.168.20.20") for vm in vms)
