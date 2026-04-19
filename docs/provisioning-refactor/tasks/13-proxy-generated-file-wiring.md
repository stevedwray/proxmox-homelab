# Task 13: Proxy Generated File Wiring

## Type

Development

## Objective

Prepare the proxy deployment workflow to load generated per-stack dynamic files
while keeping shared middleware central and legacy routes in place.

## Files

- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`

## Preconditions

- Task 07 complete.

## Operations

1. Ensure `/opt/proxy-stack/dynamic/stacks` exists.
2. Ensure Traefik file provider watches generated files.
3. Keep shared `authentik` middleware in central dynamic config.
4. Do not remove any per-service legacy route in this task.
5. Validate file readability by the Traefik container.

## Postconditions

- Migration tasks can publish one stack's generated route safely.

## Validation

- YAML parses.
- `docker compose config -q` still succeeds for the proxy stack.

## Stop Conditions

- Stop if generated files fail Traefik validation or collide with legacy routes.
