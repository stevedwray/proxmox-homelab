# Task 00: Normalize Completion State

## Type

Documentation

## Objective

Prepare the repository for teardown/deploy planning by resolving misleading
status metadata and documenting ignored generated artifact handling.

## Files

- `docs/provisioning-refactor/prompts/index.yaml`
- `docs/provisioning-refactor/prompts/*.yaml`
- `docs/teardown-test/README.md`
- `docs/teardown-test/variables.md`

## Preconditions

- None.

## Operations

1. Reconcile provisioning-refactor task statuses with completed implementation
   evidence.
2. Ensure stale ignored `.generated/` artifacts are not treated as source truth.
3. Record the commit SHA selected for the teardown/deploy test in
   `variables.md`.

## Postconditions

- Future agents do not see contradictory task completion state.
- The teardown/deploy test starts from a known source commit.

## Validation

- `python3 -c 'import yaml; yaml.safe_load(open("docs/provisioning-refactor/prompts/index.yaml"))'`
- `git diff --check`

## Stop Conditions

- Stop if task completion cannot be reconciled from commits or evidence.
