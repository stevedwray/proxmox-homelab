#!/usr/bin/env python3
"""Unified dry-run-first edge reconciliation for manifests, renderers, and Authentik."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from edge_manifest import discover_edge_manifests, load_manifest, validate_manifests  # noqa: E402


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RENDER_TRAEFIK = _load_module("render_edge_traefik", SCRIPT_DIR / "render-edge-traefik.py")
RENDER_TECHNITIUM = _load_module("render_edge_technitium", SCRIPT_DIR / "render-edge-technitium.py")
RENDER_COREDNS = _load_module("render_edge_coredns", SCRIPT_DIR / "render-edge-coredns.py")
DISCOVER_AUTHENTIK = _load_module("discover_authentik_edge", SCRIPT_DIR / "discover-authentik-edge.py")
RECONCILE_AUTHENTIK = _load_module("reconcile_authentik_edge", SCRIPT_DIR / "reconcile-authentik-edge.py")

# When PVE_ENV is set, write generated output under the env-scoped directory
# so pve and pve-test-vm outputs never share the same path.
_pve_env = os.environ.get("PVE_ENV", "")
_generated_base = (
    SCRIPT_DIR / "environments" / _pve_env / ".generated"
    if _pve_env
    else SCRIPT_DIR / ".generated"
)


DEFAULT_TARGET_PREFLIGHT_EXPECTED = os.environ.get("EDGE_TARGET_PREFLIGHT_EXPECTED") or os.environ.get("PVE_ENV", "pve-test")
DEFAULT_TRAEFIK_PROBE_HOST = os.environ["LAB_IP_PROXY"]
DEFAULT_TRAEFIK_PROBE_PORT = 443
DEFAULT_DNS_PROBE_NAME = os.environ.get("LAB_FQDN_TRAEFIK") or f"traefik.{os.environ.get('LAB_DOMAIN', 'lab.gibbsgreatly.xyz')}"
DEFAULT_DNS_PROBE_EXPECTED = os.environ["LAB_IP_PROXY"]
# Technitium is the live DNS authority post-cutover (docs/dns-refactor/README.md) and is
# probed/rendered by default. CoreDNS (dns-stack) is frozen/rollback-only per
# docs/dns-refactor/plan.md Phase 6a -- its render/probe path is opt-in only (--coredns).
DEFAULT_TECHNITIUM_PROBE_SERVER = os.environ.get("LAB_IP_TECHNITIUM", "")
DEFAULT_TECHNITIUM_PROBE_NAME = DEFAULT_DNS_PROBE_NAME
DEFAULT_TECHNITIUM_PROBE_EXPECTED = DEFAULT_DNS_PROBE_EXPECTED
DEFAULT_COREDNS_PROBE_SERVER = os.environ.get("LAB_IP_DNS", "")
DEFAULT_COREDNS_PROBE_NAME = DEFAULT_DNS_PROBE_NAME
DEFAULT_COREDNS_PROBE_EXPECTED = DEFAULT_DNS_PROBE_EXPECTED
NOT_RUN_DRY_RUN = "not run (dry-run mode)"


@dataclass(frozen=True)
class EdgeIssue:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RenderPhaseResult:
    """Bundled render outputs -- keeps _build_passed_payload's parameter count sane."""

    traefik_result: Any
    technitium_result: Any
    coredns_result: Any | None
    traefik_output_dir: Path
    rendered_files: list[str]
    rendered_records: str
    rendered_zone: str | None


@dataclass(frozen=True)
class AuthentikPhaseResult:
    """Bundled Authentik discovery/reconcile outputs."""

    needs_authentik: bool
    discovery: dict[str, object] | None
    post_apply_discovery: dict[str, object] | None
    reconcile: dict[str, object] | None


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    url: str
    ok: bool
    status_code: int | None
    detail: str

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "url": self.url,
            "ok": self.ok,
            "detail": self.detail,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


@dataclass(frozen=True)
class HealthPhaseResult:
    """Bundled apply-mode (or dry-run stub) health-check outputs."""

    target_detail: str
    traefik: HealthCheckResult
    technitium: HealthCheckResult
    coredns: HealthCheckResult | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified edge reconciliation entrypoint. "
            "Defaults to dry-run and performs no live mutation unless --apply is set."
        )
    )
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help=(
            "Optional explicit manifest files to reconcile. "
            "If omitted, discover stacks/*/edge.yaml under --stacks-dir."
        ),
    )
    parser.add_argument(
        "--stacks-dir",
        type=Path,
        default=SCRIPT_DIR / "stacks",
        help="Stacks directory used for discovery mode.",
    )
    parser.add_argument(
        "--legacy-playbook",
        type=Path,
        default=SCRIPT_DIR / "ansible" / "playbooks" / "deploy-proxy-stack.yml",
        help="Path to legacy central proxy playbook used by Traefik collision checks.",
    )
    parser.add_argument(
        "--traefik-output-dir",
        type=Path,
        default=_generated_base / "traefik",
        help="Output directory for rendered Traefik dynamic files.",
    )
    parser.add_argument(
        "--seed-zone",
        type=Path,
        default=SCRIPT_DIR / "ansible" / "files" / "coredns-lab.zone",
        help="Path to the seed zone file shared by the Technitium and (opt-in) CoreDNS renderers.",
    )
    parser.add_argument(
        "--technitium-output-records",
        type=Path,
        default=_generated_base / "technitium" / "zone-records.json",
        help="Output file for rendered Technitium parity-zone records.",
    )
    parser.add_argument(
        "--coredns",
        action="store_true",
        help=(
            "Opt in to the legacy CoreDNS (dns-stack) render and health-check path. "
            "Off by default post-cutover (docs/dns-refactor/plan.md Phase 6a) -- dns-stack "
            "is frozen/rollback-only and no longer part of the routine reconciliation path."
        ),
    )
    parser.add_argument(
        "--coredns-output-zone",
        type=Path,
        default=_generated_base / "coredns" / "coredns-lab.zone",
        help="Output file for rendered CoreDNS zone. Only used with --coredns.",
    )
    parser.add_argument(
        "--intended-replacement-host",
        help=(
            "Optional single migration host to inject as intendedReplacement for exactly "
            "one selected manifest route."
        ),
    )
    parser.add_argument(
        "--authentik-url",
        default=DISCOVER_AUTHENTIK.DEFAULT_AUTHENTIK_URL,
        help="Base Authentik URL used for discovery/reconciliation.",
    )
    parser.add_argument(
        "--token-env",
        default=DISCOVER_AUTHENTIK.DEFAULT_TOKEN_ENV,
        help="Environment variable containing the Authentik API token.",
    )
    parser.add_argument(
        "--no-verify-tls",
        action="store_true",
        help="Disable TLS verification for Authentik and health checks.",
    )
    parser.add_argument(
        "--traefik-probe-host",
        default=DEFAULT_TRAEFIK_PROBE_HOST,
        help="Traefik host required to accept TCP connections in apply mode.",
    )
    parser.add_argument(
        "--traefik-probe-port",
        type=int,
        default=DEFAULT_TRAEFIK_PROBE_PORT,
        help="Traefik TCP port required to be reachable in apply mode.",
    )
    parser.add_argument(
        "--technitium-probe-server",
        default=DEFAULT_TECHNITIUM_PROBE_SERVER,
        help="Authoritative Technitium server IP for apply-mode dig validation.",
    )
    parser.add_argument(
        "--technitium-probe-name",
        default=DEFAULT_TECHNITIUM_PROBE_NAME,
        help="DNS name queried during apply-mode authoritative Technitium probe.",
    )
    parser.add_argument(
        "--technitium-probe-expected",
        default=DEFAULT_TECHNITIUM_PROBE_EXPECTED,
        help="Expected IPv4 answer in apply-mode authoritative Technitium probe.",
    )
    parser.add_argument(
        "--coredns-probe-server",
        default=DEFAULT_COREDNS_PROBE_SERVER,
        help="Authoritative CoreDNS server IP for apply-mode dig validation. Only used with --coredns.",
    )
    parser.add_argument(
        "--coredns-probe-name",
        default=DEFAULT_COREDNS_PROBE_NAME,
        help="DNS name queried during apply-mode authoritative CoreDNS probe. Only used with --coredns.",
    )
    parser.add_argument(
        "--target-preflight-expected",
        default=DEFAULT_TARGET_PREFLIGHT_EXPECTED,
        help="Expected target value returned by target preflight command in apply mode.",
    )
    parser.add_argument(
        "--coredns-probe-expected",
        default=DEFAULT_COREDNS_PROBE_EXPECTED,
        help="Expected IPv4 answer in apply-mode authoritative CoreDNS probe. Only used with --coredns.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply create/update reconciliation. Default behavior is dry-run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser.parse_args(argv)


def _resolve_manifest_paths(args: argparse.Namespace) -> list[Path]:
    if args.manifests:
        return sorted(path.resolve() for path in args.manifests)
    return discover_edge_manifests(args.stacks_dir.resolve())


def _manifest_requires_authentik(manifest_path: Path) -> bool:
    document = load_manifest(manifest_path)
    if not isinstance(document, dict):
        return False
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return False
    routes = spec.get("routes")
    if not isinstance(routes, list):
        return False

    for route in routes:
        if not isinstance(route, dict):
            continue
        auth = route.get("auth")
        if not isinstance(auth, dict):
            continue
        if str(auth.get("mode", "")).strip() in {"forwardAuth", "oidc"}:
            return True
    return False


def _selected_manifests_require_authentik(manifest_paths: list[Path]) -> bool:
    return any(_manifest_requires_authentik(path) for path in manifest_paths)


def _route_host_matches(document: dict[str, object], host: str) -> bool:
    spec = document.get("spec")
    if not isinstance(spec, dict):
        return False
    routes = spec.get("routes")
    if not isinstance(routes, list):
        return False
    for route in routes:
        if not isinstance(route, dict):
            continue
        route_host = str(route.get("host", "")).strip().rstrip(".")
        if route_host == host:
            return True
    return False


def _load_documents(manifest_paths: list[Path]) -> dict[Path, dict[str, object]]:
    docs: dict[Path, dict[str, object]] = {}
    for path in manifest_paths:
        document = load_manifest(path)
        if isinstance(document, dict):
            docs[path] = document
    return docs


def _inject_intended_replacement(
    manifest_paths: list[Path],
    intended_replacement_host: str,
) -> tuple[list[Path] | None, tempfile.TemporaryDirectory[str] | None, EdgeIssue | None]:
    host = intended_replacement_host.strip().rstrip(".")
    if not host:
        return None, None, EdgeIssue(
            code="EGR110",
            message="--intended-replacement-host must be a non-empty hostname",
        )

    documents = _load_documents(manifest_paths)
    matches = [path for path, document in documents.items() if _route_host_matches(document, host)]

    if not matches:
        return None, None, EdgeIssue(
            code="EGR111",
            message=(
                f"--intended-replacement-host {host} does not match any selected manifest route"
            ),
        )

    if len(matches) > 1:
        return None, None, EdgeIssue(
            code="EGR112",
            message=(
                f"--intended-replacement-host {host} matches multiple manifests; "
                "select only one migration target at a time"
            ),
        )

    replacement_manifest = matches[0]
    temp_dir: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory(prefix="edge-reconcile-")
    rewritten_paths: list[Path] = []

    for path in manifest_paths:
        doc = documents.get(path)
        if doc is None:
            doc = load_manifest(path)
        if path == replacement_manifest:
            doc["intendedReplacement"] = [{"hostname": host}]

        output_path = Path(temp_dir.name) / path.name
        output_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        rewritten_paths.append(output_path.resolve())

    return sorted(rewritten_paths), temp_dir, None


def _resolve_selected_manifests(
    args: argparse.Namespace,
) -> tuple[list[Path] | None, tempfile.TemporaryDirectory[str] | None, EdgeIssue | None]:
    manifest_paths = _resolve_manifest_paths(args)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    if not args.intended_replacement_host:
        return manifest_paths, temp_dir, None

    rewritten, temp_dir, replacement_issue = _inject_intended_replacement(
        manifest_paths,
        args.intended_replacement_host,
    )
    if replacement_issue is not None:
        return None, temp_dir, replacement_issue
    assert rewritten is not None
    return rewritten, temp_dir, None


def _render_outputs(
    args: argparse.Namespace,
    manifest_paths: list[Path],
) -> tuple[Any, Any, Any | None, list[EdgeIssue]]:
    issues: list[EdgeIssue] = []
    traefik_result = RENDER_TRAEFIK.render_traefik_dry_run(
        manifest_paths,
        args.legacy_playbook.resolve(),
    )
    technitium_result = RENDER_TECHNITIUM.render_technitium_dry_run(
        manifest_paths=manifest_paths,
        seed_zone_path=args.seed_zone.resolve(),
        output_records_path=args.technitium_output_records.resolve(),
    )

    coredns_result = None
    if args.coredns:
        coredns_result = RENDER_COREDNS.render_coredns_dry_run(
            manifest_paths=manifest_paths,
            seed_zone_path=args.seed_zone.resolve(),
            output_zone_path=args.coredns_output_zone.resolve(),
            validate_live_forwarding=False,
        )

    if not traefik_result.ok:
        issues.append(EdgeIssue(code="EGR130", message="Traefik render failed"))
    if not technitium_result.ok:
        issues.append(EdgeIssue(code="EGR132", message="Technitium render failed"))
    if coredns_result is not None and not coredns_result.ok:
        issues.append(EdgeIssue(code="EGR131", message="CoreDNS render failed"))
    return traefik_result, technitium_result, coredns_result, issues


def _run_pve_target_preflight(expected_target: str) -> tuple[bool, str]:
    repo_root = SCRIPT_DIR.parents[1]
    target_command = _resolve_target_preflight_command(repo_root, expected_target)
    result = subprocess.run(
        list(target_command),
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = (
            f"target preflight command failed with exit code {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip() or '<no output>'}"
        )
        return False, message

    target = result.stdout.strip()
    if target != expected_target:
        return False, f"target preflight reported {target!r}, expected {expected_target!r}"
    return True, f"target preflight passed ({expected_target})"


def _resolve_target_preflight_command(repo_root: Path, expected_target: str) -> tuple[str, ...]:
    configured_command = os.environ.get("EDGE_TARGET_PREFLIGHT_COMMAND", "").strip()
    if configured_command:
        return tuple(configured_command.split())

    target = expected_target.strip() or os.environ.get("PVE_ENV", "").strip() or "pve-test"
    wrapper_name = "with-secrets-prod" if target == "pve" else "with-secrets"
    return (str(repo_root / wrapper_name), "bash", "-c", "echo $TF_VAR_proxmox_node")


def _tcp_health_check(host: str, port: int) -> HealthCheckResult:
    probe_target = f"tcp://{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=5):
            return HealthCheckResult(
                name="",
                url=probe_target,
                ok=True,
                status_code=None,
                detail="tcp reachability probe succeeded",
            )
    except Exception as exc:
        return HealthCheckResult(
            name="",
            url=probe_target,
            ok=False,
            status_code=None,
            detail=f"tcp reachability probe failed: {exc}",
        )


def _dns_authority_health_check(server: str, name: str, expected: str) -> HealthCheckResult:
    probe_target = f"dig @{server} +short {name}"
    result = subprocess.run(
        ["dig", f"@{server}", "+short", name],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"dig exited {result.returncode}"
        return HealthCheckResult(
            name="",
            url=probe_target,
            ok=False,
            status_code=None,
            detail=f"authoritative dns probe failed: {detail}",
        )

    answers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if expected in answers:
        return HealthCheckResult(
            name="",
            url=probe_target,
            ok=True,
            status_code=None,
            detail=f"authoritative dns probe succeeded (answer includes {expected})",
        )

    return HealthCheckResult(
        name="",
        url=probe_target,
        ok=False,
        status_code=None,
        detail=f"authoritative dns probe returned {answers or ['<empty>']}, expected {expected}",
    )


def _build_failed_result(
    *,
    applied: bool,
    manifest_paths: list[Path] | None = None,
    validation: dict[str, object] | None = None,
    traefik: dict[str, object] | None = None,
    technitium: dict[str, object] | None = None,
    coredns: dict[str, object] | None = None,
    issues: list[EdgeIssue],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "failed",
        "mode": "apply" if applied else "dry-run",
        "terraform_state_mutation": False,
        "issues": [issue.to_dict() for issue in issues],
    }
    if manifest_paths is not None:
        payload["manifests"] = [str(path) for path in manifest_paths]
    if validation is not None:
        payload["validation"] = validation
    if traefik is not None:
        payload["traefik"] = traefik
    if technitium is not None:
        payload["technitium"] = technitium
    if coredns is not None:
        payload["coredns"] = coredns
    return payload


def _run_apply_preflights(
    args: argparse.Namespace,
) -> tuple[HealthPhaseResult, list[EdgeIssue]]:
    issues: list[EdgeIssue] = []
    target_ok, target_detail = _run_pve_target_preflight(args.target_preflight_expected)
    if not target_ok:
        issues.append(EdgeIssue(code="EGR200", message=target_detail))

    traefik_probe = _tcp_health_check(args.traefik_probe_host, args.traefik_probe_port)
    traefik_health = HealthCheckResult(
        name="traefik",
        url=traefik_probe.url,
        ok=traefik_probe.ok,
        status_code=traefik_probe.status_code,
        detail=traefik_probe.detail,
    )
    if not traefik_health.ok:
        issues.append(EdgeIssue(code="EGR201", message=f"Traefik health check failed: {traefik_health.detail}"))

    technitium_probe = _dns_authority_health_check(
        args.technitium_probe_server,
        args.technitium_probe_name,
        args.technitium_probe_expected,
    )
    technitium_health = HealthCheckResult(
        name="technitium",
        url=technitium_probe.url,
        ok=technitium_probe.ok,
        status_code=technitium_probe.status_code,
        detail=technitium_probe.detail,
    )
    if not technitium_health.ok:
        issues.append(EdgeIssue(code="EGR203", message=f"Technitium health check failed: {technitium_health.detail}"))

    coredns_health: HealthCheckResult | None = None
    if args.coredns:
        coredns_probe = _dns_authority_health_check(
            args.coredns_probe_server,
            args.coredns_probe_name,
            args.coredns_probe_expected,
        )
        coredns_health = HealthCheckResult(
            name="coredns",
            url=coredns_probe.url,
            ok=coredns_probe.ok,
            status_code=coredns_probe.status_code,
            detail=coredns_probe.detail,
        )
        if not coredns_health.ok:
            issues.append(EdgeIssue(code="EGR202", message=f"CoreDNS health check failed: {coredns_health.detail}"))

    health = HealthPhaseResult(
        target_detail=target_detail,
        traefik=traefik_health,
        technitium=technitium_health,
        coredns=coredns_health,
    )
    return health, issues


def _discovery_has_route_drift(discovery: dict[str, object] | None) -> bool:
    if not isinstance(discovery, dict):
        return False

    route_results = discovery.get("route_results")
    if isinstance(route_results, list):
        for route_result in route_results:
            if not isinstance(route_result, dict):
                continue
            if str(route_result.get("classification", "")).strip() != "matching":
                return True

    issue_count = discovery.get("issue_count")
    stop_condition_count = discovery.get("stop_condition_count")
    if isinstance(issue_count, int) and issue_count > 0:
        return True
    if isinstance(stop_condition_count, int) and stop_condition_count > 0:
        return True

    return False


def _is_probe_connectivity_only_failure(reconcile: dict[str, object] | None) -> bool:
    if not isinstance(reconcile, dict):
        return False

    issues = reconcile.get("issues")
    if not isinstance(issues, list) or not issues:
        return False

    saw_probe_issue = False
    for issue in issues:
        if not isinstance(issue, dict):
            return False
        code = str(issue.get("code", "")).strip()
        message = str(issue.get("message", "")).lower()
        if code != "AKR004":
            return False
        if "connectivity failure" not in message:
            return False
        saw_probe_issue = True

    return saw_probe_issue


def _run_authentik_phase(
    *,
    manifest_paths: list[Path],
    args: argparse.Namespace,
    applied: bool,
    has_preflight_issues: bool,
) -> tuple[dict[str, object] | None, dict[str, object] | None, dict[str, object] | None, list[EdgeIssue]]:
    """Run Authentik discovery and reconcile phases.

    Returns: (discovery_dict, post_apply_discovery_dict, reconcile_dict, issues)

    In dry-run mode, or when preflight issues prevented the apply, post_apply_discovery_dict
    is None and EGR211 is evaluated against the pre-apply discovery snapshot.

    In apply mode with a successful reconcile, post_apply_discovery_dict is the result of a
    fresh discovery run after the apply; EGR211 is evaluated against that post-apply result
    rather than the stale pre-apply snapshot.
    """
    issues: list[EdgeIssue] = []
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        return (
            None,
            None,
            None,
            [
                EdgeIssue(
                    code="EGR210",
                    message=(
                        f"selected manifests require Authentik objects but {args.token_env} is missing"
                    ),
                )
            ],
        )

    discovery_client = DISCOVER_AUTHENTIK.AuthentikApiClient(
        base_url=args.authentik_url,
        token=token,
        verify_tls=not args.no_verify_tls,
    )
    discovery = DISCOVER_AUTHENTIK.discover_authentik_drift(manifest_paths, discovery_client)
    discovery_dict = discovery.to_dict()

    reconcile_client = RECONCILE_AUTHENTIK.AuthentikApiClient(
        base_url=args.authentik_url,
        token=token,
        verify_tls=not args.no_verify_tls,
    )
    reconcile = RECONCILE_AUTHENTIK.reconcile_authentik(
        manifest_paths,
        reconcile_client,
        apply=applied and not has_preflight_issues,
    )
    reconcile_dict = reconcile.to_dict()

    # In apply mode, if reconcile succeeded, re-run discovery to obtain a post-apply
    # convergence result.  The pre-apply discovery is kept for audit, but EGR211 is
    # evaluated against the post-apply snapshot so that expected pre-apply drift that was
    # fully resolved by the apply does not force a spurious top-level failure.
    post_apply_discovery_dict: dict[str, object] | None = None
    effective_discovery = discovery_dict
    if applied and not has_preflight_issues and reconcile.ok:
        post_apply_client = DISCOVER_AUTHENTIK.AuthentikApiClient(
            base_url=args.authentik_url,
            token=token,
            verify_tls=not args.no_verify_tls,
        )
        post_apply_discovery = DISCOVER_AUTHENTIK.discover_authentik_drift(manifest_paths, post_apply_client)
        post_apply_discovery_dict = post_apply_discovery.to_dict()
        effective_discovery = post_apply_discovery_dict

    if _discovery_has_route_drift(effective_discovery):
        issues.append(EdgeIssue(code="EGR211", message="Authentik discovery reported drift/issues"))
    if not reconcile.ok:
        if _is_probe_connectivity_only_failure(reconcile_dict):
            issues.append(
                EdgeIssue(
                    code="EGR213",
                    message="Authentik forward-auth probe connectivity failed",
                )
            )
        else:
            issues.append(EdgeIssue(code="EGR212", message="Authentik reconcile plan/apply failed"))

    return discovery_dict, post_apply_discovery_dict, reconcile_dict, issues


def _dry_run_health_stubs(args: argparse.Namespace) -> HealthPhaseResult:
    traefik_health = HealthCheckResult(
        name="traefik",
        url=f"tcp://{args.traefik_probe_host}:{args.traefik_probe_port}",
        ok=True,
        status_code=None,
        detail=NOT_RUN_DRY_RUN,
    )
    technitium_health = HealthCheckResult(
        name="technitium",
        url=f"dig @{args.technitium_probe_server} +short {args.technitium_probe_name}",
        ok=True,
        status_code=None,
        detail=NOT_RUN_DRY_RUN,
    )
    coredns_health: HealthCheckResult | None = None
    if args.coredns:
        coredns_health = HealthCheckResult(
            name="coredns",
            url=f"dig @{args.coredns_probe_server} +short {args.coredns_probe_name}",
            ok=True,
            status_code=None,
            detail=NOT_RUN_DRY_RUN,
        )
    return HealthPhaseResult(
        target_detail=NOT_RUN_DRY_RUN,
        traefik=traefik_health,
        technitium=technitium_health,
        coredns=coredns_health,
    )


def _write_render_outputs(
    args: argparse.Namespace,
    traefik_result: Any,
    technitium_result: Any,
    coredns_result: Any | None,
) -> RenderPhaseResult:
    traefik_output_dir = args.traefik_output_dir.resolve()
    rendered_files = [
        str(path) for path in RENDER_TRAEFIK.write_rendered_files(traefik_result.rendered, traefik_output_dir)
    ]
    rendered_records = str(
        RENDER_TECHNITIUM.write_rendered_records(
            technitium_result.zone, technitium_result.records, args.technitium_output_records.resolve()
        )
    )
    rendered_zone: str | None = None
    if coredns_result is not None:
        rendered_zone = str(
            RENDER_COREDNS.write_rendered_zone(coredns_result.rendered_zone, args.coredns_output_zone.resolve())
        )
    return RenderPhaseResult(
        traefik_result=traefik_result,
        technitium_result=technitium_result,
        coredns_result=coredns_result,
        traefik_output_dir=traefik_output_dir,
        rendered_files=rendered_files,
        rendered_records=rendered_records,
        rendered_zone=rendered_zone,
    )


def _build_passed_payload(
    *,
    applied: bool,
    repo_root: Path,
    args: argparse.Namespace,
    manifest_paths: list[Path],
    validation: Any,
    render: RenderPhaseResult,
    health: HealthPhaseResult,
    auth: AuthentikPhaseResult,
    issues: list[EdgeIssue],
) -> dict[str, object]:
    coredns_payload = (
        {**render.coredns_result.to_dict(), "output_zone": render.rendered_zone}
        if render.coredns_result is not None
        else None
    )
    coredns_health_payload = health.coredns.to_dict() if health.coredns is not None else None

    return {
        "status": "passed" if not issues else "failed",
        "mode": "apply" if applied else "dry-run",
        "terraform_state_mutation": False,
        "manifests": [str(path) for path in manifest_paths],
        "validation": validation.to_dict(),
        "preflight": {
            "targeting": {
                "command": " ".join(_resolve_target_preflight_command(repo_root, args.target_preflight_expected)),
                "detail": health.target_detail,
                "ok": not applied or not any(issue.code == "EGR200" for issue in issues),
            },
            "health": {
                "traefik": health.traefik.to_dict(),
                "technitium": health.technitium.to_dict(),
                "coredns": coredns_health_payload,
            },
        },
        "traefik": {
            **render.traefik_result.to_dict(),
            "output_dir": str(render.traefik_output_dir),
            "files": render.rendered_files,
        },
        "technitium": {
            **render.technitium_result.to_dict(),
            "output_records": render.rendered_records,
        },
        "coredns": coredns_payload,
        "authentik": {
            "required": auth.needs_authentik,
            "discovery": auth.discovery,
            "post_apply_discovery": auth.post_apply_discovery,
            "reconcile": auth.reconcile,
        },
        "issues": [issue.to_dict() for issue in issues],
    }


def reconcile_edge(args: argparse.Namespace) -> dict[str, object]:  # nosonar: python:S3776 -- sequential fail-fast pipeline (manifest resolution -> validation -> render -> preflight -> Authentik), each stage already extracted to its own helper; further splitting the gating/cleanup itself would fragment one linear flow across more functions without making it clearer
    issues: list[EdgeIssue] = []
    applied = bool(args.apply)
    repo_root = SCRIPT_DIR.parents[1]
    manifest_paths, temp_dir, replacement_issue = _resolve_selected_manifests(args)
    if replacement_issue is not None:
        return _build_failed_result(applied=applied, issues=[replacement_issue])
    assert manifest_paths is not None

    validation = validate_manifests(manifest_paths)
    if not validation.ok:
        result = _build_failed_result(
            applied=applied,
            manifest_paths=manifest_paths,
            validation=validation.to_dict(),
            issues=[EdgeIssue(code="EGR120", message="edge manifest validation failed")],
        )
        if temp_dir is not None:
            temp_dir.cleanup()
        return result

    traefik_result, technitium_result, coredns_result, render_issues = _render_outputs(args, manifest_paths)
    issues.extend(render_issues)

    if issues:
        result = _build_failed_result(
            applied=applied,
            manifest_paths=manifest_paths,
            validation=validation.to_dict(),
            traefik=traefik_result.to_dict(),
            technitium=technitium_result.to_dict(),
            coredns=coredns_result.to_dict() if coredns_result is not None else None,
            issues=issues,
        )
        if temp_dir is not None:
            temp_dir.cleanup()
        return result

    render = _write_render_outputs(args, traefik_result, technitium_result, coredns_result)

    needs_authentik = _selected_manifests_require_authentik(manifest_paths)
    discovery_dict: dict[str, object] | None = None
    post_apply_discovery_dict: dict[str, object] | None = None
    reconcile_dict: dict[str, object] | None = None

    if applied:
        health, preflight_issues = _run_apply_preflights(args)
        issues.extend(preflight_issues)
    else:
        health = _dry_run_health_stubs(args)

    if needs_authentik:
        discovery_dict, post_apply_discovery_dict, reconcile_dict, auth_issues = _run_authentik_phase(
            manifest_paths=manifest_paths,
            args=args,
            applied=applied,
            has_preflight_issues=bool(issues),
        )
        issues.extend(auth_issues)

    auth = AuthentikPhaseResult(
        needs_authentik=needs_authentik,
        discovery=discovery_dict,
        post_apply_discovery=post_apply_discovery_dict,
        reconcile=reconcile_dict,
    )

    payload = _build_passed_payload(
        applied=applied,
        repo_root=repo_root,
        args=args,
        manifest_paths=manifest_paths,
        validation=validation,
        render=render,
        health=health,
        auth=auth,
        issues=issues,
    )

    if temp_dir is not None:
        temp_dir.cleanup()
    return payload


def _print_validation_summary(validation: dict[str, object]) -> None:
    print(
        "Validation: "
        f"{validation.get('status')} "
        f"(manifests={validation.get('manifest_count')}, issues={validation.get('issue_count')})"
    )


def _print_traefik_summary(traefik: dict[str, object]) -> None:
    print(
        "Traefik render: "
        f"{traefik.get('status')} "
        f"(stacks={traefik.get('stack_count')}, issues={traefik.get('issue_count')})"
    )
    files = traefik.get("files")
    if not isinstance(files, list):
        return
    for file_path in files:
        print(f"- wrote: {file_path}")


def _print_coredns_summary(coredns: dict[str, object]) -> None:
    print(
        "CoreDNS render: "
        f"{coredns.get('status')} "
        f"(records={coredns.get('generated_record_count')}, issues={coredns.get('issue_count')})"
    )
    output_zone = coredns.get("output_zone")
    if output_zone:
        print(f"- wrote: {output_zone}")


def _print_authentik_summary(auth: dict[str, object]) -> None:
    if not auth.get("required"):
        print("Authentik: not required by selected manifests.")
        return

    discovery = auth.get("discovery")
    if isinstance(discovery, dict):
        print(
            "Authentik discovery: "
            f"{discovery.get('status')} "
            f"(routes={discovery.get('route_count')}, issues={discovery.get('issue_count')})"
        )

    reconcile = auth.get("reconcile")
    if isinstance(reconcile, dict):
        print(
            "Authentik reconcile: "
            f"{reconcile.get('status')} "
            f"(actions={reconcile.get('action_count')}, writes={reconcile.get('write_count')})"
        )


def _print_issue_summary(issues: list[dict[str, object]]) -> None:
    if not issues:
        return
    print(f"Issues: {len(issues)}")
    for issue in issues:
        print(f"- [{issue.get('code')}] {issue.get('message')}")


def _print_human_result(result: dict[str, object]) -> None:
    mode = str(result.get("mode", "dry-run"))
    print(f"Edge reconciliation {mode} completed.")
    print(f"Status: {result.get('status')}")

    validation = result.get("validation")
    if isinstance(validation, dict):
        _print_validation_summary(validation)

    traefik = result.get("traefik")
    if isinstance(traefik, dict):
        _print_traefik_summary(traefik)

    coredns = result.get("coredns")
    if isinstance(coredns, dict):
        _print_coredns_summary(coredns)

    auth = result.get("authentik")
    if isinstance(auth, dict):
        _print_authentik_summary(auth)

    issues = result.get("issues")
    if isinstance(issues, list) and issues:
        _print_issue_summary([issue for issue in issues if isinstance(issue, dict)])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = reconcile_edge(args)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human_result(result)

    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
