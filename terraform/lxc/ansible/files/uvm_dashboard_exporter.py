#!/usr/bin/env python3
"""Plain-JSON exporter for the UVM (threat & vulnerability) dashboard.

See docs/threat-vuln-platform/plan.md's Phase 10: the OpenSearch
Dashboards visualization layer was abandoned after repeated rounds of
hand-authored visState JSON produced dashboards the operator called
"not good" (no rendering feedback while authoring, a stale saved-object
cache, a version-sensitive classic-viz params failure). This exporter
moves the rendering layer to Grafana instead, reusing the exact pattern
already proven in this repo by harbor_findings_exporter.py: poll a
backend on a refresh interval, cache the result in memory, serve it as
plain JSON over HTTP for Grafana's yesoreyeram-infinity-datasource
plugin (already installed in this Grafana image, GF_INSTALL_PLUGINS).

Two endpoints:
  GET /stack-risk.json -- flat array, one object per stack, a straight
    passthrough of stack-risk-summary's own documents (already exactly
    the right shape for a Grafana Table panel -- no reshaping needed;
    that index is itself a materialized rollup built by
    cve_enrichment_sync.py's compute_stack_rollup()).
  GET /funnel.json -- {"all": N, "has_exploit": N, "kev": N}, the
    3-stage vulnerability exploitability funnel, computed via the same
    terms/filter-agg technique already used in compute_stack_rollup()/
    fetch_cve_instances() (a single three-way filter aggregation
    against unified-cve-exposure).
  GET /healthz -- {"up": bool, "last_success_ts": float, "last_error": str|None}

Intentionally stdlib-only, matching every other findings-related script
in this repo (harbor_findings_sync.py, gvm_findings_sync.py,
cve_enrichment_sync.py, harbor_findings_exporter.py) -- no Python venv
convention on LXC hosts for jobs like this.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


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


def _es_request(base_url: str, path: str, *, auth_header: str, verify_tls: bool, timeout: int = 20) -> dict:
    req = urllib.request.Request(f"{base_url}{path}", method="GET")
    req.add_header("Authorization", auth_header)
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:  # nosec B310 — internal OpenSearch API on private SDN
        return json.loads(resp.read())


def _fetch_stack_rows(base_url: str, *, auth_header: str, verify_tls: bool) -> list[dict[str, Any]]:
    result = _es_request(
        base_url, "/stack-risk-summary/_search?size=100",
        auth_header=auth_header, verify_tls=verify_tls,
    )
    return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]


def _fetch_funnel(base_url: str, *, auth_header: str, verify_tls: bool) -> dict[str, int]:
    body = {
        "size": 0,
        "aggs": {
            "funnel": {
                "filters": {
                    "filters": {
                        "all": {"match_all": {}},
                        "has_exploit": {"bool": {"should": [
                            {"term": {"poc_available": True}},
                            {"term": {"kev_listed": True}},
                        ]}},
                        "kev": {"term": {"kev_listed": True}},
                    }
                }
            }
        },
    }
    req = urllib.request.Request(
        f"{base_url}/unified-cve-exposure/_search",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:  # nosec B310 — internal OpenSearch API on private SDN
        result = json.loads(resp.read())
    buckets = result.get("aggregations", {}).get("funnel", {}).get("buckets", {})
    return {
        "all": buckets.get("all", {}).get("doc_count", 0),
        "has_exploit": buckets.get("has_exploit", {}).get("doc_count", 0),
        "kev": buckets.get("kev", {}).get("doc_count", 0),
    }


class SnapshotStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.up = False
        self.last_success_ts = 0.0
        self.last_error: str | None = None
        self.stack_rows: list[dict[str, Any]] = []
        self.funnel: dict[str, int] = {"all": 0, "has_exploit": 0, "kev": 0}

    def update_success(self, stack_rows: list[dict[str, Any]], funnel: dict[str, int]) -> None:
        with self._lock:
            self.up = True
            self.last_success_ts = time.time()
            self.last_error = None
            self.stack_rows = stack_rows
            self.funnel = funnel

    def update_failure(self, error: str) -> None:
        with self._lock:
            self.up = False
            self.last_error = error

    def render_stack_rows(self) -> str:
        # Wrapped as {"rows": [...]}, not a bare array -- confirmed live
        # (Grafana server logs: this plugin's queryData call for a bare
        # array + root_selector:"" completes in ~2-4ms with zero output
        # rows, versus ~270ms and real rows for harbor_findings_exporter's
        # identically-shaped {"rows": [...]} + root_selector:"rows" query).
        # An empty root_selector is NOT treated as "the response root is
        # already the row array" -- match the proven-working shape exactly
        # instead of relying on that assumption.
        with self._lock:
            return json.dumps({"rows": self.stack_rows})

    def render_funnel(self) -> str:
        # "Long" format (one row per funnel stage, a string category field
        # + a numeric value field), not one row with 3 numeric columns --
        # Grafana's core Bar Chart panel requires a string/time field for
        # its X-axis category and errors ("Bar charts require a string or
        # time field") on an all-numeric wide-format row.
        with self._lock:
            f = self.funnel
            rows = [
                {"stage": "1. All Vulnerabilities", "count": f.get("all", 0)},
                {"stage": "2. Exploit Exists (PoC or Active)", "count": f.get("has_exploit", 0)},
                {"stage": "3. Actively Exploited (CISA KEV)", "count": f.get("kev", 0)},
            ]
            return json.dumps({"rows": rows})

    def render_health(self) -> str:
        with self._lock:
            return json.dumps({
                "up": self.up,
                "last_success_ts": self.last_success_ts,
                "last_error": self.last_error,
            })


class UvmDashboardExporter:
    def __init__(self) -> None:
        self.refresh_interval = int(_env("UVM_DASHBOARD_REFRESH_INTERVAL_SECONDS", "300"))
        self.es_url = _env("OPENSEARCH_URL")
        self.verify_tls = not _parse_bool("OPENSEARCH_NO_VERIFY_TLS", default=True)
        creds = base64.b64encode(f"{_env('OPENSEARCH_USER')}:{_env('OPENSEARCH_PASSWORD')}".encode()).decode()
        self.auth_header = f"Basic {creds}"
        self.snapshot = SnapshotStore()

    def _refresh_once(self) -> None:
        stack_rows = _fetch_stack_rows(self.es_url, auth_header=self.auth_header, verify_tls=self.verify_tls)
        funnel = _fetch_funnel(self.es_url, auth_header=self.auth_header, verify_tls=self.verify_tls)
        self.snapshot.update_success(stack_rows, funnel)

    def refresh_forever(self) -> None:
        while True:
            try:
                self._refresh_once()
            except Exception as exc:  # noqa: BLE001 — one bad refresh shouldn't kill the loop
                print(f"WARN: refresh failed: {exc}", file=sys.stderr)
                self.snapshot.update_failure(str(exc))
            time.sleep(self.refresh_interval)


class UvmDashboardHandler(BaseHTTPRequestHandler):
    exporter: UvmDashboardExporter

    def _write_json(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/stack-risk.json", "/stack-risk.json/"}:
            self._write_json(self.exporter.snapshot.render_stack_rows())
            return
        if self.path in {"/funnel.json", "/funnel.json/"}:
            self._write_json(self.exporter.snapshot.render_funnel())
            return
        if self.path in {"/healthz", "/healthz/"}:
            self._write_json(self.exporter.snapshot.render_health())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> int:
    exporter = UvmDashboardExporter()
    UvmDashboardHandler.exporter = exporter

    refresh_thread = threading.Thread(target=exporter.refresh_forever, daemon=True)
    refresh_thread.start()

    listen_address = _env("UVM_DASHBOARD_LISTEN_ADDRESS", "0.0.0.0")  # nosec B104 — nosonar: python:S5332 — internal Grafana datasource listener; private SDN
    listen_port = int(_env("UVM_DASHBOARD_LISTEN_PORT", "9415"))
    server = ThreadingHTTPServer((listen_address, listen_port), UvmDashboardHandler)
    print(f"uvm_dashboard_exporter listening on {listen_address}:{listen_port}, refresh every {exporter.refresh_interval}s")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
