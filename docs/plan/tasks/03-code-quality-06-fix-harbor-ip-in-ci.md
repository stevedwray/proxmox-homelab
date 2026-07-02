# 03-code-quality-06 — Fix stale Harbor IP in CI workflow

> Historical task packet.
> This document reflects the earlier CI and branch workflow.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## Phase

Phase 03 — Code Quality and Bug Fixes

## GitHub Issue

Not assigned yet.

## Prerequisites

- Phase 00 complete — branch is clean

## Objective

The `harbor-image-policy` job in `validate.yml` references the old Harbor IP (`192.168.1.10`
on `vmbr0`) in its error message. Harbor is now placed at `10.57.3.10` on `infra_seg`. The
error message must reflect the current address so that developers get actionable guidance
when the policy check fires.

## Scope

- `..github/workflows/validate.yml` — update the error message in the `harbor-image-policy` job
- Branch: `fix/ci-harbor-ip` off `baseline/teardown-validated`

## Out of Scope

- Changing the image reference grep pattern itself
- Any Harbor deployment or network configuration

## Inputs

- `.github/workflows/validate.yml`

## Expected Outputs

- Error message reads `Use 10.57.3.10/... instead.`

## Acceptance Criteria

- [ ] `grep "192.168.1.10" .github/workflows/validate.yml` returns no results
- [ ] The `harbor-image-policy` job error message references `10.57.3.10`
- [ ] `terraform fmt -check -recursive terraform/` still passes
- [ ] Commit merged to `baseline/teardown-validated`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Fix the stale Harbor IP in the CI harbor-image-policy job.

STEP 1 — Create a short-lived branch:
  git checkout -b fix/ci-harbor-ip baseline/teardown-validated

STEP 2 — Read the workflow file:
  Read .github/workflows/validate.yml

STEP 3 — Replace the IP in the error message:
  In the harbor-image-policy job, change the error message from:
    "Use 192.168.1.10/... instead."
  to:
    "Use 10.57.3.10/... instead."

STEP 4 — Verify no other references to 192.168.1.10 remain in CI config:
  grep -r "192.168.1.10" .github/

STEP 5 — Commit and merge:
  git add .github/workflows/validate.yml
  git commit -m "fix(ci): update Harbor IP in harbor-image-policy error message"
  git checkout baseline/teardown-validated && git merge fix/ci-harbor-ip
  git push origin baseline/teardown-validated

DONE WHEN: The harbor-image-policy error message references 10.57.3.10 and no other
192.168.1.10 references remain in the CI config.
```
