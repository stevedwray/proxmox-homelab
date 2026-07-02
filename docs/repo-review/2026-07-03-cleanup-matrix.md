# Repository Cleanup Matrix

Date: 2026-07-03

This is a follow-on to
[2026-07-03-doc-catalog-and-tidyup-plan.md](./2026-07-03-doc-catalog-and-tidyup-plan.md).

The goal here is to turn the earlier review into a practical `keep /
summarize / archive` matrix for the main documentation clusters contributing to
LLM context bloat.

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
| `docs/provisioning-refactor/` | 81 | summarize | may still hold real source-of-truth material, but needs compression and pruning |
| `docs/productionize-refactor/` | 223 | archive | largest historical residue cluster; heavy handoffs/evidence and stale branch context |
| `docs/sessions/` | 43 | archive | raw transcripts and timestamped reports are high-noise |
| `docs/prompts/` | 28 | archive | useful for agents, not good default human/LLM docs surface |
| `docs/teardown-test/` | 45 | summarize + archive | keep the current runbook, archive execution residue and historical packets |
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

- `docs/productionize-refactor/`
- `docs/sessions/`
- `docs/prompts/`

These are the clearest “context reduction” wins because they contribute a large
number of tracked files while offering comparatively low value as first-line
documentation.

## Estimated Cleanup Size

Reasonable first-pass archive candidates:

| Area | Tracked files |
| --- | ---: |
| `docs/productionize-refactor/` | 223 |
| `docs/sessions/` | 43 |
| `docs/prompts/` | 28 |
| Subtotal | 294 |

Reasonable first-pass summarize candidates:

| Area | Tracked files |
| --- | ---: |
| `docs/plan/` | 88 |
| `docs/provisioning-refactor/` | 81 |
| `docs/teardown-test/` | 45 |
| `docs/netbox-stack/` | 11 |
| `docs/monitoring-stack/` | 3 |
| `docs/design/` | 10 |
| `docs/workflow/` | 8 |
| `docs/reference/` | 5 |
| `README.md` + `docs/getting-started.md` | 2 |
| Subtotal | 253 |

Interpretation:

- around `294` tracked docs are strong archive candidates immediately
- another `250+` docs sit in areas that should be reduced or reorganized, even
  if many individual files remain

## Recommended Cleanup Order

### Wave 1: trust and navigation

- `README.md`
- `docs/getting-started.md`
- `docs/workflow/`
- `docs/reference/`

This makes the repo safer to browse before any big moves happen.

### Wave 2: move obvious historical residue

- `docs/sessions/`
- `docs/prompts/`
- `docs/productionize-refactor/`

This gives the largest context reduction quickly.

### Wave 3: compress active but bloated areas

- `docs/plan/`
- `docs/provisioning-refactor/`
- `docs/teardown-test/`
- `docs/netbox-stack/`
- `docs/monitoring-stack/`

### Wave 4: architecture cleanup

- `docs/design/`

Mainly to separate active design docs from archive-era references and fix any
remaining moved/broken links.

## Suggested Keep Surface After Cleanup

Ideal default docs surface after tidyup:

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

The most effective first cut is to archive the three obvious historical/agent
clusters:

- `docs/productionize-refactor/`
- `docs/sessions/`
- `docs/prompts/`

That alone represents about `294` tracked files.

After that, the biggest quality improvement comes from compressing current but
verbose areas rather than deleting them outright.
