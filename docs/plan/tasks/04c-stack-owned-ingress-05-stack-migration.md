# 04c-stack-owned-ingress-05 — Migrate Existing Browser Stacks to Stack Ownership

> Historical task packet.
> This document predates the current provisioning-refactor source of truth.
> Keep it as implementation history only. For current edge-refactor guidance,
> use [docs/provisioning-refactor/README.md](../../provisioning-refactor/README.md)
> and [docs/provisioning-refactor/task-sequence.md](../../provisioning-refactor/task-sequence.md).

## Phase

Phase 04c — Stack-Owned Ingress, DNS, and Auth Integration

## Objective

Migrate existing browser-facing services from central route ownership to stack-owned manifests with minimal downtime.

## Scope

Services in order:
1. Portainer
2. NetBox
3. Harbor
4. Authentik
5. Grafana
6. Traefik dashboard

## Deliverables

- Edge manifest file per stack
- Generated Traefik files per stack
- DNS records reconciled from manifest state
- Auth behavior verified per stack policy

## Session boundary

One service per session recommended.

## Per-service checklist

- [ ] Add/validate stack manifest
- [ ] Render and deploy generated route
- [ ] Reconcile DNS
- [ ] Reconcile Authentik (if applicable)
- [ ] Validate route, auth flow, and cert
- [ ] Remove old central route entry for that service

## Validation commands

- `curl -skI --resolve <host>:443:10.57.2.10 https://<host>/`
- `dig +short @192.168.1.1 <host>`
- Auth redirects expected for forward-auth services only

## Done when

- All six services are stack-owned and central route entries are removed service-by-service
