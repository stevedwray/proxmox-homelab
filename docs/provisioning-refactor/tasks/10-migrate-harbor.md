# Task 10: Migrate Harbor

## Type

Deployment

## Objective

Move `harbor.lab.gibbsgreatly.xyz` to stack-owned provisioning while preserving
Harbor native auth and registry clients.

## Expected Manifest

- Stack: `harbor-stack`
- Host: `harbor.lab.gibbsgreatly.xyz`
- Backend: `http://10.57.3.10`
- DNS target: `10.57.2.10`
- TLS resolver: `letsencrypt`
- Auth mode: `native`

## Steps

1. Verify pve-test targeting.
2. Add `terraform/lxc/stacks/harbor-stack/edge.yaml`.
3. Run manifest validator.
4. Render Traefik config.
5. Render DNS config.
6. Confirm no Authentik forward-auth is applied.
7. Publish generated state.
8. Validate browser route.
9. Validate Docker login/pull/push expectations if in scope.
10. Remove only the legacy central Harbor route and service.
11. Re-run validation.

## Validation

- DNS resolves to `10.57.2.10`.
- Browser route reaches Harbor.
- No Traefik forward-auth middleware is present.
- Robot accounts and registry clients are not forced through Authentik.

## Stop Conditions

- Stop if Docker or CI registry clients are redirected to Authentik.
