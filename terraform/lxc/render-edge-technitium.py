#!/usr/bin/env python3
"""Render Technitium parity-zone records from seed zone and EdgeManifest files."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from edge_manifest import discover_edge_manifests, load_manifest, validate_manifests  # noqa: E402


@dataclass(frozen=True)
class RenderIssue:
    code: str
    message: str
    manifest: str | None = None
    host: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class RenderedRecord:
    name: str
    ip: str
    host: str
    source: str
    stack: str | None = None
    ptr: bool = False


@dataclass(frozen=True)
class GeneratedRecord:
    host: str
    ttl: str
    target: str
    manifest: str
    stack: str


@dataclass(frozen=True)
class RenderResult:
    zone: str
    records: tuple[RenderedRecord, ...]
    generated_records: tuple[GeneratedRecord, ...]
    diff: str
    issues: tuple[RenderIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "passed" if self.ok else "failed",
            "zone": self.zone,
            "record_count": len(self.records),
            "generated_record_count": len(self.generated_records),
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
            "records": [
                {"name": record.name, "ip": record.ip, "host": record.host, "source": record.source}
                for record in self.records
            ],
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
            "Render Technitium parity-zone record JSON from the CoreDNS seed zone "
            "and validated EdgeManifest files."
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
        "--output-records",
        type=Path,
        default=Path(__file__).resolve().parent / ".generated" / "technitium" / "zone-records.json",
        help="Dry-run output file for rendered Technitium record JSON.",
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
        if not stripped or stripped.startswith(";") or not stripped.startswith("$ORIGIN"):
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


def _parse_seed_a_record(line: str, origin: str) -> tuple[str, str, str] | None:
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

    return name, host, value


def _manifest_routes_for_generation(
    manifest_path: Path,
    issues: list[RenderIssue],
) -> tuple[str, list[dict[str, object]]]:
    document = load_manifest(manifest_path)
    if not isinstance(document, dict):
        issues.append(RenderIssue(code="TDR100", message="manifest top-level must be a mapping", manifest=str(manifest_path)))
        return "", []

    spec = document.get("spec")
    if not isinstance(spec, dict):
        issues.append(RenderIssue(code="TDR101", message="manifest spec must be a mapping", manifest=str(manifest_path)))
        return "", []

    routes = spec.get("routes")
    if not isinstance(routes, list):
        issues.append(RenderIssue(code="TDR102", message="manifest spec.routes must be a list", manifest=str(manifest_path)))
        return "", []

    metadata = document.get("metadata")
    stack = str(metadata.get("stack", "")).strip() if isinstance(metadata, dict) else ""

    return stack, [route for route in routes if isinstance(route, dict)]


def _generated_record_from_route(route: dict[str, object], manifest_path: Path, stack: str) -> GeneratedRecord | None:
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
        stack=stack,
    )


def _collect_generated_records(
    manifest_paths: list[Path],
    issues: list[RenderIssue],
) -> tuple[GeneratedRecord, ...]:
    records: list[GeneratedRecord] = []
    host_index: dict[str, str] = {}

    for manifest_path in sorted(manifest_paths):
        stack, routes = _manifest_routes_for_generation(manifest_path, issues)
        for route in routes:
            record = _generated_record_from_route(route, manifest_path, stack)
            if record is None:
                continue

            owner = host_index.get(record.host)
            if owner is not None:
                issues.append(
                    RenderIssue(
                        code="TDR200",
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


def _expand_env_placeholders(seed_text: str) -> str:
    return os.path.expandvars(seed_text)


def _render_records_from_seed(
    seed_text: str,
    generated_records: tuple[GeneratedRecord, ...],
    issues: list[RenderIssue],
) -> tuple[str, tuple[RenderedRecord, ...]]:
    seed_lines = seed_text.splitlines()
    origin = _parse_origin(seed_lines)
    if origin is None:
        issues.append(RenderIssue(code="TDR103", message="seed zone must define $ORIGIN"))
        return "", ()

    generated_by_host = {record.host: record for record in generated_records}
    rendered_records: list[RenderedRecord] = []

    for line in seed_lines:
        parsed = _parse_seed_a_record(line, origin)
        if parsed is None:
            continue

        name, host, value = parsed
        if host in generated_by_host:
            continue
        if name == "@":
            issues.append(
                RenderIssue(
                    code="TDR104",
                    message="root A records are not supported in Technitium parity renderer",
                    host=host,
                )
            )
            continue
        rendered_records.append(RenderedRecord(name=name, ip=value, host=host, source="seed"))

    authority_ip = os.environ.get("LAB_IP_TECHNITIUM", "${LAB_IP_TECHNITIUM}")
    rendered_records = [record for record in rendered_records if record.name not in {"dns", "ns1"}]
    rendered_records.extend(
        [
            RenderedRecord(name="dns", ip=authority_ip, host=f"dns.{origin}", source="authority"),
            RenderedRecord(name="ns1", ip=authority_ip, host=f"ns1.{origin}", source="authority"),
        ]
    )

    for generated in generated_records:
        label = _fqdn_to_label(generated.host, origin)
        if label is None or label == "@":
            issues.append(
                RenderIssue(
                    code="TDR105",
                    message=f"generated host {generated.host} is outside supported zone scope {origin}",
                    manifest=generated.manifest,
                    host=generated.host,
                )
            )
            continue
        rendered_records.append(
            RenderedRecord(
                name=label,
                ip=generated.target,
                host=generated.host,
                source="generated",
                stack=generated.stack,
            )
        )

    rendered_records.sort(key=lambda record: record.host)
    return origin, _assign_ptr_ownership(tuple(rendered_records))


def _assign_ptr_ownership(records: tuple[RenderedRecord, ...]) -> tuple[RenderedRecord, ...]:
    """Pick exactly one PTR owner per distinct IP.

    A PTR record is one name per IP, so when multiple A records share an
    IP (every browser-routed hostname behind Traefik shares LAB_IP_PROXY,
    for instance) only one of them can own the reverse entry. Preference
    order: the record generated from proxy-stack's own edge.yaml (that
    IP is genuinely proxy-stack's), else the record named "dns" (covers
    the dns/ns1 pair sharing LAB_IP_TECHNITIUM), else the
    alphabetically-first name in the group -- deterministic, so re-runs
    never flip which name owns an existing PTR.
    """
    by_ip: dict[str, list[RenderedRecord]] = {}
    for record in records:
        by_ip.setdefault(record.ip, []).append(record)

    ptr_owners: set[RenderedRecord] = set()
    for group in by_ip.values():
        proxy_owned = [r for r in group if r.stack == "proxy-stack"]
        dns_named = [r for r in group if r.name == "dns"]
        if proxy_owned:
            ptr_owners.add(proxy_owned[0])
        elif dns_named:
            ptr_owners.add(dns_named[0])
        else:
            ptr_owners.add(min(group, key=lambda r: r.name))

    return tuple(replace(record, ptr=(record in ptr_owners)) for record in records)


def _records_payload(zone: str, records: tuple[RenderedRecord, ...]) -> str:
    payload = {
        "zone": zone,
        "records": [
            {"name": record.name, "ip": record.ip, "ptr": record.ptr} for record in records
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _build_diff(previous_output: str, rendered_output: str, output_path: Path) -> str:
    diff_lines = list(
        difflib.unified_diff(
            previous_output.splitlines(),
            rendered_output.splitlines(),
            fromfile=f"{output_path} (previous)",
            tofile=str(output_path),
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def render_technitium_dry_run(
    manifest_paths: list[Path],
    seed_zone_path: Path,
    output_records_path: Path,
) -> RenderResult:
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
        return RenderResult(zone="", records=(), generated_records=(), diff="", issues=issues)

    seed_text = _expand_env_placeholders(seed_zone_path.read_text(encoding="utf-8"))
    issues: list[RenderIssue] = []
    generated_records = _collect_generated_records(manifest_paths, issues)
    zone, records = _render_records_from_seed(seed_text, generated_records, issues)

    rendered_output = _records_payload(zone, records) if zone else ""
    previous_output = output_records_path.read_text(encoding="utf-8") if output_records_path.exists() else ""
    diff = _build_diff(previous_output, rendered_output, output_records_path)

    issues.sort(key=lambda issue: (issue.code, issue.manifest or "", issue.host or "", issue.message))
    return RenderResult(
        zone=zone,
        records=records,
        generated_records=generated_records,
        diff=diff,
        issues=tuple(issues),
    )


def write_rendered_records(zone: str, records: tuple[RenderedRecord, ...], output_records_path: Path) -> Path:
    output_records_path.parent.mkdir(parents=True, exist_ok=True)
    output_records_path.write_text(_records_payload(zone, records), encoding="utf-8")
    return output_records_path


def _json_payload(result: RenderResult, output_records_path: Path) -> dict[str, object]:
    payload = result.to_dict()
    payload["output_records"] = str(output_records_path.resolve())
    return payload


def main() -> int:
    args = parse_args()
    manifest_paths = _resolve_manifest_paths(args)
    seed_zone_path = args.seed_zone.resolve()
    output_records_path = args.output_records.resolve()

    result = render_technitium_dry_run(
        manifest_paths=manifest_paths,
        seed_zone_path=seed_zone_path,
        output_records_path=output_records_path,
    )

    if args.json:
        print(json.dumps(_json_payload(result, output_records_path), indent=2, sort_keys=True))
    elif result.ok:
        print(
            "Technitium render dry-run passed. "
            f"Rendered zone {result.zone} with {len(result.records)} record(s)."
        )
        print(f"- wrote: {output_records_path.resolve()}")
        print("Dry-run diff:")
        print(result.diff or "(no changes)")
    else:
        print("Technitium render dry-run failed.")
        print(f"Issue count: {len(result.issues)}")
        for issue in result.issues:
            scope = issue.manifest or "<unknown>"
            if issue.host:
                print(f"- [{issue.code}] {scope} ({issue.host}): {issue.message}")
            else:
                print(f"- [{issue.code}] {scope}: {issue.message}")

    if result.ok:
        write_rendered_records(result.zone, result.records, output_records_path)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
