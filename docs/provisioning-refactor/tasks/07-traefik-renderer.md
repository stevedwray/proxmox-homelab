# Task 07: Traefik Renderer

## Type

Development

## Objective

Render deterministic per-stack Traefik dynamic config from validated manifests.

## Files

- `terraform/lxc/render-edge-traefik.py`
- focused renderer tests

## Preconditions

- Tasks 05 and 06 complete.

## Operations

1. Call the manifest validator before rendering.
2. Render one file per stack under a dry-run output directory.
3. Map `forwardAuth` to the shared `authentik` middleware.
4. Map `none`, `native`, and `oidc` to no Traefik middleware.
5. Render `url` backends as load-balancer services.
6. Render `traefikService` backends as direct Traefik service references.
7. Fail on generated duplicate hosts and accidental legacy collisions.
8. Allow exactly one explicit intended replacement host for migration dry-runs.

## Postconditions

- Generated YAML parses and is deterministic.
- No deployment or central route removal happens in this task.

## Validation

- Renderer tests pass.
- Traefik dashboard fixture renders `api@internal` without a generated
  load-balancer service.

## Stop Conditions

- Stop if output would shadow a live central route without an intended
  replacement flag.
