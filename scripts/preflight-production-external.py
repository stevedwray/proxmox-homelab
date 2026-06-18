#!/usr/bin/env python3
"""Production external infrastructure preflight.

Verifies that production SOPS secrets are present (env vars injected by
with-secrets-prod) and that all external systems are reachable with the
configured credentials. Covers systems that exist independently of the
infrastructure stack being deployed.

External systems checked:
  - Proxmox API (PVE token auth — required for Terraform apply)
  - MikroTik RouterOS API (read-only credentials — required for netbox-populate)
  - Cloudflare DNS API token (required for proxy-stack ACME DNS challenge)
  - SSH to pve host (required for Ansible provisioning)
  - GitHub CLI authentication (required for ci-runner-01 registration)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS_DIR = REPO_ROOT / "terraform" / "lxc" / "stacks" / "netbox-stack" / "integrations"
sys.path.insert(0, str(INTEGRATIONS_DIR))

from proxmox_client import ProxmoxClient  # type: ignore  # noqa: E402
from mikrotik_client import MikrotikClient  # type: ignore  # noqa: E402

# Check name constants — each used across multiple CheckResult calls in the same function
_CHECK_PVE_REACHABLE = "proxmox:api-reachable"
_CHECK_CF_TOKEN = "cloudflare:token"
_CHECK_SSH_PVE = "ssh:pve"
_CHECK_GH_AUTH = "github:cli-auth"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    warning: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify production SOPS secrets are present and all external infrastructure "
            "systems (Proxmox, MikroTik, Cloudflare, SSH, GitHub) are reachable."
        )
    )
    parser.add_argument(
        "--save-evidence",
        metavar="PATH",
        help="Write output to PATH, or to a timestamped file if PATH is a directory.",
    )
    return parser.parse_args()


def write_evidence(target: str | None, content: str) -> str | None:
    if not target:
        return None
    path = Path(target)
    if path.is_dir():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = path / f"preflight-production-external-{stamp}.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


def run_command(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def result_level(r: CheckResult) -> str:
    if r.ok:
        return "PASS"
    if r.warning:
        return "WARN"
    return "FAIL"


# ---------------------------------------------------------------------------
# Check groups
# ---------------------------------------------------------------------------


def check_required_env_vars() -> list[CheckResult]:
    """Verify required secrets and config are present in the injected environment."""
    results = []

    required = {
        # Non-secret config (from .env / .env.pve)
        "PROXMOX_HOST": "Proxmox hostname — needed for API and SSH",
        "MIKROTIK_HOST": "MikroTik hostname — needed for VLAN/topology preflight",
        # Secrets (from SOPS after with-secrets-prod merge)
        "TF_VAR_pm_api_token_id": "Proxmox API token ID — needed for Terraform",
        "TF_VAR_pm_api_token_secret": "Proxmox API token secret — needed for Terraform",
        "MIKROTIK_USER": "MikroTik read-only user — needed for netbox-populate",
        "MIKROTIK_PASSWORD": "MikroTik read-only password — needed for netbox-populate",
        "CF_DNS_API_TOKEN": "Cloudflare DNS API token — needed for proxy-stack ACME",
    }

    for key, purpose in required.items():
        value = os.environ.get(key, "")
        if value:
            is_secret = (
                "token_secret" in key.lower()
                or "password" in key.lower()
                or ("token" in key.lower() and "id" not in key.lower())
            )
            display = value if not is_secret else f"<set, {len(value)} chars>"
            results.append(CheckResult(f"env:{key}", True, f"present — {purpose} ({display})"))
        else:
            results.append(CheckResult(f"env:{key}", False, f"missing — {purpose}"))

    return results


def check_proxmox_api() -> list[CheckResult]:
    """Verify Proxmox API is reachable and the token authenticates."""
    results = []
    host = os.environ.get("PROXMOX_HOST", "")

    try:
        client = ProxmoxClient()
    except ValueError as exc:
        results.append(CheckResult("proxmox:credentials", False, str(exc)))
        return results

    results.append(CheckResult("proxmox:credentials", True, f"token_id={client.token_id}"))

    try:
        version = client.get("/version")
        pve_ver = version.get("data", {}).get("version", "unknown")
        results.append(CheckResult(_CHECK_PVE_REACHABLE, True, f"{host}:8006 → PVE {pve_ver}"))
    except RuntimeError as exc:
        msg = str(exc)
        if "401" in msg:
            results.append(CheckResult(
                _CHECK_PVE_REACHABLE,
                False,
                f"{host}:8006 reachable but token rejected (401) — "
                "verify token exists on pve and secret in secrets.pve.enc.yaml matches",
            ))
        else:
            results.append(CheckResult(_CHECK_PVE_REACHABLE, False, f"{host}:8006 error: {exc}"))
        return results
    except Exception as exc:
        results.append(CheckResult(_CHECK_PVE_REACHABLE, False, f"{host}:8006 unreachable: {exc}"))
        return results

    try:
        nodes = client.get_nodes()
        node_names = [n.get("node", "?") for n in nodes]
        results.append(CheckResult("proxmox:token-auth", True, f"nodes visible: {node_names}"))
    except Exception as exc:
        results.append(CheckResult("proxmox:token-auth", False, f"node list failed (token may lack permission): {exc}"))

    return results


def check_mikrotik_api() -> list[CheckResult]:
    """Verify MikroTik API is reachable and the read-only credentials work."""
    results = []
    host = os.environ.get("MIKROTIK_HOST", "")

    try:
        client = MikrotikClient(port=int(os.environ.get("MIKROTIK_PORT", "443")))
    except ValueError as exc:
        results.append(CheckResult("mikrotik:credentials", False, str(exc)))
        return results

    results.append(CheckResult("mikrotik:credentials", True, f"user={client.user} host={host}"))

    try:
        resource = client.get("/system/resource")
        if isinstance(resource, dict):
            obj = resource
        else:
            obj = resource[0] if resource else {}
        version = obj.get("version", "unknown")
        board = obj.get("board-name", "unknown")
        results.append(CheckResult("mikrotik:api-reachable", True, f"{host} → RouterOS {version} ({board})"))
    except Exception as exc:
        results.append(CheckResult("mikrotik:api-reachable", False, f"{host} unreachable or auth failed: {exc}"))

    return results


def check_cloudflare_token() -> list[CheckResult]:
    """Verify the Cloudflare DNS API token is valid."""
    results = []
    token = os.environ.get("CF_DNS_API_TOKEN", "")

    if not token:
        results.append(CheckResult(_CHECK_CF_TOKEN, False, "CF_DNS_API_TOKEN not set"))
        return results

    try:
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        # api.cloudflare.com uses a publicly trusted CA — no custom SSL context needed
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — public Cloudflare API
            body = json.loads(resp.read().decode())

        if body.get("success") and body.get("result", {}).get("status") == "active":
            token_id = body.get("result", {}).get("id", "?")
            results.append(CheckResult(_CHECK_CF_TOKEN, True, f"token active (id={token_id})"))
        else:
            messages = body.get("errors") or body.get("messages") or []
            results.append(CheckResult(_CHECK_CF_TOKEN, False, f"token not active: {messages}"))

    except urllib.error.HTTPError as exc:
        results.append(CheckResult(_CHECK_CF_TOKEN, False, f"HTTP {exc.code}: {exc.reason}"))
    except Exception as exc:
        results.append(CheckResult(_CHECK_CF_TOKEN, False, f"request failed: {exc}"))

    return results


def check_ssh_to_pve() -> list[CheckResult]:
    """Verify SSH connectivity to the pve host."""
    results = []
    host = os.environ.get("PROXMOX_HOST", "")

    if not host:
        results.append(CheckResult(_CHECK_SSH_PVE, False, "PROXMOX_HOST not set"))
        return results

    if shutil.which("ssh") is None:
        results.append(CheckResult(_CHECK_SSH_PVE, False, "ssh not found in PATH", warning=True))
        return results

    result = run_command(
        [
            "ssh",
            "-F", "/dev/null",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            f"root@{host}",
            "echo ok",
        ],
        timeout=20,
    )

    if result.returncode == 0 and result.stdout.strip() == "ok":
        results.append(CheckResult(_CHECK_SSH_PVE, True, f"root@{host} — connection successful"))
    else:
        error = (result.stderr or result.stdout).strip() or "no output"
        results.append(CheckResult(_CHECK_SSH_PVE, False, f"root@{host} failed (exit {result.returncode}): {error}"))

    return results


def check_github_cli() -> list[CheckResult]:
    """Verify GitHub CLI is authenticated (required for ci-runner-01 registration)."""
    results = []

    if shutil.which("gh") is None:
        results.append(CheckResult(_CHECK_GH_AUTH, False, "gh not found in PATH — required for ci-runner-01 registration"))
        return results

    result = run_command(["gh", "auth", "status"], timeout=15)

    if result.returncode == 0:
        for line in (result.stdout + result.stderr).splitlines():
            if "Logged in to" in line or "account" in line.lower():
                results.append(CheckResult(_CHECK_GH_AUTH, True, line.strip()))
                return results
        results.append(CheckResult(_CHECK_GH_AUTH, True, "gh auth status passed"))
    else:
        error = (result.stderr or result.stdout).strip()
        results.append(CheckResult(_CHECK_GH_AUTH, False, f"not authenticated: {error}"))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    branch_result = run_command(["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"])
    git_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    pve_host = os.environ.get("PROXMOX_HOST", "unset")
    target_node = os.environ.get("TF_VAR_proxmox_node", "unset")

    all_results: list[CheckResult] = []
    all_results += check_required_env_vars()
    all_results += check_proxmox_api()
    all_results += check_mikrotik_api()
    all_results += check_cloudflare_token()
    all_results += check_ssh_to_pve()
    all_results += check_github_cli()

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("PRODUCTION EXTERNAL INFRASTRUCTURE PREFLIGHT")
    lines.append(f"Run:    {now}")
    lines.append(f"Branch: {git_branch}")
    lines.append(f"Target: TF_VAR_proxmox_node={target_node}")
    lines.append(f"Host:   {pve_host}")
    lines.append("=" * 70)

    sections = [
        ("Required env vars", [r for r in all_results if r.name.startswith("env:")]),
        ("Proxmox API", [r for r in all_results if r.name.startswith("proxmox:")]),
        ("MikroTik API", [r for r in all_results if r.name.startswith("mikrotik:")]),
        ("Cloudflare DNS token", [r for r in all_results if r.name.startswith("cloudflare:")]),
        ("SSH to pve host", [r for r in all_results if r.name.startswith("ssh:")]),
        ("GitHub CLI auth", [r for r in all_results if r.name.startswith("github:")]),
    ]

    for section_title, section_results in sections:
        lines.append(f"\n--- {section_title} ---")
        for result in section_results:
            lines.append(f"  [{result_level(result)}] {result.name}: {result.detail}")

    fail_count = sum(1 for r in all_results if not r.ok and not r.warning)
    warn_count = sum(1 for r in all_results if r.warning)
    pass_count = sum(1 for r in all_results if r.ok)

    lines.append("\n" + "-" * 70)
    lines.append(f"Checks passed: {pass_count}")
    lines.append(f"Warnings:      {warn_count}")
    lines.append(f"Checks failed: {fail_count}")
    lines.append(f"Verdict: {'PASS' if fail_count == 0 else 'FAIL'}")

    output = "\n".join(lines)
    print(output)

    written = write_evidence(args.save_evidence, output)
    if written:
        print(f"\nEvidence written to: {written}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
