# 00a-host-bootstrap-03 — Build and register the Debian LXC template

## Status

PENDING

## Phase

Phase 00a — Proxmox Host Bootstrap Alignment

## GitHub Issue

[#127](https://github.com/stevedwray/proxmox-homelab/issues/127)

## Greenfield assumption

This task assumes the Proxmox host initial setup (task 00a-01) is complete and pve-test has
the package baseline applied. No Debian LXC template is assumed to exist yet on pve-test.

## Prerequisites

- Task 00a-01 complete — pve-test has the package baseline and Terraform API token
- Storage pool `infrastructure-containers` exists on pve-test
- Storage pool `storage-template` exists on pve-test
- The Proxmox Debian template tarball is available on the host or reachable via HTTP
- SSH access to pve-test as root

## Objective

A Debian LXC template (`debian-13.1-2-docker-template.tar.gz`) exists in
`storage-template:vztmpl/` on pve-test, pre-configured with Docker and the automation
tooling expected by `terraform/lxc`. This template is the base for every LXC deployed in
later phases.

## Scope

- Align `ansible/00-initial-setup/build-debian-13-template.yml` with the current pve-test
  design:
  - Change target host group from `proxmox_production` to `proxmox` (pve-test)
  - Change `storage_pool` default from `infrastructure-storage` to `infrastructure-containers`
  - Verify template naming matches `debian-13.1-2-docker-template.tar.gz` as expected by
    `terraform/lxc` stacks
  - Verify network settings use `vmbr0` / `192.168.1.0/24` for the build LXC
- Run the updated playbook against pve-test
- Confirm the template is registered in `storage-template:vztmpl/`

## Out of Scope

- SDN zone configuration (task 00a-02)
- Any LXC deployment beyond the template builder itself
- Updating `ansible/00-initial-setup/README.md` (can be a separate follow-on)

## Inputs

- `ansible/00-initial-setup/build-debian-13-template.yml` (needs redesign)
- `ansible/group_vars/proxmox.yml`
- `terraform/lxc/stacks/portainer-stack/stack.yaml` (reference for expected template name)
- `ansible/inventory/dev.yml`

## Expected Outputs

- Updated `ansible/00-initial-setup/build-debian-13-template.yml` targeting pve-test
- Template registered at `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz`

## Constraints and Conventions

- The template name must exactly match what `terraform/lxc` stacks reference:
  `debian-13.1-2-docker-template.tar.gz`
- The build LXC uses a temporary IP on `vmbr0` and is destroyed after the template is
  packaged — it must not conflict with allocated IPs
- The template storage pool name is `storage-template`, not `local` or `infrastructure-containers`

## Acceptance Criteria

- [ ] `ansible/00-initial-setup/build-debian-13-template.yml` targets `proxmox` group (pve-test)
- [ ] `storage_pool` defaults to `infrastructure-containers`
- [ ] Playbook run exits 0 with no failed tasks
- [ ] `ssh root@pve-test pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz` returns a result
- [ ] Template can be used to create an LXC via `pct create` without errors

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Align the Debian LXC template build playbook with the current pve-test design, then
run it to produce the template needed by terraform/lxc.

STEP 1 — Review the current playbook and what needs to change:
  Read: ansible/00-initial-setup/build-debian-13-template.yml
  Read: ansible/group_vars/proxmox.yml
  Read: terraform/lxc/stacks/portainer-stack/stack.yaml   (to confirm expected template name)

STEP 2 — Update the playbook:
  - Change hosts: from proxmox_production to proxmox
  - Change storage_pool default from infrastructure-storage to infrastructure-containers
  - Confirm the final template filename matches debian-13.1-2-docker-template.tar.gz
  - Confirm network_bridge defaults to vmbr0 and gateway_ip to 192.168.1.1
  - Confirm the build LXC IP (template_ip) does not conflict with allocated IPs

STEP 3 — Run the updated playbook:
  ansible-playbook \
    -i ansible/inventory/dev.yml \
    ansible/00-initial-setup/build-debian-13-template.yml

STEP 4 — Verify the template:
  ssh root@pve-test.gibbsgreatly.xyz \
    "pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz"
  # Expect: one result with the correct filename

STEP 5 — Commit the updated playbook:
  git add ansible/00-initial-setup/build-debian-13-template.yml
  git commit -m "fix(ansible): align build-debian-13-template for pve-test storage and host group"

DONE WHEN: The template exists in storage-template:vztmpl/ and is confirmed usable for LXC
creation. Task 00b-01 (deploy Portainer) can now proceed.
```
