# Handoff 10: Monitoring Canary

## Status

- Completed on May 23, 2026
- Closure summary: `docs/productionize-refactor/09-monitoring-canary-closure.md`
- Recommended next migration: `portainer-stack` on `pve`

## Objective

Continue the productionizing refactor by preparing the next low-risk canary
after `step-ca-stack`: `monitoring-stack` on `pve`.

This handoff is documentation-first. Do not execute production mutations in the
prep session.

## Branch

- `work/productionize-10-monitoring-canary`

## Primary Source

- [Task 07: Incremental Migration Plan](docs/productionize-refactor/tasks/07-incremental-migration-plan.md)
- [Production Canary Runbook: monitoring-stack on pve](docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md)
- [Production Canary Execution Checklist: monitoring-stack on pve](docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md)
- [monitoring-stack Canary Execution Packet (pve)](docs/productionize-refactor/09-monitoring-canary-execution-packet.md)
- [Handoff 09: Step-CA Canary](docs/productionize-refactor/handoffs/09-step-ca-canary.md)
- [monitoring-stack Stack Contract](terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md)
- [monitoring-stack Terragrunt root](terraform/lxc/stacks/monitoring-stack/terragrunt.hcl)

## Scope

In scope:

- monitoring canary runbook and execution packet
- preflight and counterpart-safety safeguards for `monitoring-stack`
- operator-facing evidence expectations
- aligning the migration plan so monitoring is the next migration after step-ca
- carrying forward the step-ca lessons into the next stack migration

Out of scope:

- running the production canary itself
- migrating unrelated services
- redesigning the network or storage manifests

## Files To Read First

- [docs/productionize-refactor/tasks/07-incremental-migration-plan.md](docs/productionize-refactor/tasks/07-incremental-migration-plan.md)
- [docs/productionize-refactor/pve-production-readiness.md](docs/productionize-refactor/pve-production-readiness.md)
- [docs/productionize-refactor/handoffs/09-step-ca-canary.md](docs/productionize-refactor/handoffs/09-step-ca-canary.md)
- [docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md](docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md)
- [docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md](docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md)
- [docs/productionize-refactor/09-monitoring-canary-execution-packet.md](docs/productionize-refactor/09-monitoring-canary-execution-packet.md)
- [terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md](terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md)
- [terraform/lxc/stacks/monitoring-stack/stack.yaml](terraform/lxc/stacks/monitoring-stack/stack.yaml)
- [terraform/lxc/stacks/monitoring-stack/edge.yaml](terraform/lxc/stacks/monitoring-stack/edge.yaml)
- [terraform/lxc/stacks/monitoring-stack/terragrunt.hcl](terraform/lxc/stacks/monitoring-stack/terragrunt.hcl)

## Files Most Likely To Change

- docs under `docs/productionize-refactor/`
- potentially `docs/productionize-refactor/tasks/07-incremental-migration-plan.md`
- potentially `docs/productionize-refactor/pve-production-readiness.md`

## Next Session Start Sequence

1. Re-read the monitoring handoff, monitoring runbook/checklist/packet, the step-ca handoff, and the migration plan.
2. Confirm the monitoring stack metadata still matches `.env.pve` and the
   current `pve` target assumptions.
3. Confirm monitoring required env inputs remain non-empty in production runtime:
  `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_SECRET`,
  `AUTHENTIK_SUPERUSER_API_TOKEN`, `LAB_IP_HARBOR`, and `LAB_IP_DNS`.
4. Confirm whether monitoring reuses any live `pve-test` counterpart state that
  must be stopped or destroyed before cutover.
5. If any values drifted, update the monitoring packet/checklist first; do not
   execute canary commands with stale assumptions.

## Handoff Artifacts Expected

When the future canary is executed, collect evidence under:

- `docs/productionize-refactor/evidence/monitoring-canary-<timestamp>/`

Minimum expected files:

- plan output
- apply output
- post-apply inventory contract check output
- provisioning check and live run outputs
- post-deploy health command outputs
- counterpart plan/destroy output if reuse applies

## Issues To Carry Forward

These are the concrete runbook guardrails to preserve from the step-ca canary:

- Treat workstation-only CLI availability as optional; use plan output as the
  fallback source of truth when `pvesh` is unavailable locally.
- Keep `pct list` optional in docs when the local Proxmox CLI is absent.
- Make non-empty secret requirements explicit before any bootstrap that uses
  password files or no-log initialization.
- Preserve the documented counterpart `--plan` and `--stop-only` fallback path
  so a direct destroy guard does not block safe cutover.
- Keep health checks aligned to the actual certificate/hostnames used by the
  service.
- Keep monitoring checks aligned to real service endpoints from the deploy
  playbook (`/api/health`, `/metrics`, `/ready`) instead of generic port-only
  probes.

## Constraints

- keep the next session focused on the monitoring canary only
- preserve the direct-access model; do not reintroduce ProxyJump or host-route priming
- treat DNS record-creation issues as separate from the monitoring canary
- keep the packet/checklist aligned with the actual monitoring health checks

## Done When

- the monitoring canary is documented as the next low-risk production target
  after step-ca
- the execution packet and checklist are complete and internally consistent
- the migration plan reflects monitoring as the next canary in sequence
- a future session could execute the canary without re-deriving the intent
- the packet/checklist explicitly separate read-only preflight from
  operator-approved mutation steps

## Validation

- monitoring docs point at the correct `pve` target and `mgmt_seg` values
- the packet includes counterpart safeguards, plan, apply, and health evidence
- the service checks match the real monitoring stack behavior
- ordering is consistent across handoff, migration plan, and readiness docs

## Suggested Copilot Brief

```text
Work on the monitoring-stack canary slice of the productionize refactor.
Use docs/productionize-refactor/tasks/07-incremental-migration-plan.md,
docs/productionize-refactor/pve-production-readiness.md,
docs/productionize-refactor/handoffs/09-step-ca-canary.md, and the
monitoring-stack contract and terragrunt files as the main sources. Keep the
scope to the next low-risk production canary after step-ca on pve. Do not
execute production changes; tighten the docs and handoff so a future session
can run the monitoring canary cleanly.
```
