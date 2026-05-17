#!/usr/bin/env python3
"""Validate storage intent resolution against stack manifests and live Proxmox state."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import yaml


@dataclass
class StackResolution:
    stack_name: str
    rootfs_storage: str
    docker_storage: str
    template_storage: str
    template_name: str
    extra_mount_profile: str | None
    extra_mount_storage: str | None
    required_content: dict[str, str]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML at {path} must decode to a mapping")
    return data


def parse_legacy_ostemplate(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parts = value.split(":", 1)
    if len(parts) != 2 or not parts[1].startswith("vztmpl/"):
        return None, None
    return parts[0], parts[1].removeprefix("vztmpl/")


def resolve_stack(stack_name: str, stack: dict[str, Any], manifest: dict[str, Any]) -> StackResolution:
    defaults = manifest.get("defaults", {})

    legacy_rootfs_storage_profiles = manifest.get("legacy_rootfs_storage_profiles", {})
    legacy_extra_mount_profiles = manifest.get("legacy_extra_mount_storage_profiles", {})
    legacy_template_profiles = manifest.get("legacy_template_storage_profiles", {})

    profiles = manifest.get("profiles", {})
    extra_mount_profiles = manifest.get("extra_mount_profiles", {})
    template_profiles = manifest.get("template_profiles", {})

    legacy_rootfs = stack.get("rootfs_storage")
    legacy_extra_mount = stack.get("extra_mount_storage")
    legacy_template_storage, legacy_template_name = parse_legacy_ostemplate(stack.get("ostemplate"))

    storage_profile = (
        stack.get("storage_profile")
        or legacy_rootfs_storage_profiles.get(legacy_rootfs)
        or defaults.get("storage_profile")
    )
    profile = profiles.get(storage_profile or "")
    if not isinstance(profile, dict):
        raise ValueError(
            f"stack '{stack_name}': could not resolve storage_profile (got {storage_profile!r})"
        )

    rootfs_storage = profile.get("rootfs_storage")
    docker_storage = profile.get("docker_storage") or rootfs_storage
    if not rootfs_storage or not docker_storage:
        raise ValueError(
            f"stack '{stack_name}': profile '{storage_profile}' missing rootfs/docker storage"
        )

    extra_mount_storage = None
    extra_mount_profile = None
    extra_profile: dict[str, Any] | None = None
    if stack.get("extra_mount_path"):
        extra_mount_profile = (
            stack.get("extra_mount_profile")
            or legacy_extra_mount_profiles.get(legacy_extra_mount)
            or defaults.get("extra_mount_profile")
            or storage_profile
        )
        extra_profile = extra_mount_profiles.get(extra_mount_profile or "")
        if not isinstance(extra_profile, dict):
            raise ValueError(
                f"stack '{stack_name}': could not resolve extra_mount_profile (got {extra_mount_profile!r})"
            )
        extra_mount_storage = extra_profile.get("storage")
        if not extra_mount_storage:
            raise ValueError(
                f"stack '{stack_name}': extra_mount_profile '{extra_mount_profile}' has no storage"
            )

    template_profile = (
        stack.get("template_profile")
        or legacy_template_profiles.get(legacy_template_storage)
        or defaults.get("template_profile")
    )
    template_profile_data = template_profiles.get(template_profile or "")
    if not isinstance(template_profile_data, dict):
        raise ValueError(
            f"stack '{stack_name}': could not resolve template_profile (got {template_profile!r})"
        )

    template_storage = template_profile_data.get("storage")
    template_name = (
        stack.get("template_name")
        or legacy_template_name
        or ((manifest.get("templates") or {}).get("default") or {}).get("name")
    )
    if not template_storage or not template_name:
        raise ValueError(f"stack '{stack_name}': template resolution incomplete")

    allowed_templates = template_profile_data.get("allowed_templates") or []
    if allowed_templates and template_name not in allowed_templates:
        raise ValueError(
            f"stack '{stack_name}': template '{template_name}' not allowed for template_profile '{template_profile}'"
        )

    required_content = {
        rootfs_storage: profile.get("rootfs_required_content_type", "rootdir"),
        docker_storage: profile.get("docker_required_content_type", "rootdir"),
        template_storage: template_profile_data.get("required_content_type", "vztmpl"),
    }
    if extra_mount_storage:
        required_content[extra_mount_storage] = (extra_profile or {}).get(
            "required_content_type", "rootdir"
        )

    return StackResolution(
        stack_name=stack_name,
        rootfs_storage=rootfs_storage,
        docker_storage=docker_storage,
        template_storage=template_storage,
        template_name=template_name,
        extra_mount_profile=extra_mount_profile,
        extra_mount_storage=extra_mount_storage,
        required_content=required_content,
    )


def normalize_api_base(proxmox_api_url: str) -> str:
    base = proxmox_api_url.rstrip("/")
    if base.endswith("/api2/json"):
        return base
    return f"{base}/api2/json"


def proxmox_get_json(
    base_url: str,
    path: str,
    token_id: str,
    token_secret: str,
    insecure_tls: bool,
) -> Any:
    url = f"{base_url}{path}"
    req = request.Request(url)
    req.add_header("Authorization", f"PVEAPIToken={token_id}={token_secret}")
    context = ssl._create_unverified_context() if insecure_tls else None
    try:
        with request.urlopen(req, timeout=20, context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc

    if "data" not in payload:
        raise RuntimeError(f"Unexpected API response from {url}: missing data field")
    return payload["data"]


def list_storage_content_types(
    base_url: str,
    node: str,
    token_id: str,
    token_secret: str,
    insecure_tls: bool,
) -> dict[str, set[str]]:
    data = proxmox_get_json(
        base_url,
        f"/nodes/{parse.quote(node)}/storage",
        token_id,
        token_secret,
        insecure_tls,
    )
    result: dict[str, set[str]] = {}
    for item in data:
        storage = item.get("storage")
        if not storage:
            continue
        content_raw = item.get("content") or ""
        content = {part.strip() for part in str(content_raw).split(",") if part.strip()}
        result[storage] = content
    return result


def list_templates_for_storage(
    base_url: str,
    node: str,
    storage: str,
    token_id: str,
    token_secret: str,
    insecure_tls: bool,
) -> set[str]:
    path = f"/nodes/{parse.quote(node)}/storage/{parse.quote(storage)}/content?content=vztmpl"
    data = proxmox_get_json(base_url, path, token_id, token_secret, insecure_tls)
    names: set[str] = set()
    for item in data:
        if item.get("content") != "vztmpl":
            continue
        volid = item.get("volid") or ""
        if "/" in volid:
            names.add(volid.rsplit("/", 1)[-1])
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to environment storage manifest")
    parser.add_argument("--stacks-dir", required=True, help="Path to terraform/lxc/stacks directory")
    parser.add_argument("--proxmox-node", required=True, help="Proxmox node to query")
    parser.add_argument("--proxmox-api-url", default=os.getenv("TF_VAR_proxmox_api_url", ""))
    parser.add_argument("--token-id", default=os.getenv("TF_VAR_pm_api_token_id", ""))
    parser.add_argument("--token-secret", default=os.getenv("TF_VAR_pm_api_token_secret", ""))
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Validate manifest + stack resolution only; skip live Proxmox API checks.",
    )
    parser.add_argument(
        "--insecure-tls",
        action="store_true",
        default=True,
        help="Skip TLS certificate validation (default true for homelab/self-signed endpoints)",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        default=False,
        help="Enable TLS certificate validation",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    stacks_dir = Path(args.stacks_dir)

    try:
        manifest = load_yaml(manifest_path)
    except Exception as exc:
        print(f"ERROR: failed to load manifest {manifest_path}: {exc}")
        return 1

    if not stacks_dir.exists():
        print(f"ERROR: stacks directory does not exist: {stacks_dir}")
        return 1

    resolutions: list[StackResolution] = []
    errors: list[str] = []

    for stack_yaml in sorted(stacks_dir.glob("*/stack.yaml")):
        stack_name = stack_yaml.parent.name
        try:
            stack = load_yaml(stack_yaml)
            resolutions.append(resolve_stack(stack_name, stack, manifest))
        except Exception as exc:
            errors.append(str(exc))

    if not args.offline and (
        not args.proxmox_api_url or not args.token_id or not args.token_secret
    ):
        errors.append(
            "Missing Proxmox API credentials. Run via ./with-secrets or provide --proxmox-api-url, --token-id, --token-secret."
        )

    if errors:
        for issue in errors:
            print(f"ERROR: {issue}")
        return 1

    required_backends: dict[str, set[str]] = {}
    required_templates: dict[str, set[str]] = {}

    for resolution in resolutions:
        for backend, content_type in resolution.required_content.items():
            required_backends.setdefault(backend, set()).add(content_type)
        required_templates.setdefault(resolution.template_storage, set()).add(
            resolution.template_name
        )

    if not args.offline:
        base_url = normalize_api_base(args.proxmox_api_url)
        insecure_tls = False if args.verify_tls else args.insecure_tls

        try:
            live_storage_types = list_storage_content_types(
                base_url,
                args.proxmox_node,
                args.token_id,
                args.token_secret,
                insecure_tls,
            )
        except Exception as exc:
            print(f"ERROR: failed to query Proxmox storage inventory: {exc}")
            return 1

        for backend, required_types in sorted(required_backends.items()):
            if backend not in live_storage_types:
                errors.append(f"storage backend '{backend}' is not present on node '{args.proxmox_node}'")
                continue
            live_types = live_storage_types[backend]
            for required_type in sorted(required_types):
                if required_type not in live_types:
                    errors.append(
                        f"storage backend '{backend}' does not support required content '{required_type}' (live: {sorted(live_types)})"
                    )

        for storage, template_names in sorted(required_templates.items()):
            try:
                live_templates = list_templates_for_storage(
                    base_url,
                    args.proxmox_node,
                    storage,
                    args.token_id,
                    args.token_secret,
                    insecure_tls,
                )
            except Exception as exc:
                errors.append(
                    f"failed to list templates from storage '{storage}' on node '{args.proxmox_node}': {exc}"
                )
                continue

            for template_name in sorted(template_names):
                if template_name not in live_templates:
                    errors.append(
                        f"template '{template_name}' not found on storage '{storage}'"
                    )

    if args.json:
        payload = {
            "mode": "offline" if args.offline else "live",
            "node": args.proxmox_node,
            "manifest": str(manifest_path),
            "stacks_checked": len(resolutions),
            "required_backends": {k: sorted(v) for k, v in required_backends.items()},
            "required_templates": {k: sorted(v) for k, v in required_templates.items()},
            "errors": errors,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"Validated storage contract inputs for {len(resolutions)} stacks using manifest {manifest_path}."
        )
        if args.offline:
            print("Mode: offline (manifest + stack resolution only)")
        else:
            print(f"Checked Proxmox node: {args.proxmox_node}")
        if errors:
            print("Validation failed:")
            for issue in errors:
                print(f"- {issue}")
        else:
            if args.offline:
                print("Validation passed: stack intent resolves cleanly against storage manifest.")
            else:
                print("Validation passed: all required storage backends, content types, and templates are present.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
