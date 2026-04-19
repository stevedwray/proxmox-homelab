# Task 11: Migrate Authentik

## Type

Deployment

## Objective

Move `authentik.lab.gibbsgreatly.xyz` to stack-owned provisioning without
creating an auth recursion loop.

## Expected Manifest

- Stack: `authentik-stack`
- Host: `authentik.lab.gibbsgreatly.xyz`
- Backend: `http://10.57.1.10:9000`
- DNS target: `10.57.2.10`
- TLS resolver: `letsencrypt`
- Auth mode: `none`

## Steps

1. Verify pve-test targeting.
2. Add `terraform/lxc/stacks/authentik-stack/edge.yaml`.
3. Run manifest validator.
4. Render Traefik config.
5. Render DNS config.
6. Confirm Authentik reconciler creates no self-protection objects.
7. Publish generated state.
8. Validate browser route.
9. Remove only the legacy central Authentik route and service.
10. Re-run validation.

## Validation

- DNS resolves to `10.57.2.10`.
- Authentik route responds via Traefik.
- No `authentik` forward-auth middleware is attached to Authentik route.
- Existing forward-auth outpost still works for already migrated services.

## Stop Conditions

- Stop if Authentik redirects to itself in a loop.
