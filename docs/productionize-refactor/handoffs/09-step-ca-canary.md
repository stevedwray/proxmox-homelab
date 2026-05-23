# Handoff 09: Step-CA Canary

## Objective

Continue the productionizing refactor by preparing the next low-risk canary
after `dns-stack`: `step-ca-stack` on `pve`.

This handoff is documentation-first. Do not execute production mutations in the
prep session.

## Branch

- `work/productionize-08-step-ca-canary`

## Primary Source

- [Task 07: Incremental Migration Plan](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)
- [Production Canary Runbook: step-ca-stack on pve](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/08-pve-canary-step-ca.md:1)
- [Production Canary Execution Checklist: step-ca-stack on pve](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/08-pve-canary-step-ca-checklist.md:1)
- [step-ca-stack Canary Execution Packet (pve)](/home/steve/git/proxmox-homelab/docs/productionize-refactor/08-step-ca-canary-execution-packet.md:1)

## Scope

In scope:

- step-ca canary runbook and execution packet
- preflight and duplicate-IP safeguards for `step-ca-stack`
- operator-facing evidence expectations
- aligning the migration plan so step-ca is the next canary after dns
- tightening the execution handoff so a future operator can run the canary
  without re-deriving sequence or approvals

Out of scope:

- running the production canary itself
- migrating unrelated services
- redesigning the network or storage manifests

## Files To Read First

- [docs/productionize-refactor/tasks/07-incremental-migration-plan.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)
- [docs/productionize-refactor/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)
- [docs/productionize-refactor/runbooks/08-pve-canary-step-ca.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/08-pve-canary-step-ca.md:1)
- [docs/productionize-refactor/runbooks/08-pve-canary-step-ca-checklist.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/08-pve-canary-step-ca-checklist.md:1)
- [docs/productionize-refactor/08-step-ca-canary-execution-packet.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/08-step-ca-canary-execution-packet.md:1)
- [terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md:1)
- [terraform/lxc/ansible/playbooks/deploy-step-ca.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-step-ca.yml:1)

## Files Most Likely To Change

- docs under `docs/productionize-refactor/`
- potentially `docs/productionize-refactor/tasks/07-incremental-migration-plan.md`
- potentially `docs/productionize-refactor/pve-production-readiness.md`

## Next Session Start Sequence

1. Re-read the three step-ca canary source docs and this handoff.
2. Confirm the packet and checklist still match `.env.pve` for `LAB_IP_STEP_CA`,
   `LAB_GW_MGMT`, and `LAB_IP_PROXY`.
3. Confirm whether step-ca IP reuse from `pve-test` to `pve` still applies.
4. If any value drifted, update packet/checklist first; do not execute canary
   commands with stale assumptions.

## Handoff Artifacts Expected

When the future canary is executed, collect evidence under:

- `docs/productionize-refactor/evidence/step-ca-canary-<timestamp>/`

Minimum expected files:

- plan output
- apply output
- post-apply inventory contract check output
- provisioning check and live run outputs
- post-deploy health command outputs
- production MikroTik preflight output

## Known Execution Blocker (From Live Preflight)

- `scripts/preflight-production-mikrotik.sh` now fails fast if required runtime
  variables are missing instead of recursively re-executing.
- Current blocker observed: missing `MIKROTIK_PASSWORD` in the production
  runtime environment.
- Ensure `MIKROTIK_PASSWORD` is provided via
  `terraform/secrets.pve.enc.yaml` before attempting the production canary.
- Current blocker observed during provisioning: `STEP_CA_PASSWORD` and
  `STEP_CA_PROVISIONER_PASSWORD` resolve to empty values in production runtime,
  which causes `step ca init` to fall back to an interactive prompt and fail.
- Ensure both step-ca password secrets are present as non-empty values in
  `terraform/secrets.pve.enc.yaml` before rerunning step-ca provisioning.

## Issues To Carry Forward

These are the concrete runbook problems uncovered during the step-ca canary and
should be treated as migration guardrails for the next container moves:

- `pvesh` is not installed on the workstation; target validation should rely on
 `terragrunt plan` output when the local Proxmox CLI is unavailable.
- `pct list` is also workstation-dependent; keep that check optional in docs.
- `step ca health` must use the container IP that matches the certificate SAN,
  not `127.0.0.1`.
- The pve-test counterpart destroy path can hit an SDN guard; preserve the
  `--plan` and `--stop-only` fallback workflow so cutover can still remove live
  counterpart conflict safely.
- Step-ca bootstrap secrets must be non-empty; empty values should be treated as
  a hard stop before any future container migration that uses password-file
  bootstrap.

## Next Migration

The next migration to perform after step-ca is `monitoring-stack` on `pve`.
It is the next item in the current ordering after `step-ca-stack` and should
inherit the corrected guardrails above before any execution session starts.

Primary docs for that next canary:

- `docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md`
- `docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md`
- `docs/productionize-refactor/09-monitoring-canary-execution-packet.md`

## Constraints

- keep the next session focused on the step-ca canary only
- preserve the direct-access model; do not reintroduce ProxyJump or host-route priming
- treat DNS record-creation issues as separate from the step-ca canary
- keep the packet/checklist aligned with the actual `step-ca` health checks

## Done When

- the step-ca canary is documented as the next low-risk production target after dns
- the execution packet and checklist are complete and internally consistent
- the migration plan reflects step-ca as the next canary in sequence
- a future session could execute the canary without re-deriving the intent
- the packet/checklist explicitly separate read-only preflight from
  operator-approved mutation steps
- counterpart disposal is clearly conditional on IP reuse and not implied as an
  unconditional mutation

## Validation

- step-ca docs point at the correct `pve` target and `mgmt_seg` values
- the packet includes counterpart disposal, plan, apply, and health evidence
- the step-ca service checks are based on `step ca health` and port 80 reachability to Traefik
- ordering is consistent across runbook, checklist, and packet
- no command in the prep handoff requires production execution to complete the docs task

## Suggested Copilot Brief

```text
Work on the step-ca canary slice of the productionize refactor.
Use docs/productionize-refactor/runbooks/08-pve-canary-step-ca.md,
docs/productionize-refactor/runbooks/08-pve-canary-step-ca-checklist.md, and
docs/productionize-refactor/08-step-ca-canary-execution-packet.md as the main
sources. Keep the scope to the next low-risk production canary after dns-stack
on pve. Do not execute production changes; tighten the docs and handoff so a
future session can run the canary cleanly.
```
