#!/usr/bin/env python3
"""Scheduled pull of Greenbone/GVM vulnerability findings into OpenSearch.

See docs/elasticsearch-stack/README.md section 3 (Data model) for the
GVM-specific document shape and the real caveats (finding_id is an NVT
OID not always a CVE, target replaces artifact, CVSS v2-vs-v3/threat-
bucket cross-source severity mismatch is a real open question, threat=Log
rows are ~90-95% of raw production results and are filtered out here).

Talks to gvm-bridge's /findings/all endpoint (localhost:8010, same host
this script runs on -- greenbone-stack) rather than opening a second
direct GMP/Unix-socket connection. gvm-bridge already holds the GMP
credential and does the get_results/never-get_reports, rows=-1 dance;
this script is a plain HTTP client on top of it, matching the "small
bridge service holds real credentials, caller gets trivial JSON/HTTP"
precedent docs/elasticsearch-stack/plan.md already states for the later
findings-mcp layer -- a deliberate improvement over that same doc's
Ingestion pattern section, which assumed a second direct-socket
connection; avoids duplicating GMP session code and cuts the attack
surface (one process with real GVM credentials, not two).

Same shape as harbor_findings_sync.py: deterministic per-document _id
(source::finding_id::host:port) so reruns are pure upserts, never
duplicates; first_seen set only on first insert (scripted upsert),
last_seen updates every run.

Intentionally stdlib-only, matching harbor_findings_sync.py's/
harbor_repull.py's own reasoning (no Python venv convention on LXC hosts
for jobs like this).
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Duplicated from terraform/lxc/ansible/files/greenbone-scan-setup/
# setup_scan_program.py, same "hardcode the cross-role constant rather
# than re-derive it" reasoning harbor_findings_sync.py already uses for
# Harbor's mirror-project-vs-direct-project asymmetry. Keep in sync by
# hand if that file's ZONES/REDTEAM_EXCLUDE ever change.
ZONES = [
    {"key": "build_seg", "cidr": "192.168.10.0/24"},
    {"key": "mgmt_seg", "cidr": "192.168.20.0/24"},
    {"key": "edge_seg", "cidr": "192.168.30.0/24"},
    {"key": "infra_seg", "cidr": "192.168.40.0/24"},
    {"key": "ai_seg", "cidr": "192.168.50.0/24"},
    {"key": "game_seg", "cidr": "192.168.60.0/24"},
    {"key": "pentest_seg", "cidr": "192.168.70.0/24"},
    {"key": "media_seg", "cidr": "192.168.80.0/24"},
    {"key": "cse_seg", "cidr": "192.168.100.0/24"},
    {"key": "connector_seg", "cidr": "192.168.110.0/24"},
    {"key": "apps_seg", "cidr": "192.168.120.0/24"},
    {"key": "lan", "cidr": "192.168.1.0/24"},
]
_ZONE_NETWORKS = [(z["key"], ipaddress.ip_network(z["cidr"])) for z in ZONES]

# Every FIXTURE_EXCLUDE address from setup_scan_program.py, flattened.
REDTEAM_EXCLUDE = ["192.168.1.113", "192.168.1.55", "192.168.70.12", "192.168.70.13", "192.168.70.210"]

# Reverse IP->stack registry (Phase 9, docs/threat-vuln-platform/plan.md,
# 2026-09-01) -- same graceful-degrade-to-empty-dict pattern as
# harbor_findings_sync.py's load_production_registry(). Derived from
# .env's LAB_IP_* vars (the canonical IP registry in this repo); GVM
# only ever sees raw IPs, so this is what makes "which stack does this
# scanned host belong to" answerable at all. Hosts not in the registry
# (workstations, RPis, IoT, pve/pve-test-vm themselves, unrecognized
# devices) stay stack: null -- same graceful-degrade already used for
# zone: null on non-VLAN-zoned hosts.
_STACK_REGISTRY_PATH = Path(__file__).parent / "assets" / "ip_to_stack.json"


def load_stack_registry() -> dict:
    try:
        with open(_STACK_REGISTRY_PATH) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: failed to load stack registry ({exc}), all hosts will show stack=null", file=sys.stderr)
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_zone(host: str) -> str | None:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None
    for key, network in _ZONE_NETWORKS:
        if addr in network:
            return key
    return None


def _basic_auth_header(user: str, password: str) -> str:
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {creds}"


def fetch_gvm_findings(bridge_url: str, *, timeout: int = 120) -> list[dict]:
    req = urllib.request.Request(f"{bridge_url.rstrip('/')}/findings/all", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
        body = json.loads(resp.read())
    return body.get("results", [])


def build_documents(raw_results: list[dict], *, scan_time_fallback: str, stack_registry: dict) -> list[dict]:
    docs = []
    now = _now_iso()
    for r in raw_results:
        threat = r.get("threat")
        if threat == "Log":
            # ~90-95% of raw production results, purely informational --
            # never indexed, not even filtered at query time. See
            # docs/elasticsearch-stack/README.md section 3.
            continue

        finding_id = r.get("finding_id")
        if not finding_id:
            continue

        host = r.get("host")
        try:
            severity_raw = float(r["severity"]) if r.get("severity") not in (None, "") else None
        except (TypeError, ValueError):
            severity_raw = None
        try:
            qod = int(r["qod"]) if r.get("qod") not in (None, "") else None
        except (TypeError, ValueError):
            qod = None

        pentest_target = bool(host in REDTEAM_EXCLUDE) if host else False
        docs.append(
            {
                "source": "greenbone",
                "finding_id": finding_id,
                "cve": [c for c in (r.get("cve") or []) if c],
                "name": r.get("name"),
                "severity_raw": severity_raw,
                "threat_raw": threat,
                "qod": qod,
                "target": {
                    "host": host,
                    "hostname": r.get("hostname") or None,
                    "port": r.get("port"),
                    "zone": _resolve_zone(host) if host else None,
                    "stack": stack_registry.get(host) if host else None,
                    # Derived, not guessed, per docs/threat-vuln-platform/plan.md's UVM
                    # redesign phase (2026-09-01): a pentest_target is by definition
                    # not production; a host with unknown pentest_target status (no
                    # host resolved) is also treated as unknown/false, never assumed
                    # production.
                    "in_production": (not pentest_target) if host else False,
                    "pentest_target": pentest_target,
                },
                "scan_task": r.get("task_name"),
                "scan_time": r.get("creation_time") or scan_time_fallback,
                "last_seen": now,
            }
        )
    return docs


def doc_id(doc: dict) -> str:
    target = doc["target"]
    return f"{doc['source']}::{doc['finding_id']}::{target['host']}:{target['port']}"


def bulk_upsert(base_url: str, index: str, docs: list[dict], *, auth_header: str, verify_tls: bool, dry_run: bool) -> tuple[int, int]:
    """Returns (indexed_count, error_count)."""
    if not docs:
        return 0, 0
    if dry_run:
        return len(docs), 0

    now = _now_iso()
    lines = []
    for doc in docs:
        _id = doc_id(doc)
        upsert_doc = dict(doc)
        upsert_doc["first_seen"] = now
        lines.append(json.dumps({"update": {"_index": index, "_id": _id}}))
        lines.append(
            json.dumps(
                {
                    "script": {
                        # putAll refreshes every current-scan-observed field
                        # (threat_raw, severity_raw, cve, qod, last_seen,
                        # scan_time -- doc already carries the latter two)
                        # on already-indexed documents, not just timestamps.
                        # Same latent bug found and fixed in
                        # harbor_findings_sync.py 2026-08-18: the previous
                        # version only ever touched last_seen/scan_time/
                        # first_seen, so any future field addition would
                        # silently never backfill onto already-indexed
                        # documents via a rerun. first_seen stays
                        # deliberately sticky (only set if still null).
                        "source": (
                            "ctx._source.putAll(params.doc); "
                            "if (ctx._source.first_seen == null) { ctx._source.first_seen = params.now }"
                        ),
                        "lang": "painless",
                        "params": {"now": now, "doc": doc},
                    },
                    "upsert": upsert_doc,
                }
            )
        )
    body = ("\n".join(lines) + "\n").encode("utf-8")

    url = f"{base_url}/_bulk"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/x-ndjson")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"ERROR: bulk index failed ({exc.code}): {exc.read()[:500]}", file=sys.stderr)
        return 0, len(docs)

    error_count = 0
    if result.get("errors"):
        for item in result.get("items", []):
            update_result = item.get("update", {})
            if update_result.get("status", 200) >= 300:
                error_count += 1
    return len(docs) - error_count, error_count


def update_sync_state(
    base_url: str,
    *,
    auth_header: str,
    verify_tls: bool,
    started: str,
    finished: str,
    status: str,
    findings_indexed: int,
    errors: int,
) -> None:
    doc = {
        "source": "greenbone",
        "started": started,
        "finished": finished,
        "status": status,
        "findings_indexed": findings_indexed,
        "errors": errors,
    }
    url = f"{base_url}/es-findings-sync-state/_doc/greenbone"
    req = urllib.request.Request(url, data=json.dumps(doc).encode("utf-8"), method="PUT")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15):  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            pass
    except urllib.error.HTTPError as exc:
        print(f"WARN: failed to update sync state: {exc}", file=sys.stderr)


# --- Credentialed-scan coverage check (docs/gvm-coverage-cleanup/plan.md) ---
# Found 2026-10-11: every scheduled fleet credentialed scan since
# 2026-09-30 had silently failed authentication ("SSH Login Failed For
# Authenticated Checks", zero Local Security Check results) for 11 days
# with nothing noticing. This check runs after every ingest and makes that
# failure loud: one summary document in es-findings-sync-state
# (_id greenbone-coverage) plus a non-zero exit, which fails the
# gvm-findings-ingest systemd unit.
AUTH_OK_NAME = "SSH Login Successful For Authenticated Checks"
AUTH_FAIL_NAME = "SSH Login Failed For Authenticated Checks"
# Unscheduled by design (docs/greenbone-stack/README.md) -- never "stale".
COVERAGE_IGNORE_TASKS = {"Credentialed scan: OCI Pangolin public edge"}
# Weekly schedules (setup_credentials.py ZONE_WEEKLY_SLOT); 8 days
# tolerates a run that starts late or spans midnight before alerting.
COVERAGE_MAX_AGE_HOURS = 8 * 24
COVERAGE_ACTIVE_STATUSES = {"Running", "Requested", "Queued"}
COVERAGE_FAILING = {"never_run", "auth_failed", "no_auth_evidence", "no_results", "stale", "unscheduled"}


def fetch_credentialed_tasks(bridge_url: str, *, timeout: int = 60) -> list[dict]:
    req = urllib.request.Request(f"{bridge_url.rstrip('/')}/tasks/credentialed", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
        body = json.loads(resp.read())
    return body.get("tasks", [])


def _parse_gmp_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_coverage(tasks: list[dict], raw_results: list[dict], *, now: datetime) -> list[dict]:
    """One row per (credentialed Task, target host): {"task", "host",
    "status", "coverage", "last_scan_start", "results_in_last_run"}.
    Per host, not per task, because one Task covers a whole VLAN
    (setup_credentials.py) and a single host can fail to authenticate --
    or be unreachable -- while the rest succeed. coverage is "ok",
    "running", or one of COVERAGE_FAILING ("no_results" = the host
    produced nothing at all in the last run: down, or filtered)."""
    results_by_task: dict[str, list[dict]] = {}
    for r in raw_results:
        results_by_task.setdefault(r.get("task_name") or "", []).append(r)

    rows = []
    for task in tasks:
        name = task.get("name") or ""
        if name in COVERAGE_IGNORE_TASKS:
            continue
        started = _parse_gmp_time(task.get("last_report_scan_start"))
        run_results = []
        if started is not None:
            for r in results_by_task.get(name, []):
                created = _parse_gmp_time(r.get("creation_time"))
                if created is not None and created >= started:
                    run_results.append(r)
        by_host: dict[str, set] = {}
        for r in run_results:
            by_host.setdefault(r.get("host") or "", set()).add(r.get("name"))
        hosts = task.get("target_hosts") or sorted(by_host) or ["?"]

        for host in hosts:
            names = by_host.get(host, set())
            if task.get("status") in COVERAGE_ACTIVE_STATUSES:
                coverage = "running"
            elif not task.get("schedule"):
                coverage = "unscheduled"
            elif started is None:
                coverage = "never_run"
            elif not names:
                coverage = "no_results"
            elif AUTH_FAIL_NAME in names:
                coverage = "auth_failed"
            elif AUTH_OK_NAME not in names:
                coverage = "no_auth_evidence"
            elif (now - started).total_seconds() > COVERAGE_MAX_AGE_HOURS * 3600:
                coverage = "stale"
            else:
                coverage = "ok"
            rows.append(
                {
                    "task": name,
                    "host": host,
                    "status": task.get("status"),
                    "coverage": coverage,
                    "last_scan_start": task.get("last_report_scan_start"),
                    "results_in_last_run": sum(1 for r in run_results if (r.get("host") or "") == host),
                }
            )
    return rows


def put_coverage_state(base_url: str, rows: list[dict], *, auth_header: str, verify_tls: bool, checked_at: str) -> None:
    failing = [row for row in rows if row["coverage"] in COVERAGE_FAILING]
    doc = {
        "source": "greenbone-coverage",
        "checked_at": checked_at,
        "status": "ok" if not failing else "failing",
        "hosts_total": len(rows),
        "hosts_failing": len(failing),
        "failing": failing,
        "tasks": rows,
    }
    url = f"{base_url}/es-findings-sync-state/_doc/greenbone-coverage"
    req = urllib.request.Request(url, data=json.dumps(doc).encode("utf-8"), method="PUT")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15):  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            pass
    except urllib.error.HTTPError as exc:
        print(f"WARN: failed to write coverage state: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gvm-bridge-url", default=os.environ.get("GVM_BRIDGE_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", ""))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER", ""))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD", ""))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report counts, write nothing to OpenSearch.")
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("--elasticsearch-url/ELASTICSEARCH_URL", args.elasticsearch_url),
            ("--es-user/ES_FINDINGS_USER", args.es_user),
            ("--es-password/ES_FINDINGS_PASSWORD", args.es_password),
        )
        if not value
    ]
    if missing:
        print(f"ERROR: missing required value(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    es_base = args.elasticsearch_url.rstrip("/")
    es_auth = _basic_auth_header(args.es_user, args.es_password)

    started = _now_iso()
    try:
        raw_results = fetch_gvm_findings(args.gvm_bridge_url)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to fetch findings from gvm-bridge: {exc}", file=sys.stderr)
        return 1

    print(f"Fetched {len(raw_results)} raw GVM results (before Log-severity filtering).")
    stack_registry = load_stack_registry()
    docs = build_documents(raw_results, scan_time_fallback=started, stack_registry=stack_registry)
    print(f"{len(docs)} findings after dropping threat=Log.")

    indexed, errors = bulk_upsert(
        es_base, "gvm-findings", docs, auth_header=es_auth, verify_tls=not args.no_verify_tls, dry_run=args.dry_run
    )

    finished = _now_iso()
    status = "ok" if errors == 0 else "partial"
    if not args.dry_run:
        update_sync_state(
            es_base,
            auth_header=es_auth,
            verify_tls=not args.no_verify_tls,
            started=started,
            finished=finished,
            status=status,
            findings_indexed=indexed,
            errors=errors,
        )

    coverage_failing = 0
    try:
        credentialed_tasks = fetch_credentialed_tasks(args.gvm_bridge_url)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to fetch credentialed tasks from gvm-bridge: {exc}", file=sys.stderr)
        credentialed_tasks = None
    if credentialed_tasks is not None:
        rows = evaluate_coverage(credentialed_tasks, raw_results, now=datetime.now(timezone.utc))
        for row in rows:
            print(
                f"COVERAGE {row['coverage'].upper()}: {row['task']} {row['host']} (status={row['status']}, "
                f"last_scan_start={row['last_scan_start']}, results={row['results_in_last_run']})"
            )
        coverage_failing = sum(1 for row in rows if row["coverage"] in COVERAGE_FAILING)
        if not args.dry_run:
            put_coverage_state(
                es_base, rows, auth_header=es_auth, verify_tls=not args.no_verify_tls, checked_at=_now_iso()
            )

    print(
        f"Done — raw={len(raw_results)} findings_indexed={indexed} errors={errors} "
        f"coverage_failing={coverage_failing} dry_run={args.dry_run}"
    )
    if errors > 0 or credentialed_tasks is None:
        return 1
    # 3 = ingest succeeded but credentialed-scan coverage is failing; fails
    # the gvm-findings-ingest systemd unit so it shows up in
    # `systemctl --failed` (docs/gvm-coverage-cleanup/plan.md).
    return 3 if coverage_failing else 0


if __name__ == "__main__":
    sys.exit(main())
