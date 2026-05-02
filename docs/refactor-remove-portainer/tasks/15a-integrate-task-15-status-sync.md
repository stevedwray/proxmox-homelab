# Task 15a: Integrate Task 15 package status into `dev/pve-test`

## Type

Documentation

## Objective

Integrate the validated Task 15 package-status commit into `dev/pve-test`
without bringing along unrelated router work from the current
`chore/task-15-status-sync` branch.

This is an integration step, not a new implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/15a-integrate-task-15-status-sync.md`
- `docs/refactor-remove-portainer/prompts/15a-integrate-task-15-status-sync.yaml`

## Preconditions

- Task 15 evidence is already complete and recorded locally in:
  - `docs/refactor-remove-portainer/reports/15-triage-storage-lock-contention-report.md`
  - `docs/refactor-remove-portainer/reports/15-report-correction-report.md`
  - `docs/refactor-remove-portainer/reports/15-status-update-report.md`
  - `docs/refactor-remove-portainer/reports/15-status-update-closeout-report.md`
- `dev/pve-test` still reflects the integrated Task 14 package state and does
  not yet include the Task 15 status-sync commit.
- Commit `de717554a3f91a9261bd6b40e7586d4405144d4e` exists and its scoped diff is
  limited to:
  - `docs/refactor-remove-portainer/task-sequence.md`
  - `docs/refactor-remove-portainer/prompts/index.yaml`
- The current local workspace contains hazards that must be preserved:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
- Do not merge `chore/task-15-status-sync` wholesale. That branch now contains
  unrelated router commits after `de71755`.

## Background

The package status for Task 15 was validated and committed, but that commit was
left on a short-lived branch that later accumulated unrelated router changes.

This task closes only the "validated but not integrated" gap. It must land the
existing status-sync commit on `dev/pve-test` without reopening Task 15 triage,
without starting host stale-lock cleanup, and without retrying the rebuild
gate.

## Operations

1. Add Task 15a to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the explicit integration-closeout step after Task 15.
2. Preserve the current workspace hazards. Use a separate temporary worktree or
   another non-destructive isolation method if needed so the modified secrets
   file and untracked architect notes remain untouched.
3. Cut a clean short-lived branch from `dev/pve-test` for this integration
   step.
4. Integrate only commit `de717554a3f91a9261bd6b40e7586d4405144d4e` onto that
   clean branch, for example via `git cherry-pick`.
5. Validate that the isolated diff is still limited to:
   - `docs/refactor-remove-portainer/task-sequence.md`
   - `docs/refactor-remove-portainer/prompts/index.yaml`
6. Run the required YAML/code scan before merge.
7. Merge the clean short-lived integration branch into `dev/pve-test`.
8. Write the integration report to:
   - `docs/refactor-remove-portainer/reports/15-status-update-integration-report.md`
9. Stop after reporting. Do not start host lock cleanup or rebuild-gate retry
   in this task.

## Postconditions

- `dev/pve-test` contains the Task 15 package-status update.
- The integration path carries only the intended scoped diff from `de71755`.
- Local workspace hazards remain preserved.
- The package is no longer in the "validated but not integrated" state for
  Task 15.

## Validation

```bash
git show --stat --oneline de717554a3f91a9261bd6b40e7586d4405144d4e
git log --oneline dev/pve-test..chore/task-15-status-sync
git diff --name-only e250e6f330f35a18fa3488e75620672ddf8b3058..de717554a3f91a9261bd6b40e7586d4405144d4e
./with-secrets /home/steve/.local/bin/sonar-scanner
git merge-base --is-ancestor de717554a3f91a9261bd6b40e7586d4405144d4e dev/pve-test && echo yes || echo no
grep -nF '| 15 |' docs/refactor-remove-portainer/task-sequence.md
grep -n 'rp-15-triage-storage-lock-contention' -A4 docs/refactor-remove-portainer/prompts/index.yaml
git status --short --branch
```

Expected outcome:

- preflight confirms the source commit is the narrow Task 15 status-sync change
- source-only validation proves the original branch is polluted beyond
  `de71755`, so wholesale merge is not allowed
- Sonar reports no new issues
- task-complete validation shows `de71755` is now an ancestor of
  `dev/pve-test`
- package status on `dev/pve-test` shows Task 15 complete
- no router files or other unrelated changes are present in the integration
  path

## Stop Conditions

- The current workspace hazards cannot be preserved without destructive action.
- Commit `de71755` no longer cherry-picks cleanly onto `dev/pve-test`.
- The isolated integration diff includes router files or any other out-of-scope
  changes.
- `dev/pve-test` has moved in a way that requires architecture review before
  integrating the status-sync commit.
- Sonar reports new issues.
