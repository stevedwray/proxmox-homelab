# Task 09: Remaining Platform Redeploy

## Type

Deployment

## Objective

Deploy the selected Stage 3b platform stacks after edge state is active.

## Files

- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`
- selected `terraform/lxc/stacks/*/stack.yaml`

## Preconditions

- Task 08 complete.

## Operations

1. Deploy remaining selected stacks in approved dependency order.
2. Validate direct service health after each deploy.
3. Validate browser route behavior for browser-facing services.
4. Re-run full edge dry-run after each browser-facing service if useful.

## Postconditions

- Selected platform scope is fully redeployed.

## Validation

- Stack-specific health checks pass.
- Browser routes remain consistent with `edge.yaml`.

## Stop Conditions

- Stop if a stack depends on a service that is not yet deployed or if a route
  regresses after a stack deploy.
