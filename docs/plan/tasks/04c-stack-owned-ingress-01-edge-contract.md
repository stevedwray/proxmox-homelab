# 04c-stack-owned-ingress-01 — Define Edge Contract and Validation Rules

> Historical task packet.
> This document predates the current provisioning-refactor source of truth.
> Keep it as implementation history only. For current edge-refactor guidance,
> use [docs/provisioning-refactor/README.md](../../provisioning-refactor/README.md)
> and [docs/provisioning-refactor/task-sequence.md](../../provisioning-refactor/task-sequence.md).

## Phase

Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Objective

Create a versioned edge manifest contract and validation rules that every stack must satisfy.

## Scope

- Define schema (v1alpha1)
- Define required and optional fields
- Add validation rules for host, auth mode, tls resolver, dns targets
- Create fixture examples and expected validation outcomes

## Deliverables

- Schema spec document in repo docs
- Validation rule checklist
- Example manifests for: portainer, netbox, harbor
- Error catalog for common invalid states

## Session boundary

Single-session target. No runtime deployment required.

## Implementation checklist

- [ ] Define `apiVersion`, `kind`, `metadata`, `spec.routes[]`
- [ ] Enumerate auth modes and constraints
- [ ] Add uniqueness and domain-suffix rules
- [ ] Document pve-test-only domain policy (`.lab.gibbsgreatly.xyz`)
- [ ] Provide 3 valid and 5 invalid fixture examples

## Validation

- [ ] Schema can reject duplicate hostnames
- [ ] Schema can reject missing backend URL
- [ ] Schema can reject invalid auth mode

## Done when

- Contract is explicit and unambiguous for implementation in next tasks
- Examples are sufficient for independent coding sessions
