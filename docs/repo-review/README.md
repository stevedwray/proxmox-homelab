# Repo Review / Documentation Tidyup Campaign

Status: in progress. This directory is a documentation workspace per
[docs/workflow/documentation-workspaces.md](../workflow/documentation-workspaces.md) —
durable conclusions are tracked here as dated review docs; there is no
`artifacts/` yet because this campaign hasn't needed scratch space beyond
these reports.

## Goal

The operator's actual goal is **trust**: when working with an LLM on a new
feature or fix, the docs it reads should not be misleading. Context-size
reduction (fewer, shorter files) is a secondary benefit, not the primary one
— a large labeled-historical doc is low risk; a short canonical-looking doc
that's confidently wrong is high risk. See document #1 below for the
findings organized by that lens. No code has been changed as part of this
campaign; some tracked documentation has been deleted or archived where it
was pure execution residue (see below).

## Reading order

1. [2026-07-03-llm-trust-risk-findings.md](./2026-07-03-llm-trust-risk-findings.md) —
   **read this first.** Findings re-triaged by "likelihood of causing a wrong
   LLM-assisted action," not by file size. Includes confirmed-wrong claims in
   the most-trusted docs in the repo (`docs/design/architecture.md`,
   `docs/plan/README.md`), not just verbosity.
2. [2026-07-03-file-level-action-catalog.md](./2026-07-03-file-level-action-catalog.md) —
   file-by-file keep/summarize/archive verdicts for every remaining bloated
   directory; the context-size-focused companion to #1.
3. [2026-07-03-doc-catalog-and-tidyup-plan.md](./2026-07-03-doc-catalog-and-tidyup-plan.md) —
   first-pass repo-wide inventory and phased tidyup plan.
4. [2026-07-03-doc-subdirectory-status-report.md](./2026-07-03-doc-subdirectory-status-report.md) —
   directory-by-directory relevance/redundancy assessment.
5. [2026-07-03-cleanup-matrix.md](./2026-07-03-cleanup-matrix.md) —
   keep/summarize/archive matrix and record of what was already removed.
6. [2026-07-03-productionize-refactor-review.md](./2026-07-03-productionize-refactor-review.md) —
   focused review of the single largest cluster before cleanup.

If you only read one document, read #1. Documents #3-#6 remain useful for the
reasoning/history behind the campaign but are superseded in priority order by
#1 and #2.

## Status summary

- `docs/` tracked file count: 634 → 330 after the first cleanup wave.
- Already removed: `docs/prompts/`, `docs/sessions/`,
  `docs/productionize-refactor/evidence/` + `handoffs/`,
  `docs/netbox-stack/artifacts/`, `docs/teardown-test/artifacts/` + `prompts/`,
  `docs/provisioning-refactor/prompts/`, `docs/baseline-merge/`,
  `docs/platform-hardening/`.
- Entrypoints (`README.md`, `docs/getting-started.md`) have already been
  repaired to reflect current environment naming (`pve-test-vm`) and no longer
  link to moved/deleted design docs — confirmed current as of this pass.
- Next wave identified: ~90-100 more files across
  `docs/stack-lifecycle-refactor/` (concluded program, not "active but
  bloated" as first assessed), `docs/plan/tasks/` (already labeled historical
  but never moved to `tasks/done/`), `docs/provisioning-refactor/tasks/03-*`
  (one task spawned 10 derivative files), `docs/productionize-refactor/`
  (canary runbook trios, resolved by completion status),
  `docs/network-refactor/` (concluded, gate passed but never closed out), and
  `docs/storage-refactor/` (agent-scaffolding prompt files). See doc #2 for
  the full breakdown and priority order.
- **Fixed (2026-07-03):** all 8 trust-risk findings in doc #1 — the stale
  Loki/VictoriaLogs claims in `docs/design/architecture.md` (now ADR-07 covers
  the actual Graylog decision) and `docs/monitoring-stack/design.md`, the
  wrong "Active issues" table in `docs/plan/README.md`, the missing
  administrative-access section in `docs/design/network.md`, stale
  `baseline/teardown-validated` branch references in `docs/storage-refactor/`,
  stale incident status in the graylog/portainer troubleshooting docs, and the
  three `bootstrap-stages.md` broken links. See doc #1 for what was wrong and
  why, and the exact files touched.

## Closeout

When the tidyup work described in docs #1 and #2 is complete, fold all six
documents in this directory into one short retrospective note and remove the
rest, consistent with the workspace pattern this campaign itself recommends
applying repo-wide.
