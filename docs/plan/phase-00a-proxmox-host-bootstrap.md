# Phase 00a — Proxmox Host Bootstrap Alignment

## Goal

Bring the Proxmox host/bootstrap Ansible under the active plan so that host preparation is
explicitly part of the current pve-test rebuild path rather than separate background
tooling.

This phase covers the automation in:

- `ansible/00-initial-setup/`
- `ansible/01-base-system/`

The aim is not to rewrite all of that code in one pass. The aim is to classify what is
required for the current bare-metal `pve-test` design, what needs redesign, and what
should be treated as historical or alternative environment support.

## Why this phase exists

The revised design and plan now assume:

- `pve-test` is a bare-metal Proxmox laptop
- the active network model is Proxmox SDN VLAN zones on `vmbr0`
- the active stack deployment path is `terraform/lxc`
- the active target storage pool for stacks is `infrastructure-containers`

There is also host/bootstrap Ansible in the repository which still contains older
environment assumptions. Further development of that automation needs to be planned
explicitly so the docs, host bootstrap, and LXC/service provisioning all stay aligned.

## Scope

- Review `ansible/00-initial-setup` and `ansible/01-base-system`
- Classify each playbook as:
  - active and required for the current plan
  - active but needs redesign for the current plan
  - historical / alternate environment support
- Define the minimum host bootstrap requirements for pve-test
- Add follow-on tasks for any required code/documentation alignment work

## Out of Scope

- Reworking all storage automation immediately
- Adding a second environment model beside the active pve-test rebuild
- Replacing `terraform/lxc` as the primary provisioning path

## Current assessment

### Active and required

- `ansible/00-initial-setup/proxmox-initial-setup.yml`
  Purpose: package repository baseline, Proxmox post-install tuning, Terraform API user/token creation, optional host firewall backend enablement.

- `ansible/00-initial-setup/proxmox-initial-tests.yml`
  Purpose: read-only validation helper for confirming repository state, token presence, and general host readiness before or after the bootstrap run.

- `ansible/00-initial-setup/proxmox-sdn-setup.yml`
  Purpose: apply the pve-test VLAN SDN zones and VNets directly from `terraform/lxc/network/pve-test.yaml` and verify the resulting bridges on-host.

- `ansible/00-initial-setup/build-debian-13-template.yml`
  Purpose: build, preserve, and package the Debian 13 LXC template expected by the active `terraform/lxc` stacks.

- `ansible/00-initial-setup/tasks/proxmox-host-firewall-backend.yml`
  Purpose: enable the nftables-backed Proxmox firewall capability needed by the SDN/VNet firewall work.

- `ansible/01-base-system/proxmox-terraform-setup.yml`
- `ansible/01-base-system/terraform-token-management.yml`
  Purpose: standalone Terraform token lifecycle management when needed outside the broader host setup playbook.

### Active documentation aligned with the current plan

- `ansible/00-initial-setup/README.md`
  Purpose: describe the canonical pve-test host bootstrap flow, active inventory usage, and the verified SDN/template verification paths.

### Historical / alternate environment support unless brought back into scope

- `ansible/00-initial-setup/proxmox-storage-setup.yml`
- `ansible/00-initial-setup/storage-prevalidation.yml`
- `ansible/00-initial-setup/storage-setup.yml`
- `ansible/00-initial-setup/storage-setup-02.yml`
- `ansible/00-initial-setup/storage-verify.yml`
- `ansible/00-initial-setup/StoragePlaybook.md`

These storage documents and playbooks describe multi-disk or alternate-environment storage
layouts that do not currently match the active pve-test plan. They should not be treated
as the canonical storage implementation for the current rebuild without a design update.

## Minimum host bootstrap requirements for the current plan

Before Phase 00b / 01 / 03b / 04 work is considered ready, the host layer should support:

1. Proxmox repo and package baseline on the bare-metal pve-test host
2. Terraform automation user and API token management
3. Optional host firewall backend enablement for Proxmox nftables-based firewall work
4. A documented template build path, if template creation remains part of the workflow
5. LXC bootstrap behavior that preserves the intended zone-local DNS resolver across boot
  and reboot cycles
6. Host bootstrap documentation that matches the current SDN VLAN and storage assumptions

## Tasks

| # | Task file | Description |
| --- | --- | --- |
| 01 | [00a-host-bootstrap-01-initial-setup.md](tasks/00a-host-bootstrap-01-initial-setup.md) | Run `proxmox-initial-setup.yml` — package repos, host tuning, Terraform API user/token |
| 02 | [00a-host-bootstrap-02-sdn-zones.md](tasks/00a-host-bootstrap-02-sdn-zones.md) | Write and run `proxmox-sdn-setup.yml` — create all four VLAN zones on pve-test |
| 03 | [00a-host-bootstrap-03-build-template.md](tasks/00a-host-bootstrap-03-build-template.md) | Align and run `build-debian-13-template.yml` — produce the Debian Docker template |

## Recommended follow-on tasks

1. Mark storage setup playbooks as historical/alternate-path in their headers unless a new storage phase brings them back into active scope.
2. Standardize LXC DNS handling in the platform layer so SDN-attached containers inherit
  the MikroTik gateway as their resolver without per-stack public DNS overrides.
3. Revisit the Debian template only if a shared base-image change is required. Do not rely
  on template contents alone to enforce `/etc/resolv.conf` because Proxmox may regenerate
  it on boot.

## Acceptance criteria

- [x] Task 00a-01 complete — Terraform API token provisioned on pve-test
- [x] Task 00a-02 complete — all four SDN VLAN zones active on pve-test
- [x] Task 00a-03 complete — Debian Docker template in `storage-template:vztmpl/`
- [x] Required host bootstrap playbooks are identified and classified
- [x] Non-canonical storage/bootstrap playbooks are clearly classified
