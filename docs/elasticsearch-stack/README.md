# Elasticsearch Stack — Ideas

## Status

**Ideation only. Nothing has been built.** This document exists to seed a
future session. See `docs/workflow/documentation-workspaces.md` for how
this workspace should evolve (durable conclusions here, scratch material
in `artifacts/`).

## Goal

Operator's framing: use Elasticsearch as a place to **store, normalize,
and process** vulnerability/security findings — starting with Harbor's
scan results, but not necessarily limited to Harbor. This grew out of
[Harbor vulnerability remediation work](../../docs/harbor-stack/README.md)
and directly supersedes the storage-layer part of the alerting plan
captured in memory as `project_harbor_alerting_automation_plan` — that
plan assumed Graylog/Grafana as both store and alert surface; this
direction splits it: **Elasticsearch as the store/normalization layer**,
with Graylog/Grafana/Kibana as possible surfaces on top.

## Relevant existing state

- **There is a legacy Elasticsearch container already in the infra,
  unmaintained.** Confirmed by the operator 2026-08-17; not otherwise
  identified (host/IP unknown to this doc). **Explicitly out of scope —
  leave it alone.** Not being migrated from, not being decommissioned as
  part of this work, just noted for awareness so it isn't mistaken for
  live/current if stumbled across.
- **The new container's target host is undecided — deferred to whatever
  session actually does this work.** Confirmed explicitly: this is *not*
  the `elastic-stack` LXC shell described below (checked live,
  2026-08-17: nothing listening on 9200 or 5601 there, matching its empty
  Terraform state) — the operator wants a genuinely different/new
  LXC/host, not a reuse of that reserved slot. Don't assume placement;
  that's a decision for the implementing session.
- **`elastic-stack` exists as an empty LXC shell** —
  `terraform/lxc/stacks/elastic-stack/` (vmid 112, `192.168.1.24`, on
  production `pve`). Currently just registers a Portainer agent; no
  compose stack, no playbook, and confirmed not the legacy container
  either (nothing running there at all). **Not the target for this
  work** per the operator — mentioned here only so it isn't confused
  with either the legacy container or the new one.
- **`security-stack`** (vmid 109, `192.168.1.11`) and **`analysis-stack`**
  (vmid 110, `192.168.1.16`) are the same kind of empty reserved shell,
  also on production `pve`. Unrelated unless a future session decides
  otherwise.
- **Graylog already runs its own OpenSearch backend** ("Graylog Data
  Node" — see `terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml`).
  OpenSearch is an Elasticsearch fork, API-compatible for indexing/search
  at the REST/bulk-API level. This means a search-engine-class datastore
  is already live in production. Worth an explicit decision: reuse
  Graylog's OpenSearch (new index alongside its log indices) vs. stand up
  a dedicated Elasticsearch in the empty `elastic-stack` shell. Leaning
  toward **dedicated** — Graylog manages its own index sets/rotation/
  retention internally, and writing unrelated structured data (vuln
  findings, not log lines) into the same cluster couples two different
  lifecycles and complicates future Graylog upgrades. But it's cheap
  infra-wise to at least test against Graylog's OpenSearch first before
  committing to a second JVM-heavy service.
- **Network placement:** `192.168.1.x` is the general/unsegmented LAN,
  not one of the VLAN-segmented zones Harbor/apt-cacher/NetBox use
  (`infra_seg`, confirmed for pve-test-vm's `10.57.x.x` scheme; production
  uses a `192.168.X0.x` per-service pattern instead — e.g. Harbor
  `192.168.40.10`, Portainer `192.168.20.120`). Note: the SDN VLAN design
  memory this references is 125+ days old and pve-test-vm-specific —
  re-verify production's actual zone layout before relying on it. Worth
  deciding whether a store holding vulnerability data should sit in a
  more controlled zone rather than the general LAN block the shell
  currently occupies.
- **Greenbone/GVM is also live in production** with its own, separately-
  queried findings model (`get_results` — see
  `reference_gvm_scan_gotchas` in memory). Its scan results are not
  currently correlated with Harbor's image-scan results anywhere. This is
  a second real data source for the same kind of store. **Checked live
  2026-08-17: GVM has no OpenSearch (or Elasticsearch) component to tap
  directly** — an idea floated when this section was scoped. Confirmed via
  `docker compose config --services`/`ps` against production
  `greenbone-stack`: the full service list is `gsad`, `gvm-bridge`,
  `gvmd`, `nginx`, `openvasd`, `ospd-openvas`, `pg-gvm`, `redis-server`,
  plus flat feed-data volumes (`notus-data`, `scap-data`,
  `cert-bund-data`, `dfn-cert-data`, `vulnerability-tests`). Storage is
  entirely PostgreSQL (`pg-gvm`, owned by `gvmd`) plus Redis as
  `ospd-openvas`/`openvasd`'s scan-queue cache — no search index anywhere
  in the stack, and nothing in Greenbone's own architecture docs suggests
  Community Edition ever had one. See the "GVM ingestion" section below
  for the actual (GMP-based) path in. This corrects an assumption, not a
  design already committed to — no code was written against the OpenSearch
  idea.
- **PentAGI** has its own findings/results too (pentest run output),
  potentially a third source, lower priority.

## Ideas

### 1. Data model

One document per **finding-per-artifact-per-scan**, not per-CVE-globally
(a CVE can appear in many artifacts with different fix status). Rough
shape:

```json
{
  "source": "harbor",
  "finding_id": "CVE-2026-31789",
  "severity_raw": "Critical",
  "severity_assessed": "informational",
  "assessed_reason": "32-bit-only precondition, all infra is x86_64",
  "assessed_by": "claude-session-2026-08-17",
  "assessed_at": "2026-08-17T00:00:00Z",
  "package": "openssl",
  "package_version": "3.5.5-1~deb13u1",
  "fixed_version": "3.5.5-1~deb13u2",
  "artifact": {
    "project": "mirror",
    "repository": "ghcr/goauthentik/ldap",
    "tag": "2026.5.6",
    "digest": "sha256:...",
    "in_production": true,
    "stack": "authentik-stack"
  },
  "scan_time": "2026-08-17T04:26:10Z",
  "first_seen": "2026-08-16T04:26:10Z",
  "last_seen": "2026-08-17T04:26:10Z"
}
```

`severity_raw` vs `severity_assessed` is the important split — Harbor/
Trivy's CVSS label routinely overstates real risk (see the openssl
example above, assessed this session). Keeping both, plus who/when/why
for the assessed value, is what turns "325 Critical findings" into
something a human can actually act on, and is the main thing Harbor's own
dashboard can't do today.

`first_seen`/`last_seen` (upsert semantics, not append-only) turns this
into a trend store — "how long has this been open," "did this count go
up or down this week" — which Harbor's dashboard is also bad at (it only
shows current state).

### 2. Ingestion

Options, roughly in order of how much new infra they need:

- **A: scheduled pull script** (same shape as `harbor_repull.py`, but
  reading instead of pulling) — queries Harbor's
  `GET .../artifacts/{digest}/additions/vulnerabilities` for every
  cataloged artifact, bulk-indexes into ES. Simple, no new service, easy
  to run right after `harbor-repull.timer` finishes (~04:30 UTC, see
  `project_harbor_alerting_automation_plan` in memory for the exact
  timing gotcha). Downside: still polling, and has to re-derive the
  mirror-project-vs-original-project asymmetry that caused this session's
  whole visibility bug — needs to bake in "query `mirror/*` for
  gcr/ghcr/quay/greenbone/lscr, query the project directly for
  `dockerhub`" as a hardcoded fact, or it'll silently under-report again.
- **B: Harbor webhook → small HTTP receiver → ES.** Reacts to
  `SCANNING_COMPLETED` instead of polling — confirmed this session that
  Harbor's webhook API exists and is currently unconfigured on every
  project. Needs a small always-on receiver service (could live in the
  new `elastic-stack` LXC itself). More real-time, more moving parts.
  Same mirror-project caveat as (A) applies to how the receiver resolves
  "which artifact was this."
- **C: Logstash/Beats-style pipeline.** Full ELK-idiomatic path (Logstash
  HTTP input or a custom Beat polling Harbor's API on a schedule). Heavier
  than (A)/(B) for not much extra benefit at this scale — Harbor's API is
  small and clean enough that a plain Python script is probably the right
  amount of engineering, at least to start.

Recommendation to open the future session with: start with **A**, since
it reuses the exact pattern already proven with `harbor_repull.py`
(idempotent, tolerant of individual failures, stdlib-only), and revisit
webhooks (B) later if polling proves too slow or too chatty.

### 3. GVM/Greenbone ingestion (second source)

**Correction to the original framing**: there is no OpenSearch (or any
search index) inside GVM to connect to directly — see "Relevant existing
state" above. Ingestion has to go through GMP, the same protocol
`gvm-bridge`, `setup_scan_program.py`, and `setup_schedules.py` already
use successfully — it's a well-proven path in this repo by now, not new
ground.

**Real query shape**: `gmp.get_results(filter_string="task_id=<id> rows=-1")`
via `python-gvm`, run inside the throwaway `gvm-tools` container against
`gvmd`'s Unix socket — same pattern as every other GVM script in this
repo. Two gotchas already paid for, both in `reference_gvm_scan_gotchas`
in memory, apply directly here:
- Use `get_results`, never `get_reports` — the latter has a real,
  reproducible upstream crash bug (`greenbone/gvmd` #2273-class).
- Always add `rows=-1` to `filter_string` — the 10-row pagination default
  silently truncates results otherwise.

**Real document shape**, confirmed live 2026-08-17 against a production
`get_results` call (not guessed from docs — GVM's result schema isn't
fully documented anywhere public):

```json
{
  "source": "greenbone",
  "finding_id": "1.3.6.1.4.1.25623.1.0.108440",
  "cve": [],
  "name": "Cleartext Transmission of Sensitive Information via HTTP",
  "severity_raw": 4.8,
  "threat_raw": "Medium",
  "qod": 80,
  "severity_assessed": null,
  "assessed_reason": null,
  "assessed_by": null,
  "assessed_at": null,
  "target": {
    "host": "192.168.20.14",
    "hostname": null,
    "port": "9000/tcp",
    "zone": "mgmt_seg",
    "stack": "monitoring-stack",
    "in_production": true
  },
  "scan_task": "LAN scan: mgmt_seg full-vuln",
  "scan_time": "2026-08-16T11:40:43Z",
  "first_seen": "2026-08-16T11:40:43Z",
  "last_seen": "2026-08-16T11:40:43Z"
}
```

Notable differences from the Harbor shape, all real (drawn from the
actual GVM result element, not assumed to mirror Harbor's):
- **`finding_id` is an NVT OID, not always a CVE.** A lot of real GVM
  findings — the example above included — are config/protocol-level
  issues (cleartext HTTP, weak ciphers, missing headers) with no CVE at
  all. Use the OID as the stable per-finding key; attach any CVE(s)
  separately when the NVT's `refs` actually includes a `type="cve"`
  entry, don't assume one exists.
- **`target` replaces `artifact`**: host IP (+ optional hostname, GVM
  usually leaves this empty on IP-only discovery), port/protocol, and a
  `zone` derivable for free from `setup_scan_program.py`'s existing
  `ZONES` table (same CIDR→zone map already lives there — reuse it, don't
  re-derive). `stack` is not automatic — GVM has no concept of "which
  Docker stack owns this host," so this needs the same kind of
  cross-reference NetBox/`static_hosts` enrichment as Harbor's
  `in_production`/`stack` fields (see Enrichment below), and won't be
  populated for genuinely-unknown/untracked LAN devices.
- **`qod` (Quality of Detection, 0–100) has no Harbor equivalent** and is
  worth carrying through as-is rather than discarding — a Medium-severity
  finding at `qod: 30` is a much weaker signal than the same severity at
  `qod: 95`, and GVM already computes this per-finding.
- **Severity scale mismatch, a real open question, not resolved here**:
  the example finding's `cvss_base_vector` (`AV:A/AC:L/Au:N/...`) is
  CVSS **v2** syntax — GVM's own `threat` bucketing (`Log`/`Low`/`Medium`/
  `High`/`Critical`) doesn't necessarily land on the same numeric cut
  points Harbor/Trivy's CVSS v3-based `severity_raw` buckets do. Don't
  assume a shared `severity_assessed` scale lines the two sources up
  automatically — that mapping needs an explicit decision, not an
  inherited assumption, before cross-source severity comparisons are
  trustworthy.
- **Ingest-time noise filter strongly recommended**: real overnight
  production data (2026-08-17, the first live scheduled run — see
  `docs/greenbone-stack/network-scan-rollout-plan.md`'s Phase 4 section)
  showed `threat=Log` (purely informational, not a real severity) made up
  roughly 90–95% of every zone's raw result count (e.g. `mgmt_seg`: 702
  of 740 results were `Log`). Indexing all of it as-is would make the
  store almost entirely noise — drop `threat=Log` at ingest, or at minimum
  don't let it dominate any default view.
- **Reuse the existing red-team exclusion list** for the same
  `pentest_target: true` enrichment idea already planned for Harbor's
  `kali`/`vulhub` images — GVM's routine scan population already excludes
  Metasploitable2/`harness-target` via `REDTEAM_EXCLUDE` in
  `setup_scan_program.py`, so this doesn't need a new source of truth,
  just the same list reused on the ingest side.

**Ingestion approach**: same Option A (scheduled pull) pattern recommended
for Harbor below, run per completed Task after the weekly full-vuln
schedule finishes — the `lan` zone (last in the stagger, per Phase 4) is
scheduled to finish around 05:00–06:00 Pacific/Auckland depending on scan
duration, a natural timing hook once daily-discovery scheduling (Phase
4's still-open half) also exists.

**Scope decision this section still leaves open**: whether to ingest
Discovery-task results too (they exist today but aren't on any schedule
yet — see Phase 4 status) or full-vuln only to start. Full-vuln only is
probably the better starting scope — it's where real severity data lives;
Discovery is mostly host-inventory (arguably NetBox's job, not this
store's) plus the same `Log`-heavy noise profile.

### 4. Normalization across sources

Once Greenbone/GVM findings are in the same index (same document shape,
`source: "greenbone"` instead of `"harbor"`, `target` instead of
`artifact` — see the GVM ingestion section above for the concrete field
mapping and the real caveats, especially the CVSS v2-vs-v3/threat-bucket
mismatch), a single query answers "what's our actual current exposure
across every scanner" instead of checking Harbor's dashboard and GVM's UI
separately. This is probably the single biggest win over the
Graylog/Grafana-only alerting plan — it's not just alerting, it's a real
unified inventory.

### 5. Enrichment worth doing at ingest time

- `in_production` / `stack` — cross-reference against what's actually
  running (`docker ps` sweep pattern used throughout this session, or a
  static map of project→stack) so a query can filter to "findings on
  images we actually run" vs. every cached artifact including old/unused
  tags. Applies to GVM's `target.stack` too, not just Harbor's `artifact`.
- `pentest_target: true` for the deliberately-vulnerable `kali`/`vulhub`
  images already allowlisted in the Harbor audit, and for GVM's own
  `REDTEAM_EXCLUDE` hosts (Metasploitable2/`harness-target`) — same idea,
  same reasoning, two different existing lists to reuse rather than
  re-derive.

### 6. Visualization

- **Reuse Grafana** (already live, already has an unexamined
  `harbor-cve-inventory.json` dashboard worth checking first) via its
  Elasticsearch datasource plugin — avoids standing up Kibana as a whole
  second UI with its own auth integration.
- **Or deploy Kibana** if richer index-management / dev-tools-console
  workflows end up mattering more than reusing existing dashboards.
  Would need the same Traefik+Authentik forward-auth fronting every other
  stack gets.

Lean toward Grafana-reuse first; it's less new surface to secure and
maintain, and the operator already lives in Grafana for the metrics side.

### 7. Operational considerations, from lessons already paid for elsewhere in this repo

- **Heap sizing**: Graylog's own OpenSearch Data Node needed careful heap
  sizing against the actual LXC memory budget (see that playbook's JVM
  options task) — don't reuse a default ES heap setting without doing the
  same sizing pass. See `reference_unified_memory_oom_sizing` in memory
  for the general pattern (applies beyond the Framework Desktop host it
  was found on).
- **Image pulls must go through Harbor correctly from day one** — use the
  corrected pull-then-tag pattern (try Harbor-routed pull first, fall
  back to upstream+tag only on failure), not the naive version that
  caused this session's whole Harbor-visibility investigation. See
  `reference_harbor_bootstrap_circularity` in memory.
- **`docker_socket_proxy` role** should front this stack's Docker socket
  like every other stack, for consistency and to avoid a bespoke
  exception.
- Expect the harness's own auto-mode permission classifier to block the
  first deploy/config action on this — see
  `reference_claude_code_automode_classifier` in memory; get a
  `.claude/settings.local.json` rule added up front.

## Open questions for the next session

- **Target host/IP/zone for the new container — genuinely undecided,**
  confirmed explicitly by the operator 2026-08-17. Not the `elastic-stack`
  shell, not the legacy container. Pick placement (including which
  network zone — see the stale SDN note above, re-verify production's
  real zone layout) as part of that session's own work, not assumed here.
- Dedicated Elasticsearch vs. reuse Graylog's OpenSearch — leaning
  dedicated (see above), but not decided.
- Ingestion approach: start with scheduled-pull (A) as recommended above?
  Applies to both Harbor and GVM now — same recommendation both places.
- **Scope: Harbor only to start, or Harbor + Greenbone from day one?**
  Still genuinely open — the GVM ingestion section above means the
  Greenbone half is now a concrete, de-risked plan (real document shape,
  known gotchas, known noise profile) rather than a vague "second source"
  note, so adding it isn't extra research work if the operator wants it
  from day one. But it's still more scope than Harbor alone, and the
  cross-source severity-scale mapping (CVSS v2 vs v3, GVM `threat` vs
  Harbor's qualitative bucket) is a real design decision neither source
  needs on its own — worth deciding deliberately, not defaulting to
  "both" just because both plans now exist.
- Visualization: Grafana datasource vs. Kibana?
- Retention: how long to keep historical findings — this is exactly the
  trend data Harbor's dashboard can't provide, so probably longer than
  Harbor's own 7-day artifact retention, but not decided.
- Anything worth checking on the legacy container before it's fully
  ignored (e.g. does it hold historical data anyone might want later)?
  Out of scope for now per the operator, but flagging in case that
  changes.
