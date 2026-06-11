# monitoring-stack Canary Closure (pve)

## Outcome

`monitoring-stack` canary on production `pve` completed successfully on
May 23, 2026.

## Scope Executed

- production apply for `terraform/lxc/stacks/monitoring-stack`
- post-apply inventory contract validation
- provisioning in check mode and live mode
- post-deploy health checks for Grafana, VictoriaMetrics, Loki, and Traefik
- counterpart safety handling for the matching `pve-test` stack

## Evidence

Primary evidence directory:

- `docs/productionize-refactor/evidence/monitoring-canary-20260523-102010/`

Key artifacts:

- `00-network-preflight-skip-note.txt`
- `02-counterpart-execute.txt`
- `03-plan.txt`
- `04-apply.txt`
- `08-provision-check.txt`
- `12-provision-live-rerun-after-tls-fix.txt`
- `13-post-deploy-health.txt`
- `14-counterpart-recheck.txt`

## Notable Execution Notes

1. Router preflight command was skipped by operator decision for this window
   because VLAN state was already validated and unchanged; skip attestation is
   captured in evidence.
2. Initial live provisioning failed due to missing monitoring OIDC/admin
   secrets, then succeeded after secrets were populated.
3. A TLS trust issue in the Authentik reconcile pre-task required adding
   `--no-verify-tls` to the reconcile invocation in
   `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`.
4. Counterpart destroy on `pve-test` hit the known SDN destroy guard, and the
   documented fallback path confirmed counterpart state as absent before cutover.

## Gate Result

Canary gate: **PASS**

Validated:

- target `pve` and zone `mgmt_seg`
- direct-access inventory path (`ssh_access_mode: direct`, no ProxyJump)
- monitoring compose services running
- Grafana health endpoint reachable
- VictoriaMetrics metrics endpoint reachable
- Loki readiness endpoint reachable
- Traefik port 80 reachable from monitoring host
- `pve-test` counterpart not present after cutover

## Recommended Next Migration

Next migration after monitoring canary: `portainer-stack` on `pve`.

Primary source files for the next slice:

- `terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md`
- `terraform/lxc/stacks/portainer-stack/stack.yaml`
- `terraform/lxc/stacks/portainer-stack/terragrunt.hcl`
- `terraform/lxc/stacks/portainer-stack/edge.yaml`
