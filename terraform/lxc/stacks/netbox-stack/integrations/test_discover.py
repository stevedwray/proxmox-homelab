"""Focused tests for topology discovery boundary decisions."""

import os
import unittest
from unittest.mock import patch

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

    def test_raises_when_no_portainer_endpoint_is_available(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Portainer endpoint is unresolved"):
                discover._resolve_portainer_endpoint({})


if __name__ == "__main__":
    unittest.main()
