# Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Goal

Refactor edge ownership so each service stack defines and deploys its own ingress/auth/dns intent, while central Traefik remains only the runtime gateway.

## Why this phase exists

The current central model in proxy deployment creates coupling and operational risk. This phase introduces a per-stack contract and reconciler flow so future service onboarding does not require editing central route templates.

## Scope

In scope:
- Define edge manifest schema and conventions
- Implement manifest validation and rendering into Traefik dynamic files
- Implement DNS reconciliation from stack metadata
- Implement Authentik reconciliation from stack metadata
- Migrate current browser stacks incrementally
- Remove legacy central per-service routing blocks

Out of scope:
- Production (`pve`) rollout
- Multi-cluster tenancy
- Replacing Traefik runtime itself

## Dependencies

- Phase 04 core services are operational on pve-test
- Browser ingress baseline is currently functional
- MikroTik API credentials available via secure env injection
- Authentik admin API token workflow established

## Deliverables

- Design document: `docs/design/stack-owned-ingress-auth-dns.md`
- Manifest schema and validator implementation
- Per-stack edge manifest files for core browser services
- DNS + Authentik reconciliation automation
- Updated operational prompts for each migration step

## Work packages

1. 04c-01: Edge contract and schema
2. 04c-02: Traefik stack manifest renderer
3. 04c-03: DNS reconciler (MikroTik API)
4. 04c-04: Authentik reconciler
5. 04c-05: Incremental stack migrations
6. 04c-06: Cutover and legacy cleanup

## Acceptance criteria

- New stack can onboard browser ingress without editing central proxy route template
- All migrated hosts resolve and route correctly through generated stack files
- Auth policies behave as declared in each stack manifest
- DNS and Authentik drift can be reconciled by rerunning automation
- Legacy central route blocks removed after successful migration

## Risks and mitigations

- Risk: Hostname collisions across manifests
  - Mitigation: validator blocks duplicates before render
- Risk: Auth redirect regressions
  - Mitigation: migrate one stack at a time with route-by-route checks
- Risk: DNS drift due to manual changes
  - Mitigation: explicit reconcile mode with idempotent apply
- Risk: Outage during cutover
  - Mitigation: rollback snapshots and central-template fallback

## Execution model

This phase is designed for small, isolated sessions. Each task document is one merge-sized unit and has its own prompt.

## Completion gate

Phase 04c is complete when all 04c task docs are marked complete and `deploy-proxy-stack.yml` no longer hardcodes per-service browser routes.
