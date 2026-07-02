# Consistency / Trust Risk Findings (LLM-Assisted Work)

Date: 2026-07-03

**Status: all 8 findings below were fixed on this branch on 2026-07-03.** This
doc is kept as the record of what was wrong and why — useful if similar drift
recurs — not as an open punch list. Files touched: `docs/design/architecture.md`
(added ADR-07, fixed FR-10), `docs/design/network.md` (added Administrative
Access section), `docs/monitoring-stack/design.md` (diagram, log-flow, tables,
remaining-work), `docs/plan/README.md` (active-issues table),
`docs/storage-refactor/README.md` + `plan.md` + `phase-0-audit-notes.md` +
`copilot-promotion-prompt.md` (branch references), `docs/troubleshooting/graylog-portainer-teardown-regression.md`
+ `teardown-graylog-portainer/README.md` (status), and the three
`bootstrap-stages.md` broken-link files.

## Why this doc exists

The earlier reviews in this directory
([doc-catalog-and-tidyup-plan.md](./2026-07-03-doc-catalog-and-tidyup-plan.md),
[cleanup-matrix.md](./2026-07-03-cleanup-matrix.md),
[file-level-action-catalog.md](./2026-07-03-file-level-action-catalog.md))
optimized mainly for *context size*: which docs are big, redundant, or
historical residue. That's useful, but it's not the sharpest lens for the
operator's actual goal: **when an LLM is asked to add a feature or fix
something, it should not be steered wrong by a doc that states something
confidently and incorrectly.**

Those are two different failure modes:

- A verbose historical doc costs tokens but is usually *labeled* as
  historical, so an LLM reading carefully won't be misled by it.
- A doc that looks canonical, reads as current, and is simply **wrong** is
  far more dangerous — it actively produces bad decisions, and there's no
  signal telling the reader (human or LLM) not to trust it.

This pass re-triages findings — old and new — by that second criterion:
likelihood of causing a wrong action, weighted by how likely the doc is to be
loaded during normal feature/fix work (its "trust tier").

## Trust tiers

- **Tier 1 — always-loaded canonical docs**: `README.md`, `CLAUDE.md`,
  `AGENTS.md`, `docs/design/architecture.md`, `docs/design/network.md`,
  `docs/plan/README.md`, `docs/workflow/*`, `docs/reference/*`. These are the
  docs an LLM (or a new session) reads first, by design, to build a mental
  model before touching anything. An error here propagates into every
  subsequent decision.
- **Tier 2 — topic-scoped docs**: stack-specific `README.md`/`design.md`/
  `current-state.md` files, read only when working in that area, but still
  presented as the current source of truth for that topic.
- **Tier 3 — labeled historical/plan docs**: anything self-flagged or
  directory-flagged as historical, superseded, or a point-in-time snapshot.
  Lower risk — the label itself is the safeguard.

## High-risk findings (Tier 1 — fix these first)

### 1. `docs/design/architecture.md` describes a logging stack that no longer exists

FR-10 states: *"Observability stack: VictoriaMetrics + Grafana + Loki"* and
ADR-03 ("Metrics Stack") reaffirms *"VictoriaMetrics + Grafana + Loki
(confirmed)"* with no mention of Graylog anywhere in the file.

Reality, cross-checked three ways:

- `docs/monitoring-stack/graylog-migration-plan.md` states Sprints G0-G5 are
  complete and the `stable` promotion gate has been met.
- Commit `dfcf0db4 chore(monitoring): remove victorialogs remnants and
  refresh docs` (2026-07-02) confirms VictoriaLogs (Loki's already-planned
  successor) was itself removed.
- `terraform/lxc/stacks/graylog-stack/` exists as a live, deployed stack.

So the actual logging lineage has been **Loki → VictoriaLogs → Graylog**, and
`architecture.md` — the single most authoritative, always-loaded doc in the
repo — is stuck on generation one. An LLM asked to add a log source, debug a
logging issue, or extend monitoring will reason from a completely wrong
premise.

**Fix**: update FR-10 and ADR-03 to describe the current Graylog-based
logging path (or add an ADR-07 documenting the Loki→VictoriaLogs→Graylog
history if that's useful context), and drop the stale Loki references.

### 2. `docs/plan/README.md` "Active issues" table is half wrong

The table lists 13 issues as active. Verified against `gh issue view` for
each:

| Issue | Table says | Actual state |
|---|---|---|
| #106 | active (Traefik, 04-03) | **CLOSED** |
| #125 | active (step-ca, 04-04) | **CLOSED** |
| #107 | active (Monitoring, 04-05) | **CLOSED** |
| #108 | active (Trivy CI, 05-01) | **CLOSED** |
| #109 | active (Syft SBOM, 05-02) | **CLOSED** |
| #110 | active (Cosign signing, 05-03) | **CLOSED** |
| #113-#119 | active (Phase 06) | OPEN — correct |

Nearly half the "active" list (6 of 13) is closed work. This is the
canonical plan index — an LLM asked "what's currently open" will misreport
finished work as still needing action, and could waste a turn trying to
"complete" something already done, or get confused about why the described
work already exists in the codebase.

**Fix**: regenerate this table from `gh issue list --state open`, or replace
the static table with a pointer to run that command live (tables like this
go stale by construction; a live-query instruction is more durable than a
snapshot).

### 3. `docs/design/network.md` is missing the actual final network design

`docs/network-refactor/session-8-summary.md` records "Final Gate Verdict: YES
(PASSED)" (2026-05-22) for a network refactor whose conclusion —
MikroTik as the sole L3 gateway, no ProxyJump / host-route priming needed —
was never merged into `docs/design/network.md` (zero mentions of ProxyJump
there). The refactor's own directory was never closed out either (see
[file-level-action-catalog.md](./2026-07-03-file-level-action-catalog.md)),
so this conclusion currently only exists in a directory most readers would
correctly guess is safe to ignore.

**Fix**: pull `docs/network-refactor/target-model.md`'s contract into
`docs/design/network.md` directly, then archive `docs/network-refactor/`.

## Medium-risk findings (Tier 2 — fix opportunistically)

### 4. `docs/monitoring-stack/design.md` contradicts its own sibling doc

Separately from the architecture.md problem above: `design.md` itself
correctly deprecates Promtail/Loki in favor of a syslog-based path — but its
diagram, "Log flow" section, "What Gets Monitored" table, and endpoint list
(lines ~118–194) all describe **VictoriaLogs** as the current live
destination. Its own "Remaining Work" table (lines 222-223) lists "Graylog
pilot — G4 dashboards" and "G5 VictoriaLogs deprecation" as pending/optional
next steps. But `graylog-migration-plan.md`, in the same directory, says
those sprints are done and VictoriaLogs is gone. Two docs in the same
3-file directory disagree about which generation of the logging stack is
current.

**Fix**: same underlying fix as finding #1, applied to this file's
diagram/tables/remaining-work section.

### 5. Even the code shows a third generation lingering

`terraform/lxc/stacks/monitoring-stack/stack.yaml` (not a doc — flagged only
because it corroborates the drift) still tags the stack `loki` and declares a
`loki-http` service on port 3100 — the oldest generation of the three. This
means the actual IaC, the design doc, and the migration-plan doc are each
describing a different generation of the same subsystem. Worth a look
independent of this doc review, since it affects what an LLM would infer is
actually running if it reads the stack manifest instead of (or in addition
to) the docs.

### 6. `docs/troubleshooting/graylog-portainer-teardown-regression.md` status may be stale

Status line says *"Root cause identified... Full teardown-cycle revalidation
on pve-test-vm is the remaining gate."* (last updated 2026-07-02). But
`dfcf0db4` (docs refresh) and the merged PR #387 ("complete cold-start
teardown provisioning") landed the same day, and no later commit updated this
file's status line. It's unclear whether the "remaining gate" has since
passed. An LLM reading this file at face value would treat a possibly-closed
incident as still open. Also see the near-duplicate
`docs/troubleshooting/teardown-graylog-portainer/README.md` noted in the
earlier catalog — consolidating these would also resolve the status-tracking
ambiguity by giving the incident one authoritative status line instead of two.

**Fix**: confirm current status and update (or close out) both files.

### 7. `docs/storage-refactor/` targets a retired branch, and this directory is active

Carried over from the earlier catalog, re-flagged here because it's Tier 2
*and active* (not historical): `README.md`, `plan.md`,
`phase-0-audit-notes.md`, and `copilot-promotion-prompt.md` all name
`baseline/teardown-validated` as the promotion target. Per `CLAUDE.md`,
current workflow is `work/* → stable → main`; `baseline/teardown-validated`
is a frozen historical marker. An LLM picking up storage-refactor work would
promote to the wrong branch if it trusted these docs literally.

### 8. `docs/design/bootstrap-stages.md` broken links (3 files)

Carried over: `docs/plan/phase-03d-secrets-hardening.md`,
`docs/plan/tasks/00c-bootstrap-01-stage1-temporary.md`, and
`docs/plan/tasks/00c-bootstrap-02-stage2-production.md` all link to a file
that was renamed to `docs/design/bootstrap.md`. Low severity (a dead link
just wastes a read attempt, it doesn't assert something false) but trivial to
fix — repoint, don't recreate.

## What this changes about priority

The [file-level-action-catalog.md](./2026-07-03-file-level-action-catalog.md)
priority order was organized around directory-level archiving (biggest
context-size wins first). For the "don't mislead the LLM" goal, the order
should instead be:

1. Fix finding #1 (`docs/design/architecture.md` FR-10/ADR-03) — highest
   trust tier, most confidently wrong.
2. Fix finding #2 (`docs/plan/README.md` active-issues table) — highest
   trust tier, easy to verify/regenerate.
3. Fix finding #4 (`docs/monitoring-stack/design.md`) while already in that
   file for #1's context.
4. Fix finding #3 (fold network-refactor's conclusion into
   `docs/design/network.md`).
5. Fix findings #6 and #7 (status staleness, wrong branch name) — both Tier 2
   but both actively wrong in a directory someone would trust.
6. Fix finding #8 (broken links) — cheap, do it alongside the above.
7. Everything in the earlier file-level-action-catalog (archiving,
   summarizing verbose-but-accurate docs) is lower priority under this lens —
   it's a cost problem, not a correctness problem.

None of these fixes require deleting content or restructuring directories —
they're small, targeted edits to specific sections of specific files. I have
not made any of them yet, per the standing instruction to only document in
`docs/repo-review/` — flagging here for a decision on whether to proceed.
