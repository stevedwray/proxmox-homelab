# monitoring-stack Canary Execution Packet (pve)

Use this as the short-form operator run script for the upcoming
`monitoring-stack` production canary on `pve`.

This packet is for future execution handoff only. Do not run mutation steps in a
documentation-prep session.

Detailed references:
- `docs/productionize-refactor/runbooks/09-pve-canary-monitoring.md`
- `docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md`

## Open Decisions (Confirm Before Running)

1. **Pending at run time:** whether `LAB_IP_MONITORING` on `pve` reuses the currently active `pve-test` monitoring IP.
2. **Expected:** monitoring remains in `mgmt_seg` with `${LAB_GW_MGMT}` as gateway and DNS server.
3. **Expected:** Grafana edge route still targets `${LAB_IP_PROXY}` and uses OIDC secrets from environment variables.

Do not start execution if `.env.pve` no longer sets the expected
`LAB_IP_MONITORING`, `LAB_GW_MGMT`, `LAB_IP_PROXY`, `LAB_IP_DNS`, and
`LAB_IP_HARBOR` values for this packet.

## Objective

Validate `monitoring-stack` can be deployed and provisioned on production `pve`
using direct access (`ssh_access_mode: direct`), with compose services running
and health endpoints passing:

- Grafana: `http://127.0.0.1:3000/api/health`
- VictoriaMetrics: `http://127.0.0.1:8428/metrics`
- Loki: `http://127.0.0.1:3100/ready`

## Branch And Context Assumptions

1. Running from repo root: `/home/steve/git/proxmox-homelab`
2. Working branch is short-lived (`work/*`, `feat/*`, `fix/*`, or `task/*`), not `baseline/teardown-validated`, `dev/pve-test`, or `main`
3. `.env` and `.env.pve` are present locally
4. Production commands use `./with-secrets-prod`
5. No live production mutation is executed until explicit operator approval is given

## Pre-Run Decisions And Preconditions

1. Confirm the production MikroTik preflight passes for the live `pve` uplink, required VLAN tags, and current `vlan20-mgmt` ACLs.
2. Confirm whether production is still reusing the active `pve-test` `monitoring-stack` service IP.
3. Confirm `.env.pve` still sets intended `LAB_IP_MONITORING`, `LAB_GW_MGMT`, and `LAB_IP_PROXY` values.
4. Confirm monitoring required inputs are non-empty in production runtime: `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_SECRET`, `AUTHENTIK_SUPERUSER_API_TOKEN`, `LAB_IP_HARBOR`, and `LAB_IP_DNS`.

If IP reuse is confirmed, counterpart disposal is mandatory before production
cutover.

## Execution Sequence (In Order)

Run from repo root.

### 1) Read-Only Target Validation

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_MONITORING=%s\nLAB_GW_MGMT=%s\nLAB_IP_PROXY=%s\n' "$LAB_IP_MONITORING" "$LAB_GW_MGMT" "$LAB_IP_PROXY"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on step 5 terragrunt plan target_node validation.'
fi
```

### 2) Production Router Preflight

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

If this fails with a missing credential error, ensure `MIKROTIK_PASSWORD` is
present in `terraform/secrets.pve.enc.yaml`.

Operator-approved skip: when VLAN state is already validated and unchanged for
this canary window, skip rerunning this command and record all of the following
in evidence:

1. prior passing preflight evidence file path
2. date/time of that prior pass
3. operator unchanged-network attestation

### 3) Required Input Variable Check (Read-Only)

```bash
./with-secrets-prod bash -lc 'for v in GRAFANA_ADMIN_PASSWORD GRAFANA_OAUTH_CLIENT_SECRET AUTHENTIK_SUPERUSER_API_TOKEN LAB_IP_HARBOR LAB_IP_DNS; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

Stop if any line reports `FAIL`.

### 4) Counterpart Check (Always Plan)

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack monitoring-stack --plan
```

### 5) Required Counterpart Destroy (`pve-test`)

Run this only when the service IP is being reused from `pve-test` to `pve`.

Approval point: operator approves counterpart teardown on `pve-test` before production cutover.

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack monitoring-stack --execute
```

### 6) Read-Only Terraform Plan (Production Wrapper)

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/monitoring-stack -no-color
```

Expected signals: `target_node = pve`, `network.zone = mgmt_seg`, intended
IP/gateway, `ansible_playbook = deploy-monitoring-stack`, no unexpected destroy
outside `monitoring-stack`.

### 7) Approval Gate For Production Mutation

Required operator confirmation in chat before apply/provision:

> I approve deploying monitoring-stack to production pve as the next canary validation.

Use one `TASK_APPROVAL` value for all mutation-gated steps in this canary
window (`apply`, `provision --check`, `provision`).

### 8) Apply (Approval-Gated)

```bash
export TASK_APPROVAL="canary-monitoring-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/monitoring-stack -auto-approve -no-color
```

### 9) Post-Apply Inventory Contract Check

`terraform/lxc/stacks/monitoring-stack/inventory.yml` is generated by Terraform,
so inspect it only after the apply step has completed.

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook|stack_name|vmid' terraform/lxc/stacks/monitoring-stack/inventory.yml
rg -n 'monitoring-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/.generated/inventory.pve.yml || true
```

Expected: direct host IP, `ssh_access_mode: direct`, no `ProxyJump`, no
`pve_host` fallback, `ansible_playbook: deploy-monitoring-stack`.

### 10) Provision Check Mode (Post-Apply, Approval-Gated)

```bash
export TASK_APPROVAL="canary-monitoring-pve-$(date +%Y%m%d)"
./with-secrets-prod ./scripts/provision.sh --stack monitoring-stack --check
```

Expected: `unreachable=0 failed=0`.

### 11) Live Provisioning (Post-Apply, Approval-Gated)

```bash
export TASK_APPROVAL="canary-monitoring-pve-$(date +%Y%m%d)"
./with-secrets-prod ./scripts/provision.sh --stack monitoring-stack
```

Expected: `unreachable=0 failed=0`.

### 12) Post-Deploy Health Evidence

```bash
if command -v pct >/dev/null 2>&1; then
	./with-secrets-prod pct list | grep -E '(monitoring-stack|20012)'
else
	echo 'INFO: pct not installed on this workstation; skipping local pct list check.'
fi
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_MONITORING" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_MGMT'"
ssh -G root@"$LAB_IP_MONITORING" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_MONITORING" 'docker compose -f /opt/monitoring-stack/docker-compose.yml ps'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_MONITORING" 'curl -fsS http://127.0.0.1:3000/api/health'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_MONITORING" 'curl -fsS http://127.0.0.1:8428/metrics >/dev/null'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_MONITORING" 'curl -fsS http://127.0.0.1:3100/ready'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_MONITORING" 'nc -z -w3 '"$LAB_IP_PROXY"' 80'
```

### 13) Counterpart Safety Recheck

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack monitoring-stack --plan
```

## Expected Evidence To Collect

1. target validation output (`LAB_IP_MONITORING`, `LAB_GW_MGMT`, `LAB_IP_PROXY`, optional `pvesh get /nodes/pve`)
2. production MikroTik preflight report
3. required input variable check output
4. counterpart plan output and destroy output (if reuse applies)
5. terragrunt plan output showing `pve` + `mgmt_seg` + intended IP/gateway
6. apply output (successful stack mutation on `pve`)
7. post-apply inventory checks showing direct access contract and playbook identity
8. provision check output (`unreachable=0 failed=0`)
9. live provision output (`unreachable=0 failed=0`)
10. post-deploy health outputs: IP/gateway, direct SSH/no ProxyJump, compose status, Grafana health, VictoriaMetrics endpoint, Loki readiness, and Traefik port 80 reachable

Suggested evidence directory setup before mutation-gated commands:

```bash
export EVIDENCE_DIR="docs/productionize-refactor/evidence/monitoring-canary-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCE_DIR"
```

Suggested capture style:

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/monitoring-stack -no-color | tee "$EVIDENCE_DIR/01-plan.txt"
```

## Stop Conditions

Stop immediately and escalate to operator if any occur:

1. `.env.pve` no longer matches expected `LAB_IP_MONITORING`, `LAB_GW_MGMT`, or `LAB_IP_PROXY` for this packet
2. `./with-secrets-prod pvesh get /nodes/pve` fails or indicates wrong target context (when `pvesh` is available)
3. monitoring required inputs are missing or empty
4. MikroTik preflight reports any FAIL for uplink discovery, required VLAN tags, mgmt gateway, or mgmt ACL checks
5. plan shows `pve-test`, wrong zone, wrong IP/gateway, or unexpected destroy outside `monitoring-stack`
6. post-apply inventory shows `ProxyJump` or missing `ssh_access_mode: direct`
7. apply fails or partially fails
8. provision check or live run has any `unreachable` or `failed`
9. Grafana/VictoriaMetrics/Loki health checks fail, or Traefik port 80 is unreachable from the host

Do not improvise additional production mutations outside explicit operator approval.

## Pass/Fail Gate

Pass only if all conditions are true:

1. Target validation and router preflight passed for the intended `pve` canary context.
2. Counterpart disposal happened first when the same monitoring IP was reused.
3. Plan, apply, and inventory stayed pinned to direct-access `monitoring-stack` on `pve`.
4. Provision check and live runs both succeeded.
5. Monitoring health checks passed for Grafana, VictoriaMetrics, and Loki.
