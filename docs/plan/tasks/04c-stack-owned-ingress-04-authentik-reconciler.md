# 04c-stack-owned-ingress-04 — Implement Authentik Reconciliation from Stack Manifests

## Phase

Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Objective

Automate Authentik application/provider intent for stack routes that require forward-auth or OIDC metadata.

## Scope

- Read Authentik-related declarations from manifests
- Ensure provider/app linkage is present and consistent
- Ensure outpost association for forward-auth use-cases
- Support idempotent reconcile and drift correction

## Deliverables

- Authentik reconcile workflow
- Mapping rules from manifest auth fields to Authentik objects
- Drift report and apply mode

## Session boundary

Likely two sessions: object model mapping first, then apply/validation.

## Implementation checklist

- [ ] Define minimal supported Authentik object set
- [ ] Implement lookup and upsert logic
- [ ] Keep domain-level cookie and external host policy consistent
- [ ] Avoid destructive deletes by default
- [ ] Add audit output for created/updated objects

## Validation

- [ ] Re-run is idempotent (no duplicate apps/providers)
- [ ] Forward-auth routes redirect correctly to Authentik authorization flow
- [ ] Authentik route itself remains reachable without recursion

## Done when

- Authentik wiring for stack-owned routes no longer depends on manual admin UI changes
