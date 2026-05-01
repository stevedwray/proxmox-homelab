# Task 19a: Integrate Task 19 destroy-helper commit into `dev/pve-test`

## Type

Documentation

## Objective

Integrate the validated Task 19 implementation commit into `dev/pve-test`
without disturbing preserved local workspace hazards or unrelated local
architect package edits.

This is an integration step, not a new implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/19a-integrate-destroy-helper-into-dev-pve-test.md`
- `docs/refactor-remove-portainer/prompts/19a-integrate-destroy-helper-into-dev-pve-test.yaml`

## Preconditions

- Task 19 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/19-stop-first-destroy-helper-report.md`
- Commit `04e2d2cd08488d25d707fd3f000ee3cadb90007e` exists and its scoped diff is
  limited to:
  - `scripts/rebuild-gate-destroy.sh`
  - `docs/refactor-remove-portainer/runbook.md`
- `dev/pve-test` does not yet contain commit `04e2d2c`.
- The current local workspace contains hazards that must be preserved:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
  - local uncommitted architect package updates under
    `docs/refactor-remove-portainer/`
- Do not merge local uncommitted package updates as part of this task.

## Background

Task 19 produced a narrow implementation commit for the stop-first rebuild-gate
destroy helper and updated the runbook to use it.

That implementation is validated and committed on a short-lived branch, but it
is not yet integrated on `dev/pve-test`. The current checkout also includes
local architect-session package edits and preserved hazards that are outside
this integration step.

## Operations

1. Add Task 19a to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the explicit integration-closeout step after Task 19.
2. Preserve the current workspace hazards and local package edits
   non-destructively. Use a separate temporary worktree or another isolation
   method if needed.
3. Cut a clean short-lived branch from `dev/pve-test`.
4. Integrate only commit `04e2d2cd08488d25d707fd3f000ee3cadb90007e` onto that
   clean branch, for example via `git cherry-pick`.
5. Validate that the isolated diff is still limited to:
   - `scripts/rebuild-gate-destroy.sh`
   - `docs/refactor-remove-portainer/runbook.md`
6. Run the required code/YAML scan before merge.
7. Merge the clean short-lived integration branch into `dev/pve-test`.
8. Write the integration report to:
   - `docs/refactor-remove-portainer/reports/19-destroy-helper-integration-report.md`
9. Stop after reporting. Do not retry the rebuild gate in this task.

## Postconditions

- `dev/pve-test` contains the Task 19 stop-first destroy helper commit.
- The integration path carries only the intended scoped diff from `04e2d2c`.
- Local workspace hazards and local architect package edits remain preserved.

## Validation

```bash
git show --stat --oneline 04e2d2cd08488d25d707fd3f000ee3cadb90007e
git diff --name-only dev/pve-test..04e2d2cd08488d25d707fd3f000ee3cadb90007e
./with-secrets /home/steve/.local/bin/sonar-scanner
git merge-base --is-ancestor 04e2d2cd08488d25d707fd3f000ee3cadb90007e dev/pve-test && echo yes || echo no
git status --short --branch
```

Expected outcome:

- preflight confirms the source commit is the narrow Task 19 implementation
  change
- source-only validation proves the integration diff is limited to the helper
  script and runbook
- Sonar reports no new issues
- task-complete validation shows `04e2d2c` is now an ancestor of `dev/pve-test`
- no local architect package updates or unrelated hazards are merged in this
  step

## Stop Conditions

- The current workspace hazards and local package edits cannot be preserved
  without destructive action.
- Commit `04e2d2c` no longer cherry-picks cleanly onto `dev/pve-test`.
- The isolated integration diff widens beyond the helper script and runbook.
- `dev/pve-test` has moved in a way that requires architecture review before
  integrating the destroy-helper commit.
- Sonar reports new issues.
