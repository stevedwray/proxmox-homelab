# Phase 02 — Memory Upgrade (Historical)

## Status

Complete. Historical reference only.

## Why this document is historical

This phase document was written for an earlier environment model in which `pve-test`
ran as a nested Proxmox VM and needed to be resized from the parent Proxmox host.

The current project model is different:

- `pve-test` is a **bare-metal Proxmox laptop**
- the nested-VM resize workflow no longer applies
- the active development and deployment flow is indexed from [README.md](./README.md)

See the revised architecture and planning documents for the current target state:

- [docs/design/GreenField.md](../design/GreenField.md)
- [docs/design/NetworkPlanning.md](../design/NetworkPlanning.md)
- [docs/plan/README.md](./README.md)

## Historical summary

The original purpose of this phase was to increase pve-test memory headroom before
Phase 04 shared services were brought up. That work is considered complete and is no
longer an active deployment task.

## Follow-on guidance

- Do not use the old `qm set` host-VM workflow from the retired nested-environment model.
- If platform capacity needs to be revisited again, create a new phase or task document
  against the current bare-metal pve-test environment instead of reviving the old flow.
