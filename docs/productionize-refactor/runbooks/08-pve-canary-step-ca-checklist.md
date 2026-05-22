# Production Canary Execution Checklist: step-ca-stack on pve

**Task:** Deploy `step-ca-stack` to `pve` as the next production canary for `mgmt_seg`
**Target:** `pve` (production)
**Canary:** `step-ca-stack`, `mgmt_seg`, VMID `20011`
**Date:** [fill at execution time]

This checklist is step-ca-specific on purpose. Do **not** reuse the shared
`dns-stack` checklist text as-is for this canary. In particular, drop the DNS
authority/recursion checks and focus on the PKI service health path.

Read-only wrapper usage must stay inside the actual `with-secrets-prod`
allowlist. Use `pvesh get` and `terragrunt plan` through the wrapper, and use
workstation-side `ssh`, `rg`, and `grep` for direct guest validation.

---

## Phase 1: Target Validation, Router Preflight, And Counterpart Disposal

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_STEP_CA=%s\nLAB_GW_MGMT=%s\nLAB_IP_PROXY=%s\n' "$LAB_IP_STEP_CA" "$LAB_GW_MGMT" "$LAB_IP_PROXY"
./with-secrets-prod pvesh get /nodes/pve
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
./scripts/dispose-pve-test-counterpart.sh --stack step-ca-stack --plan
```

| Check | Status | Expected |
|---|---|---|
| Wrapper target | ☐ | `.env.pve` values align with `pve`; `./with-secrets-prod pvesh get /nodes/pve` succeeds |
| MikroTik production preflight | ☐ | `Verdict: PASS`; live `pve` uplink tagged for VLANs `10/20/30/40`; mgmt ACLs match `192.168.20.0/24` |
| Production step-ca IP resolved | ☐ | Intended `${LAB_IP_STEP_CA}` for `mgmt_seg` |
| Production gateway resolved | ☐ | Intended `${LAB_GW_MGMT}` |
| Traefik reachability target resolved | ☐ | Intended `${LAB_IP_PROXY}` |
| `pve-test` counterpart disposed first when IP reused | ☐ | Counterpart absent before cutover |

Run the destroy step only if the production step-ca IP is the same IP currently in
use on `pve-test`:

```bash
./scripts/dispose-pve-test-counterpart.sh --stack step-ca-stack --execute
```

---

## Phase 2: Terraform Plan Expectations

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/step-ca-stack -no-color
```

| Check | Status | Expected |
|---|---|---|
| Plan exits successfully | ☐ | Exit code `0` |
| Plan targets production | ☐ | `target_node = pve` |
| Plan uses `mgmt_seg` | ☐ | `network.zone = mgmt_seg` |
| IP and gateway match intended values | ☐ | `${LAB_IP_STEP_CA}/24`, `${LAB_GW_MGMT}` |
| No unrelated stack actions | ☐ | Only `step-ca-stack` changes or refresh |

**Stop if:** the plan references `pve-test`, a non-`mgmt_seg` zone, or an unexpected destroy.

---

## Phase 3: Generated Inventory Expectations

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/stacks/step-ca-stack/inventory.yml
rg -n 'step-ca-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server' terraform/lxc/.generated/inventory.pve.yml || true
```

| Check | Status | Expected |
|---|---|---|
| Stack inventory exists | ☐ | `terraform/lxc/stacks/step-ca-stack/inventory.yml` present |
| Direct host path | ☐ | `ansible_host` is the guest IP |
| SSH mode | ☐ | `ssh_access_mode: direct` |
| ProxyJump removed | ☐ | No `ProxyJump` and no `pve_host` fallback |
| Playbook identity | ☐ | `ansible_playbook: deploy-step-ca` |
| DNS metadata | ☐ | `dns_server` and `contract_dns_server` match `${LAB_GW_MGMT}` |

---

## Phase 4: Apply

These commands are production mutations. Run them only after operator approval
and after exporting `TASK_APPROVAL` in the current shell.

```bash
export TASK_APPROVAL="canary-step-ca-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/step-ca-stack -auto-approve -no-color
```

| Check | Status | Expected |
|---|---|---|
| Apply completed | ☐ | Exit code `0` |
| Target remained `pve` | ☐ | No `pve-test` targeting in output |
| `mgmt_seg` addressing applied | ☐ | Intended `${LAB_IP_STEP_CA}/24`, `${LAB_GW_MGMT}` |
| Stack inventory rendered | ☐ | `terraform/lxc/stacks/step-ca-stack/inventory.yml` present |

---

## Phase 5: Provisioning Checks

These two commands are approval-gated in practice because `./with-secrets-prod`
classifies `./scripts/provision.sh` as a production command. Run them only after
the operator has approved the canary, `TASK_APPROVAL` is exported, and the apply
step above has completed.

```bash
./with-secrets-prod ./scripts/provision.sh --stack step-ca-stack --check
./with-secrets-prod ./scripts/provision.sh --stack step-ca-stack
```

| Check | Status | Expected |
|---|---|---|
| Check mode clean | ☐ | `unreachable=0 failed=0` |
| Live provisioning clean | ☐ | `unreachable=0 failed=0` |
| No default ProxyJump used during provisioning | ☐ | Direct inventory path only |
| No host-route priming dependency remains | ☐ | Direct inventory path only; no default ProxyJump |

Evidence command for the last check:

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host' terraform/lxc/stacks/step-ca-stack/inventory.yml
```

---

## Phase 6: Post-Apply Health Evidence

```bash
./with-secrets-prod pct list | grep -E '(step-ca-stack|20011)'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_MGMT'"
ssh -G root@"$LAB_IP_STEP_CA" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" hostname
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" 'systemctl is-active step-ca'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" 'step ca health --ca-url https://127.0.0.1 --root /etc/step-ca/certs/root_ca.crt'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_STEP_CA" 'nc -z -w3 '"$LAB_IP_PROXY"' 80'
```

| Check | Status | Expected |
|---|---|---|
| Intended IP assigned | ☐ | `${LAB_IP_STEP_CA}/24` on `eth0` |
| Intended gateway assigned | ☐ | default via `${LAB_GW_MGMT}` |
| Gateway reachable | ☐ | ping success |
| Direct SSH works | ☐ | guest IP reachable, `proxyjump=none` |
| step-ca active | ☐ | `active` |
| step-ca health passes | ☐ | `step ca health` exits `0` |
| Traefik port 80 reachable | ☐ | `nc -z` to `${LAB_IP_PROXY}:80` succeeds |

---

## Gate Decision

The step-ca canary passes only if all of the following are true:

1. The `pve` target and intended `mgmt_seg` IP/gateway were validated before apply.
2. The `pve-test` counterpart was destroyed first if the same service IP was being reused.
3. The plan and generated inventory showed direct-access behavior with no default ProxyJump.
4. Provisioning succeeded in both check mode and live mode.
5. step-ca is active, `step ca health` passes, and Traefik port 80 is reachable from the host.
