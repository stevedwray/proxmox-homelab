#!/usr/bin/env python3
"""Scheduled pull of Wazuh vulnerability-detector findings into OpenSearch.

See docs/threat-vuln-platform/plan.md's "Phase 2: Wazuh findings
ingestion" for the design. Same overall shape as harbor_findings_sync.py
(stdlib-only, deterministic per-document _id, scripted-upsert putAll,
sync-state doc) but the source-side query pattern (incremental by
@timestamp with a lookback window, search_after pagination) is carried
over directly from wazuh-analysis's own wazuh_es_sync.py -- already
validated against real Wazuh 4.x alert data, not reinvented here.

Only ever queries rule.groups:vulnerability-detector -- the other four
alert types wazuh-analysis's README documents (auth failures, file
integrity, rootcheck, compliance/SCA) are explicitly out of scope for
this role; that's the *-events family, a separate later phase.

Read-only against the Wazuh Indexer: only ever calls the _search API.
Read-write against OpenSearch: bulk-upserts finding documents and
updates one sync-state document (shared es-findings-sync-state index,
keyed "wazuh" -- same index harbor/gvm already write their own state
docs into).

Intentionally stdlib-only, matching every other sync script in this
repo's own reasoning (no Python venv convention on LXC hosts for jobs
like this).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WAZUH_INDEX_PATTERN = "wazuh-alerts-4.x-*"
DEST_INDEX = "wazuh-findings"
BATCH_SIZE = 1000


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _basic_auth_header(user: str, password: str) -> str:
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {creds}"


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def parse_es_dt(s: str) -> datetime:
    """Parse ES/OpenSearch ISO timestamps (handles Z and long fractional
    seconds) -- lifted directly from wazuh-analysis's wazuh_es_sync.py,
    already proven against real Wazuh alert timestamp formats."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*\.\d{1,6})\d+([+-]\d{2}:\d{2})$", s)
    if m:
        s = m.group(1) + m.group(2)
    return datetime.fromisoformat(s)


def iso_minus_seconds(iso_ts: str, seconds: int) -> str:
    return (parse_es_dt(iso_ts) - timedelta(seconds=seconds)).isoformat()


def _wazuh_search_after(base_url, auth_header, verify_tls, start_cursor, batch_size=BATCH_SIZE):
    """Deterministic incremental pagination using search_after, filtered
    to vulnerability-detector alerts only, sorted by @timestamp then _doc
    (OpenSearch-compatible tiebreaker -- not _shard_doc)."""
    search_after = None
    ctx = _ssl_context(verify_tls)

    while True:
        body = {
            "size": batch_size,
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": start_cursor}}},
                        {"term": {"rule.groups": "vulnerability-detector"}},
                    ]
                }
            },
            "sort": [
                {"@timestamp": {"order": "asc", "missing": "_last"}},
                "_doc",
            ],
        }
        if search_after:
            body["search_after"] = search_after

        url = f"{base_url}/{WAZUH_INDEX_PATTERN}/_search"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", auth_header)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read())

        hits = result.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            yield h
        search_after = hits[-1].get("sort")
        if not search_after:
            break


def _extract_cvss_score(vuln: dict) -> float | None:
    cvss = vuln.get("cvss") or {}
    score = (cvss.get("cvss3") or {}).get("base_score")
    if score is None:
        score = (cvss.get("cvss2") or {}).get("base_score")
    return score


def build_document(hit: dict) -> dict | None:
    src = hit.get("_source", {})
    vuln = (src.get("data") or {}).get("vulnerability") or {}
    cve = vuln.get("cve")
    if not cve:
        return None
    agent = src.get("agent") or {}
    package = vuln.get("package") or {}
    return {
        "source": "wazuh",
        "finding_id": cve,
        "severity_raw": vuln.get("severity"),
        "cvss_score": _extract_cvss_score(vuln),
        "package": package.get("name"),
        "package_version": package.get("version"),
        "status": vuln.get("status"),
        "target": {
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
        },
        "scan_time": src.get("@timestamp"),
        "last_seen": _now_iso(),
    }


def doc_id(doc: dict) -> str:
    target = doc["target"]
    target_key = f"{target.get('agent_id')}/{doc.get('package')}"
    return f"{doc['source']}::{doc['finding_id']}::{target_key}"


def bulk_upsert(base_url, docs, auth_header, verify_tls, dry_run) -> tuple[int, int]:
    """Returns (indexed_count, error_count). Same scripted-upsert putAll
    pattern as harbor_findings_sync.py/gvm_findings_sync.py -- refreshes
    every current-scan-observed field on already-indexed documents,
    first_seen stays sticky (only set if still null)."""
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
        lines.append(json.dumps({"update": {"_index": DEST_INDEX, "_id": _id}}))
        lines.append(
            json.dumps(
                {
                    "script": {
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

    req = urllib.request.Request(f"{base_url}/_bulk", data=body, method="POST")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/x-ndjson")
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"ERROR: bulk index failed ({exc.code}): {exc.read()[:500]}", file=sys.stderr)
        return 0, len(docs)

    error_count = 0
    if result.get("errors"):
        for item in result.get("items", []):
            if item.get("update", {}).get("status", 200) >= 300:
                error_count += 1
    return len(docs) - error_count, error_count


def get_sync_state(base_url, auth_header, verify_tls) -> dict | None:
    url = f"{base_url}/es-findings-sync-state/_doc/wazuh"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=15) as resp:
            return json.loads(resp.read()).get("_source")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def update_sync_state(base_url, auth_header, verify_tls, *, started, finished, status, docs_scanned, findings_indexed, errors, last_cursor, dry_run):
    if dry_run:
        return
    body = json.dumps(
        {
            "source": "wazuh",
            "last_run_started": started,
            "last_run_finished": finished,
            "last_run_status": status,
            "artifacts_scanned": docs_scanned,
            "findings_indexed": findings_indexed,
            "errors": errors,
            "last_cursor": last_cursor,
        }
    ).encode()
    req = urllib.request.Request(f"{base_url}/es-findings-sync-state/_doc/wazuh", data=body, method="PUT")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=15):
            pass
    except urllib.error.HTTPError as exc:
        print(f"WARN: failed to update sync-state doc: {exc.code} {exc.read()[:200]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wazuh-url", default=os.environ.get("WAZUH_URL", ""))
    parser.add_argument("--wazuh-user", default=os.environ.get("WAZUH_USER", ""))
    parser.add_argument("--wazuh-password", default=os.environ.get("WAZUH_PASSWORD", ""))
    parser.add_argument("--wazuh-no-verify-tls", action="store_true", default=os.environ.get("WAZUH_NO_VERIFY_TLS") == "1")
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", ""))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER", ""))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD", ""))
    parser.add_argument("--es-no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--lookback-seconds", type=int, default=int(os.environ.get("SYNC_LOOKBACK_SECONDS", "600")))
    parser.add_argument("--dry-run", action="store_true", help="Query Wazuh and report counts, write nothing to OpenSearch.")
    args = parser.parse_args()

    missing = [
        name
        for name, value in [
            ("--wazuh-url/WAZUH_URL", args.wazuh_url),
            ("--wazuh-user/WAZUH_USER", args.wazuh_user),
            ("--wazuh-password/WAZUH_PASSWORD", args.wazuh_password),
            ("--elasticsearch-url/ELASTICSEARCH_URL", args.elasticsearch_url),
            ("--es-user/ES_FINDINGS_USER", args.es_user),
            ("--es-password/ES_FINDINGS_PASSWORD", args.es_password),
        ]
        if not value
    ]
    if missing:
        print(f"ERROR: missing required settings: {', '.join(missing)}", file=sys.stderr)
        return 2

    wazuh_base = args.wazuh_url.rstrip("/")
    es_base = args.elasticsearch_url.rstrip("/")
    wazuh_auth = _basic_auth_header(args.wazuh_user, args.wazuh_password)
    es_auth = _basic_auth_header(args.es_user, args.es_password)

    started = _now_iso()
    started_monotonic = time.monotonic()

    state = get_sync_state(es_base, es_auth, not args.es_no_verify_tls)
    last_cursor = state.get("last_cursor") if state else None
    if last_cursor:
        start_cursor = iso_minus_seconds(last_cursor, args.lookback_seconds)
        print(f"Incremental sync from {start_cursor} (lookback {args.lookback_seconds}s)")
    else:
        start_cursor = "2025-01-01T00:00:00Z"
        print("Initial full sync (no prior sync-state doc found)")

    docs_scanned = 0
    findings_indexed = 0
    errors = 0
    max_cursor_seen = last_cursor
    batch: list[dict] = []

    for hit in _wazuh_search_after(wazuh_base, wazuh_auth, not args.wazuh_no_verify_tls, start_cursor):
        docs_scanned += 1
        ts = hit.get("_source", {}).get("@timestamp")
        if ts and (max_cursor_seen is None or parse_es_dt(ts) > parse_es_dt(max_cursor_seen)):
            max_cursor_seen = ts

        doc = build_document(hit)
        if doc is None:
            continue
        batch.append(doc)

        if len(batch) >= BATCH_SIZE:
            indexed, bulk_errors = bulk_upsert(es_base, batch, es_auth, not args.es_no_verify_tls, args.dry_run)
            findings_indexed += indexed
            errors += bulk_errors
            batch = []

    if batch:
        indexed, bulk_errors = bulk_upsert(es_base, batch, es_auth, not args.es_no_verify_tls, args.dry_run)
        findings_indexed += indexed
        errors += bulk_errors

    finished = _now_iso()
    elapsed = time.monotonic() - started_monotonic
    status = "success" if errors == 0 else "completed_with_errors"

    # Never advance the cursor on a run that found nothing at all --
    # same "never advance cursor on a 0-doc run" principle already
    # validated in security-analysis's secpipe_core design (see this
    # doc's "Prior art" section above) -- avoids silently skipping a
    # window if Wazuh's indexer was briefly unreachable mid-query.
    new_cursor = max_cursor_seen if docs_scanned > 0 else last_cursor
    update_sync_state(
        es_base, es_auth, not args.es_no_verify_tls,
        started=started, finished=finished, status=status,
        docs_scanned=docs_scanned, findings_indexed=findings_indexed,
        errors=errors, last_cursor=new_cursor, dry_run=args.dry_run,
    )

    print(
        f"Done in {elapsed:.1f}s — docs_scanned={docs_scanned} findings_indexed={findings_indexed} "
        f"errors={errors} dry_run={args.dry_run}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
