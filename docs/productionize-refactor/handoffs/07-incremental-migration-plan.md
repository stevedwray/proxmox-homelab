# Handoff 07: Incremental Migration Plan

## Objective

Convert the productionization strategy into a service-by-service migration
order for moving workloads from `pve-test` to `pve`.

## Branch

- `work/productionize-07-migration-plan`

## Primary Source

- [Task 07: Incremental Migration Plan](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)

## Scope

In scope:

- migration order
- per-service dependency and collision notes
- parallel-first vs cutover-first thinking
- rollback expectations

Out of scope:

- actual service migration execution
- rewriting manifests
- implementing credential-control mechanics

## Files To Read First

- [docs/productionize-refactor/tasks/07-incremental-migration-plan.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)
- [docs/productionize-refactor/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)
- [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)

## Files Most Likely To Change

- docs under `docs/productionize-refactor/`

## Constraints

- base the order on actual dependency weight
- treat `harbor-stack`, `netbox-stack`, and management-plane overlaps carefully
- assume the canary gate should already have informed the plan

## Done When

- there is a ranked migration order
- each major service has a short cutover stance
- later execution sessions could follow the plan without re-deriving the whole
  dependency picture

## Validation

- early movers are low-risk
- central services are intentionally placed later
- collision-heavy services are called out explicitly

## Suggested Copilot Brief

```text
Work on Task 07 in docs/productionize-refactor/tasks/07-incremental-migration-plan.md.
Produce a service-by-service migration order from pve-test to pve.
Keep it dependency-aware, collision-aware, and realistic for a homelab.
Do not execute migrations or rewrite manifests in this session.
```
