# Task 03: Implement Traefik Renderer

## Type

Development

## Objective

Render deterministic per-stack Traefik dynamic config from valid edge manifests.

## Scope

- Generate files for local review or dry-run first.
- Later tasks may wire generated files into deployment.
- Do not remove central legacy routes in this task.
- Do not deploy anything unless explicitly requested in a later deployment task.

## Output

Dry-run output should mirror the future runtime layout:

```text
<output-dir>/stacks/<stack>.yml
```

Runtime layout after Task 07:

```text
/opt/proxy-stack/dynamic/stacks/<stack>.yml
```

## Steps

1. Call the manifest validator from Task 02.
2. Render one Traefik dynamic file per stack.
3. Sort routes and services deterministically.
4. Map auth modes:
   - `forwardAuth` -> shared `authentik` middleware
   - `none`, `native`, `oidc` -> no Traefik middleware
5. Render `url` backends as load balancer services.
6. Render `traefikService` backends as direct Traefik service references.
7. Validate generated YAML syntax.
8. Validate semantic references:
   - router service exists or is a Traefik internal service
   - middleware exists when referenced
   - TLS resolver is allowed
9. Detect duplicate host rules against:
   - all generated manifests
   - legacy central proxy routes still present in `deploy-proxy-stack.yml`

## Validation

- Generated YAML parses.
- Duplicate generated hosts fail.
- Host collision with central legacy route fails before migration cleanup.
- Traefik dashboard fixture renders `api@internal` without creating a backend
  load balancer.

## Done When

- A future migration task can render one stack route without editing central
  route templates.

## Stop Conditions

- Stop if generated output would shadow or duplicate a live central route.
