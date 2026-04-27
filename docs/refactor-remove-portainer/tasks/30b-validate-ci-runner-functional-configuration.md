# Task 30b: Validate `ci-runner-01` functional configuration

## Type

Development

## Objective

Validate that the newly created `ci-runner-01` container is functionally usable
as a GitHub Actions self-hosted runner by running its explicit configuration
path and checking the core operational signals.

This is a narrow functional validation task. It is not a full CI job smoke
test.

## Files

- `docs/refactor-remove-portainer/decisions.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/30b-validate-ci-runner-functional-configuration.md`
- `docs/refactor-remove-portainer/prompts/30b-validate-ci-runner-functional-configuration.yaml`
- `docs/refactor-remove-portainer/reports/30a-validate-ci-runner-container-creation-report.md`
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
- `scripts/provision.sh`

## Preconditions

- Task 30a is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/30a-validate-ci-runner-container-creation-report.md`
  - that report must explicitly show `Status: complete`
- Treat the current live baseline as authoritative:
  - `ci-runner-01` exists as VMID `141`
  - retained CTs `153` (`proxy-stack`) and `154` (`monitoring-stack`) remain
    present
- Scope is limited to functional validation of `ci-runner-01` through the
  supported orchestration path.
- Do not run Sonar or Snyk in this task. This is an exploratory live
  functional validation step, not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current architecture-approved
   package baseline.
2. Verify `pve-test` targeting and capture the current `pct list`.
3. Run the explicit configuration path for `ci-runner-01` using:
   - `./with-secrets ./scripts/provision.sh --stack ci-runner-01`
4. Verify inside VMID `141` that the runner systemd service is active.
5. Verify via the GitHub Actions API that runner `ci-runner-pve-test` is
   visible and online.
6. Capture the post-validation `pct list`.
7. Write the task report to:
   - `docs/refactor-remove-portainer/reports/30b-validate-ci-runner-functional-configuration-report.md`
8. Stop after reporting. Do not start Task 31 automatically.

## Postconditions

- `ci-runner-01` is confirmed functionally configured, or the exact first
  blocker is reported.
- Retained CTs outside this task scope are unchanged.
- No additional stacks are applied in this task beyond the ci-runner
  configuration path.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/30a-validate-ci-runner-container-creation-report.md && echo present
rg -n "^Status: complete$" docs/refactor-remove-portainer/reports/30a-validate-ci-runner-container-creation-report.md
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets ./scripts/provision.sh --stack ci-runner-01
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct exec 141 -- systemctl is-active actions.runner.stevedwray-proxmox-homelab.ci-runner-pve-test.service"
./with-secrets gh api repos/stevedwray/proxmox-homelab/actions/runners --jq '[.runners[] | select(.name == "ci-runner-pve-test") | .status][0]'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 30a evidence is present on disk and explicitly marked complete
- the explicit `ci-runner-01` configuration path succeeds
- the runner systemd service is active inside VMID `141`
- the GitHub Actions API reports runner `ci-runner-pve-test` as `online`
- retained CTs `153` and `154` remain present
- no unrelated code or package files are edited beyond the required report

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 30a evidence is missing from disk or does not show `Status: complete`.
- The explicit `ci-runner-01` configuration path fails.
- The runner service is not active inside VMID `141` after configuration.
- The GitHub Actions API does not report runner `ci-runner-pve-test` as
  `online`.
- A retained non-target CT is unexpectedly affected.
- Unexpected tracked changes appear outside the scoped report artifact.
