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
7. Check for accidental duplicate hosts:
   - Collect all legacy central route hostnames from the live Traefik config.
   - For each generated route, check if its hostname exists in the legacy routes.
   - If a duplicate is found AND there is no `intendedReplacement` flag matching
     this hostname, fail dry-run with an error message naming the collision.
8. Allow exactly one explicit intended replacement per manifest:
   - If `intendedReplacement` is set, validate it exactly matches one generated
     route's hostname.
   - If the hostname matches a legacy central route, allow it in dry-run.
   - If the hostname does not match any legacy route, warn or fail as needed.
   - Fail if multiple hosts are marked as `intendedReplacement`.

## Postconditions

- Generated YAML parses and is deterministic.
- No deployment or central route removal happens in this task.

## Validation

- Renderer tests pass, including:
  - Unit tests for duplicate-host detection fail when expected.
  - Unit tests for `intendedReplacement` validation pass.
- Traefik dashboard fixture renders `api@internal` without a generated
  load-balancer service.
- Dry-run fails with a clear error when a generated route collides with a legacy
  central route without an `intendedReplacement` flag.

## Stop Conditions

- Stop if a generated route would shadow a live central route without an
  explicit `intendedReplacement` flag matching that hostname.
- Stop if more than one `intendedReplacement` host is set in a single manifest.
