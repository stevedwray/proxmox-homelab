#!/usr/bin/env python3
"""Incremental sync of T-Pot honeypot events into OpenSearch.

See docs/tpot-honeypot/plan.md ("Phase 4 -- findings ingestion") and
docs/threat-vuln-platform/plan.md's `*-events` index family for the
design. T-Pot is a standalone Raspberry Pi, not a Proxmox guest, so
unlike wazuh_findings_ingest/gvm_findings_ingest (which run ON their own
source stack), this runs on secpipe-stack and reaches T-Pot's internal
Elasticsearch over an SSH tunnel to a materialized key file -- the
tunnel-based fetch approach here is carried over from the original,
already-proven prototype (~/git/tpotce-analysis/tpot_es_sync.py), just
rewritten stdlib-only to match every other sync script in this repo
(no `requests`/`elasticsearch` pip packages -- no Python venv convention
for jobs like this on LXC hosts).

T-Pot's `logstash-*` indices are a genuine append-only event log (one
index per calendar day on the T-Pot side already), so this is a real
incremental cursor sync, not a full pull like the `*-findings` roles
(there's no "current state" to snapshot here -- old events don't stop
being true).

Deliberate design choice vs. the tpotce-analysis prototype: that script
wrote one destination index per (honeypot, day) -- dozens of tiny daily
indices. This writes one `tpot-events-YYYY.MM.DD` index per day across
every honeypot, with `honeypot` as a plain field, matching how
`wazuh-events`/`so-alerts` are expected to be shaped per
docs/threat-vuln-platform/plan.md's `*-events` table -- one index
pattern per source, not one per sub-category.

Retention/ILM for these indices is a separate, still-open decision (see
docs/tpot-honeypot/plan.md "Still open") -- this script only writes;
it does not define a rollover/delete policy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

STATE_INDEX = "tpot-events-sync-state"
STATE_DOC_ID = "tpot"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_es_dt(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*\.\d{1,6})\d+([+-]\d{2}:\d{2})$", s)
    if m:
        s = m.group(1) + m.group(2)
    return datetime.fromisoformat(s)


def iso_minus_seconds(iso_ts: str, seconds: int) -> str:
    return (parse_es_dt(iso_ts) - timedelta(seconds=seconds)).isoformat()


# ----------------------------
# SSH tunnel (stdlib subprocess -- same technique the prototype used)
# ----------------------------


def pick_free_local_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_port(host: str, port: int, timeout_s: float = 8.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as e:
            last_err = e
            time.sleep(0.1)
    raise TimeoutError(f"Port not reachable: {host}:{port} (last_err={last_err})")


class SSHTunnel:
    def __init__(self, ssh_host: str, ssh_port: int, ssh_user: str, ssh_key_path: str, local_port: int, remote_port: int) -> None:
        self.cmd = [
            "ssh",
            "-N",
            "-i", ssh_key_path,
            "-p", str(ssh_port),
            "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            f"{ssh_user}@{ssh_host}",
        ]
        self.local_port = local_port
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "SSHTunnel":
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)  # nosec B603 B607 -- fixed argv, no shell, internal-only ssh binary
        try:
            wait_port("127.0.0.1", self.local_port, timeout_s=10.0)
        except Exception:
            err = ""
            if self.proc and self.proc.stderr:
                try:
                    err = self.proc.stderr.read()
                except Exception:
                    pass
            self.__exit__(None, None, None)
            raise RuntimeError(f"SSH tunnel to T-Pot failed. stderr:\n{err}") from None
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)


# ----------------------------
# T-Pot source (plain HTTP, tunnel-local only -- matches how T-Pot's
# internal Elasticsearch is bound on the honeypot itself: 127.0.0.1:9200,
# no TLS, see docs/tpot-honeypot/plan.md's access table)
# ----------------------------


def tpot_get(base: str, path: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{base}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 -- internal tunnel-local endpoint, fixed loopback URL
        return json.loads(resp.read())


def tpot_post(base: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 -- internal tunnel-local endpoint, fixed loopback URL
        return json.loads(resp.read())


def sanitize_honeypot(src: dict[str, Any]) -> str:
    hp = str(src.get("type") or "unknown").strip().lower()
    hp = re.sub(r"[^a-z0-9_-]+", "-", hp)
    return hp or "unknown"


def doc_dt(src: dict[str, Any]) -> datetime:
    ts = src.get("@timestamp")
    if not ts:
        return datetime.now(timezone.utc)
    try:
        return parse_es_dt(ts).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


# ----------------------------
# OpenSearch destination
# ----------------------------


def _auth_header(user: str, password: str) -> str:
    token = b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_sync_state(es_url: str, auth_header: str, verify_tls: bool) -> dict[str, Any] | None:
    req = urllib.request.Request(f"{es_url}/{STATE_INDEX}/_doc/{STATE_DOC_ID}", method="GET")
    req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=15) as resp:  # nosec B310 -- internal operator-configured API endpoint
            return json.loads(resp.read()).get("_source")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def write_sync_state(es_url: str, auth_header: str, verify_tls: bool, doc: dict[str, Any]) -> None:
    req = urllib.request.Request(f"{es_url}/{STATE_INDEX}/_doc/{STATE_DOC_ID}", data=json.dumps(doc).encode("utf-8"), method="PUT")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=15):  # nosec B310 -- internal operator-configured API endpoint
        pass


def bulk_index(es_url: str, auth_header: str, verify_tls: bool, actions: list[tuple[str, str, dict[str, Any]]]) -> tuple[int, int]:
    if not actions:
        return 0, 0
    lines = []
    for index, doc_id, source in actions:
        lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}))
        lines.append(json.dumps(source))
    body = ("\n".join(lines) + "\n").encode("utf-8")

    req = urllib.request.Request(f"{es_url}/_bulk", data=body, method="POST")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/x-ndjson")
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=120) as resp:  # nosec B310 -- internal operator-configured API endpoint
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"ERROR: bulk index failed ({exc.code}): {exc.read()[:500]}", file=sys.stderr)
        return 0, len(actions)

    error_count = 0
    if result.get("errors"):
        for item in result.get("items", []):
            index_result = item.get("index", {})
            if index_result.get("status", 200) >= 300:
                error_count += 1
    return len(actions) - error_count, error_count


def sync_once(
    *,
    tpot_base: str,
    source_pattern: str,
    exclude_indices: set[str],
    es_url: str,
    es_auth_header: str,
    es_verify_tls: bool,
    dest_prefix: str,
    cursor_field: str,
    lookback_seconds: int,
    batch_size: int,
    max_docs: int,
    dry_run: bool,
) -> tuple[int, int, int, str | None]:
    """Returns (processed, indexed, errors, max_cursor_seen)."""
    state = get_sync_state(es_url, es_auth_header, es_verify_tls) or {}
    last_cursor = state.get("last_cursor")

    if last_cursor:
        start_cursor = iso_minus_seconds(last_cursor, lookback_seconds)
        print(f"Incremental sync from {start_cursor} (lookback {lookback_seconds}s)")
    else:
        start_cursor = os.environ.get("TPOT_SYNC_START", "now-1d")
        print(f"No prior state; starting from {start_cursor}")

    query = {
        "size": batch_size,
        "query": {
            "bool": {
                "must": [
                    {"exists": {"field": cursor_field}},
                    {"range": {cursor_field: {"gte": start_cursor}}},
                ],
                "must_not": [{"terms": {"_index": sorted(exclude_indices)}}] if exclude_indices else [],
            }
        },
        "sort": [{cursor_field: {"order": "asc"}}],
    }

    safe_index = quote(source_pattern, safe=",._-")
    resp = tpot_post(tpot_base, f"/{safe_index}/_search?scroll=5m", query)
    scroll_id = resp.get("_scroll_id")

    processed = 0
    indexed = 0
    errors = 0
    max_dt: datetime | None = None
    actions: list[tuple[str, str, dict[str, Any]]] = []

    try:
        while True:
            hits = resp.get("hits", {}).get("hits", [])
            if not hits:
                break

            for h in hits:
                src_index = h.get("_index", "")
                if src_index in exclude_indices:
                    continue
                src = h.get("_source", {}) or {}
                if not src.get("@timestamp"):
                    continue

                dt = doc_dt(src)
                if max_dt is None or dt > max_dt:
                    max_dt = dt

                if not dry_run:
                    dest_index = f"{dest_prefix}-{dt.strftime('%Y.%m.%d')}"
                    doc = dict(src)
                    doc["honeypot"] = sanitize_honeypot(src)
                    doc["source"] = "tpot"
                    actions.append((dest_index, f"{src_index}::{h.get('_id', '')}", doc))

                processed += 1
                if max_docs and processed >= max_docs:
                    break

            if not dry_run and len(actions) >= batch_size:
                ok, failed = bulk_index(es_url, es_auth_header, es_verify_tls, actions)
                indexed += ok
                errors += failed
                actions = []

            if max_docs and processed >= max_docs:
                break
            if not scroll_id:
                break

            resp = tpot_post(tpot_base, "/_search/scroll", {"scroll": "5m", "scroll_id": scroll_id})
            scroll_id = resp.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            try:
                req = urllib.request.Request(f"{tpot_base}/_search/scroll", data=json.dumps({"scroll_id": [scroll_id]}).encode("utf-8"), method="DELETE")
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=15)  # nosec B310 -- internal tunnel-local endpoint
            except Exception:
                pass

    if not dry_run and actions:
        ok, failed = bulk_index(es_url, es_auth_header, es_verify_tls, actions)
        indexed += ok
        errors += failed

    max_cursor_seen = max_dt.astimezone(timezone.utc).isoformat() if max_dt is not None else None
    return processed, indexed, errors, max_cursor_seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tpot-ssh-host", default=os.environ.get("TPOT_SSH_HOST", ""))
    parser.add_argument("--tpot-ssh-port", type=int, default=int(os.environ.get("TPOT_SSH_PORT", "64295")))
    parser.add_argument("--tpot-ssh-user", default=os.environ.get("TPOT_SSH_USER", ""))
    parser.add_argument("--tpot-ssh-key-path", default=os.environ.get("TPOT_SSH_KEY_PATH", ""))
    parser.add_argument("--tpot-remote-es-port", type=int, default=int(os.environ.get("TPOT_REMOTE_ES_PORT", "64298")))
    parser.add_argument("--source-index", default=os.environ.get("TPOT_SOURCE_INDEX_PATTERN", "logstash-20*"))
    parser.add_argument("--exclude-indices", default=os.environ.get("TPOT_EXCLUDE_INDICES", "logstash-1970.01.01"))
    parser.add_argument("--cursor-field", default=os.environ.get("TPOT_CURSOR_FIELD", "@timestamp"))
    parser.add_argument("--lookback-seconds", type=int, default=int(os.environ.get("TPOT_LOOKBACK_SECONDS", "600")))
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("TPOT_BATCH_SIZE", "2000")))
    parser.add_argument("--max-docs", type=int, default=int(os.environ.get("TPOT_MAX_DOCS", "0")))
    parser.add_argument("--dest-prefix", default=os.environ.get("TPOT_DEST_PREFIX", "tpot-events"))
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", ""))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER", ""))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD", ""))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report counts, write nothing to OpenSearch, do not advance cursor.")
    args = parser.parse_args()

    missing = [
        name
        for name, val in [
            ("--tpot-ssh-host/TPOT_SSH_HOST", args.tpot_ssh_host),
            ("--tpot-ssh-user/TPOT_SSH_USER", args.tpot_ssh_user),
            ("--tpot-ssh-key-path/TPOT_SSH_KEY_PATH", args.tpot_ssh_key_path),
            ("--elasticsearch-url/ELASTICSEARCH_URL", args.elasticsearch_url),
            ("--es-user/ES_FINDINGS_USER", args.es_user),
            ("--es-password/ES_FINDINGS_PASSWORD", args.es_password),
        ]
        if not val
    ]
    if missing:
        print(f"ERROR: missing required values: {', '.join(missing)}", file=sys.stderr)
        return 2

    if not Path(args.tpot_ssh_key_path).is_file():
        print(f"ERROR: SSH key not found at {args.tpot_ssh_key_path}", file=sys.stderr)
        return 2

    exclude = {x.strip() for x in args.exclude_indices.split(",") if x.strip()}
    es_auth_header = _auth_header(args.es_user, args.es_password)
    started = _now_iso()

    local_port = pick_free_local_port()
    print(f"Opening SSH tunnel to T-Pot ({args.tpot_ssh_host}:{args.tpot_ssh_port}) -> local:{local_port}")
    with SSHTunnel(args.tpot_ssh_host, args.tpot_ssh_port, args.tpot_ssh_user, args.tpot_ssh_key_path, local_port, args.tpot_remote_es_port):
        tpot_base = f"http://127.0.0.1:{local_port}"
        info = tpot_get(tpot_base, "/")
        ver = str(info.get("version", {}).get("number", ""))
        cluster_name = info.get("cluster_name", "")
        # Sanity-checks the tunnel landed on T-Pot's own ES, not some other
        # service entirely -- checks identity (cluster_name), not a specific
        # major version. Found live 2026-09-30: this instance's bundled ES
        # is 9.3.5 under T-Pot's own "24.04.1" release tag, not the 8.x the
        # original tpotce-analysis prototype (and this script's first
        # version, copying it) assumed -- a real version doesn't mean a
        # wrong target, and classic Scroll stays functional in ES 9.x.
        if cluster_name != "tpotcluster" or not ver:
            print(f"ERROR: tunnel did not land on T-Pot's Elasticsearch, got: {info}", file=sys.stderr)
            return 3
        print(f"[OK] T-Pot ES via tunnel: {cluster_name} (v{ver})")

        processed, indexed, errors, max_cursor = sync_once(
            tpot_base=tpot_base,
            source_pattern=args.source_index,
            exclude_indices=exclude,
            es_url=args.elasticsearch_url.rstrip("/"),
            es_auth_header=es_auth_header,
            es_verify_tls=not args.no_verify_tls,
            dest_prefix=args.dest_prefix,
            cursor_field=args.cursor_field,
            lookback_seconds=args.lookback_seconds,
            batch_size=args.batch_size,
            max_docs=args.max_docs,
            dry_run=args.dry_run,
        )

    finished = _now_iso()
    print(f"processed={processed} indexed={indexed} errors={errors} dry_run={args.dry_run}")

    if args.dry_run:
        print("[DRY-RUN] no writes, no state update")
        return 0

    if processed > 0 and max_cursor:
        write_sync_state(
            args.elasticsearch_url.rstrip("/"),
            es_auth_header,
            not args.no_verify_tls,
            {
                "source": "tpot",
                "started": started,
                "finished": finished,
                "last_cursor": max_cursor,
                "last_run_processed": processed,
                "last_run_indexed": indexed,
                "last_run_errors": errors,
            },
        )
        print(f"[STATE] updated last_cursor={max_cursor}")
    else:
        print("[STATE] not updating cursor (no documents processed)")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
