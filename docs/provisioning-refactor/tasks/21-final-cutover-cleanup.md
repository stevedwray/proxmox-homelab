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

1. Verify all six service manifests exist in `terraform/lxc/stacks/*/edge.yaml`.
2. Run manifest validator and confirm all pass.
3. Run edge reconciler dry-run for all manifests.
4. Verify dry-run output contains NO `intendedReplacement` flags (all migrations
   completed and flags removed).
5. Verify dry-run finds NO accidental host collisions with central Traefik config.
6. Confirm central Traefik config contains only runtime, entrypoint, certificate
   provider, default store, and shared middleware config; no per-service routes.
7. Deploy generated state from step 3 if not already current.
8. Validate all six DNS records, HTTPS routes, certificates, and auth behavior.
9. Re-run edge reconciler dry-run and confirm no-op (no pending changes, no
   duplicates).
10. Document and test rollback from the previous generated snapshot.

## Postconditions

- No central per-service browser route ownership remains.
- Stack-owned manifests are the default path for future browser services.

## Validation

- All six browser hosts resolve to `192.168.30.10`.
- Renderer dry-run output contains NO `intendedReplacement` flags.
- Renderer dry-run reports NO duplicate hosts between generated and central
  routes.
- Reconciler second dry-run is a complete no-op (no pending changes).
- All six services are accessible via their browser hostnames.
- Certificate, DNS, and authentication behavior are correct for each service.
- Rollback from the previous snapshot completes and is tested.

## Stop Conditions

- Stop if any route, DNS record, certificate, or auth behavior regresses.
