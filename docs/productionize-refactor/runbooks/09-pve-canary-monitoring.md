# Production Canary Runbook: monitoring-stack on pve

**Target:** `monitoring-stack` on production Proxmox host `pve`
**Zone:** `mgmt_seg` (VLAN 20, gateway from `${LAB_GW_MGMT}`)
**Difficulty:** Low-to-moderate
**Risk:** Moderate - bounded blast radius as a single stack, but depends on Harbor/Auth/Proxy and includes OIDC + compose state

## Purpose

Prepare the next low-risk production canary after `step-ca-stack`. This run verifies
that `monitoring-stack` can be deployed directly on `pve` using the same direct-
access provisioning model, while preserving the stack contract for Grafana, Loki,
VictoriaMetrics, and Authentik OIDC reconciliation.

**Not a speculative production mutation.** This runbook is an operator-reviewed,
production-guarded command plan. Production apply and provisioning require
explicit operator approval in chat and `TASK_APPROVAL` at execution time.

`./with-secrets-prod` uses a conservative allowlist. In this runbook, read-only
checks use only commands the wrapper actually permits (`pvesh get`,
`terragrunt plan`) or workstation-side commands that do not go through the
wrapper (`ssh`, `grep`, `rg`).

Use this runbook together with:

- `docs/productionize-refactor/runbooks/09-pve-canary-monitoring-checklist.md`
- `docs/productionize-refactor/09-monitoring-canary-execution-packet.md`

## Why monitoring-stack

1. `monitoring-stack` is the next migration after `step-ca-stack` in the current productionize ordering.
2. It remains lower-risk than ingress/auth cutovers because the canary is isolated to one service container with known ports and checks.
3. It validates a realistic compose + OIDC integration path used by other platform stacks.
4. Its post-deploy checks are concrete and bounded: direct SSH reachability, compose service state, and HTTP health endpoints on ports `3000`, `8428`, and `3100`.

## Important Differences From The step-ca Canary

Do **not** reuse `step-ca-stack` checklist or runbook text as-is.

Stale step-ca-specific items that do not apply here:

1. `step ca health` is not part of this canary.
2. Monitoring depends on compose services and Grafana/OIDC variables, not step-ca bootstrap password files.
3. Health checks are Grafana/VictoriaMetrics/Loki endpoints, not step-ca service state.
4. Monitoring includes Harbor/Auth dependencies and may trigger temporary DNS fallback logic during provisioning.

## Pre-Canary Checklist

**Do not proceed past any FAIL without operator intervention.**

### 1. Code State

- [ ] Work is being prepared from a short-lived branch (`work/*`, `feat/*`, `fix/*`, or `task/*`)
- [ ] The branch is not `baseline/teardown-validated`, `dev/pve-test`, or `main`
- [ ] No uncommitted changes in `terraform/` or `ansible/` that are unrelated to this canary prep
- [ ] Task 07 migration ordering shows `monitoring-stack` as the next canary after `step-ca-stack`

### 2. Repository Preconditions

- [ ] `terraform/lxc/stacks/monitoring-stack/stack.yaml` remains environment-decoupled and does not hardcode `pve-test`
- [ ] `terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md` still matches the intended deploy contract
- [ ] `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` remains environment-agnostic
- [ ] `terraform/lxc/stacks/monitoring-stack/edge.yaml` still defines the Grafana route and OIDC secret annotations

**How to verify:**

```bash
grep -r 'pve-test' terraform/lxc/stacks/monitoring-stack/ terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml || echo 'PASS'
rg -n 'LAB_IP_MONITORING|GRAFANA_OAUTH_CLIENT_SECRET|AUTHENTIK_SUPERUSER_API_TOKEN|ansible_playbook' terraform/lxc/stacks/monitoring-stack/stack.yaml terraform/lxc/stacks/monitoring-stack/edge.yaml terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md
```

### 3. Target Validation And Duplicate-IP Guard

`monitoring-stack` is expected to reuse the same service IP on `pve-test` and
`pve`. If that remains true at execution time, the disposable `pve-test`
counterpart must be destroyed before the `pve` cutover.

- [ ] `./with-secrets-prod` resolves `TF_VAR_proxmox_node=pve`
- [ ] Production `LAB_IP_MONITORING`, `LAB_GW_MGMT`, and `LAB_IP_PROXY` resolve to intended `mgmt_seg` values
- [ ] The operator has confirmed whether `LAB_IP_MONITORING` is reused between `pve-test` and `pve`
- [ ] If the same IP is reused, the `pve-test` `monitoring-stack` counterpart is destroyed first

**How to verify targeting:**

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_MONITORING=%s\nLAB_GW_MGMT=%s\nLAB_IP_PROXY=%s\n' "$LAB_IP_MONITORING" "$LAB_GW_MGMT" "$LAB_IP_PROXY"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on terragrunt plan target_node validation below.'
fi
```

**How to inspect and dispose the disposable `pve-test` counterpart:**

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack monitoring-stack --plan
```

The helper must be run from the repo root. It preflights `TF_VAR_proxmox_node=pve-test`,
stops the counterpart if needed, then destroys the managed `monitoring-stack`
resources on `pve-test`.
Run `env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack monitoring-stack --execute`
only if the production canary is reusing the same monitoring service IP as the
`pve-test` counterpart.

### 4. Network Preconditions

Network setup is out of scope for this runbook and must already be in place.
By default, production router state is validated with the MikroTik preflight.
An operator may explicitly skip rerunning that command for this canary window
when VLAN state is already validated and unchanged since the last passing run.

- [ ] The live `pve` uplink learned by the MikroTik is trunked for VLANs `10`, `20`, `30`, and `40`
- [ ] `${LAB_GW_MGMT}` is assigned on `vlan20-mgmt`
- [ ] `vlan20-mgmt` input ACLs allow ICMP plus UDP/TCP 53 from `${LAB_SUBNET_MGMT_CIDR}` to `${LAB_GW_MGMT}`
- [ ] `${LAB_IP_MONITORING}` has path to Harbor/Auth/Proxy service endpoints required by monitoring provisioning

**How to verify from the operator workstation:**

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

The preflight requires `MIKROTIK_PASSWORD` in the runtime environment. For
production canaries, ensure it is available via `terraform/secrets.pve.enc.yaml`
before running this step.

**Operator-approved skip path:**

If VLAN state was already validated and no network changes occurred, document
the skip decision and evidence path for this canary window, then continue.

Minimum skip note to capture in evidence/logs:

1. date/time of prior passing preflight evidence
2. evidence file path used as baseline
3. operator statement that VLAN and ACL state is unchanged

### 5. Monitoring Input Preconditions

`deploy-monitoring-stack.yml` has mandatory env requirements. Treat any missing
or empty value as a hard stop before apply/provision.

- [ ] `GRAFANA_ADMIN_PASSWORD` is non-empty
- [ ] `GRAFANA_OAUTH_CLIENT_SECRET` is non-empty
- [ ] `AUTHENTIK_SUPERUSER_API_TOKEN` is non-empty
- [ ] `LAB_IP_HARBOR` is set to the intended Harbor endpoint
- [ ] `LAB_IP_DNS` is set to the intended DNS endpoint used by Docker/Grafana

**How to verify:**

```bash
./with-secrets-prod bash -lc 'for v in GRAFANA_ADMIN_PASSWORD GRAFANA_OAUTH_CLIENT_SECRET AUTHENTIK_SUPERUSER_API_TOKEN LAB_IP_HARBOR LAB_IP_DNS; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

### 6. Session Environment

- [ ] `.env` exists locally and contains non-secret defaults only
- [ ] `.env.pve` exists locally and contains the production overlay
- [ ] Production commands will be run through `./with-secrets-prod`
- [ ] There are no lingering manual `TF_VAR_*` exports overriding the wrapper

## Pre-Apply Validation

**Run these checks in order. Stop on any FAIL.**

### Preflight 1: Terragrunt Plan For monitoring-stack On pve

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/monitoring-stack -no-color
```

**Expected plan signals:**

1. `target_node = pve`
2. `hostname = monitoring-stack`
3. `ip_address = ${LAB_IP_MONITORING}/24`
4. `gateway = ${LAB_GW_MGMT}`
5. `network.zone = mgmt_seg`
6. `dns_server = ${LAB_GW_MGMT}`
7. `ansible_playbook = deploy-monitoring-stack`

**Red flags (stop if any appear):**

1. Any plan output still targets `pve-test`
2. Any plan output indicates a non-`mgmt_seg` zone
3. Any unexpected destroy or change outside `monitoring-stack`
4. Storage/template references do not match the production environment

### Preflight 1a: Production Router Preflight

Run the MikroTik preflight before any apply if the packet has not already
captured a passing result for this exact canary window and the operator has not
approved a skip based on unchanged VLAN state.

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

If this step is skipped by operator decision, record the prior evidence path
and unchanged-network attestation in the canary evidence folder.

**Stop if any fail appears for:**

1. `uplink bridge-port discovery`
2. any required `trunk vlan <id>` check
3. `mgmt gateway`
4. `mgmt icmp acl`
5. `mgmt dns udp acl`
6. `mgmt dns tcp acl`

### Preflight 2: Evidence Directory Preparation

Create an evidence directory before any production mutation so all command
output for this canary window is captured in one place.

```bash
export EVIDENCE_DIR="docs/productionize-refactor/evidence/monitoring-canary-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCE_DIR"
echo "$EVIDENCE_DIR"
```

Use `tee` while executing mutation-gated steps in the future canary session.
Example:

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/monitoring-stack -no-color | tee "$EVIDENCE_DIR/01-plan.txt"
```

## Apply Phase

### Authorization Requirement

Production mutations require explicit operator approval in chat.

Before any apply or live provisioning step, the operator must confirm:

> I approve deploying monitoring-stack to production pve as the next canary validation.

### Apply Command

```bash
export TASK_APPROVAL="canary-monitoring-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/monitoring-stack -auto-approve -no-color
```

**Monitor for:**

1. apply exits successfully
2. no fallback or accidental reference to `pve-test`
3. generated inventory points to direct guest access for `monitoring-stack`

## Post-Apply Validation

### 1) Inventory Contract Checks

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook|stack_name|vmid' terraform/lxc/stacks/monitoring-stack/inventory.yml
rg -n 'monitoring-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/.generated/inventory.pve.yml || true
```

Expected:

1. `ansible_host` is `${LAB_IP_MONITORING}`
2. `ssh_access_mode: direct`
3. no `ProxyJump` and no `pve_host` fallback for default SSH path
4. `ansible_playbook: deploy-monitoring-stack`
5. `dns_server` and `contract_dns_server` align with `${LAB_GW_MGMT}`

### 2) Provisioning Check And Live Apply

```bash
export TASK_APPROVAL="canary-monitoring-pve-$(date +%Y%m%d)"
./with-secrets-prod ./scripts/provision.sh --stack monitoring-stack --check
./with-secrets-prod ./scripts/provision.sh --stack monitoring-stack
```

Expected: both runs end with `unreachable=0 failed=0`.

### 3) Post-Deploy Health Evidence

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

### 4) Counterpart Safety Recheck

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack monitoring-stack --plan
```

## Evidence Checklist

Capture at least:

1. target validation output (`LAB_IP_MONITORING`, `LAB_GW_MGMT`, `LAB_IP_PROXY`)
2. production router preflight output
3. counterpart plan/destroy output (when IP reuse applies)
4. terragrunt plan output showing `pve` + `mgmt_seg` + intended IP/gateway
5. apply output
6. post-apply inventory contract checks
7. provision check and live run outputs
8. health outputs for compose status, Grafana `api/health`, VictoriaMetrics `/metrics`, Loki `/ready`, and Traefik port `80` reachability

## Stop Conditions

Stop immediately and escalate to operator if any occur:

1. `.env.pve` no longer matches expected `LAB_IP_MONITORING`, `LAB_GW_MGMT`, or `LAB_IP_PROXY`
2. monitoring mandatory inputs are missing (`GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_SECRET`, `AUTHENTIK_SUPERUSER_API_TOKEN`, `LAB_IP_HARBOR`, `LAB_IP_DNS`)
3. MikroTik preflight reports any FAIL for uplink discovery, required VLAN tags, gateway, or ACL checks
4. plan shows `pve-test`, wrong zone, wrong IP/gateway, or unexpected destroy outside `monitoring-stack`
5. post-apply inventory shows `ProxyJump` or missing `ssh_access_mode: direct`
6. apply fails or partially fails
7. provision check or live run has any `unreachable` or `failed`
8. any of Grafana/VictoriaMetrics/Loki health checks fail

Do not improvise additional production mutations outside explicit operator approval.

## Pass/Fail Gate

Pass only if all conditions are true:

1. Target validation and router preflight succeeded for the intended `pve`/`mgmt_seg` context.
2. Counterpart disposal was completed first when IP reuse applied.
3. Plan/apply/inventory all remained pinned to direct-access `monitoring-stack` on `pve`.
4. Provision check and live runs both succeeded.
5. Post-deploy health checks passed for Grafana, VictoriaMetrics, and Loki.
