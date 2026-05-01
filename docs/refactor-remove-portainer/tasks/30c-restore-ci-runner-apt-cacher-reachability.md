# Task 30c: Restore repeatable `ci-runner-01` apt-cacher reachability in code

## Type

Development

## Objective

Implement the smallest repo-managed fix that restores `build_seg` reachability
from `ci-runner-01` to apt-cacher at `10.57.3.11:3142`, then prove the
supported `ci-runner-01` configuration path succeeds end-to-end.

This is a narrow unblocker task. It exists because Task 30b produced
authoritative blocked evidence: the container was created, but the functional
configuration path failed during apt dependency installation because the apt
proxy was unreachable from VMID `141`.

## Files

- `docs/refactor-remove-portainer/decisions.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/30c-restore-ci-runner-apt-cacher-reachability.md`
- `docs/refactor-remove-portainer/prompts/30c-restore-ci-runner-apt-cacher-reachability.yaml`
- `docs/refactor-remove-portainer/reports/30b-validate-ci-runner-functional-configuration-report.md`
- `terraform/lxc/network/pve-test.yaml`
- `terraform/lxc/network/NETWORK_CONTRACT.md`
- `ansible/00-initial-setup/README.md`
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
- `terraform/lxc/ansible/playbooks/validate-network-layer.yml`

## Preconditions

- Task 30b is recorded on disk in:
  - `docs/refactor-remove-portainer/reports/30b-validate-ci-runner-functional-configuration-report.md`
  - that report must explicitly show `Status: blocked`
- Treat the current live baseline as authoritative:
  - `ci-runner-01` exists as VMID `141`
  - apt-cacher exists at `10.57.3.11` on `infra_seg`
  - retained CTs `153` (`proxy-stack`) and `154` (`monitoring-stack`) remain
    present
- The fix must be repeatable in repo-managed code. Do not close this task with
  a manual one-off router or host change that is not captured in the repo.
- Do not run Sonar or Snyk in this task. This is an exploratory live unblocker,
  not a merge-candidate integration step.

## Operations

1. Cut a clean short-lived branch from the current architecture-approved
   package baseline.
2. Verify `pve-test` targeting and confirm the Task 30b blocked evidence is
   present on disk.
3. Reproduce or confirm the apt-cacher reachability blocker from VMID `141`.
4. Identify the smallest repo-managed code change that restores
   `build_seg -> infra_seg tcp/3142` reachability in a repeatable way.
5. Implement that code change without widening into unrelated network cleanup.
6. Apply only the affected automation needed to activate the fix on `pve-test`.
7. Validate from VMID `141` that:
   - `10.57.3.11:3142` is reachable
   - apt update succeeds through the configured proxy path
8. Re-run the supported orchestration path:
   - `./with-secrets ./scripts/provision.sh --stack ci-runner-01`
9. Verify inside VMID `141` that the runner systemd service is active.
10. Verify via GitHub Actions API that runner `ci-runner-pve-test` is online.
11. Capture the post-fix `pct list`.
12. Write the task report to:
    - `docs/refactor-remove-portainer/reports/30c-restore-ci-runner-apt-cacher-reachability-report.md`
13. Stop after reporting. Do not start Task 31 automatically.

## Postconditions

- The apt-cacher path for `ci-runner-01` is either fixed repeatably in code, or
  the first blocker outside the current repo-managed automation boundary is
  reported exactly.
- `ci-runner-01` functional readiness is re-validated through the supported
  provisioning path.
- Retained CTs outside this task scope remain unchanged.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/30b-validate-ci-runner-functional-configuration-report.md && echo present
rg -n "^Status: blocked$" docs/refactor-remove-portainer/reports/30b-validate-ci-runner-functional-configuration-report.md
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct exec 141 -- bash -lc \"timeout 5 bash -lc 'cat </dev/null >/dev/tcp/10.57.3.11/3142'\""
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct exec 141 -- apt-get update"
./with-secrets ./scripts/provision.sh --stack ci-runner-01
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct exec 141 -- systemctl is-active actions.runner.stevedwray-proxmox-homelab.ci-runner-pve-test.service"
./with-secrets gh api repos/stevedwray/proxmox-homelab/actions/runners --jq '[.runners[] | select(.name == \"ci-runner-pve-test\") | .status][0]'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 30b blocked evidence is present on disk
- the repo-managed code change restores apt-cacher reachability from VMID `141`
- apt update succeeds from VMID `141`
- the supported `ci-runner-01` configuration path succeeds
- the runner systemd service is active inside VMID `141`
- the GitHub Actions API reports runner `ci-runner-pve-test` as `online`
- retained CTs `153` and `154` remain present

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 30b evidence is missing from disk or does not show `Status: blocked`.
- The required fix cannot be implemented through repo-managed code in scope.
- The task would require a manual one-off environment change to succeed.
- `10.57.3.11:3142` remains unreachable from VMID `141` after the scoped fix.
- The supported `ci-runner-01` configuration path still fails after the network
  fix is applied.
- The runner service is not active inside VMID `141`.
- The GitHub Actions API does not report runner `ci-runner-pve-test` as
  `online`.
- A retained non-target CT is unexpectedly affected.
- Unexpected tracked changes appear outside the scoped files.
