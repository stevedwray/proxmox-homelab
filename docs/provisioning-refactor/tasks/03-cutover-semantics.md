# Task 03: Define Cutover Semantics

## Type

Documentation

## Objective

Fix generated-vs-legacy route collision semantics with an explicit one-host
replacement workflow.

## Files

- `docs/provisioning-refactor/decisions.md`
- `docs/provisioning-refactor/tasks/07-traefik-renderer.md`
- `docs/provisioning-refactor/tasks/15-migrate-authentik.md`
- `docs/provisioning-refactor/tasks/16-migrate-harbor.md`
- `docs/provisioning-refactor/tasks/17-migrate-grafana.md`
- `docs/provisioning-refactor/tasks/18-migrate-portainer.md`
- `docs/provisioning-refactor/tasks/19-migrate-netbox.md`
- `docs/provisioning-refactor/tasks/20-migrate-traefik-dashboard.md`

## Preconditions

- Task 01 complete.

## Operations

1. Renderer dry-run fails on accidental generated-vs-legacy duplicate hosts.
2. A migration task may pass exactly one intended replacement host.
3. Live publish removes the legacy central route and adds the generated route in
   the same deployment unit.
4. Re-run validation must report no duplicate host and no pending changes.

## Postconditions

- Generated route validation can support safe migration without allowing
  duplicate live routers.

## Validation

- `rg -n "intended replacement|same deployment unit|duplicate host" docs/provisioning-refactor`

## Stop Conditions

- Stop if a migration requires more than one host replacement in one task.
