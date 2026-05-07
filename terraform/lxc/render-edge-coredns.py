#!/usr/bin/env python3
"""Render deterministic CoreDNS lab zone output from validated EdgeManifest files."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from edge_manifest import discover_edge_manifests, load_manifest, validate_manifests


EXPECTED_DNS_TARGET = os.environ["LAB_IP_PROXY"]


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
    host: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class GeneratedRecord:
    """Generated browser DNS A record derived from a route."""

    host: str
    ttl: str
    target: str
    manifest: str


@dataclass(frozen=True)
class RenderResult:
    """Result of rendering the CoreDNS lab zone."""

    rendered_zone: str
    generated_records: tuple[GeneratedRecord, ...]
    diff: str
    issues: tuple[RenderIssue, ...]
    warnings: tuple[RenderWarning, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        status = "passed" if self.ok else "failed"
        return {
            "status": status,
            "generated_record_count": len(self.generated_records),
            "issue_count": len(self.issues),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "generated_records": [
                {
                    "host": record.host,
                    "ttl": record.ttl,
                    "target": record.target,
                    "manifest": record.manifest,
                }
                for record in self.generated_records
            ],
            "diff": self.diff,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render full CoreDNS lab zone output from seed records and "
            "validated EdgeManifest files."
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
        "--seed-zone",
        type=Path,
        default=Path(__file__).resolve().parent / "ansible" / "files" / "coredns-lab.zone",
        help="Path to the seed CoreDNS zone file.",
    )
    parser.add_argument(
        "--output-zone",
        type=Path,
        default=Path(__file__).resolve().parent / ".generated" / "coredns" / "coredns-lab.zone",
        help="Dry-run output file for rendered CoreDNS zone.",
    )
    parser.add_argument(
        "--validate-live-forwarding",
        action="store_true",
        help=(
            "Validate live resolver forwarding for generated hosts. "
            "This check is skipped unless this flag is set."
        ),
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


def _parse_origin(seed_lines: list[str]) -> str | None:
    for line in seed_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if not stripped.startswith("$ORIGIN"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            return None
        return parts[1].rstrip(".")
    return None


def _fqdn_to_label(host: str, origin: str) -> str | None:
    normalized_host = host.rstrip(".")
    if normalized_host == origin:
        return "@"
    suffix = f".{origin}"
    if not normalized_host.endswith(suffix):
        return None
    return normalized_host[: -len(suffix)]


def _parse_seed_a_record(line: str, origin: str) -> tuple[str, str] | None:
    content = line.split(";", 1)[0].strip()
    if not content:
        return None

    parts = content.split()
    if len(parts) < 3:
        return None

    name = parts[0]
    record_type_index = -1
    if len(parts) >= 4 and parts[1].upper() == "IN" and parts[2].upper() == "A":
        record_type_index = 2
    elif parts[1].upper() == "A":
        record_type_index = 1

    if record_type_index == -1:
        return None

    value_index = record_type_index + 1
    if value_index >= len(parts):
        return None

    value = parts[value_index]
    if name == "@":
        host = origin
    elif name.endswith("."):
        host = name.rstrip(".")
    else:
        host = f"{name}.{origin}"

    return host, value


def _manifest_routes_for_generation(
    manifest_path: Path,
    issues: list[RenderIssue],
) -> list[dict[str, object]]:
    document = load_manifest(manifest_path)
    if not isinstance(document, dict):
        issues.append(
            RenderIssue(
                code="CDR100",
                message="manifest top-level must be a mapping",
                manifest=str(manifest_path),
            )
        )
        return []

    spec = document.get("spec")
    if not isinstance(spec, dict):
        issues.append(
            RenderIssue(
                code="CDR101",
                message="manifest spec must be a mapping",
                manifest=str(manifest_path),
            )
        )
        return []

    routes = spec.get("routes")
    if not isinstance(routes, list):
        issues.append(
            RenderIssue(
                code="CDR102",
                message="manifest spec.routes must be a list",
                manifest=str(manifest_path),
            )
        )
        return []

    return [route for route in routes if isinstance(route, dict)]


def _generated_record_from_route(route: dict[str, object], manifest_path: Path) -> GeneratedRecord | None:
    dns = route.get("dns")
    if not isinstance(dns, dict) or dns.get("enabled") is not True:
        return None

    host = str(route.get("host", "")).strip().rstrip(".")
    if not host:
        return None

    return GeneratedRecord(
        host=host,
        ttl=str(dns.get("ttl", "")).strip(),
        target=str(dns.get("target", "")).strip(),
        manifest=str(manifest_path),
    )


def _collect_generated_records(
    manifest_paths: list[Path],
    issues: list[RenderIssue],
) -> tuple[GeneratedRecord, ...]:
    records: list[GeneratedRecord] = []
    host_index: dict[str, str] = {}

    for manifest_path in sorted(manifest_paths):
        for route in _manifest_routes_for_generation(manifest_path, issues):
            record = _generated_record_from_route(route, manifest_path)
            if record is None:
                continue

            owner = host_index.get(record.host)
            if owner is not None:
                issues.append(
                    RenderIssue(
                        code="CDR200",
                        message=(
                            "duplicate generated browser DNS record for host "
                            f"{record.host} (from {owner} and {record.manifest})"
                        ),
                        manifest=record.manifest,
                        host=record.host,
                    )
                )
                continue

            host_index[record.host] = record.manifest
            records.append(record)

    records.sort(key=lambda record: record.host)
    return tuple(records)


def _render_zone_from_seed(
    seed_text: str,
    generated_records: tuple[GeneratedRecord, ...],
    issues: list[RenderIssue],
) -> str:
    seed_lines = seed_text.splitlines()
    origin = _parse_origin(seed_lines)
    if origin is None:
        issues.append(
            RenderIssue(
                code="CDR103",
                message="seed zone must define $ORIGIN",
            )
        )
        return ""

    generated_hosts = {record.host for record in generated_records}
    preserved_lines: list[str] = []

    for line in seed_lines:
        parsed = _parse_seed_a_record(line, origin)
        if parsed is None:
            preserved_lines.append(line)
            continue

        host, _value = parsed
        if host in generated_hosts:
            continue
        preserved_lines.append(line)

    output_lines = preserved_lines[:]
    if output_lines and output_lines[-1].strip():
        output_lines.append("")

    output_lines.append("; Generated browser edge records (manifest-owned)")
    for record in generated_records:
        label = _fqdn_to_label(record.host, origin)
        if label is None:
            issues.append(
                RenderIssue(
                    code="CDR104",
                    message=(
                        f"generated host {record.host} is outside zone {origin}"
                    ),
                    manifest=record.manifest,
                    host=record.host,
                )
            )
            continue

        output_lines.append(
            f"{label:<15} {record.ttl:<4} IN  A   {record.target} ; generated from EdgeManifest"
        )

    return "\n".join(output_lines) + "\n"


def _build_diff(seed_text: str, rendered_zone: str, seed_zone: Path, output_zone: Path) -> str:
    diff_lines = list(
        difflib.unified_diff(
            seed_text.splitlines(),
            rendered_zone.splitlines(),
            fromfile=str(seed_zone),
            tofile=str(output_zone),
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def _live_validate_forwarding(
    generated_records: tuple[GeneratedRecord, ...],
    warnings: list[RenderWarning],
) -> None:
    for record in generated_records:
        try:
            resolved = {
                info[4][0]
                for info in socket.getaddrinfo(record.host, None, family=socket.AF_INET)
            }
        except OSError as exc:
            warnings.append(
                RenderWarning(
                    code="CDR300",
                    message=f"live DNS lookup failed for {record.host}: {exc}",
                    host=record.host,
                )
            )
            continue

        if record.target not in resolved:
            warnings.append(
                RenderWarning(
                    code="CDR301",
                    message=(
                        f"live DNS lookup for {record.host} resolved to {sorted(resolved)} "
                        f"instead of expected {record.target}"
                    ),
                    host=record.host,
                )
            )


def render_coredns_dry_run(
    manifest_paths: list[Path],
    seed_zone_path: Path,
    output_zone_path: Path,
    validate_live_forwarding: bool = False,
) -> RenderResult:
    """Render full CoreDNS zone output from seed + generated browser records."""

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
            rendered_zone="",
            generated_records=(),
            diff="",
            issues=issues,
            warnings=(),
        )

    seed_text = seed_zone_path.read_text(encoding="utf-8")
    issues: list[RenderIssue] = []
    warnings: list[RenderWarning] = []

    generated_records = _collect_generated_records(manifest_paths, issues)
    rendered_zone = _render_zone_from_seed(seed_text, generated_records, issues)
    diff = _build_diff(seed_text, rendered_zone, seed_zone_path, output_zone_path)

    if validate_live_forwarding and not issues:
        _live_validate_forwarding(generated_records, warnings)

    issues.sort(key=lambda issue: (issue.code, issue.manifest or "", issue.host or "", issue.message))
    warnings.sort(key=lambda warning: (warning.code, warning.host or "", warning.message))
    return RenderResult(
        rendered_zone=rendered_zone,
        generated_records=generated_records,
        diff=diff,
        issues=tuple(issues),
        warnings=tuple(warnings),
    )


def write_rendered_zone(rendered_zone: str, output_zone_path: Path) -> Path:
    """Write rendered CoreDNS zone output to the target dry-run file."""

    output_zone_path.parent.mkdir(parents=True, exist_ok=True)
    output_zone_path.write_text(rendered_zone, encoding="utf-8")
    return output_zone_path


def _json_payload(result: RenderResult, output_zone_path: Path) -> dict[str, object]:
    payload = result.to_dict()
    payload["output_zone"] = str(output_zone_path.resolve())
    return payload


def _print_failure(result: RenderResult) -> None:
    print("CoreDNS render dry-run failed.")
    print(f"Issue count: {len(result.issues)}")
    for issue in result.issues:
        scope = issue.manifest or "<unknown>"
        if issue.host:
            print(f"- [{issue.code}] {scope} ({issue.host}): {issue.message}")
        else:
            print(f"- [{issue.code}] {scope}: {issue.message}")


def _print_success(result: RenderResult, output_zone_path: Path) -> None:
    print(
        "CoreDNS render dry-run passed. "
        f"Rendered zone with {len(result.generated_records)} generated browser record(s)."
    )
    print(f"- wrote: {output_zone_path.resolve()}")

    if result.warnings:
        print(f"Warning count: {len(result.warnings)}")
        for warning in result.warnings:
            if warning.host:
                print(f"- [{warning.code}] {warning.host}: {warning.message}")
            else:
                print(f"- [{warning.code}] {warning.message}")

    print("Dry-run diff:")
    if result.diff:
        print(result.diff)
    else:
        print("(no changes)")


def main() -> int:
    args = parse_args()
    manifest_paths = _resolve_manifest_paths(args)
    seed_zone_path = args.seed_zone.resolve()
    output_zone_path = args.output_zone.resolve()

    result = render_coredns_dry_run(
        manifest_paths=manifest_paths,
        seed_zone_path=seed_zone_path,
        output_zone_path=output_zone_path,
        validate_live_forwarding=args.validate_live_forwarding,
    )

    if args.json:
        print(json.dumps(_json_payload(result, output_zone_path), indent=2, sort_keys=True))
        if result.ok:
            write_rendered_zone(result.rendered_zone, output_zone_path)
        return 0 if result.ok else 1

    if not result.ok:
        _print_failure(result)
        return 1

    write_rendered_zone(result.rendered_zone, output_zone_path)
    _print_success(result, output_zone_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
