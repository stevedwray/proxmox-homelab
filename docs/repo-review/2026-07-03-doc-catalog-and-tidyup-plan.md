# Repository Review: Documentation Catalog And Tidyup Plan

Date: 2026-07-03

## Scope

This review catalogs the tracked repository contents with emphasis on
documentation sprawl, staleness, redundancy, and LLM context cost.

Constraints followed:

- ignored paths were not reviewed as primary inputs
- no code was changed
- only `docs/repo-review/` was written
- code was consulted only where needed to judge whether docs still appear relevant

## Method

- Read `.gitignore` to avoid ignored material
- Cataloged tracked files with `git ls-files`
- Measured documentation counts and byte sizes
- Sampled current entrypoint docs and major documentation hubs
- Reviewed recent git history for documentation-heavy areas
- Reviewed open GitHub issues and PRs for still-active workstreams

## High-Level Inventory

Tracked file counts by top-level area:

| Area | Tracked files |
| --- | ---: |
| `docs/` | 637 |
| `terraform/` | 338 |
| `scripts/` | 42 |
| `ansible/` | 28 |
| `.github/` | 11 |
| `router/` | 7 |
| `tests/` | 6 |

The repository is documentation-heavy. `docs/` alone is the single largest
top-level area by file count.

## Documentation Footprint

Tracked documentation footprint under `docs/`:

- 634 tracked docs/data files
- about 4.68 MB of tracked content

Largest documentation clusters by tracked size:

| Area | Files | Approx bytes | Notes |
| --- | ---: | ---: | --- |
| `docs/productionize-refactor` | 223 | 1,639,861 | largest single context source; heavy handoff/evidence history |
| `docs/plan` | 88 | 628,338 | active planning plus stale task/history overlap |
| `docs/sessions` | 43 | 546,267 | raw session logs and reports |
| `docs/provisioning-refactor` | 81 | 244,433 | active source-of-truth claim, but broad supporting set |
| `docs/prompts` | 28 | 177,382 | agent-oriented prompt inventory, not operator-first docs |
| `docs/teardown-test` | 45 | 155,401 | active harness docs plus historical reports |
| `docs/monitoring-stack` | 3 | 152,791 | unusually large for a single stack area |
| `docs/storage-refactor` | 14 | 148,274 | planning plus prompt artifacts |
| `docs/design` | 10 | 134,867 | important, but partly mixed with archive references |
| `docs/netbox-stack` | 11 | 133,759 | useful but very verbose and time-layered |

Filename-pattern counts also show the source of the noise:

| Pattern | Count |
| --- | ---: |
| `evidence` | 152 |
| `plan` | 127 |
| `prompt` | 73 |
| `session` | 57 |
| `handoff` | 44 |
| `runbook` | 17 |
| `artifact` | 16 |

This is the clearest signal that the repo’s default doc tree contains a large
amount of execution residue, not just durable guidance.

## Main Findings

### 1. The default docs tree mixes canonical guidance with historical execution residue

The repo currently stores active documentation, work plans, AI prompts, handoff
packets, evidence logs, and session transcripts side by side under `docs/`.

This is the biggest context problem for LLM use. A model browsing `docs/` cannot
easily distinguish:

- current operator guidance
- active implementation plans
- historical migration packets
- one-off session residue
- raw validation evidence

The heaviest examples are:

- `docs/productionize-refactor/`
- `docs/sessions/`
- `docs/prompts/`
- `docs/teardown-test/`
- tracked evidence under multiple refactor areas

Recommendation:

- define a small canonical docs surface for everyday use
- move historical execution material under an explicit archive namespace
- keep raw evidence either ignored by default or isolated far from canonical docs

### 2. Entrypoint docs are stale and sometimes point to missing files

Concrete examples:

- `README.md` still links to `docs/design/GreenField.md` and
  `docs/design/NetworkPlanning.md`, but those now live under
  `docs/design/archive/`
- `README.md` still describes the active build as `pve-test`, while current
  planning/workflow docs describe `pve-test-vm` as the active test target
- `docs/getting-started.md` also presents `pve-test` as the current host model
- `docs/design/architecture.md` and several `docs/plan/*` docs reference
  `docs/design/bootstrap-stages.md`, which no longer exists

Impact:

- new readers start from stale assumptions
- LLMs are pushed toward retired environment names and moved documents
- the highest-traffic docs become the least trustworthy

Recommendation:

- repair entrypoint docs first
- treat broken/moved links as priority cleanup
- ensure root onboarding documents match the current environment model

### 3. Workflow and branch guidance is duplicated across multiple sources

Branch and validation workflow appears in:

- `AGENTS.md`
- `docs/workflow/branch-model.md`
- `docs/plan/README.md`
- older refactor READMEs

There is drift between them. For example:

- `docs/workflow/branch-model.md` describes `stable` as the target model
- `docs/plan/README.md` still says `CLAUDE.md` is authoritative and still refers
  to `baseline/teardown-validated`
- `docs/productionize-refactor/README.md` still refers to
  `refactor/productionize` and `baseline/teardown-validated` as live workflow
  branches
- `docs/teardown-test/README.md` still says next work should branch from
  `baseline/teardown-validated`

Impact:

- operators and models can receive contradictory instructions
- old branch names remain sticky in context windows

Recommendation:

- pick one canonical workflow document
- convert other copies into short pointers
- remove branch-model prose from historical/refactor READMEs unless essential

### 4. Several doc areas are still active, but the surrounding history is too verbose

Some areas clearly still matter based on recent commits and/or open issues:

- `docs/workflow`
- `docs/monitoring-stack`
- `docs/plan`
- `docs/teardown-test`
- `docs/step-ca-implementation`

But even active areas contain too much accumulated history in the same reader path.

Examples:

- `docs/monitoring-stack/design.md` is very large for a stack design doc
- `docs/monitoring-stack/graylog-migration-plan.md` is also very large and likely
  mixes current state with journey/history
- `docs/netbox-stack/README.md` is extremely detailed, time-layered, and harder
  to treat as a stable source of truth
- `docs/plan/phase-04-core-shared-services.md` is large enough that it likely
  needs a concise summary plus detailed appendices

Recommendation:

- compress large “living docs” into a short current-state summary
- move historical narrative, superseded decisions, and experiment logs to archive

### 5. `docs/productionize-refactor` looks mostly historical relative to the current workflow

Signals:

- largest documentation cluster in the repo
- heavy concentration of handoffs and evidence
- branch model references are outdated
- recent open PRs are about reconciler and Harbor fixes, not this refactor track
- open issues are centered on current stack lifecycle, teardown harness, and app
  migration work, not the original productionize branch structure

This does not mean the material is useless. It does mean it should not remain in
the default “active docs” surface in its current form.

Recommendation:

- preserve as archive/reference
- extract only durable conclusions into current design/reference docs
- archive the rest as historical program records

### 6. `docs/sessions` is high-noise, low-signal for default browsing

`docs/sessions/` contains many raw command transcripts and execution reports.
These are useful as evidence, but poor default context:

- timestamp-heavy filenames
- repeated plan/apply/destroy iterations
- low semantic density for future readers
- high token cost

Recommendation:

- keep only curated session summaries if needed
- move raw transcripts to a clearly historical location
- prefer one summary doc per incident/sprint over many raw command captures

### 7. Prompt inventories likely belong outside the default operator docs path

`docs/prompts/` and prompt-heavy refactor directories are useful for agent
execution, but they are not the same thing as human/operator documentation.

For LLM browsing they create two problems:

- they add large amounts of procedural text that competes with actual source of truth
- they encourage models to treat historical prompt scaffolding as live policy

Recommendation:

- separate prompt assets from human docs
- keep them in a dedicated agent-facing namespace
- leave short references from current docs only where needed

## Directory Triage

Suggested first-pass classification:

| Area | Status | Suggested action |
| --- | --- | --- |
| `README.md` | stale entrypoint | rewrite as a thin, trusted index |
| `docs/getting-started.md` | stale entrypoint | align with current environment and tooling |
| `docs/design/` | important but mixed | keep current docs, move archive references behind a clear boundary |
| `docs/reference/` | good canonical target | strengthen and expand as stable reference layer |
| `docs/workflow/` | active and important | make this the single workflow source of truth |
| `docs/plan/` | active but bloated | keep high-level plan, archive completed and superseded planning detail |
| `docs/productionize-refactor/` | mostly historical | archive after extracting durable conclusions |
| `docs/provisioning-refactor/` | semi-canonical | keep only if still the real source of truth; otherwise collapse into reference/design |
| `docs/sessions/` | historical evidence | archive or keep summaries only |
| `docs/prompts/` | agent support | move out of main docs surface |
| `docs/teardown-test/` | active but heavy | split current runbook from historical rehearsal evidence |
| `docs/netbox-stack/` | active but verbose | compress into current-state, runbook, and archive |
| `docs/monitoring-stack/` | active but verbose | split current architecture from migration history |

## Candidate Canonical Docs Surface

For a leaner LLM-friendly repo, the default reading path should probably shrink
to something like:

- `README.md`
- `docs/getting-started.md`
- `docs/workflow/branch-model.md`
- `docs/workflow/environments.md`
- `docs/reference/*`
- `docs/design/architecture.md`
- `docs/design/network.md`
- `docs/design/bootstrap.md`
- `terraform/README.md`
- `terraform/lxc/README.md`

Everything else should either:

- be linked as task-specific deep reference
- live in a clearly marked archive/history area
- or be moved to an agent/evidence namespace

## Tidyup Plan

### Phase 1: Repair trust in entrypoints

1. Fix root `README.md` links and environment naming.
2. Align `docs/getting-started.md` with `pve-test-vm` and current secrets/workflow.
3. Remove or update references to deleted/moved docs like `bootstrap-stages.md`.

### Phase 2: Establish a canonical information hierarchy

1. Declare `docs/workflow/` as the workflow authority.
2. Declare `docs/reference/` as stable operator reference.
3. Keep `docs/design/` for durable architecture only.
4. Reduce `docs/plan/` to active roadmap and live tasks.

### Phase 3: Archive historical execution material

1. Move `docs/sessions/` under an explicit archive/history namespace.
2. Move `docs/productionize-refactor/` to archive after extracting durable conclusions.
3. Split `docs/teardown-test/` into current runbook vs historical evidence.
4. Move stack-specific migration/history narratives out of the default stack READMEs.

### Phase 4: Separate agent assets from human docs

1. Move `docs/prompts/` out of the main docs path.
2. Move prompt/handoff packets from refactor directories into an agent-only area.
3. Keep only small human-readable indexes that point to those assets.

### Phase 5: Compress oversized living docs

Priority candidates for summarization:

- `docs/monitoring-stack/design.md`
- `docs/monitoring-stack/graylog-migration-plan.md`
- `docs/netbox-stack/README.md`
- `docs/stack-lifecycle-refactor/handoff.md`
- `docs/storage-refactor/plan.md`
- `docs/plan/phase-04-core-shared-services.md`

Compression pattern:

- short “current state” summary at top
- concise durable decisions
- links to historical/archive detail

## Suggested Review Order

If this cleanup is done incrementally, review in this order:

1. `README.md`
2. `docs/getting-started.md`
3. `docs/workflow/*`
4. `docs/reference/*`
5. `docs/design/*`
6. `docs/plan/*`
7. `docs/teardown-test/*`
8. `docs/netbox-stack/*`
9. `docs/monitoring-stack/*`
10. `docs/productionize-refactor/*`
11. `docs/sessions/*`
12. `docs/prompts/*`

## GitHub Context

Open GitHub work suggests the live focus has moved toward:

- teardown/redeploy harness work
- stack lifecycle refactor work
- application migration work
- Portainer migration and related fixes

That reinforces the recommendation to demote older productionization-era
handoff/evidence material from the default docs surface.

Open PRs at review time:

- PR #374: Portainer SSO/reconciler fix
- PR #373: Harbor `external_url` scheme fix

Open issues at review time include:

- #381 teardown+redeploy harness
- #318 stack lifecycle refactor stage 2
- #113-#119 app migration and supply-chain follow-up

## Bottom Line

The main problem is not lack of documentation. It is that too much historical
execution material sits beside current guidance with weak boundaries.

The fastest path to a leaner, more LLM-friendly repo is:

1. fix the entrypoints
2. declare a small canonical docs surface
3. archive historical handoffs, prompts, transcripts, and evidence
4. compress the few living docs that are still valuable but too long
