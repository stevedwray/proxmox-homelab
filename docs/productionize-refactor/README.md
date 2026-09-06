# Productionize Refactor

## Purpose

This directory now acts as a reduced historical reference for the
productionization refactor: the work required to make the platform safe,
parameterized, and incrementally deployable on production `pve`.

The detailed execution artifacts that used to live here have been removed. What
remains should be treated as durable reference material only.

The retained scope covers:

- environment separation
- storage and network parameterization
- production credential controls
- migration sequencing from `pve-test-vm` to `pve`
- production canary outcomes that may still be useful as reference

Current migration sequence status:

- `monitoring-stack` canary completed
- `portainer-stack` canary completed
- `netbox-stack` canary completed
- `ci-runner-01` is the next production migration after netbox

## Workflow Note

Do not use this directory as a source of truth for the current branch model or
promotion workflow.

For current workflow rules, use:

- [docs/workflow/branch-model.md](/home/steve/git/proxmox-homelab/docs/workflow/branch-model.md:1)
- [docs/workflow/environments.md](/home/steve/git/proxmox-homelab/docs/workflow/environments.md:1)

## Documents

- Main working plan:
  [pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)
- Task backlog:
  [tasks/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/README.md:1)
- Retained inventory / teardown reference:
  [pve-infra-teardown-inventory.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-infra-teardown-inventory.md:1)

## Relationship To Other Docs

- canonical network design stays in
  [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)
- environment-specific network intent stays in
  [terraform/lxc/network/](/home/steve/git/proxmox-homelab/terraform/lxc/network/)
- this directory owns the refactor strategy, sequencing, risk controls, and
  migration plan

## Outcomes We Want

- production storage and network intent are first-class tracked configuration
- active stacks are not hardcoded to `pve-test-vm`
- production credentials are tightly gated and not casually available to AI
- one-stack-at-a-time migration to `pve` is possible
- early canary validation proves networking before critical services move
