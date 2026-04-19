# Task 14: Final Cutover Cleanup

## Type

Deployment

## Objective

Remove remaining legacy central route ownership and validate the stack-owned
model end to end.

## Scope

- Runs only after Tasks 08 through 13 are complete.
- Remove service-specific central route/service stanzas.
- Keep shared middleware and runtime config centrally owned.

## Steps

1. Verify all six service manifests exist.
2. Run manifest validator.
3. Render Traefik config for all manifests.
4. Render DNS config for all manifests.
5. Run Authentik drift/reconcile checks.
6. Confirm no central per-service routers remain.
7. Deploy generated state if not already current.
8. Validate all browser routes.
9. Validate all DNS records.
10. Validate expected auth behavior.
11. Document rollback procedure from previous generated snapshot.

## Validation Matrix

| Host | Expected Auth |
| --- | --- |
| `authentik.lab.gibbsgreatly.xyz` | none |
| `portainer.lab.gibbsgreatly.xyz` | forwardAuth |
| `harbor.lab.gibbsgreatly.xyz` | native |
| `netbox.lab.gibbsgreatly.xyz` | forwardAuth |
| `grafana.lab.gibbsgreatly.xyz` | oidc |
| `traefik.lab.gibbsgreatly.xyz` | forwardAuth |

## Done When

- No central per-service route ownership remains.
- Stack-owned manifests are the default path for future browser services.
- Rollback is documented and tested.

## Stop Conditions

- Stop if any route, DNS record, certificate, or auth behavior regresses.
