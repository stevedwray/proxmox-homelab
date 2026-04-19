# Task 09: Migrate NetBox

## Type

Deployment

## Objective

Move `netbox.lab.gibbsgreatly.xyz` to stack-owned provisioning.

## Expected Manifest

- Stack: `netbox-stack`
- Host: `netbox.lab.gibbsgreatly.xyz`
- Backend: `http://10.57.3.12:8080`
- DNS target: `10.57.2.10`
- TLS resolver: `letsencrypt`
- Auth mode: `forwardAuth`

## Steps

1. Verify pve-test targeting.
2. Add `terraform/lxc/stacks/netbox-stack/edge.yaml`.
3. Run manifest validator.
4. Render Traefik config.
5. Render DNS config.
6. Reconcile Authentik if required.
7. Publish generated state.
8. Validate route and auth redirect.
9. Remove only the legacy central NetBox route and service.
10. Re-run validation.

## Validation

- DNS resolves to `10.57.2.10`.
- HTTPS route responds through Traefik.
- Unauthenticated request redirects to Authentik.
- NetBox API credential flow remains available after browser gate.

## Stop Conditions

- Stop if forward-auth creates a loop or blocks expected API access patterns.
