# Task 05: Destroy Rehearsal Execution

## Type

Destructive execution

## Objective

Destroy the approved pve-test stack set in a controlled order and verify absence.

## Files

- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`
- evidence directory under `docs/teardown-test/evidence/` (ignored if configured)

## Preconditions

- Task 04 complete.
- Explicit operator approval for destructive work.

## Operations

1. Re-run target guard.
2. Announce stack list and rollback deadline.
3. Destroy stacks in reverse approved dependency order.
4. Verify selected VMIDs are absent.
5. Preserve destroy output in evidence.

## Postconditions

- Approved stack set is absent from pve-test.
- No unapproved VMID was destroyed.

## Validation

- `pct list` on `pve-test` shows selected VMIDs absent.

## Stop Conditions

- Stop if target guard fails, a destroy command targets an unapproved stack, or
  any selected stack cannot be destroyed cleanly.
