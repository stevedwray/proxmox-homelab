"""Side-effect-free EdgeManifest v1alpha1 discovery and validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse
import re

import yaml


API_VERSION = "homelab.gibbsgreatly.xyz/v1alpha1"
KIND = "EdgeManifest"
LAB_DOMAIN_SUFFIX = ".lab.gibbsgreatly.xyz"
EXPECTED_DNS_TARGET = "10.57.2.10"
ALLOWED_AUTH_MODES = ("none", "forwardAuth", "native", "oidc")
ALLOWED_BACKEND_TYPES = ("url", "traefikService")
TTL_PATTERN = re.compile(r"^[1-9]\d*[smhd]$")
TRAEFIK_SERVICE_REF_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9_.-]*$"
)
LEGACY_HOST_RULE_PATTERN = re.compile(r"Host\(`([^`]+)`\)")
JINJA_DEFAULT_HOST_PATTERN = re.compile(
    r"^\{\{\s*[^}]*\|\s*default\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}$"
)


@dataclass(frozen=True)
class ValidationIssue:
    """Machine-readable validation issue."""

    code: str
    message: str
    manifest: str | None = None
    route: str | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class RouteRecord:
    """Extracted route metadata used for cross-manifest checks."""

    manifest_path: str
    manifest_name: str
    stack: str
    route_name: str
    host: str


@dataclass(frozen=True)
class ValidationResult:
    """Full validation result across one or more manifest files."""

    manifests: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        status = "passed" if self.ok else "failed"
        return {
            "status": status,
            "manifest_count": len(self.manifests),
            "manifests": list(self.manifests),
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class LegacyRouteIssue:
    """Machine-readable extraction issue for legacy route inventory."""

    code: str
    message: str
    source: str | None = None
    line: int | None = None
    router: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class LegacyRouteRecord:
    """Extracted legacy central Traefik host rule metadata."""

    host: str
    router: str
    source: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyRouteInventoryResult:
    """Read-only legacy route inventory extraction result."""

    routes: tuple[LegacyRouteRecord, ...]
    issues: tuple[LegacyRouteIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        status = "passed" if self.ok else "failed"
        return {
            "status": status,
            "route_count": len(self.routes),
            "routes": [route.to_dict() for route in self.routes],
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def extract_legacy_routes(playbook_path: Path) -> LegacyRouteInventoryResult:
    """Extract central legacy Host(...) router rules from a Traefik playbook."""

    try:
        content = playbook_path.read_text(encoding="utf-8")
    except OSError as exc:
        return LegacyRouteInventoryResult(
            routes=(),
            issues=(
                LegacyRouteIssue(
                    code="LRI100",
                    message=f"failed to read legacy playbook: {exc}",
                    source=str(playbook_path),
                ),
            ),
        )

    routes, issues = _extract_legacy_routes_from_text(content, str(playbook_path))
    routes.sort(key=lambda route: (route.router, route.host, route.line))
    issues.sort(key=lambda issue: (issue.code, issue.source or "", issue.line or 0, issue.router or ""))
    return LegacyRouteInventoryResult(routes=tuple(routes), issues=tuple(issues))


def _extract_legacy_routes_from_text(
    content: str,
    source: str,
) -> tuple[list[LegacyRouteRecord], list[LegacyRouteIssue]]:
    routes: list[LegacyRouteRecord] = []
    issues: list[LegacyRouteIssue] = []

    in_routers = False
    routers_indent = -1
    current_router: str | None = None

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if stripped == "routers:":
            in_routers = True
            routers_indent = indent
            current_router = None
            continue

        if _is_router_block_exit(in_routers, stripped, indent, routers_indent):
            in_routers = False
            current_router = None

        if not in_routers:
            continue

        router_name = _match_router_name(stripped, indent, routers_indent)
        if router_name is not None:
            current_router = router_name
            continue

        route, issue = _extract_route_from_rule(
            current_router=current_router,
            stripped=stripped,
            source=source,
            line_number=line_number,
        )
        if route is None and issue is None:
            continue

        if issue is not None:
            issues.append(issue)
            continue

        routes.append(route)

    return routes, issues


def _is_router_block_exit(
    in_routers: bool,
    stripped: str,
    indent: int,
    routers_indent: int,
) -> bool:
    return in_routers and bool(stripped) and indent <= routers_indent


def _match_router_name(stripped: str, indent: int, routers_indent: int) -> str | None:
    router_match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):\s*$", stripped)
    if router_match is None or indent != routers_indent + 2:
        return None
    return router_match.group(1)


def _extract_route_from_rule(
    current_router: str | None,
    stripped: str,
    source: str,
    line_number: int,
) -> tuple[LegacyRouteRecord | None, LegacyRouteIssue | None]:
    if current_router is None or not stripped.startswith("rule:"):
        return None, None

    host_match = LEGACY_HOST_RULE_PATTERN.search(stripped)
    if host_match is None:
        return None, LegacyRouteIssue(
            code="LRI101",
            message="router rule must include Host(`...`)",
            source=source,
            line=line_number,
            router=current_router,
        )

    raw_host = host_match.group(1).strip()
    host = _resolve_legacy_host(raw_host)
    if host is None:
        return None, LegacyRouteIssue(
            code="LRI102",
            message=(
                "router Host(...) value must be a literal host or a "
                "Jinja default('host') expression"
            ),
            source=source,
            line=line_number,
            router=current_router,
        )

    return (
        LegacyRouteRecord(
            host=host,
            router=current_router,
            source=source,
            line=line_number,
        ),
        None,
    )


def _resolve_legacy_host(raw_host: str) -> str | None:
    if "{{" not in raw_host:
        return raw_host

    default_match = JINJA_DEFAULT_HOST_PATTERN.match(raw_host)
    if default_match is None:
        return None

    return default_match.group(1)


def discover_edge_manifests(stacks_dir: Path) -> list[Path]:
    """Find stack-owned edge manifests at stacks/*/edge.yaml."""

    return sorted(path for path in stacks_dir.glob("*/edge.yaml") if ".hold" not in path.parts)


def load_manifest(path: Path) -> dict[str, object]:
    """Load a YAML manifest document from disk."""

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def validate_manifests(manifest_paths: list[Path]) -> ValidationResult:
    """Validate one or more EdgeManifest documents."""

    issues: list[ValidationIssue] = []
    route_records: list[RouteRecord] = []
    manifests = tuple(str(path) for path in sorted(manifest_paths))

    for path in sorted(manifest_paths):
        document, load_issues = _load_manifest_document(path)
        issues.extend(load_issues)
        if document is None:
            continue
        route_records.extend(_validate_manifest_document(document, path, issues))

    _validate_cross_manifest(route_records, issues)
    issues.sort(key=lambda issue: (issue.code, issue.manifest or "", issue.route or "", issue.message))
    return ValidationResult(manifests=manifests, issues=tuple(issues))


def _load_manifest_document(path: Path) -> tuple[dict[str, object] | None, list[ValidationIssue]]:
    try:
        document = load_manifest(path)
    except yaml.YAMLError as exc:
        return None, [
            ValidationIssue(
                code="EMV100",
                message=f"manifest is not valid YAML: {exc}",
                manifest=str(path),
            )
        ]

    if not isinstance(document, dict):
        return None, [
            ValidationIssue(
                code="EMV101",
                message="manifest top-level must be a mapping",
                manifest=str(path),
            )
        ]
    return document, []


def _validate_manifest_document(
    document: dict[str, object],
    path: Path,
    issues: list[ValidationIssue],
) -> list[RouteRecord]:
    manifest = str(path)
    records: list[RouteRecord] = []

    _validate_document_header(document, manifest, issues)

    manifest_name, stack = _validate_metadata(document, manifest, issues)
    routes = _validate_spec_routes(document, manifest, issues)
    if routes is None:
        return records

    route_names_seen: set[str] = set()
    for route_index, route in enumerate(routes):
        route_record = _validate_route(
            route=route,
            route_index=route_index,
            route_names_seen=route_names_seen,
            manifest=manifest,
            manifest_name=manifest_name,
            stack=stack,
            issues=issues,
        )
        if route_record is not None:
            records.append(route_record)

    return records


def _validate_document_header(
    document: dict[str, object],
    manifest: str,
    issues: list[ValidationIssue],
) -> None:
    if document.get("apiVersion") != API_VERSION:
        issues.append(
            ValidationIssue(
                code="EMV102",
                message=f"apiVersion must be {API_VERSION}",
                manifest=manifest,
                field="apiVersion",
            )
        )

    if document.get("kind") != KIND:
        issues.append(
            ValidationIssue(
                code="EMV103",
                message=f"kind must be {KIND}",
                manifest=manifest,
                field="kind",
            )
        )


def _validate_metadata(
    document: dict[str, object],
    manifest: str,
    issues: list[ValidationIssue],
) -> tuple[str, str]:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        issues.append(
            ValidationIssue(
                code="EMV104",
                message="metadata must be a mapping",
                manifest=manifest,
                field="metadata",
            )
        )
        return "", ""

    manifest_name = metadata.get("name")
    stack = metadata.get("stack")
    if not isinstance(manifest_name, str) or not manifest_name.strip():
        issues.append(
            ValidationIssue(
                code="EMV105",
                message="metadata.name is required and must be a non-empty string",
                manifest=manifest,
                field="metadata.name",
            )
        )
        manifest_name = ""

    if not isinstance(stack, str) or not stack.strip():
        issues.append(
            ValidationIssue(
                code="EMV106",
                message="metadata.stack is required and must be a non-empty string",
                manifest=manifest,
                field="metadata.stack",
            )
        )
        stack = ""

    return manifest_name, stack


def _validate_spec_routes(
    document: dict[str, object],
    manifest: str,
    issues: list[ValidationIssue],
) -> list[object] | None:
    spec = document.get("spec")
    if not isinstance(spec, dict):
        issues.append(
            ValidationIssue(
                code="EMV107",
                message="spec must be a mapping",
                manifest=manifest,
                field="spec",
            )
        )
        return None

    routes = spec.get("routes")
    if not isinstance(routes, list):
        issues.append(
            ValidationIssue(
                code="EMV108",
                message="spec.routes is required and must be a list",
                manifest=manifest,
                field="spec.routes",
            )
        )
        return None

    return routes


def _validate_route(
    route: object,
    route_index: int,
    route_names_seen: set[str],
    manifest: str,
    manifest_name: str,
    stack: str,
    issues: list[ValidationIssue],
) -> RouteRecord | None:
    route_key = f"spec.routes[{route_index}]"
    if not isinstance(route, dict):
        issues.append(
            ValidationIssue(
                code="EMV109",
                message=f"{route_key} must be a mapping",
                manifest=manifest,
                field=route_key,
            )
        )
        return None

    route_name = route.get("name")
    host = route.get("host")
    if not isinstance(route_name, str) or not route_name.strip():
        issues.append(
            ValidationIssue(
                code="EMV110",
                message=f"{route_key}.name is required and must be a non-empty string",
                manifest=manifest,
                field=f"{route_key}.name",
            )
        )
        route_name = f"<index:{route_index}>"

    if route_name in route_names_seen:
        issues.append(
            ValidationIssue(
                code="EMV010",
                message=(
                    f"route name {route_name} is duplicated within manifest {manifest_name}"
                ),
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.name",
            )
        )
    route_names_seen.add(route_name)

    if not isinstance(host, str) or not host.strip():
        issues.append(
            ValidationIssue(
                code="EMV111",
                message=f"{route_key}.host is required and must be a non-empty string",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.host",
            )
        )
        host = ""

    if host and not host.endswith(LAB_DOMAIN_SUFFIX):
        issues.append(
            ValidationIssue(
                code="EMV002",
                message=f"host {host} must end with {LAB_DOMAIN_SUFFIX}",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.host",
            )
        )

    _validate_backend(route, route_key, route_name, manifest, issues)
    _validate_dns(route, route_key, route_name, manifest, issues)
    _validate_tls(route, route_key, route_name, manifest, issues)
    _validate_auth(route, route_key, route_name, manifest, stack, issues)

    return RouteRecord(
        manifest_path=manifest,
        manifest_name=manifest_name,
        stack=stack,
        route_name=route_name,
        host=host,
    )


def _validate_backend(
    route: dict[str, object],
    route_key: str,
    route_name: str,
    manifest: str,
    issues: list[ValidationIssue],
) -> None:
    backend = route.get("backend")
    if not isinstance(backend, dict):
        issues.append(
            ValidationIssue(
                code="EMV003",
                message=f"route {route_name} is missing required backend object",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.backend",
            )
        )
        return

    backend_type = backend.get("type")
    if backend_type not in ALLOWED_BACKEND_TYPES:
        issues.append(
            ValidationIssue(
                code="EMV112",
                message=(
                    "backend.type is invalid; "
                    "allowed: url, traefikService"
                ),
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.backend.type",
            )
        )
        return

    if backend_type == "url":
        backend_url = backend.get("url")
        if not isinstance(backend_url, str) or not backend_url.strip():
            issues.append(
                ValidationIssue(
                    code="EMV113",
                    message="backend.type url requires backend.url",
                    manifest=manifest,
                    route=route_name,
                    field=f"{route_key}.backend.url",
                )
            )
            return

        parsed_url = urlparse(backend_url)
        if parsed_url.scheme not in {"http", "https"}:
            issues.append(
                ValidationIssue(
                    code="EMV007",
                    message=f"backend.url {backend_url} must use http or https",
                    manifest=manifest,
                    route=route_name,
                    field=f"{route_key}.backend.url",
                )
            )

    if backend_type == "traefikService":
        service_ref = backend.get("service")
        if not isinstance(service_ref, str) or not service_ref.strip():
            issues.append(
                ValidationIssue(
                    code="EMV114",
                    message="backend.type traefikService requires backend.service",
                    manifest=manifest,
                    route=route_name,
                    field=f"{route_key}.backend.service",
                )
            )
            return

        if not TRAEFIK_SERVICE_REF_PATTERN.match(service_ref):
            issues.append(
                ValidationIssue(
                    code="EMV008",
                    message=f"backend.service {service_ref} must match <service>@<provider>",
                    manifest=manifest,
                    route=route_name,
                    field=f"{route_key}.backend.service",
                )
            )


def _validate_dns(
    route: dict[str, object],
    route_key: str,
    route_name: str,
    manifest: str,
    issues: list[ValidationIssue],
) -> None:
    dns = route.get("dns")
    if not isinstance(dns, dict):
        issues.append(
            ValidationIssue(
                code="EMV115",
                message=f"route {route_name} is missing required dns object",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.dns",
            )
        )
        return

    enabled = dns.get("enabled")
    target = dns.get("target")
    ttl = dns.get("ttl")

    if not isinstance(enabled, bool):
        issues.append(
            ValidationIssue(
                code="EMV116",
                message="dns.enabled is required and must be boolean",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.dns.enabled",
            )
        )

    if not isinstance(target, str) or target != EXPECTED_DNS_TARGET:
        issues.append(
            ValidationIssue(
                code="EMV117",
                message=f"dns.target must be {EXPECTED_DNS_TARGET}",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.dns.target",
            )
        )

    if not isinstance(ttl, str) or not ttl.strip() or not TTL_PATTERN.match(ttl):
        issues.append(
            ValidationIssue(
                code="EMV118",
                message="dns.ttl must be a duration like 300s, 5m, or 1h",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.dns.ttl",
            )
        )


def _validate_tls(
    route: dict[str, object],
    route_key: str,
    route_name: str,
    manifest: str,
    issues: list[ValidationIssue],
) -> None:
    tls = route.get("tls")
    if not isinstance(tls, dict):
        issues.append(
            ValidationIssue(
                code="EMV119",
                message=f"route {route_name} is missing required tls object",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.tls",
            )
        )
        return

    resolver = tls.get("resolver")
    if not isinstance(resolver, str) or not resolver.strip():
        issues.append(
            ValidationIssue(
                code="EMV120",
                message="tls.resolver is required and must be a non-empty string",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.tls.resolver",
            )
        )


def _validate_auth(
    route: dict[str, object],
    route_key: str,
    route_name: str,
    manifest: str,
    stack: str,
    issues: list[ValidationIssue],
) -> None:
    auth = route.get("auth")
    if not isinstance(auth, dict):
        issues.append(
            ValidationIssue(
                code="EMV121",
                message=f"route {route_name} is missing required auth object",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.auth",
            )
        )
        return

    mode = auth.get("mode")
    if mode not in ALLOWED_AUTH_MODES:
        issues.append(
            ValidationIssue(
                code="EMV004",
                message=(
                    f"auth.mode {mode} is invalid; "
                    "allowed: none, forwardAuth, native, oidc"
                ),
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.auth.mode",
            )
        )
        return

    if stack == "authentik-stack" and mode == "forwardAuth":
        issues.append(
            ValidationIssue(
                code="EMV005",
                message="authentik-stack cannot use auth.mode forwardAuth; use none",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.auth.mode",
            )
        )

    if stack == "harbor-stack" and mode == "forwardAuth":
        issues.append(
            ValidationIssue(
                code="EMV006",
                message="harbor-stack cannot use auth.mode forwardAuth; use native or oidc",
                manifest=manifest,
                route=route_name,
                field=f"{route_key}.auth.mode",
            )
        )


def _validate_cross_manifest(
    route_records: list[RouteRecord],
    issues: list[ValidationIssue],
) -> None:
    host_owners: dict[str, set[str]] = {}
    route_owners: dict[str, set[str]] = {}
    for record in route_records:
        if record.host:
            host_owners.setdefault(record.host, set()).add(record.manifest_name)
        if record.route_name:
            route_owners.setdefault(record.route_name, set()).add(record.manifest_name)

    for host, owners in sorted(host_owners.items()):
        if len(owners) > 1:
            issues.append(
                ValidationIssue(
                    code="EMV001",
                    message=f"host {host} is defined by multiple manifests",
                    field="spec.routes[].host",
                )
            )

    for route_name, owners in sorted(route_owners.items()):
        if len(owners) > 1:
            issues.append(
                ValidationIssue(
                    code="EMV009",
                    message=(
                        f"route name {route_name} is defined by multiple manifests"
                    ),
                    field="spec.routes[].name",
                )
            )
