#!/usr/bin/env python3
"""Daily security report across every findings source, written by the local
LLM -- see docs/threat-vuln-platform/plan.md's Phase 15.

OpenSearch is the only input. Every source already lands there through its
own sync job, so this script never talks to Harbor, GVM, Wazuh or T-Pot
directly:

  harbor-findings            Harbor's Trivy scans     (es_findings_ingest, harbor-stack)
  gvm-findings               Greenbone network scans  (gvm_findings_ingest, greenbone-stack)
  wazuh-findings             Wazuh vulnerability state (wazuh_findings_ingest, wazuh-stack)
  tpot-events-*              T-Pot honeypot events    (tpot_findings_ingest, secpipe-stack)
  unified-cve-exposure       correlated, enriched CVEs (cve_enrichment_sync, secpipe-stack)
  stack-risk-summary         per-stack rollup          (cve_enrichment_sync, secpipe-stack)
  cve-remediation-assessment weekly deep-dive calls    (cve_deep_dive, secpipe-stack)

The script builds a deterministic fact set first (counts, what is new in the
last 24h, top risks, honeypot hits, and how fresh each source is), then asks
the local Framework llama-server to turn those facts into a short report. The
result is one document per UTC day in security-daily-report, id = the date,
so a rerun replaces that day's report instead of adding a second one.

The document is shaped for the two planned consumers:
  - Discord notification: `headline` is a one-line deterministic summary that
    never depends on the LLM, and `summary_markdown` is the narrative. A
    notifier reads security-daily-report/_doc/<date> and posts both.
  - Threat modelling: `top_cves`, `stack_risk` and `facts.exposure_by_zone`
    carry the stack/zone context for each risk.

If the LLM call fails, the report is still written with status
`llm_failed` and the facts, so a notifier always has something true to post
(`facts_only` when run with --no-llm).
Local-only by design: there is no hosted-provider path in this script.

Colocated with cve_enrichment_sync.py and imports its ES/LLM helpers, the
same way cve_deep_dive.py does.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import cve_enrichment_sync as ces

REPORT_INDEX = "security-daily-report"
WINDOW_HOURS = 24
SEVERE = ["Critical", "High", "critical", "high", "CRITICAL", "HIGH"]

# Findings sources: one current-state index each, all with the same
# first_seen/ingested_at contract (see each role's index template).
FINDINGS_SOURCES = [
    {
        "name": "harbor",
        "index": "harbor-findings",
        "severity_field": "severity_raw",
        "stack_field": "artifact.stack",
        "zone_field": "artifact.zone",
        # Phase 13: skip artifacts nothing runs. A missing in_use counts as
        # in use, same rule cve_deep_dive.py's shortlist relies on.
        "scope": [
            {"term": {"artifact.in_production": True}},
            {"bool": {"must_not": {"term": {"artifact.in_use": False}}}},
        ],
    },
    {
        "name": "greenbone",
        "index": "gvm-findings",
        "severity_field": "threat_raw",
        "stack_field": "target.stack",
        "zone_field": "target.zone",
        # pentest_seg targets are scanned on request only and stay out of
        # lab findings (docs/alerting/README.md).
        "scope": [
            {"term": {"target.in_production": True}},
            {"bool": {"must_not": {"term": {"target.pentest_target": True}}}},
        ],
    },
    {
        "name": "wazuh",
        "index": "wazuh-findings",
        "severity_field": "severity_raw",
        "stack_field": "target.stack",
        "zone_field": "target.zone",
        "scope": [{"term": {"target.in_production": True}}],
    },
]

# Freshness: the newest timestamp each pipeline writes, and how old it may
# get before the report calls that source stale. Daily jobs get 26h (one
# missed run plus timer jitter); T-Pot syncs every 10 minutes; the deep dive
# is weekly.
FRESHNESS = [
    {"name": "harbor", "index": "harbor-findings", "field": "ingested_at", "max_age_hours": 26},
    {"name": "greenbone", "index": "gvm-findings", "field": "ingested_at", "max_age_hours": 26},
    {"name": "wazuh", "index": "wazuh-findings", "field": "ingested_at", "max_age_hours": 26},
    {"name": "tpot", "index": "tpot-events-*", "field": "@timestamp", "max_age_hours": 1},
    # stack-risk-summary is fully recomputed on every cve-enrichment-sync
    # run; unified-cve-exposure.enriched_at only moves when a new CVE shows
    # up, so it would read as stale on a quiet day.
    {"name": "cve-correlation", "index": "stack-risk-summary", "field": "updated_at", "max_age_hours": 26},
    {"name": "cve-deep-dive", "index": "cve-remediation-assessment", "field": "generated_at", "max_age_hours": 8 * 24 + 2},
]

# Same definition of "unexpected connection" as the Grafana tripwire rule
# (terraform/lxc/stacks/monitoring-stack/alerting/homelab-honeypot.yml) --
# keep the two in step.
TPOT_UNEXPECTED_QUERY = (
    'honeypot.keyword:suricata AND event_type.keyword:flow AND dest_ip.keyword:"192.168.1.28" '
    "AND NOT dest_port:(64295 OR 64297 OR 64294 OR 64298 OR 64296 OR 8083 OR 8084 OR 67 OR 68 "
    "OR 137 OR 138 OR 546 OR 547 OR 5353 OR 1900) "
    'AND NOT src_ip.keyword:("192.168.1.28" OR "192.168.1.4" OR "192.168.1.104" OR "192.168.1.251" '
    'OR "192.168.50.12" OR "192.168.20.12" OR "192.168.20.14" OR "192.168.20.15" OR "192.168.40.15" '
    'OR "192.168.70.11") AND dest_port:[1 TO 32767] AND src_port:[1024 TO 65535]'
)


class Client:
    def __init__(self, es_url: str, auth_header: str, verify_tls: bool):
        self.es_url = es_url
        self.auth_header = auth_header
        self.verify_tls = verify_tls

    def search(self, index: str, body: dict) -> dict | None:
        path = f"/{urllib.parse.quote(index, safe='*,-')}/_search?ignore_unavailable=true&allow_no_indices=true"
        status, result = ces._es_request(
            self.es_url, path, method="POST", body=body,
            auth_header=self.auth_header, verify_tls=self.verify_tls,
        )
        if status != 200 or result is None:
            print(f"WARN: search on {index} failed ({status}): {result}", file=sys.stderr)
            return None
        return result

    def put(self, path: str, body: dict) -> bool:
        status, result = ces._es_request(
            self.es_url, path, method="PUT", body=body,
            auth_header=self.auth_header, verify_tls=self.verify_tls,
        )
        if status not in (200, 201):
            print(f"WARN: PUT {path} failed ({status}): {result}", file=sys.stderr)
            return False
        return True


# --- fact collection -------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value) -> datetime | None:
    """OpenSearch max aggs return epoch millis plus value_as_string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _buckets(result: dict | None, agg: str) -> dict[str, int]:
    """Terms buckets from a search response, or from a filter sub-agg
    (which holds its child aggs directly, not under "aggregations")."""
    if not result:
        return {}
    container = result.get("aggregations", result)
    return {
        str(b["key"]): b["doc_count"]
        for b in container.get(agg, {}).get("buckets", [])
    }


def _total(result: dict | None) -> int:
    if not result:
        return 0
    total = result.get("hits", {}).get("total", 0)
    return total.get("value", 0) if isinstance(total, dict) else int(total)


def normalize_severity(counts: dict[str, int]) -> dict[str, int]:
    """Harbor/Wazuh say Critical/High/..., GVM says High/Medium/Low/Log --
    fold case so the report and the LLM see one vocabulary."""
    out: dict[str, int] = {}
    for key, count in counts.items():
        label = key.strip().lower() or "unknown"
        out[label] = out.get(label, 0) + count
    return out


def evaluate_freshness(newest: datetime | None, doc_count: int, max_age_hours: float, now: datetime) -> dict:
    if doc_count == 0 or newest is None:
        return {"status": "missing", "newest": None, "age_hours": None}
    age = round((now - newest).total_seconds() / 3600, 1)
    return {
        "status": "stale" if age > max_age_hours else "fresh",
        "newest": _iso(newest),
        "age_hours": age,
    }


def collect_freshness(client: Client, now: datetime) -> list[dict]:
    rows = []
    for spec in FRESHNESS:
        result = client.search(spec["index"], {
            "size": 0,
            "track_total_hits": True,
            "aggs": {"newest": {"max": {"field": spec["field"]}}},
        })
        if result is None:
            rows.append({"name": spec["name"], "index": spec["index"], "status": "error",
                         "newest": None, "age_hours": None, "doc_count": 0,
                         "max_age_hours": spec["max_age_hours"]})
            continue
        newest_agg = result.get("aggregations", {}).get("newest", {})
        newest = _parse_ts(newest_agg.get("value_as_string") or newest_agg.get("value"))
        doc_count = _total(result)
        rows.append({"name": spec["name"], "index": spec["index"], "doc_count": doc_count,
                     "max_age_hours": spec["max_age_hours"],
                     **evaluate_freshness(newest, doc_count, spec["max_age_hours"], now)})
    return rows


def collect_findings(client: Client, since: datetime) -> list[dict]:
    rows = []
    for src in FINDINGS_SOURCES:
        sev = src["severity_field"]
        scope = {"bool": {"filter": src["scope"]}}
        result = client.search(src["index"], {
            "size": 0,
            "track_total_hits": True,
            "query": scope,
            "aggs": {
                "by_severity": {"terms": {"field": sev, "size": 10}},
                "new": {
                    "filter": {"range": {"first_seen": {"gte": _iso(since)}}},
                    "aggs": {"by_severity": {"terms": {"field": sev, "size": 10}}},
                },
                "severe": {
                    "filter": {"terms": {sev: SEVERE}},
                    "aggs": {
                        "by_stack": {"terms": {"field": src["stack_field"], "size": 10}},
                        "by_zone": {"terms": {"field": src["zone_field"], "size": 10}},
                    },
                },
            },
        })
        aggs = (result or {}).get("aggregations", {})
        rows.append({
            "source": src["name"],
            "index": src["index"],
            "ok": result is not None,
            "in_scope_total": _total(result),
            "by_severity": normalize_severity(_buckets(result, "by_severity")),
            "new_last_24h": normalize_severity(_buckets(aggs.get("new"), "by_severity")),
            "severe_by_stack": _buckets(aggs.get("severe"), "by_stack"),
            "severe_by_zone": _buckets(aggs.get("severe"), "by_zone"),
        })
    return rows


def collect_cves(client: Client, since: datetime, top_n: int) -> dict:
    scope = [{"term": {"in_production": True}}, {"term": {"in_use": True}}]
    summary = client.search("unified-cve-exposure", {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": scope}},
        "aggs": {
            "by_band": {"terms": {"field": "risk_band", "size": 10}},
            "kev": {"filter": {"term": {"kev_listed": True}}},
            "poc": {"filter": {"term": {"poc_available": True}}},
            "new": {"filter": {"range": {"enriched_at": {"gte": _iso(since)}}}},
            "by_zone": {"terms": {"field": "zones", "size": 20}},
        },
    })
    fields = ["cve_id", "risk_score", "risk_band", "cvss_score", "epss_score", "kev_listed",
              "poc_available", "stacks", "zones", "total_instances", "risk_urgency"]
    top = client.search("unified-cve-exposure", {
        "size": top_n,
        "query": {"bool": {"filter": scope}},
        "sort": [{"risk_score": {"order": "desc"}}],
        "_source": fields,
    })
    new_top = client.search("unified-cve-exposure", {
        "size": 5,
        "query": {"bool": {"filter": scope + [{"range": {"enriched_at": {"gte": _iso(since)}}}]}},
        "sort": [{"risk_score": {"order": "desc"}}],
        "_source": fields,
    })
    aggs = (summary or {}).get("aggregations", {})
    return {
        "ok": summary is not None,
        "in_production_in_use": _total(summary),
        "by_risk_band": normalize_severity(_buckets(summary, "by_band")),
        "kev_listed": aggs.get("kev", {}).get("doc_count", 0),
        "poc_available": aggs.get("poc", {}).get("doc_count", 0),
        "new_last_24h": aggs.get("new", {}).get("doc_count", 0),
        "exposure_by_zone": _buckets(summary, "by_zone"),
        "top": [h["_source"] for h in (top or {}).get("hits", {}).get("hits", [])],
        "new_top": [h["_source"] for h in (new_top or {}).get("hits", {}).get("hits", [])],
    }


def collect_stack_risk(client: Client, top_n: int) -> list[dict]:
    result = client.search("stack-risk-summary", {
        "size": top_n,
        "sort": [{"critical": {"order": "desc"}}, {"high": {"order": "desc"}}],
        "_source": ["stack", "total_cves", "critical", "high", "avg_risk_score", "sources_reporting"],
    })
    return [h["_source"] for h in (result or {}).get("hits", {}).get("hits", [])]


def collect_remediation(client: Client) -> dict:
    open_q = {"bool": {"must_not": {"term": {"resolved": True}}}}
    result = client.search("cve-remediation-assessment", {
        "size": 10,
        "track_total_hits": True,
        "query": open_q,
        "sort": [{"risk_score": {"order": "desc"}}],
        "_source": ["cve_id", "recommended_action", "stacks", "zones", "risk_score", "generated_at"],
        "aggs": {"by_action": {"terms": {"field": "recommended_action", "size": 10}}},
    })
    return {
        "ok": result is not None,
        "open": _total(result),
        "by_action": _buckets(result, "by_action"),
        "top_open": [h["_source"] for h in (result or {}).get("hits", {}).get("hits", [])],
    }


def collect_tpot(client: Client, since: datetime) -> dict:
    window = {"range": {"@timestamp": {"gte": _iso(since)}}}
    unexpected = client.search("tpot-events-*", {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [window, {"query_string": {"query": TPOT_UNEXPECTED_QUERY}}]}},
        "aggs": {
            "sources": {"terms": {"field": "src_ip.keyword", "size": 10}},
            "ports": {"terms": {"field": "dest_port", "size": 10}},
        },
    })
    # Sensor-level activity, without the Suricata/p0f/nginx plumbing, same
    # split as the T-Pot Events dashboard's sensor panel.
    sensors = client.search("tpot-events-*", {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {
            "filter": [window],
            "must_not": [{"terms": {"honeypot.keyword": ["suricata", "p0f", "nginx"]}}],
        }},
        "aggs": {"by_sensor": {"terms": {"field": "honeypot.keyword", "size": 15}}},
    })
    src = _buckets(unexpected, "sources")
    return {
        "ok": unexpected is not None and sensors is not None,
        "unexpected_connections": _total(unexpected),
        "unexpected_sources": len(src),
        "unexpected_by_source": src,
        "unexpected_by_port": _buckets(unexpected, "ports"),
        "sensor_events": _total(sensors),
        "sensor_events_by_sensor": _buckets(sensors, "by_sensor"),
    }


# --- report ----------------------------------------------------------------


def totals(findings: list[dict]) -> dict[str, int]:
    out = {"critical": 0, "high": 0, "new_critical": 0, "new_high": 0}
    for row in findings:
        out["critical"] += row["by_severity"].get("critical", 0)
        out["high"] += row["by_severity"].get("high", 0)
        out["new_critical"] += row["new_last_24h"].get("critical", 0)
        out["new_high"] += row["new_last_24h"].get("high", 0)
    return out


def build_headline(report_date: str, tot: dict, cves: dict, tpot: dict, freshness: list[dict]) -> str:
    """Deterministic one-liner for the Discord post -- no LLM in it, so it is
    always true even when the narrative failed."""
    not_fresh = [f"{r['name']} ({r['status']})" for r in freshness if r["status"] != "fresh"]
    return (
        f"Security daily {report_date}: {tot['critical']} critical / {tot['high']} high findings in production "
        f"(+{tot['new_critical']} / +{tot['new_high']} new in 24h); "
        f"{cves['kev_listed']} KEV-listed and {cves['poc_available']} PoC CVEs in use; "
        f"honeypot: {tpot['unexpected_sources']} unexpected source(s), {tpot['unexpected_connections']} connection(s); "
        f"data: {'all sources fresh' if not not_fresh else 'check ' + ', '.join(not_fresh)}"
    )


def build_prompt(facts: dict) -> str:
    return (
        "You are the security analyst for a home lab: Proxmox LXC stacks in isolated "
        "network zones behind one reverse-proxy edge, a container registry (Harbor, "
        "scanned by Trivy), a network vulnerability scanner (Greenbone), host agents "
        "(Wazuh) and a LAN honeypot (T-Pot) that nothing but allowlisted scanners "
        "should ever touch. Below are today's facts, already computed from OpenSearch. "
        "Write the daily security report from them.\n\n"
        "Rules:\n"
        "- Use only the numbers, CVE IDs, stacks and zones in the facts. Never invent "
        "a number, a fixed version, a host or a CVE.\n"
        "- A scanner name is not the vulnerable product: 'harbor' means Harbor's scanner "
        "found it in an image; the affected stack is in 'stacks'.\n"
        "- If a source is stale, missing or errored, say what that means for how far the "
        "report can be trusted, and do not describe its numbers as current.\n"
        "- Any unexpected honeypot connection is a possible intruder on the LAN; lead "
        "with it if there is one.\n"
        "- Under 450 words, Markdown, these sections in this order:\n"
        "  ## Bottom line (1-2 sentences)\n"
        "  ## What changed in the last 24 hours\n"
        "  ## Top risks to act on (at most 5 bullets: CVE or finding, stack, zone, why now, next step)\n"
        "  ## Honeypot\n"
        "  ## Data quality\n"
        "  ## Threat-model focus (which zones or stacks carry the most exploitable exposure, "
        "and the attack path worth modelling next)\n\n"
        f"FACTS (JSON):\n{json.dumps(facts, indent=1, default=str)}"
    )


def build_document(report_date: str, now: datetime, facts: dict, headline: str,
                   summary: str | None, llm_error: str | None, model: str) -> dict:
    tot = facts["totals"]
    freshness = facts["freshness"]
    return {
        "report_date": report_date,
        "generated_at": _iso(now),
        "window_hours": WINDOW_HOURS,
        "status": "ok" if summary else ("llm_failed" if llm_error else "facts_only"),
        "llm_provider": "llamacpp" if model else "none",
        "llm_model": model,
        "llm_error": llm_error,
        "headline": headline,
        "summary_markdown": summary,
        "stale_sources": [r["name"] for r in freshness if r["status"] == "stale"],
        "missing_sources": [r["name"] for r in freshness if r["status"] in ("missing", "error")],
        "critical_total": tot["critical"],
        "high_total": tot["high"],
        "new_critical_24h": tot["new_critical"],
        "new_high_24h": tot["new_high"],
        "kev_in_use": facts["cves"]["kev_listed"],
        "poc_in_use": facts["cves"]["poc_available"],
        "open_remediations": facts["remediation"]["open"],
        "tpot_unexpected_sources": facts["tpot"]["unexpected_sources"],
        "tpot_unexpected_connections": facts["tpot"]["unexpected_connections"],
        "top_cves": [
            {k: c.get(k) for k in ("cve_id", "risk_score", "risk_band", "kev_listed", "poc_available", "stacks", "zones")}
            for c in facts["cves"]["top"]
        ],
        "stack_risk": facts["stack_risk"],
        "facts": facts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", "https://127.0.0.1:9200"))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER"))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD"))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--llamacpp-url", default=os.environ.get("LLAMACPP_URL", "http://framework.gibbsgreatly.xyz:8080"))
    parser.add_argument("--llamacpp-model", default=os.environ.get("LLAMACPP_MODEL", "qwen3.8-flash-next"))
    parser.add_argument("--llamacpp-api-key", default=os.environ.get("LLAMACPP_API_KEY", ""))
    parser.add_argument("--top-n", type=int, default=int(os.environ.get("SECURITY_REPORT_TOP_N", "10")))
    parser.add_argument("--no-llm", action="store_true", help="Facts and headline only, no LLM call.")
    parser.add_argument("--dry-run", action="store_true", help="Print the report instead of writing it.")
    args = parser.parse_args()

    if not args.es_user or not args.es_password:
        print("ERROR: --es-user/--es-password (or ES_FINDINGS_USER/ES_FINDINGS_PASSWORD) are required", file=sys.stderr)
        return 1

    auth_header = "Basic " + base64.b64encode(f"{args.es_user}:{args.es_password}".encode()).decode()
    client = Client(args.elasticsearch_url, auth_header, not args.no_verify_tls)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=WINDOW_HOURS)
    report_date = now.strftime("%Y-%m-%d")

    findings = collect_findings(client, since)
    facts = {
        "report_date": report_date,
        "window_start": _iso(since),
        "freshness": collect_freshness(client, now),
        "findings": findings,
        "totals": totals(findings),
        "cves": collect_cves(client, since, args.top_n),
        "stack_risk": collect_stack_risk(client, args.top_n),
        "remediation": collect_remediation(client),
        "tpot": collect_tpot(client, since),
    }
    if not any(r["status"] == "fresh" for r in facts["freshness"]):
        # Nothing readable at all: almost certainly a credential or
        # permission problem, not a quiet day. Fail the unit so it shows.
        print("ERROR: no source index returned fresh data -- check es-user.env and es_findings_writer", file=sys.stderr)
        return 1

    headline = build_headline(report_date, facts["totals"], facts["cves"], facts["tpot"], facts["freshness"])
    summary = None
    llm_error = None
    if not args.no_llm:
        try:
            summary = ces._call_llamacpp(
                args.llamacpp_url, args.llamacpp_model, build_prompt(facts), api_key=args.llamacpp_api_key,
            )
        except Exception as exc:  # noqa: BLE001 -- the facts still get written
            llm_error = str(exc)[:500]
            print(f"WARN: report LLM call failed: {llm_error}", file=sys.stderr)

    doc = build_document(report_date, now, facts, headline, summary, llm_error,
                         args.llamacpp_model if not args.no_llm else "")
    if args.dry_run:
        print(json.dumps(doc, indent=1, default=str))
        return 0
    if not client.put(f"/{REPORT_INDEX}/_doc/{report_date}", doc):
        return 1
    print(f"Wrote {REPORT_INDEX}/{report_date} status={doc['status']}: {headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
