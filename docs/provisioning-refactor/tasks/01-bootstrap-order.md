# Task 01: Document Edge Bootstrap Order

## Type

Documentation

## Objective

Document Stage 3a edge foundation ordering and the rule that edge
reconciliation is unavailable until CoreDNS, Traefik, and required Authentik API
access are healthy.

## Files

- `docs/design/bootstrap.md`
- `docs/provisioning-refactor/decisions.md`
- `docs/provisioning-refactor/tasks/01-bootstrap-order.md`
- `docs/provisioning-refactor/prompts/01-bootstrap-order.yaml`

## Preconditions

- Task 00 complete.

## Operations

1. Add Stage 3a: CoreDNS seed zone -> Traefik runtime -> step-ca -> Authentik
   direct first boot/API token.
2. State that Terraform does not detect edge readiness or run a hidden second
   pass.
3. State that direct-IP access is the bootstrap fallback until the edge
   reconciler is active.

## Postconditions

- Fresh pve-test deployment order is explicit for Mode 2 rebuilds.
- The edge reconciler activation gate is documented before tooling tasks begin.

## Validation

- `rg -n "Stage 3a|edge reconciler|hidden second pass" docs/design/bootstrap.md docs/provisioning-refactor/decisions.md`

## Stop Conditions

- Stop if the documented order conflicts with current live stack prerequisites.
