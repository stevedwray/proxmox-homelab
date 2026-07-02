# Task 02: Define DNS Ownership Transition

## Type

Documentation

## Objective

Specify CoreDNS seed records versus generated browser records, including
one-host-at-a-time replacement of direct/static browser records during
migration.

## Files

- `docs/provisioning-refactor/decisions.md`
- `docs/provisioning-refactor/tasks/08-coredns-renderer.md`

## Preconditions

- Task 01 complete.

## Operations

1. Define seed/non-browser records as bootstrap-owned.
2. Define generated browser records as manifest-owned.
3. Require generated browser records to target `10.57.2.10`.
4. Require migration to replace only one hostname at a time.

## Postconditions

- DNS renderer implementation can distinguish bootstrap seed records from
  generated browser edge records.
- No task treats MikroTik static records as the long-term browser record store.

## Validation

- `rg -n "10.57.2.10|seed|generated browser|MikroTik static" docs/provisioning-refactor`

## Stop Conditions

- Stop if a service requires the same hostname to be both a direct internal
  identity and browser edge identity without a documented exception.
