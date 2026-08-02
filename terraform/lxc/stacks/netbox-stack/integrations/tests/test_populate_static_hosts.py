import unittest
from unittest.mock import MagicMock

import populate


class TestPopulateStaticHosts(unittest.TestCase):
    """Covers the framework.gibbsgreatly.xyz static-host + services case
    (docs/framework-ubuntu/platform-integration-plan.md, Plan C) as well as
    the plain device-only case that pve-test-vm/linux-desktop/argon already
    rely on -- must not regress just because services support was added.
    """

    def _make_nb(self):
        nb = MagicMock()

        def get_side_effect(path, **kwargs):
            if path == populate.NB_DCIM_DEVICE_TYPES and kwargs.get("model") == "Generic Device":
                return {"results": [{"id": 1}], "count": 1}
            if path == populate.NB_DCIM_DEVICE_ROLES and "slug" in kwargs:
                return {"results": [{"id": 10, "slug": kwargs["slug"]}], "count": 1}
            return {"results": [], "count": 0}

        nb.get.side_effect = get_side_effect

        def ensure_side_effect(path, lookup, defaults=None, **kwargs):
            defaults = defaults or {}
            if path == populate.NB_DCIM_DEVICE_ROLES:
                return {"id": 10, **lookup}
            if path == populate.NB_DCIM_DEVICES:
                return {"id": 100, "name": lookup.get("name"), "primary_ip4": None}
            if path == populate.NB_DCIM_INTERFACES:
                return {"id": 200}
            if path == populate.NB_IPAM_IP_ADDRESSES:
                return {"id": 300}
            if path == populate.NB_IPAM_SERVICES:
                return {"id": 400, **lookup, **defaults}
            return {"id": 999}

        nb.ensure.side_effect = ensure_side_effect
        return nb

    def test_device_without_services_creates_no_service(self):
        nb = self._make_nb()
        site = {"id": 1}

        populate.populate_static_hosts(nb, site, [
            {"name": "linux-desktop", "role": "workstation", "ip": "192.168.1.104"},
        ])

        service_calls = [c for c in nb.ensure.call_args_list if c.args[0] == populate.NB_IPAM_SERVICES]
        self.assertEqual(service_calls, [])

    def test_framework_host_registers_device_and_all_declared_services(self):
        nb = self._make_nb()
        site = {"id": 1}

        populate.populate_static_hosts(nb, site, [
            {
                "name": "framework",
                "role": "ai-workstation",
                "ip": "192.168.1.8",
                "description": "framework.gibbsgreatly.xyz",
                "services": [
                    {"name": "lmstudio", "port": 8090, "protocol": "tcp"},
                    {"name": "llamacpp", "port": 8080, "protocol": "tcp"},
                    {"name": "ollama", "port": 11434, "protocol": "tcp"},
                    {"name": "openwebui", "port": 8081, "protocol": "tcp"},
                    {"name": "searxng", "port": 8082, "protocol": "tcp"},
                ],
            },
        ])

        device_calls = [c for c in nb.ensure.call_args_list if c.args[0] == populate.NB_DCIM_DEVICES]
        self.assertEqual(len(device_calls), 1)
        self.assertEqual(device_calls[0].args[1]["name"], "framework")

        service_calls = [c for c in nb.ensure.call_args_list if c.args[0] == populate.NB_IPAM_SERVICES]
        self.assertEqual(len(service_calls), 5)

        service_names = {c.args[1]["name"] for c in service_calls}
        self.assertEqual(service_names, {"lmstudio", "llamacpp", "ollama", "openwebui", "searxng"})

        for call in service_calls:
            lookup, defaults = call.args[1], call.args[2]
            self.assertEqual(lookup["parent_object_type"], "dcim.device")
            self.assertEqual(lookup["parent_object_id"], 100)
            self.assertEqual(defaults["parent_object_type"], "dcim.device")
            self.assertEqual(defaults["parent_object_id"], 100)

    def test_service_missing_port_raises_clear_error(self):
        nb = self._make_nb()
        site = {"id": 1}

        with self.assertRaises(KeyError):
            populate.populate_static_hosts(nb, site, [
                {
                    "name": "framework",
                    "role": "ai-workstation",
                    "ip": "192.168.1.8",
                    "services": [{"name": "broken"}],
                },
            ])


if __name__ == "__main__":
    unittest.main()
