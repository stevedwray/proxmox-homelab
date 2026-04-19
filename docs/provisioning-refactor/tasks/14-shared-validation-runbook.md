# Task 14: Shared Edge Validation Runbook

## Type

Documentation

## Objective

Document shared preflight checks, expected outputs, validation commands, and
rollback for edge reconciliation and route migration tasks.

## Files

- `docs/provisioning-refactor/runbook.md`
- migration task docs if they need runbook references

## Preconditions

- Tasks 11 through 13 complete.

## Operations

1. Document pve-test targeting preflight.
2. Document CoreDNS, MikroTik forwarding, Traefik, and Authentik health checks.
3. Document route validation for DNS, HTTPS, cert, and auth behavior.
4. Document generated snapshot rollback.
5. Document when to stop and present options.

## Postconditions

- Every migration task uses the same validation vocabulary.

## Validation

- Runbook commands are copy-pasteable and include expected outcomes.

## Stop Conditions

- Stop if a validation command mutates live infrastructure.
