# Handoff 06: Canary Validation Gate

## Objective

Define the early canary validation workflow that proves production networking
before moving a high-value service.

## Branch

- `work/productionize-06-canary-validation`

## Primary Source

- [Task 06: Canary Validation Gate](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md:1)

## Scope

In scope:

- canary runbook
- validation matrix
- success/failure criteria
- recommended first canary

Out of scope:

- migrating a real high-value service
- broad credential-system changes
- rewriting the storage or network manifests from scratch

## Files To Read First

- [docs/productionize-refactor/tasks/06-canary-validation-gate.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md:1)
- [docs/productionize-refactor/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)
- [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)

## Files Most Likely To Change

- docs under `docs/productionize-refactor/`
- possibly a disposable test-stack doc reference if needed

## Constraints

- validate early
- keep the first canary low-risk
- assume VLAN work exists outside the repo but must still be proven

## Done When

- there is a clear canary runbook
- the required checks are explicit
- the first canary candidate is named and justified

## Validation

- runbook covers IP, gateway, DNS, and one useful dependency path
- evidence expectations are clear enough for a future execution session

## Suggested Copilot Brief

```text
Work on Task 06 in docs/productionize-refactor/tasks/06-canary-validation-gate.md.
Create a practical canary validation workflow for pve.
Keep the first canary low-risk and focused on proving network and environment behavior before real migration.
Do not turn this into a full migration plan; keep it as a gate.
```
