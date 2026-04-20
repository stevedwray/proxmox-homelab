# Task 04: Source And Edge Preflight

## Type

Validation

## Objective

Validate source state and regenerate edge outputs before any destructive action.

## Files

- `terraform/lxc/.generated/` (ignored runtime output)
- `docs/teardown-test/runbook.md`

## Preconditions

- Task 03 complete.

## Operations

1. Confirm clean working tree and approved commit.
2. Confirm target guard returns `pve-test`.
3. Run manifest validation and edge unit tests.
4. Remove stale ignored edge outputs.
5. Regenerate Traefik and CoreDNS outputs.
6. Run full edge reconciler dry-run.

## Postconditions

- The test has fresh generated artifacts and source validation evidence.

## Validation

- Commands in runbook sections 0 through 2 pass.

## Stop Conditions

- Stop on dirty working tree, wrong target, stale artifacts that cannot be
  regenerated, failing tests, or failing dry-run.
