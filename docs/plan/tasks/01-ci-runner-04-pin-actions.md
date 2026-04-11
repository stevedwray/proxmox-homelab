# 01-ci-runner-04 — Pin GitHub Actions workflow versions

## Status

COMPLETE

All GitHub Actions in `.github/workflows/` were audited and found to be pinned to stable
release tags (`@v4`, `@v3`, etc.). No `@master` or unpinned refs were found. Issue #71
closed. Note: release-tag pins are mutable; commit-SHA pinning is the next level of
hardening (not yet done).

## Phase

Phase 01 — CI Runner Deployment and Actions Pinning

## Prerequisites

- Task 01-01 complete: repository is in a clean state

## Objective

All `uses:` lines in `.github/workflows/` reference a pinned release tag or commit SHA, and no `@master` or unversioned refs exist.

## Scope

- Audit `.github/workflows/security-scan.yml` and `validate.yml` for unpinned refs
- Pin any `@master` or bare refs to the latest stable release tag
- Verify with grep

## Out of Scope

- Commit-SHA pinning (a future hardening step beyond this phase)
- Adding new workflow jobs (Phase 05)

## Inputs

- `.github/workflows/validate.yml`
- `.github/workflows/security-scan.yml`

## Expected Outputs

- Workflow files updated if any unpinned refs were found (none were in this case)

## Constraints and Conventions

- Release-tag pins (`@v4`) are mutable but acceptable here; commit-SHA pins are the gold standard
- Any pin change must be tested by triggering the workflow

## Acceptance Criteria

- [x] `grep -r 'uses:' .github/workflows/ | grep -v '@'` returns no output
- [x] `grep -r 'uses:' .github/workflows/ | grep '@master'` returns no output
- [x] All actions verified pinned to stable release tags

## Session Prompt

```
This task is COMPLETE. All GitHub Actions in .github/workflows/ are already pinned to
stable release tags. No action needed.

To verify:
  grep -r 'uses:' .github/workflows/ | grep -v '@' | grep -v '#'
  # Expected: no output

  grep -r 'uses:' .github/workflows/ | grep '@master'
  # Expected: no output

Current pin status:
  - actions/checkout        @v4
  - hashicorp/setup-terraform @v3
  - actions/setup-python    @v5
  - actions/cache           @v4
  - aquasecurity/trivy-action @v0.35.0
  - github/codeql-action/upload-sarif @v3
  - snyk/actions/iac        @v1.0.0
  - trufflesecurity/trufflehog @v3.94.3
```
