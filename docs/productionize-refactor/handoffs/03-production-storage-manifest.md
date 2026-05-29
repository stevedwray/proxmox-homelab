# Handoff 03: Production Storage Manifest

## Objective

Author the first production storage manifest for `pve` and document the chosen
storage policy.

## Branch

- `work/productionize-03-storage-manifest`

## Primary Source

- [Task 03: Production Storage Manifest](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/03-production-storage-manifest.md:1)

## Scope

In scope:

- `terraform/lxc/storage/pve.yaml`
- storage profile mapping and rationale
- manifest-level validation design

Out of scope:

- stack target decoupling
- production network intent rewrite
- non-Docker module refactors unless absolutely necessary for manifest clarity

## Files To Read First

- [terraform/lxc/storage/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/storage/pve-test.yaml:1)
- [terraform/lxc/validate-storage-contract.py](/home/steve/git/proxmox-homelab/terraform/lxc/validate-storage-contract.py:1)
- [docs/productionize-refactor/tasks/03-production-storage-manifest.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/03-production-storage-manifest.md:1)
- [docs/productionize-refactor/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)

## Files Most Likely To Change

- new `terraform/lxc/storage/pve.yaml`
- possibly docs in `docs/productionize-refactor/`

## Constraints

- fit the actual `pve` storage layout
- size for a homelab, not enterprise overprovisioning
- do not assume `local-lvm` should be the production runtime target

## Done When

- `terraform/lxc/storage/pve.yaml` exists
- the manifest expresses a coherent rootfs, Docker, durable, and template policy
- the rationale is documented

## Validation

- manifest shape matches what `terraform/lxc/main.tf` expects
- referenced storage backends are real production backends
- template storage resolves to `storage-template`

## Suggested Copilot Brief

```text
Work on Task 03 in docs/productionize-refactor/tasks/03-production-storage-manifest.md.
Create terraform/lxc/storage/pve.yaml based on the real production storage layout.
Keep the policy homelab-sized and practical.
Prefer infrastructure-containers for rootfs and normal Docker layers, and use storage-containers deliberately for durable data where it makes sense.
Do not broaden the task into network or stack target changes.
Document the rationale clearly.
```
