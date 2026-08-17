# Threat & Vulnerability Reporting Platform — Plan

## Goal

A single correlated view of "what CVEs/threats affect us, how many places,
how exploitable, what's the priority" across every security tool in the
lab — starting with GVM (`gvm-findings`) and Harbor (`harbor-findings`),
already live in `opensearch-stack`, and later extending to Wazuh, Security
Onion, and the T-Pot honeypot.

This is intentionally bigger than `docs/opensearch-stack/`, which stays
scoped to that LXC's own infra (OpenSearch/Dashboards, OIDC, sizing). This
doc owns the cross-cutting ingestion/correlation/enrichment design that
spans multiple stacks.

## Phase scope (current)

**This phase: GVM + Harbor only.** Wazuh, Security Onion, and T-Pot
ingestion are explicitly deferred to a later session — those source
systems need their own setup work first (operator instruction,
2026-08-18). Don't build `wazuh_findings_ingest`/`so_events_ingest`/
`tpot_events_ingest` yet; the design below anticipates them but this
phase only ships the CVE-correlation/enrichment layer on top of the two
sources already live.

## Prior art (found during planning, reused not rebuilt)

A separate repo, `security-analysis` (not part of this repo), already
built a real sync pipeline for Wazuh/Security Onion/T-Pot — a shared
`secpipe_core` library (ES client, cursor/state tracking, setup-assets)
plus per-source `pipelines/{wazuh,security_onion,tpotce}/{sync,setup,
report,cli}.py`. Validated design decisions worth reusing when that phase
starts: incremental sync by `@timestamp` + `_id` tiebreaker, "never
advance cursor on a 0-doc run," destination index naming from each doc's
own timestamp (not sync runtime).

**Decided 2026-08-18: nothing from that pipeline's destination is being
migrated.** It targets a separate, standalone Elasticsearch (`my-elastic`,
`elastic-api.gibbsgreatly.xyz`, v9.2.1, real volume already in it —
`so-soc`/`so-zeek` in the tens of millions of docs) that has nothing worth
bringing over. Same for this repo's own (already decommissioned)
`elasticsearch-stack` — nothing there either. Both are ignored; the
Wazuh/SO/T-Pot ingestion work, when it starts, targets `opensearch-stack`
directly, designed fresh using the *patterns* above, not migrated data.

`security-analysis`'s `llm.py`/`report.py` are empty stubs — no
LLM/CVE-MCP integration exists anywhere yet. The enrichment design below
is new work.

**Real finding, not part of the architecture but worth recording**:
`wazuh-analysis/.env`, `so-analysis/.env`, and `tpotce-analysis/.env` all
contained live plaintext secrets (an Anthropic API key, an OpenAI/ChatGPT
key, several ES API keys). The Anthropic/OpenAI keys have been moved into
this repo's `terraform/secrets.common.enc.yaml` (see below) since they're
still in use; the ES API keys are irrelevant now that the destination
they authenticated to is being ignored. Operator decision: no rotation
needed.

## Architecture: two index families, not one pile

| Family | Sources (this phase / later) | Shape | Pattern |
|---|---|---|---|
| **`*-findings`** | `harbor-findings`, `gvm-findings` (live) / later: `wazuh-findings` (vulnerability-detector CVE alerts only, split out of Wazuh's general alert stream) | asset-state, upsert by `(source, finding_id, target)`, `first_seen`/`last_seen` | Already built — `es_findings_ingest`, `gvm_findings_ingest` roles |
| **`*-events`** | later: `wazuh-events`, `so-alerts`/`so-soc`/`so-zeek` (filtered, NOT the raw firehose), `tpot-events` | time-series, append-only, ILM-managed | Not built this phase |
| **`unified-cve-exposure`** | derived, cross-source | one doc per CVE ID, aggregates every `*-findings` (and later CVE-bearing `*-events`) occurrence | **New — this phase** |

Rationale for the split: GVM/Harbor answer "is this CVE currently true of
this asset" (long-lived state, no time filter — the exact bug class fixed
in both dashboards already, see `docs/opensearch-stack/README.md`).
Wazuh/SO/T-Pot mostly answer "this happened at this instant" (naturally
time-bucketed, and SO's zeek/soc alone would be orders of magnitude
larger than everything else combined — keep that firehose out of
`opensearch-stack` entirely; only bring in the same filtered/normalized
slice `wazuh-analysis`'s README already validated, ~90% noise reduction).

## `unified-cve-exposure` index design

One document per CVE ID (`_id` = the CVE string itself, e.g.
`CVE-2026-27171`):

```json
{
  "cve_id": "CVE-2026-27171",
  "sources": [
    {"source": "harbor", "finding_id": "CVE-2026-27171", "count": 47},
    {"source": "greenbone", "finding_id": "CVE-2026-27171", "count": 3}
  ],
  "total_instances": 50,
  "cvss_score": 5.5,
  "cvss_vector": "CVSS:3.1/...",
  "epss_score": 0.0119,
  "epss_percentile": 65.3,
  "kev_listed": false,
  "poc_available": false,
  "risk_score": 7.82,
  "risk_band": "LOW",
  "risk_urgency": "SCHEDULE FOR NEXT CYCLE",
  "triage_raw_text": "=== CVE Triage: ... (full triage_cve output, for display)",
  "llm_narrative": "...(short synthesized risk note, this phase via Anthropic/OpenAI)",
  "llm_provider": "anthropic",
  "enriched_at": "2026-08-18T...",
  "enrichment_stale": false
}
```

`sources[]` and `total_instances` are computed by aggregating the
`*-findings` indices (terms agg on the CVE field, matching the
`harbor-findings-by-cve`/`gvm-findings-by-cve` dashboard panels already
built). The CVSS/EPSS/KEV/PoC/risk fields come from CVE-MCP's
`triage_cve` call. `llm_narrative` is the one new synthesis step (see
below).

## CVE-MCP integration (confirmed live, not assumed)

`cve-mcp-server` is live in production right now on `mcp-utility-stack`
(`192.168.50.10:8000`, `ai_seg`) — confirmed via a real MCP `tools/list`
call during this planning session, not from docs. 28 tools available;
the one that matters most here:

**`triage_cve`** — one-call orchestrator. Fans out NVD (CVSS), EPSS, CISA
KEV, and (depth != "quick") public PoC discovery concurrently, returns a
composite 0–100 risk score with a KEV hard-override (KEV-listed = always
≥76/CRITICAL). Confirmed live output shape (plain formatted text, not
JSON — needs parsing):

```
=== CVE Triage: CVE-2011-3374 ===
RISK SCORE: 7.82/100  (LOW)
Urgency:    SCHEDULE FOR NEXT CYCLE
SIGNALS:
  CVSS:   3.7 LOW
  Vector: CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:L/A:N
  EPSS:   1.19% (percentile 65.3th, as of 2026-08-17)
  KEV:    NO
  PoC:    NONE (No public PoC found) — 0 public source(s)
```

Use `depth: "standard"` by default (adds PoC discovery over `"quick"`;
`"deep"` adds an SSVC decision — not needed for this phase). One call per
CVE, not four separate tool calls — minimizes API load on upstream
NVD/EPSS/KEV/GitHub.

**Note (PentAGI-adjacent, don't confuse the two)**: `docs/pentagi-stack/
cve-mcp-integration-plan.md` is about wiring PentAGI's own agents to use
this server as an MCP client — status "scoped, not started" there. This
plan doesn't touch that; it calls `cve-mcp-server`'s HTTP endpoint
directly, same as that doc's own confirmed-live handshake test did.

## LLM narrative step (temporary provider substitution)

The local LLM is currently occupied with benchmarking work and isn't
available for testing this. Operator decision 2026-08-18: use the
Anthropic and OpenAI API keys recovered from the exposed `.env` files
(now in `terraform/secrets.common.enc.yaml` as `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`) for testing — "may as well use them up." This is a
**temporary substitution, not a design decision** — the enrichment
script's LLM call should be provider-swappable (a thin adapter, not
hardcoded to one SDK) so switching back to the local Ollama runtime later
is a config change, not a rewrite, matching this project's established
Ollama-only runtime policy for everything else.

Narrative step: feed `triage_cve`'s raw text plus the finding's own
context (which sources reported it, how many instances, which
hosts/artifacts) to the LLM, ask for a short (2-4 sentence) prioritized
risk note. This is what actually makes the dashboard panel readable at a
glance instead of just another numbers table.

## New LXC: `secpipe-stack`

Placement: `ai_seg` (VLAN 50) — same zone as `mcp-utility-stack`, so the
CVE-MCP calls (the hot path) need no new cross-zone firewall rule at all.
Only one new rule needed: `ai_seg → infra_seg:9200` (OpenSearch) — this
was already anticipated and explicitly deferred in
`project_harbor_alerting_automation_plan` memory ("ai_seg -> infra_seg:9200
for findings-mcp, is Stage 10/Phase 8"), so this isn't a surprise
addition. Internet egress for NVD/EPSS/KEV/GitHub (via CVE-MCP) and
Anthropic/OpenAI (direct) — same egress profile `mcp-utility-stack`
already has and depends on.

vmid/IP: next free slot in `ai_seg` on `pve` — `mcp-utility-stack`=50011
(`.10`), `ai-services-stack`=50013 (`.11`); **50012 / `192.168.50.12`**
is free and is what this stack should use.

```yaml
hostname: secpipe-stack
ip_address: "${lab_ip_secpipe}/24"
gateway: "${lab_gw_ai}"
dns_server: "${lab_gw_ai}"
network:
  zone: ai_seg
vmid: 50012
cores: 2
memory: 1024
swap: 512
rootfs_size: 10
```

No Docker/`docker_mount` needed — this runs plain Python + systemd
timers, same pattern as `harbor_findings_sync.py`/`gvm_findings_sync.py`
today (no Docker Compose service to speak of, just a scheduled script).
Sized like `mcp-utility-stack` (its closest analog: lightweight
Python/API utility, not a scanner) — revisit if the LLM-call volume ever
makes this CPU-bound.

## `cve_enrichment_sync` role (new, this phase)

Mirrors `es_findings_ingest`/`gvm_findings_ingest`'s shape (role,
`defaults/main.yml`, `tasks/main.yml`, `files/*.py`, systemd
service+timer, scoped OpenSearch credential via the existing
`es_findings_writer` role pattern — reads `harbor-findings`/`gvm-findings`,
writes `unified-cve-exposure`).

1. Query `harbor-findings` (`finding_id`) and `gvm-findings` (`cve`) for
   distinct CVE IDs and per-CVE instance counts (same terms aggregation
   already proven in both dashboards' "by CVE" panels).
2. For each CVE without a fresh `unified-cve-exposure` doc (or past a
   re-check interval — CVSS/EPSS/KEV change over time, this isn't a
   one-shot), call `triage_cve` via `cve-mcp-server`, parse the text
   response into structured fields.
3. Call the LLM adapter (Anthropic/OpenAI for now) for the narrative.
4. Upsert into `unified-cve-exposure`.
5. Write back onto each originating finding's own `severity_assessed`/
   `assessed_reason`/`assessed_by`/`assessed_at` fields — this is exactly
   the compatibility constraint the operator set when Harbor ingestion
   was first built (index schema deliberately kept ready for "other
   tools to do further triage and research on the CVE which themselves
   would be collected into other indices"). Use the same scripted-upsert
   `putAll` pattern already fixed in both `*_findings_sync.py` scripts
   (2026-08-18) so this doesn't silently fail to backfill the way CVSS
   capture initially did.

## Dashboard

New "Threat & Vulnerability Overview" dashboard on `unified-cve-exposure`:
KEV-listed criticals, top CVEs by `risk_score`, top CVEs by cross-source
`total_instances`, the LLM narrative as a text panel per selected CVE.
Same Global-tenant-transplant technique and generous panel sizing already
proven for the Harbor/GVM dashboards.

## Open items / not decided yet

- Exact re-check interval for already-enriched CVEs (EPSS moves daily;
  daily re-triage of every known CVE may be excessive — needs a real
  number once volume is known).
- Whether `severity_assessed` write-back should require a
  human-in-the-loop confirmation step before it's treated as
  authoritative, or whether LLM-assessed is trusted directly. Not decided;
  default to writing it with `assessed_by: "cve_enrichment_sync"` so it's
  clearly attributable and distinguishable from a human assessment later.
- Wazuh/Security Onion/T-Pot ingestion design (the `*-events` family) —
  deferred to its own session per operator instruction; the shared
  sync-library refactor (extracting the ~90%-duplicated logic already
  visible between `harbor_findings_sync.py` and `gvm_findings_sync.py`,
  informed by `security-analysis`'s `secpipe_core` design) should happen
  when that third source actually gets built, not before.
