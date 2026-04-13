# 01-ci-runner-01 — Deploy and register ci-runner-01 on build_seg

## Status

PENDING

## Phase

Phase 01 — CI Runner Deployment and Actions Pinning

## Greenfield assumption

This task assumes a greenfield laptop rebuild where the local Portainer server is already
up and the `build_seg` SDN zone exists on `pve-test`.

## Prerequisites

- Phase 00b complete
- `.env` and `.env.pve-test` sourced
- `build_seg` SDN zone/VNet applied on `pve-test`
- GitHub CLI authenticated on the workstation
- `terraform/lxc/stacks/ci-runner-01/stack.yaml` and `terragrunt.hcl` exist
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml` exists

## Objective

LXC `ci-runner-01` (VMID 141) is running at `10.57.0.63`, the GitHub Actions runner is
registered and online with labels `self-hosted`, `pve-test`, `build`, and the repo once
again has a worker for `terraform-validate` and `ansible-lint`.

## Scope

- Apply the `ci-runner-01` stack via Terragrunt
- Run `deploy-ci-runner.yml`
- Verify runner registration in GitHub
- Verify the runner survives a reboot

## Out of Scope

- GitHub Actions pinning
- apt proxy or Terraform mirror follow-up work from Phase 03c

## Acceptance Criteria

- [ ] VMID 141 exists at `10.57.0.63`
- [ ] `deploy-ci-runner.yml` exits 0
- [ ] Runner appears online in GitHub with labels `self-hosted`, `pve-test`, `build`, `linux`, `x64`
- [ ] `terraform-validate` and `ansible-lint` can be scheduled again
- [ ] Runner returns online after LXC reboot

## Session Prompt

```text
TASK: Deploy and register ci-runner-01 so self-hosted workflow jobs can run again.

STEP 1 — Source environment:
  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test
  echo "$TF_VAR_proxmox_node"   # must print pve-test

STEP 2 — Apply the stack:
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
  terragrunt apply

STEP 3 — Run the playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.0.63," \
    terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

STEP 4 — Verify runner registration:
  gh api repos/stevedwray/proxmox-homelab/actions/runners \
    --jq '.runners[] | {name, status, labels: [.labels[].name]}'

STEP 5 — Verify reboot recovery:
  ssh root@10.57.0.63 "systemctl status actions.runner.*"
  ssh root@10.57.0.63 reboot
  # confirm the runner returns online after boot

DONE WHEN: ci-runner-01 is online and self-hosted workflow jobs can run again.
```
