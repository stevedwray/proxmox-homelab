# Handoff

## Current State

- The document tree has been created.
- Core working assumptions have been captured.
- No code or workflow changes have been implemented yet under this refactor.

## Current Phase

- Phase 0: Define the Target Model

## Established Working Assumptions

- Terraform owns day-1 infrastructure and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- Shared inventory is an evolution of `stack.yaml`.
- Generated artifacts are derived only.
- Terraform may offer an approved post-change day-2 reconcile path.

## Suggested Next Step

Start Stage 1 on a short-lived branch from `refactor/stack-lifecycle`:

- `task/slr-01-shared-contract-draft`

Primary objective:

- audit the current implemented contract and define the first draft of the shared `stack.yaml` contract

Initial focus:

- audit:
  - `terraform/lxc/PLATFORM_CONTRACT.md`
  - relevant per-stack `STACK_CONTRACT.md` files
- identify current contract coverage, gaps, and conflicts
- common fields
- Terraform-derived fields
- Ansible-derived fields
- special-case extension sections
- validation metadata

Do not broaden into implementation changes yet unless required to clarify the contract.

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

## Stage 3 Outcomes

- Stage: 3 — Exemplar selection and scoped documentation.
- Session: `slr-03-main-work-01` scoped to branch `task/slr-03-exemplar-scope`.
- Outcome: created `docs/stack-lifecycle-refactor/stage-03-exemplar-scope.md` selecting `apt-cacher-stack` and `harbor-stack` as the exemplar pair; `netbox-stack` recorded as deferred.
- Next: Stage 4 will implement validation artifacts for the selected exemplars based on the expected validation evidence captured in the Stage 3 document.

## Stage 4 Kickoff

- Stage: 4 — Exemplar scaffolding bootstrap.
- Session: slr-04-bootstrap-01 on branch task/slr-04-exemplar-scaffolding.
- Outcome target: bounded Stage 4 scope and implementation checklist for apt-cacher-stack and harbor-stack, with no infrastructure command execution.
- Next: Stage 4 main-work will implement the scoped scaffolding changes and capture code-level evidence for Stage 5 validation.
