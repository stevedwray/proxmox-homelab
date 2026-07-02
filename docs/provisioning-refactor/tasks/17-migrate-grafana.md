# Task 17: Migrate Grafana Route

## Type

Deployment

## Objective

Move `grafana.lab.gibbsgreatly.xyz` to stack-owned provisioning while preserving
Grafana native OIDC.

## Files

- `terraform/lxc/stacks/monitoring-stack/edge.yaml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- generated DNS/Traefik artifacts as applicable

## Preconditions

- Task 15 complete.

## Operations

1. Verify pve-test targeting.
2. Add or update `monitoring-stack/edge.yaml`.
3. Run edge reconciler dry-run with `grafana.lab.gibbsgreatly.xyz` marked as
   the intended replacement host.
4. Verify dry-run finds no accidental duplicates.
5. Apply generated DNS and Traefik state; remove the central Grafana route in
   the same deployment unit.
6. Validate browser route and Grafana OIDC redirect.
7. Re-run reconciler and confirm no-op (no pending changes, no duplicate host).

## Postconditions

- Grafana uses native OIDC and has no Traefik forward-auth middleware.

## Validation

- DNS resolves to `192.168.30.10`.
- No double-auth loop occurs.

## Stop Conditions

- Stop if Grafana is protected by both forward-auth and OIDC.
