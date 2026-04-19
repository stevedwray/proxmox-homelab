# Task 07: Wire Proxy Deployment To Generated Files

## Type

Development

## Objective

Update the proxy deployment workflow to publish generated per-stack Traefik
dynamic files.

## Scope

- Functional code changes happen in this future task, not in the planning task.
- Keep central Traefik config limited to shared runtime/middleware/cert config.
- Do not remove service-specific central routes except through migration tasks.

## Steps

1. Ensure the proxy playbook creates `/opt/proxy-stack/dynamic/stacks`.
2. Add a safe publish step for generated files.
3. Preserve existing `dynamic/authentik.yml` shared middleware while routes are
   being migrated.
4. Validate file-provider watch behavior.
5. Add dry-run mode or local render validation before publish.
6. Ensure generated files are readable by the Traefik container.

## Validation

- Traefik sees files under `/etc/traefik/dynamic/stacks`.
- Central shared middleware still works.
- No central legacy route is removed in this task.
- No generated route duplicates a legacy route.

## Done When

- Migration tasks can publish one stack's generated route safely.

## Stop Conditions

- Stop if generated files fail Traefik validation or collide with legacy routes.
