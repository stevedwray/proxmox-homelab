#!/usr/bin/env python3
"""Render deterministic Traefik dynamic config from validated EdgeManifest files."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from edge_manifest import (
    discover_edge_manifests,
    extract_legacy_routes,
    load_manifest,
    validate_manifests,
)


@dataclass(frozen=True)
class RenderIssue:
    """Machine-readable renderer issue."""

    code: str
    message: str
    manifest: str | None = None
    host: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class RenderWarning:
    """Machine-readable non-fatal renderer warning."""

    code: str
    message: str
    manifest: str | None = None
    host: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class RenderedStack:
    """Deterministic rendered dynamic config payload for one stack."""

    stack: str
    manifest: str
    config: dict[str, object]


@dataclass(frozen=True)
class RenderResult:
    """Result of rendering one or more manifests."""

    rendered: tuple[RenderedStack, ...]
    issues: tuple[RenderIssue, ...]
    warnings: tuple[RenderWarning, ...]
    legacy_route_count: int

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        status = "passed" if self.ok else "failed"
        return {
            "status": status,
            "stack_count": len(self.rendered),
            "legacy_route_count": self.legacy_route_count,
            "issue_count": len(self.issues),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "stacks": [
                {
                    "stack": rendered.stack,
                    "manifest": rendered.manifest,
                }
                for rendered in self.rendered
            ],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render per-stack Traefik dynamic config from EdgeManifest files "
            "with legacy collision checks."
        )
    )
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help=(
            "Optional explicit manifest files to render. "
            "If omitted, discover stacks/*/edge.yaml under --stacks-dir."
        ),
    )
    parser.add_argument(
        "--stacks-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "stacks",
        help="Stacks directory used for discovery mode.",
    )
    parser.add_argument(
        "--legacy-playbook",
        type=Path,
        default=Path(__file__).resolve().parent / "ansible" / "playbooks" / "deploy-proxy-stack.yml",
        help="Path to legacy central proxy playbook used for collision checks.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / ".generated" / "traefik",
        help="Dry-run output directory for per-stack Traefik files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser.parse_args()


def _resolve_manifest_paths(args: argparse.Namespace) -> list[Path]:
    if args.manifests:
        return sorted(path.resolve() for path in args.manifests)
    return discover_edge_manifests(args.stacks_dir.resolve())


def _read_intended_replacement_source(manifest_doc: dict[str, object]) -> object | None:
    raw_replacements = manifest_doc.get("intendedReplacement")
    if raw_replacements is not None:
        return raw_replacements

    spec = manifest_doc.get("spec")
    if isinstance(spec, dict):
        return spec.get("intendedReplacement")
    return None


def _replacement_to_host(replacement: object) -> str | None:
    if isinstance(replacement, str) and replacement.strip():
        return replacement.strip()

    if not isinstance(replacement, dict):
        return None

    hostname = replacement.get("hostname")
    if isinstance(hostname, str) and hostname.strip():
        return hostname.strip()

    host = replacement.get("host")
    if isinstance(host, str) and host.strip():
        return host.strip()

    return None


def _extract_intended_replacements(
    manifest_doc: dict[str, object],
    manifest_path: Path,
    issues: list[RenderIssue],
) -> list[str]:
    raw_replacements = _read_intended_replacement_source(manifest_doc)
    if raw_replacements is None:
        return []

    manifest = str(manifest_path)
    if not isinstance(raw_replacements, list):
        issues.append(
            RenderIssue(
                code="RTR203",
                message="intendedReplacement must be a list when provided",
                manifest=manifest,
            )
        )
        return []

    hosts: list[str] = []
    for replacement in raw_replacements:
        host = _replacement_to_host(replacement)
        if host is not None:
            hosts.append(host)
            continue

        issues.append(
            RenderIssue(
                code="RTR204",
                message=(
                    "intendedReplacement entries must be host strings or objects "
                    "with hostname"
                ),
                manifest=manifest,
            )
        )
        return []

    if len(hosts) > 1:
        issues.append(
            RenderIssue(
                code="RTR201",
                message=(
                    f"Manifest contains {len(hosts)} intendedReplacement entries. "
                    "Only one migration per task is allowed."
                ),
                manifest=manifest,
            )
        )
    return hosts


def _build_route_dynamic_config(route: dict[str, object]) -> tuple[str, dict[str, object], dict[str, object] | None]:
    route_name = str(route["name"])
    host = str(route["host"])
    backend = route["backend"]
    auth_mode = route["auth"]["mode"]
    resolver = route["tls"]["resolver"]

    router: dict[str, object] = {
        "rule": f"Host(`{host}`)",
        "entryPoints": ["websecure"],
        "tls": {"certResolver": resolver},
    }

    if auth_mode == "forwardAuth":
        router["middlewares"] = ["authentik"]

    service: dict[str, object] | None = None
    if backend["type"] == "url":
        service_name = f"{route_name}-backend"
        router["service"] = service_name
        service = {
            "loadBalancer": {
                "servers": [{"url": backend["url"]}],
            }
        }
    else:
        router["service"] = backend["service"]

    return route_name, router, service


def _render_manifest(
    manifest_path: Path,
    manifest_doc: dict[str, object],
    legacy_hosts: set[str],
    issues: list[RenderIssue],
    warnings: list[RenderWarning],
) -> RenderedStack | None:
    manifest = str(manifest_path)
    metadata = manifest_doc["metadata"]
    stack = str(metadata["stack"])
    routes = manifest_doc["spec"]["routes"]

    generated_hosts = {str(route["host"]) for route in routes}
    intended_hosts = _extract_intended_replacements(manifest_doc, manifest_path, issues)
    if len(intended_hosts) > 1:
        return None

    intended_host = intended_hosts[0] if intended_hosts else None
    if intended_host and intended_host not in generated_hosts:
        issues.append(
            RenderIssue(
                code="RTR202",
                message=(
                    "intendedReplacement hostname does not match any generated route "
                    "hostname"
                ),
                manifest=manifest,
                host=intended_host,
            )
        )
        return None

    if intended_host and intended_host not in legacy_hosts:
        warnings.append(
            RenderWarning(
                code="RTR301",
                message=(
                    "intendedReplacement hostname is not present in legacy central "
                    "routes"
                ),
                manifest=manifest,
                host=intended_host,
            )
        )

    collisions = sorted(host for host in generated_hosts if host in legacy_hosts)
    unapproved_collisions = [host for host in collisions if host != intended_host]
    if unapproved_collisions:
        for host in unapproved_collisions:
            issues.append(
                RenderIssue(
                    code="RTR200",
                    message=(
                        f"Generated route {host} collides with legacy central route "
                        "without intendedReplacement flag"
                    ),
                    manifest=manifest,
                    host=host,
                )
            )
        return None

    routers: dict[str, object] = {}
    services: dict[str, object] = {}
    for route in sorted(routes, key=lambda item: str(item["name"])):
        route_name, router, service = _build_route_dynamic_config(route)
        routers[route_name] = router
        if service is not None:
            services[str(router["service"])] = service

    rendered_http: dict[str, object] = {"routers": routers}
    if services:
        rendered_http["services"] = services

    return RenderedStack(
        stack=stack,
        manifest=manifest,
        config={"http": rendered_http},
    )


def render_traefik_dry_run(manifest_paths: list[Path], legacy_playbook: Path) -> RenderResult:
    """Render per-stack dynamic Traefik config with collision checks."""

    validation = validate_manifests(manifest_paths)
    if not validation.ok:
        issues = tuple(
            RenderIssue(
                code=issue.code,
                message=issue.message,
                manifest=issue.manifest,
                host=issue.route,
            )
            for issue in validation.issues
        )
        return RenderResult(
            rendered=(),
            issues=issues,
            warnings=(),
            legacy_route_count=0,
        )

    legacy_result = extract_legacy_routes(legacy_playbook)
    if not legacy_result.ok:
        issues = tuple(
            RenderIssue(
                code=issue.code,
                message=issue.message,
                manifest=issue.source,
                host=issue.router,
            )
            for issue in legacy_result.issues
        )
        return RenderResult(
            rendered=(),
            issues=issues,
            warnings=(),
            legacy_route_count=0,
        )

    legacy_hosts = {route.host for route in legacy_result.routes}
    issues: list[RenderIssue] = []
    warnings: list[RenderWarning] = []
    rendered: list[RenderedStack] = []

    for manifest_path in sorted(manifest_paths):
        document = load_manifest(manifest_path)
        if not isinstance(document, dict):
            issues.append(
                RenderIssue(
                    code="RTR205",
                    message="manifest top-level must be a mapping",
                    manifest=str(manifest_path),
                )
            )
            continue

        stack_render = _render_manifest(
            manifest_path=manifest_path,
            manifest_doc=document,
            legacy_hosts=legacy_hosts,
            issues=issues,
            warnings=warnings,
        )
        if stack_render is not None:
            rendered.append(stack_render)

    issues.sort(key=lambda issue: (issue.code, issue.manifest or "", issue.host or "", issue.message))
    warnings.sort(
        key=lambda warning: (
            warning.code,
            warning.manifest or "",
            warning.host or "",
            warning.message,
        )
    )
    rendered.sort(key=lambda item: item.stack)
    return RenderResult(
        rendered=tuple(rendered),
        issues=tuple(issues),
        warnings=tuple(warnings),
        legacy_route_count=len(legacy_result.routes),
    )


def write_rendered_files(rendered: tuple[RenderedStack, ...], output_dir: Path) -> list[Path]:
    """Write per-stack rendered config files to the output directory."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for item in rendered:
        output_path = output_dir / f"{item.stack}.yml"
        output_path.write_text(
            yaml.safe_dump(item.config, sort_keys=False),
            encoding="utf-8",
        )
        written_paths.append(output_path)
    return written_paths


def _json_payload(result: RenderResult, output_dir: Path) -> dict[str, object]:
    payload = result.to_dict()
    if not result.ok:
        return payload

    resolved_output = output_dir.resolve()
    payload["output_dir"] = str(resolved_output)
    payload["files"] = [str(resolved_output / f"{item.stack}.yml") for item in result.rendered]
    return payload


def _print_failure(result: RenderResult) -> None:
    print("Traefik render dry-run failed.")
    print(f"Issue count: {len(result.issues)}")
    for issue in result.issues:
        scope = issue.manifest or "<unknown>"
        if issue.host:
            print(f"- [{issue.code}] {scope} ({issue.host}): {issue.message}")
        else:
            print(f"- [{issue.code}] {scope}: {issue.message}")


def _print_success(result: RenderResult, output_dir: Path, written: list[Path]) -> None:
    print(
        "Traefik render dry-run passed. "
        f"Rendered {len(result.rendered)} stack file(s) into {output_dir.resolve()}."
    )
    if result.warnings:
        print(f"Warning count: {len(result.warnings)}")
        for warning in result.warnings:
            scope = warning.manifest or "<unknown>"
            if warning.host:
                print(f"- [{warning.code}] {scope} ({warning.host}): {warning.message}")
            else:
                print(f"- [{warning.code}] {scope}: {warning.message}")
    for path in written:
        print(f"- wrote: {path}")


def main() -> int:
    args = parse_args()
    manifest_paths = _resolve_manifest_paths(args)
    output_dir = args.output_dir.resolve()
    result = render_traefik_dry_run(manifest_paths, args.legacy_playbook.resolve())

    if args.json:
        print(json.dumps(_json_payload(result, output_dir), indent=2, sort_keys=True))
        if result.ok:
            write_rendered_files(result.rendered, output_dir)
        return 0 if result.ok else 1

    if not result.ok:
        _print_failure(result)
        return 1

    written = write_rendered_files(result.rendered, output_dir)
    _print_success(result, output_dir, written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
