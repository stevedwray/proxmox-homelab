#!/usr/bin/env python3
"""Rotate supported production stack credentials and reconcile affected stacks."""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
PROD_SECRETS_FILE = REPO_ROOT / "terraform" / "secrets.pve.enc.yaml"
WITH_SECRETS_PROD = REPO_ROOT / "with-secrets-prod"
PROVISION_SCRIPT = REPO_ROOT / "scripts" / "provision.sh"
AGE_KEY_FILE = Path.home() / ".config" / "sops" / "age" / "keys.txt"


@dataclass(frozen=True)
class Capability:
    name: str
    sops_key: str
    stack: str
    generator: str
    description: str


SUPPORTED_CAPABILITIES: "OrderedDict[str, Capability]" = OrderedDict(
    [
        (
            "authentik-lab-admin-password",
            Capability(
                name="authentik-lab-admin-password",
                sops_key="AUTHENTIK_STEVE_PASSWORD",
                stack="authentik-stack",
                generator="password",
                description="Rotate the Authentik lab-admin user password.",
            ),
        ),
        (
            "netbox-superuser-password",
            Capability(
                name="netbox-superuser-password",
                sops_key="NETBOX_SUPERUSER_PASSWORD",
                stack="netbox-stack",
                generator="password",
                description="Rotate the NetBox local superuser password.",
            ),
        ),
        (
            "grafana-oauth-client-secret",
            Capability(
                name="grafana-oauth-client-secret",
                sops_key="GRAFANA_OAUTH_CLIENT_SECRET",
                stack="monitoring-stack",
                generator="client-secret",
                description="Rotate the Grafana Authentik OIDC client secret.",
            ),
        ),
        (
            "harbor-oidc-client-secret",
            Capability(
                name="harbor-oidc-client-secret",
                sops_key="HARBOR_OIDC_CLIENT_SECRET",
                stack="harbor-stack",
                generator="client-secret",
                description="Rotate the Harbor Authentik OIDC client secret.",
            ),
        ),
        (
            "portainer-oauth-client-secret",
            Capability(
                name="portainer-oauth-client-secret",
                sops_key="PORTAINER_OAUTH_CLIENT_SECRET",
                stack="portainer-stack",
                generator="client-secret",
                description="Rotate the Portainer Authentik OIDC client secret.",
            ),
        ),
    ]
)

UNSUPPORTED_KEYS = (
    "HARBOR_ADMIN_PASSWORD",
    "TF_VAR_portainer_admin_password",
    "GRAFANA_ADMIN_PASSWORD",
    "BREAKGLASS_PASSWORD",
    "AUTHENTIK_SUPERUSER_PASSWORD",
    "AUTHENTIK_SUPERUSER_API_TOKEN",
    "NETBOX_SUPERUSER_API_TOKEN",
    "STEP_CA_PASSWORD",
    "STEP_CA_PROVISIONER_PASSWORD",
)


def fail(message: str) -> "NoReturn":
    print(f"[rotate-stack-credentials] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def info(message: str) -> None:
    print(f"[rotate-stack-credentials] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rotate supported production stack credentials in "
            "terraform/secrets.pve.enc.yaml and reconcile the owning stacks."
        )
    )
    parser.add_argument(
        "--credential",
        action="append",
        choices=list(SUPPORTED_CAPABILITIES.keys()),
        help="Credential capability to rotate. Repeat to rotate multiple values.",
    )
    parser.add_argument(
        "--all-supported",
        action="store_true",
        help="Rotate every currently supported credential capability.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually update SOPS and run the affected Ansible reconcile commands.",
    )
    parser.add_argument(
        "--skip-reconcile",
        action="store_true",
        help="Update SOPS only; do not run post-rotation stack reconcile.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List supported and unsupported credential rotation capabilities.",
    )
    return parser.parse_args()


def generate_secret(generator: str) -> str:
    if generator == "password":
        return secrets.token_urlsafe(24)
    if generator == "client-secret":
        return secrets.token_hex(32)
    fail(f"unsupported generator type: {generator}")


def ensure_prerequisites() -> None:
    if not PROD_SECRETS_FILE.is_file():
        fail(f"production secrets file not found: {PROD_SECRETS_FILE}")
    if not WITH_SECRETS_PROD.is_file():
        fail(f"production wrapper not found: {WITH_SECRETS_PROD}")
    if not os.access(WITH_SECRETS_PROD, os.X_OK):
        fail(f"production wrapper is not executable: {WITH_SECRETS_PROD}")
    if not PROVISION_SCRIPT.is_file():
        fail(f"provision script not found: {PROVISION_SCRIPT}")
    if not AGE_KEY_FILE.is_file():
        fail(f"age key file not found: {AGE_KEY_FILE}")


def load_overlay_vars(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def ensure_production_targeting() -> None:
    merged = {}
    merged.update(load_overlay_vars(REPO_ROOT / ".env"))
    merged.update(load_overlay_vars(REPO_ROOT / ".env.pve"))
    proxmox_node = merged.get("TF_VAR_proxmox_node", "pve")
    if proxmox_node != "pve":
        fail(
            "production targeting guard failed: .env/.env.pve resolve "
            f"TF_VAR_proxmox_node={proxmox_node!r}, expected 'pve'"
        )


def decrypt_yaml(path: Path) -> dict:
    result = subprocess.run(
        ["sops", "--decrypt", str(path)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "SOPS_AGE_KEY_FILE": str(AGE_KEY_FILE)},
    )
    data = yaml.safe_load(result.stdout) or {}
    if not isinstance(data, dict):
        fail(f"expected top-level YAML mapping in {path}")
    return data


def encrypt_yaml(path: Path, data: dict) -> None:
    plaintext = yaml.safe_dump(data, sort_keys=False)
    result = subprocess.run(
        [
            "sops",
            "--encrypt",
            "--input-type",
            "yaml",
            "--output-type",
            "yaml",
            "--filename-override",
            str(path),
            "/dev/stdin",
        ],
        check=True,
        capture_output=True,
        text=True,
        input=plaintext,
        env={**os.environ, "SOPS_AGE_KEY_FILE": str(AGE_KEY_FILE)},
    )
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(result.stdout, encoding="utf-8")
    os.replace(temp_path, path)


def dedupe_capabilities(args: argparse.Namespace) -> list[Capability]:
    selected_names: list[str] = []
    if args.all_supported:
        selected_names.extend(SUPPORTED_CAPABILITIES.keys())
    if args.credential:
        selected_names.extend(args.credential)
    if not selected_names:
        fail("select at least one --credential or pass --all-supported")

    ordered: list[Capability] = []
    seen: set[str] = set()
    for name in selected_names:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(SUPPORTED_CAPABILITIES[name])
    return ordered


def list_capabilities() -> None:
    print("Supported credential rotation capabilities:")
    for capability in SUPPORTED_CAPABILITIES.values():
        print(
            f"- {capability.name}: {capability.sops_key} -> {capability.stack} "
            f"({capability.description})"
        )

    print("\nNot supported yet:")
    for key in UNSUPPORTED_KEYS:
        print(f"- {key}")


def reconcile_stacks(capabilities: list[Capability]) -> None:
    if "TASK_APPROVAL" not in os.environ or not os.environ["TASK_APPROVAL"].strip():
        fail(
            "TASK_APPROVAL must be set before running production reconcile. "
            "Example: TASK_APPROVAL=prod-credential-rotation"
        )

    ordered_stacks: list[str] = []
    seen: set[str] = set()
    for capability in capabilities:
        if capability.stack in seen:
            continue
        seen.add(capability.stack)
        ordered_stacks.append(capability.stack)

    for stack in ordered_stacks:
        info(f"Reconciling {stack} via with-secrets-prod + scripts/provision.sh")
        subprocess.run(
            [
                str(WITH_SECRETS_PROD),
                str(PROVISION_SCRIPT),
                "--stack",
                stack,
            ],
            check=True,
            cwd=REPO_ROOT,
        )


def main() -> None:
    args = parse_args()
    if args.list:
        list_capabilities()
        return

    ensure_prerequisites()
    ensure_production_targeting()
    capabilities = dedupe_capabilities(args)

    info(f"Target secrets file: {PROD_SECRETS_FILE}")
    info("Selected capabilities:")
    for capability in capabilities:
        info(
            f"  - {capability.name}: update {capability.sops_key} "
            f"and reconcile {capability.stack}"
        )

    if not args.execute:
        info("Plan only. Re-run with --execute to apply changes.")
        return

    updated = decrypt_yaml(PROD_SECRETS_FILE)
    for capability in capabilities:
        updated[capability.sops_key] = generate_secret(capability.generator)

    encrypt_yaml(PROD_SECRETS_FILE, updated)
    info(f"Updated {len(capabilities)} credential value(s) in {PROD_SECRETS_FILE}")

    if args.skip_reconcile:
        info("Skipping stack reconcile because --skip-reconcile was requested.")
        return

    reconcile_stacks(capabilities)
    info("Rotation and reconcile completed.")


if __name__ == "__main__":
    main()
