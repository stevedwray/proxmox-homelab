# Handoff

## Current State

- The document tree has been created.
- Core working assumptions have been captured.
- No code or workflow changes have been implemented yet under this refactor.

## Current Phase

- Stage 1: Contract schema draft (IN PROGRESS → COMPLETE)

## Established Working Assumptions

- Terraform owns day-1 infrastructure and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- Shared inventory is an evolution of `stack.yaml`.
- Generated artifacts are derived only.
- Terraform may offer an approved post-change day-2 reconcile path.

## Suggested Next Step

- Current Phase: Stage 1 complete / Stage 2 pending

- What was completed:
  - Contract surface audit (contract-audit.md)
  - First-pass shared contract schema draft (docs/stack-lifecycle-refactor/contract-schema.md)

- Evidence:
  - docs/stack-lifecycle-refactor/contract-schema.md
  - docs/stack-lifecycle-refactor/field-classification.csv

- Suggested Next Step: start Stage 2 on `task/slr-02-workflow-and-validation`
  - Goals for Stage 2: operator workflows, post-Terraform day-2 reconcile path, drift handling expectations, mandatory validation gates per change class

- Open questions to carry forward: see the numbered list in `contract-schema.md` section 7

## Open Questions To Carry Forward

- exact shape of the shared stack contract
- exact classification of managed vs observed vs adoptable paths
- exact validation gates and thresholds

## Session Closeout Checklist

- update [decisions.md](./decisions.md) if a decision is made
- update [plan.md](./plan.md) if phase or scope changes
- update this file with:
  - what changed
  - what was validated
  - what remains next
