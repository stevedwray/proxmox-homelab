"""Focused tests for Proxmox discovery environment resolution."""

import os
import unittest
from unittest.mock import patch

from proxmox_client import ProxmoxClient


class TestProxmoxClientEnvResolution(unittest.TestCase):
    def test_prefers_readonly_env_names(self):
        with patch.dict(
            os.environ,
            {
                "PROXMOX_HOST": "pve-test.example.test",
                "PROXMOX_READONLY_TOKEN_ID": "readonly@pve!token",
                "PROXMOX_READONLY_TOKEN_SECRET": "ro-secret",
                "PROXMOX_TOKEN_ID": "automation@pve!terraform",
                "TF_VAR_pm_api_token_secret": "secret-value",
            },
            clear=True,
        ):
            client = ProxmoxClient()

        self.assertEqual(client.token_id, "readonly@pve!token")
        self.assertEqual(client.token_secret, "ro-secret")

    def test_uses_tf_var_token_secret_fallback(self):
        with patch.dict(
            os.environ,
            {
                "PROXMOX_HOST": "pve-test.example.test",
                "PROXMOX_TOKEN_ID": "automation@pve!terraform",
                "TF_VAR_pm_api_token_secret": "secret-value",
            },
            clear=True,
        ):
            client = ProxmoxClient()

        self.assertEqual(client.url, "https://pve-test.example.test:8006")
        self.assertEqual(client.token_id, "automation@pve!terraform")
        self.assertEqual(client.token_secret, "secret-value")

    def test_uses_tf_var_url_and_token_id_fallbacks(self):
        with patch.dict(
            os.environ,
            {
                "TF_VAR_proxmox_api_url": "https://pve.example.test:8006/api2/json",
                "TF_VAR_pm_api_token_id": "automation@pve!terraform",
                "TF_VAR_pm_api_token_secret": "secret-value",
            },
            clear=True,
        ):
            client = ProxmoxClient()

        self.assertEqual(client.url, "https://pve.example.test:8006")
        self.assertEqual(client.token_id, "automation@pve!terraform")
        self.assertEqual(client.token_secret, "secret-value")

    def test_raises_when_secret_is_missing_across_supported_names(self):
        with patch.dict(
            os.environ,
            {
                "PROXMOX_HOST": "pve-test.example.test",
                "PROXMOX_TOKEN_ID": "automation@pve!terraform",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                ProxmoxClient()


if __name__ == "__main__":
    unittest.main()
