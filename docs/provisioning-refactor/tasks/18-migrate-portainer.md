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
3. Run edge reconciler dry-run with `portainer.lab.gibbsgreatly.xyz` as the
   intended replacement host.
4. Reconcile Authentik forward-auth objects if required.
5. Apply generated DNS/Traefik state and remove the central Portainer route in
   the same publish unit.
6. Validate browser route and auth redirect.
7. Re-run reconciler and confirm no-op.

## Postconditions

- Portainer browser UI is gated by forward-auth.
- Portainer API/agent behavior is unchanged.

## Validation

- DNS resolves to `10.57.2.10`.
- Unauthenticated browser request redirects to Authentik.

## Stop Conditions

- Stop if Portainer API or agent behavior regresses.
