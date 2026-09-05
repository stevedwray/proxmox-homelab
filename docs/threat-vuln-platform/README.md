# Threat & Vulnerability Platform

## Status

**Planning complete, build starting 2026-08-18.** See `plan.md` for the
full design. Current phase scope: CVE correlation/enrichment on top of
the two sources already live (`harbor-findings`, `gvm-findings` in
`opensearch-stack`). Wazuh, Security Onion, and T-Pot ingestion are
explicitly deferred to a later session.

## What this is

A cross-cutting design that sits on top of `docs/opensearch-stack/`
(which stays scoped to that LXC's own infra) — correlating CVE findings
across every security tool in the lab into one view, enriched with real
threat-intel signals (CVSS/EPSS/KEV/PoC via `cve-mcp-server`) and an
LLM-synthesized risk narrative.

## What's built so far

- `docs/threat-vuln-platform/plan.md` — the design
- `terraform/secrets.common.enc.yaml` — `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` added (temporary LLM provider while the local LLM is
  occupied with benchmarking; see plan.md)

## What's not built yet

- `secpipe-stack` LXC (spec'd in plan.md, not yet scaffolded/deployed)
- `cve_enrichment_sync` role
- `unified-cve-exposure` index + dashboard
- Everything Wazuh/Security Onion/T-Pot (separate future session)
