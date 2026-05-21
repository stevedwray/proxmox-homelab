# Productionize Refactor

## Purpose

This directory is the working documentation home for the productionization
refactor: the work required to make the current `pve-test`-oriented platform
safe, parameterized, and incrementally deployable on production `pve`.

This refactor is not a single cutover. It is a staged program covering:

- environment separation
- storage and network parameterization
- production credential controls
- migration sequencing from `pve-test` to `pve`
- early validation and canary workflows

## Branch Model

Primary branch for this refactor:

- `refactor/productionize`

Base branch:

- `baseline/teardown-validated`

Recommended child-branch pattern during implementation:

- `work/productionize-01-storage-manifest`
- `work/productionize-02-network-intent`
- `work/productionize-03-credential-guardrails`
- `work/productionize-04-stack-decoupling`
- `work/productionize-05-canary-validation`

Working rule:

- merge focused implementation branches back into `refactor/productionize`
- keep `refactor/productionize` as the integration branch for this whole
  program
- do not promote directly from partial work branches

## Documents

- Main working plan:
  [pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)
- Task backlog:
  [tasks/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/README.md:1)
- Copilot handoff packets:
  [handoffs/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/README.md:1)

## Relationship To Other Docs

- canonical network design stays in
  [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)
- environment-specific network intent stays in
  [terraform/lxc/network/](/home/steve/git/proxmox-homelab/terraform/lxc/network/)
- this directory owns the refactor strategy, sequencing, risk controls, and
  migration plan

## Outcomes We Want

- production storage and network intent are first-class tracked configuration
- active stacks are not hardcoded to `pve-test`
- production credentials are tightly gated and not casually available to AI
- one-stack-at-a-time migration to `pve` is possible
- early canary validation proves networking before critical services move
