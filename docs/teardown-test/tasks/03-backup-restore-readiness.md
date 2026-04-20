# Task 03: Backup And Restore Readiness

## Type

Operational planning

## Objective

Gate destructive work on explicit backup, restore, or accepted data-loss policy.

## Files

- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`

## Preconditions

- Task 02 complete.

## Operations

1. For every selected persistent service, record backup source and restore
   procedure.
2. Run or verify a restore dry-run where practical.
3. Mark data loss acceptable only with explicit operator approval.
4. Record backup IDs/paths in the evidence directory.

## Postconditions

- Destruction is blocked unless persistent-state policy is explicit.

## Validation

- `rg -n "REQUIRES_OPERATOR_INPUT|VERIFY" docs/teardown-test/variables.md`

## Stop Conditions

- Stop if any selected persistent service lacks both backup/restore confidence
  and explicit data-loss approval.
