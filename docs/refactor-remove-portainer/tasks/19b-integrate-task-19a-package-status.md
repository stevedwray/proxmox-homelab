# Task 19b: Integrate Task 19a package status into `dev/pve-test`

## Type

Documentation

## Objective

Integrate the local package-status update for Task 19a into `dev/pve-test`
without disturbing preserved workspace hazards or reopening the destroy-helper
implementation.

This is a package closeout step, not a new implementation task and not a
rebuild-gate retry.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/19b-integrate-task-19a-package-status.md`
- `docs/refactor-remove-portainer/prompts/19b-integrate-task-19a-package-status.yaml`

## Preconditions

- Task 19a is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/19-destroy-helper-integration-report.md`
- `origin/dev/pve-test` contains the integrated destroy-helper cherry-pick:
  - `18820711b8128c160807479e7a192a5258d88876`
- The local package source of truth now needs to reflect:
  - Task `19a` complete
  - Task `19b` pending as the explicit package-status integration closeout
- The current local workspace contains hazards that must be preserved:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
  - local uncommitted architect package updates under
    `docs/refactor-remove-portainer/`
- Do not retry the rebuild gate in this task.

## Background

Task 19 implemented the stop-first rebuild-gate destroy helper. Task 19a then
integrated that helper onto `origin/dev/pve-test` as commit `1882071`.

The remaining gap is package state: the tracked package registries in the local
architect workspace still show Task 19a as pending. This step closes only that
gap by integrating the narrow status update into `dev/pve-test`.

## Operations

1. Preserve the current workspace hazards and local architect package edits
   non-destructively. Use a separate temporary worktree or another isolation
   method if needed.
2. Refresh or otherwise verify the integration baseline so the clean working
   branch starts from the `dev/pve-test` state that already includes
   `1882071`.
3. Cut a clean short-lived branch from that refreshed `dev/pve-test` baseline.
4. Apply only the narrow package-status diff required to:
   - mark Task `19a` complete in `task-sequence.md`
   - mark `rp-19a-integrate-destroy-helper-into-dev-pve-test` complete in
     `prompts/index.yaml`
   - register Task `19b` / `rp-19b-...` as pending
5. Validate that the isolated diff remains limited to:
   - `docs/refactor-remove-portainer/task-sequence.md`
   - `docs/refactor-remove-portainer/prompts/index.yaml`
6. Run the required YAML/code scan before merge.
7. Merge the clean short-lived branch into `dev/pve-test`.
8. Write the integration report to:
   - `docs/refactor-remove-portainer/reports/19a-status-update-integration-report.md`
9. Stop after reporting. Do not start the rebuild gate in this task.

## Postconditions

- `dev/pve-test` package state reflects Task 19a as complete.
- `dev/pve-test` package state records Task 19b as the package closeout step.
- No destroy-helper code changes are reopened in this step.
- Local workspace hazards remain preserved.

## Validation

```bash
git rev-parse origin/dev/pve-test
git merge-base --is-ancestor 18820711b8128c160807479e7a192a5258d88876 origin/dev/pve-test && echo yes || echo no
git diff --name-only
./with-secrets /home/steve/.local/bin/sonar-scanner
grep -nF '| 19a |' docs/refactor-remove-portainer/task-sequence.md
grep -nF '| 19b |' docs/refactor-remove-portainer/task-sequence.md
grep -n 'rp-19a-integrate-destroy-helper-into-dev-pve-test' -A4 docs/refactor-remove-portainer/prompts/index.yaml
git status --short --branch
```

Expected outcome:

- preflight confirms the integrated destroy-helper baseline is already present
- source-only validation shows only the two package registry files changed
- Sonar reports no new issues
- task-complete validation shows Task 19a marked complete and Task 19b
  registered as pending in package status
- no rebuild-gate commands are executed

## Stop Conditions

- Workspace hazards cannot be preserved non-destructively.
- The integration baseline cannot be verified as containing `1882071`.
- The isolated diff widens beyond the two package registry files.
- `dev/pve-test` has moved in a way that requires architecture review before
  package closeout.
- Sonar reports new issues.
