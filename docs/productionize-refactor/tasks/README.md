# Productionize Refactor Tasks

## Purpose

This task set breaks the productionization refactor into focused slices that
can be implemented, reviewed, and validated incrementally on
`refactor/productionize`.

Use these tasks as the working backlog for the refactor. The main strategy doc
remains:

- [pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)

Copilot-ready session packets live at:

- [../handoffs/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/README.md:1)

## Task Order

1. [01-credential-controls.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md:1)
2. [02-production-environment-model.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/02-production-environment-model.md:1)
3. [03-production-storage-manifest.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/03-production-storage-manifest.md:1)
4. [04-production-network-intent.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/04-production-network-intent.md:1)
5. [05-stack-target-decoupling.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/05-stack-target-decoupling.md:1)
6. [06-canary-validation-gate.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md:1)
7. [07-incremental-migration-plan.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)

## Sequencing Rule

- credential controls come before broad production secret availability
- environment modeling comes before real `pve` targeting
- canary validation comes before high-value service migration
- migration planning must reflect the real results of the canary gate

## Branching Pattern

Suggested implementation branches:

- `work/productionize-01-credential-controls`
- `work/productionize-02-production-env-model`
- `work/productionize-03-storage-manifest`
- `work/productionize-04-network-intent`
- `work/productionize-05-stack-decoupling`
- `work/productionize-06-canary-validation`
- `work/productionize-07-migration-plan`

## Definition Of Done For The Refactor Program

- production credential access is non-default and tightly gated
- `pve` storage and network manifests are tracked and validated
- active stacks are no longer hardcoded to `pve-test`
- one low-risk canary has been proven on `pve`
- there is a documented, dependency-aware order for migrating real services
