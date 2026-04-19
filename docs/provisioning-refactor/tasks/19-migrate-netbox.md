# Task 19: Migrate NetBox Route

## Type

Deployment

## Objective

Move `netbox.lab.gibbsgreatly.xyz` to stack-owned provisioning with Authentik
forward-auth.

## Files

- `terraform/lxc/stacks/netbox-stack/edge.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- generated DNS/Traefik/Auth artifacts as applicable

## Preconditions

- Task 18 complete.

## Operations

1. Verify pve-test targeting.
2. Add `netbox-stack/edge.yaml`.
3. Run edge reconciler dry-run with `netbox.lab.gibbsgreatly.xyz` marked as
   the intended replacement host.
4. Verify dry-run finds no accidental duplicates.
5. Reconcile Authentik forward-auth objects if required.
6. Apply generated DNS and Traefik state; remove the central NetBox route in the
   same deployment unit.
7. Validate browser route, auth redirect, and API credential flow.
8. Re-run reconciler and confirm no-op (no pending changes, no duplicate host).

## Postconditions

- NetBox browser UI is gated by forward-auth.
- NetBox API credential flow remains usable.

## Validation

- DNS resolves to `10.57.2.10`.
- Unauthenticated browser request redirects to Authentik.

## Stop Conditions

- Stop if forward-auth blocks expected API access patterns.
