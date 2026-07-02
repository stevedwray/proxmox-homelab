# Repository Cleanup Matrix

Date: 2026-07-03

This is a follow-on to
[2026-07-03-doc-catalog-and-tidyup-plan.md](./2026-07-03-doc-catalog-and-tidyup-plan.md).

The goal here is to turn the earlier review into a practical `keep /
summarize / archive` matrix for the main documentation clusters contributing to
LLM context bloat.

## Current Status

Current working branch for the cleanup:

- `docs/repo-review`

Already completed on this branch:

- deleted `docs/prompts/`
- deleted `docs/sessions/`
- deleted `docs/productionize-refactor/evidence/`
- deleted `docs/productionize-refactor/handoffs/`
- deleted `docs/netbox-stack/artifacts/`
- deleted `docs/teardown-test/artifacts/`
- deleted `docs/provisioning-refactor/prompts/`
- deleted `docs/teardown-test/prompts/`

These removals establish the first repo-wide cleanup rule in practice:

- tracked `evidence/`, `handoffs/`, and `artifacts/` material should be treated
  as temporary unless there is a strong, explicit reason to keep it

## Working Meanings

- `keep`: retain in the default docs surface as current/canonical
- `summarize`: keep the topic, but replace bulky docs with a shorter current-state version
- `archive`: remove from the default docs surface; keep in git history or a clearly historical namespace

## Retention Rule

The cleanup review now has a stronger default rule:

- `evidence/`, `handoffs/`, and `artifacts/` are temporary working material,
  not long-term documentation
- they may exist briefly during an active effort
- once their durable conclusions are captured elsewhere, they should be deleted
  from tracked docs
- git history is the recovery path if the raw material is ever needed again

This rule applies repo-wide, not just to one refactor directory.

## Priority Matrix

| Area | Tracked files | Action | Why |
| --- | ---: | --- | --- |
| `README.md` | 1 | summarize | should be a thin trusted index; currently stale |
| `docs/getting-started.md` | 1 | summarize | onboarding is important, but it currently points at stale assumptions |
| `docs/workflow/` | 8 | keep | this should become the workflow authority |
| `docs/reference/` | 5 | keep | best candidate for stable operator reference |
| `docs/design/` | 10 | keep + summarize | durable architecture should stay, but archive references should be clearly separated |
| `docs/plan/` | 88 | summarize | active roadmap matters, but the area is too large and historically layered |
| `docs/provisioning-refactor/` | 57 | summarize | may still hold real source-of-truth material, but needs compression and pruning |
| `docs/productionize-refactor/` | 223 before cleanup | summarize + selective keep | core strategy docs may still be useful; evidence and handoffs are already removed |
| `docs/sessions/` | 43 before cleanup | completed archive | raw transcripts and timestamped reports were high-noise and are now removed |
| `docs/prompts/` | 28 before cleanup | completed archive | agent support material, now removed from tracked docs |
| `docs/teardown-test/` | 24 | summarize + archive | keep the current runbook, archive execution residue and historical packets |
| `docs/netbox-stack/` | 11 | summarize | still relevant, but the README/current-state material is too time-layered |
| `docs/monitoring-stack/` | 3 | summarize | very small count, but the docs are unusually large and verbose |

## Suggested Directory Outcomes

### Keep mostly as-is

- `docs/workflow/`
- `docs/reference/`

These are the best foundations for a canonical docs surface and should be made
more authoritative, not more sprawling.

### Keep, but compress hard

- `README.md`
- `docs/getting-started.md`
- `docs/design/`
- `docs/plan/`
- `docs/provisioning-refactor/`
- `docs/teardown-test/`
- `docs/netbox-stack/`
- `docs/monitoring-stack/`

The pattern for these areas should be:

1. short current-state summary
2. durable guidance only
3. links out to archived detail when needed

### Archive out of the default docs path

- `docs/sessions/` completed
- `docs/prompts/` completed
- tracked `evidence/`, `handoffs/`, and `artifacts/` directories completed where identified
- remaining historical material should be removed opportunistically when found in future passes

These are the clearest “context reduction” wins because they contribute a large
number of tracked files while offering comparatively low value as first-line
documentation.

## Estimated Cleanup Size

Completed first-pass archive/removal work:

| Area | Tracked files |
| --- | ---: |
| `docs/prompts/` | 28 |
| `docs/sessions/` | 43 |
| `docs/productionize-refactor/evidence/` | 149 |
| `docs/productionize-refactor/handoffs/` | 37 |
| `docs/netbox-stack/artifacts/` | 4 |
| `docs/teardown-test/artifacts/` | 6 |
| `docs/provisioning-refactor/prompts/` | 24 |
| `docs/teardown-test/prompts/` | 15 |
| Subtotal removed | 306 |

Primary summarize/rewrite candidates now:

| Area | Tracked files |
| --- | ---: |
| `docs/plan/` | 88 |
| `docs/provisioning-refactor/` | 57 |
| `docs/teardown-test/` | 24 |
| `docs/netbox-stack/` | 11 |
| `docs/monitoring-stack/` | 3 |
| `docs/design/` | 10 |
| `docs/workflow/` | 8 |
| `docs/reference/` | 5 |
| `README.md` + `docs/getting-started.md` | 2 |
| Subtotal | 253 |

Second-pass archive work now completed:

| Area | Tracked files | Result |
| --- | ---: | --- |
| `docs/provisioning-refactor/prompts/` | 24 | removed after rewriting task indexes to rely on task docs instead of prompt packs |
| `docs/teardown-test/prompts/` | 15 | removed after confirming no active docs needed them |
| Subtotal | 39 | completed archive |

Interpretation:

- the highest-noise doc classes have already been removed in this branch
- the next phase is less about deletion and more about trust, consolidation,
  and shortening
- another `250+` docs still sit in areas that should be reduced or reorganized,
  even if many individual files remain

## Recommended Cleanup Order

### Step 1: trust and navigation

- `README.md`
- `docs/getting-started.md`
- `docs/workflow/`
- `docs/reference/`

This makes the repo safer to browse before any big moves happen.

### Step 2: consolidate workflow truth

- trim duplicated branch/process guidance outside `docs/workflow/`
- especially review:
  - `docs/plan/README.md`
  - `docs/productionize-refactor/README.md`
  - any docs still pointing at retired branches or deleted artifact paths

Goal:

- one authoritative workflow path
- no stale branch-model prose in secondary docs

### Step 3: compress active but bloated areas

- `docs/productionize-refactor/`
- `docs/plan/`
- `docs/provisioning-refactor/`
- `docs/teardown-test/`
- `docs/netbox-stack/`
- `docs/monitoring-stack/`

Goal:

- preserve durable current-state guidance
- rewrite or shrink oversized living docs
- avoid carrying historical narrative inline

### Step 4: architecture cleanup

- `docs/design/`

Mainly to separate active design docs from archive-era references and fix any
remaining moved/broken links.

### Step 5: repo-wide stale reference pass

- old environment naming: `pve-test` vs `pve-test-vm`
- retired branch references
- moved or missing design docs
- links into deleted artifact directories

## Detailed Next Sequence

The next practical execution order should be:

1. Complete the entrypoint updates in `README.md` and `docs/getting-started.md`.
2. Finish consolidating workflow guidance into `docs/workflow/` and remove stale
   branch-model duplication elsewhere.
3. Remove or rewrite references to deleted `evidence/`, `handoffs/`, and
   `artifacts/` paths in active docs.
4. Reduce `docs/productionize-refactor/` to its durable core only.
5. Shorten `docs/plan/`, `docs/provisioning-refactor/`, and
   `docs/monitoring-stack/` around a current-state-first structure.
6. Complete the repo-wide stale-link and stale-environment-name pass.

## Decision Gates

Before each major cleanup wave:

1. Confirm whether the target area is canonical, active-but-bloated, or purely
   historical.
2. If it is canonical, rewrite rather than delete.
3. If it is active-but-bloated, summarize and trim.
4. If it is historical or artifact-only, delete and rely on git history.

This keeps the cleanup consistent and avoids turning a docs reduction effort
into accidental knowledge loss.

## Suggested Keep Surface After Cleanup

Ideal default docs surface after the next cleanup waves:

- `README.md`
- `docs/getting-started.md`
- `docs/workflow/*`
- `docs/reference/*`
- selected `docs/design/*`
- a slimmed `docs/plan/README.md`
- one current runbook each for teardown, NetBox, and monitoring if still needed

Everything else should either be:

- archived
- condensed into those canonical docs
- or left recoverable only through git history

## Bottom Line

The most effective first cut has already happened on this branch: the obvious
artifact-heavy material is gone.

The next phase should be deliberate and step-by-step:

1. fix entrypoint trust
2. consolidate workflow truth
3. archive artifact-style prompt material
4. compress the large living docs
5. finish with a stale-reference pass
