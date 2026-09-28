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
- Automated upstream-fix checking (Phase 12) — design decided and a
  live-tested `check_upstream_fixes.py` sketch written, queries OSV.dev
  daily for CVEs already accepted as risk pending an upstream fix; not
  yet wired into a systemd service/timer or deployed.
- Scoping CVE reporting to images actually in use (Phase 13 + Phase 14
  uvm-14-01/02/03) — **live**, and now genuinely holistic. Phase 13's
  `in_use` field (digest-exact + tag-exact fallback) was Portainer-only
  at first, which turned out to be blind to most of the platform's
  actual security/infra tier (only 9 real stacks are Portainer-registered
  — every security/infra stack was deliberately exempted for
  attack-surface reasons). Phase 14 added a second, self-reporting
  collector (`docker_live_usage_reporter`, strictly read-only against
  each host's own Docker socket, no SSH-based polling) for that exempt
  tier, deployed to 10 of 12 confirmed gap-list stacks. Result: Harbor
  CVEs correctly retained in the shortlist went from 356 to **2,313**
  (out of 4,413 in-production) once Wazuh's own manager/dashboard/
  indexer, the GVM/Greenbone scanner engine, OpenSearch, Grafana, and
  NetBox's images stopped being invisible to `in_use`.
- Harbor cleanup itself — the other half of Phase 13's original title —
  **built and live, dry-run only.** `harbor_cleanup.py` runs daily
  (`harbor-cleanup.timer`), identifying artifacts confirmed `in_use:
  false` for 7+ consecutive days (`artifact.not_in_use_since`) and
  logging what it *would* delete via Harbor's own artifact API —
  excluding the `pentagi` pentest-target project. Real deletion
  (`--execute`) stays off until the operator reviews a full grace
  period's worth of dry-run output by hand. `manifest.txt`
  auto-generation (uvm-14-07) stays explicitly deferred, per the plan's
  own design — not enough time has passed on the combined live-usage
  source to "trust it now."
