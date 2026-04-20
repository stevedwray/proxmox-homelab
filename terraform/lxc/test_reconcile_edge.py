"""Tests for unified edge reconciler orchestration behavior."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "docs" / "provisioning-refactor" / "fixtures" / "valid"
MODULE_PATH = Path(__file__).resolve().parent / "reconcile-edge.py"
SPEC = importlib.util.spec_from_file_location("reconcile_edge", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestReconcileEdge(unittest.TestCase):
    def test_parse_args_defaults_to_dry_run(self):
        args = MODULE.parse_args([])
        self.assertFalse(args.apply)

    def test_apply_fails_on_target_preflight(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "authentik.yaml"
            manifest.write_text((FIXTURES_DIR / "authentik.yaml").read_text(encoding="utf-8"), encoding="utf-8")

            args = MODULE.parse_args([str(manifest), "--apply", "--json"])

            healthy_tcp = MODULE.HealthCheckResult(
                name="stub",
                url="tcp://example.local:443",
                ok=True,
                status_code=None,
                detail="ok",
            )
            healthy_dns = MODULE.HealthCheckResult(
                name="stub",
                url="dig @example.local +short example.local",
                ok=True,
                status_code=None,
                detail="ok",
            )

            with mock.patch.object(MODULE, "_run_pve_target_preflight", return_value=(False, "wrong target")):
                with mock.patch.object(MODULE, "_tcp_health_check", return_value=healthy_tcp):
                    with mock.patch.object(
                        MODULE,
                        "_dns_authority_health_check",
                        return_value=healthy_dns,
                    ):
                        result = MODULE.reconcile_edge(args)

        self.assertEqual("failed", result["status"])
        self.assertTrue(any(issue["code"] == "EGR200" for issue in result["issues"]))

    def test_noop_with_empty_manifest_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stacks_dir = Path(tmpdir) / "stacks"
            stacks_dir.mkdir(parents=True, exist_ok=True)

            args = MODULE.parse_args([
                "--stacks-dir",
                str(stacks_dir),
                "--json",
            ])
            result = MODULE.reconcile_edge(args)

        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["manifests"])
        self.assertFalse(result["authentik"]["required"])
        self.assertEqual(0, result["traefik"]["stack_count"])
        self.assertEqual(0, result["coredns"]["generated_record_count"])

    def test_intended_replacement_host_allows_migration_collision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "traefik-dashboard.yaml"
            document = yaml.safe_load((FIXTURES_DIR / "traefik-dashboard.yaml").read_text(encoding="utf-8"))
            document["spec"]["routes"][0]["auth"]["mode"] = "none"
            manifest_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

            args = MODULE.parse_args(
                [
                    str(manifest_path),
                    "--intended-replacement-host",
                    "traefik.lab.gibbsgreatly.xyz",
                    "--json",
                ]
            )
            result = MODULE.reconcile_edge(args)

        self.assertEqual("passed", result["status"])
        self.assertEqual("passed", result["traefik"]["status"])
        self.assertEqual([], result["issues"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Helpers for Authentik status-gating tests
# ---------------------------------------------------------------------------


def _healthy_tcp() -> MODULE.HealthCheckResult:
    return MODULE.HealthCheckResult(
        name="stub",
        url="tcp://example.local:443",
        ok=True,
        status_code=None,
        detail="ok",
    )


def _healthy_dns() -> MODULE.HealthCheckResult:
    return MODULE.HealthCheckResult(
        name="stub",
        url="dig @example.local +short example.local",
        ok=True,
        status_code=None,
        detail="ok",
    )


def _discovery_ok() -> mock.MagicMock:
    result = mock.MagicMock()
    result.ok = True
    result.to_dict.return_value = {"status": "passed", "route_count": 3, "issue_count": 0}
    return result


def _discovery_drift() -> mock.MagicMock:
    result = mock.MagicMock()
    result.ok = False
    result.to_dict.return_value = {"status": "failed", "route_count": 3, "issue_count": 1}
    return result


def _reconcile_ok(write_count: int = 7) -> mock.MagicMock:
    result = mock.MagicMock()
    result.ok = True
    result.to_dict.return_value = {
        "status": "passed",
        "write_count": write_count,
        "action_count": write_count,
        "stop_condition_count": 0,
        "issue_count": 0,
        "mode": "apply",
    }
    return result


def _reconcile_failed() -> mock.MagicMock:
    result = mock.MagicMock()
    result.ok = False
    result.to_dict.return_value = {
        "status": "failed",
        "write_count": 0,
        "action_count": 0,
        "stop_condition_count": 1,
        "issue_count": 1,
        "mode": "apply",
    }
    return result


class TestReconcileEdgeApplyAuthentikStatus(unittest.TestCase):
    """Tests for post-apply Authentik convergence status gating."""

    # Minimal manifest with forwardAuth so that _selected_manifests_require_authentik
    # returns True.  Uses a hostname that is not present in the legacy central proxy
    # playbook to avoid any Traefik collision-check failures.
    _FORWARDAUTH_MANIFEST_YAML = """\
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: test-reconcile-edge
  stack: test-reconcile-edge-stack
spec:
  routes:
    - name: test
      host: test-reconcile-edge.lab.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.0.1:9000
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
"""
    _TOKEN_ENV = "AUTHENTIK_SUPERUSER_API_TOKEN"

    def test_apply_pre_apply_drift_passes_after_successful_reconcile(self):
        """Apply mode: pre-apply drift, reconcile succeeds, post-apply clean → top-level passed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "test-reconcile-edge.yaml"
            manifest.write_text(self._FORWARDAUTH_MANIFEST_YAML, encoding="utf-8")
            args = MODULE.parse_args([str(manifest), "--apply", "--json"])

            # First discover call returns pre-apply drift; second (post-apply) returns clean.
            discover_side_effect = [_discovery_drift(), _discovery_ok()]

            with (
                mock.patch.object(
                    MODULE, "_run_pve_target_preflight", return_value=(True, "pve-test")
                ),
                mock.patch.object(MODULE, "_tcp_health_check", return_value=_healthy_tcp()),
                mock.patch.object(
                    MODULE, "_dns_authority_health_check", return_value=_healthy_dns()
                ),
                mock.patch.dict("os.environ", {self._TOKEN_ENV: "fake-token"}),
                mock.patch.object(MODULE.DISCOVER_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(MODULE.RECONCILE_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(
                    MODULE.DISCOVER_AUTHENTIK,
                    "discover_authentik_drift",
                    side_effect=discover_side_effect,
                ),
                mock.patch.object(
                    MODULE.RECONCILE_AUTHENTIK,
                    "reconcile_authentik",
                    return_value=_reconcile_ok(),
                ),
            ):
                result = MODULE.reconcile_edge(args)

        self.assertEqual(
            "passed", result["status"], msg=f"Expected passed, got issues: {result.get('issues')}"
        )
        self.assertEqual([], result["issues"])
        # Post-apply discovery must be present and clean.
        self.assertIsNotNone(result["authentik"]["post_apply_discovery"])
        self.assertEqual("passed", result["authentik"]["post_apply_discovery"]["status"])

    def test_apply_authentik_reconcile_failure_still_fails(self):
        """Apply mode: reconcile apply fails → top-level failed with EGR212."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "test-reconcile-edge.yaml"
            manifest.write_text(self._FORWARDAUTH_MANIFEST_YAML, encoding="utf-8")
            args = MODULE.parse_args([str(manifest), "--apply", "--json"])

            with (
                mock.patch.object(
                    MODULE, "_run_pve_target_preflight", return_value=(True, "pve-test")
                ),
                mock.patch.object(MODULE, "_tcp_health_check", return_value=_healthy_tcp()),
                mock.patch.object(
                    MODULE, "_dns_authority_health_check", return_value=_healthy_dns()
                ),
                mock.patch.dict("os.environ", {self._TOKEN_ENV: "fake-token"}),
                mock.patch.object(MODULE.DISCOVER_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(MODULE.RECONCILE_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(
                    MODULE.DISCOVER_AUTHENTIK,
                    "discover_authentik_drift",
                    return_value=_discovery_drift(),
                ),
                mock.patch.object(
                    MODULE.RECONCILE_AUTHENTIK,
                    "reconcile_authentik",
                    return_value=_reconcile_failed(),
                ),
            ):
                result = MODULE.reconcile_edge(args)

        self.assertEqual("failed", result["status"])
        self.assertTrue(any(i["code"] == "EGR212" for i in result["issues"]))
        # Reconcile failed → post-apply discovery not run.
        self.assertIsNone(result["authentik"]["post_apply_discovery"])

    def test_apply_post_apply_drift_still_fails(self):
        """Apply mode: reconcile succeeds but post-apply discovery still has drift → EGR211."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "test-reconcile-edge.yaml"
            manifest.write_text(self._FORWARDAUTH_MANIFEST_YAML, encoding="utf-8")
            args = MODULE.parse_args([str(manifest), "--apply", "--json"])

            # Both pre- and post-apply discovery return drift.
            discover_side_effect = [_discovery_drift(), _discovery_drift()]

            with (
                mock.patch.object(
                    MODULE, "_run_pve_target_preflight", return_value=(True, "pve-test")
                ),
                mock.patch.object(MODULE, "_tcp_health_check", return_value=_healthy_tcp()),
                mock.patch.object(
                    MODULE, "_dns_authority_health_check", return_value=_healthy_dns()
                ),
                mock.patch.dict("os.environ", {self._TOKEN_ENV: "fake-token"}),
                mock.patch.object(MODULE.DISCOVER_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(MODULE.RECONCILE_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(
                    MODULE.DISCOVER_AUTHENTIK,
                    "discover_authentik_drift",
                    side_effect=discover_side_effect,
                ),
                mock.patch.object(
                    MODULE.RECONCILE_AUTHENTIK,
                    "reconcile_authentik",
                    return_value=_reconcile_ok(),
                ),
            ):
                result = MODULE.reconcile_edge(args)

        self.assertEqual("failed", result["status"])
        self.assertTrue(any(i["code"] == "EGR211" for i in result["issues"]))
        # Post-apply discovery is present and shows the remaining drift.
        self.assertIsNotNone(result["authentik"]["post_apply_discovery"])
        self.assertEqual("failed", result["authentik"]["post_apply_discovery"]["status"])

    def test_dry_run_with_missing_authentik_objects_reports_egr211(self):
        """Dry-run: missing Authentik objects → EGR211 reported, top-level failed, no post-apply run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "test-reconcile-edge.yaml"
            manifest.write_text(self._FORWARDAUTH_MANIFEST_YAML, encoding="utf-8")
            args = MODULE.parse_args([str(manifest), "--json"])  # no --apply

            with (
                mock.patch.dict("os.environ", {self._TOKEN_ENV: "fake-token"}),
                mock.patch.object(MODULE.DISCOVER_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(MODULE.RECONCILE_AUTHENTIK, "AuthentikApiClient"),
                mock.patch.object(
                    MODULE.DISCOVER_AUTHENTIK,
                    "discover_authentik_drift",
                    return_value=_discovery_drift(),
                ),
                mock.patch.object(
                    MODULE.RECONCILE_AUTHENTIK,
                    "reconcile_authentik",
                    return_value=_reconcile_ok(write_count=0),
                ),
            ):
                result = MODULE.reconcile_edge(args)

        self.assertEqual("failed", result["status"])
        self.assertTrue(any(i["code"] == "EGR211" for i in result["issues"]))
        # No post-apply discovery in dry-run mode.
        self.assertIsNone(result["authentik"]["post_apply_discovery"])
