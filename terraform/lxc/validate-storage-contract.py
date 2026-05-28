#!/usr/bin/env python3
"""Validate storage intent resolution against stack manifests and live Proxmox state."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import yaml


PROXMOX_API_JSON_PATH = "/api2/json"


@dataclass
class StackResolution:
    stack_name: str
    storage_profile: str
    rootfs_storage: str
    docker_storage: str
    docker_backend_type: str | None
    template_storage: str
    template_name: str
    extra_mount_profile: str | None
    extra_mount_storage: str | None
    extra_mount_backend_type: str | None
    required_content: dict[str, str]
    docker_mount: dict[str, Any] | None
    extra_mount: dict[str, Any] | None


@dataclass
class TemplateResolution:
    storage: str
    name: str


@dataclass
class LiveCheckConfig:
    host: str
    port: int
    base_path: str
    token_id: str
    token_secret: str
    insecure_tls: bool


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


def normalize_mount_block(stack_name: str, stack: dict[str, Any]) -> dict[str, Any] | None:
    mount = stack.get("docker_mount")
    if mount is None:
        return None
    if not isinstance(mount, dict):
        raise ValueError(f"stack '{stack_name}': docker_mount must decode to a mapping")

    normalized = dict(mount)
    normalized.setdefault("logical_name", "docker-data")
    normalized.setdefault("path", "/var/lib/docker")
    normalized.setdefault("size", stack.get("docker_storage_size"))
    normalized.setdefault("backup_policy", "include")
    normalized.setdefault("mutation_policy", "grow-only")
    normalized.setdefault("resize_control_plane", "provider")

    legacy_size = stack.get("docker_storage_size")
    if legacy_size and normalized.get("size") and str(legacy_size) != str(normalized["size"]):
        raise ValueError(
            f"stack '{stack_name}': docker_mount.size must match legacy docker_storage_size while both are present"
        )

    if not normalized.get("size"):
        raise ValueError(f"stack '{stack_name}': docker_mount.size is required when docker_mount is declared")
    if not str(normalized.get("path", "")).startswith("/"):
        raise ValueError(f"stack '{stack_name}': docker_mount.path must be an absolute path")

    return normalized


def normalize_extra_mount_block(stack_name: str, stack: dict[str, Any]) -> dict[str, Any] | None:
    # Prefer the canonical `extra_mount` block when present; fall back to
    # legacy `extra_mount_path`, `extra_mount_size`, and `extra_mount_profile`.
    declared = stack.get("extra_mount")
    legacy_path = stack.get("extra_mount_path")
    legacy_size = stack.get("extra_mount_size")
    legacy_profile = stack.get("extra_mount_profile")

    if declared is None and not legacy_path:
        return None

    if declared is None:
        declared = {}
    if not isinstance(declared, dict):
        raise ValueError(f"stack '{stack_name}': extra_mount must decode to a mapping")

    normalized = dict(declared)
    normalized.setdefault("logical_name", "extra-data")
    normalized.setdefault("path", legacy_path)
    normalized.setdefault("size", declared.get("size") or legacy_size)
    normalized.setdefault("profile", declared.get("profile") or legacy_profile)
    normalized.setdefault("backup_policy", "include")
    normalized.setdefault("mutation_policy", "grow-only")
    normalized.setdefault("resize_control_plane", "provider")

    # Fast-fail on obvious mismatches between canonical and legacy fields
    if legacy_path and normalized.get("path") and str(legacy_path) != str(normalized["path"]):
        raise ValueError(
            f"stack '{stack_name}': extra_mount.path must match legacy extra_mount_path while both are present"
        )
    if legacy_size and normalized.get("size") and str(legacy_size) != str(normalized["size"]):
        raise ValueError(
            f"stack '{stack_name}': extra_mount.size must match legacy extra_mount_size while both are present"
        )
    if legacy_profile and normalized.get("profile") and str(legacy_profile) != str(normalized["profile"]):
        raise ValueError(
            f"stack '{stack_name}': extra_mount.profile must match legacy extra_mount_profile while both are present"
        )

    if not normalized.get("size"):
        raise ValueError(f"stack '{stack_name}': extra_mount.size is required when extra_mount is declared")
    if not str(normalized.get("path", "")).startswith("/"):
        raise ValueError(f"stack '{stack_name}': extra_mount.path must be an absolute path")

    return normalized


def resolve_storage_profile(
    stack_name: str,
    stack: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[str, dict[str, Any], str, str, str | None]:
    defaults = manifest.get("defaults", {})
    profiles = manifest.get("profiles", {})
    legacy_rootfs_storage_profiles = manifest.get("legacy_rootfs_storage_profiles", {})

    legacy_rootfs = stack.get("rootfs_storage")
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

    docker_backend_type = ((manifest.get("storage_backends") or {}).get(docker_storage) or {}).get(
        "backend_type"
    )
    return str(storage_profile), profile, rootfs_storage, docker_storage, docker_backend_type


def resolve_extra_mount(
    stack_name: str,
    stack: dict[str, Any],
    manifest: dict[str, Any],
    storage_profile: str,
) -> tuple[str | None, str | None, dict[str, Any] | None, str | None]:
    normalized_extra = normalize_extra_mount_block(stack_name, stack)
    if normalized_extra is None:
        return None, None, None, None

    defaults = manifest.get("defaults", {})
    legacy_extra_mount_profiles = manifest.get("legacy_extra_mount_storage_profiles", {})
    extra_mount_profiles = manifest.get("extra_mount_profiles", {})
    legacy_extra_mount = stack.get("extra_mount_storage")

    extra_mount_profile = (
        normalized_extra.get("profile")
        or stack.get("extra_mount_profile")
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

    extra_mount_backend_type = ((manifest.get("storage_backends") or {}).get(extra_mount_storage) or {}).get(
        "backend_type"
    )

    return extra_mount_profile, extra_mount_storage, extra_profile, extra_mount_backend_type


def resolve_template(
    stack_name: str,
    stack: dict[str, Any],
    manifest: dict[str, Any],
) -> TemplateResolution:
    defaults = manifest.get("defaults", {})
    template_profiles = manifest.get("template_profiles", {})
    legacy_template_profiles = manifest.get("legacy_template_storage_profiles", {})
    legacy_template_storage, legacy_template_name = parse_legacy_ostemplate(stack.get("ostemplate"))

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

    return TemplateResolution(storage=template_storage, name=template_name)


def build_required_content(
    profile: dict[str, Any],
    rootfs_storage: str,
    docker_storage: str,
    template_storage: str,
    extra_mount_storage: str | None,
    extra_profile: dict[str, Any] | None,
    manifest: dict[str, Any],
    stack: dict[str, Any],
) -> dict[str, str]:
    template_profiles = manifest.get("template_profiles", {})
    defaults = manifest.get("defaults", {})
    legacy_template_profiles = manifest.get("legacy_template_storage_profiles", {})
    legacy_template_storage, _ = parse_legacy_ostemplate(stack.get("ostemplate"))
    template_profile = (
        stack.get("template_profile")
        or legacy_template_profiles.get(legacy_template_storage)
        or defaults.get("template_profile")
    )
    template_profile_data = template_profiles.get(template_profile or "") or {}

    required_content = {
        rootfs_storage: profile.get("rootfs_required_content_type", "rootdir"),
        docker_storage: profile.get("docker_required_content_type", "rootdir"),
        template_storage: template_profile_data.get("required_content_type", "vztmpl"),
    }
    if extra_mount_storage:
        required_content[extra_mount_storage] = (extra_profile or {}).get(
            "required_content_type", "rootdir"
        )
    return required_content


def resolve_stack(stack_name: str, stack: dict[str, Any], manifest: dict[str, Any]) -> StackResolution:
    storage_profile, profile, rootfs_storage, docker_storage, docker_backend_type = (
        resolve_storage_profile(stack_name, stack, manifest)
    )
    extra_mount_profile, extra_mount_storage, extra_profile, extra_mount_backend_type = resolve_extra_mount(
        stack_name,
        stack,
        manifest,
        storage_profile,
    )
    normalized_extra = normalize_extra_mount_block(stack_name, stack)
    template = resolve_template(stack_name, stack, manifest)
    required_content = build_required_content(
        profile,
        rootfs_storage,
        docker_storage,
        template.storage,
        extra_mount_storage,
        extra_profile,
        manifest,
        stack,
    )

    return StackResolution(
        stack_name=stack_name,
        storage_profile=str(storage_profile),
        rootfs_storage=rootfs_storage,
        docker_storage=docker_storage,
        docker_backend_type=str(docker_backend_type) if docker_backend_type is not None else None,
        template_storage=template.storage,
        template_name=template.name,
        extra_mount_profile=extra_mount_profile,
        extra_mount_storage=extra_mount_storage,
        extra_mount_backend_type=str(extra_mount_backend_type) if extra_mount_backend_type is not None else None,
        required_content=required_content,
        docker_mount=normalize_mount_block(stack_name, stack),
        extra_mount=normalized_extra,
    )


def validate_operational_resize_policy(resolution: StackResolution) -> list[str]:
    errors: list[str] = []
    mount = resolution.docker_mount

    if mount is not None:
        resize_control_plane = str(mount.get("resize_control_plane", "provider"))
        mutation_policy = str(mount.get("mutation_policy", "grow-only"))

        if resize_control_plane not in {"provider", "operational"}:
            errors.append(
                f"stack '{resolution.stack_name}': docker_mount.resize_control_plane must be 'provider' or 'operational'"
            )
        elif mutation_policy != "grow-only":
            errors.append(
                f"stack '{resolution.stack_name}': docker_mount.mutation_policy must remain 'grow-only' for the supported resize workflow"
            )
        elif resize_control_plane == "operational":
            if resolution.docker_backend_type not in {"zfs", "lvm-thin"}:
                errors.append(
                    f"stack '{resolution.stack_name}': operational docker_mount resize is only supported on zfs- or lvm-thin-backed docker storage (resolved backend '{resolution.docker_storage}', backend_type '{resolution.docker_backend_type}')"
                )
            if mount.get("path") != "/var/lib/docker":
                errors.append(
                    f"stack '{resolution.stack_name}': first-slice operational docker_mount resize only supports /var/lib/docker"
                )

    extra_mount = resolution.extra_mount
    if extra_mount is not None:
        resize_control_plane = str(extra_mount.get("resize_control_plane", "provider"))
        mutation_policy = str(extra_mount.get("mutation_policy", "grow-only"))

        if resize_control_plane not in {"provider", "operational"}:
            errors.append(
                f"stack '{resolution.stack_name}': extra_mount.resize_control_plane must be 'provider' or 'operational'"
            )
        elif mutation_policy != "grow-only":
            errors.append(
                f"stack '{resolution.stack_name}': extra_mount.mutation_policy must remain 'grow-only' for the supported resize workflow"
            )
        elif resize_control_plane == "operational" and resolution.extra_mount_backend_type != "zfs":
            errors.append(
                f"stack '{resolution.stack_name}': operational extra_mount resize is only supported on zfs-backed extra-mount storage (resolved backend '{resolution.extra_mount_storage}', backend_type '{resolution.extra_mount_backend_type}')"
            )

    return errors


def normalize_api_base(proxmox_api_url: str) -> str:
    base = proxmox_api_url.rstrip("/")
    if base.endswith(PROXMOX_API_JSON_PATH):
        return base
    return f"{base}{PROXMOX_API_JSON_PATH}"


def normalized_hostname(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "://" in candidate:
        parsed = parse.urlsplit(candidate)
        return parsed.hostname.lower() if parsed.hostname else None
    return candidate.split(":", 1)[0].lower()


def is_allowed_api_hostname(hostname: str, proxmox_node: str) -> bool:
    normalized = hostname.lower()
    node = proxmox_node.lower()
    if normalized == node or normalized.startswith(f"{node}."):
        return True

    allowed_hosts = {
        normalized_hostname(os.getenv("TF_VAR_proxmox_host")),
        normalized_hostname(os.getenv("PVE_TEST_FQDN")),
    }
    return normalized in {host for host in allowed_hosts if host}


def validate_api_base_url(proxmox_api_url: str, proxmox_node: str) -> tuple[str, int, str]:
    normalized = normalize_api_base(proxmox_api_url)
    parsed_url = parse.urlsplit(normalized)

    if parsed_url.scheme != "https":
        raise ValueError("Proxmox API URL must use https")
    if not parsed_url.hostname:
        raise ValueError("Proxmox API URL must include a hostname")
    if parsed_url.username or parsed_url.password:
        raise ValueError("Proxmox API URL must not embed credentials")
    if parsed_url.query or parsed_url.fragment:
        raise ValueError("Proxmox API URL must not include a query string or fragment")
    if parsed_url.path not in {"", "/", PROXMOX_API_JSON_PATH}:
        raise ValueError(f"Proxmox API URL path must be empty or {PROXMOX_API_JSON_PATH}")
    if not is_allowed_api_hostname(parsed_url.hostname, proxmox_node):
        raise ValueError(
            f"Proxmox API URL host '{parsed_url.hostname}' does not match expected node '{proxmox_node}'"
        )

    return parsed_url.hostname, parsed_url.port or 8006, PROXMOX_API_JSON_PATH


def build_ssl_context(insecure_tls: bool) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_default_certs()
    context.check_hostname = True
    if insecure_tls:
        context.check_hostname = False  # NOSONAR - pve-test uses self-signed internal TLS by design
        context.verify_mode = ssl.CERT_NONE  # NOSONAR - homelab validator supports explicit insecure mode
    return context


def proxmox_get_json(
    host: str,
    port: int,
    base_path: str,
    path: str,
    token_id: str,
    token_secret: str,
    insecure_tls: bool,
) -> Any:
    request_path = f"{base_path}{path}"
    context = build_ssl_context(insecure_tls)
    connection = http.client.HTTPSConnection(host, port, context=context)
    try:
        connection.request(
            "GET",
            request_path,
            headers={"Authorization": f"PVEAPIToken={token_id}={token_secret}"},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"Request failed for https://{host}:{port}{request_path}: {exc}") from exc
    finally:
        connection.close()

    if response.status >= 400:
        raise RuntimeError(
            f"HTTP {response.status} for https://{host}:{port}{request_path}: {body}"
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Unexpected API response from https://{host}:{port}{request_path}: invalid JSON"
        ) from exc

    if "data" not in payload:
        raise RuntimeError(
            f"Unexpected API response from https://{host}:{port}{request_path}: missing data field"
        )
    return payload["data"]


def list_storage_content_types(
    host: str,
    port: int,
    base_path: str,
    node: str,
    token_id: str,
    token_secret: str,
    insecure_tls: bool,
) -> dict[str, set[str]]:
    data = proxmox_get_json(
        host,
        port,
        base_path,
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
    host: str,
    port: int,
    base_path: str,
    node: str,
    storage: str,
    token_id: str,
    token_secret: str,
    insecure_tls: bool,
) -> set[str]:
    path = f"/nodes/{parse.quote(node)}/storage/{parse.quote(storage)}/content?content=vztmpl"
    data = proxmox_get_json(host, port, base_path, path, token_id, token_secret, insecure_tls)
    names: set[str] = set()
    for item in data:
        if item.get("content") != "vztmpl":
            continue
        volid = item.get("volid") or ""
        if "/" in volid:
            names.add(volid.rsplit("/", 1)[-1])
    return names


def parse_args() -> argparse.Namespace:
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
    return parser.parse_args()


def load_stack_resolutions(
    manifest: dict[str, Any],
    stacks_dir: Path,
) -> tuple[list[StackResolution], list[str]]:
    resolutions: list[StackResolution] = []
    errors: list[str] = []

    for stack_yaml in sorted(stacks_dir.glob("*/stack.yaml")):
        stack_name = stack_yaml.parent.name
        try:
            stack = load_yaml(stack_yaml)
            resolutions.append(resolve_stack(stack_name, stack, manifest))
        except Exception as exc:
            errors.append(str(exc))

    return resolutions, errors


def collect_requirements(
    resolutions: list[StackResolution],
) -> tuple[dict[str, set[str]], dict[str, set[str]], list[str]]:
    required_backends: dict[str, set[str]] = {}
    required_templates: dict[str, set[str]] = {}
    errors: list[str] = []

    for resolution in resolutions:
        for backend, content_type in resolution.required_content.items():
            required_backends.setdefault(backend, set()).add(content_type)
        required_templates.setdefault(resolution.template_storage, set()).add(
            resolution.template_name
        )
        errors.extend(validate_operational_resize_policy(resolution))

    return required_backends, required_templates, errors


def validate_live_credentials(args: argparse.Namespace) -> list[str]:
    if args.offline:
        return []
    if args.proxmox_api_url and args.token_id and args.token_secret:
        return []
    return [
        "Missing Proxmox API credentials. Run via ./with-secrets or provide --proxmox-api-url, --token-id, --token-secret."
    ]


def build_live_check_config(args: argparse.Namespace) -> LiveCheckConfig:
    host, port, base_path = validate_api_base_url(args.proxmox_api_url, args.proxmox_node)
    insecure_tls = False if args.verify_tls else args.insecure_tls
    return LiveCheckConfig(
        host=host,
        port=port,
        base_path=base_path,
        token_id=args.token_id,
        token_secret=args.token_secret,
        insecure_tls=insecure_tls,
    )


def validate_required_templates(
    args: argparse.Namespace,
    live: LiveCheckConfig,
    required_templates: dict[str, set[str]],
) -> list[str]:
    errors: list[str] = []

    for storage, template_names in sorted(required_templates.items()):
        try:
            live_templates = list_templates_for_storage(
                live.host,
                live.port,
                live.base_path,
                args.proxmox_node,
                storage,
                live.token_id,
                live.token_secret,
                live.insecure_tls,
            )
        except Exception as exc:
            errors.append(
                f"failed to list templates from storage '{storage}' on node '{args.proxmox_node}': {exc}"
            )
            continue

        for template_name in sorted(template_names):
            if template_name not in live_templates:
                errors.append(f"template '{template_name}' not found on storage '{storage}'")

    return errors


def validate_live_storage(
    args: argparse.Namespace,
    live: LiveCheckConfig,
    required_backends: dict[str, set[str]],
    required_templates: dict[str, set[str]],
) -> list[str]:
    errors: list[str] = []
    live_storage_types = list_storage_content_types(
        live.host,
        live.port,
        live.base_path,
        args.proxmox_node,
        live.token_id,
        live.token_secret,
        live.insecure_tls,
    )

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

    errors.extend(validate_required_templates(args, live, required_templates))

    return errors


def print_errors(errors: list[str]) -> None:
    for issue in errors:
        print(f"ERROR: {issue}")


def build_json_payload(
    args: argparse.Namespace,
    manifest_path: Path,
    resolutions: list[StackResolution],
    required_backends: dict[str, set[str]],
    required_templates: dict[str, set[str]],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "mode": "offline" if args.offline else "live",
        "node": args.proxmox_node,
        "manifest": str(manifest_path),
        "stacks_checked": len(resolutions),
        "operational_mounts": {
            resolution.stack_name: {
                "docker_mount": resolution.docker_mount,
                "extra_mount": resolution.extra_mount,
            }
            for resolution in resolutions
        },
        "required_backends": {k: sorted(v) for k, v in required_backends.items()},
        "required_templates": {k: sorted(v) for k, v in required_templates.items()},
        "errors": errors,
    }


def print_human_output(
    args: argparse.Namespace,
    manifest_path: Path,
    resolutions: list[StackResolution],
    errors: list[str],
) -> None:
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
        return

    if args.offline:
        print("Validation passed: stack intent resolves cleanly against storage manifest.")
    else:
        print("Validation passed: all required storage backends, content types, and templates are present.")


def main() -> int:
    args = parse_args()

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

    resolutions, errors = load_stack_resolutions(manifest, stacks_dir)
    errors.extend(validate_live_credentials(args))

    if errors:
        print_errors(errors)
        return 1

    required_backends, required_templates, policy_errors = collect_requirements(resolutions)
    errors.extend(policy_errors)

    if not args.offline:
        try:
            live = build_live_check_config(args)
            errors.extend(
                validate_live_storage(
                    args,
                    live,
                    required_backends,
                    required_templates,
                )
            )
        except Exception as exc:
            print(f"ERROR: failed to query Proxmox storage inventory: {exc}")
            return 1

    if args.json:
        payload = build_json_payload(
            args,
            manifest_path,
            resolutions,
            required_backends,
            required_templates,
            errors,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_human_output(args, manifest_path, resolutions, errors)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
