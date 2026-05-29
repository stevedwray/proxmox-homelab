# Handoff 12: NetBox Canary

## Status

- Completed execution
- Historical migration after portainer: `netbox-stack` on `pve`

## Objective

Document the completed production migration of `netbox-stack` on `pve` and
carry forward the sequence to the next target: `ci-runner-01`.

This handoff is documentation-first. Do not execute production mutations in the
prep session.

## Branch

- `work/productionize-12-netbox-canary`

## Primary Source

- [Task 07: Incremental Migration Plan](docs/productionize-refactor/tasks/07-incremental-migration-plan.md)
- [Production Canary Runbook: netbox-stack on pve](docs/productionize-refactor/runbooks/10-pve-canary-netbox.md)
- [Production Canary Execution Checklist: netbox-stack on pve](docs/productionize-refactor/runbooks/10-pve-canary-netbox-checklist.md)
- [netbox-stack Canary Execution Packet (pve)](docs/productionize-refactor/10-netbox-canary-execution-packet.md)
- [Handoff 11: Portainer Canary](docs/productionize-refactor/handoffs/11-portainer-canary.md)
- [netbox-stack Stack Contract](terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md)
- [netbox-stack Terragrunt root](terraform/lxc/stacks/netbox-stack/terragrunt.hcl)

## Scope

In scope:

- netbox migration runbook and execution packet
- preflight and counterpart-safety safeguards for `netbox-stack`
- operator-facing evidence expectations
- capturing the executed netbox migration as a completed production cutover
- aligning the migration plan so `ci-runner-01` is the next migration after netbox
- carrying forward the portainer lessons into the next stack migration

Out of scope:

- running the production migration itself
- migrating unrelated services
- redesigning the network or storage manifests

## Files To Read First

- [docs/productionize-refactor/tasks/07-incremental-migration-plan.md](docs/productionize-refactor/tasks/07-incremental-migration-plan.md)
- [docs/productionize-refactor/pve-production-readiness.md](docs/productionize-refactor/pve-production-readiness.md)
- [docs/productionize-refactor/runbooks/10-pve-canary-netbox.md](docs/productionize-refactor/runbooks/10-pve-canary-netbox.md)
- [docs/productionize-refactor/runbooks/10-pve-canary-netbox-checklist.md](docs/productionize-refactor/runbooks/10-pve-canary-netbox-checklist.md)
- [docs/productionize-refactor/10-netbox-canary-execution-packet.md](docs/productionize-refactor/10-netbox-canary-execution-packet.md)
- [terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md](terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md)
- [terraform/lxc/stacks/netbox-stack/stack.yaml](terraform/lxc/stacks/netbox-stack/stack.yaml)
- [terraform/lxc/stacks/netbox-stack/edge.yaml](terraform/lxc/stacks/netbox-stack/edge.yaml)
- [terraform/lxc/stacks/netbox-stack/terragrunt.hcl](terraform/lxc/stacks/netbox-stack/terragrunt.hcl)

## Files Most Likely To Change

- docs under `docs/productionize-refactor/`
- potentially `docs/productionize-refactor/tasks/07-incremental-migration-plan.md`
- potentially `docs/productionize-refactor/pve-production-readiness.md`

## Next Session Start Sequence

1. Re-read the netbox handoff, netbox runbook/checklist/packet, and the migration plan.
2. Confirm the netbox stack metadata still matches `.env.pve` and the current `pve` target assumptions.
3. Confirm netbox required env inputs remain non-empty in production runtime: `NETBOX_DB_PASSWORD`, `NETBOX_REDIS_PASSWORD`, `NETBOX_REDIS_CACHE_PASSWORD`, `NETBOX_SECRET_KEY`, `NETBOX_API_TOKEN_PEPPER`, `NETBOX_SUPERUSER_PASSWORD`, `NETBOX_SUPERUSER_API_TOKEN`, `LAB_IP_PORTAINER`, `LAB_IP_HARBOR`, and `LAB_IP_DNS`.
4. Confirm whether netbox reuses any live `pve-test` counterpart state that must be stopped or destroyed before cutover.
5. If any values drifted, update the netbox packet/checklist first; do not execute migration commands with stale assumptions.

## Handoff Artifacts Expected

When the future migration is executed, collect evidence under:

- `docs/productionize-refactor/evidence/netbox-canary-<timestamp>/`

Minimum expected files:

- plan output
- apply output
- post-apply inventory contract check output
- provisioning check and live run outputs
- post-deploy health command outputs
- counterpart plan/destroy output if reuse applies

## Issues To Carry Forward

These are the concrete runbook guardrails to preserve for the netbox migration:

- Treat workstation-only CLI availability as optional; use plan output as the fallback source of truth when `pvesh` is unavailable locally.
- Keep `pct list` optional in docs when the local Proxmox CLI is absent.
- Make non-empty secret requirements explicit before any compose/bootstrap path that uses password-file initialization.
- Preserve the documented counterpart `--plan` and conditional `--execute` workflow so a direct destroy guard does not block safe cutover.
- Keep health checks aligned to the actual NetBox compose health and edge route behavior.
- Keep network checks aligned to the real `infra_seg` values from the production overlay.

## Constraints

- keep the next session focused on the netbox migration only
- preserve the direct-access model; do not reintroduce ProxyJump or host-route priming
- treat any remaining data-path cleanup as separate from the NetBox migration
- keep the packet/checklist aligned with the actual NetBox health checks

## Done When

- the netbox migration is documented as completed production work
- the execution packet and checklist remain available as historical references
- the migration plan reflects `ci-runner-01` as the next migration in sequence
- a future session can use the ci-runner handoff without re-deriving intent
- the packet/checklist explicitly separate read-only preflight from operator-approved mutation steps

## Validation

- netbox docs point at the correct `pve` target and `infra_seg` values
- the packet includes counterpart safeguards, plan, apply, and health evidence
- the service checks match the real NetBox stack behavior
- ordering is consistent across handoff, migration plan, readiness docs, and execution packet

## Suggested Copilot Brief

```text
Work on the ci-runner migration slice of the productionize refactor.
Use docs/productionize-refactor/tasks/07-incremental-migration-plan.md,
docs/productionize-refactor/pve-production-readiness.md,
docs/productionize-refactor/handoffs/13-ci-runner-canary.md, and the
ci-runner-01 stack contract, stack definition, and terragrunt files as the
main sources. Keep the scope to the next production migration after netbox on
pve. Do not execute production changes; tighten the docs and handoff so a
future session can run the ci-runner migration cleanly.
```
