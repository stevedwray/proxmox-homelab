# Production Canary Runbook: step-ca-stack on pve

**Target:** `step-ca-stack` on production Proxmox host `pve`
**Zone:** `mgmt_seg` (VLAN 20, gateway from `${LAB_GW_MGMT}`)
**Difficulty:** Low
**Risk:** Low-to-moderate - small service footprint, but it anchors the internal PKI path used by the rest of the platform

## Purpose

Prepare the next low-risk production canary after `dns-stack`. This run verifies
that `step-ca-stack` can be deployed directly on `pve` using the same direct-
access provisioning model, while keeping the DNS record-creation work decoupled
from the canary itself.

**Not a speculative production mutation.** This runbook is an operator-reviewed,
production-guarded command plan. Production apply and provisioning require
explicit operator approval in chat and `TASK_APPROVAL` at execution time.

`./with-secrets-prod` uses a conservative allowlist. In this runbook, read-only
checks use only commands the wrapper actually permits (`pvesh get`,
`terragrunt plan`) or workstation-side commands that do not go through the
wrapper (`ssh`, `grep`, `rg`).

## Why step-ca-stack

1. `step-ca-stack` is the next low-risk service after `apt-cacher-stack` and `dns-stack`.
2. It exercises the PKI trust path used by the broader platform without being an ingress or auth entrypoint.
3. Its canary checks are direct and bounded: SSH reachability, local service health, and reachability to Traefik on port 80 for ACME callback use.
4. It can proceed even while DNS record-creation work is being repaired, because the canary uses direct IP-based validation.

## Important Differences From The dns Canary

Do **not** reuse the `dns-stack` checklist or runbook text as-is.

Stale dns-specific items that do not apply here:

1. UDP/TCP DNS authority and recursion checks are not part of this canary.
2. `LAB_IP_DNS` is not the service under test; this canary focuses on `LAB_IP_STEP_CA`.
3. The service health check is `step ca health`, not a DNS lookup.
4. ACME reachability is validated against Traefik port 80 from the container, not by creating new DNS records.

## Pre-Canary Checklist

**Do not proceed past any FAIL without operator intervention.**

### 1. Code State

- [ ] Work is being prepared from a short-lived branch (`work/*`, `feat/*`, `fix/*`, or `task/*`)
- [ ] The branch is not `baseline/teardown-validated`, `dev/pve-test`, or `main`
- [ ] No uncommitted changes in `terraform/` or `ansible/` that are unrelated to this canary prep
- [ ] Task 07 migration ordering shows `step-ca-stack` as the next low-risk canary after `dns-stack`

### 2. Repository Preconditions

- [ ] `terraform/lxc/stacks/step-ca-stack/stack.yaml` remains environment-decoupled and does not hardcode `pve-test`
- [ ] `terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md` still matches the intended deploy contract
- [ ] `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` remains environment-agnostic

**How to verify:**

```bash
grep -r 'pve-test' terraform/lxc/stacks/step-ca-stack/ terraform/lxc/ansible/playbooks/deploy-step-ca.yml || echo 'PASS'
```

### 3. Target Validation And Duplicate-IP Guard

`step-ca-stack` is expected to reuse the same service IP on `pve-test` and `pve`.
If that remains true at execution time, the disposable `pve-test` counterpart
must be destroyed before the `pve` cutover.

- [ ] `./with-secrets-prod` resolves `TF_VAR_proxmox_node=pve`
- [ ] Production `LAB_IP_STEP_CA`, `LAB_GW_MGMT`, and `LAB_IP_PROXY` resolve to the intended `mgmt_seg` values
- [ ] The operator has confirmed whether `LAB_IP_STEP_CA` is reused between `pve-test` and `pve`
- [ ] If the same IP is reused, the `pve-test` `step-ca-stack` counterpart is destroyed first

**How to verify targeting:**

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_STEP_CA=%s\nLAB_GW_MGMT=%s\nLAB_IP_PROXY=%s\n' "$LAB_IP_STEP_CA" "$LAB_GW_MGMT" "$LAB_IP_PROXY"
./with-secrets-prod pvesh get /nodes/pve
```

**How to inspect and dispose the disposable `pve-test` counterpart:**

```bash
./scripts/dispose-pve-test-counterpart.sh --stack step-ca-stack --plan
```

The helper must be run from the repo root. It preflights `TF_VAR_proxmox_node=pve-test`,
stops the counterpart if needed, then destroys the managed `step-ca-stack`
resources on `pve-test`.
Run `./scripts/dispose-pve-test-counterpart.sh --stack step-ca-stack --execute` only
if the production canary is reusing the same step-ca service IP as the `pve-test`
counterpart.

### 4. Network Preconditions

Network setup is out of scope for this runbook and must already be in place,
but the production router state is now a required read-only preflight because
the first `pve` canary exposed real MikroTik drift.

- [ ] The live `pve` uplink learned by the MikroTik is trunked for VLANs `10`, `20`, `30`, and `40`
- [ ] `${LAB_GW_MGMT}` is assigned on `vlan20-mgmt`
- [ ] `vlan20-mgmt` input ACLs allow ICMP plus UDP/TCP 53 from `${LAB_SUBNET_MGMT_CIDR}` to `${LAB_GW_MGMT}`
- [ ] Traefik remains reachable on port 80 from the `step-ca` host for ACME `httpChallenge`

**How to verify from the operator workstation:**

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

**Expected result:**

1. `Verdict: PASS`
2. The report shows the live `pve` uplink bridge port and confirms VLANs `10/20/30/40` are tagged there
3. Gateway interfaces match `vlan10-build`, `vlan20-mgmt`, `vlan30-edge`, and `vlan40-infra`
4. `mgmt icmp acl`, `mgmt dns udp acl`, and `mgmt dns tcp acl` all pass for the current `192.168.x.0/24` design
5. The `step-ca` host can reach Traefik on port 80 using the configured `LAB_IP_PROXY`

### 5. Production Proxmox Preconditions

- [ ] `pve.gibbsgreatly.xyz` responds and the production API token is valid
- [ ] The required storage backends exist on `pve`
- [ ] The Debian 13 LXC template expected by `step-ca-stack` exists on `pve`

**How to verify:**

```bash
./with-secrets-prod pvesh get /version
./with-secrets-prod pvesh get /nodes/pve
./with-secrets-prod pvesh get /storage
```

### 6. Session Environment

- [ ] `.env` exists locally and contains non-secret defaults only
- [ ] `.env.pve` exists locally and contains the production overlay
- [ ] Production commands will be run through `./with-secrets-prod`
- [ ] There are no lingering manual `TF_VAR_*` exports overriding the wrapper

## Pre-Apply Validation

**Run these checks in order. Stop on any FAIL.**

### Preflight 1: Terragrunt Plan For step-ca-stack On pve

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/step-ca-stack -no-color
```

**Expected plan signals:**

1. `target_node = pve`
2. `hostname = step-ca`
3. `ip_address = ${LAB_IP_STEP_CA}/24`
4. `gateway = ${LAB_GW_MGMT}`
5. `network.zone = mgmt_seg`
6. `dns_server = ${LAB_GW_MGMT}`

**Red flags (stop if any appear):**

1. Any plan output still targets `pve-test`
2. Any plan output indicates `infra_seg` or another non-`mgmt_seg` zone
3. Any unexpected destroy or change outside `step-ca-stack`
4. Storage/template references do not match the production environment

### Preflight 1a: Production Router Preflight

Run the MikroTik preflight before any apply if the packet has not already
captured a passing result for this exact canary window.

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

**Stop if any fail appears for:**

1. `uplink bridge-port discovery`
2. any required `trunk vlan <id>` check
3. `mgmt gateway`
4. `mgmt icmp acl`
5. `mgmt dns udp acl`
6. `mgmt dns tcp acl`
7. `step-ca host can reach Traefik 80`

### Preflight 2: Generated Inventory Inspection

The stack-local generated inventory is the primary artifact to inspect.

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/stacks/step-ca-stack/inventory.yml
```

If a shared production inventory snapshot exists, inspect the `step-ca-stack` stanza there too:

```bash
rg -n 'step-ca-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server' terraform/lxc/.generated/inventory.pve.yml || true
```

**Expected result:**

1. `ansible_host` is the direct `step-ca` guest IP
2. `ssh_access_mode: direct`
3. No `ProxyJump`
4. No `pve_host` fallback for the default SSH path
5. `ansible_playbook: deploy-step-ca`
6. `dns_server` and `contract_dns_server` resolve to `${LAB_GW_MGMT}`

### Preflight 3: Direct-Access Contract Check

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host' terraform/lxc/stacks/step-ca-stack/inventory.yml
```

**Expected result:**

1. `ansible_host` is the direct guest IP
2. `ssh_access_mode: direct`
3. No `ProxyJump`
4. No `pve_host` fallback for the default SSH path
5. No manual host-route priming step is part of this runbook

## Apply Phase

### Authorization Requirement

Production mutations require explicit operator approval in chat.

Before any apply or live provisioning step, the operator must confirm:

> I approve deploying step-ca-stack to production pve as the next canary validation.

### Apply Command

```bash
export TASK_APPROVAL="canary-step-ca-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/step-ca-stack -auto-approve -no-color
```

**Monitor for:**

1. `pve` as the target node, not `pve-test`
2. Correct `mgmt_seg` IP and gateway assignment
3. No unexpected destroy/recreate outside the stack
4. Successful inventory rendering after apply

### Post-Apply Provisioning Check

```bash
./with-secrets-prod ./scripts/provision.sh --stack step-ca-stack --check
```

### Post-Apply Live Provisioning

```bash
./with-secrets-prod ./scripts/provision.sh --stack step-ca-stack
```

### Post-Deploy Health Evidence

```bash
./with-secrets-prod pct list | grep -E '(step-ca-stack|20011)'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_MGMT'"
ssh -G root@"$LAB_IP_STEP_CA" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" hostname
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" 'systemctl is-active step-ca'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" 'step ca health --ca-url https://127.0.0.1 --root /etc/step-ca/certs/root_ca.crt'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" 'nc -z -w3 '"$LAB_IP_PROXY"' 80'
```

## Gate Decision

The step-ca canary passes only if all of the following are true:

1. The `pve` target and intended `mgmt_seg` IP/gateway were validated before apply.
2. The `pve-test` counterpart was destroyed first if the same service IP was being reused.
3. The plan and generated inventory showed direct-access behavior with no default ProxyJump.
4. Provisioning succeeded in both check mode and live mode.
5. `step-ca` is active, `step ca health` passes, and the host can reach Traefik on port 80.
