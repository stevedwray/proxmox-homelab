# Task 11: Evidence And Follow-Up Closeout

## Type

Documentation

## Objective

Capture the test result and any follow-up work without mixing runtime evidence
into source control accidentally.

## Files

- `docs/teardown-test/README.md`
- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`
- optional summary document under `docs/teardown-test/results/`

## Preconditions

- Task 10 complete.

## Operations

1. Summarize commit, scope, start/end time, and operator.
2. Summarize destroy, deploy, and validation results.
3. List evidence directory path.
4. Record follow-ups such as local lab CA trust, dependency-order fixes, or
   backup improvements.
5. Ensure large runtime snapshots remain ignored unless explicitly requested.

## Postconditions

- The rehearsal has a durable summary and a clear follow-up list.

## Validation

- `git status --short`
- `git diff --check`

## Stop Conditions

- Stop if evidence contains secrets or large runtime data that would be
  accidentally committed.
