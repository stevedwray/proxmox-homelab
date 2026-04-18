# 01-ci-runner-01 — Deploy and register ci-runner-01 on build_seg

## Status

COMPLETE

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
registered and online with labels `self-hosted`, `pve-test`, `build`, and the repo has a
worker for `terraform-validate` and `ansible-lint` on the fresh `pve-test` build.

## Scope

- Apply the `ci-runner-01` stack via Terragrunt
- Run `deploy-ci-runner.yml`
- Verify runner registration in GitHub
- Verify the runner survives a reboot

## Out of Scope

- GitHub Actions pinning
- apt proxy or Terraform mirror follow-up work from Phase 03c

## Acceptance Criteria

- [x] VMID 141 exists at `10.57.0.63`
- [x] `deploy-ci-runner.yml` exits 0
- [x] Runner appears online in GitHub with labels `self-hosted`, `pve-test`, `build`, `linux`, `x64`
- [x] `terraform-validate` and `ansible-lint` can be scheduled again
- [x] Runner returns online after LXC reboot

## Completion Notes

- Verified live on 2026-04-16 against `pve-test.gibbsgreatly.xyz`.
- `terragrunt apply -auto-approve` completed successfully for
  `terraform/lxc/stacks/ci-runner-01` and returned VMID 141 on `10.57.0.63/24`.
- GitHub reports `ci-runner-pve-test` online with labels `self-hosted`, `Linux`, `X64`,
  `pve-test`, and `build`.
- Recovery required two greenfield fixes:
  - creating the MikroTik `vlan10-build` interface with `10.57.0.1/24`
  - temporarily overriding runner bootstrap DNS to `1.1.1.1` because router-local DNS on
    `10.57.0.1` did not answer during initial bring-up
- Reboot recovery required an additional persistence fix: Proxmox rewrote
  `/etc/resolv.conf` on boot, so the runner needed a systemd-managed resolver restore
  step before the GitHub runner service started.
- Target state is still MikroTik DNS, not `1.1.1.1`. The temporary override used during
  recovery has now been removed, and the runner was revalidated against `10.57.0.1`.
- This incident showed that resolver persistence is not a template-only concern.
  Proxmox writes `/etc/resolv.conf` at boot, so future LXC DNS fixes should land in the
  container creation/bootstrap path first and only use template rebuilds for shared base
  image changes.

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
