# Task 11: Edge Reconciler

## Type

Development

## Objective

Add one operator command that runs edge preflight, validation, rendering, plan,
and optional apply.

## Files

- `terraform/lxc/reconcile-edge.py`
- focused tests
- `docs/provisioning-refactor/README.md`

## Preconditions

- Tasks 07 through 10 complete.

## Operations

1. Default to dry-run.
2. Run pve-test targeting preflight.
3. Run manifest validation.
4. Render Traefik and CoreDNS outputs.
5. Run Authentik discovery/reconcile only when selected routes require it.
6. In apply mode, require explicit `--apply` and healthy CoreDNS/Traefik checks.
7. Support one explicit intended replacement host for migration tasks.

## Postconditions

- Operators have one clear entrypoint for edge dry-run and apply.

## Validation

- Tests cover dry-run default, apply preflight failure, no-op result, and
  intended replacement host behavior.

## Stop Conditions

- Stop if the edge reconciler would need to mutate Terraform state.
