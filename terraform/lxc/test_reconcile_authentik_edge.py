"""Tests for create/update-only Authentik reconciliation behavior."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "reconcile-authentik-edge.py"
SPEC = importlib.util.spec_from_file_location("reconcile_authentik_edge", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
import os  # noqa: E402
os.environ["LAB_IP_PROXY"] = "10.57.2.10"
SPEC.loader.exec_module(MODULE)

reconcile_authentik = MODULE.reconcile_authentik


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
        target: ${{LAB_IP_PROXY}}
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
        *,
        applications: list[dict] | None = None,
        providers: list[dict] | None = None,
        oauth2_providers: list[dict] | None = None,
        outposts: list[dict] | None = None,
        flows: list[dict] | None = None,
        certificate_keypairs: list[dict] | None = None,
        scope_property_mappings: list[dict] | None = None,
    ) -> None:
        self.applications = list(applications or [])
        self.providers = list(providers or [])
        self.oauth2_providers = list(oauth2_providers or [])
        self.outposts = list(outposts or [])
        self.flows = list(
            flows
            if flows is not None
            else [
                {
                    "pk": "flow-authz-default",
                    "slug": "default-provider-authorization-implicit-consent",
                    "designation": "authorization",
                },
                {
                    "pk": "flow-invalidation-default",
                    "slug": "default-provider-invalidation-flow",
                    "designation": "invalidation",
                },
            ]
        )
        self.certificate_keypairs = list(
            certificate_keypairs
            if certificate_keypairs is not None
            else [
                {
                    "pk": "certkey-default",
                    "name": "authentik Self-signed Certificate",
                    "private_key_available": True,
                    "private_key_type": "rsa",
                }
            ]
        )
        self.scope_property_mappings = list(
            scope_property_mappings
            if scope_property_mappings is not None
            else [
                {"pk": "scope-openid", "scope_name": "openid", "name": "OpenID"},
                {"pk": "scope-profile", "scope_name": "profile", "name": "Profile"},
                {"pk": "scope-email", "scope_name": "email", "name": "Email"},
            ]
        )
        self.request_methods: list[str] = []
        self.writes: list[tuple[str, str, dict]] = []
        self.application_update_targets: list[str] = []
        self._next_id = 1000

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def fetch_applications(self):
        self.request_methods.append("GET")
        return self.applications

    def fetch_proxy_providers(self):
        self.request_methods.append("GET")
        return self.providers

    def fetch_oauth2_providers(self):
        self.request_methods.append("GET")
        return self.oauth2_providers

    def fetch_outposts(self):
        self.request_methods.append("GET")
        return self.outposts

    def fetch_flows(self):
        self.request_methods.append("GET")
        return self.flows

    def fetch_certificate_keypairs(self):
        self.request_methods.append("GET")
        return self.certificate_keypairs

    def fetch_scope_property_mappings(self):
        self.request_methods.append("GET")
        return self.scope_property_mappings

    def create_proxy_provider(self, payload: dict):
        self.request_methods.append("POST")
        self.writes.append(("provider", "create", dict(payload)))
        obj = {"pk": self._new_id(), **payload}
        self.providers.append(obj)
        return obj

    def create_oauth2_provider(self, payload: dict):
        self.request_methods.append("POST")
        self.writes.append(("provider", "create", dict(payload)))
        obj = {"pk": self._new_id(), **payload}
        self.oauth2_providers.append(obj)
        return obj

    def update_proxy_provider(self, provider_id: str, payload: dict):
        self.request_methods.append("PATCH")
        self.writes.append(("provider", "update", dict(payload)))
        for provider in self.providers:
            if str(provider.get("pk")) == str(provider_id):
                provider.update(payload)
                return provider
        raise AssertionError("provider not found")

    def update_oauth2_provider(self, provider_id: str, payload: dict):
        self.request_methods.append("PATCH")
        self.writes.append(("provider", "update", dict(payload)))
        for provider in self.oauth2_providers:
            if str(provider.get("pk")) == str(provider_id):
                provider.update(payload)
                return provider
        raise AssertionError("provider not found")

    def create_application(self, payload: dict):
        self.request_methods.append("POST")
        self.writes.append(("application", "create", dict(payload)))
        obj = {"pk": self._new_id(), **payload}
        self.applications.append(obj)
        return obj

    def update_application(self, application_id: str, payload: dict):
        self.request_methods.append("PATCH")
        self.application_update_targets.append(str(application_id))
        self.writes.append(("application", "update", dict(payload)))
        for app in self.applications:
            if str(app.get("slug")) == str(application_id):
                app.update(payload)
                return app
        raise AssertionError("application not found")

    def create_outpost(self, payload: dict):
        self.request_methods.append("POST")
        self.writes.append(("outpost", "create", dict(payload)))
        obj = {"pk": self._new_id(), **payload}
        self.outposts.append(obj)
        return obj

    def update_outpost(self, outpost_id: str, payload: dict):
        self.request_methods.append("PATCH")
        self.writes.append(("outpost", "update", dict(payload)))
        for outpost in self.outposts:
            if str(outpost.get("pk")) == str(outpost_id):
                outpost.update(payload)
                return outpost
        raise AssertionError("outpost not found")


class TestReconcileAuthentikEdge(unittest.TestCase):
    def test_dry_run_plans_create_without_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "portainer.yaml"
            _write_manifest(
                manifest,
                stack="portainer-stack",
                route="portainer",
                host="portainer.lab.gibbsgreatly.xyz",
                mode="forwardAuth",
            )
            client = FakeClient()
            result = reconcile_authentik([manifest], client, apply=False)

        self.assertTrue(result.ok)
        self.assertEqual(0, result.write_count)
        self.assertEqual([], client.writes)
        operations = [action.operation for action in result.actions]
        self.assertIn("create", operations)
        self.assertIn(("provider", "create"), [(a.object_kind, a.operation) for a in result.actions])
        self.assertIn(("application", "create"), [(a.object_kind, a.operation) for a in result.actions])
        self.assertIn(("outpost", "create"), [(a.object_kind, a.operation) for a in result.actions])

    def test_apply_then_second_apply_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "grafana.yaml"
            _write_manifest(
                manifest,
                stack="grafana-stack",
                route="grafana",
                host="grafana.lab.gibbsgreatly.xyz",
                mode="forwardAuth",
            )
            client = FakeClient()

            first = reconcile_authentik([manifest], client, apply=True)
            second = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(first.ok)
        self.assertGreater(first.write_count, 0)
        self.assertTrue(second.ok)
        self.assertEqual(0, second.write_count)
        self.assertTrue(all(action.operation == "noop" for action in second.actions))

    def test_existing_owned_objects_with_drift_plan_updates(self):
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
                providers=[
                    {
                        "pk": 11,
                        "name": "edge-netbox-stack-netbox-provider",
                        "external_host": "https://old-netbox.lab.gibbsgreatly.xyz",
                        "cookie_domain": ".example.local",
                    }
                ],
                applications=[
                    {
                        "pk": 22,
                        "name": "edge-netbox-stack-netbox-app",
                        "slug": "edge-netbox-stack-netbox",
                        "meta_launch_url": "https://old-netbox.lab.gibbsgreatly.xyz/",
                        "provider": 11,
                    }
                ],
                outposts=[
                    {
                        "pk": 33,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [],
                        "config": {
                            "authentik_host": "https://authentik.lab.gibbsgreatly.xyz",
                            "authentik_host_browser": "https://authentik.lab.gibbsgreatly.xyz",
                            "log_level": "info",
                            "authentik_host_insecure": False,
                        },
                    }
                ],
            )

            with patch.dict(MODULE.os.environ, {"LAB_FQDN_AUTHENTIK": "authentik.test.gibbsgreatly.xyz"}, clear=False):
                result = reconcile_authentik([manifest], client, apply=False)

        self.assertTrue(result.ok)
        operations = {(action.object_kind, action.operation) for action in result.actions}
        self.assertIn(("provider", "update"), operations)
        self.assertIn(("application", "update"), operations)
        self.assertIn(("outpost", "update"), operations)

    def test_apply_updates_shared_outpost_browser_host(self):
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
                providers=[
                    {
                        "pk": 11,
                        "name": "edge-netbox-stack-netbox-provider",
                        "external_host": "https://netbox.lab.gibbsgreatly.xyz",
                    }
                ],
                applications=[
                    {
                        "pk": 22,
                        "name": "edge-netbox-stack-netbox-app",
                        "slug": "edge-netbox-stack-netbox",
                        "meta_launch_url": "https://netbox.lab.gibbsgreatly.xyz/",
                        "provider": 11,
                    }
                ],
                outposts=[
                    {
                        "pk": 33,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [11],
                        "config": {
                            "authentik_host": "https://authentik.lab.gibbsgreatly.xyz",
                            "authentik_host_browser": "https://authentik.lab.gibbsgreatly.xyz",
                            "log_level": "info",
                            "authentik_host_insecure": False,
                        },
                    }
                ],
            )

            with patch.dict(
                MODULE.os.environ,
                {
                    "LAB_FQDN_AUTHENTIK": "authentik.test.gibbsgreatly.xyz",
                },
                clear=False,
            ):
                result = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.write_count, 1)
        self.assertEqual(
            "https://authentik.test.gibbsgreatly.xyz",
            client.outposts[0]["config"]["authentik_host_browser"],
        )
        self.assertIn(
            (
                "outpost",
                "update",
                {
                    "config": {
                        "authentik_host": "https://authentik.test.gibbsgreatly.xyz",
                        "authentik_host_browser": "https://authentik.test.gibbsgreatly.xyz",
                        "log_level": "info",
                        "authentik_host_insecure": False,
                    }
                },
            ),
            client.writes,
        )

    def test_prefers_embedded_outpost_when_legacy_custom_outpost_exists(self):
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
                providers=[
                    {
                        "pk": 201,
                        "name": "edge-portainer-stack-portainer-provider",
                        "external_host": "https://portainer.lab.gibbsgreatly.xyz",
                    }
                ],
                applications=[
                    {
                        "pk": 202,
                        "name": "edge-portainer-stack-portainer-app",
                        "slug": "edge-portainer-stack-portainer",
                        "meta_launch_url": "https://portainer.lab.gibbsgreatly.xyz/",
                        "provider": 201,
                    }
                ],
                outposts=[
                    {
                        "pk": 203,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [],
                    },
                    {
                        "pk": 204,
                        "name": "edge-forwardauth-outpost",
                        "type": "proxy",
                        "providers": [201],
                    },
                ],
            )

            result = reconcile_authentik([manifest], client, apply=False)

        self.assertTrue(result.ok)
        outpost_actions = [a for a in result.actions if a.object_kind == "outpost"]
        self.assertEqual(1, len(outpost_actions))
        self.assertEqual("authentik Embedded Outpost", outpost_actions[0].object_name)
        self.assertEqual("update", outpost_actions[0].operation)

    def test_dry_run_reports_issue_when_forwardauth_endpoint_404(self):
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
                providers=[
                    {
                        "pk": 1,
                        "name": "edge-netbox-stack-netbox-provider",
                        "external_host": "https://netbox.lab.gibbsgreatly.xyz",
                    }
                ],
                applications=[
                    {
                        "pk": 2,
                        "name": "edge-netbox-stack-netbox-app",
                        "slug": "edge-netbox-stack-netbox",
                        "meta_launch_url": "https://netbox.lab.gibbsgreatly.xyz/",
                        "provider": 1,
                    }
                ],
                outposts=[
                    {
                        "pk": 3,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [1],
                    }
                ],
            )
            client.base_url = "http://auth.local"
            client.verify_tls = True

            with patch.object(MODULE, "_probe_forwardauth_endpoint", return_value=(404, None)):
                result = reconcile_authentik([manifest], client, apply=False)

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.code == "AKR004" for issue in result.issues))

    def test_dry_run_accepts_forwardauth_redirect_status(self):
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
                providers=[
                    {
                        "pk": 1,
                        "name": "edge-netbox-stack-netbox-provider",
                        "external_host": "https://netbox.lab.gibbsgreatly.xyz",
                    }
                ],
                applications=[
                    {
                        "pk": 2,
                        "name": "edge-netbox-stack-netbox-app",
                        "slug": "edge-netbox-stack-netbox",
                        "meta_launch_url": "https://netbox.lab.gibbsgreatly.xyz/",
                        "provider": 1,
                    }
                ],
                outposts=[
                    {
                        "pk": 3,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [1],
                    }
                ],
            )
            client.base_url = "http://auth.local"
            client.verify_tls = True

            with patch.object(MODULE, "_probe_forwardauth_endpoint", return_value=(302, None)):
                result = reconcile_authentik([manifest], client, apply=False)

        self.assertTrue(result.ok)
        self.assertFalse(any(issue.code == "AKR004" for issue in result.issues))

    def test_dry_run_reports_probe_connectivity_failure_clearly(self):
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
                providers=[
                    {
                        "pk": 1,
                        "name": "edge-netbox-stack-netbox-provider",
                        "external_host": "https://netbox.lab.gibbsgreatly.xyz",
                    }
                ],
                applications=[
                    {
                        "pk": 2,
                        "name": "edge-netbox-stack-netbox-app",
                        "slug": "edge-netbox-stack-netbox",
                        "meta_launch_url": "https://netbox.lab.gibbsgreatly.xyz/",
                        "provider": 1,
                    }
                ],
                outposts=[
                    {
                        "pk": 3,
                        "name": "authentik Embedded Outpost",
                        "type": "proxy",
                        "providers": [1],
                    }
                ],
            )
            client.base_url = "http://auth.local"
            client.verify_tls = True

            with patch.object(
                MODULE,
                "_probe_forwardauth_endpoint",
                return_value=(None, "[Errno 111] Connection refused"),
            ):
                result = reconcile_authentik([manifest], client, apply=False)

        self.assertFalse(result.ok)
        probe_issues = [issue for issue in result.issues if issue.code == "AKR004"]
        self.assertEqual(1, len(probe_issues))
        self.assertIn("connectivity failure", probe_issues[0].message)

    def test_non_forwardauth_reports_delete_only(self):
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
                providers=[
                    {
                        "pk": 91,
                        "name": "edge-authentik-stack-authentik-provider",
                        "external_host": "https://authentik.lab.gibbsgreatly.xyz",
                    }
                ],
                applications=[
                    {
                        "pk": 92,
                        "name": "edge-authentik-stack-authentik-app",
                        "slug": "edge-authentik-stack-authentik",
                        "meta_launch_url": "https://authentik.lab.gibbsgreatly.xyz/",
                    }
                ],
            )

            result = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(result.ok)
        self.assertEqual(0, result.write_count)
        self.assertEqual([], client.writes)
        self.assertTrue(all(action.operation == "delete-report" for action in result.actions))

    def test_unmanaged_candidate_causes_stop(self):
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
                providers=[
                    {
                        "pk": 201,
                        "name": "legacy-portainer-provider",
                        "external_host": "https://portainer.lab.gibbsgreatly.xyz",
                    }
                ]
            )

            result = reconcile_authentik([manifest], client, apply=True)

        self.assertFalse(result.ok)
        self.assertGreater(len(result.stop_conditions), 0)
        self.assertEqual(0, result.write_count)
        self.assertEqual([], client.writes)

    def test_owned_objects_from_other_stacks_do_not_cause_stop(self):
        """Orphan check is scoped: objects from stacks not in the current manifest are ignored."""
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
                # These owned objects belong to OTHER stacks — should not block portainer reconcile.
                applications=[
                    {"pk": 301, "name": "edge-netbox-stack-netbox-app", "slug": "edge-netbox-stack-netbox", "meta_launch_url": "https://netbox.lab.gibbsgreatly.xyz"},
                    {"pk": 302, "name": "edge-harbor-stack-harbor-app", "slug": "edge-harbor-stack-harbor", "meta_launch_url": "https://harbor.lab.gibbsgreatly.xyz"},
                ],
                providers=[
                    {"pk": 401, "name": "edge-netbox-stack-netbox-provider", "external_host": "https://netbox.lab.gibbsgreatly.xyz"},
                    {"pk": 402, "name": "edge-harbor-stack-harbor-provider", "external_host": "https://harbor.lab.gibbsgreatly.xyz"},
                ],
            )

            result = reconcile_authentik([manifest], client, apply=True)

        self.assertEqual((), result.stop_conditions)
        self.assertTrue(result.ok)
    def test_provider_payload_uses_resolved_flow_pks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "portainer.yaml"
            _write_manifest(
                manifest,
                stack="portainer-stack",
                route="portainer",
                host="portainer.lab.gibbsgreatly.xyz",
                mode="forwardAuth",
            )
            client = FakeClient()

            result = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(result.ok)
        provider_writes = [entry for entry in client.writes if entry[0] == "provider" and entry[1] == "create"]
        self.assertEqual(1, len(provider_writes))
        payload = provider_writes[0][2]
        self.assertEqual("flow-authz-default", payload["authorization_flow"])
        self.assertEqual("flow-invalidation-default", payload["invalidation_flow"])

    def test_missing_required_flow_fails_preflight_before_writes(self):
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
                flows=[
                    {
                        "pk": "flow-authz-default",
                        "slug": "default-provider-authorization-implicit-consent",
                        "designation": "authorization",
                    }
                ]
            )

            result = reconcile_authentik([manifest], client, apply=True)

        self.assertFalse(result.ok)
        self.assertEqual(0, result.write_count)
        self.assertEqual([], client.writes)
        self.assertTrue(any(issue.code == "AKR003" for issue in result.issues))

    def test_flow_slug_override_is_honored(self):
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
                flows=[
                    {
                        "pk": "flow-authz-custom",
                        "slug": "custom-authz",
                        "designation": "authorization",
                    },
                    {
                        "pk": "flow-invalidation-custom",
                        "slug": "custom-invalidation",
                        "designation": "invalidation",
                    },
                ]
            )

            with patch.dict(
                MODULE.os.environ,
                {
                    MODULE.AUTHORIZATION_FLOW_SLUG_ENV: "custom-authz",
                    MODULE.INVALIDATION_FLOW_SLUG_ENV: "custom-invalidation",
                },
                clear=False,
            ):
                auth_override = MODULE._resolve_slug_override(MODULE.AUTHORIZATION_FLOW_SLUG_ENV)
                invalidation_override = MODULE._resolve_slug_override(MODULE.INVALIDATION_FLOW_SLUG_ENV)
                result = reconcile_authentik(
                    [manifest],
                    client,
                    apply=True,
                    authorization_flow_slug_override=auth_override,
                    invalidation_flow_slug_override=invalidation_override,
                )

        self.assertTrue(result.ok)
        provider_writes = [entry for entry in client.writes if entry[0] == "provider" and entry[1] == "create"]
        self.assertEqual(1, len(provider_writes))
        payload = provider_writes[0][2]
        self.assertEqual("flow-authz-custom", payload["authorization_flow"])
        self.assertEqual("flow-invalidation-custom", payload["invalidation_flow"])

    def test_harbor_oidc_dry_run_plans_provider_and_application_without_outpost(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "harbor.yaml"
            _write_manifest(
                manifest,
                stack="harbor-stack",
                route="harbor",
                host="harbor.lab.gibbsgreatly.xyz",
                mode="oidc",
            )
            client = FakeClient()

            with patch.dict(
                MODULE.os.environ,
                {
                    "HARBOR_OIDC_CLIENT_SECRET": "secret-value",
                    "HARBOR_EXTERNAL_URL": "https://harbor.gibbsgreatly.xyz",
                },
                clear=False,
            ):
                result = reconcile_authentik([manifest], client, apply=False)

        self.assertTrue(result.ok)
        operations = {(action.object_kind, action.operation) for action in result.actions}
        self.assertIn(("provider", "create"), operations)
        self.assertIn(("application", "create"), operations)
        self.assertNotIn(("outpost", "create"), operations)

    def test_harbor_oidc_apply_writes_expected_provider_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "harbor.yaml"
            _write_manifest(
                manifest,
                stack="harbor-stack",
                route="harbor",
                host="harbor.lab.gibbsgreatly.xyz",
                mode="oidc",
            )
            client = FakeClient()

            with patch.dict(
                MODULE.os.environ,
                {
                    "HARBOR_OIDC_CLIENT_SECRET": "secret-value",
                    "HARBOR_EXTERNAL_URL": "https://harbor.gibbsgreatly.xyz",
                },
                clear=False,
            ):
                result = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(result.ok)
        provider_writes = [entry for entry in client.writes if entry[0] == "provider" and entry[1] == "create"]
        self.assertEqual(1, len(provider_writes))
        payload = provider_writes[0][2]
        self.assertEqual("harbor", payload["client_id"])
        self.assertEqual("secret-value", payload["client_secret"])
        self.assertEqual("certkey-default", payload["signing_key"])
        self.assertEqual(["scope-openid", "scope-profile", "scope-email"], payload["property_mappings"])
        self.assertEqual(
            [{"matching_mode": "strict", "url": "https://harbor.gibbsgreatly.xyz/c/oidc/callback"}],
            payload["redirect_uris"],
        )

    def test_harbor_oidc_apply_updates_existing_application_launch_url(self):
        # When HARBOR_EXTERNAL_URL is an internal IP (non-prod), launch_url must still
        # use the public FQDN (intent.host) — Authentik rejects bare IP launch_urls.
        # The redirect_uri follows HARBOR_EXTERNAL_URL; launch_url is always intent.host.
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
                        "pk": 302,
                        "name": "edge-harbor-stack-harbor-app",
                        "slug": "edge-harbor-stack-harbor",
                        "launch_url": "http://192.168.40.110/",
                        "meta_launch_url": "http://192.168.40.110/",
                        "provider": 402,
                    }
                ],
                oauth2_providers=[
                    {
                        "pk": 402,
                        "name": "edge-harbor-stack-harbor-provider",
                        "client_id": "harbor",
                        "redirect_uris": [
                            {"matching_mode": "strict", "url": "https://harbor.lab.gibbsgreatly.xyz/c/oidc/callback"}
                        ],
                    }
                ],
            )

            with patch.dict(
                MODULE.os.environ,
                {
                    "HARBOR_OIDC_CLIENT_SECRET": "secret-value",
                    "HARBOR_EXTERNAL_URL": "http://192.168.40.110",
                },
                clear=False,
            ):
                result = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.write_count, 1)
        self.assertEqual("https://harbor.lab.gibbsgreatly.xyz/", client.applications[0]["meta_launch_url"])
        self.assertEqual("https://harbor.lab.gibbsgreatly.xyz/", client.applications[0]["launch_url"])
        self.assertEqual(["edge-harbor-stack-harbor"], client.application_update_targets)
        self.assertIn(
            (
                "application",
                "update",
                {
                    "launch_url": "https://harbor.lab.gibbsgreatly.xyz/",
                    "meta_launch_url": "https://harbor.lab.gibbsgreatly.xyz/",
                },
            ),
            client.writes,
        )

    def test_harbor_oidc_requires_secret_before_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "harbor.yaml"
            _write_manifest(
                manifest,
                stack="harbor-stack",
                route="harbor",
                host="harbor.lab.gibbsgreatly.xyz",
                mode="oidc",
            )
            client = FakeClient()

            with patch.dict(
                MODULE.os.environ,
                {"HARBOR_EXTERNAL_URL": "https://harbor.gibbsgreatly.xyz"},
                clear=True,
            ):
                result = reconcile_authentik([manifest], client, apply=True)

        self.assertFalse(result.ok)
        self.assertEqual(0, result.write_count)
        self.assertEqual([], client.writes)
        self.assertTrue(any(issue.code == "AKR006" for issue in result.issues))

    def test_harbor_oidc_requires_signing_key_before_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "harbor.yaml"
            _write_manifest(
                manifest,
                stack="harbor-stack",
                route="harbor",
                host="harbor.lab.gibbsgreatly.xyz",
                mode="oidc",
            )
            client = FakeClient(certificate_keypairs=[])

            with patch.dict(
                MODULE.os.environ,
                {
                    "HARBOR_OIDC_CLIENT_SECRET": "secret-value",
                    "HARBOR_EXTERNAL_URL": "https://harbor.gibbsgreatly.xyz",
                },
                clear=False,
            ):
                result = reconcile_authentik([manifest], client, apply=True)

        self.assertFalse(result.ok)
        self.assertEqual(0, result.write_count)
        self.assertEqual([], client.writes)
        self.assertTrue(any(issue.code == "AKR007" for issue in result.issues))

    def test_technitium_oidc_apply_writes_expected_provider_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "technitium.yaml"
            _write_manifest(
                manifest,
                stack="technitium-stack",
                route="technitium",
                host="technitium.lab.gibbsgreatly.xyz",
                mode="oidc",
            )
            client = FakeClient()

            with patch.dict(
                MODULE.os.environ,
                {"TECHNITIUM_OIDC_CLIENT_SECRET": "secret-value"},
                clear=False,
            ):
                result = reconcile_authentik([manifest], client, apply=True)

        self.assertTrue(result.ok)
        provider_writes = [entry for entry in client.writes if entry[0] == "provider" and entry[1] == "create"]
        self.assertEqual(1, len(provider_writes))
        payload = provider_writes[0][2]
        self.assertEqual("technitium", payload["client_id"])
        self.assertEqual("secret-value", payload["client_secret"])
        self.assertEqual(
            [{"matching_mode": "strict", "url": "https://technitium.lab.gibbsgreatly.xyz/sso/callback"}],
            payload["redirect_uris"],
        )


if __name__ == "__main__":
    unittest.main()
