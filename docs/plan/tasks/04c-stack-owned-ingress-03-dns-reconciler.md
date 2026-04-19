# 04c-stack-owned-ingress-03 — Implement DNS Reconciliation from Stack Manifests

## Phase

Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Objective

Automate MikroTik DNS static record reconciliation based on stack edge manifests.

## Scope

- Parse desired DNS records from manifests
- Read current records from MikroTik REST API
- Compute create/update/delete plan
- Apply in idempotent mode

## Deliverables

- DNS reconcile script/role/playbook entrypoint
- Dry-run diff output
- Apply mode with safe defaults
- Retry/error handling for API failures

## Session boundary

Single-session target for reconcile planner; optional second session for full apply + test hardening.

## Implementation checklist

- [ ] Add environment-driven credentials only
- [ ] Implement list current records
- [ ] Implement diff: add/update/delete
- [ ] Apply with TTL standardization (`5m`)
- [ ] Protect non-managed records via ownership tag or naming scope

## Validation

- [ ] Two consecutive runs produce no changes when state matches
- [ ] Record updates occur when target IP changes
- [ ] Invalid credentials fail with actionable message

## Done when

- DNS state is derivable from stack manifests without ad-hoc router CLI commands
