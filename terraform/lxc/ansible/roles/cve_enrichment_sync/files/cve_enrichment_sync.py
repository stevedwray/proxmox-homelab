#!/usr/bin/env python3
"""CVE correlation/enrichment sync — see docs/threat-vuln-platform/plan.md.

Reads distinct CVE IDs (+ instance counts) from harbor-findings,
gvm-findings, and wazuh-findings, enriches each not-yet-enriched CVE via
cve-mcp-server's triage_cve tool (CVSS/EPSS/KEV/PoC + a composite risk
score), synthesizes a short risk narrative via an LLM, and:

  1. Upserts one document per CVE into unified-cve-exposure.
  2. Writes severity_assessed/assessed_reason/assessed_by/assessed_at
     back onto every originating finding document via _update_by_query --
     NOT a full scripted upsert like harbor_findings_sync.py/
     gvm_findings_sync.py use. Those documents already exist (created by
     the respective sync script); this only ever touches the four
     assessment fields, never anything else.

LLM provider is Anthropic or OpenAI for now, not the local Ollama runtime
this project otherwise standardizes on -- the local LLM is occupied with
benchmarking work as of 2026-08-18. This is a deliberate, temporary
substitution (operator instruction), not a design decision; --llm-provider
is a plain switch so moving back to Ollama later is a config change, not
a rewrite.

Already-enriched CVEs are skipped by default -- each enrichment fans out
to NVD/EPSS/KEV/GitHub via cve-mcp-server plus an LLM call, not free to
repeat unconditionally on every run. Pass --force-refresh to re-enrich
everything (EPSS/KEV status does change over time; a real re-check
interval policy is a documented open item in plan.md, not decided yet).

Phase 1 scope (see plan.md): harbor-findings + gvm-findings. Phase 2
(2026-09-01) added wazuh-findings as a third source -- CVE-only
vulnerability-detector findings, not Wazuh's general alert stream. No
security-onion/tpot sources yet.
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
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _es_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    auth_header: str,
    verify_tls: bool,
    timeout: int = 30,
) -> tuple[int, dict | None]:
    url = f"{base_url}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", auth_header)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw.decode(errors="replace")[:500]}


def fetch_cve_instances(
    es_url: str, index: str, cve_field: str, *, auth_header: str, verify_tls: bool
) -> dict[str, int]:
    """Terms-aggregate distinct CVE values + doc counts from one findings
    index. Works unchanged whether the field is a single keyword
    (harbor-findings.finding_id) or a keyword array (gvm-findings.cve) --
    a terms agg on an array field buckets each value independently, which
    is the correct behaviour here (a finding with 2 CVEs should count
    toward both)."""
    body = {"size": 0, "aggs": {"cves": {"terms": {"field": cve_field, "size": 10000}}}}
    status, result = _es_request(
        es_url, f"/{index}/_search", method="POST", body=body,
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status != 200 or not result:
        print(f"WARN: failed to aggregate {index} ({status}): {result}", file=sys.stderr)
        return {}
    buckets = result.get("aggregations", {}).get("cves", {}).get("buckets", [])
    return {b["key"]: b["doc_count"] for b in buckets if b.get("key")}


def get_existing_enrichment(
    es_url: str, cve_id: str, *, auth_header: str, verify_tls: bool
) -> dict | None:
    status, result = _es_request(
        es_url, f"/unified-cve-exposure/_doc/{urllib.parse.quote(cve_id, safe='')}",
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status == 200 and result and result.get("found"):
        return result.get("_source")
    return None


# --- cve-mcp-server ------------------------------------------------------

_TRIAGE_PATTERNS = {
    "risk_score": re.compile(r"RISK SCORE:\s*([\d.]+)/100\s*\(([A-Z]+)\)"),
    "urgency": re.compile(r"Urgency:\s*(.+)"),
    "cvss": re.compile(r"CVSS:\s*([\d.]+)\s+([A-Z]+)"),
    "vector": re.compile(r"Vector:\s*(\S+)"),
    "epss": re.compile(r"EPSS:\s*([\d.]+)%\s*\(percentile\s*([\d.]+)"),
    "kev": re.compile(r"KEV:\s*(YES|NO)"),
    "poc": re.compile(r"PoC:\s*(\S+)"),
}


def parse_triage_text(text: str) -> dict:
    """Regex-parse cve-mcp-server's triage_cve plain-text output into
    structured fields -- confirmed live during planning that this tool
    has no JSON output mode, only formatted text. Deliberately tolerant:
    missing fields stay None rather than raising, since upstream sources
    can legitimately lack data for a given CVE (e.g. no EPSS score yet
    for a very recently published one)."""
    out: dict = {
        "risk_score": None, "risk_band": None, "risk_urgency": None,
        "cvss_score": None, "cvss_severity": None, "cvss_vector": None,
        "epss_score": None, "epss_percentile": None,
        "kev_listed": None, "poc_available": None,
    }
    m = _TRIAGE_PATTERNS["risk_score"].search(text)
    if m:
        out["risk_score"] = float(m.group(1))
        out["risk_band"] = m.group(2)
    m = _TRIAGE_PATTERNS["urgency"].search(text)
    if m:
        out["risk_urgency"] = m.group(1).strip()
    m = _TRIAGE_PATTERNS["cvss"].search(text)
    if m:
        out["cvss_score"] = float(m.group(1))
        out["cvss_severity"] = m.group(2)
    m = _TRIAGE_PATTERNS["vector"].search(text)
    if m:
        out["cvss_vector"] = m.group(1)
    m = _TRIAGE_PATTERNS["epss"].search(text)
    if m:
        out["epss_score"] = float(m.group(1)) / 100.0
        out["epss_percentile"] = float(m.group(2))
    m = _TRIAGE_PATTERNS["kev"].search(text)
    if m:
        out["kev_listed"] = m.group(1) == "YES"
    m = _TRIAGE_PATTERNS["poc"].search(text)
    if m:
        out["poc_available"] = m.group(1).upper() != "NONE"
    return out


def call_cve_mcp_triage(mcp_url: str, cve_id: str, *, depth: str = "standard", timeout: int = 30) -> str:
    """POST a stateless MCP tools/call to cve-mcp-server. No session
    handshake required -- confirmed live both here and in
    docs/pentagi-stack/cve-mcp-integration-plan.md: a fresh tools/call
    with no prior initialize still works. Response is SSE-framed
    ("event: message\\ndata: {...}\\n\\n"), confirmed live too."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "triage_cve", "arguments": {"cve_id": cve_id, "depth": depth}},
    }
    req = urllib.request.Request(
        mcp_url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    for line in raw.splitlines():
        if line.startswith("data:"):
            payload = json.loads(line[len("data:"):].strip())
            result = payload.get("result", {})
            if result.get("isError"):
                raise RuntimeError(f"triage_cve returned an error for {cve_id}: {result}")
            content = result.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0]["text"]
    raise RuntimeError(f"unexpected cve-mcp-server response for {cve_id}: {raw[:300]}")


# --- LLM narrative (Anthropic/OpenAI -- temporary provider, see module
# docstring) -------------------------------------------------------------


def synthesize_narrative(
    provider: str, api_key: str, cve_id: str, triage_text: str, sources: list[dict], total_instances: int
) -> str:
    prompt = (
        f"You are a security analyst. Given this automated CVE triage for {cve_id}, "
        f"which appears {total_instances} time(s) across these sources in our environment: "
        f"{json.dumps(sources)}.\n\n{triage_text}\n\n"
        "Write a 2-4 sentence prioritized risk note for a vulnerability management "
        "dashboard. Be concrete about urgency and why, not generic advice."
    )
    if provider == "anthropic":
        return _call_anthropic(api_key, prompt)
    if provider == "openai":
        return _call_openai(api_key, prompt)
    raise ValueError(f"unknown LLM provider: {provider}")


def _call_anthropic(api_key: str, prompt: str, *, model: str = "claude-haiku-4-5-20251001", timeout: int = 30) -> str:
    body = {"model": model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    return "".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text").strip()


def _call_openai(api_key: str, prompt: str, *, model: str = "gpt-4o-mini", timeout: int = 30) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 300}
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"].strip()


# --- write-back ------------------------------------------------------------


def writeback_findings(
    es_url: str, index: str, field: str, cve_id: str, assessment: dict, *, auth_header: str, verify_tls: bool, dry_run: bool
) -> int:
    """_update_by_query, not a scripted upsert -- these documents already
    exist (created by harbor_findings_sync.py/gvm_findings_sync.py). This
    only ever sets the four assessment fields, deliberately never
    anything else those scripts own."""
    if dry_run:
        return 0
    body = {
        "query": {"term": {field: cve_id}},
        "script": {
            "source": (
                "ctx._source.severity_assessed = params.severity_assessed; "
                "ctx._source.assessed_reason = params.assessed_reason; "
                "ctx._source.assessed_by = params.assessed_by; "
                "ctx._source.assessed_at = params.assessed_at;"
            ),
            "lang": "painless",
            "params": assessment,
        },
    }
    status, result = _es_request(
        es_url, f"/{index}/_update_by_query", method="POST", body=body,
        auth_header=auth_header, verify_tls=verify_tls, timeout=60,
    )
    if status != 200 or not result:
        print(f"WARN: writeback failed for {cve_id} on {index} ({status}): {result}", file=sys.stderr)
        return 0
    return result.get("updated", 0)


def refresh_exposure_sources(
    es_url: str, cve_id: str, sources_list: list[dict], total_instances: int, *, auth_header: str, verify_tls: bool, dry_run: bool
) -> bool:
    """Cheap update for an already-enriched CVE whose sources/counts have
    changed (e.g. a newly-added findings source, like wazuh-findings
    joining harbor-findings/gvm-findings on 2026-09-01) -- updates only
    sources/total_instances via a partial _update, with NO triage_cve or
    LLM call. This is what backfills existing enrichments onto a newly
    added source without re-running the expensive full enrichment for
    every already-enriched CVE. Returns True if updated."""
    if dry_run:
        return False
    status, result = _es_request(
        es_url, f"/unified-cve-exposure/_update/{urllib.parse.quote(cve_id, safe='')}",
        method="POST",
        body={"doc": {"sources": sources_list, "total_instances": total_instances}},
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status != 200:
        print(f"WARN: source refresh failed for {cve_id} ({status}): {result}", file=sys.stderr)
        return False
    return True


def upsert_exposure_doc(
    es_url: str, cve_id: str, doc: dict, *, auth_header: str, verify_tls: bool, dry_run: bool
) -> None:
    if dry_run:
        return
    status, result = _es_request(
        es_url, f"/unified-cve-exposure/_doc/{urllib.parse.quote(cve_id, safe='')}",
        method="PUT", body=doc, auth_header=auth_header, verify_tls=verify_tls,
    )
    if status not in (200, 201):
        print(f"ERROR: failed to upsert {cve_id}: {status} {result}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", "https://127.0.0.1:9200"))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER"))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD"))
    parser.add_argument(
        "--no-verify-tls", action="store_true",
        default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1",
    )
    parser.add_argument("--cve-mcp-url", default=os.environ.get("CVE_MCP_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument(
        "--llm-provider", default=os.environ.get("LLM_PROVIDER", "anthropic"),
        choices=["anthropic", "openai", "none"],
    )
    parser.add_argument("--anthropic-api-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    parser.add_argument("--openai-api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--triage-depth", default=os.environ.get("TRIAGE_DEPTH", "standard"))
    parser.add_argument(
        "--max-cves", type=int, default=int(os.environ.get("MAX_CVES", "0")) or None,
        help="cap CVEs enriched per run (0/unset = no cap)",
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.es_user or not args.es_password:
        print("ERROR: ES_FINDINGS_USER/ES_FINDINGS_PASSWORD (or --es-user/--es-password) are required", file=sys.stderr)
        return 1

    auth_header = "Basic " + base64.b64encode(f"{args.es_user}:{args.es_password}".encode()).decode()
    verify_tls = not args.no_verify_tls

    # Phase 1: harbor + greenbone. Phase 2 (2026-09-01) added wazuh as a
    # third, identically-shaped source (see module docstring / plan.md) --
    # fetch_cve_instances()/writeback_findings() are both driven off this
    # one list, so adding wazuh-findings here is the only change needed
    # to cover both aggregation and write-back for the new source.
    sources = [
        {"source": "harbor", "index": "harbor-findings", "field": "finding_id"},
        {"source": "greenbone", "index": "gvm-findings", "field": "cve"},
        {"source": "wazuh", "index": "wazuh-findings", "field": "finding_id"},
    ]

    cve_map: dict[str, dict] = {}
    for src in sources:
        counts = fetch_cve_instances(
            args.elasticsearch_url, src["index"], src["field"],
            auth_header=auth_header, verify_tls=verify_tls,
        )
        for cve_id, count in counts.items():
            entry = cve_map.setdefault(cve_id, {"sources": [], "total_instances": 0})
            entry["sources"].append({"source": src["source"], "finding_id": cve_id, "count": count})
            entry["total_instances"] += count

    print(f"Found {len(cve_map)} distinct CVEs across {len(sources)} findings indices.")

    llm_api_key = args.anthropic_api_key if args.llm_provider == "anthropic" else args.openai_api_key
    if args.llm_provider != "none" and not llm_api_key:
        print(f"WARN: --llm-provider={args.llm_provider} but no API key set -- narratives will be skipped.", file=sys.stderr)

    enriched = 0
    skipped_fresh = 0
    sources_refreshed = 0
    errors = 0
    processed = 0

    for cve_id, entry in sorted(cve_map.items(), key=lambda kv: -kv[1]["total_instances"]):
        if args.max_cves and processed >= args.max_cves:
            break
        processed += 1

        if not args.force_refresh:
            existing = get_existing_enrichment(
                args.elasticsearch_url, cve_id, auth_header=auth_header, verify_tls=verify_tls
            )
            if existing is not None:
                # Cheap backfill path, no triage_cve/LLM call: an
                # already-enriched CVE whose real source set or instance
                # count has drifted (the exact case a newly added
                # findings source like wazuh-findings hits for every CVE
                # it shares with harbor/gvm) gets its sources/
                # total_instances refreshed directly, and the existing
                # (not re-triaged) assessment gets written back onto
                # whichever finding indices now carry this CVE -- so a
                # new source doesn't have to wait for a full
                # --force-refresh sweep to show up in the dashboard.
                existing_source_names = {s.get("source") for s in existing.get("sources", [])}
                new_source_names = {s["source"] for s in entry["sources"]}
                if (
                    new_source_names != existing_source_names
                    or existing.get("total_instances") != entry["total_instances"]
                ):
                    if refresh_exposure_sources(
                        args.elasticsearch_url, cve_id, entry["sources"], entry["total_instances"],
                        auth_header=auth_header, verify_tls=verify_tls, dry_run=args.dry_run,
                    ):
                        sources_refreshed += 1
                        assessment = {
                            "severity_assessed": existing.get("risk_band"),
                            "assessed_reason": (existing.get("llm_narrative") or existing.get("triage_raw_text") or "")[:2000],
                            "assessed_by": "cve_enrichment_sync",
                            "assessed_at": _now_iso(),
                        }
                        for src in sources:
                            if any(s["source"] == src["source"] for s in entry["sources"]):
                                writeback_findings(
                                    args.elasticsearch_url, src["index"], src["field"], cve_id, assessment,
                                    auth_header=auth_header, verify_tls=verify_tls, dry_run=args.dry_run,
                                )
                skipped_fresh += 1
                continue

        try:
            triage_text = call_cve_mcp_triage(args.cve_mcp_url, cve_id, depth=args.triage_depth)
        except Exception as exc:  # noqa: BLE001 -- one bad CVE shouldn't kill the run
            print(f"ERROR: triage_cve failed for {cve_id}: {exc}", file=sys.stderr)
            errors += 1
            continue

        parsed = parse_triage_text(triage_text)

        narrative = ""
        llm_provider_used = None
        if args.llm_provider != "none" and llm_api_key:
            try:
                narrative = synthesize_narrative(
                    args.llm_provider, llm_api_key, cve_id, triage_text,
                    entry["sources"], entry["total_instances"],
                )
                llm_provider_used = args.llm_provider
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: LLM narrative failed for {cve_id}: {exc}", file=sys.stderr)

        now = _now_iso()
        doc = {
            "cve_id": cve_id,
            "sources": entry["sources"],
            "total_instances": entry["total_instances"],
            **parsed,
            "triage_raw_text": triage_text,
            "llm_narrative": narrative,
            "llm_provider": llm_provider_used,
            "enriched_at": now,
        }
        upsert_exposure_doc(
            args.elasticsearch_url, cve_id, doc,
            auth_header=auth_header, verify_tls=verify_tls, dry_run=args.dry_run,
        )

        assessment = {
            "severity_assessed": parsed.get("risk_band"),
            "assessed_reason": (narrative or triage_text)[:2000],
            "assessed_by": "cve_enrichment_sync",
            "assessed_at": now,
        }
        for src in sources:
            if any(s["source"] == src["source"] for s in entry["sources"]):
                writeback_findings(
                    args.elasticsearch_url, src["index"], src["field"], cve_id, assessment,
                    auth_header=auth_header, verify_tls=verify_tls, dry_run=args.dry_run,
                )

        enriched += 1
        # Polite pacing -- each call fans out to NVD/EPSS/KEV/GitHub via
        # cve-mcp-server, plus an external LLM API call.
        time.sleep(1)

    print(
        f"Done — cves_seen={len(cve_map)} enriched={enriched} skipped_fresh={skipped_fresh} "
        f"sources_refreshed={sources_refreshed} errors={errors} dry_run={args.dry_run}"
    )
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
