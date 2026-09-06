# 01-ci-runner-03 — Verify CI jobs run on the self-hosted runner

> Historical archived task. Useful for implementation history only.
> Do not use this as the current deployment procedure.
> Current workflow and environment rules live under `docs/workflow/`.

## Status

COMPLETE

The `terraform-validate` and `ansible-lint` jobs in the `Validate` workflow both ran on
`ci-runner-pve-test` after commit `49663c8`. The `Validate` workflow was restored to green
in that commit. Issue #66 closed.

## Phase

Phase 01 — CI Runner Deployment and Actions Pinning

## Prerequisites

- Task 01-02 complete: runner online with correct labels

## Objective

The `terraform-validate` and `ansible-lint` CI jobs show `ci-runner-pve-test` in their run header, not `ubuntu-latest`, and both complete successfully on a push to `dev/pve-test`.

## Scope

- Push a trivial commit to `dev/pve-test`
- Observe GitHub Actions run and verify runner identity in job headers
- Verify runner survives an LXC reboot

## Out of Scope

- Actions pinning (task 01-04)

## Inputs

- `.github/workflows/validate.yml`
- GitHub Actions UI

## Expected Outputs

- No file changes required — verification only

## Constraints and Conventions

- Use `git commit --allow-empty` to avoid dummy code changes
- Only push to `dev/pve-test`, not `main`

## Acceptance Criteria

- [x] `terraform-validate` CI job log header shows `ci-runner-pve-test`
- [x] `ansible-lint` CI job log header shows `ci-runner-pve-test`
- [x] Both jobs complete with exit 0
- [x] Runner comes back online after `reboot` inside the LXC

## Session Prompt

```
This task is COMPLETE. Both CI jobs are running on ci-runner-pve-test and the Validate
workflow is green.

To verify current state, check the most recent Actions run:
  gh run list --branch dev/pve-test --limit 5

No action required.
```
