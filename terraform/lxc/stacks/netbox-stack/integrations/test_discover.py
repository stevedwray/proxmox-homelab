"""Focused tests for topology discovery boundary decisions."""

import os
import unittest
from unittest.mock import patch
import json

import discover


class TestResolvePortainerEndpoint(unittest.TestCase):
    def test_uses_lab_ip_portainer_when_service_env_is_unset(self):
        stack_yamls = {
            "portainer-stack": {
                "ip_address": "10.57.1.20/24",
            }
        }

        with patch.dict(os.environ, {"LAB_IP_PORTAINER": "10.57.1.25"}, clear=True):
            ip, url = discover._resolve_portainer_endpoint(stack_yamls)

        self.assertEqual(ip, "10.57.1.25")
        self.assertEqual(url, "https://10.57.1.25:9443")

    def test_uses_declared_portainer_stack_ip_when_env_is_unset(self):
        stack_yamls = {
            "portainer-stack": {
                "ip_address": "10.57.1.20/24",
            }
        }

        with patch.dict(os.environ, {}, clear=True):
            ip, url = discover._resolve_portainer_endpoint(stack_yamls)

        self.assertEqual(ip, "10.57.1.20")
        self.assertEqual(url, "https://10.57.1.20:9443")

    def test_env_override_still_wins(self):
        stack_yamls = {
            "portainer-stack": {
                "ip_address": "10.57.1.20/24",
            }
        }

        with patch.dict(
            os.environ,
            {
                "PORTAINER_SERVER_IP": "192.168.1.4",
                "PORTAINER_URL": "https://portainer.example.test:9443",
            },
            clear=True,
        ):
            ip, url = discover._resolve_portainer_endpoint(stack_yamls)

        self.assertEqual(ip, "192.168.1.4")
        self.assertEqual(url, "https://portainer.example.test:9443")

    def test_ignores_unresolved_service_ip_template(self):
        stack_yamls = {
            "portainer-stack": {
                "ip_address": "10.57.1.20/24",
            }
        }

        with patch.dict(
            os.environ,
            {
                "PORTAINER_SERVER_IP": "${LAB_IP_PORTAINER}",
                "LAB_IP_PORTAINER": "10.57.1.25",
            },
            clear=True,
        ):
            ip, url = discover._resolve_portainer_endpoint(stack_yamls)

        self.assertEqual(ip, "10.57.1.25")
        self.assertEqual(url, "https://10.57.1.25:9443")

    def test_ignores_unresolved_portainer_url_template(self):
        stack_yamls = {
            "portainer-stack": {
                "ip_address": "10.57.1.20/24",
            }
        }

        with patch.dict(
            os.environ,
            {
                "LAB_IP_PORTAINER": "10.57.1.25",
                "PORTAINER_URL": "${PORTAINER_BASE_URL}",
            },
            clear=True,
        ):
            ip, url = discover._resolve_portainer_endpoint(stack_yamls)

        self.assertEqual(ip, "10.57.1.25")
        self.assertEqual(url, "https://10.57.1.25:9443")

    def test_raises_when_no_portainer_endpoint_is_available(self):
        # Portainer is optional; resolution should return (None, None)
        with patch.dict(os.environ, {}, clear=True):
            ip, url = discover._resolve_portainer_endpoint({})

        self.assertIsNone(ip)
        self.assertIsNone(url)


class TestProxmoxHostContext(unittest.TestCase):
    def test_selects_preferred_vmbr0_address_for_target_node(self):
        proxmox_data = {
            "networks": {
                "pve-test": [
                    {"iface": "nic1", "cidr": "192.168.1.41/24"},
                    {"iface": "vmbr0", "cidr": "192.168.1.40/24"},
                ]
            }
        }

        address, iface = discover._select_proxmox_host_address(
            proxmox_data,
            target_node="pve-test",
        )

        self.assertEqual(address, "192.168.1.40/24")
        self.assertEqual(iface, "vmbr0")

    def test_builds_proxmox_context_from_env_selected_node(self):
        proxmox_data = {
            "networks": {
                "pve-test": [
                    {"iface": "vmbr0", "cidr": "192.168.1.40/24"},
                ]
            }
        }

        with patch.dict(os.environ, {"TF_VAR_proxmox_node": "pve-test"}, clear=True):
            result = discover.build_proxmox_context(proxmox_data)

        self.assertEqual(result["target_node"], "pve-test")
        self.assertEqual(result["host_address"], "192.168.1.40/24")
        self.assertEqual(result["host_interface"], "vmbr0")


class TestBuildVmListRuntimeState(unittest.TestCase):
    def test_uses_runtime_inspector_without_portainer_endpoint(self):
        proxmox_data = {
            "containers": [
                {
                    "name": "netbox-stack",
                    "status": "running",
                    "type": "lxc",
                    "vmid": 40012,
                    "node": "pve-test",
                    "config": {
                        "net0": "name=eth0,ip=10.57.3.12/24",
                        "cores": "4",
                        "memory": "4096",
                        "description": "live description",
                        "tags": "netbox;platform",
                    },
                    "mounts": [{"type": "rootfs", "size": "34G"}],
                }
            ]
        }
        stack_yamls = {
            "netbox-stack": {
                "ip_address": "10.57.99.12/24",
                "cores": 2,
                "memory": 2048,
                "rootfs_size": 8,
                "tags": ["stale"],
            }
        }

        vms = discover.build_vm_list(
            proxmox_data=proxmox_data,
            stack_yamls=stack_yamls,
            portainer=None,
            runtime_inspector=lambda container: [
                {"name": "netbox-netbox-1-8080", "port": 8080, "protocol": "tcp"}
            ],
        )

        self.assertEqual(vms[0]["ip"], "10.57.3.12/24")
        self.assertEqual(vms[0]["vcpus"], 4)
        self.assertEqual(vms[0]["memory"], 4096)
        self.assertEqual(vms[0]["disk"], 34)
        self.assertEqual(vms[0]["description"], "live description")
        self.assertEqual(vms[0]["tags"], ["netbox", "platform"])
        self.assertEqual(
            vms[0]["services"],
            [{"name": "netbox-netbox-1-8080", "port": 8080, "protocol": "tcp"}],
        )

    def test_skips_container_without_live_ip_even_if_stack_yaml_has_one(self):
        proxmox_data = {
            "containers": [
                {
                    "name": "netbox-stack",
                    "status": "running",
                    "type": "lxc",
                    "vmid": 40012,
                    "node": "pve-test",
                    "config": {},
                    "mounts": [],
                }
            ]
        }
        stack_yamls = {
            "netbox-stack": {
                "ip_address": "10.57.3.12/24",
            }
        }

        vms = discover.build_vm_list(
            proxmox_data=proxmox_data,
            stack_yamls=stack_yamls,
            portainer=None,
            runtime_inspector=lambda container: [],
        )

        self.assertEqual(vms, [])

    def test_uses_runtime_inspector_object_when_passed(self):
        proxmox_data = {
            "containers": [
                {
                    "name": "netbox-stack",
                    "status": "running",
                    "type": "lxc",
                    "vmid": 40012,
                    "node": "pve-test",
                    "config": {"net0": "name=eth0,ip=10.57.3.12/24"},
                    "mounts": [],
                }
            ]
        }

        class ObjInspector:
            def __init__(self):
                self.called = False
                self.args = None

            def inspect(self, container, portainer_ep=None):
                self.called = True
                self.args = (container, portainer_ep)
                return [{"name": "obj-service", "port": 1111, "protocol": "tcp"}]

        inspector = ObjInspector()

        vms = discover.build_vm_list(
            proxmox_data=proxmox_data,
            stack_yamls={},
            portainer=None,
            runtime_inspector=inspector,
        )

        self.assertTrue(inspector.called)
        self.assertEqual(vms[0]["services"], [{"name": "obj-service", "port": 1111, "protocol": "tcp"}])

    def test_prefers_portainer_endpoint_when_present(self):
        proxmox_data = {
            "containers": [
                {
                    "name": "netbox-stack",
                    "status": "running",
                    "type": "lxc",
                    "vmid": 40012,
                    "node": "pve-test",
                    "config": {"net0": "name=eth0,ip=10.57.3.12/24"},
                    "mounts": [],
                }
            ]
        }

        class FakePortainer:
            def get_endpoints(self):
                return [{"Name": "netbox-stack", "URL": "tcp://10.57.3.12:2375", "Id": 1, "Status": 1}]

            def get_containers(self, endpoint_id):
                return [{"Names": ["/netbox-stack"], "Ports": [{"PublicPort": 8080, "Type": "tcp"}]}]

        fake_portainer = FakePortainer()

        # Provide a legacy callable to ensure Portainer still wins when present
        vms = discover.build_vm_list(
            proxmox_data=proxmox_data,
            stack_yamls={},
            portainer=fake_portainer,
            runtime_inspector=lambda container: [{"name": "should-not-be-used", "port": 1, "protocol": "tcp"}],
        )

        self.assertEqual(
            vms[0]["services"],
            [{"name": "netbox-stack-8080", "port": 8080, "protocol": "tcp", "source": "portainer"}],
        )

    def test_uses_socket_proxy_when_env_set(self):
        proxmox_data = {
            "containers": [
                {
                    "name": "netbox-stack",
                    "status": "running",
                    "type": "lxc",
                    "vmid": 40012,
                    "node": "pve-test",
                    "config": {"net0": "name=eth0,ip=10.57.3.12/24"},
                    "mounts": [],
                }
            ]
        }

        # Summary list returned by GET /containers/json
        fake_list = json.dumps(
            [
                {
                    "Id": "abcd1234",
                    "Names": ["/netbox-netbox-1"],
                    "Ports": [{"PublicPort": 8080, "Type": "tcp"}],
                }
            ]
        ).encode()

        # Inspect payload returned by GET /containers/{id}/json
        fake_inspect = json.dumps(
            {
                "Name": "/netbox-netbox-1",
                "Names": ["/netbox-netbox-1"],
                "NetworkSettings": {
                    "Ports": {
                        "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],  # nosec B104 — test fixture data
                        "53/udp": [{"HostIp": "0.0.0.0", "HostPort": "53"}],  # nosec B104 — test fixture data
                    },
                    "Networks": {"bridge": {"IPAddress": "10.57.3.12"}},
                },
            }
        ).encode()

        class FakeResp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(req, context=None):
            url = getattr(req, 'full_url', req if isinstance(req, str) else '')
            if url.endswith('/containers/json') or url.endswith('/containers/json?all=1'):
                return FakeResp(fake_list)
            if url.endswith('/containers/abcd1234/json'):
                return FakeResp(fake_inspect)
            return FakeResp(b'[]')

        # Use the per-guest socket-proxy URL template that substitutes the
        # discovered guest IP into the proxy host address.
        with patch.dict(os.environ, {"DOCKER_SOCKET_PROXY_URL_TEMPLATE": "http://{guest_ip}:2375"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                vms = discover.build_vm_list(
                    proxmox_data=proxmox_data, stack_yamls={}, portainer=None, runtime_inspector=None
                )

        self.assertEqual(
            vms[0]["services"],
            [
                {"name": "netbox-netbox-1-8080", "port": 8080, "protocol": "tcp", "source": "socket-proxy"},
                {"name": "netbox-netbox-1-53", "port": 53, "protocol": "udp", "source": "socket-proxy"},
            ],
        )


class TestBuildTopology(unittest.TestCase):
    def test_forwards_portainer_to_build_vm_list(self):
        fake_proxmox = {"containers": []}
        fake_portainer = object()

        with patch.object(discover, "build_vm_list", return_value=[]) as build_vm_list:
            result = discover.build_topology(
                proxmox_data=fake_proxmox,
                stack_yamls={},
                portainer=fake_portainer,
            )

        self.assertEqual(result, [])
        build_vm_list.assert_called_once_with(fake_proxmox, {}, portainer=fake_portainer)


if __name__ == "__main__":
    unittest.main()
