# Task 03: Production Storage Manifest

## Goal

Create and validate `terraform/lxc/storage/pve.yaml` so production storage
policy is explicit, tracked, and testable.

## Objective

Translate the live `pve` storage layout into a production storage manifest that
fits the kinds of services we actually run in a homelab.

## Initial Direction

Starting recommendation:

- root filesystems on `infrastructure-containers`
- normal Docker writable layers on `infrastructure-containers`
- explicit durable service data on `storage-containers`
- templates on `storage-template`

## Deliverables

- `terraform/lxc/storage/pve.yaml`
- profile mapping for:
  - rootfs
  - Docker mount
  - extra durable mount
  - template storage
- documented rationale for why each pool is used
- validation commands against live production storage

## Design Decisions To Capture

- whether `durable-default` should point to `storage-containers`
- whether any services need production-specific extra-mount profiles
- whether monitoring data should get its own profile shape
- whether non-Docker stacks should continue inheriting Docker storage at all

## Service-Aware Considerations

- Harbor is the strongest candidate for explicit durable data on
  `storage-containers`
- NetBox can stay relatively small unless growth proves otherwise
- CoreDNS and step-ca do not really need Docker storage if the module is later
  refined
- apt-cacher may benefit from explicit cache storage instead of pretending to
  be a Docker-heavy stack

## Files Likely Involved

- new `terraform/lxc/storage/pve.yaml`
- [terraform/lxc/storage/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/storage/pve-test.yaml:1)
- [terraform/lxc/validate-storage-contract.py](/home/steve/git/proxmox-homelab/terraform/lxc/validate-storage-contract.py:1)
- [terraform/lxc/modules/lxc-docker-host/main.tf](/home/steve/git/proxmox-homelab/terraform/lxc/modules/lxc-docker-host/main.tf:1)

## Dependencies

- task 02 for overall environment modeling

## Validation

- manifest resolves for all active target stacks
- manifest backends exist on `pve`
- required content types are present
- template artifact resolves correctly on `pve`

## Risks

- copying `pve-test` storage policy too literally
- overallocating durable storage without evidence
- leaving wasteful Docker mounts in place for systemd-only services

## Suggested Branch

- `work/productionize-03-storage-manifest`
