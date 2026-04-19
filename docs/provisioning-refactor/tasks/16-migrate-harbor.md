# Task 16: Migrate Harbor Route

## Type

Deployment

## Objective

Move `harbor.lab.gibbsgreatly.xyz` to stack-owned provisioning with native
Harbor auth.

## Files

- `terraform/lxc/stacks/harbor-stack/edge.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- generated DNS/Traefik artifacts as applicable

## Preconditions

- Task 15 complete.

## Operations

1. Verify pve-test targeting.
2. Add `harbor-stack/edge.yaml`.
3. Run edge reconciler dry-run with `harbor.lab.gibbsgreatly.xyz` as the
   intended replacement host.
4. Apply generated DNS/Traefik state and remove the central Harbor route in the
   same publish unit.
5. Validate browser route.
6. Validate Docker login/pull/push expectations when in scope.
7. Re-run reconciler and confirm no-op.

## Postconditions

- Harbor browser route works and registry clients are not redirected to
  Authentik.

## Validation

- DNS resolves to `10.57.2.10`.
- No Traefik forward-auth middleware is present.

## Stop Conditions

- Stop if Docker or CI registry clients are redirected to Authentik.
