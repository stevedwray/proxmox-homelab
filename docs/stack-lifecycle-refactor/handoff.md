# Handoff

## Current State

- The refactor document tree remains the planning source for the program.
- The old architect/executor bidirectional handoff loop has been retired for this refactor.
- The autonomous execution workflow skeleton is now in place on `refactor/stack-lifecycle`.
- The active machine state is tracked in `.git/ai/plan-state.yaml`.
- The active executor packet is `.git/ai/current-step.yaml`.

## Current Phase

- Stage 1: Shared Contract Draft
- Current ready step: `slr-01-contract-audit`

## Established Working Assumptions

- Terraform owns day-1 infrastructure and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- Shared inventory is an evolution of `stack.yaml`.
- Generated artifacts are derived only.
- Terraform may offer an approved post-change day-2 reconcile path.

## Suggested Next Step

Run the current ready step from the autonomous workflow:

- planner/state source: `.git/ai/plan-state.yaml`
- executor packet: `.git/ai/current-step.yaml`
- current step id: `slr-01-contract-audit`

Primary objective:

- audit the current implemented contract surface and capture coverage, gaps, and conflicts before drafting the shared `stack.yaml` contract

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
Do not use legacy `.git/ai/handoff-to-*.yaml` files for this refactor flow.

## Open Questions To Carry Forward

- exact shape of the shared stack contract
- exact classification of managed vs observed vs adoptable paths
- exact validation gates and thresholds
- whether the Stage 1 audit reveals a need to split the shared contract draft into smaller follow-on steps

## Execution Model

- `execution-plan.md` is the durable human roadmap
- `.git/ai/plan-state.yaml` is the machine state
- `.git/ai/current-step.spec.yaml` is the authoring source for the next executor packet
- `.git/ai/current-step.yaml` is the rendered executor packet
- `.git/ai/reports/<step-id>.md` is the execution report
- `.git/ai/blocker.yaml` exists only when autonomous execution cannot continue

Normal successful executor steps should update report plus plan state and stop.
Architect is for blocker triage or plan changes, not the default post-step hop.

## Session Closeout Checklist

- update [decisions.md](./decisions.md) if a decision is made
- update [plan.md](./plan.md) if the roadmap changes
- update [execution-plan.md](./execution-plan.md) if step structure changes
- update `.git/ai/plan-state.yaml` through the workflow scripts
- update this file only when the operator-facing starting point changes

## Legacy Note

Previous Stage 3 and Stage 4 experimental handoff-loop artifacts should be treated
as historical noise unless explicitly mined for useful design notes. They are not
the live control plane for this refactor anymore.
