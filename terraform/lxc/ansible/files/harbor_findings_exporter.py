#!/usr/bin/env python3
"""Prometheus exporter for Harbor proxy-cache scan coverage and findings."""

from __future__ import annotations

import base64
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


PAGE_SIZE = 100
SEVERITIES = ("Critical", "High", "Medium", "Low", "Unknown")


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value in (None, ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_rfc3339(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_line(name: str, value: int | float, labels: dict[str, str] | None = None) -> str:
    if not labels:
        return f"{name} {value}"
    rendered = ",".join(f'{key}="{_escape_label(val)}"' for key, val in sorted(labels.items()))
    return f"{name}{{{rendered}}} {value}"


def _repository_path(repository: str) -> str:
    return urllib.parse.quote(urllib.parse.quote(repository, safe=""), safe="")


class HarborClient:
    def __init__(self, base_url: str, username: str, password: str, *, insecure: bool) -> None:
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self._auth_header = f"Basic {token}"
        _CA_PATH = "/usr/local/share/ca-certificates/homelab-root.crt"
        self._ssl_context = (
            ssl.create_default_context(cafile=_CA_PATH)  # nosonar: python:S4423
            if os.path.exists(_CA_PATH)
            else ssl.create_default_context()  # nosonar: python:S4423
        )

    def _request_json(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": self._auth_header},
        )
        try:
            with urllib.request.urlopen(request, timeout=20, context=self._ssl_context) as response:  # nosec B310 — internal Harbor API on private SDN
                content = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", "replace").strip()
            raise RuntimeError(f"GET {path} returned {exc.code}: {detail}") from exc

        if not content.strip():
            return None
        return json.loads(content)

    def list_repositories(self, project: str) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request_json(
                f"/api/v2.0/projects/{project}/repositories?page={page}&page_size={PAGE_SIZE}"
            )
            page_items = payload or []
            repositories.extend(page_items)
            if len(page_items) < PAGE_SIZE:
                return repositories
            page += 1

    def list_artifacts(self, project: str, repository: str) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        page = 1
        path_prefix = (
            f"/api/v2.0/projects/{project}/repositories/{_repository_path(repository)}"
            "/artifacts?with_scan_overview=true"
        )
        while True:
            payload = self._request_json(f"{path_prefix}&page={page}&page_size={PAGE_SIZE}")
            page_items = payload or []
            artifacts.extend(page_items)
            if len(page_items) < PAGE_SIZE:
                return artifacts
            page += 1

    def get_vulnerabilities(self, project: str, repository: str, digest: str) -> dict[str, Any] | None:
        encoded_ref = urllib.parse.quote(digest, safe="")
        return self._request_json(
            f"/api/v2.0/projects/{project}/repositories/{_repository_path(repository)}"
            f"/artifacts/{encoded_ref}/additions/vulnerabilities"
        )


def _artifact_sort_key(artifact: dict[str, Any]) -> tuple[int, int, int, int]:
    tags = artifact.get("tags") or []
    extra_attrs = artifact.get("extra_attrs") or {}
    is_tagged = 0 if tags else 1
    is_amd64 = 0 if extra_attrs.get("os") == "linux" and extra_attrs.get("architecture") == "amd64" else 1
    has_scan = 0 if artifact.get("scan_overview") else 1
    is_real_platform = 0 if extra_attrs.get("os") == "linux" and extra_attrs.get("architecture") not in {None, "", "unknown"} else 1
    return (is_tagged, is_amd64, has_scan, is_real_platform)


def _choose_repository_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not artifacts:
        return None
    return min(artifacts, key=_artifact_sort_key)


def _artifact_tag_name(selected: dict[str, Any], artifacts: list[dict[str, Any]]) -> str:
    tags = selected.get("tags") or []
    if tags:
        first_tag = tags[0]
        if isinstance(first_tag, dict):
            return first_tag.get("name") or ""
        return str(first_tag)

    for artifact in artifacts:
        tags = artifact.get("tags") or []
        if not tags:
            continue
        first_tag = tags[0]
        if isinstance(first_tag, dict) and first_tag.get("name"):
            return first_tag["name"]
        if isinstance(first_tag, str) and first_tag:
            return first_tag

    return ""


def _scan_report_from_overview(artifact: dict[str, Any]) -> dict[str, Any] | None:
    overview = artifact.get("scan_overview") or {}
    for value in overview.values():
        if isinstance(value, dict):
            return value
    return None


def _severity_counts_from_scan_overview(report: dict[str, Any] | None) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not report:
        return counts
    summary = report.get("summary") or {}
    by_severity = summary.get("summary") or {}
    for severity in SEVERITIES:
        counts[severity] = int(by_severity.get(severity, 0) or 0)
    return counts


def _severity_counts_from_vulnerability_payload(payload: dict[str, Any] | None) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not payload:
        return counts
    for report in payload.values():
        if not isinstance(report, dict):
            continue
        for vulnerability in report.get("vulnerabilities") or []:
            severity = vulnerability.get("severity") or "Unknown"
            if severity not in SEVERITIES:
                severity = "Unknown"
            counts[severity] += 1
    return counts


class SnapshotStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.exporter_up = 0
        self.last_success_ts = 0.0
        self.last_duration_seconds = 0.0
        self.refresh_errors_total = 0
        self.metrics_body = ""
        self.findings_rows: list[dict[str, Any]] = []

    def update_success(self, metrics_body: str, duration_seconds: float, findings_rows: list[dict[str, Any]] | None = None) -> None:
        with self._lock:
            self.exporter_up = 1
            self.last_success_ts = time.time()
            self.last_duration_seconds = duration_seconds
            self.metrics_body = metrics_body
            self.findings_rows = findings_rows or []

    def update_failure(self) -> None:
        with self._lock:
            self.exporter_up = 0
            self.refresh_errors_total += 1

    def render(self) -> str:
        with self._lock:
            header = [
                "# HELP harbor_findings_exporter_up Whether the Harbor findings exporter last refresh succeeded.",
                "# TYPE harbor_findings_exporter_up gauge",
                _metric_line("harbor_findings_exporter_up", self.exporter_up),
                "# HELP harbor_findings_exporter_last_refresh_success_timestamp_seconds Last successful Harbor findings refresh timestamp.",
                "# TYPE harbor_findings_exporter_last_refresh_success_timestamp_seconds gauge",
                _metric_line(
                    "harbor_findings_exporter_last_refresh_success_timestamp_seconds",
                    self.last_success_ts,
                ),
                "# HELP harbor_findings_exporter_last_refresh_duration_seconds Duration of the last successful Harbor findings refresh.",
                "# TYPE harbor_findings_exporter_last_refresh_duration_seconds gauge",
                _metric_line(
                    "harbor_findings_exporter_last_refresh_duration_seconds",
                    self.last_duration_seconds,
                ),
                "# HELP harbor_findings_exporter_refresh_errors_total Total failed Harbor findings refresh attempts.",
                "# TYPE harbor_findings_exporter_refresh_errors_total counter",
                _metric_line("harbor_findings_exporter_refresh_errors_total", self.refresh_errors_total),
            ]
            if self.metrics_body:
                header.append(self.metrics_body)
            return "\n".join(header) + "\n"

    def render_findings_json(self) -> str:
        with self._lock:
            payload = {
                "exporter_up": int(self.exporter_up),
                "last_success_ts": float(self.last_success_ts),
                "last_duration_seconds": float(self.last_duration_seconds),
                "rows": list(self.findings_rows),
            }
            return json.dumps(payload, default=str)


def _determine_scan_state(
    report: dict | None,
    severity_counts: Counter[str],
    last_scan_ts: float | None,
    now: float,
    scan_stale_after: int,
) -> str:
    if not report and not severity_counts:
        return "unscanned"
    if last_scan_ts is not None and now - last_scan_ts > scan_stale_after:
        return "stale"
    return "scanned"


def _scanner_name_from_report(report_value: dict) -> str:
    scanner = report_value.get("scanner")
    if isinstance(scanner, dict):
        return scanner.get("name") or scanner.get("vendor") or ""
    return scanner or report_value.get("scanner_name") or ""


def _extract_vuln_ids(vuln: dict) -> tuple[str, str]:
    cve = vuln.get("vuln_id") or vuln.get("id") or vuln.get("vulnerability_id") or vuln.get("CVE") or vuln.get("cve") or ""
    pkg = vuln.get("pkg_name") or vuln.get("package") or vuln.get("name") or ""
    return cve, pkg


def _extract_vuln_versions(vuln: dict) -> tuple[str, str]:
    installed = vuln.get("installed_version") or vuln.get("pkg_version") or vuln.get("installedVersion") or vuln.get("version") or ""
    fixed = vuln.get("fixed_version") or vuln.get("fix_version") or vuln.get("fixedVersion") or ""
    return installed, fixed


def _extract_vuln_text(vuln: dict) -> tuple[str, str, list[str] | str]:
    severity = vuln.get("severity") or "Unknown"
    summary = vuln.get("title") or vuln.get("description") or vuln.get("summary") or ""
    links = vuln.get("links") or vuln.get("references") or []
    return severity, summary, links


def _extract_vuln_link(links: list[str] | str) -> str:
    if isinstance(links, str):
        return links
    return links[0] if links else ""


def _parse_vuln_entry(
    project: str,
    repository: str,
    tag: str,
    digest: str,
    push_time: Any,
    scanner_name: str,
    generated_at: Any,
    vuln: dict,
) -> tuple[tuple, dict]:
    cve, pkg = _extract_vuln_ids(vuln)
    installed, fixed = _extract_vuln_versions(vuln)
    severity, summary, links = _extract_vuln_text(vuln)
    link = _extract_vuln_link(links)
    key = (project, repository, digest, pkg, cve)
    row = {
        "project": project, "repository": repository, "tag": tag, "digest": digest,
        "artifact_push_time": push_time, "scan_completed_at": generated_at or None,
        "scanner": scanner_name, "cve_id": cve, "severity": severity,
        "package": pkg, "installed_version": installed, "fixed_version": fixed,
        "link": link, "summary": summary,
    }
    return key, row


def _build_vuln_findings_rows(
    project: str,
    repository: str,
    digest: str,
    selected: dict,
    artifacts: list,
    vuln_payload: dict,
) -> list[dict]:
    rows: list[dict] = []
    seen: set = set()
    tag = _artifact_tag_name(selected, artifacts)
    push_time = selected.get("push_time") or selected.get("extra_attrs", {}).get("created")
    for _report_name, report_value in (vuln_payload or {}).items():
        if not isinstance(report_value, dict):
            continue
        scanner_name = _scanner_name_from_report(report_value)
        generated_at = report_value.get("generated_at")
        for vuln in report_value.get("vulnerabilities") or []:
            key, row = _parse_vuln_entry(project, repository, tag, digest, push_time, scanner_name, generated_at, vuln)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


class HarborFindingsExporter:
    def __init__(self) -> None:
        self.projects = [project.strip() for project in _env("HARBOR_FINDINGS_PROJECTS", "dockerhub,ghcr,quay,lscr").split(",") if project.strip()]
        self.refresh_interval = int(_env("HARBOR_FINDINGS_REFRESH_INTERVAL_SECONDS", "300"))
        self.scan_stale_after = int(_env("HARBOR_FINDINGS_SCAN_STALE_AFTER_SECONDS", "86400"))
        self.client = HarborClient(
            _env("HARBOR_API_URL"),
            _env("HARBOR_API_USERNAME"),
            _env("HARBOR_API_PASSWORD"),
            insecure=_parse_bool("HARBOR_API_INSECURE", default=False),
        )
        self.snapshot = SnapshotStore()

    def _resolve_severity_and_timestamp(
        self,
        project: str,
        repository: str,
        digest: str,
        report: dict | None,
        severity_counts: Counter[str],
        last_scan_ts: float | None,
        lines: list[str],
    ) -> tuple[Counter[str], float | None, dict | None, bool]:
        if severity_counts or report:
            return severity_counts, last_scan_ts, None, False
        try:
            payload = self.client.get_vulnerabilities(project, repository, digest)
        except Exception:
            lines.append(_metric_line(
                "harbor_findings_repository_info", 1,
                {"project": project, "repository": repository, "state": "error", "digest": digest},
            ))
            return Counter(), last_scan_ts, None, True
        severity_counts = _severity_counts_from_vulnerability_payload(payload)
        for report_value in (payload or {}).values():
            if isinstance(report_value, dict):
                last_scan_ts = _parse_rfc3339(report_value.get("generated_at")) or last_scan_ts
                break
        return severity_counts, last_scan_ts, payload, False

    def _collect_repository_metrics(
        self,
        project: str,
        repository: str,
        now: float,
        lines: list[str],
        project_state_counts: dict,
        findings_rows: list[dict],
    ) -> None:
        try:
            artifacts = self.client.list_artifacts(project, repository)
        except Exception:
            project_state_counts[project]["error"] += 1
            lines.append(_metric_line(
                "harbor_findings_repository_info", 1,
                {"project": project, "repository": repository, "state": "error", "digest": ""},
            ))
            return
        selected = _choose_repository_artifact(artifacts)
        if selected is None:
            return
        digest = selected.get("digest", "")
        report = _scan_report_from_overview(selected)
        severity_counts = _severity_counts_from_scan_overview(report)
        last_scan_ts = _parse_rfc3339(report.get("end_time") if report else None)
        severity_counts, last_scan_ts, api_payload, had_error = self._resolve_severity_and_timestamp(
            project, repository, digest, report, severity_counts, last_scan_ts, lines,
        )
        if had_error:
            project_state_counts[project]["error"] += 1
            return
        state = _determine_scan_state(report, severity_counts, last_scan_ts, now, self.scan_stale_after)
        project_state_counts[project][state] += 1
        lines.append(_metric_line(
            "harbor_findings_repository_info", 1,
            {"project": project, "repository": repository, "state": state, "digest": digest},
        ))
        if last_scan_ts is not None:
            lines.append(_metric_line(
                "harbor_findings_repository_last_scan_timestamp_seconds", last_scan_ts,
                {"project": project, "repository": repository, "digest": digest},
            ))
        for severity in SEVERITIES:
            count = int(severity_counts.get(severity, 0))
            if count == 0:
                continue
            lines.append(_metric_line(
                "harbor_findings_vulnerabilities_total", count,
                {"project": project, "repository": repository, "severity": severity},
            ))
        vuln_payload = api_payload
        if vuln_payload is None:
            try:
                vuln_payload = self.client.get_vulnerabilities(project, repository, digest)
            except Exception:
                vuln_payload = None
        if vuln_payload:
            findings_rows.extend(_build_vuln_findings_rows(project, repository, digest, selected, artifacts, vuln_payload))

    def _collect_metrics(self) -> tuple[str, list[dict[str, Any]]]:
        findings_rows: list[dict[str, Any]] = []
        now = time.time()
        lines = [
            "# HELP harbor_findings_repositories_total Harbor proxy-cache repositories by project and scan state.",
            "# TYPE harbor_findings_repositories_total gauge",
            "# HELP harbor_findings_repository_info Harbor proxy-cache repository scan state for the selected representative digest.",
            "# TYPE harbor_findings_repository_info gauge",
            "# HELP harbor_findings_repository_last_scan_timestamp_seconds Last completed scan timestamp for the selected representative digest.",
            "# TYPE harbor_findings_repository_last_scan_timestamp_seconds gauge",
            "# HELP harbor_findings_vulnerabilities_total Harbor vulnerability counts by repository and severity.",
            "# TYPE harbor_findings_vulnerabilities_total gauge",
        ]
        project_state_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for project in self.projects:
            repositories = self.client.list_repositories(project)
            for repository_item in repositories:
                repository_name = repository_item.get("name", "")
                prefix = f"{project}/"
                repository = repository_name[len(prefix):] if repository_name.startswith(prefix) else repository_name
                if not repository:
                    continue
                self._collect_repository_metrics(project, repository, now, lines, project_state_counts, findings_rows)
        for project, counts in project_state_counts.items():
            for state in ("scanned", "unscanned", "stale", "error"):
                lines.append(_metric_line(
                    "harbor_findings_repositories_total",
                    int(counts.get(state, 0)),
                    {"project": project, "state": state},
                ))
        return "\n".join(lines), findings_rows

    def refresh_forever(self) -> None:
        while True:
            started = time.monotonic()
            try:
                metrics, findings = self._collect_metrics()
            except Exception:
                self.snapshot.update_failure()
            else:
                self.snapshot.update_success(metrics, time.monotonic() - started, findings)
            time.sleep(self.refresh_interval)


class MetricsHandler(BaseHTTPRequestHandler):
    exporter: HarborFindingsExporter

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/metrics", "/metrics/"}:
            payload = self.exporter.snapshot.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path in {"/findings.json", "/findings.json/"}:
            payload = self.exporter.snapshot.render_findings_json().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # unknown path
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> int:
    exporter = HarborFindingsExporter()
    MetricsHandler.exporter = exporter

    initial_thread = threading.Thread(target=exporter.refresh_forever, daemon=True)
    initial_thread.start()

    listen_address = _env("HARBOR_FINDINGS_LISTEN_ADDRESS", "0.0.0.0")  # nosec B104 — nosonar: python:S5332 — Prometheus metrics listener; HTTP is standard for scraping
    listen_port = int(_env("HARBOR_FINDINGS_LISTEN_PORT", "9414"))
    server = ThreadingHTTPServer((listen_address, listen_port), MetricsHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
