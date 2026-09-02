# Threat & Vulnerability Platform

## Status

**Live in production, Phases 1-11 built and deployed.** See `plan.md`
for the full build history (each phase records what was built, real bugs
found deploying it, and how it was verified live) and
`remediation-runbook.md` for how to actually work through the weekly
output.

Sources correlated: Harbor, GVM/Greenbone, and Wazuh findings. Security
Onion and T-Pot ingestion remain explicitly deferred (those source
systems need their own setup work first).

## What this is

A cross-cutting design that sits on top of `docs/opensearch-stack/`
(which stays scoped to that LXC's own infra) — correlating CVE findings
across every security tool in the lab into one view, enriched with real
threat-intel signals (CVSS/EPSS/KEV/PoC via `cve-mcp-server`), an
LLM-synthesized risk narrative, and (Phase 11) an architecture-aware
remediation call for the worst/most-exploitable subset.

## What's built and live

- `secpipe-stack` LXC — runs `cve_enrichment_sync` (daily correlation +
  narrative) and `cve_deep_dive` (weekly, architecture-aware remediation
  assessment for the top CVEs) as systemd timers.
- `unified-cve-exposure` — the correlated CVE index (Harbor + GVM +
  Wazuh), with `stacks[]`/`zones[]`/`in_production` threaded through.
- `stack-risk-summary` — a per-stack severity rollup (Phase 9).
- `cve-remediation-assessment` — architecture-aware remediation calls
  for the worst/most-exploitable CVEs (Phase 11), with a
  `mark_cve_resolved.py` workflow to record what's actually been done —
  see `remediation-runbook.md`.
- `Threat & Vulnerability Overview (UVM)` Grafana dashboard
  (`monitoring-stack`) — exploitability funnel, per-stack risk table, and
  the "Top CVEs Needing Attention" remediation panel (Phase 10).

## What's not built yet

- Security Onion / T-Pot ingestion (`*-events` index family) — needs its
  own session; those source systems aren't set up yet.
- A shared sync-library refactor across `harbor_findings_sync.py`/
  `gvm_findings_sync.py`/`wazuh_findings_sync.py`/`cve_enrichment_sync.py`
  (each still stdlib-only and independent) — deferred until a further
  source is added.
- OpenSearch Transform-job rollups (Phase 3, an explicit one-off
  departure from this repo's plain-Python-sync convention) — scoped but
  not step-blocked pending a live schema check.
