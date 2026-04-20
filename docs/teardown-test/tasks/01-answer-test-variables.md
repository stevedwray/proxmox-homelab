# Task 01: Answer Test Variables

## Type

Documentation

## Objective

Fill the required variables and open questions that gate destructive execution.

## Files

- `docs/teardown-test/variables.md`
- `docs/teardown-test/decisions.md`

## Preconditions

- Task 00 complete.

## Operations

1. Fill execution window and operator approval fields.
2. Confirm branch, commit SHA, target guard, and `with-secrets` availability.
3. Confirm whether disposable validation and `test-*` stacks stay out of scope.
4. Fill resolver contract values.
5. Fill initial stack order proposal for review.

## Postconditions

- No destructive-gate `REQUIRES_OPERATOR_INPUT` or `VERIFY` value remains
  unresolved in `variables.md`.

## Validation

- `rg -n "REQUIRES_OPERATOR_INPUT|VERIFY" docs/teardown-test/variables.md`

## Stop Conditions

- Stop if any destructive-gate variable is unknown.
