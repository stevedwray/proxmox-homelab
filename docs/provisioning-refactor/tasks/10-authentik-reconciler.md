# Task 10: Authentik Reconciler

## Type

Development

## Objective

Implement create/update-only Authentik reconciliation for stack-owned routes.

## Files

- `terraform/lxc/reconcile-authentik-edge.py`
- tests with mocked API responses

## Preconditions

- Task 09 complete.

## Operations

1. Define object ownership labels or names.
2. Implement dry-run plan output.
3. Implement create/update apply mode for supported objects.
4. Associate forward-auth routes with the correct outpost.
5. Preserve cookie domain `.lab.gibbsgreatly.xyz`.
6. Prevent Authentik self-protection recursion.
7. Report deletes but do not apply them.

## Postconditions

- First apply creates or updates expected objects.
- Second apply is a no-op.

## Validation

- Mocked API tests prove idempotence and no-delete behavior.

## Stop Conditions

- Stop if an API write would affect an object not owned by this refactor.
