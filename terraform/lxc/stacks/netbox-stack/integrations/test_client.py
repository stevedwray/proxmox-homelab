"""Focused tests for NetBox client reconciliation behavior."""

import unittest
from unittest.mock import patch

from client import NetBoxClient


class TestNetBoxClientEnsure(unittest.TestCase):
    def test_uses_lab_ip_netbox_fallback_for_url(self):
        with patch.dict(
            "os.environ",
            {"LAB_IP_NETBOX": "192.168.40.12", "NETBOX_SUPERUSER_API_TOKEN": "token"},
            clear=True,
        ):
            nb = NetBoxClient()

        self.assertEqual(nb.url, "http://192.168.40.12:8080")

    def test_prefers_neutral_api_token(self):
        with patch.dict(
            "os.environ",
            {
                "LAB_IP_NETBOX": "192.168.40.12",
                "NETBOX_API_TOKEN": "neutral-token",
                "NETBOX_SUPERUSER_API_TOKEN": "super-token",
            },
            clear=True,
        ):
            nb = NetBoxClient()

        self.assertEqual(nb.token, "neutral-token")

    def test_updates_existing_object_when_fields_drift(self):
        with patch.object(NetBoxClient, "_request") as request:
            request.side_effect = [
                {"count": 1, "results": [{"id": 5, "name": "vm-1", "status": "offline"}]},
                {"id": 5},
            ]
            nb = NetBoxClient(url="http://netbox.test", token="token")
            obj = nb.ensure(
                "/virtualization/virtual-machines/",
                {"name": "vm-1"},
                {"status": "active"},
            )

        self.assertEqual(obj["status"], "active")
        request.assert_any_call(
            "PATCH",
            "/virtualization/virtual-machines/5/",
            data={"status": "active"},
        )

    def test_skips_patch_for_unmanaged_existing_object_when_guarded(self):
        existing = {
            "id": 5,
            "name": "vm-1",
            "status": "offline",
            "tags": [{"slug": "operator-owned"}],
        }
        with patch.object(NetBoxClient, "_request") as request:
            request.return_value = {"count": 1, "results": [existing]}
            nb = NetBoxClient(url="http://netbox.test", token="token")
            obj = nb.ensure(
                "/virtualization/virtual-machines/",
                {"name": "vm-1"},
                {"status": "active", "tags": [{"slug": "managed-by-proxmox-homelab"}]},
                managed_tag_slug="managed-by-proxmox-homelab",
                allow_unmanaged_patch=False,
            )

        self.assertEqual(obj["status"], "offline")
        self.assertEqual(request.call_count, 1)
        request.assert_called_once_with("GET", "/virtualization/virtual-machines/", params={"name": "vm-1"})

    def test_patches_managed_existing_object_when_guarded(self):
        with patch.object(NetBoxClient, "_request") as request:
            request.side_effect = [
                {
                    "count": 1,
                    "results": [{
                        "id": 5,
                        "name": "vm-1",
                        "status": "offline",
                        "tags": [{"slug": "managed-by-proxmox-homelab"}],
                    }],
                },
                {"id": 5},
            ]
            nb = NetBoxClient(url="http://netbox.test", token="token")
            obj = nb.ensure(
                "/virtualization/virtual-machines/",
                {"name": "vm-1"},
                {"status": "active"},
                managed_tag_slug="managed-by-proxmox-homelab",
                allow_unmanaged_patch=False,
            )

        self.assertEqual(obj["status"], "active")
        request.assert_any_call(
            "PATCH",
            "/virtualization/virtual-machines/5/",
            data={"status": "active"},
        )

    def test_allowed_patch_fields_filters_changes(self):
        with patch.object(NetBoxClient, "_request") as request:
            request.side_effect = [
                {
                    "count": 1,
                    "results": [{
                        "id": 5,
                        "name": "vm-1",
                        "status": "offline",
                        "description": "old",
                        "tags": [{"slug": "managed-by-proxmox-homelab"}],
                    }],
                },
                {"id": 5},
            ]
            nb = NetBoxClient(url="http://netbox.test", token="token")
            obj = nb.ensure(
                "/virtualization/virtual-machines/",
                {"name": "vm-1"},
                {"status": "active", "description": "new"},
                allowed_patch_fields={"description"},
                managed_tag_slug="managed-by-proxmox-homelab",
                allow_unmanaged_patch=False,
            )

        self.assertEqual(obj["status"], "offline")
        self.assertEqual(obj["description"], "new")
        request.assert_any_call(
            "PATCH",
            "/virtualization/virtual-machines/5/",
            data={"description": "new"},
        )

    def test_dry_run_create_returns_synthetic_object(self):
        with patch.object(NetBoxClient, "_request", return_value={"count": 0, "results": []}):
            nb = NetBoxClient(url="http://netbox.test", token="token", dry_run=True)
            obj = nb.ensure("/dcim/sites/", {"name": "Homelab"}, {"slug": "homelab"})

        self.assertLess(obj["id"], 0)
        self.assertEqual(obj["slug"], "homelab")

    def test_dry_run_get_can_find_synthetic_object(self):
        with patch.object(NetBoxClient, "_request", return_value={"count": 0, "results": []}):
            nb = NetBoxClient(url="http://netbox.test", token="token", dry_run=True)
            nb.ensure("/dcim/sites/", {"name": "Homelab"}, {"slug": "homelab"})
            results = nb.get("/dcim/sites/", name="Homelab")

        self.assertEqual(results["count"], 1)
        self.assertEqual(results["results"][0]["name"], "Homelab")

    def test_live_get_bypasses_dry_run_synthetic_objects(self):
        with patch.object(NetBoxClient, "_request", return_value={"count": 0, "results": []}) as request:
            nb = NetBoxClient(url="http://netbox.test", token="token", dry_run=True)
            nb.ensure("/dcim/sites/", {"name": "Homelab"}, {"slug": "homelab"})
            results = nb.live_get("/dcim/sites/", name="Homelab")

        self.assertEqual(results["count"], 0)
        request.assert_called_with("GET", "/dcim/sites/", params={"name": "Homelab"})

    def test_legacy_lookup_can_migrate_existing_object(self):
        with patch.object(NetBoxClient, "_request") as request:
            request.side_effect = [
                {"count": 0, "results": []},
                {"count": 1, "results": [{"id": 7, "name": "legacy-vm", "status": "active"}]},
                {"id": 7},
            ]
            nb = NetBoxClient(url="http://netbox.test", token="token")
            obj = nb.ensure(
                "/virtualization/virtual-machines/",
                {"name": "legacy-vm@pve-test"},
                {"status": "active"},
                legacy_lookups=[{"name": "legacy-vm"}],
            )

        self.assertEqual(obj["name"], "legacy-vm@pve-test")
        request.assert_any_call(
            "PATCH",
            "/virtualization/virtual-machines/7/",
            data={"name": "legacy-vm@pve-test"},
        )

    def test_choice_value_dict_matches_expected_string(self):
        with patch.object(NetBoxClient, "_request") as request:
            request.side_effect = [
                {"count": 1, "results": [{"id": 9, "name": "portainer", "protocol": {"value": "tcp", "label": "TCP"}}]},
            ]
            nb = NetBoxClient(url="http://netbox.test", token="token")
            obj = nb.ensure(
                "/ipam/services/",
                {"name": "portainer"},
                {"protocol": "tcp"},
            )

        self.assertEqual(obj["id"], 9)
        self.assertEqual(request.call_count, 1)

    def test_delete_object_honors_dry_run(self):
        with patch.object(NetBoxClient, "_request", return_value={"count": 0, "results": []}):
            nb = NetBoxClient(url="http://netbox.test", token="token", dry_run=True)
            nb._planned_objects["/ipam/ip-addresses/"][5] = {"id": 5, "address": "192.168.1.2/24"}

            nb.delete_object("/ipam/ip-addresses/", {"id": 5, "address": "192.168.1.2/24"})

        self.assertNotIn(5, nb._planned_objects["/ipam/ip-addresses/"])


class TestNetBoxClientStale(unittest.TestCase):
    def test_find_stale_returns_managed_objects_not_in_desired_lookups(self):
        with patch.object(NetBoxClient, "_request") as request:
            request.side_effect = [
                {"count": 1, "results": [{"id": 1, "name": "keep-me", "status": "active"}]},
                {"count": 2, "results": [
                    {"id": 1, "name": "keep-me", "tags": [{"slug": "managed-by-proxmox-homelab"}]},
                    {"id": 2, "name": "stale-me", "tags": [{"slug": "managed-by-proxmox-homelab"}]},
                ]},
            ]
            nb = NetBoxClient(url="http://netbox.test", token="token")
            nb.ensure("/dcim/devices/", {"name": "keep-me"}, {"status": "active"})
            stale = nb.find_stale("/dcim/devices/", tag="managed-by-proxmox-homelab")

        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["name"], "stale-me")


if __name__ == "__main__":
    unittest.main()
