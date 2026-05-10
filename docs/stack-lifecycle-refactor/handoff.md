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
