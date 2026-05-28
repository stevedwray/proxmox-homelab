# Baseline Merge Backport Checklist

Purpose: classify the branch delta between `baseline/teardown-validated` and
`prod/pve-infra` into review buckets so the convergence branch can implement a
small, behavior-driven subset first.

Branch comparison used:

```bash
git diff --name-status baseline/teardown-validated..prod/pve-infra
git diff --name-only baseline/teardown-validated..prod/pve-infra \
  | rg -v '^docs/productionize-refactor/(evidence|handoffs)/'
```

## Review Table

| Path | Bucket | Why it matters on pve-test | Status | Notes |
|---|---|---|---|---|
| `with-secrets` | `must-backport` | Establishes default-safe environment selection and wrapper behavior used by baseline validation. | pending-review | Treat as inseparable from the `.env` plus `.env.pve-test` overlay contract; do not hand off alone as slice 1. |
| `with-secrets-prod` | `prod-only` | Production-only wrapper with explicit `pve` targeting and approval controls. | exclude | Keep out of baseline; no convergence need on `pve-test`. |
| `.env.template` | `should-backport` | Documents the new layered env contract that baseline operators need once targeting is environment-driven. | pending | Safe to backport even if tracked `.env` handling is deferred. |
| `.env` | `should-backport` | Supplies the new default-safe non-secret baseline used by the wrapper and stack templates. | pending-review | Recommendation: do not backport as a tracked file in slice 1; translate its contract into operator-local `.env` plus templates. |
| `.env.pve-test` | `should-backport` | Supplies the explicit `pve-test` overlay expected by the new wrapper and teardown harness. | pending-review | Recommendation: do not backport as a tracked file in slice 1; keep it operator-local and derive it from `.env.pve-test.template`. |
| `.env.pve-test.template` | `should-backport` | Gives baseline a tracked template for the new `pve-test` overlay contract. | pending | Low-risk documentation/template parity. |
| `.env.pve` | `prod-only` | Production-only non-secret overlay for `with-secrets-prod`. | exclude | Explicitly keep out of baseline; this file encodes `pve` targeting only. |
| `.env.pve.template` | `prod-only` | Production-only overlay template for operators preparing `pve` runs. | exclude | Useful on `prod/pve-infra`, not for `pve-test` convergence. |
| `.gitignore` | `should-backport` | Keeps the new tracked template files and overlay rules consistent if the env-layering model is adopted. | pending-review | Defer until the overlay policy is settled; not ready for slice 1. |
| `.github/workflows/validate.yml` | `should-backport` | Keeps CI branch coverage aligned with the newer branch model during convergence work. | pending | Not required for the teardown gate itself. |
| `.github/workflows/security-scan.yml` | `should-backport` | Keeps security scanning aligned with the newer branch model. | pending | Operational parity, not runtime parity. |
| `.github/copilot-instructions.md` | `should-backport` | Carries the updated promotion-branch workflow guidance used during convergence work. | pending | Useful operator/agent guidance, not runtime logic. |
| `AGENTS.md` | `should-backport` | Same workflow guidance as `.github/copilot-instructions.md`; helps keep the backport branch instructions consistent. | pending | Useful for future handoffs and review steps. |
| `docs/baseline-merge/README.md` | `should-backport` | Defines the convergence program and gives later implementation handoffs stable context. | pending | Process doc, not runtime. |
| `docs/baseline-merge/plan.md` | `should-backport` | Defines the bucket model and implementation order for the convergence branch. | pending | Process doc, not runtime. |
| `scripts/teardown-deploy-test.sh` | `must-backport` | Converts the harness from a hard-coded `pve-test` assumption to explicit target selection and guard checks. | pending-review | Depends on the `with-secrets` plus `.env`/`.env.pve-test` contract; defer from slice 1. |
| `scripts/provision.sh` | `must-backport` | Reconcile/apply path now follows the selected environment and tolerates internal TLS bootstrap state. | pending | Includes environment-aware secret-file hinting and `--no-verify-tls` edge/authentik calls. |
| `scripts/rotate-stack-credentials.py` | `should-backport` | Useful for later follow-on refactors once baseline convergence lands. | deferred | Not needed for the first teardown parity slice. |
| `scripts/dispose-pve-test-counterpart.sh` | `prod-only` | Counterpart-disposal flow is tied to productionization/data-preservation work, not baseline teardown parity. | exclude | Keep out of the first convergence branch. |
| `scripts/plan-pve-infra-teardown.sh` | `prod-only` | Explicitly production-targeted teardown planning. | exclude | Out of scope for baseline convergence. |
| `scripts/preflight-production-mikrotik.py` | `prod-only` | Production-only network preflight. | exclude | Out of scope for baseline convergence. |
| `scripts/preflight-production-mikrotik.sh` | `prod-only` | Production-only network preflight wrapper. | exclude | Out of scope for baseline convergence. |
| `scripts/preflight-network-refactor.sh` | `ignore-artifact` | Network-refactor planning helper, not required to backport lifecycle behavior. | exclude | Treat as refactor-program material. |
| `terraform/README.md` | `should-backport` | Documents the split between shared dev secrets and production-only secret handling. | pending | Helpful operator context once wrapper/env layering changes land. |
| `terraform/SECRETS_PVE_TEMPLATE.md` | `prod-only` | Template for production-only secret inventory. | exclude | Leave out of baseline. |
| `terraform/secrets.pve.enc.yaml` | `prod-only` | Production-only secret store. | exclude | Never backport into baseline. |
| `terraform/lxc/PLATFORM_CONTRACT.md` | `should-backport` | Documents the new inventory/access-path contract and the updated zone/gateway expectations used by runtime code. | pending | Good companion to the executable Terraform changes. |
| `terraform/lxc/main.tf` | `must-backport` | Moves baseline to env-driven targeting, direct-vs-proxyjump access selection, and safer SDN destroy guards. | pending | Core lifecycle parity file. |
| `terraform/lxc/variables.tf` | `must-backport` | Changes the default node to `pve-test` and relaxes optional inputs for env-driven operation. | pending | Required to remove hard-coded production defaults from shared Terraform. |
| `terraform/lxc/templates/inventory.tpl` | `must-backport` | Makes SSH access mode explicit so SDN-attached guests can use direct access instead of forced ProxyJump. | pending | Required by the new `main.tf` access-path logic. |
| `terraform/lxc/generate-zone-members-index.py` | `must-backport` | Keeps generated zone-members stable across shells and supports explicit env expansion when needed. | pending | Supports env-driven stack/network rendering. |
| `terraform/lxc/reconcile-edge.py` | `must-backport` | Makes apply-mode target preflight environment-aware instead of hard-coding `pve-test`. | pending | Required for shared edge reconcile logic. |
| `terraform/lxc/network/pve-test.yaml` | `must-backport` | Carries the updated VLAN/subnet/gateway model and documents the current SDN automation boundary on `pve-test`. | pending-review | Keep in the overall must-backport set, but do not include it in slice 1 because it changes the live `pve-test` network contract and MikroTik prerequisites. |
| `terraform/lxc/network/pve.yaml` | `prod-only` | Production network intent manifest for `pve`. | exclude | Keep environment-specific production data out of baseline. |
| `terraform/lxc/network/pve.zone-members.yaml` | `prod-only` | Generated production zone-members inventory. | exclude | Production-targeted generated data. |
| `terraform/lxc/storage/pve.yaml` | `prod-only` | Production storage manifest. | exclude | Environment-specific production data. |
| `terraform/lxc/ansible/playbooks/configure-keyctl.yml` | `must-backport` | Removes the hard dependency on `pve_host` so the playbook works with the new inventory/access model. | pending | Shared provisioning behavior. |
| `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml` | `must-backport` | Adds target/host assertions and VLAN-zone handling needed by the current SDN model. | pending | Shared SDN attachment behavior. |
| `terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml` | `must-backport` | Restricts SDN destroy to the allowed target environment and uses explicit target metadata. | pending | Prevents unsafe destroy behavior drift. |
| `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml` | `must-backport` | Makes runner name/labels environment-driven instead of hard-coding `pve-test`. | pending | Shared stack provisioning behavior. |
| `terraform/lxc/ansible/playbooks/deploy-coredns.yml` | `must-backport` | Improves CoreDNS readiness/probing so deploy validation is less timing-sensitive. | pending | Runtime fix, not just doc cleanup. |
| `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml` | `must-backport` | Defers Harbor OIDC until Authentik reconcile succeeds and tolerates bootstrap TLS. | pending | Runtime bug fix. |
| `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` | `must-backport` | Uses the same TLS-relaxed Authentik reconcile path as other stacks. | pending | Shared edge/authentik convergence fix. |
| `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml` | `must-backport` | Adds explicit bootstrap waits and converged bootstrap/token setup. | pending | Runtime fix for NetBox bring-up. |
| `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` | `must-backport` | Tightens password validation and removes fragile wait behavior during bootstrap. | pending | Runtime fix for step-ca bring-up. |
| `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml` | `should-backport` | Removes hard-coded Bitwarden metadata from defaults and aligns credential handling with SOPS/manual capture. | pending | Desirable cleanup, but not part of the first teardown gate. |
| `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml` | `must-backport` | Preserves Harbor auth-mode transitions and removes the brittle Bitwarden-only robot-secret flow. | pending | Runtime and operational fix. |
| `terraform/lxc/stacks/apt-cacher-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/authentik-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/authentik-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/authentik-stack/docker-compose.yml` | `should-backport` | Updates stack commentary to the env-driven service-address model. | pending | Comment-only but keeps docs aligned with the runtime contract. |
| `terraform/lxc/stacks/ci-runner-01/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/ci-runner-01/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md` | `should-backport` | Documents the new runner-token acquisition contract used by the playbook. | pending | Helpful once the playbook change lands. |
| `terraform/lxc/stacks/dns-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/dns-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/dns-stack/STACK_CONTRACT.md` | `should-backport` | Updates docs to the segmented lab model instead of a `pve-test`-only framing. | pending | Documentation parity. |
| `terraform/lxc/stacks/harbor-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md` | `should-backport` | Documents the deferred-OIDC behavior introduced by the playbook/runtime fix. | pending | Documentation parity after runtime backport. |
| `terraform/lxc/stacks/monitoring-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/monitoring-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md` | `should-backport` | Reframes docs around the shared lab environment instead of `pve-test` only. | pending | Documentation parity. |
| `terraform/lxc/stacks/netbox-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting and includes the productionized memory/runtime sizing fix. | pending-review | Keep out of slice 1. The diff is a mixed runtime hunk, so NetBox should move as a single later slice rather than split across files or hunks. |
| `terraform/lxc/stacks/netbox-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending-review | Exclude from slice 1 for consistency with `netbox-stack/stack.yaml`; all NetBox changes should move together in a later runtime-focused slice. |
| `terraform/lxc/stacks/netbox-stack/docker-compose.yml` | `should-backport` | Updates commentary to the env-driven address model. | pending | Comment-only but aligns with the stack contract. |
| `terraform/lxc/stacks/netbox-stack/README.md` | `should-backport` | Documents the environment-driven identity and storage model. | pending | Documentation parity. |
| `terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md` | `should-backport` | Reframes docs around the shared segmented-lab model. | pending | Documentation parity. |
| `terraform/lxc/stacks/portainer-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/portainer-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/proxy-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/proxy-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/step-ca-stack/stack.yaml` | `must-backport` | Removes hard-coded `pve-test` targeting from stack metadata. | pending | Shared env-driven targeting. |
| `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl` | `must-backport` | Removes hard-coded `pve-test` input from Terragrunt. | pending | Shared env-driven targeting. |
| `docs/reference/proxmox-terraform-user.md` | `should-backport` | Documents the new SOPS-backed token handling and the shared automation-user pattern. | pending | Helpful operator reference once wrapper/env changes land. |
| `docs/reference/sdn-segment-routing.md` | `should-backport` | Updates the segmented network reference to the current gateway/subnet model and SDN automation state. | pending | Aligns docs with `pve-test` network intent. |
| `docs/reference/production-credentials.md` | `prod-only` | Dedicated production access-control documentation. | exclude | Leave out of baseline. |
| `docs/design/network.md` | `should-backport` | Captures the updated current-state network contract used by `pve-test`. | pending | Useful reference, but not first-slice critical. |
| `docs/stack-lifecycle-refactor/README.md` | `should-backport` | Provides future operator context on shared stack lifecycle assumptions after convergence. | pending | Useful follow-on doc. |
| `docs/stack-lifecycle-refactor/day-2-credential-rotation.md` | `should-backport` | Useful follow-on operator guidance once convergence lands. | deferred | Not required for the first gate. |
| `docs/productionize-refactor/README.md` | `should-backport` | Concise summary of the productionization program that explains why these shared fixes exist. | pending | Keep narrow; do not pull the rest of the program docs by default. |
| `docs/productionize-refactor/pve-production-readiness.md` | `prod-only` | Production readiness packet for `pve`. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/pve-infra-teardown-inventory.md` | `prod-only` | Production-only teardown inventory. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/15-pve-infra-only-teardown-planner.md` | `prod-only` | Production-only teardown planning document. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/runbooks/**` | `prod-only` | Production canary/runbook material, not baseline lifecycle parity logic. | exclude | Covers 12 changed runbook paths. |
| `docs/productionize-refactor/tasks/**` | `prod-only` | Productionization task packets and design docs, not baseline convergence inputs. | exclude | Covers 8 changed task paths including `tasks/README.md`. |
| `docs/productionize-refactor/06-COMPLETION-SUMMARY.md` | `ignore-artifact` | Program-summary artifact, not merge material. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/06-canary-execution-2026-05-22.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/07-dns-canary-execution-packet.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/08-step-ca-canary-execution-packet.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/09-monitoring-canary-closure.md` | `ignore-artifact` | Closure artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/09-monitoring-canary-execution-packet.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/10-netbox-canary-execution-packet.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/11-portainer-canary-closure.md` | `ignore-artifact` | Closure artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/13-ci-runner-canary-execution-packet.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/14-pve-parity-pass-01.md` | `ignore-artifact` | Review/evidence summary, not merge material. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/16-pve-infra-teardown-advisory-summary.md` | `ignore-artifact` | Advisory artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/17-pve-infra-teardown-review-summary.md` | `ignore-artifact` | Review artifact. | exclude | Keep out of baseline. |
| `docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md` | `ignore-artifact` | Execution packet artifact. | exclude | Keep out of baseline. |
| `docs/network-refactor/**` | `ignore-artifact` | Separate refactor-program planning/history material rather than baseline merge input. | exclude | Covers 12 changed paths. |
| `docs/credential-management-refactor/**` | `ignore-artifact` | Follow-on refactor planning, not a prerequisite backport target. | exclude | Covers 2 changed paths. |
| `docs/data-preservation-refactor/**` | `ignore-artifact` | Follow-on refactor planning, not a prerequisite backport target. | exclude | Covers 2 changed paths. |
| `docs/plan/PHASE-DOCUMENT-REVIEW.md` | `ignore-artifact` | Planning artifact unrelated to the convergence implementation slice. | exclude | Keep out of baseline. |
| `CLAUDE.md` | `ignore-artifact` | Auxiliary agent-instruction variant; not needed for the baseline convergence branch. | exclude | `AGENTS.md` is the operator-facing source of truth used here. |

## Explicit Exclusion Rules

- `docs/productionize-refactor/evidence/**` -> `ignore-artifact`
- `docs/productionize-refactor/handoffs/**` -> `ignore-artifact`
- production-only wrappers, overlays, secrets, network manifests, and storage manifests stay `prod-only` unless a later backport slice proves a shared lifecycle dependency
- refactor-program notes, session summaries, and execution packets stay `ignore-artifact` unless a later implementation slice depends on a concrete operational rule captured only there

## Coverage Accounting

- explicit checklist rows: `105`
- wildcard/group rows that expand to additional changed paths: `31`
- filtered branch-delta paths covered by this checklist: `136`
- effective bucket totals by changed path: `39` `must-backport`, `29` `should-backport`, `36` `prod-only`, `32` `ignore-artifact`
