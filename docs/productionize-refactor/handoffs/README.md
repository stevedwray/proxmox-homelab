# Productionize Refactor Handoffs

## Purpose

These handoff packets are designed for separate GitHub Copilot sessions.

Each packet is intentionally narrow:

- one session
- one primary objective
- one bounded write scope
- one clear "done when" definition

Use these when you want to delegate a slice of the refactor without carrying
the whole program context into every session.

## Recommended Session Order

1. [01-credential-controls.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/01-credential-controls.md:1)
2. [02-production-environment-model.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/02-production-environment-model.md:1)
3. [03-production-storage-manifest.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/03-production-storage-manifest.md:1)
4. [04-production-network-intent.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/04-production-network-intent.md:1)
5. [05-stack-target-decoupling.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/05-stack-target-decoupling.md:1)
6. [06-canary-validation-gate.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/06-canary-validation-gate.md:1)
7. [07-incremental-migration-plan.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/07-incremental-migration-plan.md:1)

## Source Documents

These packets are derived from:

- [docs/productionize-refactor/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)
- [docs/productionize-refactor/tasks/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/README.md:1)
- the corresponding task doc for each packet

## Session Rule

If using these with Copilot, prefer:

- one packet per session
- one work branch per packet
- one focused commit series per packet

Do not ask a single session to combine multiple packets unless the scopes are
explicitly being merged on purpose.
