# Task 18: Migrate Portainer Route

## Type

Deployment

## Objective

Move `portainer.lab.gibbsgreatly.xyz` to stack-owned provisioning with
Authentik forward-auth.

## Files

- `terraform/lxc/stacks/portainer-stack/edge.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- generated DNS/Traefik/Auth artifacts as applicable

## Preconditions

- Task 15 complete.
- Forward-auth provider/outpost reconciliation works.

## Operations

1. Verify pve-test targeting.
2. Add `portainer-stack/edge.yaml`.
3. Run edge reconciler dry-run with `portainer.lab.gibbsgreatly.xyz` marked as
   the intended replacement host.
4. Verify dry-run finds no accidental duplicates.
5. Reconcile Authentik forward-auth objects if required.
6. Apply generated DNS and Traefik state; remove the central Portainer route in
   the same deployment unit.
7. Validate browser route and auth redirect.
8. Re-run reconciler and confirm no-op (no pending changes, no duplicate host).

## Postconditions

- Portainer browser UI is gated by forward-auth.
- Portainer API/agent behavior is unchanged.

## Validation

- DNS resolves to `10.57.2.10`.
- Unauthenticated browser request redirects to Authentik.

## Stop Conditions

- Stop if Portainer API or agent behavior regresses.
