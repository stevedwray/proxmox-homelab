# Stack Lifecycle Refactor

This document tree is the working area for the stack lifecycle refactor:

- clarify the Terraform day-1 / Ansible day-2 boundary
- evolve `stack.yaml` into a shared stack contract
- define inventory, drift, validation, and change-management rules
- plan and track the refactor across multiple sessions

Use this tree as the durable context for future work. Do not rely on chat history.

## Working Files

- [decisions.md](./decisions.md): confirmed decisions, defaults, and open questions
- [plan.md](./plan.md): phased roadmap, scope, exemplars, and rollout
- [execution-plan.md](./execution-plan.md): autonomous execution roadmap and step inventory
- [current-state.md](./current-state.md): current state for the next session
- [validation.md](./validation.md): validation policy and required checks
- [inventory-model.md](./inventory-model.md): shared stack contract and generated artifact model
- [drift-policy.md](./drift-policy.md): managed, observed, and adoptable drift rules
- [special-cases.md](./special-cases.md): notes on stacks with exceptional behavior
- [autonomous-execution-workflow.md](./autonomous-execution-workflow.md): redesigned low-touch agent workflow

## Session Start

At the start of a new planning session, read:

1. [decisions.md](./decisions.md)
2. [plan.md](./plan.md)
3. [current-state.md](./current-state.md)
4. [execution-plan.md](./execution-plan.md)

Then confirm the current phase and work only on the next scoped item unless a blocker is found.

## Current Intent

- Terraform owns infrastructure lifecycle and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- `stack.yaml` will evolve into the shared stack contract.
- Generated artifacts remain derived, not source of truth.
- Terraform may offer an approved safe path to run day-2 reconciliation after infra changes.
