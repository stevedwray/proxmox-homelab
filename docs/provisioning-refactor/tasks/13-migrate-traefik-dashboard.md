# Task 13: Migrate Traefik Dashboard

## Type

Deployment

## Objective

Move `traefik.lab.gibbsgreatly.xyz` to stack-owned provisioning using the
special Traefik internal service target.

## Expected Manifest

- Stack: `proxy-stack`
- Host: `traefik.lab.gibbsgreatly.xyz`
- Backend type: `traefikService`
- Backend value: `api@internal`
- DNS target: `10.57.2.10`
- TLS resolver: `letsencrypt`
- Auth mode: `forwardAuth`

## Steps

1. Verify pve-test targeting.
2. Add `terraform/lxc/stacks/proxy-stack/edge.yaml` or append the dashboard route
   if the stack already owns one.
3. Run manifest validator.
4. Render Traefik config.
5. Confirm renderer does not create a load-balancer backend for `api@internal`.
6. Render DNS config.
7. Reconcile Authentik if required.
8. Publish generated state.
9. Validate dashboard route and Authentik redirect.
10. Remove only the legacy central Traefik dashboard route.
11. Re-run validation.

## Validation

- DNS resolves to `10.57.2.10`.
- Dashboard route uses `api@internal`.
- Unauthenticated request redirects to Authentik.
- Existing migrated routes still work.

## Stop Conditions

- Stop if Traefik rejects the generated dynamic config.
