# 01-ci-runner-02 — Verify and maintain immutable GitHub Actions pins

## Status

COMPLETE

The active workflow files are already SHA-pinned. This task is retained as a verification
checkpoint for greenfield passes and future workflow edits, not as a pending repository
change.

## Phase

Phase 01 — CI Runner Deployment and Actions Pinning

## Prerequisites

- [01-ci-runner-01 — Deploy and register ci-runner-01 on build_seg](01-ci-runner-01-deploy-ci-runner.md) complete or intentionally skipped for a docs-only pass

## Objective

All GitHub-hosted and self-hosted workflow actions remain pinned to immutable commit SHAs.

## Scope

- Audit `.github/workflows/validate.yml`
- Audit `.github/workflows/security-scan.yml`
- Update any mutable tag pins if found

## Out of Scope

- Adding new workflow jobs
- Supply-chain jobs introduced in Phase 05

## Acceptance Criteria

- [x] No remote `uses:` entries are unpinned
- [x] No `@master` references exist
- [x] Any changed workflow refs are pinned to SHAs and validated

## Session Prompt

```text
This task is already complete. Use it as a verification step when workflows change or
when validating a fresh greenfield pass.

STEP 1 — Audit workflows:
  rg -n 'uses:' .github/workflows

STEP 2 — Check for bad patterns:
  grep -r 'uses:' .github/workflows/ | grep '@master'
  grep -r 'uses:' .github/workflows/ | grep -E '@v[0-9]+$'

STEP 3 — If any mutable tag refs are found, replace them with the correct commit SHA.

DONE WHEN: All workflow action references are commit-SHA pinned.
```
