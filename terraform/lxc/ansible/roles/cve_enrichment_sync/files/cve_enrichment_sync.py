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
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw.decode(errors="replace")[:500]}


ASSET_SAMPLE_SIZE = 5


def _get_path(d: dict, path: str):
    """Dotted-path lookup into a nested dict, e.g. 'artifact.repository'."""
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


ASSET_FIELD_SPECS = {
    "harbor": {
        "source_fields": ["artifact.repository", "artifact.tag"],
        "format": lambda src: (
            f"{_get_path(src, 'artifact.repository') or '?'}:"
            f"{_get_path(src, 'artifact.tag') or '?'}"
        ),
        "production_field": "artifact.in_production",
        "zone_field": "artifact.zone",
        "stack_field": "artifact.stack",
    },
    "greenbone": {
        "source_fields": ["target.host", "target.port", "target.zone"],
        "format": lambda src: (
            f"{_get_path(src, 'target.host') or '?'}:"
            f"{_get_path(src, 'target.port') or '?'}"
            f" ({_get_path(src, 'target.zone') or '?'})"
        ),
        "production_field": "target.in_production",
        "zone_field": "target.zone",
        "stack_field": "target.stack",
    },
    "wazuh": {
        "source_fields": ["target.agent_id", "target.agent_name"],
        "format": lambda src: (
            _get_path(src, "target.agent_name")
            or _get_path(src, "target.agent_id")
            or "?"
        ),
        "production_field": "target.in_production",
        "zone_field": "target.zone",
        "stack_field": "target.stack",
    },
}


def build_assets_summary(sources_list: list[dict]) -> str:
    """Flatten sources[] (each already carrying an 'assets' list and
    'assets_truncated' flag) into one human-readable text block, for
    direct display via a top_hit/concat table column -- the same pattern
    already proven live for risk_band/llm_narrative."""
    lines = []
    for s in sources_list:
        assets = s.get("assets") or []
        if not assets:
            continue
        label = f"{s['source']} ({s.get('count', len(assets))}): " + ", ".join(assets)
        if s.get("assets_truncated"):
            label += f" (+{s.get('count', 0) - len(assets)} more)"
        lines.append(label)
    return "\n".join(lines)


def fetch_cve_instances(
    es_url: str, index: str, cve_field: str, asset_source_fields: list[str],
    *, auth_header: str, verify_tls: bool, production_field: str, zone_field: str, stack_field: str,
) -> dict[str, dict]:
    """Terms-aggregate distinct CVE values + doc counts from one findings
    index, plus: (1) a top_hits sub-aggregation sampling up to
    ASSET_SAMPLE_SIZE of the most-recently-seen documents' asset
    identifier fields per CVE, (2) a filter sub-agg counting how many of
    this CVE's instances are in_production:true, (3) a terms sub-agg
    collecting the distinct zones this CVE appears in -- the UVM
    redesign's production/zone rollup (docs/threat-vuln-platform/plan.md,
    2026-09-01), (4) a terms sub-agg collecting the distinct stacks this
    CVE appears on -- Phase 9's stack-centric rollup, same day. Works
    unchanged whether the field is a single keyword
    (harbor-findings.finding_id) or a keyword array (gvm-findings.cve) --
    a terms agg on an array field buckets each value independently, which
    is the correct behaviour here (a finding with 2 CVEs should count
    toward both)."""
    body = {
        "size": 0,
        "aggs": {
            "cves": {
                "terms": {"field": cve_field, "size": 10000},
                "aggs": {
                    "assets": {
                        "top_hits": {
                            "size": ASSET_SAMPLE_SIZE,
                            "_source": asset_source_fields,
                            "sort": [{"last_seen": {"order": "desc"}}],
                        }
                    },
                    "production_count": {"filter": {"term": {production_field: True}}},
                    "zones": {"terms": {"field": zone_field, "size": 10}},
                    "stacks": {"terms": {"field": stack_field, "size": 10}},
                },
            }
        },
    }
    status, result = _es_request(
        es_url, f"/{index}/_search", method="POST", body=body,
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status != 200 or not result:
        print(f"WARN: failed to aggregate {index} ({status}): {result}", file=sys.stderr)
        return {}
    buckets = result.get("aggregations", {}).get("cves", {}).get("buckets", [])
    out: dict[str, dict] = {}
    for b in buckets:
        if not b.get("key"):
            continue
        hits = b.get("assets", {}).get("hits", {}).get("hits", [])
        zones = [z["key"] for z in b.get("zones", {}).get("buckets", []) if z.get("key")]
        stacks = [s["key"] for s in b.get("stacks", {}).get("buckets", []) if s.get("key")]
        out[b["key"]] = {
            "count": b["doc_count"],
            "raw_assets": [h.get("_source", {}) for h in hits],
            "production_count": b.get("production_count", {}).get("doc_count", 0),
            "zones": zones,
            "stacks": stacks,
        }
    return out


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
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
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


# --- LLM narrative (Anthropic/OpenAI/Ollama -- see module docstring for
# the local-LLM migration this is moving toward) --------------------------


def synthesize_narrative(
    provider: str, api_key: str, cve_id: str, triage_text: str, sources: list[dict], total_instances: int,
    *, ollama_url: str = "", ollama_model: str = "",
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
    if provider == "ollama":
        return _call_ollama(ollama_url, ollama_model, prompt)
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"].strip()


def _call_ollama(ollama_url: str, model: str, prompt: str, *, timeout: int = 120) -> str:
    """Local Framework LLM via Ollama's /api/generate -- confirmed live
    2026-09-01: framework.gibbsgreatly.xyz:11434, reachable from
    secpipe-stack's network, laguna-s-2.1:q4_k_m-ctx131k confirmed loaded
    (see docs/threat-vuln-platform/plan.md). No API key -- Ollama has none.
    Longer default timeout than Anthropic/OpenAI (120s not 30s): a local
    117B-param model genuinely takes longer per call than a hosted API,
    confirmed by this project's own BFCL numbers for this exact model
    (project_laguna_ollama_runtime memory)."""
    if not ollama_url or not model:
        raise ValueError("ollama provider requires both --ollama-url and --ollama-model")
    body = {"model": model, "prompt": prompt, "stream": False}
    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
        result = json.loads(resp.read())
    return (result.get("response") or "").strip()


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
    es_url: str, cve_id: str, sources_list: list[dict], total_instances: int,
    in_production: bool, zones: list[str], stacks: list[str],
    *, auth_header: str, verify_tls: bool, dry_run: bool
) -> bool:
    """Cheap update for an already-enriched CVE whose sources/counts/
    production-or-zone-or-stack status have changed (e.g. a newly-added
    findings source, like wazuh-findings joining harbor-findings/
    gvm-findings on 2026-09-01, or the UVM redesign's in_production/
    zones/stacks fields backfilling onto every existing doc) -- updates
    only these fields via a partial _update, with NO triage_cve or LLM
    call. This is what backfills existing enrichments without re-running
    the expensive full enrichment for every already-enriched CVE. Returns
    True if updated."""
    if dry_run:
        return False
    status, result = _es_request(
        es_url, f"/unified-cve-exposure/_update/{urllib.parse.quote(cve_id, safe='')}",
        method="POST",
        body={"doc": {
            "sources": sources_list,
            "total_instances": total_instances,
            "assets_summary": build_assets_summary(sources_list),
            "in_production": in_production,
            "zones": zones,
            "stacks": stacks,
        }},
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status != 200:
        print(f"WARN: source refresh failed for {cve_id} ({status}): {result}", file=sys.stderr)
        return False
    return True


def compute_stack_rollup(es_url: str, *, auth_header: str, verify_tls: bool, dry_run: bool) -> int:
    """Materialize a per-stack severity breakdown into stack-risk-summary,
    one document per stack (docs/threat-vuln-platform/plan.md, Phase 9
    follow-up, 2026-09-02). Exists because classic OpenSearch Dashboards
    visualizations cannot pivot an aggregation bucket (risk_band) into
    real table columns -- a dashboard panel on unified-cve-exposure
    directly can show "count of CRITICAL CVEs, split by stack" OR
    "stack | count" but never "stack | critical | high | medium | low"
    as one row with real columns. This precomputes that pivot server-side
    using the same terms-bucket-with-filter-sub-aggs technique already
    proven in fetch_cve_instances() (production_count), just aggregating
    unified-cve-exposure's own already-correlated stacks/risk_band fields
    instead of a raw findings index. Full recompute every run (cheap --
    a few dozen stacks at most) rather than incremental, avoiding drift
    between this rollup and unified-cve-exposure's own state. Returns the
    number of stack documents written."""
    body = {
        "size": 0,
        "aggs": {
            "stacks": {
                "terms": {"field": "stacks", "size": 50},
                "aggs": {
                    "critical": {"filter": {"term": {"risk_band": "CRITICAL"}}},
                    "high": {"filter": {"term": {"risk_band": "HIGH"}}},
                    "medium": {"filter": {"term": {"risk_band": "MEDIUM"}}},
                    "low": {"filter": {"term": {"risk_band": "LOW"}}},
                    "avg_risk": {"avg": {"field": "risk_score"}},
                    "sources": {"cardinality": {"field": "sources.source"}},
                },
            }
        },
    }
    status, result = _es_request(
        es_url, "/unified-cve-exposure/_search", method="POST", body=body,
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status != 200 or not result:
        print(f"WARN: stack rollup aggregation failed ({status}): {result}", file=sys.stderr)
        return 0

    buckets = result.get("aggregations", {}).get("stacks", {}).get("buckets", [])
    now = _now_iso()
    seen_stacks = set()
    written = 0
    for b in buckets:
        stack = b.get("key")
        if not stack:
            continue
        seen_stacks.add(stack)
        doc = {
            "stack": stack,
            "total_cves": b["doc_count"],
            "critical": b.get("critical", {}).get("doc_count", 0),
            "high": b.get("high", {}).get("doc_count", 0),
            "medium": b.get("medium", {}).get("doc_count", 0),
            "low": b.get("low", {}).get("doc_count", 0),
            "avg_risk_score": b.get("avg_risk", {}).get("value"),
            "sources_reporting": b.get("sources", {}).get("value", 0),
            "updated_at": now,
        }
        if dry_run:
            continue
        put_status, put_result = _es_request(
            es_url, f"/stack-risk-summary/_doc/{urllib.parse.quote(stack, safe='')}",
            method="PUT", body=doc, auth_header=auth_header, verify_tls=verify_tls,
        )
        if put_status not in (200, 201):
            print(f"WARN: failed to write stack-risk-summary doc for {stack}: {put_status} {put_result}", file=sys.stderr)
            continue
        written += 1

    # Clean up stale rows for stacks that no longer appear at all (e.g. a
    # decommissioned stack, or REDTEAM_EXCLUDE-only findings aging out) --
    # otherwise this index only ever grows and can show a stack as still
    # having risk long after every underlying CVE is gone.
    if not dry_run:
        existing_status, existing_result = _es_request(
            es_url, "/stack-risk-summary/_search", method="POST",
            body={"size": 100, "_source": False},
            auth_header=auth_header, verify_tls=verify_tls,
        )
        if existing_status == 200 and existing_result:
            for hit in existing_result.get("hits", {}).get("hits", []):
                stale_id = hit.get("_id")
                if stale_id and stale_id not in seen_stacks:
                    _es_request(
                        es_url, f"/stack-risk-summary/_doc/{urllib.parse.quote(stale_id, safe='')}",
                        method="DELETE", auth_header=auth_header, verify_tls=verify_tls,
                    )

    return written


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
        choices=["anthropic", "openai", "ollama", "none"],
    )
    parser.add_argument("--anthropic-api-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    parser.add_argument("--openai-api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument(
        "--ollama-url", default=os.environ.get("OLLAMA_URL", "http://192.168.1.8:11434"),
        help="local Framework Ollama endpoint (see docs/threat-vuln-platform/plan.md)",
    )
    parser.add_argument(
        "--ollama-model", default=os.environ.get("OLLAMA_MODEL", "laguna-s-2.1:q4_k_m-ctx131k"),
        help="Ollama model tag -- Laguna S 2.1 must run on Ollama not llama.cpp for this task, see project_laguna_ollama_runtime memory",
    )
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
        spec = ASSET_FIELD_SPECS[src["source"]]
        counts = fetch_cve_instances(
            args.elasticsearch_url, src["index"], src["field"], spec["source_fields"],
            auth_header=auth_header, verify_tls=verify_tls,
            production_field=spec["production_field"], zone_field=spec["zone_field"],
            stack_field=spec["stack_field"],
        )
        for cve_id, info in counts.items():
            entry = cve_map.setdefault(
                cve_id, {"sources": [], "total_instances": 0, "production_count": 0, "zones": set(), "stacks": set()}
            )
            assets = [spec["format"](raw) for raw in info["raw_assets"]]
            entry["sources"].append({
                "source": src["source"],
                "finding_id": cve_id,
                "count": info["count"],
                "assets": assets,
                "assets_truncated": info["count"] > len(assets),
            })
            entry["total_instances"] += info["count"]
            entry["production_count"] += info["production_count"]
            entry["zones"].update(info["zones"])
            entry["stacks"].update(info["stacks"])

    # Normalize the per-CVE production/zone/stack rollup computed above
    # (sets aren't JSON-serializable, and in_production is a simple
    # derived bool: true if ANY instance across ANY source is production).
    for entry in cve_map.values():
        entry["in_production"] = entry["production_count"] > 0
        entry["zones"] = sorted(entry["zones"])
        entry["stacks"] = sorted(entry["stacks"])

    print(f"Found {len(cve_map)} distinct CVEs across {len(sources)} findings indices.")

    # Ollama needs no API key (it's a local, unauthenticated endpoint) --
    # only anthropic/openai are gated on one being present.
    llm_api_key = None
    if args.llm_provider == "anthropic":
        llm_api_key = args.anthropic_api_key
    elif args.llm_provider == "openai":
        llm_api_key = args.openai_api_key
    llm_ready = (
        args.llm_provider == "ollama"
        or (args.llm_provider in ("anthropic", "openai") and bool(llm_api_key))
    )
    if args.llm_provider != "none" and not llm_ready:
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
                    or "assets_summary" not in existing
                    or "in_production" not in existing
                    or existing.get("in_production") != entry["in_production"]
                    or existing.get("zones") != entry["zones"]
                    or existing.get("stacks") != entry["stacks"]
                ):
                    if refresh_exposure_sources(
                        args.elasticsearch_url, cve_id, entry["sources"], entry["total_instances"],
                        entry["in_production"], entry["zones"], entry["stacks"],
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
        if args.llm_provider != "none" and llm_ready:
            try:
                narrative = synthesize_narrative(
                    args.llm_provider, llm_api_key, cve_id, triage_text,
                    entry["sources"], entry["total_instances"],
                    ollama_url=args.ollama_url, ollama_model=args.ollama_model,
                )
                llm_provider_used = args.llm_provider
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: LLM narrative failed for {cve_id}: {exc}", file=sys.stderr)

        now = _now_iso()
        doc = {
            "cve_id": cve_id,
            "sources": entry["sources"],
            "total_instances": entry["total_instances"],
            "assets_summary": build_assets_summary(entry["sources"]),
            "in_production": entry["in_production"],
            "zones": entry["zones"],
            "stacks": entry["stacks"],
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

    stack_rows_written = compute_stack_rollup(
        args.elasticsearch_url, auth_header=auth_header, verify_tls=verify_tls, dry_run=args.dry_run,
    )

    print(
        f"Done — cves_seen={len(cve_map)} enriched={enriched} skipped_fresh={skipped_fresh} "
        f"sources_refreshed={sources_refreshed} stack_rows_written={stack_rows_written} "
        f"errors={errors} dry_run={args.dry_run}"
    )
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
