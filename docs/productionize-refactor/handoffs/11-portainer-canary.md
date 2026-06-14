# Handoff 11: Portainer Canary

## Objective

Execute the next low-risk production migration after monitoring:
`portainer-stack` on `pve`.

This handoff is execution-ready. Production mutations are allowed only after
read-only preflight and explicit operator approval in chat.

## Branch

- `work/productionize-11-portainer-canary`

## Primary Source

- [Task 07: Incremental Migration Plan](docs/productionize-refactor/tasks/07-incremental-migration-plan.md)
- [pve Production Readiness Plan](docs/productionize-refactor/pve-production-readiness.md)
- [monitoring-stack Canary Closure (pve)](docs/productionize-refactor/09-monitoring-canary-closure.md)
- [portainer-stack Stack Contract](terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md)
- [portainer-stack Stack Definition](terraform/lxc/stacks/portainer-stack/stack.yaml)
- [portainer-stack Terragrunt root](terraform/lxc/stacks/portainer-stack/terragrunt.hcl)
- [portainer-stack Edge Manifest](terraform/lxc/stacks/portainer-stack/edge.yaml)
- [Deploy playbook: portainer-stack](terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml)

## Scope

In scope:

- run the `portainer-stack` production canary on `pve`
- counterpart-safety checks and conditional disposal for shared service IP reuse
- read-only preflight, plan, apply, provision, and post-deploy health evidence
- execution evidence capture under a timestamped folder

Out of scope:

- unrelated stack migrations
- redesigning storage/network manifests
- broad refactor changes outside portainer canary flow

## Files To Read First

- [docs/productionize-refactor/09-monitoring-canary-closure.md](docs/productionize-refactor/09-monitoring-canary-closure.md)
- [docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md](docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md)
- [docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md](docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md)
- [docs/productionize-refactor/09-monitoring-canary-execution-packet.md](docs/productionize-refactor/09-monitoring-canary-execution-packet.md)
- [terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md](terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md)
- [terraform/lxc/stacks/portainer-stack/stack.yaml](terraform/lxc/stacks/portainer-stack/stack.yaml)
- [terraform/lxc/stacks/portainer-stack/edge.yaml](terraform/lxc/stacks/portainer-stack/edge.yaml)
- [terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml](terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml)

## Files Most Likely To Change

- docs under `docs/productionize-refactor/`
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` only if execution uncovers a concrete defect

## Required Runtime Inputs

From `deploy-portainer-stack.yml`, treat these as preflight gates:

- `PORTAINER_ADMIN_PASSWORD` or `TF_VAR_portainer_admin_password` must be non-empty
- `PORTAINER_OAUTH_CLIENT_SECRET` must be non-empty when `PORTAINER_OAUTH_ENABLED=true`
- `LAB_IP_DNS` (or inventory `dns_server`) must be set for Docker daemon DNS config
- expected targeting values from `.env.pve` must resolve correctly for `LAB_IP_PORTAINER`, `LAB_GW_MGMT`, `LAB_IP_PROXY`

## Next Session Start Sequence

1. Confirm branch is short-lived and not a promotion branch.
2. Confirm wrapper target and IP values (`LAB_IP_PORTAINER`, `LAB_GW_MGMT`, `LAB_IP_PROXY`).
3. Run counterpart plan for `portainer-stack` on `pve-test` and decide whether disposal is required for shared IP reuse.
4. Validate required runtime inputs (password/OAuth/DNS env vars).
5. Run production plan for `terraform/lxc/stacks/portainer-stack` and verify `target_node = pve`, `network.zone = mgmt_seg`, expected IP/gateway.
6. Obtain explicit operator approval before apply/provision.
7. Apply, run provisioning (`--check` then live), then collect health evidence.

## Handoff Artifacts Expected

When canary is executed, collect evidence under:

- `docs/productionize-refactor/evidence/portainer-canary-<timestamp>/`

Minimum expected files:

- target validation output
- counterpart plan and execute output (or explicit no-reuse evidence)
- plan output
- apply output
- stack inventory contract output
- provision check output
- live provision output
- post-deploy health output

## Portainer Health Gate (Post-Deploy)

Use the stack contract and deploy playbook behavior as the gate:

- Portainer API status endpoint: `http://${LAB_IP_PORTAINER}:9000/api/system/status` returns `200`
- container has intended IP/gateway on `mgmt_seg`
- direct SSH path remains in effect (`proxyjump=none`)
- Portainer service ports available: `9000`, `9443`, `8000`
- counterpart safety recheck on `pve-test` shows no conflicting active counterpart

## Issues To Carry Forward

- Preserve optional workstation-tool behavior (`pvesh`/`pct` may be unavailable locally).
- Preserve counterpart `--plan` and `--stop-only` fallback when destroy is blocked by SDN guards.
- Preserve operator-approved MikroTik skip behavior only when network state is already validated and unchanged, with skip attestation recorded in evidence.
- Preserve explicit secret/input gates before any production mutation.

## Constraints

- keep execution focused on `portainer-stack` only
- preserve direct-access model; do not reintroduce ProxyJump or host-route priming
- avoid unrelated production mutations in the same window

## Done When

- `portainer-stack` canary on `pve` is executed with complete evidence
- apply/provision and health checks pass
- counterpart collision risk is addressed before cutover when reuse applies
- canary closure summary is added under `docs/productionize-refactor/`

## Validation

- targeting shows `pve` and `mgmt_seg`
- inventory shows direct-access path and expected playbook identity
- provisioning check and live runs both complete without failures
- Portainer API health endpoint returns success
- evidence folder contains plan/apply/provision/health artifacts

## Suggested Copilot Brief

```text
Execute the portainer-stack canary slice of the productionize refactor.
Use docs/productionize-refactor/tasks/07-incremental-migration-plan.md,
docs/productionize-refactor/pve-production-readiness.md,
docs/productionize-refactor/09-monitoring-canary-closure.md, and the
portainer-stack contract/stack/terragrunt/playbook files as the main sources.
Run read-only preflight first, then apply/provision only after explicit
operator approval. Capture complete evidence under a timestamped
portainer-canary folder and finish with a pass/fail closure summary.
```
