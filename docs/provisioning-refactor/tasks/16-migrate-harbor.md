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
3. Run edge reconciler dry-run with `harbor.lab.gibbsgreatly.xyz` marked as
   the intended replacement host.
4. Verify dry-run finds no accidental duplicates.
5. Apply generated DNS and Traefik state; remove the central Harbor route in the
   same deployment unit.
6. Validate browser route and Docker login/pull/push expectations.
7. Re-run reconciler and confirm no-op (no pending changes, no duplicate host).

## Postconditions

- Harbor browser route works and registry clients are not redirected to
  Authentik.

## Validation

- DNS resolves to `192.168.30.10`.
- No Traefik forward-auth middleware is present.

## Stop Conditions

- Stop if Docker or CI registry clients are redirected to Authentik.
