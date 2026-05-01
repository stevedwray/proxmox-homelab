# Task 33: Validate SDN VNet idempotency with the minimal build-path harness

## Type

Development

## Objective

Validate the current SDN VNet idempotency fix against the minimal build-path
harness instead of against the full rebuild gate.

This is the first task that reopens the current `configure-network-sdn-vnet.yml`
implementation path after the cleanup-first reset.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/33-validate-sdn-vnet-idempotency-with-minimal-harness.md`
- `docs/refactor-remove-portainer/prompts/33-validate-sdn-vnet-idempotency-with-minimal-harness.yaml`
- `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml`
- `terraform/lxc/validate-build-path.sh`
- `terraform/lxc/ansible/playbooks/validate-build-path.yml`

## Preconditions

- Task 32 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/32-run-minimal-build-path-harness-report.md`
- The minimal build-path harness is still available on `pve-test`, or can be
  cleanly re-applied from the same three-stack scope.
- Scope is limited to the SDN idempotency fix and the minimal harness. Do not
  widen back into the broad rebuild gate.
- Do not run Sonar or Snyk in this task. This is still an exploratory
  validation step, not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current `origin/dev/pve-test`
   baseline that includes the current SDN idempotency change and the Task 31
   minimal harness assets.
2. Validate the SDN playbook source locally.
3. Re-apply `net-build-01` against the already-present build-path baseline and
   confirm the SDN creation path no longer fails on existing zone/VNet objects.
4. Re-run the minimal build-path harness after the idempotency validation.
5. Write the task report to:
   - `docs/refactor-remove-portainer/reports/33-validate-sdn-vnet-idempotency-with-minimal-harness-report.md`
6. Stop after reporting. Do not start another task automatically.

## Postconditions

- The SDN idempotency fix is either validated on the minimal harness or the
  first failing behavior is reported with exact evidence.
- No broad rebuild-gate commands are run in this task.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/32-run-minimal-build-path-harness-report.md && echo present
cd terraform/lxc/ansible && ansible-lint playbooks/configure-network-sdn-vnet.yml
./with-secrets terragrunt --working-dir terraform/lxc/stacks/net-build-01 apply -auto-approve
./with-secrets bash -lc 'cd /home/steve/git/proxmox-homelab/terraform/lxc && ./validate-build-path.sh'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 32 evidence is present on disk
- `ansible-lint` passes for the SDN playbook
- the repeated `net-build-01` apply does not fail on existing SDN zone/VNet
  objects
- the minimal build-path harness still passes after the repeated apply

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 32 evidence is missing from disk.
- `ansible-lint` fails.
- the repeated `net-build-01` apply still fails on SDN object re-creation.
- the minimal build-path harness fails after the repeated apply.
- Unexpected tracked changes appear outside the scoped files.
