# 03c-artifact-proxy-03 — Apply apt proxy and Terraform mirror config to ci-runner-01

> Historical task packet.
> This document reflects the earlier artifact-proxy workflow and retired branch
> model.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## Phase

Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform mirror)

## Prerequisites

- [01-ci-runner-01 — Deploy and register ci-runner-01 on build_seg](01-ci-runner-01-deploy-ci-runner.md) complete
- [03c-artifact-proxy-01 — Deploy apt-cacher-ng stack on infra_seg](03c-artifact-proxy-01-deploy-apt-cacher.md) complete
- [03c-artifact-proxy-02 — Configure Terraform provider filesystem mirror](03c-artifact-proxy-02-configure-terraform-mirror.md) complete

## Objective

`ci-runner-01` has both `/etc/apt/apt.conf.d/01proxy` and `/root/.terraformrc`, and it is
ready to perform apt installs and Terraform init operations through the local infra services.

## Scope

- Re-run `deploy-ci-runner.yml`
- Verify apt proxy config on the runner
- Verify `.terraformrc` on the runner
- Verify apt-cacher stats increase after a runner apt operation

## Out of Scope

- Deploying additional LXCs
- Harbor image cache validation

## Acceptance Criteria

- [ ] `/etc/apt/apt.conf.d/01proxy` exists on `ci-runner-01`
- [ ] `/root/.terraformrc` exists on `ci-runner-01`
- [ ] `apt-get update` on `ci-runner-01` can hit `10.57.3.11:3142`

## Session Prompt

```text
TASK: Re-run the ci-runner playbook so the runner picks up the apt proxy and Terraform mirror settings.

STEP 1 — Source environment:
  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test

STEP 2 — Re-run the runner playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.0.63," \
    terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

STEP 3 — Verify files:
  ssh root@10.57.0.63 "cat /etc/apt/apt.conf.d/01proxy"
  ssh root@10.57.0.63 "cat /root/.terraformrc"

STEP 4 — Verify apt-cacher usage:
  ssh root@10.57.0.63 "apt-get update -qq"
  curl http://10.57.3.11:3142/acng-report.html

DONE WHEN: ci-runner-01 is configured to use both local infra services.
```
