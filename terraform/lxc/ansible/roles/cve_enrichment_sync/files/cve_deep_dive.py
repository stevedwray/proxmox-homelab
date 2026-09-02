#!/usr/bin/env python3
"""Architecture-aware CVE deep-dive assessment -- see
docs/threat-vuln-platform/plan.md's Phase 11.

cve_enrichment_sync.py's per-CVE narrative is deliberately generic (2-4
sentences, no architecture context) because it runs against every CVE in
unified-cve-exposure (~10,000+) -- adding real per-stack context there
would multiply an already-nontrivial LLM call volume for near-zero value
on low-severity CVEs.

This script instead does a *narrow, deep* pass: pull only the worst,
most-exploitable CVEs already in unified-cve-exposure (KEV-listed or a
known PoC exists, actually present in production), and for each one, ask
a local LLM to reason about it *with real architecture context* -- which
stack(s) it's on, which network zone(s) those stacks sit in, that zone's
containment policy, and whether the affected stack is reachable through
the shared reverse-proxy edge (and if so, whether that route is
auth-gated). The result is a genuine remediation call (recommended
action + a concrete rationale), not a repeat of the generic narrative.

Deliberately a separate script/index/timer from cve_enrichment_sync.py,
not a mode flag on it:
  - Different cadence (weekly, not daily -- the shortlist doesn't
    meaningfully change day to day, and this is a heavier prompt).
  - Different LLM provider by design (Ollama/laguna from day one -- see
    project_threat_vuln_platform_status memory; this is new work, not a
    switch of the existing narrative pipeline's standing provider, which
    stays gated behind its own separate quality-validation step).
  - Different output shape (cve-remediation-assessment, one doc per
    shortlisted CVE, not a write-back onto unified-cve-exposure itself).

Colocated with cve_enrichment_sync.py on secpipe-stack and imports its
ES/Ollama helpers directly (_es_request, _call_ollama) rather than
duplicating them -- both scripts already live in the same directory on
disk, so this isn't the cross-role shared-library refactor that's
deliberately deferred (see plan.md's "Not built / not decided yet").
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.parse

import cve_enrichment_sync as ces

_ACTIONS = {"PATCH", "UPGRADE", "ISOLATE", "ACCEPT_RISK", "INVESTIGATE"}
_ACTION_LINE = re.compile(r"RECOMMENDED ACTION:\s*([A-Z_]+)", re.IGNORECASE)


def load_architecture(path: str) -> dict:
    if not path or not os.path.exists(path):
        print(f"WARN: architecture file not found at {path!r} -- proceeding with no architecture context", file=sys.stderr)
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("stacks", {})


def fetch_shortlist(
    es_url: str, top_n: int, *, auth_header: str, verify_tls: bool
) -> list[dict]:
    """Worst, most-exploitable, actually-deployed CVEs: KEV-listed or a
    known PoC exists (minimum_should_match:1), in_production:true, sorted
    by the composite risk_score cve-mcp-server's triage_cve already
    computed. Reuses fields cve_enrichment_sync.py already writes onto
    every unified-cve-exposure document -- no new data collection."""
    body = {
        "size": top_n,
        "query": {
            "bool": {
                "filter": [{"term": {"in_production": True}}],
                "should": [
                    {"term": {"kev_listed": True}},
                    {"term": {"poc_available": True}},
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"risk_score": {"order": "desc"}}],
    }
    status, result = ces._es_request(
        es_url, "/unified-cve-exposure/_search", method="POST", body=body,
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status != 200 or not result:
        print(f"WARN: shortlist query failed ({status}): {result}", file=sys.stderr)
        return []
    return [hit["_source"] | {"_id": hit["_id"]} for hit in result.get("hits", {}).get("hits", [])]


def describe_architecture(stacks: list[str], architecture: dict) -> str:
    if not stacks:
        return "No specific stack identified for this CVE -- treat as environment-wide."
    lines = []
    for stack in stacks:
        info = architecture.get(stack)
        if not info:
            lines.append(f"- {stack}: architecture unknown (not found in stack registry)")
            continue
        exposure = "no reverse-proxy route (not reachable via the shared edge)"
        if info.get("edge_exposed"):
            auth = info.get("edge_auth_mode") or "unknown"
            exposure = f"reachable via the shared reverse-proxy edge, auth mode: {auth}"
        lines.append(
            f"- {stack}: zone '{info.get('zone')}' ({info.get('zone_description', 'no description')}); {exposure}"
        )
    return "\n".join(lines)


def build_prompt(cve: dict, architecture: dict) -> str:
    stacks = cve.get("stacks") or []
    zones = cve.get("zones") or []
    # sources[].source is which SCANNER found this (e.g. "harbor" means
    # "Harbor's own vulnerability scanner found this in an image it
    # registry-scanned", NOT "the Harbor application is vulnerable") --
    # confirmed live 2026-09-03: the existing llm_narrative field (written
    # by cve_enrichment_sync.py's own, separate Anthropic-driven prompt)
    # conflates the two for CVE-2023-48795, saying "Patch Harbor within 72
    # hours" when the real affected asset is wazuh/wazuh-manager on
    # wazuh-stack (Harbor merely scanned that image). Since this prompt
    # quotes that narrative verbatim as context, it must say so explicitly
    # or the model repeats the same confusion -- confirmed happens if this
    # warning is omitted.
    vulnerable_assets = ", ".join(
        f"{s.get('source')}: {', '.join(s.get('assets') or []) or '(no asset detail)'}"
        for s in (cve.get("sources") or [])
    ) or "(none)"
    return (
        "You are a security architect triaging vulnerabilities for a home-lab "
        "environment made of isolated network zones behind a shared reverse-proxy "
        "edge. You are given one CVE that automated triage has already flagged as "
        "high-risk (CISA KEV-listed and/or a known public exploit exists), plus the "
        "real architecture of the stack(s) it affects. Produce a remediation call, "
        "not a repeat of the CVE facts.\n\n"
        f"CVE: {cve.get('cve_id', cve.get('_id'))}\n"
        f"Risk score: {cve.get('risk_score')} ({cve.get('risk_band')})\n"
        f"CVSS: {cve.get('cvss_score')} {cve.get('cvss_severity')} ({cve.get('cvss_vector')})\n"
        f"EPSS: {cve.get('epss_score')}\n"
        f"KEV listed: {cve.get('kev_listed')}\n"
        f"PoC available: {cve.get('poc_available')}\n"
        f"Total instances in environment: {cve.get('total_instances')}\n"
        f"Zones affected: {', '.join(zones) or 'unknown'}\n"
        "The 'stacks' list and the vulnerable-assets list below are the "
        "authoritative facts about WHAT is actually running this vulnerable "
        "code and WHERE. Each entry below is formatted as "
        "'<scanner that found it>: <the actual vulnerable image/package>' -- "
        "the scanner name (e.g. 'harbor') is NOT itself the affected "
        "application unless the vulnerable image IS that application; e.g. "
        "'harbor: wazuh/wazuh-manager:4.14.7' means Harbor's own scanner "
        "found this in the wazuh-manager image, so wazuh-stack is affected, "
        "not Harbor.\n"
        f"Vulnerable asset(s): {vulnerable_assets}\n"
        f"Affected stack(s) (authoritative): {', '.join(stacks) or 'unknown/environment-wide'}\n\n"
        f"Existing automated narrative (background context ONLY -- may be "
        f"imprecise about which stack is affected, defer to the authoritative "
        f"fields above if they conflict): {cve.get('llm_narrative') or '(none)'}\n\n"
        "Architecture of the affected stack(s):\n"
        f"{describe_architecture(stacks, architecture)}\n\n"
        "Respond in exactly this format:\n"
        "RECOMMENDED ACTION: <one of PATCH, UPGRADE, ISOLATE, ACCEPT_RISK, INVESTIGATE>\n"
        "ASSESSMENT: <3-5 sentences. Reference the actual zone/exposure above -- "
        "e.g. whether this is more or less urgent because of containment or "
        "public-edge exposure -- and be concrete about what to do next, not generic "
        "advice.>"
    )


def parse_assessment(text: str) -> tuple[str | None, str]:
    action = None
    m = _ACTION_LINE.search(text)
    if m:
        candidate = m.group(1).upper()
        if candidate in _ACTIONS:
            action = candidate
    assessment = re.sub(r"RECOMMENDED ACTION:\s*[A-Z_]+\s*", "", text, flags=re.IGNORECASE)
    assessment = re.sub(r"^ASSESSMENT:\s*", "", assessment.strip(), flags=re.IGNORECASE)
    return action, assessment.strip()


def upsert_assessment(
    es_url: str, cve_id: str, doc: dict, *, auth_header: str, verify_tls: bool, dry_run: bool
) -> bool:
    if dry_run:
        return False
    status, result = ces._es_request(
        es_url, f"/cve-remediation-assessment/_doc/{urllib.parse.quote(cve_id, safe='')}",
        method="PUT", body=doc, auth_header=auth_header, verify_tls=verify_tls,
    )
    if status not in (200, 201):
        print(f"WARN: upsert failed for {cve_id} ({status}): {result}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", "https://127.0.0.1:9200"))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER"))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD"))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--top-n", type=int, default=int(os.environ.get("CVE_DEEP_DIVE_TOP_N", "15")))
    parser.add_argument(
        "--architecture-file",
        default=os.environ.get("CVE_DEEP_DIVE_ARCHITECTURE_FILE", "stack-architecture.json"),
        help="Path to the generated stack-architecture.json snapshot (see generate-stack-architecture.py).",
    )
    parser.add_argument(
        "--ollama-url", default=os.environ.get("OLLAMA_URL", "http://192.168.1.8:11434"),
    )
    parser.add_argument(
        "--ollama-model", default=os.environ.get("OLLAMA_MODEL", "laguna-s-2.1:q4_k_m-ctx131k"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.es_user or not args.es_password:
        print("ERROR: --es-user/--es-password (or ES_FINDINGS_USER/ES_FINDINGS_PASSWORD) are required", file=sys.stderr)
        return 1

    auth_header = "Basic " + base64.b64encode(f"{args.es_user}:{args.es_password}".encode()).decode()
    verify_tls = not args.no_verify_tls
    architecture = load_architecture(args.architecture_file)

    shortlist = fetch_shortlist(args.elasticsearch_url, args.top_n, auth_header=auth_header, verify_tls=verify_tls)
    print(f"Deep-dive shortlist: {len(shortlist)} CVE(s) (KEV-listed or PoC-available, in production, top {args.top_n} by risk score)")

    assessed = 0
    errors = 0
    for cve in shortlist:
        cve_id = cve.get("_id")
        prompt = build_prompt(cve, architecture)
        try:
            raw = ces._call_ollama(args.ollama_url, args.ollama_model, prompt)
        except Exception as exc:  # noqa: BLE001 -- one bad call shouldn't kill the whole batch
            print(f"WARN: deep-dive LLM call failed for {cve_id}: {exc}", file=sys.stderr)
            errors += 1
            continue
        action, assessment_text = parse_assessment(raw)
        doc = {
            "cve_id": cve_id,
            "risk_score": cve.get("risk_score"),
            "risk_band": cve.get("risk_band"),
            "stacks": cve.get("stacks") or [],
            "zones": cve.get("zones") or [],
            "kev_listed": bool(cve.get("kev_listed")),
            "poc_available": bool(cve.get("poc_available")),
            "recommended_action": action or "INVESTIGATE",
            "assessment": assessment_text or raw.strip(),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "llm_provider": "ollama",
            "llm_model": args.ollama_model,
        }
        if upsert_assessment(args.elasticsearch_url, cve_id, doc, auth_header=auth_header, verify_tls=verify_tls, dry_run=args.dry_run):
            assessed += 1
        elif args.dry_run:
            assessed += 1
            print(f"[dry-run] {cve_id}: {action} -- {assessment_text[:120]}")

    print(f"Done -- assessed={assessed} errors={errors} dry_run={args.dry_run}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
