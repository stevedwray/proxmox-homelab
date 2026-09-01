#!/usr/bin/env python3
"""Scheduled pull of Wazuh's current vulnerability state into OpenSearch.

See docs/threat-vuln-platform/plan.md's "Phase 2: Wazuh findings
ingestion" for the design, and its "CORRECTION 2026-09-01" note for why
this queries wazuh-states-vulnerabilities-* rather than wazuh-alerts-*.

**Real finding from the first live run against production wazuh-stack**:
querying wazuh-alerts-4.x-* for rule.groups:vulnerability-detector (the
design wazuh-analysis's own pipeline used, and this script's first
version copied) only captures Wazuh's alert *log* -- on this deployment
that turned out to be almost entirely "Solved" state-transition
notifications, not ongoing active state, and it silently missed 2 of 7
real agents (pve and wazuh.manager itself) whose vulnerability alerts
apparently never crossed whatever produced that specific alert stream.
Wazuh 4.14.7 (this deployment's version) keeps the actual current
vulnerability state -- what's *unsolved right now*, per agent -- in a
separate, newer-schema index family: wazuh-states-vulnerabilities-*.
Confirmed live: 2745 real documents covering all 7 real agents, using
top-level vulnerability.id/package.name/agent.id fields (Wazuh's ECS-like
"states" schema), not the classic dotted data.vulnerability.cve alert
schema wazuh-analysis's design assumed.

This index is a genuine current-state snapshot, not an append-only event
log -- Wazuh's own vulnerability-detector module removes a row once the
CVE is resolved (upgraded package, etc.), so mere presence in a full
pull IS "still active." That's why this script does a full pull every
run (same shape as harbor_findings_sync.py's full Harbor-catalog walk,
gvm_findings_sync.py's full current-Results pull) rather than an
incremental cursor -- there's no natural "last modified" field to cursor
on, and at ~2,700 documents a full pull is cheap. This also means
last_seen naturally advances every run a CVE is still present, and
naturally stops advancing (going stale) once Wazuh removes it -- the
same staleness-by-omission signal Harbor/GVM's own findings already
carry, no separate "status" field needed (the classic alerts schema's
Active/Solved status doesn't exist in this index at all: being present
IS "active").

Read-only against the Wazuh Indexer: only ever calls the _search API.
Read-write against OpenSearch: bulk-upserts finding documents and
updates one sync-state document (shared es-findings-sync-state index,
keyed "wazuh" -- same index harbor/gvm already write their own state
docs into). No cursor stored -- this is a full pull every run, not an
incremental one; the sync-state doc here is purely informational (last
run's timing/counts), matching harbor_findings_sync.py's own use of it.

Intentionally stdlib-only, matching every other sync script in this
repo's own reasoning (no Python venv convention on LXC hosts for jobs
like this).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

WAZUH_INDEX_PATTERN = "wazuh-states-vulnerabilities-*"
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


def _wazuh_search_after(base_url, auth_header, verify_tls, batch_size=BATCH_SIZE):
    """Full-index walk via search_after -- no query filter at all, this
    index already contains only current/unsolved vulnerabilities. Sorted
    purely on _doc (OpenSearch-compatible tiebreaker) since there's no
    meaningful business ordering needed for a full pull."""
    search_after = None
    ctx = _ssl_context(verify_tls)

    while True:
        body = {
            "size": batch_size,
            "query": {"match_all": {}},
            "sort": ["_doc"],
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


# Wazuh's agent.name IS the owning stack name for every currently
# enrolled infra agent (confirmed live, not guessed -- see
# project_wazuh_stack_status memory: 6 agents, 5 stacks + pve itself).
# A Wazuh agent only exists on a host that was deliberately enrolled onto
# real infrastructure, so in_production is unconditionally True here --
# unlike Harbor (mixed real/lab images) or GVM (pentest_target scans),
# there's no "lab" case for an enrolled agent. Zone needs a small lookup
# since agent_name alone doesn't carry it; an agent not in this map still
# gets stack=agent_name and in_production=True, just zone=None until
# added here -- never guessed. See docs/threat-vuln-platform/plan.md's
# UVM redesign phase (2026-09-01).
AGENT_ZONE_MAP = {
    "authentik-stack": "mgmt_seg",
    "proxy-stack": "edge_seg",
    "harbor-stack": "infra_seg",
    "technitium-stack": "mgmt_seg",
    "apt-cacher-stack": "infra_seg",
    "pve": None,  # the Proxmox hypervisor host itself, not a VLAN-zoned stack
}


def build_document(hit: dict) -> dict | None:
    src = hit.get("_source", {})
    vuln = src.get("vulnerability") or {}
    cve = vuln.get("id")
    if not cve:
        return None
    agent = src.get("agent") or {}
    package = src.get("package") or {}
    now = _now_iso()
    agent_name = agent.get("name")
    return {
        "source": "wazuh",
        "finding_id": cve,
        "severity_raw": vuln.get("severity"),
        "cvss_score": (vuln.get("score") or {}).get("base"),
        "package": package.get("name"),
        "package_version": package.get("version"),
        "description": (vuln.get("description") or "")[:2000] or None,
        "target": {
            "agent_id": agent.get("id"),
            "agent_name": agent_name,
            "stack": agent_name,
            "zone": AGENT_ZONE_MAP.get(agent_name),
            "in_production": True,
        },
        "scan_time": vuln.get("detected_at") or now,
        "last_seen": now,
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


def update_sync_state(base_url, auth_header, verify_tls, *, started, finished, status, docs_scanned, findings_indexed, errors, dry_run):
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

    docs_scanned = 0
    findings_indexed = 0
    errors = 0
    batch: list[dict] = []

    for hit in _wazuh_search_after(wazuh_base, wazuh_auth, not args.wazuh_no_verify_tls):
        docs_scanned += 1
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

    update_sync_state(
        es_base, es_auth, not args.es_no_verify_tls,
        started=started, finished=finished, status=status,
        docs_scanned=docs_scanned, findings_indexed=findings_indexed,
        errors=errors, dry_run=args.dry_run,
    )

    print(
        f"Done in {elapsed:.1f}s — docs_scanned={docs_scanned} findings_indexed={findings_indexed} "
        f"errors={errors} dry_run={args.dry_run}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
