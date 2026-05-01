# Task 29: Strip down disposable validation containers on `pve-test`

## Type

Development

## Objective

Remove the disposable validation containers from `pve-test` so the next SDN and
network tasks start from a reduced, intentional baseline rather than from the
leftovers of the earlier broad matrix runs.

This is a cleanup-first execution task, not a rebuild-gate retry and not an SDN
code-change task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/29-strip-down-disposable-validation-containers.md`
- `docs/refactor-remove-portainer/prompts/29-strip-down-disposable-validation-containers.yaml`

## Preconditions

- Task 24 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/24-pve-test-reboot-recovery-report.md`
- Run this rerun from the current architecture-approved package baseline that
  already contains this Task 29 contract revision and the tracked report
  history. Do not cut from an older Task 29 branch snapshot or from a bare
  `origin/dev/pve-test` baseline that does not include those package updates.
- If a clean worktree is used, it must contain the updated tracked package
  artifacts for this task. Local-only execution prerequisites such as
  `with-secrets` and non-secret env files may be borrowed from the original
  checkout, but the Task 29 report must be written inside the executor
  worktree.
- Treat the current live baseline as authoritative:
  - disposable validation CTs `130` through `140` are currently running
  - retained platform CTs `153` (`proxy-stack`) and `154`
    (`monitoring-stack`) are not in scope for removal
- Scope is limited to disposable validation containers:
  - `test-lxc`
  - `test-docker`
  - `net-client-01`
  - `net-service-01`
  - `net-app-01`
  - `net-svc-01`
  - `net-isolated-01`
  - `net-client-02`
  - `net-service-02`
  - `net-build-01`
  - `net-artifacts-01`
- Do not remove or mutate SDN zones/VNets in this task.
- Do not run Sonar or Snyk in this task. This is an exploratory cleanup step,
  not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current architecture-approved
   package baseline for this rerun.
2. Verify `pve-test` targeting and capture the current `pct list`.
3. Destroy only the disposable validation stacks, one explicit command at a
   time, using the stack-local Terragrunt path rather than a broad `run --all`
   command or a single shell loop.
4. If a stack destroy fails before live mutation because of provider or plugin
   init interruption, rerun that same stack destroy once immediately.
5. If a stack destroy still fails because of provider or plugin init,
   missing state, orphaned CTs, or any other inconsistency, stop immediately
   and report the exact stack and error.
6. Re-check `pct list` after the cleanup pass.
7. Write the task report to:
   - `docs/refactor-remove-portainer/reports/29-strip-down-disposable-validation-containers-report.md`
8. Stop after reporting. Do not start Task 30 automatically.

## Postconditions

- The disposable validation CTs are absent from `pve-test`, or the exact first
  blocker is reported.
- Retained platform CTs outside this task scope are unchanged.
- No SDN zone/VNet pruning is attempted in this task.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/24-pve-test-reboot-recovery-report.md && echo present
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/test-lxc" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/test-docker" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-client-01" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-service-01" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-app-01" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-svc-01" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-isolated-01" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-client-02" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-service-02" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-build-01" destroy -auto-approve
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/net-artifacts-01" destroy -auto-approve
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 24 evidence is present on disk
- the executor baseline already contains the updated Task 29 package artifacts
- each disposable validation stack destroy succeeds or cleanly no-ops if it is
  already absent
- if a pre-mutation provider or plugin init failure occurs on a stack, the
  single-stack retry either succeeds or cleanly proves the blocker
- `pct list` no longer contains VMIDs `130` through `140`
- retained CTs outside this task scope remain present
- no code or package files are edited in this task beyond the required report

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 24 evidence is missing from disk.
- The executor baseline does not contain the updated tracked package artifacts
  for this rerun.
- Any disposable stack destroy fails.
- A provider or plugin init failure repeats on the same stack retry.
- A retained non-disposable stack is unexpectedly targeted or affected.
- Unexpected tracked changes appear outside the scoped report artifact.
