# Task 06: Implement Authentik Reconciler

## Type

Development

## Objective

Implement idempotent Authentik create/update behavior for stack-owned routes.

## Scope

- Build on Task 05 discovery output.
- Create/update only objects declared by manifests.
- Do not delete Authentik objects by default.
- Do not modify Traefik or DNS.

## Steps

1. Define object ownership naming or labels.
2. Implement dry-run plan output.
3. Implement apply mode for supported objects.
4. Ensure forward-auth routes are associated with the correct outpost.
5. Preserve cookie domain `.lab.gibbsgreatly.xyz`.
6. Prevent Authentik self-protection recursion.
7. Add idempotence tests with mocked API responses.

## Validation

- First apply creates or updates expected objects.
- Second apply is a no-op.
- Authentik route with `auth.mode: none` creates no recursive dependency.
- Deletes are reported but not applied.

## Done When

- Authentik configuration for supported stack routes can be reconciled without
  manual UI drift.

## Stop Conditions

- Stop if an API write would affect an object not owned by this refactor.
