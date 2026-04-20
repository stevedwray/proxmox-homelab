# Task 06: Foundation Redeploy

## Type

Deployment

## Objective

Rebuild Stage 1/2 foundation services needed by later stacks.

## Files

- `docs/teardown-test/variables.md`
- `docs/teardown-test/runbook.md`
- `terraform/lxc/stacks/<selected>/stack.yaml` (read-only)

## Preconditions

- Task 05 complete.

## Operations

1. Deploy foundation stacks in approved order.
2. Validate Portainer direct access.
3. Validate Harbor direct registry path and robot credential policy.
4. Validate apt-cacher if included.
5. Validate CI runner registration if included.

## Postconditions

- Foundation services needed for Stage 3a and Stage 3b are healthy.

## Validation

- Stack-specific direct health checks pass.
- Harbor `/v2/` returns native registry auth challenge.

## Stop Conditions

- Stop if Harbor, Portainer, CI runner, or apt-cacher does not reach its
  approved foundation exit condition.
