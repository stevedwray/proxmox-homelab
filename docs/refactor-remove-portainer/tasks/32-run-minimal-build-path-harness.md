# Task 32: Run the minimal build-path harness on `pve-test`

## Type

Development

## Objective

Deploy only the first cleanup-first minimal harness and validate one concrete
path on `pve-test` before any broader SDN retry work resumes.

The harness scope is:

- `net-build-01`
- `net-artifacts-01`
- `net-client-01`

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/32-run-minimal-build-path-harness.md`
- `docs/refactor-remove-portainer/prompts/32-run-minimal-build-path-harness.yaml`
- `terraform/lxc/validate-build-path.sh`
- `terraform/lxc/ansible/playbooks/validate-build-path.yml`

## Preconditions

- Task 30 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md`
- Task 31 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/31-add-minimal-build-path-validation-harness-report.md`
- The minimal harness assets from Task 31 are available on the execution
  branch.
- Do not run Sonar or Snyk in this task. This is an exploratory validation
  step, not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current `origin/dev/pve-test`
   baseline that includes the Task 31 harness assets.
2. Apply only:
   - `net-build-01`
   - `net-artifacts-01`
   - `net-client-01`
3. Run the minimal build-path validation harness.
4. Leave the minimal harness containers running if validation passes, so the
   next SDN idempotency task can reuse them.
5. Write the task report to:
   - `docs/refactor-remove-portainer/reports/32-run-minimal-build-path-harness-report.md`
6. Stop after reporting. Do not start Task 33 automatically.

## Postconditions

- The minimal build-path harness is live and validated, or the first blocker is
  clearly reported.
- The task proves a narrow connectivity/firewall/port path without reintroducing
  the broad nine-container matrix.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md && echo present
test -f docs/refactor-remove-portainer/reports/31-add-minimal-build-path-validation-harness-report.md && echo present
for stack in net-build-01 net-artifacts-01 net-client-01; do
  ./with-secrets terragrunt --working-dir "terraform/lxc/stacks/${stack}" apply -auto-approve
done
./with-secrets bash -lc 'cd /home/steve/git/proxmox-homelab/terraform/lxc && ./validate-build-path.sh'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Tasks 30 and 31 evidence are present on disk
- only the three build-path harness stacks are applied
- the minimal harness reports the expected allow/deny behavior
- the harness containers remain available for Task 33 if validation passes

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 30 or Task 31 evidence is missing from disk.
- Any stack apply in the minimal harness fails.
- The minimal harness reports an unexpected connectivity result.
- Unexpected tracked changes appear outside the scoped report artifact.
