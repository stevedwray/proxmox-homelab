# Task 21: Final Cutover Cleanup

## Type

Deployment

## Objective

Remove remaining central per-service route ownership and validate the
stack-owned model end to end.

## Files

- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- `docs/provisioning-refactor/tasks/21-final-cutover-cleanup.md`
- `docs/provisioning-refactor/runbook.md`

## Preconditions

- Tasks 15 through 20 complete.

## Operations

1. Verify all six service manifests exist.
2. Run manifest validator.
3. Run edge reconciler dry-run for all manifests.
4. Confirm central Traefik config contains only runtime, certificate, provider,
   default store, and shared middleware config.
5. Deploy generated state if not already current.
6. Validate all DNS records, HTTPS routes, certificates, and auth behavior.
7. Document and test rollback from the previous generated snapshot.

## Postconditions

- No central per-service browser route ownership remains.
- Stack-owned manifests are the default path for future browser services.

## Validation

- All six browser hosts resolve to `10.57.2.10`.
- Reconciler second run is a no-op.

## Stop Conditions

- Stop if any route, DNS record, certificate, or auth behavior regresses.
