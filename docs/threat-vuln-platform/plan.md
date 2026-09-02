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

**Phase 1 (GVM + Harbor + `unified-cve-exposure`): done, live** — see
below. **Phase 2 (Wazuh): open, operator go-ahead given 2026-09-01** —
`wazuh-stack`'s own agent pilot rollout (see `docs/wazuh-stack/README.md`)
finished 2026-08-29, so the source system this phase needs now exists.
Security Onion and T-Pot ingestion remain deferred — those source systems
still need their own setup work first. Phase 2's step-by-step plan is in
its own section near the bottom of this file
(["Phase 2: Wazuh findings ingestion"](#phase-2-wazuh-findings-ingestion-this-phase)).

Operator decisions locked in for Phase 2, 2026-09-01:

- **Source**: the live `wazuh-stack` (6 enrolled agents), not the older,
  separate Wazuh instance `wazuh-analysis` (a different repo, not part of
  this one) was built against — that instance is retired/irrelevant here.
- **Rollups**: port to OpenSearch's own native Transform-job feature
  (`_plugins/_transform`), not a plain Python batch job — a deliberate
  departure from every existing sync in this repo (`harbor_findings_sync.py`/
  `gvm_findings_sync.py`/`cve_enrichment_sync.py` are all systemd-timer
  Python), because it's the closer analog to what `wazuh-analysis` already
  validated (Elasticsearch continuous Transforms) and nothing here has
  exercised this OpenSearch feature yet — treat the exact job schema as
  unverified until confirmed live against this cluster's real OpenSearch
  version (see Phase 3 below).
- **Harbor/GVM scope**: once the Wazuh pipeline's rollup approach is
  proven, apply the same periodic rollup treatment to `harbor-findings`/
  `gvm-findings` too, and fold all of it into the existing "Threat &
  Vulnerability Overview" dashboard rather than building a separate one.

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
  Wazuh is now scoped below (Phase 2); Security Onion/T-Pot remain
  deferred. The shared sync-library refactor (extracting the
  ~90%-duplicated logic already visible between `harbor_findings_sync.py`
  and `gvm_findings_sync.py`, informed by `security-analysis`'s
  `secpipe_core` design) should happen once Wazuh is the third
  `*_findings_ingest`-shaped role, not before — Phase 2 below
  deliberately does NOT refactor this yet, to keep its own diff reviewable.

## Phase 2: Wazuh findings ingestion (this phase)

### Scope: CVE findings only, not the general alert stream

`wazuh-analysis` (a separate repo, prior art only — see above) built a
pipeline for Wazuh's *general* alert stream: everything `rule.level >= 7`
(auth failures, file-integrity changes, rootcheck, SCA, vulnerability
alerts all mixed together), normalized and rolled up into daily/weekly/
CVE-tracking/auth-failure summaries. That's real, validated design, but
it's the `*-events` shape (time-series, append-only) — a bigger piece of
work than this phase takes on.

**This phase builds the narrower, higher-value slice first**: a new
`wazuh_findings_ingest` role, shaped exactly like `es_findings_ingest`/
`gvm_findings_ingest`, that pulls only Wazuh's `vulnerability-detector`
alerts (installed-package CVEs, one of the five alert types
`wazuh-analysis`'s own README table already separates out) into a new
`wazuh-findings` index — the `*-findings` asset-state family, not
`*-events`. This is the exact "third, genuinely different angle" already
identified as the next step in `docs/wazuh-stack/README.md`'s "What's not
built yet" section: Harbor answers "which container images have this
CVE", GVM answers "which network hosts have this CVE", Wazuh answers
"which hosts have this CVE **in an installed OS package**" — three
different exposure surfaces for the same CVE ID, exactly what
`unified-cve-exposure`'s cross-source correlation was designed for.

The general alert stream (auth failures, FIM, rootcheck, SCA — the
`*-events` shape, plus the OpenSearch Transform-job rollups) is Phase 3,
after this phase's pattern is proven live. Building both at once would
make this phase's diff much harder to review and validate independently.

### Architecture

```text
Wazuh Indexer (wazuh-stack, infra_seg, :9200)
    │  scoped read-only user, rule.groups:vulnerability-detector,
    │  incremental by @timestamp (wazuh-analysis's proven cursor pattern)
    ▼
wazuh_findings_sync.py  (runs ON wazuh-stack itself — same "colocated
    │                     with the source, pushes to opensearch-stack
    │                     remotely" shape as es_findings_ingest/
    │                     gvm_findings_ingest; no new firewall rule
    │                     needed, wazuh-stack and opensearch-stack are
    │                     both already in infra_seg)
    ▼
opensearch-stack: wazuh-findings index (normalized via
    wazuh-findings-normalize ingest pipeline)
    │
    ▼
cve_enrichment_sync (secpipe-stack) — extended to aggregate CVE IDs from
    THREE sources (harbor-findings, gvm-findings, wazuh-findings) instead
    of two, writing severity_assessed back onto wazuh-findings docs too
```

No new MikroTik rule needed for this phase — verified against the
existing zone layout (`wazuh-stack` is `infra_seg`, `opensearch-stack` is
`infra_seg`, same zone as every other `*_findings_ingest` role's own
same-zone hop).

### `wazuh-findings` document shape and dedup key

Same `(source, finding_id, target)` upsert shape as `harbor-findings`/
`gvm-findings` (see the architecture table above). For Wazuh's
vulnerability-detector alerts specifically:

- `finding_id` = the CVE ID (`data.vulnerability.cve`)
- `target` = `{agent_id}/{package_name}` — the same CVE can affect
  multiple packages on the same host, and the same package can exist on
  multiple agents; both need their own document
- `_id` = `wazuh::{finding_id}::{target}` (identical scheme to Harbor's
  `source::finding_id::artifact_key` and GVM's `source::finding_id::host:port`)

Field source mapping (confirmed against `wazuh-analysis`'s own working
ingest pipeline, `elasticsearch/pipelines/wazuh-alerts-normalize.json` —
these are real field paths already validated against live Wazuh 4.x
alert data, not guessed):

| `wazuh-findings` field | Wazuh alert source field |
|---|---|
| `finding_id` | `data.vulnerability.cve` |
| `severity_raw` | `data.vulnerability.severity` |
| `cvss_score` | `data.vulnerability.cvss.cvss3.base_score`, fall back to `.cvss2.base_score` if v3 absent (same v3-preferred-over-v2 rule already used in `harbor_findings_sync.py`'s `_extract_cvss_score`) |
| `package` | `data.vulnerability.package.name` |
| `package_version` | `data.vulnerability.package.version` |
| `status` | `data.vulnerability.status` (Wazuh's own field — values include `Active`/`Solved`) |
| `target.agent_id` | `agent.id` |
| `target.agent_name` | `agent.name` |
| `scan_time` | `@timestamp` of the alert |

**Open question, deliberately not resolved here — verify on first live
run rather than guess**: does `vulnerability-detector` re-emit an alert
for a still-active CVE on every scan cycle, or only on a state
transition (new detection / marked Solved)? This changes whether
`last_seen` naturally advances daily or needs a separate "still active"
reassertion query. `wazuh-findings-01` below includes a verification gate
for exactly this — check it before trusting `last_seen` staleness for
any alerting built on top of this index later.

---

## CORRECTION 2026-09-01: wrong source index, found on the first live production run

Everything above this line describes the plan as originally written and
first deployed. Running it for real against production `wazuh-stack`
(6 agents, real data) surfaced a genuine design bug, not a guess this
time — worth recording in full rather than quietly rewriting history.

**What happened**: the first live run of `wazuh_findings_sync.py`
completed cleanly (`docs_scanned=1705 findings_indexed=1705 errors=0`) —
looked like success. Checking the actual data (per this doc's own
"Deploying and validating" step 2 — never trust a clean exit code alone)
found two real problems:

1. **All 1700 resulting documents had `status: "Solved"` — zero
   `Active`.** Querying `wazuh-alerts-4.x-*` for
   `rule.groups:vulnerability-detector` (the design transcribed from
   `wazuh-analysis`'s own pipeline, and the mapping table above) only
   captures Wazuh's alert *log* — on this deployment that turned out to
   be almost entirely historical "Solved" state-transition
   notifications, not an ongoing signal of current active state.
2. **Only 5 of 7 real agents were represented.** `pve` (the single
   highest-value host in the whole rollout — see
   `docs/wazuh-stack/README.md`) and `wazuh.manager` itself were
   completely absent.

**Root cause**: Wazuh 4.14.7 (this deployment's real version) keeps
current vulnerability state — what's genuinely unsolved right now, per
agent — in a separate, newer-schema index family:
`wazuh-states-vulnerabilities-*` (already referenced, for a different
reason, in `reference_wazuh_states_index_per_agent_field` memory — the
`-wazuh.manager` suffix is the writing node, not a scope filter; a
single index holds every agent's data). Confirmed live: **2745 real
documents covering all 7 agents**, using a different, top-level-field
("ECS-like") schema — `vulnerability.id`, `vulnerability.severity`,
`vulnerability.score.base` (a real number, not the string
`data.vulnerability.cvss.cvss3.base_score` would have been), `package.name`,
`package.version`, `agent.id`, `agent.name`, `vulnerability.detected_at` —
not the classic dotted `data.vulnerability.*` alert schema
`wazuh-analysis`'s pipeline (built against an older/different Wazuh
deployment) assumed applied here too.

**This also fully resolves the "open question" above, differently than
planned**: `wazuh-states-vulnerabilities-*` is a genuine current-state
snapshot, not an append-only log — Wazuh's own vulnerability-detector
module removes a row once the CVE is actually resolved. That means mere
presence in a full pull already means "still active," and `last_seen`
naturally advances every run a CVE is still present and naturally goes
stale once Wazuh removes it — the same staleness-by-omission signal
Harbor's/GVM's own findings already carry. No two-day empirical check
needed; no separate `status` field needed either (dropped from the
mapping — being present in this index at all IS the "active" signal).

**Fix, applied directly (not deferred to a follow-up plan pass)**:
`wazuh_findings_sync.py` rewritten to do a **full pull** of
`wazuh-states-vulnerabilities-*` every run (`match_all` + `search_after`
pagination, no query filter, no incremental cursor/lookback window at
all) — the same shape `harbor_findings_sync.py`'s full Harbor-catalog
walk and `gvm_findings_sync.py`'s full current-Results pull already use.
At ~2,700 documents this is cheap; there's no natural "last modified"
field on this index to cursor on anyway. Updated field mapping:

| `wazuh-findings` field | Real source field (`wazuh-states-vulnerabilities-*`) |
|---|---|
| `finding_id` | `vulnerability.id` |
| `severity_raw` | `vulnerability.severity` |
| `cvss_score` | `vulnerability.score.base` (already numeric) |
| `package` | `package.name` |
| `package_version` | `package.version` |
| `description` | `vulnerability.description`, truncated 2000 chars (new field, matches Harbor's own truncation convention) |
| `target.agent_id` | `agent.id` |
| `target.agent_name` | `agent.name` |
| `scan_time` | `vulnerability.detected_at` |

Also fixed as part of the same correction: the Wazuh-Indexer-side scoped
role's `index_permissions` (`wazuh_findings_ingest_wazuh_role_name`)
updated from `wazuh-alerts-*` to `wazuh-states-vulnerabilities-*`, and —
a second, independent real bug found while fixing the first — **that
role-PUT task was incorrectly gated behind "credential file doesn't
exist yet,"** the same idempotency mistake already documented and fixed
once for Harbor/GVM (`es_findings_writer`'s own role-PUT is correctly
unconditional). Left as originally written, this index-pattern fix would
have silently never reapplied to a wazuh-stack that had already
completed its first deploy. Fixed by splitting the reachability
check/role-PUT (now unconditional, idempotent) from the
password-generation/user-creation/credential-write steps (still
correctly gated on "credential doesn't exist yet," so a rotate never
happens by accident).

`wazuh-findings-05`'s index template also updated: `status` field
removed (no longer produced), `description` field added (`text`).

**Not yet re-verified live** at the time this section was written — the
fix needs another `provision.sh --stack wazuh-stack` run plus a manual
`systemctl start wazuh-findings-ingest.service` to confirm real data
now shows all 7 agents and genuinely active CVEs (Critical/High counts
that make sense for a live fleet, not a historical "Solved" log).

## CORRECTION 2, same day: a third real idempotency bug, found running the fix above

Re-running `provision.sh --stack wazuh-stack` to apply the correction
above (`failed=0`, `changed=18`) looked clean, but a manual sync run
immediately failed: `urllib.error.HTTPError: HTTP Error 401:
Unauthorized`, from `wazuh_findings_sync.py`'s very first request.

**Root cause, confirmed live**: querying Wazuh's own security API
directly found the role (`wazuh_findings_reader`) present and correctly
updated — the unconditional-role-PUT fix from Correction 1 worked — but
the **user** (`wazuh_findings_ingest`) had been deleted entirely
(`"status": "NOT_FOUND"`), while the local credential file on
`wazuh-stack` still held a password for that now-nonexistent user.
`deploy-wazuh-stack.yml`'s own "Wire real Authentik OIDC onto the Wazuh
dashboard" play conditionally runs `securityadmin.sh -cd $CONFIG_DIR
-icl` — a **full security-config-directory reapply** — whenever its own
OIDC-domain/all-access-wildcard check trips. That reapply restores
Wazuh Indexer's entire security config from the on-disk
`internal_users.yml` this playbook writes (`admin`/`kibanaserver`/
`kibanaro` only, a literal transcription of upstream's vendor file) —
silently deleting any user that only ever existed via the live REST API,
this role's own included. This ran on the *first* deploy too, presumably
consistently every deploy — the first sync worked anyway purely because
that manual test happened to run before the user got wiped, not because
the user survived.

**The actual bug, generalized**: the local credential-file `stat` check
this role used for "does this user already exist, skip creating it
again" — the exact same idempotent shape every sibling role
(`es_findings_ingest`/`gvm_findings_ingest`/`cve_enrichment_sync`) uses
for their own OpenSearch-side users — is a cheap proxy for remote state,
and it goes stale the moment something *else* (here, Wazuh's own OIDC
play) can delete the remote object independently of the local file. This
is the same principle already learned and documented once this session
(Correction 1, for the role-PUT being wrongly gated) and once before in
this repo (`docs/wazuh-stack/README.md`'s own "idempotency checks need
to verify real state, not a cheap proxy for it" lesson, for agent
enrollment) — worth remembering as a recurring failure mode specifically
around Wazuh, whose own OIDC play has this real config-reapply side
effect that OpenSearch's own equivalent security plugin does not
exhibit under normal operation (sibling roles targeting `opensearch-stack`
directly have not hit this class of bug).

**Fix, applied directly**: replaced the local `ansible.builtin.stat`
check with a live `GET /_plugins/_security/api/internalusers/
wazuh_findings_ingest` against the Wazuh Indexer itself
(`status_code: [200, 404]`), and gated password-generation/user-creation/
credential-file-write on that GET returning `404`, not on the local
file's existence. This means every deploy now correctly detects and
repairs a wiped user, no matter what wiped it or when — including a
future OIDC-play run.

**Not yet re-verified live at the time this section was written** — a
third `provision.sh --stack wazuh-stack` run is needed to confirm the
user gets recreated and a manual sync succeeds end-to-end this time.

## Verified live end-to-end, 2026-09-01 — Phase 2 is genuinely done

Third `provision.sh --stack wazuh-stack` run: `failed=0, changed=16`.
Confirmed live: `GET /_plugins/_security/api/internalusers/
wazuh_findings_ingest` now returns the user, correctly bound to
`wazuh_findings_reader`. Manual sync run:
`docs_scanned=2745 findings_indexed=2745 errors=0` — exactly matching
the real document count on the Wazuh Indexer, all 7 agents present
(`apt-cacher-stack`/`authentik-stack`/`harbor-stack`/`proxy-stack`/
`technitium-stack`/`pve.gibbsgreatly.xyz`/`wazuh.manager`), real numeric
CVSS scores, real severity spread (Critical 99, High 1419, Medium 1687,
Low 241).

**One more real cleanup needed and done**: the index held 4440 documents
before this, not 2745 — the two earlier wrong-source runs (querying
`wazuh-alerts-*`) had written 1700 stale "Solved"-only documents whose
`agent_id` values (classic alert schema's `agent.id`, e.g. `"005"`) don't
match the states-index schema's own `agent.id` numbering (e.g. `"006"`
for `pve`), so they never collided on `_id` and just sat there polluting
the index. `DELETE /wazuh-findings` + one more sync run resolved this
cleanly (documents are fully reconstructable from source, so a full
wipe-and-resync carries no real risk here) — confirmed back down to
exactly 2745 afterward, idempotent on a second manual run.

**Also verified, the real point of this whole phase**: `secpipe-stack`
redeployed (`provision.sh --stack secpipe-stack`, `failed=0, changed=2`)
to pick up the 3-source `cve_enrichment_sync` extension, then a manual
run (`--max-cves 3 --force-refresh`, kept small to bound LLM/API cost)
confirmed it end to end: log line reads
`Found 10070 distinct CVEs across 3 findings indices` (not 2) —
`unified-cve-exposure` now shows real documents with
`sources: [{"source": "harbor", "count": 71}, {"source": "wazuh", "count": 24}]`
and a correctly summed `total_instances: 95` for genuinely overlapping
CVEs, and the write-back half works too: the same CVE's `wazuh-findings`
document now carries `severity_assessed`/`assessed_by: "cve_enrichment_sync"`/
`assessed_at` populated, exactly the same write-back shape Harbor/GVM's
own findings already had.

**Phase 2 is complete and live in production, not just built.** No known
open items remain from the original plan's "Deploying and validating"
section. Phase 2B (general Wazuh alert stream) and Phase 3 (OpenSearch
Transform-job rollups) remain the next, separate, not-yet-started work.

### wazuh-findings-01: provision.sh key whitelist

```yaml
id: wazuh-findings-01-provision-keys
title: Add WAZUH_FINDINGS_INGEST_KEYS to provision.sh's stack.yaml passthrough
depends_on: []

change: >
  In scripts/provision.sh, add a new tuple WAZUH_FINDINGS_INGEST_KEYS =
  ("wazuh_findings_ingest_enabled",) immediately after the existing
  GVM_FINDINGS_INGEST_KEYS tuple (before CVE_ENRICHMENT_SYNC_KEYS), and
  add a matching "for key in WAZUH_FINDINGS_INGEST_KEYS:" loop block
  immediately after the existing "for key in GVM_FINDINGS_INGEST_KEYS:"
  loop (before the CVE_ENRICHMENT_SYNC_KEYS loop) -- copy the GVM loop's
  body exactly, only the tuple name changes. Without this,
  wazuh_findings_ingest_enabled: true in wazuh-stack's stack.yaml is
  silently never forwarded to Ansible, exactly the bug already found and
  fixed for es_findings_ingest_enabled on 2026-08-17.

scope:
  allowed_paths:
    - scripts/provision.sh
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run -- code edit only in this step"

gates:
  - id: bash-syntax
    cmd: "bash -n scripts/provision.sh"
    expect: "exit 0"
    critical: true
  - id: keys-present
    cmd: "grep -c 'WAZUH_FINDINGS_INGEST_KEYS' scripts/provision.sh"
    expect: "2"
    critical: true
```

**Correction, found executing this step**: `scripts/provision.sh` is a bash
script with an embedded Python heredoc (`python3 - ... <<'PY'`), not a
plain Python file — a `python3 -m py_compile` gate against the whole file
was wrong (it fails on the shell syntax around the heredoc, not on the
edit itself). `bash -n` is the correct syntax gate for the file as a
whole; the embedded Python block was separately confirmed to compile
cleanly by extracting it between the heredoc markers.

### wazuh-findings-02: new role scaffold — defaults

```yaml
id: wazuh-findings-02-role-defaults
title: Create wazuh_findings_ingest role defaults/main.yml
depends_on: []

change: >
  Create terraform/lxc/ansible/roles/wazuh_findings_ingest/defaults/main.yml
  with exactly the content below -- a direct adaptation of
  es_findings_ingest/defaults/main.yml's shape, substituting Wazuh's own
  indexer as the source instead of Harbor's API.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/defaults/main.yml
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/ansible/roles/wazuh_findings_ingest/defaults/main.yml'))\""
    expect: "exit 0"
    critical: true
```

Literal content for `defaults/main.yml`:

```yaml
---
# Defaults for wazuh_findings_ingest role -- see docs/threat-vuln-platform/
# plan.md "Phase 2: Wazuh findings ingestion". Explicit opt-in, matching
# es_findings_ingest_enabled/gvm_findings_ingest_enabled's pattern -- only
# ever included on wazuh-stack, gated by a flag so it never silently
# attaches to any other host that happens to reuse this role file.
wazuh_findings_ingest_enabled: false

wazuh_findings_ingest_dir: /opt/wazuh-findings-ingest
wazuh_findings_ingest_log_path: /var/log/wazuh-findings-ingest.log

# Runs on wazuh-stack itself -- independent of es_findings_ingest's own
# 05:30 UTC and gvm_findings_ingest's own schedule (different hosts, no
# chaining dependency). Wazuh's vulnerability-detector feed updates
# roughly daily; 06:00 UTC gives it a comfortable margin after midnight
# rollover with no other known dependency to wait on.
wazuh_findings_ingest_on_calendar: "*-*-* 06:00:00"

# How far back to re-scan on every incremental run, to catch
# late-arriving/reprocessed alerts -- same reasoning and same default
# (600s) as wazuh-analysis's own SYNC_LOOKBACK_SECONDS, already validated
# against real Wazuh alert timing behavior.
wazuh_findings_ingest_lookback_seconds: 600

# --- Wazuh Indexer connection (source) -----------------------------------
# Colocated on the same host this role is installed on (wazuh-stack) --
# addressed via its own routable IP, not localhost, matching
# es_findings_ingest's own reasoning for why harbor_findings_sync.py
# addresses Harbor via LAB_IP_HARBOR rather than 127.0.0.1 (the sync
# script runs on the LXC host, Wazuh's indexer runs inside Docker on that
# same host, published on the host's real IP -- addressing it the same
# way as every other role stays consistent and avoids container-network
# assumptions).
wazuh_findings_ingest_wazuh_host: "{{ lookup('env', 'LAB_IP_WAZUH') | mandatory('LAB_IP_WAZUH env var is required') }}"
wazuh_findings_ingest_wazuh_url: "https://{{ wazuh_findings_ingest_wazuh_host }}:9200"
wazuh_findings_ingest_wazuh_no_verify_tls: true

# Wazuh Indexer admin superuser -- needed only to bootstrap this role's
# own scoped read-only Indexer user. Never used at runtime by
# wazuh_findings_sync.py, which only ever uses the scoped credential
# written locally to wazuh_findings_ingest_dir.
wazuh_findings_ingest_wazuh_admin_user: admin
wazuh_findings_ingest_wazuh_admin_password: "{{ lookup('env', 'WAZUH_INDEXER_ADMIN_PASSWORD') | mandatory('WAZUH_INDEXER_ADMIN_PASSWORD env var is required') }}"

# Scoped Wazuh Indexer internal user this role provisions for itself --
# read-only on wazuh-alerts-*, never the admin superuser. Wazuh's own
# Indexer is a plain Wazuh-branded build of OpenSearch with the same
# security plugin opensearch-stack uses -- the same
# _plugins/_security/api/roles + .../internalusers REST endpoints are
# expected to work identically post-boot, but this is UNVERIFIED against
# this specific product's build until wazuh-findings-03 actually runs
# live; if it doesn't, fall back to a file-based internal_users.yml entry
# matching deploy-wazuh-stack.yml's own existing pattern instead.
wazuh_findings_ingest_wazuh_role_name: wazuh_findings_reader
wazuh_findings_ingest_wazuh_user_name: wazuh_findings_ingest

# --- OpenSearch connection (destination) ---------------------------------
# Identical target/reasoning to every other *_findings_ingest role.
wazuh_findings_ingest_elasticsearch_host: "{{ lookup('env', 'LAB_IP_OPENSEARCH') | mandatory('LAB_IP_OPENSEARCH env var is required') }}"
wazuh_findings_ingest_elasticsearch_url: "https://{{ wazuh_findings_ingest_elasticsearch_host }}:9200"
wazuh_findings_ingest_es_no_verify_tls: true

wazuh_findings_ingest_elastic_admin_user: admin
wazuh_findings_ingest_elastic_admin_password: "{{ lookup('env', 'OPENSEARCH_ADMIN_PASSWORD') | mandatory('OPENSEARCH_ADMIN_PASSWORD env var is required') }}"

# Reuses es_findings_ingest's own es_findings_writer OpenSearch role
# (this role's own tasks/main.yml extends its index_patterns to include
# wazuh-findings*), same technique cve_enrichment_sync already used to
# add unified-cve-exposure* -- a distinct internal-user identity keeps
# this role's credential independently rotatable/revocable.
wazuh_findings_ingest_es_role_name: es_findings_writer
wazuh_findings_ingest_es_user_name: wazuh_findings_ingest
```

### wazuh-findings-03: role scaffold — tasks, handlers, templates

```yaml
id: wazuh-findings-03-role-tasks
title: Create wazuh_findings_ingest role tasks/handlers/templates
depends_on: [wazuh-findings-02-role-defaults, wazuh-findings-04-sync-script, wazuh-findings-05-assets]

change: >
  Create terraform/lxc/ansible/roles/wazuh_findings_ingest/tasks/main.yml,
  handlers/main.yml, templates/wazuh-findings-ingest.service.j2, and
  templates/wazuh-findings-ingest.timer.j2 with exactly the content below
  -- a direct adaptation of es_findings_ingest's own four files, with the
  Harbor-robot-creation block replaced by a Wazuh-Indexer-scoped-user
  creation block (same shape, different product), and the es_findings_writer
  extension task's index_patterns list including "wazuh-findings*".

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/tasks/main.yml
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/handlers/main.yml
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/templates/wazuh-findings-ingest.service.j2
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/templates/wazuh-findings-ingest.timer.j2
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply / ansible-playbook run against pve or pve-test-vm -- file creation only in this step"

gates:
  - id: yaml-syntax-tasks
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/ansible/roles/wazuh_findings_ingest/tasks/main.yml'))\""
    expect: "exit 0"
    critical: true
  - id: yaml-syntax-handlers
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/ansible/roles/wazuh_findings_ingest/handlers/main.yml'))\""
    expect: "exit 0"
    critical: true
```

Literal content for `handlers/main.yml` (byte-for-byte identical to every
other role's handler in this family):

```yaml
---
- name: Reload systemd
  ansible.builtin.systemd:
    daemon_reload: true
```

Literal content for `templates/wazuh-findings-ingest.service.j2`:

```ini
[Unit]
Description=Wazuh vulnerability-detector findings sync -> OpenSearch (wazuh_findings_ingest)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=WAZUH_URL={{ wazuh_findings_ingest_wazuh_url }}
Environment=WAZUH_NO_VERIFY_TLS={{ wazuh_findings_ingest_wazuh_no_verify_tls | ternary('1', '0') }}
Environment=SYNC_LOOKBACK_SECONDS={{ wazuh_findings_ingest_lookback_seconds }}
Environment=ELASTICSEARCH_URL={{ wazuh_findings_ingest_elasticsearch_url }}
Environment=ES_FINDINGS_NO_VERIFY_TLS={{ wazuh_findings_ingest_es_no_verify_tls | ternary('1', '0') }}
EnvironmentFile=-{{ wazuh_findings_ingest_dir }}/wazuh-user.env
EnvironmentFile=-{{ wazuh_findings_ingest_dir }}/es-user.env
ExecStart=/usr/bin/python3 {{ wazuh_findings_ingest_dir }}/wazuh_findings_sync.py
StandardOutput=append:{{ wazuh_findings_ingest_log_path }}
StandardError=append:{{ wazuh_findings_ingest_log_path }}

[Install]
WantedBy=multi-user.target
```

Literal content for `templates/wazuh-findings-ingest.timer.j2`:

```ini
[Unit]
Description=Schedule for wazuh-findings-ingest.service

[Timer]
OnCalendar={{ wazuh_findings_ingest_on_calendar }}
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

Literal content for `tasks/main.yml` — same two-block shape (remove when
disabled / install when enabled) as `es_findings_ingest/tasks/main.yml`,
adapted:

```yaml
---
- name: Remove scheduled Wazuh findings ingest when not explicitly enabled
  when: not (wazuh_findings_ingest_enabled | bool)
  block:
    - name: Stop and disable wazuh-findings-ingest timer
      ansible.builtin.systemd:
        name: wazuh-findings-ingest.timer
        state: stopped
        enabled: false
      failed_when: false

    - name: Stop wazuh-findings-ingest service if present
      ansible.builtin.systemd:
        name: wazuh-findings-ingest.service
        state: stopped
        enabled: false
      failed_when: false

    - name: Remove wazuh-findings-ingest units and files
      ansible.builtin.file:
        path: "{{ item }}"
        state: absent
      loop:
        - /etc/systemd/system/wazuh-findings-ingest.timer
        - /etc/systemd/system/wazuh-findings-ingest.service
        - "{{ wazuh_findings_ingest_dir }}"
      notify: Reload systemd

    - name: Clear stale wazuh-findings-ingest service failure state
      ansible.builtin.command:
        cmd: systemctl reset-failed wazuh-findings-ingest.service wazuh-findings-ingest.timer
      failed_when: false
      changed_when: false

- name: Install scheduled Wazuh findings ingest when explicitly enabled
  when: wazuh_findings_ingest_enabled | bool
  block:
    - name: Create wazuh-findings-ingest directory
      ansible.builtin.file:
        path: "{{ wazuh_findings_ingest_dir }}"
        state: directory
        owner: root
        group: root
        mode: "0750"

    - name: Create wazuh-findings-ingest assets directory
      ansible.builtin.file:
        path: "{{ wazuh_findings_ingest_dir }}/assets/{{ item }}"
        state: directory
        owner: root
        group: root
        mode: "0750"
      loop:
        - templates
        - ingest_pipelines

    - name: Copy es_setup_assets.py
      ansible.builtin.copy:
        src: es_setup_assets.py
        dest: "{{ wazuh_findings_ingest_dir }}/es_setup_assets.py"
        owner: root
        group: root
        mode: "0750"

    - name: Copy wazuh_findings_sync.py
      ansible.builtin.copy:
        src: wazuh_findings_sync.py
        dest: "{{ wazuh_findings_ingest_dir }}/wazuh_findings_sync.py"
        owner: root
        group: root
        mode: "0750"

    - name: Copy index template assets
      ansible.builtin.copy:
        src: "assets/templates/{{ item }}"
        dest: "{{ wazuh_findings_ingest_dir }}/assets/templates/{{ item }}"
        owner: root
        group: root
        mode: "0640"
      loop:
        - wazuh-findings.json

    - name: Copy ingest pipeline assets
      ansible.builtin.copy:
        src: "assets/ingest_pipelines/{{ item }}"
        dest: "{{ wazuh_findings_ingest_dir }}/assets/ingest_pipelines/{{ item }}"
        owner: root
        group: root
        mode: "0640"
      loop:
        - wazuh-findings-normalize.json

    # ---------------------------------------------------------------
    # Scoped Wazuh Indexer internal user (read-only on wazuh-alerts-*) --
    # same idempotent "credential file is the only existence check" shape
    # every other role in this family uses. UNVERIFIED against Wazuh's
    # own Indexer build until this runs live -- see defaults/main.yml's
    # comment on wazuh_findings_ingest_wazuh_role_name.
    # ---------------------------------------------------------------

    - name: Check for existing Wazuh Indexer reader credential
      ansible.builtin.stat:
        path: "{{ wazuh_findings_ingest_dir }}/wazuh-user.env"
      register: wazuh_findings_ingest_wazuh_credential_stat

    - name: Check if Wazuh Indexer is reachable before provisioning its scoped user
      ansible.builtin.wait_for:
        host: "{{ wazuh_findings_ingest_wazuh_host }}"
        port: 9200
        timeout: 5
      register: wazuh_findings_ingest_wazuh_reachable
      ignore_errors: true
      when: not wazuh_findings_ingest_wazuh_credential_stat.stat.exists

    - name: Warn and skip Wazuh Indexer user provisioning when it is not yet reachable
      ansible.builtin.debug:
        msg: >-
          Wazuh Indexer at {{ wazuh_findings_ingest_wazuh_host }}:9200 is not
          reachable (timeout). Skipping wazuh-findings-ingest reader creation --
          re-run provision once wazuh-stack's indexer is up.
      when:
        - not wazuh_findings_ingest_wazuh_credential_stat.stat.exists
        - wazuh_findings_ingest_wazuh_reachable.failed | default(true)

    - name: Generate a random password for the scoped Wazuh Indexer user
      ansible.builtin.set_fact:
        wazuh_findings_ingest_wazuh_password: "{{ lookup('password', '/dev/null length=32 chars=ascii_letters,digits') }}"
      when:
        - not wazuh_findings_ingest_wazuh_credential_stat.stat.exists
        - not (wazuh_findings_ingest_wazuh_reachable.failed | default(true))
      no_log: true

    - name: Ensure wazuh_findings_reader role exists in Wazuh Indexer
      ansible.builtin.uri:
        url: "{{ wazuh_findings_ingest_wazuh_url }}/_plugins/_security/api/roles/{{ wazuh_findings_ingest_wazuh_role_name }}"
        method: PUT
        url_username: "{{ wazuh_findings_ingest_wazuh_admin_user }}"
        url_password: "{{ wazuh_findings_ingest_wazuh_admin_password }}"
        validate_certs: "{{ not wazuh_findings_ingest_wazuh_no_verify_tls }}"
        force_basic_auth: true
        body_format: json
        body:
          index_permissions:
            - index_patterns:
                - "wazuh-alerts-*"
              allowed_actions:
                - "read"
        status_code: [200, 201]
      when:
        - not wazuh_findings_ingest_wazuh_credential_stat.stat.exists
        - not (wazuh_findings_ingest_wazuh_reachable.failed | default(true))
      delegate_to: localhost

    - name: Ensure scoped Wazuh Indexer user exists
      ansible.builtin.uri:
        url: "{{ wazuh_findings_ingest_wazuh_url }}/_plugins/_security/api/internalusers/{{ wazuh_findings_ingest_wazuh_user_name }}"
        method: PUT
        url_username: "{{ wazuh_findings_ingest_wazuh_admin_user }}"
        url_password: "{{ wazuh_findings_ingest_wazuh_admin_password }}"
        validate_certs: "{{ not wazuh_findings_ingest_wazuh_no_verify_tls }}"
        force_basic_auth: true
        body_format: json
        body:
          password: "{{ wazuh_findings_ingest_wazuh_password }}"
          opendistro_security_roles:
            - "{{ wazuh_findings_ingest_wazuh_role_name }}"
          description: "wazuh_findings_ingest service account (wazuh-stack) -- read-only, never the admin superuser"
        status_code: [200, 201]
      when:
        - not wazuh_findings_ingest_wazuh_credential_stat.stat.exists
        - not (wazuh_findings_ingest_wazuh_reachable.failed | default(true))
      delegate_to: localhost
      no_log: true

    - name: Write Wazuh Indexer reader credential file
      ansible.builtin.copy:
        dest: "{{ wazuh_findings_ingest_dir }}/wazuh-user.env"
        owner: root
        group: root
        mode: "0600"
        content: |
          # wazuh-findings-ingest Wazuh Indexer reader credential - managed by Ansible, do not edit by hand
          WAZUH_USER={{ wazuh_findings_ingest_wazuh_user_name }}
          WAZUH_PASSWORD={{ wazuh_findings_ingest_wazuh_password }}
      when:
        - not wazuh_findings_ingest_wazuh_credential_stat.stat.exists
        - not (wazuh_findings_ingest_wazuh_reachable.failed | default(true))
      no_log: true

    # ---------------------------------------------------------------
    # Scoped OpenSearch internal user (destination) -- extends the
    # existing es_findings_writer role's index_patterns to also cover
    # wazuh-findings*, same technique cve_enrichment_sync used for
    # unified-cve-exposure*. Idempotent PUT -- safe even if
    # es_findings_ingest/gvm_findings_ingest/cve_enrichment_sync already
    # created this role with a narrower pattern list; this is the union.
    # ---------------------------------------------------------------

    - name: Check for existing OpenSearch findings-writer credential
      ansible.builtin.stat:
        path: "{{ wazuh_findings_ingest_dir }}/es-user.env"
      register: wazuh_findings_ingest_es_credential_stat

    - name: Check if OpenSearch is reachable before provisioning its scoped user
      ansible.builtin.wait_for:
        host: "{{ wazuh_findings_ingest_elasticsearch_host }}"
        port: 9200
        timeout: 5
      register: wazuh_findings_ingest_es_reachable
      ignore_errors: true
      when: not wazuh_findings_ingest_es_credential_stat.stat.exists

    - name: Warn and skip OpenSearch user provisioning when it is not yet reachable
      ansible.builtin.debug:
        msg: >-
          OpenSearch at {{ wazuh_findings_ingest_elasticsearch_host }}:9200 is not
          reachable (timeout). Skipping wazuh-findings-ingest user creation --
          re-run provision once opensearch-stack is reachable.
      when:
        - not wazuh_findings_ingest_es_credential_stat.stat.exists
        - wazuh_findings_ingest_es_reachable.failed | default(true)

    - name: Generate a random password for the scoped OpenSearch user
      ansible.builtin.set_fact:
        wazuh_findings_ingest_es_password: "{{ lookup('password', '/dev/null length=32 chars=ascii_letters,digits') }}"
      when:
        - not wazuh_findings_ingest_es_credential_stat.stat.exists
        - not (wazuh_findings_ingest_es_reachable.failed | default(true))
      no_log: true

    - name: Ensure es_findings_writer role exists in OpenSearch (extended to wazuh-findings*)
      ansible.builtin.uri:
        url: "{{ wazuh_findings_ingest_elasticsearch_url }}/_plugins/_security/api/roles/{{ wazuh_findings_ingest_es_role_name }}"
        method: PUT
        url_username: "{{ wazuh_findings_ingest_elastic_admin_user }}"
        url_password: "{{ wazuh_findings_ingest_elastic_admin_password }}"
        validate_certs: "{{ not wazuh_findings_ingest_es_no_verify_tls }}"
        force_basic_auth: true
        body_format: json
        body:
          index_permissions:
            - index_patterns:
                - "harbor-findings*"
                - "gvm-findings*"
                - "es-findings-sync-state"
                - "unified-cve-exposure*"
                - "wazuh-findings*"
              allowed_actions:
                - "create_index"
                - "write"
                - "read"
        status_code: [200, 201]
      delegate_to: localhost

    - name: Ensure scoped OpenSearch user exists
      ansible.builtin.uri:
        url: "{{ wazuh_findings_ingest_elasticsearch_url }}/_plugins/_security/api/internalusers/{{ wazuh_findings_ingest_es_user_name }}"
        method: PUT
        url_username: "{{ wazuh_findings_ingest_elastic_admin_user }}"
        url_password: "{{ wazuh_findings_ingest_elastic_admin_password }}"
        validate_certs: "{{ not wazuh_findings_ingest_es_no_verify_tls }}"
        force_basic_auth: true
        body_format: json
        body:
          password: "{{ wazuh_findings_ingest_es_password }}"
          opendistro_security_roles:
            - "{{ wazuh_findings_ingest_es_role_name }}"
          description: "wazuh_findings_ingest service account (wazuh-stack) -- never the admin superuser"
        status_code: [200, 201]
      when:
        - not wazuh_findings_ingest_es_credential_stat.stat.exists
        - not (wazuh_findings_ingest_es_reachable.failed | default(true))
      delegate_to: localhost
      no_log: true

    - name: Write OpenSearch findings-writer credential file
      ansible.builtin.copy:
        dest: "{{ wazuh_findings_ingest_dir }}/es-user.env"
        owner: root
        group: root
        mode: "0600"
        content: |
          # wazuh-findings-ingest OpenSearch user credential - managed by Ansible, do not edit by hand
          ES_FINDINGS_USER={{ wazuh_findings_ingest_es_user_name }}
          ES_FINDINGS_PASSWORD={{ wazuh_findings_ingest_es_password }}
      when:
        - not wazuh_findings_ingest_es_credential_stat.stat.exists
        - not (wazuh_findings_ingest_es_reachable.failed | default(true))
      no_log: true

    - name: Check if OpenSearch is reachable for asset setup
      ansible.builtin.wait_for:
        host: "{{ wazuh_findings_ingest_elasticsearch_host }}"
        port: 9200
        timeout: 5
      register: wazuh_findings_ingest_es_reachable_for_assets
      ignore_errors: true

    - name: Apply OpenSearch index templates and ingest pipelines
      ansible.builtin.command:
        cmd: >-
          /usr/bin/python3 {{ wazuh_findings_ingest_dir }}/es_setup_assets.py
          --elasticsearch-url {{ wazuh_findings_ingest_elasticsearch_url }}
          --user {{ wazuh_findings_ingest_elastic_admin_user }}
          --password {{ wazuh_findings_ingest_elastic_admin_password | quote }}
          {{ '--no-verify-tls' if wazuh_findings_ingest_es_no_verify_tls else '' }}
          --apply
      register: wazuh_findings_ingest_setup_assets_result
      changed_when: >-
        'created' in wazuh_findings_ingest_setup_assets_result.stdout
        or 'updated' in wazuh_findings_ingest_setup_assets_result.stdout
      when: not (wazuh_findings_ingest_es_reachable_for_assets.failed | default(true))
      no_log: true

    - name: Report asset setup skipped
      ansible.builtin.debug:
        msg: >-
          OpenSearch at {{ wazuh_findings_ingest_elasticsearch_host }}:9200 is not reachable --
          skipped index template / ingest pipeline setup this run.
      when: wazuh_findings_ingest_es_reachable_for_assets.failed | default(true)

    - name: Write wazuh-findings-ingest systemd service
      ansible.builtin.template:
        src: wazuh-findings-ingest.service.j2
        dest: /etc/systemd/system/wazuh-findings-ingest.service
        owner: root
        group: root
        mode: "0644"  # nosonar: ansible:S2612 - standard systemd unit file permissions
      notify: Reload systemd

    - name: Write wazuh-findings-ingest systemd timer
      ansible.builtin.template:
        src: wazuh-findings-ingest.timer.j2
        dest: /etc/systemd/system/wazuh-findings-ingest.timer
        owner: root
        group: root
        mode: "0644"  # nosonar: ansible:S2612 - standard systemd unit file permissions
      notify: Reload systemd

    - name: Flush handlers before enabling timer
      ansible.builtin.meta: flush_handlers

    - name: Enable and start wazuh-findings-ingest timer
      ansible.builtin.systemd:
        name: wazuh-findings-ingest.timer
        enabled: true
        state: started
      when: not ansible_check_mode
```

### wazuh-findings-04: sync script

```yaml
id: wazuh-findings-04-sync-script
title: Write wazuh_findings_sync.py
depends_on: []

change: >
  Create terraform/lxc/ansible/roles/wazuh_findings_ingest/files/wazuh_findings_sync.py
  and terraform/lxc/ansible/roles/wazuh_findings_ingest/files/es_setup_assets.py
  (the latter is a byte-for-byte copy of
  terraform/lxc/ansible/roles/es_findings_ingest/files/es_setup_assets.py --
  a plain shared utility, copy it exactly, no edits). The sync script's
  full content is below -- adapted from harbor_findings_sync.py's overall
  shape (argparse, bulk_upsert with putAll scripted upsert, sync-state
  write) plus wazuh-analysis's proven search_after/cursor pattern against
  a Wazuh/OpenSearch-shaped Indexer.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/files/wazuh_findings_sync.py
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/files/es_setup_assets.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running this script against any live host -- file creation only in this step"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/ansible/roles/wazuh_findings_ingest/files/wazuh_findings_sync.py"
    expect: "exit 0"
    critical: true
  - id: setup-assets-identical
    cmd: "diff -q terraform/lxc/ansible/roles/es_findings_ingest/files/es_setup_assets.py terraform/lxc/ansible/roles/wazuh_findings_ingest/files/es_setup_assets.py"
    expect: "exit 0"
    critical: true
```

Literal content for `wazuh_findings_sync.py`:

```python
#!/usr/bin/env python3
"""Scheduled pull of Wazuh vulnerability-detector findings into OpenSearch.

See docs/threat-vuln-platform/plan.md's "Phase 2: Wazuh findings
ingestion" for the design. Same overall shape as harbor_findings_sync.py
(stdlib-only, deterministic per-document _id, scripted-upsert putAll,
sync-state doc) but the source-side query pattern (incremental by
@timestamp with a lookback window, search_after pagination) is carried
over directly from wazuh-analysis's own wazuh_es_sync.py -- already
validated against real Wazuh 4.x alert data, not reinvented here.

Only ever queries rule.groups:vulnerability-detector -- the other four
alert types wazuh-analysis's README documents (auth failures, file
integrity, rootcheck, compliance/SCA) are explicitly out of scope for
this role; that's the *-events family, a separate later phase.

Read-only against the Wazuh Indexer: only ever calls the _search API.
Read-write against OpenSearch: bulk-upserts finding documents and
updates one sync-state document (shared es-findings-sync-state index,
keyed "wazuh" -- same index harbor/gvm already write their own state
docs into).

Intentionally stdlib-only, matching every other sync script in this
repo's own reasoning (no Python venv convention on LXC hosts for jobs
like this).
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
import urllib.request
from datetime import datetime, timedelta, timezone

WAZUH_INDEX_PATTERN = "wazuh-alerts-4.x-*"
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


def parse_es_dt(s: str) -> datetime:
    """Parse ES/OpenSearch ISO timestamps (handles Z and long fractional
    seconds) -- lifted directly from wazuh-analysis's wazuh_es_sync.py,
    already proven against real Wazuh alert timestamp formats."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*\.\d{1,6})\d+([+-]\d{2}:\d{2})$", s)
    if m:
        s = m.group(1) + m.group(2)
    return datetime.fromisoformat(s)


def iso_minus_seconds(iso_ts: str, seconds: int) -> str:
    return (parse_es_dt(iso_ts) - timedelta(seconds=seconds)).isoformat()


def _wazuh_search_after(base_url, auth_header, verify_tls, start_cursor, batch_size=BATCH_SIZE):
    """Deterministic incremental pagination using search_after, filtered
    to vulnerability-detector alerts only, sorted by @timestamp then _doc
    (OpenSearch-compatible tiebreaker -- not _shard_doc)."""
    search_after = None
    ctx = _ssl_context(verify_tls)

    while True:
        body = {
            "size": batch_size,
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": start_cursor}}},
                        {"term": {"rule.groups": "vulnerability-detector"}},
                    ]
                }
            },
            "sort": [
                {"@timestamp": {"order": "asc", "missing": "_last"}},
                "_doc",
            ],
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


def _extract_cvss_score(vuln: dict) -> float | None:
    cvss = vuln.get("cvss") or {}
    score = (cvss.get("cvss3") or {}).get("base_score")
    if score is None:
        score = (cvss.get("cvss2") or {}).get("base_score")
    return score


def build_document(hit: dict) -> dict | None:
    src = hit.get("_source", {})
    vuln = (src.get("data") or {}).get("vulnerability") or {}
    cve = vuln.get("cve")
    if not cve:
        return None
    agent = src.get("agent") or {}
    package = vuln.get("package") or {}
    return {
        "source": "wazuh",
        "finding_id": cve,
        "severity_raw": vuln.get("severity"),
        "cvss_score": _extract_cvss_score(vuln),
        "package": package.get("name"),
        "package_version": package.get("version"),
        "status": vuln.get("status"),
        "target": {
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
        },
        "scan_time": src.get("@timestamp"),
        "last_seen": _now_iso(),
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


def get_sync_state(base_url, auth_header, verify_tls) -> dict | None:
    url = f"{base_url}/es-findings-sync-state/_doc/wazuh"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=15) as resp:
            return json.loads(resp.read()).get("_source")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def update_sync_state(base_url, auth_header, verify_tls, *, started, finished, status, docs_scanned, findings_indexed, errors, last_cursor, dry_run):
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
            "last_cursor": last_cursor,
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
    parser.add_argument("--lookback-seconds", type=int, default=int(os.environ.get("SYNC_LOOKBACK_SECONDS", "600")))
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

    state = get_sync_state(es_base, es_auth, not args.es_no_verify_tls)
    last_cursor = state.get("last_cursor") if state else None
    if last_cursor:
        start_cursor = iso_minus_seconds(last_cursor, args.lookback_seconds)
        print(f"Incremental sync from {start_cursor} (lookback {args.lookback_seconds}s)")
    else:
        start_cursor = "2025-01-01T00:00:00Z"
        print("Initial full sync (no prior sync-state doc found)")

    docs_scanned = 0
    findings_indexed = 0
    errors = 0
    max_cursor_seen = last_cursor
    batch: list[dict] = []

    for hit in _wazuh_search_after(wazuh_base, wazuh_auth, not args.wazuh_no_verify_tls, start_cursor):
        docs_scanned += 1
        ts = hit.get("_source", {}).get("@timestamp")
        if ts and (max_cursor_seen is None or parse_es_dt(ts) > parse_es_dt(max_cursor_seen)):
            max_cursor_seen = ts

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

    # Never advance the cursor on a run that found nothing at all --
    # same "never advance cursor on a 0-doc run" principle already
    # validated in security-analysis's secpipe_core design (see this
    # doc's "Prior art" section above) -- avoids silently skipping a
    # window if Wazuh's indexer was briefly unreachable mid-query.
    new_cursor = max_cursor_seen if docs_scanned > 0 else last_cursor
    update_sync_state(
        es_base, es_auth, not args.es_no_verify_tls,
        started=started, finished=finished, status=status,
        docs_scanned=docs_scanned, findings_indexed=findings_indexed,
        errors=errors, last_cursor=new_cursor, dry_run=args.dry_run,
    )

    print(
        f"Done in {elapsed:.1f}s — docs_scanned={docs_scanned} findings_indexed={findings_indexed} "
        f"errors={errors} dry_run={args.dry_run}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
```

### wazuh-findings-05: index template and ingest pipeline

```yaml
id: wazuh-findings-05-assets
title: Create wazuh-findings index template and normalize ingest pipeline
depends_on: []

change: >
  Create terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/templates/wazuh-findings.json
  and terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/ingest_pipelines/wazuh-findings-normalize.json
  with exactly the content below -- adapted from harbor-findings.json's
  mapping shape (same first_seen/last_seen/severity_assessed fields for
  cve_enrichment_sync write-back parity) and harbor-findings-normalize.json's
  null-default pattern (the OpenSearch set-processor-rejects-null-value
  workaround already fixed there).

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/templates/wazuh-findings.json
    - terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/ingest_pipelines/wazuh-findings-normalize.json
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: json-syntax-template
    cmd: "python3 -c \"import json; json.load(open('terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/templates/wazuh-findings.json'))\""
    expect: "exit 0"
    critical: true
  - id: json-syntax-pipeline
    cmd: "python3 -c \"import json; json.load(open('terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/ingest_pipelines/wazuh-findings-normalize.json'))\""
    expect: "exit 0"
    critical: true
```

Literal content for `assets/templates/wazuh-findings.json`:

```json
{
  "index_patterns": ["wazuh-findings*"],
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 0,
      "index.default_pipeline": "wazuh-findings-normalize"
    },
    "mappings": {
      "dynamic": false,
      "properties": {
        "source": { "type": "keyword" },
        "finding_id": { "type": "keyword" },
        "severity_raw": { "type": "keyword" },
        "cvss_score": { "type": "float" },
        "severity_assessed": { "type": "keyword" },
        "assessed_reason": { "type": "text" },
        "assessed_by": { "type": "keyword" },
        "assessed_at": { "type": "date" },
        "package": { "type": "keyword" },
        "package_version": { "type": "keyword" },
        "status": { "type": "keyword" },
        "target": {
          "properties": {
            "agent_id": { "type": "keyword" },
            "agent_name": { "type": "keyword" }
          }
        },
        "scan_time": { "type": "date" },
        "first_seen": { "type": "date" },
        "last_seen": { "type": "date" },
        "ingested_at": { "type": "date" }
      }
    }
  },
  "priority": 200,
  "_meta": {
    "description": "Wazuh vulnerability-detector findings — one document per CVE-per-package-per-agent, upserted on a deterministic _id so reruns update first_seen/last_seen rather than duplicating. Third *-findings source alongside harbor-findings and gvm-findings, feeding unified-cve-exposure. See docs/threat-vuln-platform/plan.md Phase 2.",
    "managed_by": "wazuh_findings_ingest role, es_setup_assets.py"
  }
}
```

Literal content for `assets/ingest_pipelines/wazuh-findings-normalize.json`:

```json
{
  "description": "Normalize Wazuh vulnerability-detector finding documents at ingest time — stamps ingested_at, and defaults the human-assessment fields to explicit nulls when the sync script didn't already carry forward a prior assessment. Same OpenSearch null-value workaround as harbor-findings-normalize.json (OpenSearch's set processor rejects an explicit null value; Elasticsearch's 'set value:null override:false' has no direct equivalent).",
  "processors": [
    {
      "set": {
        "field": "ingested_at",
        "value": "{{{_ingest.timestamp}}}"
      }
    },
    {
      "script": {
        "description": "Default the human-assessment fields to explicit null only when absent -- never overwrites a real value a downstream tool already wrote.",
        "lang": "painless",
        "source": "for (field in params.fields) { if (!ctx.containsKey(field)) { ctx.put(field, null); } }",
        "params": {
          "fields": ["severity_assessed", "assessed_reason", "assessed_by", "assessed_at"]
        }
      }
    }
  ]
}
```

### wazuh-findings-06: wire the role into wazuh-stack's deploy

```yaml
id: wazuh-findings-06-wire-deploy
title: Include wazuh_findings_ingest role in deploy-wazuh-stack.yml and add the stack.yaml flag
depends_on: [wazuh-findings-02-role-defaults, wazuh-findings-03-role-tasks, wazuh-findings-04-sync-script, wazuh-findings-05-assets]

change: >
  In terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml, add
  "- wazuh_findings_ingest" to the play's roles list (same play that
  already deploys the manager/indexer/dashboard containers), after any
  existing roles in that list. In terraform/lxc/stacks/wazuh-stack/stack.yaml,
  add a new top-level key "wazuh_findings_ingest_enabled: true" (matching
  the existing "harbor_repull_enabled"/"es_findings_ingest_enabled" style
  already used by sibling stack.yaml files) -- default it true here since
  this is the one intended consumer, not a shared role with a false default
  used elsewhere.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml
    - terraform/lxc/stacks/wazuh-stack/stack.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply / ansible-playbook run -- wiring only in this step"
    - "Removing or reordering any existing role in deploy-wazuh-stack.yml's roles list"

gates:
  - id: yaml-syntax-playbook
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml"
    expect: "exit 0"
    critical: true
  - id: yaml-syntax-stack
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/wazuh-stack/stack.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: role-referenced
    cmd: "grep -c 'wazuh_findings_ingest' terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml"
    expect: "at least 1"
    critical: true
```

### wazuh-findings-07: extend cve_enrichment_sync to a third source

```yaml
id: wazuh-findings-07-extend-cve-enrichment
title: Add wazuh-findings as a third CVE source in cve_enrichment_sync
depends_on: [wazuh-findings-05-assets]

change: >
  In terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py,
  find the function that aggregates distinct CVE IDs and per-source instance
  counts from harbor-findings/gvm-findings (a terms aggregation against each
  index's finding_id/cve field) and add a third, identically-shaped query
  against wazuh-findings' own finding_id field, merging its per-CVE instance
  count into the same aggregate structure the harbor/gvm queries already
  populate -- do not change the shape of that aggregate structure, only add
  a third contributor to it. In
  terraform/lxc/ansible/roles/cve_enrichment_sync/tasks/main.yml, add
  "wazuh-findings*" to the existing "Ensure es_findings_writer role exists"
  task's index_permissions.index_patterns list (it currently reads
  harbor-findings*/gvm-findings*/es-findings-sync-state/unified-cve-exposure*)
  so this role's write-back onto wazuh-findings' severity_assessed field is
  permitted -- this is a redundant-but-harmless third grant of the same
  pattern wazuh-findings-03 already applies from wazuh_findings_ingest's own
  side; OpenSearch's role PUT is idempotent so both roles applying the same
  union is safe, not a conflict.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py
    - terraform/lxc/ansible/roles/cve_enrichment_sync/tasks/main.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing unified-cve-exposure's document schema -- this step only adds a data source, not a new field shape"
    - "Any provision.sh / terragrunt apply / ansible-playbook run -- code edit only in this step"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py"
    expect: "exit 0"
    critical: true
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/ansible/roles/cve_enrichment_sync/tasks/main.yml'))\""
    expect: "exit 0"
    critical: true
  - id: wazuh-findings-referenced
    cmd: "grep -c 'wazuh-findings' terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py"
    expect: "at least 1"
    critical: true
```

### Deploying and validating (operator action, not a step block)

Once wazuh-findings-01 through -07 have landed and their gates pass, the
role still has to actually run against the real `wazuh-stack` LXC to
produce real data — that's a production deploy + verification pass, not
something the local model runs unsupervised. Follow the normal flow:

1. `./with-secrets-prod scripts/provision.sh --stack wazuh-stack` under
   `TASK_APPROVAL` (per this repo's Production Credential Controls) — the
   auto-mode classifier has blocked bare `ansible-playbook`/`terragrunt
   apply` for this stack before (see `docs/wazuh-stack/README.md`'s
   harness notes), so the operator may need to run this command directly.
2. Confirm live: `wazuh-findings-ingest.timer` active, one successful
   `wazuh-findings-ingest.service` run in its log, real documents in
   `wazuh-findings` (query it directly — don't trust `docs_scanned > 0`
   alone, confirm actual `finding_id`/`package`/`target.agent_id` values
   look real).
3. Resolve the "does `last_seen` naturally advance daily?" open question
   above by comparing two consecutive days' sync-state `docs_scanned`
   counts for the same known-still-vulnerable host/package pair.
4. Re-run `cve_enrichment_sync` once manually
   (`systemctl start cve-enrichment-sync.service` on `secpipe-stack`) and
   confirm `unified-cve-exposure` now shows `total_instances` contributions
   from all three sources for at least one real overlapping CVE.

## Phase 3: rollups and dashboard fold-in (scoped, not yet step-blocked)

Deliberately left for a follow-up planning pass once Phase 2 is live and
its real index volumes/shapes are known — writing OpenSearch Transform-job
step blocks against an unverified API shape would violate this process's
own "literal, not guessed" rule. What's already decided:

- **Mechanism**: OpenSearch's native Transform-job API
  (`_plugins/_transform`), applied to `wazuh-events` (once Phase 2B below
  builds it), `harbor-findings`, and `gvm-findings` alike — the operator's
  2026-09-01 decision, a deliberate departure from this repo's usual
  systemd-timer-Python pattern.
- **First real step before any Transform job is written**: `GET
  _cat/plugins` against `opensearch-stack` to confirm the Index Management
  plugin (which owns Transform jobs) is actually installed on this
  cluster's real OpenSearch version, then one `PUT _plugins/_transform/<id>`
  test job against a throwaway index to confirm the exact field names this
  OpenSearch version expects, before trusting any schema written from
  training-data knowledge of the feature.
- **Dashboard**: fold new rollup panels into the existing "Threat &
  Vulnerability Overview" dashboard (operator's 2026-09-01 decision),
  not a new dashboard.

## Phase 2B: `wazuh-events` general alert stream (scoped, not yet step-blocked)

The `*-events` shape `wazuh-analysis` actually built (level 7+ filter,
`wazuh-alerts-normalize` pipeline's severity/type classification, all
five alert types) — build this once Phase 2's narrower `wazuh-findings`
pattern is proven live, reusing its exact field-normalization design
(already transcribed field-for-field into this plan's Phase 2 mapping
table above for the vulnerability subset; the auth-failure/file-integrity/
rootcheck/compliance subsets need the same treatment). ILM policy for
this index (a genuine append-only time-series, unlike `*-findings`) is
not yet designed — needs its own judgment call on retention window before
step-blocking.

## Operator direction, 2026-09-01 — the dashboard isn't a real VM tool yet

Live review of the "Threat & Vulnerability Overview" dashboard (fetched
its actual `panelsJSON`/visualization definitions, not assumed) confirmed
the operator's complaint directly: all four panels (`threat-kev-count`,
`threat-top-by-risk-score`, `threat-top-by-exposure`,
`threat-risk-narratives`) bucket only on `cve_id`, with metrics limited to
`risk_score`/`total_instances`/`risk_band`/`kev_listed`/`llm_narrative`.
Nothing shows which system found a CVE or which specific asset has it —
`unified-cve-exposure.sources[]` itself only ever stored
`{source, finding_id, count}`, never an asset identifier. Confirmed via a
live sample doc (`CVE-2026-12087`, both harbor and wazuh sources, no
asset info in either).

Three follow-on decisions from the operator, to be built one phase at a
time, dashboard first:

1. **Phase 4 (this phase)**: full per-asset drill-down — extend
   `unified-cve-exposure` to carry real asset identifiers per source, not
   just a count, and surface them on the dashboard.
2. **Phase 5** (next): a daily "CISO brief" — LLM-synthesized top-findings
   summary. Refined 2026-09-01: the first pass outputs plain markdown,
   readable directly in a chat/terminal session (not an OpenSearch
   Dashboards panel, and not any outbound delivery mechanism) — proves
   out the content/selection logic before deciding how it's automated or
   delivered. Dashboard embedding and actual delivery (email/Slack/etc.)
   both remain explicitly deferred, separate decisions from the content
   itself.
3. **Phase 7** (last — renumbered 2026-09-01, see note below): migrate the LLM narrative calls — both the
   per-CVE `cve_enrichment_sync` triage narrative (currently Anthropic,
   ~50-150 real triages/night) and the new Phase 5 daily-brief synthesis
   — to the local Framework LLM (Ollama, `laguna-s-2.1:q4_k_m-ctx131k`,
   confirmed live-loaded on `framework.gibbsgreatly.xyz:11434` and
   reachable from `secpipe-stack`'s network zone as of this decision).
   Operator confirmed the GPU has standing capacity for this now — the
   "temporary Anthropic substitution" noted in `cve_enrichment_sync.py`'s
   own module docstring (LLM_PROVIDER=anthropic, "the local LLM is
   occupied with benchmarking work as of 2026-08-18") no longer applies.

## Phase 4: asset-level exposure (this phase)

### What each source already has, confirmed live (not guessed)

Sample docs pulled directly from each `*-findings` index:

| Source | Index | Asset identifier fields | Example |
|---|---|---|---|
| `harbor` | `harbor-findings` | `artifact.repository`, `artifact.tag` | `goauthentik/server:2026.2.4` |
| `greenbone` | `gvm-findings` | `target.host`, `target.port`, `target.zone` | `192.168.1.113:21/tcp (lan)` |
| `wazuh` | `wazuh-findings` | `target.agent_id`, `target.agent_name` | `web-01` |

(Note: the source name is literally `"greenbone"` in both `gvm-findings`
documents and `cve_enrichment_sync.py`'s own `sources` list — not
`"gvm"`. Carry that through exactly; do not rename it.)

Every source already has what's needed to identify the affected asset —
the gap is entirely in `cve_enrichment_sync.py`'s aggregation step, which
only ever ran a plain `terms` aggregation on the CVE field
(`fetch_cve_instances()`), discarding everything about *which* documents
made up that count.

### Design

- **Aggregation**: add a `top_hits` sub-aggregation nested inside the
  existing `cves.terms` bucket, requesting only the asset identifier
  fields (`_source` filtered), sorted by `last_seen` desc, capped at
  `ASSET_SAMPLE_SIZE = 5` per CVE per source. One query per source still
  (no extra round-trips) — this only changes the aggregation body of the
  existing per-source call.
- **Per-source formatting**: a small `ASSET_FIELD_SPECS` table (source
  name → source fields to request + a formatter function turning one hit
  into a short display string), so the three sources' very different
  shapes (container image, host:port, agent name) all reduce to one
  `list[str]` per `sources[]` entry.
- **New fields on `unified-cve-exposure`**:
  - `sources[].assets`: `list[str]`, the sampled/formatted asset labels
    (capped at 5).
  - `sources[].assets_truncated`: `bool`, true when `count > 5` (tells
    the reader "there are more than shown").
  - `assets_summary`: one flattened `text` field built at write time,
    e.g. `"harbor (71): goauthentik/server:2026.2.4, ... (+66 more)\n
    wazuh (24): web-01, app-03, ... (+22 more)"` — this is the field the
    dashboard actually reads, using the exact same `top_hit`/`concat`
    single-value-per-bucket pattern already proven live for `risk_band`
    and `llm_narrative` in the existing table panels. A raw
    `sources[].assets` array can't be flattened into one table cell by a
    classic OpenSearch Dashboards visualization the way a scalar text
    field can — `assets_summary` exists specifically to be that scalar.
- **Backfill trigger**: `refresh_exposure_sources()`'s cheap
  no-LLM-call path currently only fires when the source set or
  `total_instances` changed. Extend its trigger condition to also fire
  when `"assets_summary" not in existing` — this is what makes the
  ~10,151 already-enriched CVEs pick up the new fields on the very next
  scheduled/manual run, without a special one-off backfill script and
  without re-spending any `triage_cve`/LLM calls (same pattern already
  proven live for the Phase 2 wazuh-source backfill, `sources_refreshed`
  counter and all).

### Step blocks

#### threat-vuln-04-01: asset-aware aggregation + new document fields

**Change**: in
`terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py`:

1. Add near the top (after `_TRIAGE_PATTERNS`):
   ```python
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
       },
       "greenbone": {
           "source_fields": ["target.host", "target.port", "target.zone"],
           "format": lambda src: (
               f"{_get_path(src, 'target.host') or '?'}:"
               f"{_get_path(src, 'target.port') or '?'}"
               f" ({_get_path(src, 'target.zone') or '?'})"
           ),
       },
       "wazuh": {
           "source_fields": ["target.agent_id", "target.agent_name"],
           "format": lambda src: (
               _get_path(src, "target.agent_name")
               or _get_path(src, "target.agent_id")
               or "?"
           ),
       },
   }


   def build_assets_summary(sources_list: list[dict]) -> str:
       """Flatten sources[] (each already carrying an 'assets' list and
       'assets_truncated' flag) into one human-readable text block, for
       direct display via a top_hit/concat table column -- the same
       pattern already proven live for risk_band/llm_narrative."""
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
   ```

2. Replace `fetch_cve_instances()` with an asset-aware version (same
   name kept so call sites don't change beyond the return shape):
   ```python
   def fetch_cve_instances(
       es_url: str, index: str, cve_field: str, asset_source_fields: list[str],
       *, auth_header: str, verify_tls: bool
   ) -> dict[str, dict]:
       """Terms-aggregate distinct CVE values + doc counts from one findings
       index, plus a top_hits sub-aggregation sampling up to
       ASSET_SAMPLE_SIZE of the most-recently-seen documents' asset
       identifier fields per CVE. Works unchanged whether the field is a
       single keyword (harbor-findings.finding_id) or a keyword array
       (gvm-findings.cve) -- a terms agg on an array field buckets each
       value independently, which is the correct behaviour here (a
       finding with 2 CVEs should count toward both)."""
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
                       }
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
           out[b["key"]] = {"count": b["doc_count"], "raw_assets": [h.get("_source", {}) for h in hits]}
       return out
   ```

3. In `main()`, update the `sources` list to also carry
   `asset_fields`/`formatter`, and update the aggregation loop:
   ```python
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
       )
       for cve_id, info in counts.items():
           entry = cve_map.setdefault(cve_id, {"sources": [], "total_instances": 0})
           assets = [spec["format"](raw) for raw in info["raw_assets"]]
           entry["sources"].append({
               "source": src["source"],
               "finding_id": cve_id,
               "count": info["count"],
               "assets": assets,
               "assets_truncated": info["count"] > len(assets),
           })
           entry["total_instances"] += info["count"]
   ```

4. In the `--force-refresh`-skip branch (the `existing is not None`
   block), change the refresh-trigger condition from:
   ```python
   if (
       new_source_names != existing_source_names
       or existing.get("total_instances") != entry["total_instances"]
   ):
   ```
   to:
   ```python
   if (
       new_source_names != existing_source_names
       or existing.get("total_instances") != entry["total_instances"]
       or "assets_summary" not in existing
   ):
   ```

5. `refresh_exposure_sources()`'s `_update` body gains the new field:
   ```python
   body={"doc": {
       "sources": sources_list,
       "total_instances": total_instances,
       "assets_summary": build_assets_summary(sources_list),
   }},
   ```
   (function signature unchanged — `build_assets_summary` is computed
   from the `sources_list` parameter already passed in.)

6. In the main enrichment path's `doc` dict (the `upsert_exposure_doc`
   call), add the same field:
   ```python
   doc = {
       "cve_id": cve_id,
       "sources": entry["sources"],
       "total_instances": entry["total_instances"],
       "assets_summary": build_assets_summary(entry["sources"]),
       **parsed,
       ...
   }
   ```

**Scope**: only
`terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py`.
No other file. Forbidden: touching `harbor_findings_sync.py`/
`gvm_findings_sync.py`/`wazuh_findings_sync.py` (their documents already
carry everything needed; this phase only reads them differently).

**Gates**:
- `python3 -m py_compile terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py` — must exit 0.
- `bash -n scripts/provision.sh` — unaffected by this phase, run anyway as
  a cheap regression check per this repo's standing Ansible-changes rule.

#### threat-vuln-04-02: index template mapping

**Change**: in
`terraform/lxc/ansible/roles/cve_enrichment_sync/files/assets/templates/unified-cve-exposure.json`,
extend the `sources` object mapping and add `assets_summary`:
```json
"sources": {
  "properties": {
    "source": { "type": "keyword" },
    "finding_id": { "type": "keyword" },
    "count": { "type": "integer" },
    "assets": { "type": "keyword" },
    "assets_truncated": { "type": "boolean" }
  }
},
"assets_summary": { "type": "text" },
```
inserted between the existing `"sources"` block and `"total_instances"`.
Also update the template's `_meta.description` to mention asset-level
exposure alongside cross-source correlation.

**Scope**: only that one template file.

**Gates**: `python3 -m json.tool <file>` must exit 0 (valid JSON).

#### threat-vuln-04-03: dashboard columns

**Change**: add one new `top_hit`/`concat` metric aggregation on
`assets_summary` to each of the two "Top CVEs" table visualizations
(`threat-top-by-risk-score`, `threat-top-by-exposure`), matching the
exact pattern already live for their `risk_band`/`kev_listed` columns —
`{"type": "top_hit", "schema": "metric", "params": {"field":
"assets_summary", "aggregate": "concat", "size": 1, "sortField":
"_score", "sortOrder": "desc", "customLabel": "Assets Affected"}}`,
appended to each visualization's `aggs` array (new `id`, one higher than
the current max in that panel) before the existing `terms` bucket agg on
`cve_id`. Applied live via the OpenSearch Dashboards saved-objects API
(`PUT /api/saved_objects/visualization/<id>`) with the admin credential,
same technique already used for the `wazuh-findings` index pattern
migration — read each visualization's current `attributes.visState` via
`GET`, splice in the new agg, `PUT` it back unchanged otherwise. No
dashboard-level (`panelsJSON`) change needed — the dashboard already
references these two visualization IDs; editing the visualization in
place is sufficient.

**Scope**: live Dashboards saved objects only (`threat-top-by-risk-score`,
`threat-top-by-exposure`) — no repo file changes for this step (there is
no dashboard-definition file checked into this repo; it was always
built/edited live, see "Dashboard" section above).

**Gates**: after the `PUT`, re-`GET` the same saved object and confirm
the new agg is present in the returned `visState`.

### Validation (after all three steps deployed)

1. Redeploy `secpipe-stack` (`provision.sh --stack secpipe-stack`) to
   ship the updated `cve_enrichment_sync.py` + template.
2. Confirm the template re-applied:
   `GET /unified-cve-exposure/_mapping` shows `sources.assets` and
   `assets_summary`.
3. Run `cve-enrichment-sync.service` once (manual `systemctl start`, same
   as Phase 2's validation) — expect a `sources_refreshed` count close to
   the full ~10,151 existing docs (the `"assets_summary" not in
   existing"` trigger fires for literally all of them on this first run,
   same one-time-migration shape already proven for the Phase 2 wazuh
   backfill), `enriched` only for genuinely new CVEs since the last run,
   and no new LLM/triage_cve spend for the backfilled majority.
4. Spot-check one multi-source CVE (e.g. `CVE-2026-12087`, already known
   to span harbor+wazuh) via `_doc/<id>` and confirm `assets_summary`
   reads sensibly.
5. Confirm live in the Dashboards UI: open "Threat & Vulnerability
   Overview", confirm both top-CVE tables now show an "Assets Affected"
   column with real asset labels, not just counts.

## Phase 6: UVM redesign — production/zone classification (2026-09-01)

Operator direction: rebuild the dashboard completely as a real
Unified Vulnerability Management tool (Avalor/Ivanti-Neurons-style),
showing risk across the home lab, where it comes from, and what's
finding it — not just a CVE-bucketed counter. Sequenced one phase at a
time, this phase first: classify every finding as production vs. lab/
practice, and by network zone, at ingestion time, before touching the
dashboard itself (Phase 7).

### Per-source classification design (all three sources structurally different)

- **Wazuh — trivially production.** An agent only exists on a real
  enrolled host, and `agent.name` already IS the owning stack's name.
  `target.stack = agent_name`, `target.in_production = True`
  unconditionally, `target.zone` via a small hardcoded `AGENT_ZONE_MAP`
  (5 known stacks + `pve` itself, `wazuh_findings_sync.py`) — an agent
  not yet in the map still gets `stack`/`in_production` right, just
  `zone: null` until added, never guessed.
- **GVM — already half-built.** `target.pentest_target` already existed
  and is correctly populated; `target.zone` already existed and is
  already populated. Only `in_production` needed fixing:
  `not pentest_target` when a host is known, else `False` (unknown, not
  assumed production). `target.stack` stays `null` — GVM scans raw IPs,
  not named stacks.
- **Harbor — genuinely mixed, needed a real registry.** Built
  `known_production_images.json`, an **exact-match** (not
  substring/prefix) registry of every real `artifact.repository` value
  observed live in `harbor-findings` (pulled via a terms aggregation,
  not guessed) against this repo's actual `terraform/lxc/stacks/*/` +
  each stack's real `network_zone`. Exact match deliberately chosen over
  substring matching after finding a real collision risk during design:
  a naive `"community/"` substring pattern for greenbone-stack's images
  would have silently matched `netboxcommunity/netbox` too.

### Two edge cases resolved by direct operator decision, not guessed

- **`vulhub/*` and `vxcontrol/*` (PentAGI) are explicit non-production
  overrides**, applied before any registry lookup, regardless of whether
  they'd otherwise match a deployed stack. `vxcontrol/*` genuinely is
  deployed (pentagi-stack is real and running) — operator chose to
  exclude it anyway since PentAGI's remediation is closed/deprioritized.
- **The legacy `elastic-stack` LXC (vmid 112) was actually decommissioned**,
  not just special-cased in the classifier. Confirmed live (`pvesh get
  .../status/current` showed `status: stopped`, `uptime: 0s`) before
  destroying — see `project_elasticsearch_stack_ideas` memory's
  2026-09-01 correction. `terraform/lxc/stacks/elastic-stack/` removed
  from the repo entirely. `elastic/kibana`/`elastic/elasticsearch`
  Harbor findings are stale historical scans from this host and
  correctly fall through the registry's default (unmatched →
  `in_production: false`) with no explicit entry needed.

### Cross-source rollup onto `unified-cve-exposure`

`cve_enrichment_sync.py`'s per-source aggregation (`fetch_cve_instances()`,
already extended once for Phase 4's asset sampling) gained two more
sub-aggregations per CVE bucket: a `filter` agg counting
`in_production:true` instances, and a `terms` agg collecting distinct
zones. Rolled up per CVE across all three sources into two new top-level
fields: `in_production` (`true` if ANY instance from ANY source is
production) and `zones` (sorted list of every zone this CVE appears in).
The existing Phase 4 backfill-trigger pattern (refresh already-enriched
CVEs without a triage_cve/LLM call when a tracked field is missing or has
drifted) was extended to also catch `in_production`/`zones` — this is
what backfills the new fields onto the ~10,151 already-enriched CVEs on
the next run, the same shape already proven live for `assets_summary`.

### Files changed

- `terraform/lxc/ansible/roles/es_findings_ingest/files/assets/known_production_images.json` — new, the Harbor registry.
- `terraform/lxc/ansible/roles/es_findings_ingest/files/harbor_findings_sync.py` — `load_production_registry()`/`classify_artifact()`, wired into `build_documents()`.
- `terraform/lxc/ansible/roles/es_findings_ingest/files/assets/templates/harbor-findings.json` — added `artifact.zone` (in_production/stack already existed, unpopulated).
- `terraform/lxc/ansible/roles/es_findings_ingest/tasks/main.yml` — copy task for the new registry file.
- `terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py` — `in_production = not pentest_target`. No template change needed (field already existed).
- `terraform/lxc/ansible/roles/wazuh_findings_ingest/files/wazuh_findings_sync.py` — `AGENT_ZONE_MAP`, `target.stack`/`target.zone`/`target.in_production`.
- `terraform/lxc/ansible/roles/wazuh_findings_ingest/files/assets/templates/wazuh-findings.json` — added all three new `target.*` fields (none existed before).
- `terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py` — aggregation rollup, `refresh_exposure_sources()` signature extended, main upsert doc extended.
- `terraform/lxc/ansible/roles/cve_enrichment_sync/files/assets/templates/unified-cve-exposure.json` — added `in_production`/`zones`.

### Deploy sequence (dependency order — source classifiers before the rollup that reads them)

1. `harbor-stack` (es_findings_ingest) — ships the registry + classifier.
2. `greenbone-stack` (gvm_findings_ingest) — ships the pentest_target-derived fix.
3. `wazuh-stack` (wazuh_findings_ingest) — ships the new template fields + classifier.
4. Full resync of all three (existing `putAll` upsert pattern means a
   normal scheduled/manual resync run naturally refreshes every
   already-indexed document's `in_production`/`stack`/`zone` fields —
   no separate backfill script needed, unlike Phase 2/4's `*-findings`→
   `unified-cve-exposure` situation).
5. **Live `PUT _mapping`** on each of `harbor-findings`/`gvm-findings`/
   `wazuh-findings` for any genuinely new field (`artifact.zone`,
   `target.stack`/`target.zone`/`target.in_production` on wazuh-findings)
   — same index-template-doesn't-retroactively-remap gotcha as Phase 4,
   confirmed to still apply, must not be skipped.
6. `secpipe-stack` (cve_enrichment_sync) redeploy, then one manual run to
   backfill `in_production`/`zones` onto `unified-cve-exposure`.

### CORRECTION 2026-09-01: `gvm-findings` was only ever seeing 3 of 23 real GVM tasks

After Phase 6 shipped, the dashboard's new production-split panel showed
`greenbone` contributing **zero** production findings — reported as "GVM's
current scope is 100% pentest-target/lab." Operator correctly pushed
back: GVM's real scope is absolutely not lab-only — the
`network-scan-rollout` project (see `project_gvm_lan_scan_rollout`
memory) has a genuine weekly full-LAN vulnerability scan live in
production since 2026-08-17.

Root cause, confirmed by querying `pg-gvm`'s Postgres DB directly
(`SELECT t.name, u.name FROM tasks t LEFT JOIN users u ON t.owner=u.id`),
bypassing GMP's own user-scoping entirely — not guessed: **23 real tasks
exist**, only 3 of which (the two ad-hoc PentAGI-triggered scans against
`192.168.1.113`/`.55`) belong to `pentagi-integration`, the GMP identity
`gvm-bridge` (and therefore `gvm_findings_sync.py`, which pulls
exclusively through it) has always authenticated as. The other **19
tasks — the actual production scan rollout** (`LAN scan: <zone>
full-vuln`/`discovery` for every VLAN zone, plus credentialed scans of
`pve`, managed Debian services, Linux workstations, Raspberry Pis) — all
belong to `admin`. GMP enforces per-user task/result visibility, so
`gvm-bridge` has never been able to see any of them. `gvm-findings` has
held exactly 10 documents, from exactly 2 hosts, for its entire
existence — a real, complete blind spot in the "production vs lab"
picture Phase 6 reported, not a classification bug (`REDTEAM_EXCLUDE`
itself was correct all along, it just never saw the other 19 tasks'
results to classify).

**Fix, operator-approved ("yes as admin")**: `deploy-greenbone-stack.yml`'s
`gvm-bridge` container now authenticates to GMP as `admin` directly
(`GVM_BRIDGE_USERNAME`/`PASSWORD` → `admin`/`greenbone_admin_password`),
not `pentagi-integration`. The `pentagi-integration` GMP user and its own
create-user/set-password tasks are left in place, just unused by the
bridge now — not deleted, in case anything else still keys off that
identity. **Original tradeoff note, now moot**: this widens whatever
PentAGI can do through the same bridge from `pentagi-integration`'s
scoped rights to full admin — accepted knowingly at the time, but
PentAGI is declared defunct (see `project_harbor_vuln_remediation_status`
memory) and out of scope for any further design consideration; nothing
here needs to cater to it. No code change needed in `gvm_findings_sync.py`
itself — it already pulls unfiltered via `/findings/all`.
`REDTEAM_EXCLUDE`'s zone/host list already covers every zone the real
LAN-scan tasks target.

**Deployed 2026-09-01** — `greenbone-stack` redeployed clean
(`ok=96 changed=11 failed=0`). First `gvm-findings-ingest` resync after
the swap jumped from raw=63/13-after-filter (the old `pentagi-integration`
dataset) to raw=1000/94-after-filter — **but 1000 turned out to be a
truncation, not the real total**.

### Found immediately after: gvmd's global "Max Rows Per Page" cap silently truncated the bridge to 1000 of 9,356 real results

`gvm_findings_sync.py`'s docstring assumed `rows=-1` in the GMP filter
string meant "unlimited." It doesn't — gvmd enforces a separate,
independent ceiling via a global GMP setting literally named
"Max Rows Per Page" (confirmed via direct `pg-gvm` query:
`SELECT name, value FROM settings` → `Max Rows Per Page = 1000`,
`owner` blank). This was invisible before today because
`pentagi-integration`'s 3-task dataset (63 raw results) never came
close to it; the real total in the `results` table is 9,356, confirmed
via `SELECT count(*) FROM results`.

Tried raising the setting directly via GMP `modify_setting` against its
setting_id (`76374a7a-0569-11e6-b6da-28d24461215b`, a well-known GVM
built-in UUID, confirmed via the same `pg-gvm` query) — this failed with
`<modify_setting_response status="400" status_text="Failed to find
setting"/>`. Root cause: that settings row has no `owner` (a bare global
default, not a per-user override), and gvmd's `modify_setting` looks up
settings scoped to the calling user — it can't find or create a row to
update for a global default. Not worth fighting GMP's settings model
further for a one-off ceiling raise.

**Real fix**: made `gvm-bridge` itself paginate explicitly
(`first=`/`rows=1000` loop, capped at 200 pages = 200,000 results as an
infinite-loop sanity guard) in `/findings/all`
([app.py](../../terraform/lxc/ansible/files/gvm-bridge/app.py)), rather
than depending on `rows=-1` bypassing a cap it never actually bypasses.
This is a code-level fix under our own control — no GMP settings
manipulation needed, works regardless of what "Max Rows Per Page" is set
to. `scan_results()` (the single-task endpoint PentAGI used) was left
alone — out of scope now that PentAGI is defunct, and 1000 results for a
single task is in practice never going to be hit.

**Deployed and verified live 2026-09-01.** `greenbone-stack` redeployed
clean (`ok=96 changed=11 failed=0`). `gvm-findings-ingest` re-run:
raw=8,060 (vs the DB's raw `results` count of 9,356 — the gap is
unexplained but not a pagination bug, since 8,060 is nowhere near the
1000-row ceiling and the loop runs to a short final page, not the
200-page safety cap), 655 findings after the threat=Log filter.
`gvm-findings` index: **264 total docs** (up from 10), of which **254
(96%) are production** — spread across every real VLAN zone (`lan`=126,
`mgmt_seg`=41, `edge_seg`=39, `infra_seg`=28, `ai_seg`=15,
`build_seg`=9, `game_seg`=6). Only 10 remain pentest-lab-only. This
directly confirms the operator's original correction: GVM was never
lab-only, it just wasn't *visible* to the ingest pipeline.

`cve-enrichment-sync` re-run afterward: `cves_seen=10152 enriched=79
skipped_fresh=10073 errors=0`. `unified-cve-exposure` totals moved from
10,070/4,185 (Phase 6 report) to **10,280 total / 4,307 production**
(41.6%→41.9%) — the aggregate split barely moved, since most GVM CVEs
overlap with ones Harbor/Wazuh already surfaced. What actually changed
is *source attribution*, not the topline number: GVM went from
contributing 0% of production findings to 96% of its own findings being
production — the earlier "GVM contributes zero production findings"
conclusion from Phase 6/8 is now corrected, not just caveated.

(The known-benign `409 version_conflict` writeback warnings on
`gvm-findings` recurred during this run, same pre-existing
multi-CVE-per-finding race documented earlier in this section — no
action needed.)

## Phase 7: local LLM migration + fast test-iteration (2026-09-01, code built)

Operator direction: full-corpus `cve_enrichment_sync` runs during Phase 6
took 20-75 minutes each (mostly OpenSearch write-back contention, not
enrichment itself), which is far too slow a feedback loop for iterating
on a genuinely new capability like local-LLM narratives. Two changes,
built together since the second only has value once the first exists:

1. **`--llm-provider ollama`** added alongside the existing anthropic/
   openai/none choices. New `_call_ollama()` hits Ollama's `/api/generate`
   (`{"model", "prompt", "stream": false}` → `{"response": ...}`) —
   confirmed live and reachable from `secpipe-stack`'s network at
   `framework.gibbsgreatly.xyz:11434`, `laguna-s-2.1:q4_k_m-ctx131k`
   confirmed loaded (both re-verified 2026-09-01, not assumed from an
   older memory note). No API key needed (`llm_ready` gating logic
   updated so ollama doesn't false-WARN on a missing anthropic/openai
   key). Longer default timeout (120s vs 30s) — a local 117B model
   genuinely takes longer per call than a hosted API, matching this
   project's own BFCL timing numbers for this exact model
   (`project_laguna_ollama_runtime` memory).
2. **`--max-cves`/`MAX_CVES` wired into the systemd unit** as
   `cve_enrichment_sync_max_cves` (role default `0` = unlimited, the
   standing scheduled timer's real behavior unchanged). The CLI flag
   itself already existed and already capped the per-CVE loop regardless
   of which path (full enrich or the cheap backfill) a given CVE takes —
   it just wasn't exposed as a documented, repeatable lever before.

**Quick test-run invocation** (fast, small-scope, no redeploy needed —
run directly on `secpipe-stack` once this phase's code is live there):
```bash
ansible secpipe-stack -i terraform/lxc/environments/pve/secpipe-stack/inventory.yml -u root \
  -m shell -a "bash -c 'set -a; source /opt/cve-enrichment-sync/es-user.env; \
  export ELASTICSEARCH_URL=https://<opensearch-ip>:9200 ES_FINDINGS_NO_VERIFY_TLS=1 \
  CVE_MCP_URL=http://<mcp-utility-ip>:8000/mcp LLM_PROVIDER=ollama MAX_CVES=10 \
  FORCE_REFRESH... ; python3 /opt/cve-enrichment-sync/cve_enrichment_sync.py'"
```
(`--force-refresh`/`FORCE_REFRESH` isn't currently read from an env var —
pass it as a literal CLI arg appended to the python3 invocation, since
this is a manual/direct run, not going through the systemd
EnvironmentFile mechanism — needed to actually exercise the LLM call
path on CVEs that are already enriched, since the cheap skip-fresh path
would otherwise short-circuit before reaching `synthesize_narrative()`.)
`MAX_CVES=10` bounds this to the top 10 CVEs by exposure breadth —
seconds to low-single-digit-minutes even with a slower local model, not
20-75 minutes.

**Not yet done**: no actual comparison test run against Ollama has been
executed — this phase built the capability, validation is next. The
standing scheduled timer's `cve_enrichment_sync_llm_provider` default
stays `anthropic` until that validation happens; this is a deliberate
gate, not an oversight — see the defaults file's own comment.

### Phase 8 (next, not yet started): dashboard rebuild

(Numbering note: this section was originally "Phase 7" in the same
paragraph that scoped local-LLM migration as "Phase 6" — that collided
with the production/zone classification work this document's own Phase 6
heading above actually covers. Renumbered 2026-09-01: LLM migration is
now Phase 7, dashboard rebuild is Phase 8. No content changed, only the
numbers.)

Once the above is verified live (spot-check a known lab CVE shows
`in_production:false`, a known real-infra CVE shows `true` + correct
zones), rebuild "Threat & Vulnerability Overview": production-only
default view (operator's decision — lab/practice findings de-emphasized,
not deleted, still queryable), a by-source breakdown panel, and a
by-zone risk panel. Not step-blocked yet — do after Phase 6 is proven
live, per this project's own "literal, not guessed" planning rule.

**Done, 2026-09-01.** Added three new panels to "Threat & Vulnerability
Overview" via the OpenSearch Dashboards saved-objects API (same
Global-tenant-as-admin technique already proven for the `wazuh-findings`
index pattern): `threat-by-source` (terms on `sources.source` + avg
`risk_score`), `threat-by-zone` (terms on `zones` + avg `risk_score` +
summed `total_instances`), `threat-production-split` (terms on
`in_production`). Also set the dashboard's own default query to
`in_production: true` (KQL, in `kibanaSavedObjectMeta.searchSourceJSON`)
— filters every panel to production-only by default, fully clearable in
the viewer's own search bar; nothing is deleted or hidden from the
underlying index.

Verified against the real aggregations (not just that the panels saved):
`harbor` 10,131 CVEs (avg risk 12.45), `wazuh` 177 (avg risk 9.93),
`greenbone` 19 (avg risk 20.18 — smaller finding set, skews higher-risk).
Filtered to `in_production:true`: 4,185 total, `harbor` 4,134 +
`wazuh` 177 (sums exceed the total since a CVE can span both sources).
**Correction, 2026-09-01, same day**: the "`greenbone` contributes zero
production findings" conclusion originally written here was wrong — see
the gvm-bridge GMP-user-scoping bug below. `gvm-bridge` was only ever
authenticating as a scoped `pentagi-integration` GMP user that could see
3 of 23 real GVM tasks; once fixed to authenticate as `admin`, GVM's
production-finding contribution went from 0% to 96%. Left the original
paragraph above intact (not deleted) as a record of the mistake and how
it was caught (operator directly challenged it, see the CORRECTION
section further down) — do not cite "greenbone contributes zero
production findings" as current fact anywhere else in this doc.

Not done as part of this pass (fine as follow-on, not blocking): the two
existing "Top CVEs" tables (`threat-top-by-risk-score`/
`threat-top-by-exposure`) weren't updated to also respect the new
production/zone fields as explicit columns — they already inherit the
dashboard-level `in_production:true` default query, so they show
production-only results too, just without a dedicated column calling
that out (their existing `assets_summary` column from Phase 4 already
surfaces per-source detail).

### CORRECTION 2026-09-01: index templates don't retroactively remap an existing index

Deployed threat-vuln-04-01/02 to `secpipe-stack`, confirmed the updated
`unified-cve-exposure.json` template registered fine
(`GET _index_template/unified-cve-exposure` showed the new
`assets`/`assets_truncated`/`assets_summary` properties) — but a `GET
/unified-cve-exposure/_mapping` on the **live** index showed the old
mapping, still `"dynamic": "false"` with no new fields. Index templates
only apply their mapping at index-creation time; an already-existing
index (this one's been live since Phase 1) never picks up a template
change on its own. Combined with `dynamic: false` at the top level, any
document write carrying `assets_summary`/`sources[].assets` would have
had those keys silently dropped from the indexed/aggregatable view (each
of the three `*-findings` roles' respective template files have this
same characteristic — worth remembering before assuming a template edit
alone is sufficient the next time one of them changes shape).

Fixed with an explicit `PUT /unified-cve-exposure/_mapping` carrying the
same `sources.assets`/`sources.assets_truncated`/`assets_summary`
properties, applied directly to the live index (mapping *additions* are
always backward-compatible in OpenSearch — no reindex required). Verified
via a follow-up `GET` that all three fields are now present on the live
index's own mapping, not just the template.

## Phase 9 (next session, not started): stack-centric UVM view — "which of my stacks is broken"

Operator feedback 2026-09-01, after Phase 8's dashboard rebuild and the
GVM visibility fix both landed: **the dashboard still has nothing on it
about which stacks have which findings.** Every panel built so far
(by-source, by-zone, production-split, the two top-CVE tables) answers
"where does risk come from" and "is it real" — none of them answer the
question that actually drives action in a home lab: *what do I need to
go patch, on which of my stacks, this week.* That's an asset-centric
axis, and it was never built. This is a real, correctly-scoped gap, not
scope creep — write it up in full so next session can start straight
into implementation rather than re-deriving this diagnosis.

### Root cause (confirmed in code, not guessed)

Stack identity exists inconsistently across the three findings sources,
and — separately, more importantly — **it never survives the
cross-source correlation step even where it does exist**:

- **Harbor**: already computes `artifact.stack` per document (Phase 6's
  `classify_artifact()` against `known_production_images.json`).
- **Wazuh**: has it for free — `target.stack` is set to the literal
  agent name, which *is* the stack name (see
  `wazuh_findings_sync.py`'s `build_document()`).
- **Greenbone**: `target.stack` is hardcoded `None` —
  [gvm_findings_sync.py:131](../../terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py#L131):
  `"stack": None,  # not automatic -- GVM scans raw IPs, not stacks`.
  GVM only ever sees IP:port, with no reverse lookup to a stack name
  attempted.
- **`cve_enrichment_sync.py`'s per-CVE rollup carries `zones[]` into
  `unified-cve-exposure` (Phase 6) but never `stacks[]`.** Even for CVEs
  whose Harbor/Wazuh source documents already have a populated `stack`
  field, that identity is dropped at the correlation step — `zones` and
  `production_count` sub-aggs exist in `fetch_cve_instances()`, a
  `stacks` sub-agg does not. So today, no query anywhere in the pipeline
  can answer "show me everything wrong with authentik-stack" — the only
  per-CVE asset detail is the free-text `assets_summary` column (Phase
  4), which is CVE→assets, not stack→CVEs, and isn't a real
  keyword/aggregatable field a dashboard panel can bucket on.

### What a real home-lab UVM needs (reasoned from first principles, not enterprise-tool cargo-culting)

The asset/stack axis needs to be the **primary** view, not a filter
bolted onto a CVE-centric one:

1. **Stack Risk table** (the front page) — one row per known deployed
   stack: critical/high/medium/low finding counts, which source(s)
   actually cover it (Harbor image scan? GVM network scan? Wazuh
   agent?), last-seen timestamp per source.
2. **Coverage gaps** — genuinely valuable once stack identity is
   populated everywhere: which stacks have zero Wazuh agent, or have
   never had a GVM scan hit them. Not a hypothetical — per
   `project_wazuh_stack_status` memory, only 6 of the ~20 real deployed
   stacks have a Wazuh agent enrolled today, so this table starts
   non-empty and immediately useful.
3. **Drill-through**: click a stack, see its actual CVE list (the
   inverse of what Phase 4's `assets_summary` already gives — that's
   CVE→assets; this needs stack→CVEs, which requires `stacks` to be a
   real terms-aggregatable field on `unified-cve-exposure`, not a text
   blob).
4. Keep by-source/by-zone/production-split (Phase 8) as macro filters
   layered on top of the stack view, not the primary lens.

### Concrete technical plan for next session

1. **`gvm_findings_ingest` role** (`gvm_findings_sync.py`): replace the
   hardcoded `"stack": None` with a reverse IP→stack lookup. Reuse
   `.env`'s existing `LAB_IP_*` registry (already the canonical
   IP→stack mapping in this repo — do not invent a second one) rather
   than a new hand-maintained JSON file, matching this project's own
   "don't duplicate a registry that already exists" lesson from
   `known_production_images.json`'s design in Phase 6. IPs that don't
   match anything (workstations, RPis, IoT, `pve` itself, `pve-test-vm`)
   stay `stack: null` — same graceful-degrade pattern already used for
   `zone: null` on non-VLAN-zoned hosts. Needs a small helper to parse
   `.env`'s `LAB_IP_<NAME>='<ip>'` lines into a `{ip: stack_name}` dict
   at role-deploy time (templated into the role's own assets, similar
   to how `known_production_images.json` is templated in) — build this
   fresh next session rather than guessing the exact stack-name string
   per IP, since a couple of `.env` entries (`LAB_IP_FRAMEWORK`,
   `LAB_IP_COMFYUI`, `LAB_IP_LLM_GPU` all resolve to the same host,
   `192.168.1.8`, which is bare-metal `framework.gibbsgreatly.xyz`, not
   a "stack") need an explicit non-stack judgment call, not an
   auto-derived one.
2. **`gvm-findings.json` template**: no change needed — `target.stack`
   already exists as a mapped keyword field (added in Phase 6), just
   unpopulated.
3. **`cve_enrichment_sync.py`**: add a `stack_field` entry per source to
   `ASSET_FIELD_SPECS` (`"artifact.stack"` for harbor, `"target.stack"`
   for greenbone/wazuh — all three already exist as real keyword fields
   on their respective source indices, no template changes needed
   there). Add a `"stacks": {"terms": {"field": stack_field, "size":
   20}}` sub-agg to `fetch_cve_instances()`, parallel to the existing
   `zones` sub-agg. Thread `entry["stacks"] = set()` /
   `entry["stacks"].update(info["stacks"])` through `main()`'s
   aggregation loop the same way `zones` is threaded today, and add
   `"stacks": entry["stacks"]` to both the skip-fresh refresh-trigger
   condition and the final upsert `doc` dict.
4. **`unified-cve-exposure.json` template**: add `"stacks": {"type":
   "keyword"}` alongside the existing `zones` field.
5. **Live mapping PUT**: same "index templates don't retroactively
   remap an existing index" gotcha documented immediately above this
   section applies again — `unified-cve-exposure` is long-lived, so a
   `PUT /unified-cve-exposure/_mapping` with just the new `stacks` field
   will be needed after the template change, before the next
   `cve-enrichment-sync` run, exactly like every other field added this
   way so far.
6. **Dashboard**: two new panels via the same OpenSearch Dashboards
   saved-objects API technique already proven three times over (Phase
   4, Phase 8) — a "Risk by Stack" table (terms on `stacks` + counts by
   severity/risk band) and a "Coverage Gaps" panel (requires a small
   amount of extra thought at build time: this likely needs a *known
   stacks list* to diff against, not just "what appears in the data,"
   since a stack with zero findings from a given source is invisible to
   a plain terms-agg on that source's own index — probably best solved
   by aggregating `stacks` per source independently and diffing against
   the full `.env` `LAB_IP_*` list client-side in the panel build
   script, not something OpenSearch's own aggregation DSL does for free).

### Deploy sequence (matches this project's established pattern)

`gvm_findings_ingest` role change → redeploy `greenbone-stack` → resync
`gvm-findings-ingest` → `cve_enrichment_sync` template/role change →
redeploy `secpipe-stack` → live `PUT` mapping on `unified-cve-exposure`
→ resync `cve-enrichment-sync` (full corpus, not `--max-cves`-capped,
since this is a schema change affecting every CVE, not a narrow test) →
rebuild dashboard panels → verify against real aggregation numbers, not
just that the panels saved.

**Done and deployed live, 2026-09-01 (same day, not "next session" —
operator asked to start immediately).** Full pipeline built and
verified end-to-end:

- `ip_to_stack.json` (reverse IP->stack registry from `.env`'s
  `LAB_IP_*`) + `gvm_findings_sync.py`'s `target.stack` lookup, deployed
  via a NEW `findings-ingest` tag on the `gvm_findings_ingest` play
  (see below) rather than a full `greenbone-stack` redeploy.
- `stacks[]` threaded through `cve_enrichment_sync.py`'s correlation
  rollup exactly parallel to `zones[]`, `stacks: keyword` added to
  `unified-cve-exposure`'s template + a live `PUT` mapping (same
  templates-don't-retroactively-remap gotcha as every time before).
- Full `cve-enrichment-sync` resync: `cves_seen=10152
  sources_refreshed=10152 errors=0`.
- **Verified real per-stack numbers**: `authentik-stack` 3,010 CVEs,
  `greenbone-stack` 1,471 (expected -- it scans itself), `proxy-stack`
  595, `opensearch-stack` 567, `wazuh-stack` 539, plus Wazuh's own
  agent-name-as-stack entries flowing through independently of the new
  GVM registry (`pve.gibbsgreatly.xyz`, `wazuh.manager`,
  `gaming-stack`) -- confirms Harbor/Wazuh's pre-existing stack identity
  and GVM's newly-added one both correctly feed the same `stacks[]`
  field. Crit/High counts are 0 for almost every stack right now --
  genuinely sparse data (only 14 Critical / 11 High exist across all
  10,152 CVEs total), not a pipeline bug.

### Dashboard rebuilt from scratch, same session

Operator feedback mid-session: the Phase 8 panels were "pretty useless"
(2 were actually broken -- see below) and didn't show per-stack risk at
all. Discarded all 7 existing panels (unlinked from the dashboard, saved
objects left in `.kibana` in case anything's wanted back) and replaced
with 6 new ones:

1. **Vulnerability Exploitability Funnel** (`vuln-exploit-funnel`) --
   horizontal bar chart, a `filters` bucket agg with 3 stages: "All
   Vulnerabilities" (match-all) -> "Exploit Exists (PoC or Active)"
   (`poc_available:true OR kev_listed:true`) -> "Actively Exploited
   (CISA KEV)" (`kev_listed:true`). Real numbers: 10,280 -> 58 -> 14
   unfiltered; 4,307 -> 19 -> 0 under the dashboard's `in_production:true`
   default (zero actively-exploited-in-production right now -- genuine
   good news, confirmed not a bug).
2. **Risk by Stack - Overview** (`stack-risk-overview`) -- table, terms
   on `stacks`, metrics: Total CVEs, Avg Risk Score, Sources Reporting
   (cardinality of `sources.source`).
3-6. **Critical/High/Medium/Low by Stack** (`stack-risk-critical/high/
   medium/low`) -- 4 near-identical tables, same `stacks` terms bucket,
   each with its own `risk_band` search-level filter and a plain Count
   metric, laid out as 4 narrow columns side by side. **Not a single
   pivoted table** -- classic OpenSearch Dashboards visualizations
   cannot pivot a bucket into columns (that needs Lens or a hand-written
   Vega spec, neither used here); this is 4 separate panels achieving
   the same "crit/high/med/low as columns" visual layout the operator
   asked for, built from the same proven filtered-table pattern already
   used elsewhere on this dashboard. Revisit with Vega if a genuine
   single-widget pivot table is wanted later.

**Two real bugs found and fixed as part of this, unrelated to the new
panels**: the operator reported `threat-by-zone`/`threat-production-split`
showing "Could not locate that index-pattern-field (id: zones)" /
"(id: in_production)". Root cause: the `unified-cve-exposure`
index-pattern saved object's own cached `fields` list (a JSON blob
Dashboards uses for field autocomplete/validation, separate from the
live index mapping) was stale from 2026-08-18 -- creating/updating an
index's *mapping* does NOT refresh a Dashboards index-pattern's cached
field list; that only happens via an explicit "Refresh field list"
action (the UI button, or replaying its logic by hand). Fixed twice this
session (once after adding `zones`/`in_production`/`stacks_summary`
fields, again after adding `stacks`) by fetching the live `_mapping`,
flattening it into Dashboards' expected field-descriptor shape, and
`POST`ing it onto `index-pattern:unified-cve-exposure` directly. **Add
this as a required step any time a new field is added to
`unified-cve-exposure`'s template** -- it's now the third
mapping-related gotcha for this index family (see the two entries
above), and unlike those, it's specific to Dashboards' own saved object,
not the index itself.

### CORRECTION 2026-09-02: dashboard rebuilt again -- funnel error fixed, stack view is now one real table

Operator feedback on the just-shipped rebuild: the funnel visualization
errored (`horizontal_bar` type, custom `categoryAxes`/`valueAxes`
params -- exact cause not confirmed, but this cluster's classic-viz bar
chart params schema is evidently more version-sensitive than the
already-proven table type), and the 5-panel stack view (overview + 4
severity columns as separate panels) wasn't what was wanted -- operator
explicitly asked for ONE table, each stack a row, with
critical/high/medium/low + risk as real columns.

**Funnel**: converted from `horizontal_bar` to `table` type, same 3-stage
`filters` bucket aggregation, now rendering correctly (matches every
other panel on this dashboard, all of which use `table`).

**Stack view**: classic OpenSearch Dashboards visualizations genuinely
cannot pivot an aggregation bucket (`risk_band`) into real table columns
from a live query against `unified-cve-exposure` -- confirmed this is a
hard limitation (Lens or a hand-written Vega spec would be needed
otherwise, neither in use in this repo). Solved by materializing the
pivot server-side instead: added `compute_stack_rollup()` to
`cve_enrichment_sync.py`, called unconditionally at the end of `main()`.
It aggregates `unified-cve-exposure` (terms on `stacks` + a `filter`
sub-agg per `risk_band`, the exact same technique already proven in
`fetch_cve_instances()`'s `production_count`) and writes one flat
document per stack into a new `stack-risk-summary` index --
`{stack, total_cves, critical, high, medium, low, avg_risk_score,
sources_reporting, updated_at}`. Full recompute every run (cheap -- at
most a few dozen stacks) plus a cleanup pass deleting rows for stacks
that no longer appear at all, so the index can't accumulate stale
entries for decommissioned stacks. New `stack-risk-summary.json`
template (wired into `es_setup_assets.py`'s existing glob-all-templates
pattern) and the `es_findings_writer` role's `index_patterns` extended
to cover it.

The dashboard panel itself is now trivial by construction: a plain
`table` viz on `stack-risk-summary` with a `terms` bucket on `stack` and
`max` metrics on each numeric field (valid, since there's exactly one
document per stack -- `max` just returns that document's value; no
`filter`-as-metric mistake this time, that only works as a `bucket`
schema in classic viz, not `metric`). Verified live: `wazuh-stack`
(C0/H1/M4/L516), `authentik-stack` (3,010 total, avg risk 10.8),
`greenbone-stack` (1,471, expected -- self-scanning), 19 stacks total.
The old 5-panel version (`stack-risk-overview` +
`stack-risk-critical/high/medium/low`) was fully deleted, not just
unlinked -- explicitly superseded, unlike the original Phase 8 panels
which were only unlinked.

Dashboard is now exactly 2 panels: the funnel, and this one stack risk
table.

### Also fixed this session: `gvm_findings_ingest` tagged for scoped redeploys

Operator feedback: routine code-only changes to this role (like the
`ip_to_stack.json` addition above) still forced running the ENTIRE
`deploy-greenbone-stack.yml` playbook, including the compose play that
unconditionally resets the gvmd admin password, re-enables LDAP auth,
and re-creates both GMP users on every single run -- "it's scary every
time I run this playbook." That play was already documented as purely
additive (new role, new systemd timer, doesn't touch gvmd/gvm-bridge/
credentials) but had no way to run it alone. Fixed by adding
`tags: [findings-ingest]` to the play -- `ANSIBLE_TAGS=findings-ingest`
(provision.sh already passes this through, same mechanism the existing
`scan-program` tag uses) now skips straight to it. Verified live:
`ok=14 changed=1` vs. the usual `ok=96 changed=11` for a full run. The
underlying "the compose play has no real idempotency, it just always
reports changed" design gap (see "operator feedback" note above) is
still not fixed -- this tag is a scoped workaround for changes that
only touch `gvm_findings_ingest`, not a general fix for every future
change to this playbook.
