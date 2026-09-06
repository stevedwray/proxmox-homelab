# File-Level Action Catalog (Next Cleanup Wave)

Date: 2026-07-03

This is a follow-on to the three earlier reviews in this directory:

- [2026-07-03-doc-catalog-and-tidyup-plan.md](./2026-07-03-doc-catalog-and-tidyup-plan.md)
- [2026-07-03-doc-subdirectory-status-report.md](./2026-07-03-doc-subdirectory-status-report.md)
- [2026-07-03-cleanup-matrix.md](./2026-07-03-cleanup-matrix.md)
- [2026-07-03-productionize-refactor-review.md](./2026-07-03-productionize-refactor-review.md)

Those reviews judged directories as a whole. This pass goes one level deeper:
every file in the largest/bloatiest remaining clusters gets its own verdict
(`keep` / `summarize` / `archive`), based on reading file content, git log,
and cross-referencing GitHub issues. No files were changed to produce this
catalog — it is read-only research.

Current tracked `docs/` size at time of writing: **330 files**, down from 634
before the first cleanup wave (which removed `docs/prompts/`, `docs/sessions/`,
`docs/productionize-refactor/evidence/` + `handoffs/`, several `artifacts/`
directories, and archived `docs/baseline-merge/` + `docs/platform-hardening/`).

## Corrections to the prior directory-level pass

File-level reading changed the verdict on two directories the earlier
subdirectory status report called "active but bloated":

- **`docs/stack-lifecycle-refactor/`** — closer reading shows this program is
  **concluded**, not active. All substantive commits (Stages 1–9, closeouts)
  stopped 2026-05-17; the only 2026-07-03 commits were repo-wide branch-name
  refreshes, not new planning. `next-session-note.md` explicitly says the
  program's stages are "done enough — do not reopen" and redirects future work
  to Phase 06 / Portainer instead. GitHub issues #308, #318, #311 are still
  open and tagged for this workstream, but read as orphaned tracking issues
  that were never closed rather than evidence of live work — worth a look
  independent of this doc cleanup.
- **`docs/network-refactor/`** — fully historical. `session-8-summary.md`
  records "Final Gate Verdict: YES (PASSED)" on 2026-05-22, but the planned
  Session 9 (clean up and promote) never happened, so `README.md` and
  `current-state.md` still read as an open handoff. One real gap: the
  conclusion of this refactor (MikroTik as sole L3 gateway, no ProxyJump /
  host-route priming) was never folded into `docs/design/network.md`, which
  currently has zero mentions of ProxyJump — durable content stuck in a
  directory that's otherwise safe to archive.

## Correction on "dangling references"

Not every reference to a deleted path is stale. Two different patterns exist:

1. **Genuinely dead links** — content that was tracked and got deleted
   (`docs/prompts/`, `docs/sessions/`, `docs/productionize-refactor/evidence/`
   and `handoffs/`). References to these are real broken links.
2. **Valid forward-references to gitignored working directories** — e.g.
   `docs/teardown-test/artifacts/evidence/<stamp>/...` describes where a
   *future* harness run will write output. `docs/teardown-test/.gitignore`
   ignores `artifacts/` on purpose (this is the documented workspace pattern:
   durable docs tracked, transient material local under `artifacts/`). These
   are not broken and should not be "fixed."

### Genuinely broken links (worth fixing)

| File | Target | Issue |
|---|---|---|
| `docs/network-refactor/README.md` (4 links) | `docs/sessions/*.txt` | Directory deleted; links dead |
| `docs/network-refactor/session-6-summary.md` | `docs/sessions/` | Same |
| `docs/agent-design/testing-plan.md` (2 refs) | `docs/sessions/evidence/...` | Same |
| `docs/productionize-refactor/16-pve-infra-teardown-advisory-summary.md` | `handoffs/15-...-handback.md` | Directory deleted |
| `docs/productionize-refactor/17-pve-infra-teardown-review-summary.md` (3 links) | `evidence/pve-infra-teardown-plan-.../...` | Directory deleted |
| `docs/productionize-refactor/pve-infra-teardown-inventory.md` | `evidence/step-ca-canary-.../02-pvesh-node-pve.json` | Directory deleted |
| `docs/productionize-refactor/runbooks/EXECUTION-CHECKLIST.md` | `handoffs/13-ci-runner-canary.md`, `evidence/` | Directory deleted; file is self-described legacy anyway (see below) |
| `docs/stack-lifecycle-refactor/plan.md`, `current-state.md` (~54 refs combined) | `docs/sessions/evidence/slr-*/...` | Directory deleted; moot if this directory is archived per above |
| `.github/copilot-prompts/diagnose-proxmox-401.md`, `fix-proxmox-401.md` | `docs/netbox-stack/artifacts/proxmox-401-*.md` | `artifacts/` here is a legitimate ignored output path (same pattern as teardown-test) — **not actually broken**, listed for completeness only |

Everything else matching the earlier grep (mentions of `docs/teardown-test/artifacts/`,
`docs/netbox-stack/artifacts/` as a *pattern*, not a specific dead file) is fine as-is.

### `docs/design/bootstrap-stages.md` broken link (3 files)

`docs/design/bootstrap.md` (H1: "Bootstrap Stages") is verifiably the renamed
replacement for the old `docs/design/bootstrap-stages.md`. Repoint, don't
recreate:

- `docs/plan/phase-03d-secrets-hardening.md:71`
- `docs/plan/tasks/00c-bootstrap-01-stage1-temporary.md:69,127`
- `docs/plan/tasks/00c-bootstrap-02-stage2-production.md:66,134`

## New findings beyond the original grep

- **`docs/monitoring-stack/design.md` is stale, not just long.** Despite a
  recent commit titled "remove victorialogs remnants and refresh docs"
  (`dfcf0db4`), the architecture diagram, "Log flow" prose, "What Gets
  Monitored" table, and "Remaining Work" table (lines ~118–178, 222–223) still
  describe VictoriaLogs as the active log path. `graylog-migration-plan.md`
  confirms VictoriaLogs was fully removed (Sprint G5, complete). This is a
  correctness bug in a canonical doc, not just a trim candidate.
- **`docs/storage-refactor/` still points at the retired branch model.**
  `README.md`, `plan.md`, `phase-0-audit-notes.md`, and
  `copilot-promotion-prompt.md` all target `baseline/teardown-validated` as
  the promotion branch. Per `CLAUDE.md` that branch is now a frozen historical
  marker; current workflow is `work/* → stable → main`. Unlike similar
  references in directories being archived, this one matters because
  storage-refactor is **active, incomplete** work (README's own "Current next
  target" section says a full teardown/deploy rehearsal is still pending).
- **Root-level `next-session.md` is stale clutter.** It's a handoff note for
  branch `work/storage-refactor-rewrite-01`, which merged 2026-05-28 — over a
  month before this review. It predates the `docs/<workspace>/artifacts/`
  workspace pattern this repo has since adopted. Candidate for deletion.
- **Duplicate troubleshooting docs for the same incident.**
  `docs/troubleshooting/graylog-portainer-teardown-regression.md` (199 lines,
  RCA-style) and `docs/troubleshooting/teardown-graylog-portainer/README.md`
  (448 lines, sprint-plan-style, oddly nested in its own single-file
  subdirectory) both cover the graylog/Portainer teardown breakage first
  observed 2026-07-01. Recent commits (`0754e762`, `24ddfc59`, PR #387 merged
  2026-07-02 "complete cold-start teardown provisioning") suggest this is now
  resolved. Recommend folding the durable RCA into one doc (or into
  `docs/teardown-test/lessons-learned.md`, which exists for exactly this) and
  archiving the rest.
- **`docs/repo-review/` itself has internal redundancy.** The doc-catalog and
  cleanup-matrix files cover nearly the same directory list (cleanup-matrix is
  explicitly a follow-on). Consistent with this directory's own stated plan
  ("archive or summarize once the campaign closes"), these should be
  consolidated into one doc once the cleanup work is done, not before.

## Directory-by-directory file tables

### `docs/plan/` (88 files: 88 total, 64 under `tasks/`, 18 of those in `tasks/done/`)

Top level:

| File | Verdict | Reason |
|---|---|---|
| `README.md` | keep | Canonical index, accurate |
| `current-state.md` | archive | Describes retired `baseline/teardown-validated` model; sprint concluded |
| `development-status.md` | archive | Self-banner: "historical snapshot — pre-SDN-refactor era" |
| `sprint-plan.md` | archive | Self-banner: "historical sprint snapshot" |
| `PHASE-DOCUMENT-REVIEW.md` | archive | Self-flagged historical meta-review; its recommendations are already implemented elsewhere |
| `phase-00a/00b/00c/01/03b/03c/03d/04/04b-*.md` | keep | Match README's active phase table |
| `phase-02-memory-upgrade.md` | keep (small) | Self-flagged historical but tiny (34 lines); fine as-is |
| `phase-03-code-quality.md`, `phase-05-supply-chain.md`, `phase-06-app-stacks.md`, `phase-07-runtime-security.md` | keep | Track real open issues (#113-#119 etc.) |
| `phase-04c-stack-owned-ingress-auth-dns.md` | archive | Self-flagged "legacy context — see docs/provisioning-refactor/" |
| `pve-migration-inventory.md` | keep | Recent (2026-06-18), in-progress |
| `boundary-strengthening.md` + `boundary-strengthening-ambiguities.md` | summarize | Companion pair with overlapping "current state" sections; merge to one doc |
| `authentik-sso-rollout-plan.md` | archive | References retired branch + closed issue #166; Wave 1 already done elsewhere |
| `tasks/phase-04-deployment-guide.md` | archive | Self-flagged historical; duplicates `phase-04-core-shared-services.md` |

`docs/plan/tasks/` (46 non-`done/` files): ~38 already carry a "Historical task
packet" banner from an earlier same-day cleanup pass, but were never actually
moved into `tasks/done/` — contradicting the directory's own stated convention
in `README.md`. **Process fix, not content fix**: move the already-labeled
files into `tasks/done/` (or delete if `done/` already has an equivalent —
near-duplicate pairs exist under different filenames, e.g.
`tasks/00b-pve-test-02-update-env-isolation.md` vs
`done/00b-pve-test-04-update-env-isolation.md`; `tasks/01-ci-runner-01-deploy-ci-runner.md`
vs `done/01-ci-runner-01-deploy-lxc.md`). The 7 `06-app-stacks-*` files are the
exception — issues #113–#118 are still open, so these need a refresh (drop
stale branch references) rather than archiving.

`docs/plan/tasks/done/` (18 files): keep as-is — this is the correct location
per the repo's own convention.

### `docs/stack-lifecycle-refactor/` (24 files)

Verdict: **archive nearly all of it** — see correction above. Individually:
`README.md`, `plan.md`, `current-state.md` (788 lines, largest file here),
`execution-plan.md`, `decisions.md`, `autonomous-execution-workflow.md`,
`handoff-spec.md`, `contract-audit.md`, `drift-policy.md`, `inventory-model.md`,
`special-cases.md`, `validation.md`, `session-01-sync.md`,
`stage-03-exemplar-scope.md`, `stage-04-exemplar-scaffolding.md`,
`next-session-note.md`, and all 8 `templates/*.yaml` files → archive (concluded
program; `.git/ai/` state it drives hasn't moved since 2026-05-15).

### `docs/provisioning-refactor/` (57 files) and `docs/teardown-test/` (25 files)

These two remain the "hard-validation path" per the earlier review — mostly
keep, with one clear collapse candidate:

| File(s) | Verdict | Reason |
|---|---|---|
| `README.md`, `decisions.md`, `findings-addressed.md`, `edge-manifest-v1alpha1.md`, `task-sequence.md`, `runbook.md`, `fixtures/*` | keep | Current, accurate, `fixtures/` is load-bearing for tests |
| `tasks/00-02,04-14,17a,21` (16 files) | keep | Compact spec docs, still the reference pattern |
| `tasks/15-20` (6 migrate-* files) | summarize | Near-identical 7-step template × 6, all confirmed done (edge.yaml exists for all target stacks) — collapse to one pattern doc + completed-migrations table |
| `tasks/03-cutover-semantics.md` | keep | The actual compact task spec |
| `tasks/03-cutover-semantics-SUMMARY.md`, `03-CUTOVER-INDEX.md`, `03-CUTOVER-CONTRACT.md`, `03-CUTOVER-STATE-TRANSITIONS.md`, `03-CUTOVER-QUICK-REFERENCE.md`, `03-MANIFEST-FORMAT-REFERENCE.md`, `03-CUTOVER-VALIDATION-COMMANDS.md`, `03-COMPLETE-SUMMARY.md`, `03-DOCUMENTATION-CHECKLIST.md`, `03-DELIVERABLES.md`, `README-TASK-03.md` (10 files, ~3,773 lines) | archive | One task ("define cutover semantics") spawned 10 derivative index/summary/reference/checklist files restating the same ~46-line rule already in `decisions.md` Decision 10 and `tasks/03-cutover-semantics.md`. `README-TASK-03.md` in particular reads as an AI "delivery summary" of the doc-generation exercise itself. |
| `docs/teardown-test/README.md`, `validation-model.md`, `decisions.md`, `variables.md`, `inventory.md`, `harness-roadmap.md`, `lessons-learned.md`, `task-sequence.md`, `repeatable-test.md`, `tasks/00-11` | keep | Current, accurate, harness-aligned |
| `backup-plan.md` | summarize | Same per-stack backup/restore pattern repeated 9× — compress to one template + parameter table |
| `operations-plan.md`, `runbook.md` | summarize | Overlap each other and `repeatable-test.md`; `runbook.md` already defers to the harness ("prefer the harness") — trim to gate/stop-condition reference once harness is the default path |

### `docs/productionize-refactor/` (37 root/tasks files + 12 runbooks = 49 files)

Historical reference overall (confirmed), with one live exception
(ci-runner-01, the next pending canary). The repeating "trio" pattern — a
root-level execution packet + `runbooks/NN-*.md` + `runbooks/NN-*-checklist.md`
per canary stack — resolves cleanly by canary status:

| Canary stack | Status | Verdict for its trio |
|---|---|---|
| apt-cacher | completed | archive (`06-canary-execution-2026-05-22.md`, `06-COMPLETION-SUMMARY.md` → summarize into readiness doc, `runbooks/06-pve-canary-apt-cacher.md`) |
| monitoring | completed, closure doc exists | keep `09-monitoring-canary-closure.md`; archive `09-monitoring-canary-execution-packet.md` + `runbooks/09-*` pair |
| netbox | completed | archive `10-netbox-canary-execution-packet.md` + `runbooks/10-*` pair |
| portainer | completed, closure doc exists | keep `11-portainer-canary-closure.md` |
| dns | **status unclear** — not in the completed list in `pve-production-readiness.md` | summarize/confirm — keep `07-dns-canary-execution-packet.md` + `runbooks/07-*` pair until status is confirmed |
| step-ca | **status unclear**, same issue | summarize/confirm — keep `08-step-ca-canary-execution-packet.md` + `runbooks/08-*` pair until status is confirmed |
| ci-runner-01 | **not yet executed — live** | keep `13-ci-runner-canary-execution-packet.md` + `runbooks/11-*` pair (this is the actual next step) |

Other files: `README.md`, `pve-production-readiness.md`,
`pve-infra-teardown-inventory.md`, `tasks/README.md`, `tasks/06-canary-validation-gate.md`,
`18-pve-infra-teardown-execution-packet.md` → keep (durable or still-live).
`tasks/01-05` (credential-controls, environment-model, storage-manifest,
network-intent, target-decoupling) → archive (already implemented).
`tasks/07-incremental-migration-plan.md` → summarize. `14-pve-parity-pass-01.md`
→ archive (one-off data capture). `15/16/17` (teardown planner/advisory/review
chain) → summarize. `runbooks/EXECUTION-CHECKLIST.md` → archive (self-described
legacy, dead links, superseded by stack-specific runbooks).

### `docs/network-refactor/` (12 files) — archive, with two salvage items

Archive: `README.md`, `current-state.md`, `checkpoint.md`, `migration-mechanics.md`,
`validation-gate.md`, `session-2-summary.md`, `session-6-summary.md`,
`session-7-summary.md`.

Summarize/salvage: `plan.md`, `target-model.md` (fold its MikroTik-as-L3-gateway
contract into `docs/design/network.md`, which currently omits it entirely),
`implementation-inventory.md`, `session-8-summary.md` (the actual closure
record — "Final Gate Verdict: YES (PASSED)" — worth one short retrospective
paragraph before archiving the rest).

### `docs/storage-refactor/` (14 files) — active, keep most, drop the scaffolding

Keep: `README.md`, `classifier-design.md`, `capability-matrix.md`,
`docker-mount-resize-tests.md`, `extra-mount-attach-tests.md`, `fixtures/*`.

Summarize: `plan.md` (838 lines — early-phase sections are now historical
since those phases are done).

Archive: `phase-0-audit-notes.md` (self-declared "not the authoritative
summary... no longer the canonical next-step document"), and all 5
`copilot-*-prompt.md` files (`copilot-init-prompt.md`, `copilot-validation-prompt.md`,
`copilot-gate-prompt.md`, `copilot-promotion-prompt.md`, `copilot-followup-prompt.md`)
— confirmed pure agent-scaffolding, same category as the already-deleted
`docs/prompts/`, no unique durable content.

**Priority fix** (this directory is active, so the stale content matters more
than in archived directories): update `README.md`, `plan.md`,
`phase-0-audit-notes.md` to reference `stable`/`main` instead of
`baseline/teardown-validated`.

### `docs/netbox-stack/` (7 files)

| File | Verdict | Reason |
|---|---|---|
| `README.md` (1605 lines) | summarize | Mixes a Step 1–9 plan with dated "Implementation Notes/Findings" narrative per step, plus a full 12-session Copilot roadmap (~270 lines) that's fully superseded — `current-state.md` references session numbering in the 50s+ |
| `current-state.md` | keep | The actually-current resume point |
| `populate-ownership-gap-report.md` (408 lines) | archive | Two closed point-in-time audit snapshots; one recommendation already confirmed implemented in code |
| `ownership.md`, `ownership-field-rules.md`, `portainer-socket-proxy-canary.md`, `docker-runtime-host-matrix.md` | keep | Stable policy/reference docs |

### `docs/monitoring-stack/` (3 files)

| File | Verdict | Reason |
|---|---|---|
| `design.md` (1122 lines) | summarize + fix stale content | See "New findings" above — VictoriaLogs still shown as active in several places despite being removed |
| `graylog-migration-plan.md` (1445 lines) | summarize | Sprints G0–G5 all complete; compress ~900 lines of sprint journal to a summary table, keep only the pve-promotion-readiness tail (~100 lines) in full |
| `node-exporter-tls.md` | keep | Focused, single-topic |

### `docs/design/`, `docs/reference/`, `docs/workflow/` — the strongest canonical core, mostly keep

- `docs/design/`: all 5 main-dir files keep; `archive/` split is working (no
  duplication found); no broken links found *from* these docs to others.
- `docs/reference/`: all 5 files keep as-is.
- `docs/workflow/`: all 8 files keep, except `provisioning-harness.md`'s
  "Target State" section — the features it describes (`--target-env`, smoke
  tests, parallel layers) are already shipped in `scripts/provision.sh`;
  reframe as "Current State."

### Smaller directories (spot-checked, one line each)

| Directory/file | Verdict | Reason |
|---|---|---|
| `docs/portainer-stack/*` (3 files) | keep | Clean, current, matches active issues #379-#381 |
| `docs/docker-refactor/current-state.md` | keep | Tight current-state doc |
| `docs/docker-refactor/socket-proxy-planning.md` (491 lines) | summarize | 8-session Copilot roadmap, likely mostly completed per current-state.md |
| `docs/harbor-stack/README.md` (730 lines) | summarize | Same plan+journal mixing pattern as netbox/graylog, smaller scale |
| `docs/step-ca-implementation/*` (8 files) | keep | None oversized, single-topic, no internal redundancy |
| `docs/threat-model/*.yaml` (2 files) | keep | Legitimate size for a full flow inventory, not narrative sprawl |
| `docs/agent-design/*` (3 files) | keep (historical reference) | Single "preserve baseline" commit; low future relevance but not urgent to remove |
| `docs/application-migration/*` (6 files) | keep | Matches open issues #113-#118 |
| `docs/code-cleanup/*` (3 files) | keep | Bounded, recently closed out cleanly |
| `docs/troubleshooting/*` (8 files) | keep, except the graylog/portainer pair — consolidate (see "New findings" above) |

## Rough scale of this next wave

Counting only clear `archive` verdicts above (excluding `summarize`, which
needs editing rather than removal): roughly **90-100 more files** are
candidates for archiving in the next wave, concentrated in
`docs/stack-lifecycle-refactor/` (~23), `docs/plan/tasks/` (~38, mostly a
move-not-delete since content is already labeled historical),
`docs/provisioning-refactor/tasks/03-*` (10), `docs/productionize-refactor/`
(~14), `docs/network-refactor/` (8), and `docs/storage-refactor/` (6).

## Suggested next-action order

1. **Quick, low-risk fixes** (small diffs, no judgment calls):
   - Repoint the 3 files' `bootstrap-stages.md` links to `docs/design/bootstrap.md`.
   - Fix the genuinely broken markdown links table above.
   - Delete root `next-session.md`.
   - Move the ~38 already-labeled-historical `docs/plan/tasks/*.md` files into `tasks/done/` (or delete duplicates where `done/` already has an equivalent).
2. **Correctness fix**: update `docs/monitoring-stack/design.md` to stop describing VictoriaLogs as active.
3. **Correctness fix**: update `docs/storage-refactor/README.md`, `plan.md`, `phase-0-audit-notes.md` to reference `stable`/`main` instead of `baseline/teardown-validated` (active directory, stale branch model matters more here than in archived directories).
4. **Archive the concluded programs**: `docs/stack-lifecycle-refactor/` (nearly whole directory) and `docs/network-refactor/` (after extracting `target-model.md`'s contract into `docs/design/network.md`).
5. **Collapse the `tasks/03-*` cluster** in `docs/provisioning-refactor/` down to `tasks/03-cutover-semantics.md`.
6. **Resolve the productionize-refactor canary trios** by status (archive completed, keep ci-runner-01 live, confirm dns/step-ca status before deciding).
7. **Summarize the oversized living docs**: `docs/netbox-stack/README.md`, `docs/monitoring-stack/graylog-migration-plan.md`, `docs/harbor-stack/README.md`, `docs/docker-refactor/socket-proxy-planning.md`, `docs/plan/boundary-strengthening*.md`.
8. **Consolidate the troubleshooting duplicate pair** for the graylog/Portainer teardown incident.
9. At campaign close: fold this file, the cleanup-matrix, and the doc-catalog-and-tidyup-plan into one short retrospective, per this directory's own stated workspace pattern.
