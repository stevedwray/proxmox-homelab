# 04c-stack-owned-ingress-02 — Build Traefik Renderer from Stack Manifests

> Historical task packet.
> This document predates the current provisioning-refactor source of truth.
> Keep it as implementation history only. For current edge-refactor guidance,
> use [docs/provisioning-refactor/README.md](../../provisioning-refactor/README.md)
> and [docs/provisioning-refactor/task-sequence.md](../../provisioning-refactor/task-sequence.md).

## Phase

Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Objective

Implement manifest-driven generation of per-stack Traefik dynamic files.

## Scope

- Discover stack manifests from standard paths
- Validate each manifest
- Render per-stack output file under Traefik dynamic directory
- Preserve stable output ordering for diff-friendly commits

## Deliverables

- Renderer implementation
- Rendered file naming convention (`<stack>.yml`)
- Conflict handling for duplicate host rules
- Dry-run mode for CI/testing

## Session boundary

Single-session target if validation library is already present; otherwise split into parser + renderer sub-sessions.

## Implementation checklist

- [ ] Add manifest discovery logic
- [ ] Add schema validation call before render
- [ ] Map auth modes to middleware declarations
- [ ] Generate routers/services/tls blocks
- [ ] Add deterministic sort order for routes and services
- [ ] Keep central Traefik static config untouched

## Validation

- [ ] Render output passes `docker compose config -q` in proxy stack context
- [ ] Generated file for each sample stack is syntactically valid YAML
- [ ] Duplicate host collision fails fast with clear error

## Done when

- Traefik routes can be sourced from stack manifests without editing central route template
