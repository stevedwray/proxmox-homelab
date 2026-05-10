# Decisions

This file records decisions that have been made for the stack lifecycle refactor.

## Confirmed

### Ownership Boundary

- Terraform owns infrastructure lifecycle and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- Router, switch, and Proxmox SDN control remain in the day-1 / infrastructure domain, even where Ansible is the actuator.

### Workflow

- The target model is a day-1 / day-2 split.
- A combined safe path is desired:
  - infrastructure plan/apply
  - optional approved day-2 reconcile
  - validation
- Maintenance playbooks should be runnable per container.
- Coordinated changes across multiple containers must also be supported.

### Shared Model

- Shared inventory should be an evolution of `stack.yaml`.
- `stack.yaml` should become a higher-level shared contract used to derive Terraform and Ansible inputs.

### Behavior

- Day-2 playbooks should be safe to rerun.
- Ansible should be the supported way to repair drift.
- Manual in-container changes should be auditable.
- Manual changes should be adoptable into managed config with operator approval.
- Stack upgrades such as package upgrades should run through Ansible.

### Secrets and Config

- Secrets continue to flow through `./with-secrets`.
- Non-secret configuration should move toward clearer vars structures over time.

### Change Management

- The refactor should be staged with testing between phases.
- The overall effort is one coordinated refactor program.
- Migration should start with cleaner platform stacks, not the most interconnected ones.

## Recommended Defaults

- Generated files remain derived artifacts, not source of truth.
- Terraform does not auto-run guest reconcile by default.
- Terraform may offer an approved post-change day-2 reconcile path.
- Managed in-container settings are authoritative and may be overwritten by Ansible.

## Candidate Exemplars

### Conservative Pair

- `apt-cacher-stack`
- `harbor-stack`

### Broader Pair

- `apt-cacher-stack`
- `netbox-stack`

## Open Decisions

- Exact `stack.yaml` schema for the shared contract
- Exact inventory generation flow and artifact boundaries
- Which in-container paths and settings are `managed`, `observed`, or `adoptable`
- Final validation gates for infra-only, config-only, and coordinated changes
- Whether directory reorganization is part of the initial staged refactor
