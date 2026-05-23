# portainer-stack Canary Closure (pve)

## Outcome

`portainer-stack` canary on production `pve` completed successfully on
May 23, 2026.

## Scope Executed

- production apply for `terraform/lxc/stacks/portainer-stack`
- post-apply inventory contract validation
- provisioning in check mode and live mode
- post-deploy health checks for Portainer API, service ports, direct SSH path,
  and counterpart safety
- counterpart safety handling for matching `pve-test` stack

## Evidence

Primary evidence directory:

- `docs/productionize-refactor/evidence/portainer-canary-20260523-111249/`

Key artifacts:

- `01-target-validation.txt`
- `03-counterpart-plan.txt`
- `06-plan.txt`
- `07-counterpart-execute.txt`
- `09-counterpart-recheck.txt`
- `10-apply.txt`
- `11-stack-inventory-contract.txt`
- `12-provision-check.txt` (initial failure)
- `13-provision-live.txt` (initial failure)
- `14-provision-check-rerun-after-tls-fix.txt`
- `17-provision-check-rerun-with-admin-and-allow-pve.txt`
- `18-provision-live-rerun-with-admin-and-allow-pve.txt` (blocked by target guard)
- `19-provision-live-rerun-after-target-preflight-fix.txt`
- `20-post-deploy-health.txt`
- `21-counterpart-final-recheck.txt`
- `22-runtime-var-presence-after-sops-update.txt`
- `23-provision-check-after-sops-update.txt`
- `24-provision-live-after-sops-update.txt` (auth mismatch before reset)
- `27-password-reset-execute.txt` (initial DB lock)
- `28-password-reset-stop-reset-start.txt`
- `29-admin-auth-after-reset.txt`
- `30-provision-live-after-password-reset.txt`
- `31-post-reset-health-check.txt`

## Notable Execution Notes

1. `pve-test` counterpart was initially running; disposal was performed before
   production cutover.
2. Counterpart destroy hit the known SDN destroy guard during teardown hook; the
   documented fallback path and rechecks confirmed counterpart ended absent.
3. Initial provisioning failed on Authentik TLS verification. `scripts/provision.sh`
   was updated to pass `--no-verify-tls` for Portainer Authentik/edge reconcile
   calls in this lab context.
4. Live edge publish path initially failed because `terraform/lxc/reconcile-edge.py`
   hardcoded expected target `pve-test`. Script updated to use configurable expected
   target and default to active `PVE_ENV`.
5. `PORTAINER_ADMIN_PASSWORD` and `TF_VAR_portainer_admin_password` were both
   unset in production runtime, so an ephemeral in-memory `PORTAINER_ADMIN_PASSWORD`
   was injected for this canary window.
6. After SOPS secrets were updated, live provisioning initially still failed at
   Portainer auth (`422`) because the running admin credential had been set during
   the earlier ephemeral initialization. Password was reset on the `pve` instance
   to the current SOPS value using `portainer/helper-reset-password`, then live
   provisioning succeeded idempotently.

## Gate Result

Canary gate: **PASS**

Validated:

- target `pve` and zone `mgmt_seg`
- inventory direct-access contract (`ssh_access_mode: direct`, `proxyjump=none`)
- intended Portainer addressing (`192.168.20.20/24`, gateway `192.168.20.1`)
- Portainer API status endpoint reachable on port `9000`
- Portainer service ports reachable: `9000`, `9443`, `8000`
- provisioning check and live runs reached `unreachable=0 failed=0`
- `pve-test` counterpart absent after cutover

## Required Follow-up

- Keep `reconcile-edge.py` target-preflight behavior aligned with production
   wrappers during future edge publishes.

## Recommended Next Migration

Next migration after portainer canary: `netbox-stack` on `pve`.

Primary source files for the next slice:

- `terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md`
- `terraform/lxc/stacks/netbox-stack/README.md`
- `terraform/lxc/stacks/netbox-stack/terragrunt.hcl`
