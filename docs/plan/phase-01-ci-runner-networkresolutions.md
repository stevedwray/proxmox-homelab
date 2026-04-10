# Phase 01 - CI Runner Problems and Fixes

## Purpose

This note records the failures encountered while bringing `Validate` back to green for the `ci-runner-01` deployment, along with the fixes that were applied.

## What failed

### 1. The runner could not execute the Terraform setup action

The first `Validate` runs failed inside `terraform-validate` because `hashicorp/setup-terraform` depends on `node`, and the freshly deployed Debian 13 runner image did not have `nodejs` installed.

Observed failure:

- `env: 'node': No such file or directory`

Fix:

- Added `nodejs` to the runner bootstrap playbook at [`terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-ci-runner.yml)
- Re-ran the runner setup so `setup-terraform` could execute normally

### 2. `actions/setup-python` was not reliable on Debian 13

The `ansible-lint` job initially used `actions/setup-python@v5`, but the runner could not provision the requested Python version on Debian 13.

Observed failure:

- `The version '3.12' with architecture 'x64' was not found for Debian 13.`

I tried moving the workflow to a newer Python version, but the GitHub action still was not a good fit for this runner image.

Fix:

- Removed `actions/setup-python` from [`.github/workflows/validate.yml`](/home/steve/git/proxmox-homelab/.github/workflows/validate.yml)
- Switched to a local virtual environment created with `python3 -m venv .venv`
- Installed `ansible-lint` into the venv and used that executable directly

### 3. System `pip` was blocked by Debian 13's PEP 668 behavior

After removing `actions/setup-python`, installing `ansible-lint` with the system Python still failed because Debian 13 marks the base Python environment as externally managed.

Observed failure:

- `error: externally-managed-environment`

Fix:

- Kept the venv-based install so `ansible-lint` runs in an isolated environment instead of the system Python

### 4. `ansible-lint` then exposed real repository issues

Once the environment problems were gone, `ansible-lint` started reporting genuine lint problems in the repo instead of setup failures.

Observed failures:

- `become_user` without `become` in [`terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-ci-runner.yml)
- Long shell conditionals in [`terraform/lxc/ansible/playbooks/validate-network-matrix.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/validate-network-matrix.yml)

Fix:

- Added `become: true` next to `become_user` in the runner configuration task
- Wrapped the long shell conditionals in the network matrix playbook

## Result

After those changes:

- `terraform fmt -check -recursive terraform/` passed
- `ansible-lint playbooks/` passed locally, with remaining warnings only
- The `Validate` workflow moved from runner/bootstrap failures to normal repo-level checks

## Network and redeploy follow-up

The teardown/redeploy test exposed a second set of operational issues around the SDN-backed `build_seg` stack:

- Destroy initially failed because Proxmox would not delete a VNet while its subnet still existed.
- Fresh redeploys could not SSH directly to the container IP from the workstation because the container lives behind `pve-test`.
- The runner bootstrap playbook also needed to wait for SSH before gathering facts on a recreated guest.

Those issues were resolved by:

- Removing SDN subnets before deleting the VNet in [`terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml)
- Using `ProxyJump=root@pve-test.gibbsgreatly.xyz` in [`terraform/lxc/templates/inventory.tpl`](/home/steve/git/proxmox-homelab/terraform/lxc/templates/inventory.tpl)
- Adding `wait_for_connection` and deferred fact gathering in [`terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-ci-runner.yml)

The remaining non-network blocker is the GitHub Actions runner registration token:

- `runner_registration_token` is still supplied manually in the documented bootstrap flow
- The playbook does not yet source or generate the token itself

So the network resolution work is complete, and the remaining gap is runner-registration plumbing rather than SDN connectivity.

## Notes

- The repository still contains non-blocking ansible-lint warnings in the Harbor and network-matrix areas, but they were not the cause of the runner outage.
- The user-facing plan document for the deployment remains in [`docs/plan/phase-01-ci-runner-deployment.md`](/home/steve/git/proxmox-homelab/docs/plan/phase-01-ci-runner-deployment.md)
