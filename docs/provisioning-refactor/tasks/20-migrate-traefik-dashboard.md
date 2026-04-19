# Task 20: Migrate Traefik Dashboard

## Type

Deployment

## Objective

Move `traefik.lab.gibbsgreatly.xyz` to stack-owned provisioning using
`api@internal` and forward-auth.

## Files

- `terraform/lxc/stacks/proxy-stack/edge.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- generated DNS/Traefik/Auth artifacts as applicable

## Preconditions

- Tasks 18 and 19 complete.

## Operations

1. Verify pve-test targeting.
2. Add or update `proxy-stack/edge.yaml`.
3. Run edge reconciler dry-run with `traefik.lab.gibbsgreatly.xyz` as the
   intended replacement host.
4. Confirm renderer uses `api@internal` directly.
5. Apply generated DNS/Traefik state and remove the central dashboard route in
   the same publish unit.
6. Validate dashboard route and Authentik redirect.
7. Re-run reconciler and confirm no-op.

## Postconditions

- Dashboard route is generated from `proxy-stack/edge.yaml`.
- All previously migrated routes still work.

## Validation

- DNS resolves to `10.57.2.10`.
- Dashboard route uses `api@internal`.

## Stop Conditions

- Stop if Traefik rejects generated dynamic config.
