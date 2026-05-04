"""Tests for read-only Authentik discovery and drift classification."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parent / "discover-authentik-edge.py"
SPEC = importlib.util.spec_from_file_location("discover_authentik_edge", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

AuthentikApiClient = MODULE.AuthentikApiClient
discover_authentik_drift = MODULE.discover_authentik_drift
_resolve_token = MODULE._resolve_token


def _write_manifest(path: Path, stack: str, route: str, host: str, mode: str) -> None:
    path.write_text(
        f"""apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: {stack}-edge
  stack: {stack}
spec:
  routes:
    - name: {route}
      host: {host}
      backend:
        type: url
        url: http://10.57.1.20:9000
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: {mode}
""",
        encoding="utf-8",
    )


class FakeClient:
    def __init__(
        self,
        applications: list[dict],
        providers: list[dict],
        oauth2_providers: list[dict],
        outposts: list[dict],
    ) -> None:
        self._applications = applications
        self._providers = providers
        self._oauth2_providers = oauth2_providers
        self._outposts = outposts
        self.request_methods = ["GET", "GET", "GET", "GET"]

    def fetch_applications(self):
        return self._applications

    def fetch_proxy_providers(self):
        return self._providers

    def fetch_oauth2_providers(self):
        return self._oauth2_providers

    def fetch_outposts(self):
        return self._outposts


class TestDiscoverAuthentikDrift(unittest.TestCase):
    def test_matching_route_returns_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "portainer.yaml"
            _write_manifest(
                manifest,
                stack="portainer-stack",
                route="portainer",
                host="portainer.lab.gibbsgreatly.xyz",
                mode="forwardAuth",
            )

            client = FakeClient(
                applications=[
                    {
                        "pk": 101,
                        "name": "edge-portainer-stack-portainer-app",
                        "slug": "edge-portainer-stack-portainer",
                        "meta_launch_url": "https://portainer.lab.gibbsgreatly.xyz/",
                        "provider": 201,
                    }
                ],
                providers=[
                    {
                        "pk": 201,
                        "name": "edge-portainer-stack-portainer-provider",
                        "external_host": "https://portainer.lab.gibbsgreatly.xyz",
                    }
                ],
                oauth2_providers=[],
                outposts=[
                    {
                        "pk": 301,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [201],
                    }
                ],
            )

            result = discover_authentik_drift([manifest], client)

        self.assertTrue(result.ok)
        self.assertEqual(1, len(result.route_results))
        self.assertEqual("matching", result.route_results[0].classification)
        self.assertEqual(3, len(result.route_results[0].identifiers))
        self.assertEqual(0, len(result.unmanaged))

    def test_ambiguous_and_unmanaged_are_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "netbox.yaml"
            _write_manifest(
                manifest,
                stack="netbox-stack",
                route="netbox",
                host="netbox.lab.gibbsgreatly.xyz",
                mode="forwardAuth",
            )

            client = FakeClient(
                applications=[],
                providers=[
                    {
                        "pk": 1,
                        "name": "edge-netbox-stack-netbox-provider",
                        "external_host": "https://netbox.lab.gibbsgreatly.xyz",
                    },
                    {
                        "pk": 2,
                        "name": "legacy-netbox-provider",
                        "external_host": "https://netbox.lab.gibbsgreatly.xyz",
                    },
                    {
                        "pk": 9,
                        "name": "edge-orphan-provider",
                        "external_host": "https://orphan.lab.gibbsgreatly.xyz",
                    },
                ],
                oauth2_providers=[],
                outposts=[],
            )

            result = discover_authentik_drift([manifest], client)

        self.assertFalse(result.ok)
        self.assertEqual("ambiguous", result.route_results[0].classification)
        self.assertEqual(1, len(result.stop_conditions))
        self.assertEqual(
            ["edge-netbox-stack-netbox-provider", "edge-orphan-provider"],
            [obj.name for obj in result.unmanaged],
        )

    def test_non_forwardauth_route_with_existing_objects_is_differing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "authentik.yaml"
            _write_manifest(
                manifest,
                stack="authentik-stack",
                route="authentik",
                host="authentik.lab.gibbsgreatly.xyz",
                mode="none",
            )

            client = FakeClient(
                applications=[
                    {
                        "pk": 11,
                        "name": "edge-authentik-stack-authentik-app",
                        "slug": "edge-authentik-stack-authentik",
                        "meta_launch_url": "https://authentik.lab.gibbsgreatly.xyz/",
                    }
                ],
                providers=[
                    {
                        "pk": 12,
                        "name": "edge-authentik-stack-authentik-provider",
                        "external_host": "https://authentik.lab.gibbsgreatly.xyz",
                    }
                ],
                oauth2_providers=[],
                outposts=[],
            )

            result = discover_authentik_drift([manifest], client)

        self.assertFalse(result.ok)
        self.assertEqual("differing", result.route_results[0].classification)
        self.assertEqual(0, len(result.stop_conditions))

    def test_oidc_route_with_existing_objects_is_matching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "harbor.yaml"
            _write_manifest(
                manifest,
                stack="harbor-stack",
                route="harbor",
                host="harbor.lab.gibbsgreatly.xyz",
                mode="oidc",
            )

            client = FakeClient(
                applications=[
                    {
                        "pk": 21,
                        "name": "edge-harbor-stack-harbor-app",
                        "slug": "edge-harbor-stack-harbor",
                        "meta_launch_url": "https://harbor.lab.gibbsgreatly.xyz/",
                        "provider": 22,
                    }
                ],
                providers=[],
                oauth2_providers=[
                    {
                        "pk": 22,
                        "name": "edge-harbor-stack-harbor-provider",
                        "client_id": "harbor",
                        "redirect_uris": [
                            {"url": "https://harbor.lab.gibbsgreatly.xyz/c/oidc/callback"}
                        ],
                    }
                ],
                outposts=[],
            )

            result = discover_authentik_drift([manifest], client)

        self.assertTrue(result.ok)
        self.assertEqual("matching", result.route_results[0].classification)
        self.assertEqual(2, len(result.route_results[0].identifiers))


class TestReadOnlyApiClient(unittest.TestCase):
    def test_client_uses_get_only_and_follows_pagination(self):
        calls: list[str] = []

        class DummyResponse:
            def __init__(self, payload: dict):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        payloads = {
            "https://example.local/api/v3/core/applications/?page_size=200": {
                "results": [{"pk": 1, "name": "app-a"}],
                "next": "https://example.local/api/v3/core/applications/?page=2",
            },
            "https://example.local/api/v3/core/applications/?page=2": {
                "results": [{"pk": 2, "name": "app-b"}],
                "next": None,
            },
            "https://example.local/api/v3/providers/proxy/?page_size=200": {
                "results": [],
                "next": None,
            },
            "https://example.local/api/v3/providers/oauth2/?page_size=200": {
                "results": [],
                "next": None,
            },
            "https://example.local/api/v3/outposts/instances/?page_size=200": {
                "results": [],
                "next": None,
            },
        }

        def fake_urlopen(request, context=None):
            calls.append(request.get_method())
            return DummyResponse(payloads[request.full_url])

        client = AuthentikApiClient(base_url="https://example.local", token="token", verify_tls=False)
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            apps = client.fetch_applications()
            providers = client.fetch_proxy_providers()
            oauth2_providers = client.fetch_oauth2_providers()
            outposts = client.fetch_outposts()

        self.assertEqual(2, len(apps))
        self.assertEqual([], providers)
        self.assertEqual([], oauth2_providers)
        self.assertEqual([], outposts)
        self.assertTrue(all(method == "GET" for method in calls))
        self.assertEqual(calls, client.request_methods)


class TestClientTlsBehavior(unittest.TestCase):
    def _make_dummy_response(self):
        class DummyResponse:
            def read(self):
                return json.dumps({"results": [], "next": None}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return DummyResponse()

    def test_default_client_verifies_tls(self):
        captured: list = []
        dummy = self._make_dummy_response()

        def fake_urlopen(request, context=None):
            captured.append(context)
            return dummy

        client = AuthentikApiClient(base_url="https://example.local", token="token")
        with mock.patch.dict(os.environ, {"AUTHENTIK_EXTRA_CA": ""}), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.fetch_applications()

        self.assertIsNone(captured[0], "default client must pass context=None (system TLS verification)")

    def test_no_verify_tls_client_disables_certificate_check(self):
        captured: list = []
        dummy = self._make_dummy_response()

        def fake_urlopen(request, context=None):
            captured.append(context)
            return dummy

        client = AuthentikApiClient(base_url="https://example.local", token="token", verify_tls=False)
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.fetch_applications()

        ctx = captured[0]
        self.assertIsNotNone(ctx, "verify_tls=False must supply a custom SSL context")
        self.assertEqual(ssl.CERT_NONE, ctx.verify_mode)


class TestCliArgs(unittest.TestCase):
    def test_default_args_enable_tls_verification(self):
        with mock.patch.object(sys, "argv", ["discover-authentik-edge.py"]):
            args = MODULE.parse_args()
        self.assertFalse(args.no_verify_tls)

    def test_no_verify_tls_flag_disables_verification(self):
        with mock.patch.object(sys, "argv", ["discover-authentik-edge.py", "--no-verify-tls"]):
            args = MODULE.parse_args()
        self.assertTrue(args.no_verify_tls)


class TestTokenResolution(unittest.TestCase):
    def test_missing_token_returns_actionable_issue(self):
        with mock.patch.dict(MODULE.os.environ, {}, clear=True):
            token, issue = _resolve_token("AUTHENTIK_SUPERUSER_API_TOKEN")

        self.assertIsNone(token)
        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual("AKD001", issue.code)
        self.assertIn("./with-secrets", issue.message)


if __name__ == "__main__":
    unittest.main()
