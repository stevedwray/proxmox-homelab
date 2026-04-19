# Task 15: Migrate Authentik Route

## Type

Deployment

## Objective

Move `authentik.lab.gibbsgreatly.xyz` to stack-owned provisioning with
`auth.mode: none`.

## Files

- `terraform/lxc/stacks/authentik-stack/edge.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- generated DNS/Traefik artifacts as applicable

## Preconditions

- Tasks 11 through 14 complete.
- Authentik is healthy via direct IP.
- Authentik API token is stored in SOPS.

## Operations

1. Verify pve-test targeting.
2. Add `authentik-stack/edge.yaml` with `auth.mode: none`.
3. Run edge reconciler dry-run with `authentik.lab.gibbsgreatly.xyz` marked as
   the intended replacement host.
4. Verify dry-run finds no accidental duplicates.
5. Apply generated DNS and Traefik state; remove the central Authentik route in
   the same deployment unit.
6. Validate browser route through Traefik.
7. Confirm no forward-auth middleware or self-protection object exists.
8. Re-run reconciler and confirm no-op (no pending changes, no duplicate host).

## Postconditions

- Authentik routes through Traefik without recursion.

## Validation

- DNS resolves to `10.57.2.10`.
- HTTPS returns Authentik response via Traefik.
- No `authentik` middleware is attached to the Authentik route.

## Stop Conditions

- Stop if Authentik redirects to itself in a loop.
