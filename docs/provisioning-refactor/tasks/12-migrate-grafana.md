# Task 12: Migrate Grafana

## Type

Deployment

## Objective

Move `grafana.lab.gibbsgreatly.xyz` to stack-owned provisioning while preserving
Grafana native OIDC.

## Expected Manifest

- Stack: `monitoring-stack`
- Host: `grafana.lab.gibbsgreatly.xyz`
- Backend: `http://10.57.1.12:3000`
- DNS target: `10.57.2.10`
- TLS resolver: `letsencrypt`
- Auth mode: `oidc`

## Steps

1. Verify pve-test targeting.
2. Add `terraform/lxc/stacks/monitoring-stack/edge.yaml` or append the Grafana
   route if the stack already owns one.
3. Run manifest validator.
4. Render Traefik config.
5. Render DNS config.
6. Confirm no Traefik forward-auth is applied.
7. Publish generated state.
8. Validate browser route and Grafana OIDC redirect.
9. Remove only the legacy central Grafana route and service.
10. Re-run validation.

## Validation

- DNS resolves to `10.57.2.10`.
- Browser route reaches Grafana.
- Grafana performs native OIDC behavior.
- No double-auth loop occurs.

## Stop Conditions

- Stop if Grafana is protected by both Traefik forward-auth and Grafana OIDC.
