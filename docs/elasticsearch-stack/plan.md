# Elasticsearch Stack — Deployment Plan

## Status

**Planning complete, nothing built yet.** This supersedes the open questions
in `README.md` with concrete decisions. `README.md` remains the ideation/
data-model source (finding shapes, GVM gotchas) — this doc is placement,
sizing, deployment mechanics, and phasing. **`runbook.md` turns this doc's
Phases 1–6 into concrete step-by-step commands with testing at each
stage** — read that when actually executing; this doc is the "what and
why," `runbook.md` is the "exact how."

Scope, confirmed with the operator 2026-08-17:

- Build a **new, well-integrated, single-node Elasticsearch stack** on the
  existing Terraform/Ansible/SDN/Authentik/Traefik/Harbor/Technitium
  platform — not a resurrection of Wazuh, Security Onion, or TPOTCE.
- Ingest from **Harbor** (vuln scan results) and **GVM/Greenbone** (network
  vuln scan results), per the data model and gotchas already captured in
  `README.md`.
- Reuse the **ingestion/normalization pattern** proven in `wazuh-analysis`,
  `so-analysis`, `tpotce-analysis`, and unified in `security-analysis`
  (index templates + ingest pipelines + transforms as declarative JSON
  assets, applied idempotently by a small setup script; a scheduled sync
  script with cursor-based state and deterministic doc IDs) — adapted into
  this repo's own conventions (systemd timer, not a standalone dev package).
  The actual Wazuh/SO/TPOT services stay untouched and out of scope; only
  the pipeline *shape* carries forward.
- Decide whether the legacy Elasticsearch container's storage needs to be
  reclaimed first. **Answer below: no.**
- **The actual end goal, stated explicitly by the operator 2026-08-17**:
  something in the shape of **Avalor or Ivanti Neurons for the home
  lab** — normalize and de-duplicate findings across sources, make them
  available for analysis by the **local LLM running on Framework**,
  enrich via **CVE-MCP**, and eventually **hand verified findings off to
  PentAGI** for actual penetration-testing. Grafana/Kibana are secondary,
  human-facing conveniences; **the primary interface is automation**.
  See "Beyond ingest" below — this reshapes the plan from "a place to
  put findings" into "a store an agent loop can read, enrich, and act
  on," and is why `findings-mcp` and the PentAGI handoff are in scope
  here at all, not a separate future doc.

## Development environment: `pve` directly, not `pve-test-vm`

**Decided 2026-08-17, operator directive, overrides this repo's normal
default for this project.** Every other CLAUDE.md validation tier assumes
`pve-test-vm` is the free-iteration ground and `pve` is the careful,
approval-gated promotion target. For this project specifically, that's
inverted: **development happens directly against `pve`**, and
`pve-test-vm` stays powered off except when a specific test is disruptive
enough to genuinely need an isolated environment first.

**Why — confirmed with real numbers, not just the general concern**:
`pve-test-vm` is a KVM *guest running on `pve` itself* (vmid 113), not
separate hardware — so its memory allocation directly competes with
`pve`'s own workloads for the same 125GB physical pool. Checked live
2026-08-17 (`free -h` / `qm list` on `pve`, read-only):

```
pve:  125Gi total, 96Gi used, 21Gi free, 29Gi available
pve-test-vm (vmid 113): 20480MB (20GB) allocated, cores=4, currently running
```

`pve` is already at ~77% memory utilization before counting any of this
project's own footprint. `pve-test-vm` alone is ~20GB of that — powering
it off is a meaningful, immediate relief, and more dev work piling onto
`pve-test-vm` (this project's original default target) would only make
that worse over time, which is exactly the pattern the operator flagged.

**What this means operationally**:

- The new `elasticsearch-stack` LXC gets provisioned on **`pve`**
  directly — a genuinely new, isolated `infra_seg` container, not a
  modification of anything already running. Blast radius of a mistake
  is still real (it's production), but scoped to a new resource, not an
  existing live stack.
- `pve` is a declared production node
  (`terraform/PRODUCTION_NODES`) — every mutating action against it
  (`terragrunt apply`, `pct create`, Ansible deploys) goes through the
  full CLAUDE.md "Approval Flow For Production Mutations": preflight
  summary → operator says "Proceed" in chat → `TASK_APPROVAL` set →
  `./with-secrets-prod`. **This is real, accepted friction** — iteration
  against `pve` will be slower and more deliberate than the normal
  free-form `pve-test-vm` workflow, one approval per distinct task, no
  standing blanket approval. That's the deliberate tradeoff here, not an
  oversight.
- Read-only inspection (checking state, `pvesm status`, `qm list`,
  `docker ps` on existing containers) doesn't need this flow — only
  actual mutations do.
- **`pve-test-vm` stays powered off by default for the duration of this
  project.** Per the operator: spin it back up only "under controlled
  conditions when we need to test something potentially disruptive" —
  e.g. validating a new SDN cross-zone rule before trusting it against
  live traffic, or anything else where getting it wrong on `pve` first
  would be a bad idea. Powering `pve-test-vm` on/off is itself a
  mutating action against `pve` (a guest running on it) — treat it the
  same as any other production mutation, not a free action, even though
  it's "just" starting/stopping a VM rather than touching Terraform
  state.
- **Sizing implication**: the ES+Kibana memory budget recommended below
  (Graylog's heap formula against a ~6–8GB container allocation) should
  be treated as a starting ceiling to reconsider, not a settled number —
  `pve` doesn't have much headroom to spare even with `pve-test-vm` off.
  Start smaller if the actual working set allows it (this store's data
  volume is genuinely small at launch — Harbor + GVM only, `threat=Log`
  filtered at ingest) and grow only if real usage demands it, same
  `mutation_policy: grow-only` philosophy already used for the storage
  volume.
- This directive is scoped to **this project**. It doesn't retroactively
  change the standing branch-model default for other work — flagging
  that explicitly rather than assuming it's a permanent repo-wide policy
  change, since that's a bigger call than this session's scope.

## The storage call

**No reclaim needed. Build fresh on the `storage` ZFS pool; treat legacy
decommission as separate, non-blocking cleanup.**

Checked live 2026-08-17 (`pvesm status` / `zpool list` on `pve`, read-only):

| Pool | Size | Used | Free | Used% |
|---|---|---|---|---|
| `monitoring` (legacy elastic-stack lives here) | 464G | 196G | 268G | 42% |
| `storage` (Harbor's data volume already lives here) | 1.81T | 201G | 1.62T | 10% |
| `security` | 1.81T | 210G | 1.61T | 12% |
| `rpool` / `infrastructure-containers` (default LXC rootfs pool) | 230G | 147G | ~61G at the PVE-storage-ID level | 72.5% |

Two separate facts, easy to conflate:

1. **The legacy container's own LXC disk (200G quota) is 93% full** — see
   below, real and worth fixing eventually.
2. **The underlying pool it sits on has 268G free**, and the pool this new
   stack should actually use (`storage`, via the same `durable-zfs`
   extra-mount profile Harbor already uses) has **1.62TB free**.

So the legacy container being full doesn't gate this work at all — there's
no shortage of raw capacity anywhere in the cluster. What *is* worth noting:
`rpool`/`infrastructure-containers` (the pool `platform-default` /
`platform-zfs` route plain LXC rootfs+docker storage to) is already at
72.5% with only ~61G free at the PVE-storage-ID level. That's fine for this
stack's rootfs+docker allocation (same modest size every other stack uses,
~16–20G), but it's a reason to put the actual Elasticsearch **data** on a
dedicated `extra_mount` against `durable-zfs` (→ the 1.62TB-free `storage`
pool) rather than growing the container's own rootfs — exactly the pattern
`harbor-stack` already uses for its 120G `harbor-data` volume. Don't grow
anything on `rpool` for this.

## Corrected facts about the legacy container

The operator's framing ("the original elasticsearch cluster... is also not
well maintained") is right, but `README.md`'s specifics were wrong and are
corrected here:

- **The legacy Elasticsearch *is* the `elastic-stack` LXC** —
  vmid 112, `192.168.1.24`, on production `pve`, storage backed by
  `monitoring/subvol-112-disk-0`. `README.md` said this shell was
  confirmed empty ("nothing listening on 9200 or 5601... checked live
  2026-08-17"); that check was wrong or against a stale state — as of this
  session, live checks show otherwise:
  - `systemctl` shows `elasticsearch.service`, `kibana.service`, and
    `elastic-agent.service` all **loaded/active/running**, natively
    installed (not Docker) — Elasticsearch 9.2.1, `/opt/Elastic`,
    `/root/elastic-agent-9.2.1-linux-x86_64`.
  - Ports 9200 (ES), 5601 (Kibana), and 8220 (Fleet) are open externally.
  - `/var/lib/elasticsearch` alone is **177G**, out of 186G used on the
    container's 200G volume (93% full, 14.8G free).
  - This is genuinely reachable from the legacy reverse proxy chain:
    `elastic-api.gibbsgreatly.xyz` / `elastic-fleet.gibbsgreatly.xyz` →
    (nginx-proxy-manager on `management-stack`, `192.168.1.4`) →
    `elastic-stack.gibbsgreatly.xyz:9200` / `:8220` → `192.168.1.24`.
    `so-api.gibbsgreatly.xyz` and `wazuh-api.gibbsgreatly.xyz` proxy
    elsewhere (`securityonion.gibbsgreatly.xyz` = `192.168.1.13`,
    `192.168.1.14` for Wazuh) — both of those specific hosts are currently
    unreachable (ping fails), consistent with "several of these services
    are offline." `tpot.gibbsgreatly.xyz` (`192.168.1.28`) does still
    respond to ping.
  - The ES REST API requires auth (401 without credentials) — didn't probe
    further, not needed to answer the storage/placement question and this
    document doesn't touch legacy credentials.
- **This means the `elastic-stack` Terraform module is drifted, not
  empty.** `terraform/lxc/stacks/elastic-stack/stack.yaml` declares
  "portainer_agent: true... No portainer_stacks — agent registration only,
  no compose stacks to deploy." The real container has a fully live,
  natively-installed ES/Kibana/Fleet stack that Terraform/Ansible has no
  knowledge of and doesn't manage. It works today only because nobody has
  re-run provisioning against it.
- **Confirmed not the target for the new work**, per the operator, and
  this finding doesn't change that — if anything it reinforces it: this
  host is unmanaged, undocumented-in-IaC, and nearly full. Standing up the
  new stack fresh (own manifest, own Ansible playbook, in the current
  platform's Docker Compose + Terraform + SDN pattern) rather than trying
  to adopt this one in place is the right call.
- **`management-stack` (`192.168.1.4`, vmid 101)** is a separate,
  still-relevant piece of this picture — it's alive, running Docker
  (nginx-proxy-manager, a legacy registry, registry-ui, trivy-scanner,
  portainer-agent), and is the reverse-proxy path that makes
  `elastic-api.gibbsgreatly.xyz` etc. resolve at all. It sits on general
  LAN (`192.168.1.0/24`), unsegmented, outside current VLAN/SDN zones —
  consistent with this being pre-SDN legacy infrastructure. Out of scope
  for this plan beyond noting it as the thing that will need its NPM proxy
  hosts removed when legacy `elastic-stack` is eventually decommissioned.

## Legacy decommission (separate phase, not a prerequisite)

Recommended, but explicitly **not required to unblock the new build** and
**not scheduled as part of the phases below**:

- Stop/remove `elasticsearch.service` / `kibana.service` /
  `elastic-agent.service` on `192.168.1.24`, reclaim 177G on `monitoring`.
- Remove the now-dead NPM proxy hosts on `management-stack`
  (`elastic-api`, `elastic-fleet`) once nothing depends on them.
- Decide whether `terraform/lxc/stacks/elastic-stack/` should be
  Terraform-destroyed and the vmid/IP freed, or left as a Portainer-agent
  shell.
- This is a **production mutation on a currently-running container** —
  needs the standard preflight/approval flow (CLAUDE.md "Approval Flow For
  Production Mutations") when the operator wants to schedule it, and
  should happen in its own session/branch, not bundled into the new
  stack's build.

## Target architecture

### Placement

| Field | Value | Rationale |
|---|---|---|
| Zone | `infra_seg` (VLAN 40, `192.168.40.0/24`) | Co-locates with Harbor (primary ingestion source, eliminates one cross-zone rule) and fits the existing "shared platform data service" tier (Harbor, apt-cacher, NetBox already here). Keeps `mgmt_seg` (Authentik/step-ca/Graylog control-plane) uncrowded. |
| Example vmid / IP | `40013` / `192.168.40.13` | Next free slot after harbor(`.10`)/apt-cacher(`.11`)/netbox(`.12`) — confirm against current allocations at implementation time, not hard-committed here. |
| `storage_profile` | `platform-zfs` (rootfs+docker → `infrastructure-containers`, same as every other stack) | Standard, small footprint (~16–20G rootfs, 20G docker) — no reason to deviate. |
| `extra_mount` | `durable-zfs` profile, e.g. `es-data` volume, start at **150G**, `mutation_policy: grow-only` | Mirrors `harbor-stack`'s `harbor-data` (120G on the same `durable-zfs`→`storage`-pool profile). 150G gives headroom well past the legacy container's full 177G without touching the cramped `rpool`. `storage` pool has 1.62TB free — resize later is cheap. |
| `depends_on` | `harbor-stack`, `apt-cacher-stack` | Standard image-pull dependency chain. |
| `deployment_tier` | `platform` | Matches Graylog/Harbor/NetBox, not `ai`. |

### Software

Single-node Elasticsearch + Kibana via Docker Compose (not a native install
— avoids repeating the legacy container's drift), pulled through Harbor
using the corrected pull-then-tag pattern
(`reference_harbor_bootstrap_circularity`), fronted by
`docker_socket_proxy` like every other stack.

- `elasticsearch:9.x` (or latest stable at implementation time) — single
  node, `discovery.type: single-node`.
- `kibana:9.x` — matched version, for index-management/dev-tools/pipeline
  debugging behind Traefik forward-auth. Not the primary consumption
  surface (see Visualization below).
- **Heap sizing**: reuse Graylog's exact formula
  (`deploy-graylog-stack.yml`) — `max(1, floor(container_total_mem_mb /
  1024 / 2))` GB, applied to both `ES_JAVA_OPTS` `-Xms`/`-Xmx`. Don't
  reuse a default ES heap setting
  (`reference_unified_memory_oom_sizing`). At a starting container memory
  budget of ~6–8G (Graylog's tier), that's 3–4G heap — reasonable for a
  single-node findings store at this data volume (low hundreds of MB/day
  once Harbor+GVM are the only two sources and `threat=Log` noise is
  dropped at ingest per README).
- Single-node ES security: built-in ES security (API keys) for
  service-to-service ingestion auth (Harbor/GVM sync scripts,
  Grafana datasource) — same auth model `security-analysis` already uses
  against the legacy cluster, so the ingestion-script side of this is a
  known pattern, not new ground.

### Auth & edge exposure

Kibana has no free-tier OIDC/SSO (Elastic gates SAML/OIDC login behind a
paid license) — same shape as NetBox, GVM's `gsad`, and Traefik's own
dashboard. Use the existing **`auth: mode: forwardAuth`** pattern
(Authentik outpost via Traefik), not `mode: oidc`:

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: elastic-edge
  stack: elastic-stack-v2   # working name; see Naming below
spec:
  routes:
    - name: kibana
      host: kibana.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_ELASTIC}:5601
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
```

The raw Elasticsearch REST API (9200) should **not** get a public Traefik
route — it's a service-to-service API (Harbor sync, GVM sync, Grafana
datasource), reached only from inside the SDN via the cross-zone rules
below, authenticated with ES API keys. This matches how `security-analysis`
already treats the legacy cluster's `EXTERNAL_ES_URL`/`EXTERNAL_ES_API_KEY`
pair, just without exposing it to the internet.

### Naming

Don't reuse `elastic-stack` as the new Terraform stack directory name —
that name is already claimed (and drifted) at vmid 112. Use a distinct
name, e.g. `elasticsearch-stack` or `es-stack`, so the new manifest can't
be confused with the legacy one in `terraform/lxc/stacks/`. Final name is
an implementation-time bikeshed, not a blocker.

### Network / SDN changes

All **additive-only** cross-zone allow rules — lightest validation tier in
CLAUDE.md's table (apply, then `provision.sh` against 1–2 adjacent
stacks, not a full teardown):

1. `mgmt_seg` (Grafana, `192.168.20.x`) → new zone `infra_seg`:9200 —
   Grafana's Elasticsearch datasource plugin querying the store.
2. `pentest_seg` (`192.168.70.x`, where the GVM sync job runs — see
   Ingestion below) → new zone `infra_seg`:9200.
3. `ai_seg` (`192.168.50.x`, where `findings-mcp` runs — see "Beyond
   ingest" below) → new zone `infra_seg`:9200. This is the one that
   actually matters most for the automation goal: it's what lets the
   local-LLM/MCP layer reach the store at all.

`harbor-stack` → same-zone traffic to the new host needs no new rule
(both `infra_seg`). Standard baseline rules (every stack ↔ `edge_seg`
Traefik, every stack ↔ `mgmt_seg` Authentik forward-auth) already exist
platform-wide and don't need re-adding. Note `framework.gibbsgreatly.xyz`
(`192.168.1.8`, bare-metal Ubuntu running the local LLM/Ollama since
`pve-framework` was retired) sits on general LAN, **outside every VLAN
zone** — it already reaches into `ai_seg`/`pentest_seg` today (PentAGI's
own model calls prove this path works, per
`docs/greenbone-stack/pentagi-integration.md`'s live end-to-end run
against `Qwen3-Coder-30B-A3B` served from Framework). No new rule needed
for Framework itself; it rides the existing LAN→`ai_seg` reachability
that PentAGI already depends on.

## Ingestion pattern

Reuse the shape proven in `security-analysis`'s `secpipe_core` +
per-source `assets/` layout, adapted to this repo's existing conventions
(systemd timer + oneshot service, same as `harbor_repull`) instead of a
standalone `.venv`-based CLI package:

```
terraform/lxc/ansible/roles/es_findings_ingest/
├── files/
│   ├── es_setup_assets.py       # idempotent PUT of templates/pipelines/transforms
│   ├── harbor_findings_sync.py  # Option A: scheduled pull, Harbor scan API -> ES
│   ├── gvm_findings_sync.py     # Option A: scheduled pull, gmp.get_results -> ES
│   └── assets/
│       ├── templates/harbor-findings-template.json
│       ├── templates/gvm-findings-template.json
│       ├── ingest_pipelines/harbor-findings-normalize.json
│       ├── ingest_pipelines/gvm-findings-normalize.json
│       └── transforms/ (rollups, once a real reporting need exists)
├── templates/es-findings-ingest.timer.j2
├── templates/es-findings-ingest.service.j2
└── tasks/main.yml
```

Concrete carry-overs from the analysis repos, not reinvented:

- **Idempotent asset apply** (`es_setup_assets.py`): GET-compare-PUT for
  index templates / ingest pipelines / transforms, dry-run by default,
  `--apply` to write — straight port of
  `security-analysis/src/secpipe_core/setup_assets.py`.
- **Deterministic `_id`** per document (`source::finding_id::artifact_or_target_key`)
  so re-runs are pure upserts, never duplicate — same idea as tpotce's
  `"<source_index>::<source_id>"`.
- **Cursor/state doc in ES itself** (`es-findings-sync-state` index, one
  doc per source), same shape as `secpipe_core/state.py` /
  `tpot_es_sync.py`'s `update_sync_state` — no separate state store needed.
- **`first_seen`/`last_seen` upsert semantics** per README's data model —
  this is what makes it a trend store, not an append-only log.
- **Severity/noise filtering at ingest**, not left to query time — the
  ingest pipeline drops `threat=Log` (GVM) the same way the T-Pot pipeline
  already reshapes/derives fields in Painless.

Deployment mechanics: plain systemd timer + oneshot `python3` service
(`harbor_repull` pattern), not a `.venv` package — this repo doesn't
currently ship Python venvs on LXC hosts for this kind of job, and staying
consistent avoids introducing a second convention.

- **`harbor_findings_sync.py`** runs on `harbor-stack` itself (same host
  `harbor_repull.timer` already runs on) — same host means it needs the
  cross-zone rule to reach the new ES stack's 9200, and can trigger right
  after `harbor-repull.timer` finishes (~04:30 UTC,
  `project_harbor_alerting_automation_plan` timing note). Bakes in the
  mirror-project-vs-original-project asymmetry
  (`mirror/*` for gcr/ghcr/quay/greenbone/lscr, direct project for
  dockerhub) as a hardcoded constant, same as `harbor_repull.py` already
  does — don't re-derive it.
- **`gvm_findings_sync.py`** runs inside `pentest_seg`, following the
  existing `gvm-bridge`/`setup_scan_program.py` pattern of talking to
  `gvmd` over its Unix socket from a container on the same Docker network
  — not a remote GMP connection. Triggered after the weekly full-vuln
  schedule's `lan` zone finishes (~05:00–06:00 Pacific/Auckland per
  `project_gvm_lan_scan_rollout`), or on its own daily timer once
  Phase 4's daily-discovery scheduling exists. Uses `get_results` (never
  `get_reports`), always `rows=-1`, drops `threat=Log`, reuses `ZONES`
  from `setup_scan_program.py` for `target.zone` and `REDTEAM_EXCLUDE` for
  `pentest_target` enrichment — all per `reference_gvm_scan_gotchas` and
  README §3.

Scope for first cut: **Harbor only**, add GVM once Harbor's pipeline is
proven live — README's own recommendation, still the right call. Both
already have de-risked document shapes in README so this isn't deferred
research, just deferred rollout.

## Beyond ingest: the actual goal is TVM automation, not a dashboard

Operator framing (2026-08-17): the end state looks like **Avalor or
Ivanti Neurons for the home lab** — pull findings from multiple sources,
normalize and de-duplicate, make the result available for analysis by
the **local LLM on Framework**, enrich via **CVE-MCP**, and eventually
**hand verified findings off to PentAGI** to actually attempt exploitation.
Dashboards (Grafana) are for humans; Kibana is for management (index/
pipeline debugging), not analysis. **The primary interface to this store
is automation, not a UI** — everything below is designed around that.

This reuses a design principle this repo has already proven twice, not a
new idea: **agents never get raw credentials to the thing they're
querying — a small purpose-built bridge service holds the real
complexity/credentials server-side, and the agent gets trivial JSON/HTTP
(or MCP) tool calls.** `cve-mcp-server` does this for NVD/EPSS/KEV/etc.;
`gvm-bridge` does it for GMP. The same shape applies here.

### New component: `findings-mcp`

A small service, same precedent as `gvm-bridge` — deployed in **`ai_seg`**
(co-located with `mcp-utility-stack`/`cve-mcp-server`, the zone PentAGI
and Framework already reach today), holding a scoped Elasticsearch API
key server-side. Exposes tools over MCP (consistent with everything else
in `ai_seg`, unlike `gvm-bridge`'s plain-JSON choice — this one's
consumer is an LLM tool-calling loop directly, not a Go client):

- `list_findings(filters...)` / `get_finding(id)` — query the store
  (Harbor + GVM indices, and later the correlated view below).
- `annotate_finding(id, severity_assessed, reason)` — writes back into
  the `severity_assessed`/`assessed_reason`/`assessed_by`/`assessed_at`
  fields README's data model already reserved for exactly this. This is
  the write path that turns "325 Critical findings" into something
  triaged — now actually wired to an LLM doing the triage, not just a
  human doing it manually in a Claude session like the openssl example
  that originally motivated this field.
- **No hard-coded "enrich" pipeline tool.** `pentagi-integration.md`
  already validated this exact pattern for GVM+CVE-MCP: give the agent
  `list_findings`/`get_finding` alongside the existing `triage_cve`/
  `search_cves` tools (already live on PentAGI's side; Framework's local
  LLM tooling would need the equivalent MCP client wiring) and let it
  compose the calls itself — read a finding, triage its CVE, write back
  an assessment — in one reasoning loop, the same way the real GVM→
  CVE-MCP chain was proven live rather than hand-coded as a fixed
  pipeline.
- Needs the `ai_seg`→`infra_seg`:9200 rule above. ES-side: a dedicated,
  narrowly-scoped API key (read on `harbor-findings-*`/`gvm-findings-*`/
  `unified-cve-exposure-*`, write limited to the `severity_assessed`
  family of fields) — same "dedicated non-admin credential, not the
  admin account" precedent `gvm-bridge` set for its own `gvmd` user.

### Cross-source correlation / de-duplication

Within a source, dedup is already solved (deterministic `_id`,
`first_seen`/`last_seen` upsert — see Ingestion pattern above). The new
piece is **cross-source correlation**: the same CVE can show up via
Harbor (image scan, container-shaped) and GVM (network scan, host-shaped)
independently, and nothing today says "these are the same underlying
exposure." Recommended shape: an ES **transform** (the same feature
`so-alerts-daily`/`tpot-rollup-*` already use for time-based rollups,
just pivoting on `cve` instead of a date histogram) building a
`unified-cve-exposure-*` index — one document per CVE, with an array of
contributing findings (source, artifact-or-target, severity_raw,
first/last_seen per contributor) and a single top-line
`severity_assessed`. This is the actual "single query answers current
exposure across every scanner" deliverable README §4 already named as
the biggest win, made concrete. Depends on Harbor+GVM ingestion both
being live (Phase 5 in the rollout below), so it's a later phase, not
blocking.

### PentAGI handoff — confirmed genuinely buildable, not yet built

Checked rather than assumed: `docs/pentagi-stack/test-harness-design.md`
already documents (from reading PentAGI's fork's resolver source
directly, not guessed) that PentAGI exposes a **real GraphQL API** for
flow lifecycle control — `createFlow(modelProvider, input, resourceIds)`,
`stopFlow`/`finishFlow`/`deleteFlow`, and status polling via
`tasks(flowId)`. That's exactly the mechanism a `trigger_pentagi_verification`
tool on `findings-mcp` would need: build a prompt from a specific
finding's data ("verify and assess exploitability of CVE-X on host Y"),
call `createFlow`, capture `flowId`, and (on a later poll) write the
outcome back onto the finding document. **This specific handoff has not
been built for either project** — `test-harness-design.md` calls its own
use of this API "proposed architecture" too — so this is real, scoped,
not-yet-started integration work, not a rename of something that already
exists. Treat it as a distinct, later, opt-in phase (a human should
almost certainly gate "actually let an agent try to exploit something,"
at least initially — not proposing unattended auto-exploitation as the
default).

## Human-facing surfaces (secondary)

**Grafana** (already live, already Authentik-OIDC'd) via its
Elasticsearch datasource plugin, for dashboards/alerting a human glances
at. **Kibana** gets deployed (bundled with ES anyway, cheap) and fronted
with forwardAuth, but per the operator's own framing its job is
**management** — index/pipeline/transform inspection and debugging —
not primary analysis. The primary analysis surface is the automation
layer above; both UIs are conveniences on top of it, not the thing being
built toward.

## Validation tiers for this work

CLAUDE.md's table assumes `pve-test-vm` as the validation ground before
`pve`; per the "Development environment" section above, **this project
develops directly against `pve`**, so the tier column below is adjusted
accordingly — same change classes, different (heavier, approval-gated)
execution target:

| Change | Tier |
|---|---|
| New `infra_seg` LXC + Docker Compose stack (ES/Kibana) | `scripts/provision.sh --stack <new-name>` against `pve`, via the standard production approval flow (`./with-secrets-prod`, preflight summary, chat "Proceed", `TASK_APPROVAL`) |
| Two additive cross-zone SDN rules | Apply against `pve` under the same approval flow, then `provision.sh` against 1–2 existing stacks in `mgmt_seg`/`pentest_seg`/`ai_seg` (already-live production stacks — read-only confirmation, not a mutation) to confirm no regression |
| `es_findings_ingest` Ansible role/timer additions to `harbor-stack` | `scripts/provision.sh --stack harbor-stack` against `pve`, same approval flow — this one touches an already-running production stack, so treat it with the same care as the Authentik/Traefik row in CLAUDE.md's table, not the lighter "new stack" case |
| GVM-side sync job touching `greenbone-stack`/`pentagi-stack` | Same — approval flow, targets already-live production stacks |
| `pve-test-vm` power-on for a specific disruptive test | Its own explicit, scoped approval — state which test, power on, run it, report, power back off. Not a standing state. |
| Legacy decommission (later, separate) | Production mutation — full preflight/approval flow, own session |

No full teardown cycle anywhere in this plan unless the operator asks for
one by name. Every row above still needs its own per-task chat approval
when the actual work happens — nothing here is pre-approved by this plan
existing.

## Phased rollout

1. **LXC + base stack**: new `terraform/lxc/stacks/<name>/` manifest
   (`stack.yaml`, `network-sdn-vars.yml` via the SDN module, `edge.yaml`),
   Ansible playbook standing up ES+Kibana via Docker Compose, heap sized
   per formula above (reconsidered downward given `pve`'s actual
   headroom — see "Development environment" above), `docker_socket_proxy`
   enabled. Deployed directly to **`pve`**, under the production approval
   flow — no `pve-test-vm` step in this project's normal path.
2. **SDN additive rules**: the two cross-zone allow rules above, applied
   to `pve` under the same flow.
3. **Asset + Harbor ingestion**: `es_setup_assets.py` + index
   template/pipeline for Harbor findings, `harbor_findings_sync.py` +
   timer on `harbor-stack`, dry-run first, then `--apply`/`--write`.
   Confirm a real end-to-end row shows up in ES matching README's Harbor
   document shape.
4. **Grafana datasource**: add ES datasource in Grafana, build a minimal
   "current exposure" dashboard as the smoke test for the visualization
   layer.
5. **GVM ingestion**: same shape, inside `pentest_seg`, once (3)+(4) are
   proven. Add the cross-source severity-scale mapping decision (CVSS v2
   vs v3, GVM `threat` bucket) explicitly rather than defaulting it.
6. **`stable`/`main` bookkeeping — decided 2026-08-17**: merge to
   `stable` once each stage validates; **do not merge `stable` → `main`
   yet** — operator not ready. Stay on `stable` until told otherwise;
   this is a live constraint, re-confirm before ever opening that PR
   rather than assuming enough time has passed. See `runbook.md` Stage 9
   for the exact mechanics. This is the MVP: a working, queryable, deduplicated-within-
   source store. Everything below is the TVM-automation layer built on
   top of it.
7. **Cross-source correlation**: the `unified-cve-exposure-*` transform,
   once both sources have real data flowing.
8. **`findings-mcp` in `ai_seg`**: the `ai_seg`→`infra_seg`:9200 rule,
   the service itself (`list_findings`/`get_finding`/`annotate_finding`),
   scoped ES API key. Validate by having the local LLM actually chain
   `list_findings`→`triage_cve`(existing CVE-MCP)→`annotate_finding` on
   a handful of real findings, same validation shape
   `pentagi-integration.md` used for its own live proof.
9. **(Opt-in, gated, later)** `trigger_pentagi_verification` on
   `findings-mcp`, using PentAGI's `createFlow` GraphQL API. Human-gated
   at least initially — this is the step that lets an agent attempt real
   exploitation, not read-only analysis.
10. **(Separate, later, own approval)** Legacy `elastic-stack` decommission.
    Not dependent on any of the above and not blocking any of it.

## Open decisions still left to the operator

- Exact vmid/IP for the new stack (example given above, not committed).
- Final stack directory name (`elasticsearch-stack` vs `es-stack` vs
  other).
- Retention policy for findings (README already flags this as open —
  longer than Harbor's 7-day artifact retention, exact number undecided).
- Whether Kibana ships in phase 1 or is deferred until genuinely needed
  for pipeline debugging (cheap either way; default here is "ship it,
  behind forwardAuth, from day one").
- Timing for the legacy decommission phase — not blocking, schedule
  whenever convenient.
- ~~How this project's `pve`-direct work reconciles with the `stable`/
  `main` branch model~~ — **decided 2026-08-17**: stay on `stable`, don't
  merge to `main` yet.
- ~~Final container memory allocation~~ — **resolved 2026-08-17**: started
  conservative at 3GB/1GB-heap as planned; live deploy then showed it was
  genuinely too tight (ES+Kibana+Docker+sidecars left the LXC at 24Mi
  free, Kibana couldn't reach healthy) — grew to 6GB/3GB-heap, matching
  `graylog-stack`'s own tier for a comparable JVM-backed service.
  Confirmed live with real headroom afterward (1.5Gi available). This is
  the "start conservative, observe, grow appropriately" approach playing
  out exactly as intended, not a planning miss.
- **What actually drives Framework's local LLM analysis loop** — a
  standing scheduled job ("triage anything new every morning"), an
  on-demand Claude/Open-WebUI session with `findings-mcp` wired in, or
  both. Not designed here; depends on how Framework's existing local-LLM
  tooling is invoked today, which this session didn't investigate.
- **How gated `trigger_pentagi_verification` should be** — a human
  clicking "verify this" per finding, a human approving a batch, or
  something looser. Explicitly not defaulting to unattended
  auto-exploitation; exact gate mechanism is undecided.
- Whether `findings-mcp`'s write scope (annotate only) is sufficient
  forever, or whether later phases need it to also create/update
  index-level assets (e.g., adjusting the correlation transform) —
  default assumption is annotate-only stays narrow indefinitely, revisit
  only if a real need appears.
