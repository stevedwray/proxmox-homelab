# Task 10: End-To-End Validation

## Type

Validation

## Objective

Prove the rebuilt platform satisfies the expected service, DNS, auth, and edge
convergence contracts.

## Files

- `docs/teardown-test/runbook.md`
- `docs/teardown-test/variables.md`

## Preconditions

- Task 09 complete.

## Operations

1. Validate all selected LXCs are present at expected VMIDs and IPs.
2. Validate browser DNS through authoritative and delegated resolvers.
3. Validate HTTPS/certificate behavior for all six browser routes.
4. Validate Authentik, Harbor, Grafana, Portainer, NetBox, and Traefik dashboard
   behavior.
5. Run full edge reconciler dry-run with no manifest arguments.
6. Run selected network validation scripts if in scope.

## Postconditions

- The teardown/deploy test has objective pass/fail evidence.

## Validation

- Commands in runbook section 10 pass.

## Stop Conditions

- Stop if the final reconciler dry-run is not clean or any service fails its
  expected behavior.
