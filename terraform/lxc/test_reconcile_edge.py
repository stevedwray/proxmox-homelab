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

            with mock.patch.object(MODULE, "_run_pve_target_preflight", return_value=(False, "wrong target")):
                with mock.patch.object(MODULE, "_http_health_check") as probe_mock:
                    probe_mock.return_value = MODULE.HealthCheckResult(
                        name="stub",
                        url="http://example.local",
                        ok=True,
                        status_code=200,
                        detail="ok",
                    )
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
