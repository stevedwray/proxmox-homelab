# Task 17a: Edge Validation Substrate Hardening

## Type

Development

## Objective

Harden migration validation substrate before forward-auth route migrations.

## Scope

- Clarify and enforce DNS validation resolver contract for route migrations.
- Ensure generated Traefik files are always published to the directory Traefik
  actively watches.
- Add explicit preflight checks so Tasks 18-20 fail fast on substrate drift.

## Inputs

- `docs/provisioning-refactor/runbook.md`
- `terraform/lxc/reconcile-edge.py`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- Any publish helper used for generated Traefik file sync

## Required Outcomes

1. Resolver contract is explicit:
   - Either `192.168.30.11` is restored as required endpoint and validated from
     runtime contexts.
   - Or runbook/reconciler DNS checks are updated to validate through the
     intended reachable lab resolvers.
2. Traefik generated-file publish path matches the watched file-provider
   directory in deployed runtime, with no manual fallback copy.
3. A deterministic post-publish validation confirms:
   - Generated route is loaded by Traefik.
   - Route behavior matches manifest auth mode.

## Validation

- DNS validation command succeeds from required runtime context(s).
- Grafana/Harbor/AuthentiK smoke checks remain healthy.
- Reconciler dry-run remains passed with zero issues after hardening changes.

## Stop Conditions

- Stop if resolver contract cannot be agreed or proven from any runtime context.
- Stop if publish-path changes risk regressing already migrated routes.
