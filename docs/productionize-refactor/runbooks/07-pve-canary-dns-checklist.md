# Production Canary Execution Checklist: dns-stack on pve

**Task:** Deploy `dns-stack` to `pve` as the next production canary for `mgmt_seg`
**Target:** `pve` (production)
**Canary:** `dns-stack`, `mgmt_seg`, VMID `20013`
**Date:** [fill at execution time]

This checklist is dns-specific on purpose. Do **not** reuse the shared
`apt-cacher-stack` checklist text as-is for this canary. In particular, drop the
legacy `preflight-network-refactor.sh` step and all HTTP/3142 or
`apt-cacher-ng` service checks.

Read-only wrapper usage must stay inside the actual `with-secrets-prod`
allowlist. Use `pvesh get` and `terragrunt plan` through the wrapper, and use
workstation-side `ssh`, `dig`, `rg`, and `grep` for direct guest validation.

---

## Phase 1: Target Validation, Router Preflight, And Counterpart Disposal

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_DNS=%s\nLAB_GW_MGMT=%s\n' "$LAB_IP_DNS" "$LAB_GW_MGMT"
./with-secrets-prod pvesh get /nodes/pve
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
./scripts/dispose-pve-test-counterpart.sh --stack dns-stack --plan
```

| Check | Status | Expected |
|---|---|---|
| Wrapper target | ☐ | `.env.pve` values align with `pve`; `./with-secrets-prod pvesh get /nodes/pve` succeeds |
| MikroTik production preflight | ☐ | `Verdict: PASS`; live `pve` uplink tagged for VLANs `10/20/30/40`; mgmt ACLs match `192.168.20.0/24` |
| Production dns IP resolved | ☐ | Intended `${LAB_IP_DNS}` for `mgmt_seg` |
| Production gateway resolved | ☐ | Intended `${LAB_GW_MGMT}` |
| `pve-test` counterpart disposed first when IP reused | ☐ | Counterpart absent before cutover |

Run the destroy step only if the production dns IP is the same IP currently in
use on `pve-test`:

```bash
./scripts/dispose-pve-test-counterpart.sh --stack dns-stack --execute
```

---

## Phase 2: Terraform Plan Expectations

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/dns-stack -no-color
```

| Check | Status | Expected |
|---|---|---|
| Plan exits successfully | ☐ | Exit code `0` |
| Plan targets production | ☐ | `target_node = pve` |
| Plan uses `mgmt_seg` | ☐ | `network.zone = mgmt_seg` |
| IP and gateway match intended values | ☐ | `${LAB_IP_DNS}/24`, `${LAB_GW_MGMT}` |
| No unrelated stack actions | ☐ | Only `dns-stack` changes or refresh |

**Stop if:** the plan references `pve-test`, a non-`mgmt_seg` zone, or an unexpected destroy.

---

## Phase 3: Generated Inventory Expectations

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/stacks/dns-stack/inventory.yml
rg -n 'dns-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server' terraform/lxc/.generated/inventory.pve.yml || true
```

| Check | Status | Expected |
|---|---|---|
| Stack inventory exists | ☐ | `terraform/lxc/stacks/dns-stack/inventory.yml` present |
| Direct host path | ☐ | `ansible_host` is the guest IP |
| SSH mode | ☐ | `ssh_access_mode: direct` |
| ProxyJump removed | ☐ | No `ProxyJump` and no `pve_host` fallback |
| Playbook identity | ☐ | `ansible_playbook: deploy-coredns` |
| DNS metadata | ☐ | `dns_server` and `contract_dns_server` match `${LAB_GW_MGMT}` |

---

## Phase 4: Apply

These commands are production mutations. Run them only after operator approval
and after exporting `TASK_APPROVAL` in the current shell.

```bash
export TASK_APPROVAL="canary-dns-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/dns-stack -auto-approve -no-color
```

| Check | Status | Expected |
|---|---|---|
| Apply completed | ☐ | Exit code `0` |
| Target remained `pve` | ☐ | No `pve-test` targeting in output |
| `mgmt_seg` addressing applied | ☐ | Intended `${LAB_IP_DNS}/24`, `${LAB_GW_MGMT}` |
| Stack inventory rendered | ☐ | `terraform/lxc/stacks/dns-stack/inventory.yml` present |

---

## Phase 5: Provisioning Checks

These two commands are approval-gated in practice because `./with-secrets-prod`
classifies `./scripts/provision.sh` as a production command. Run them only after
the operator has approved the canary, `TASK_APPROVAL` is exported, and the apply
step above has completed.

```bash
./with-secrets-prod ./scripts/provision.sh --stack dns-stack --check
./with-secrets-prod ./scripts/provision.sh --stack dns-stack
```

| Check | Status | Expected |
|---|---|---|
| Check mode clean | ☐ | `unreachable=0 failed=0` |
| Live provisioning clean | ☐ | `unreachable=0 failed=0` |
| No default ProxyJump used during provisioning | ☐ | Direct inventory path only |
| No host-route priming dependency remains | ☐ | Direct inventory path only; no default ProxyJump |

Evidence command for the last check:

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host' terraform/lxc/stacks/dns-stack/inventory.yml
```

---

## Phase 6: Post-Apply Health Evidence

```bash
./with-secrets-prod pct list | grep -E '(dns-stack|20013)'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_DNS" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_MGMT'"
ssh -G root@"$LAB_IP_DNS" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_DNS" hostname
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_DNS" 'systemctl is-active coredns'
echo 'UDP authoritative:'
dig @"$LAB_IP_DNS" traefik.lab.gibbsgreatly.xyz +short
echo 'TCP authoritative:'
dig +tcp @"$LAB_IP_DNS" traefik.lab.gibbsgreatly.xyz +short
echo 'UDP recursive:'
dig @"$LAB_IP_DNS" github.com +short
echo 'TCP recursive:'
dig +tcp @"$LAB_IP_DNS" github.com +short
```

| Check | Status | Expected |
|---|---|---|
| Intended IP assigned | ☐ | `${LAB_IP_DNS}/24` on `eth0` |
| Intended gateway assigned | ☐ | default via `${LAB_GW_MGMT}` |
| Gateway reachable | ☐ | ping success |
| Direct SSH works | ☐ | guest IP reachable, `proxyjump=none` |
| CoreDNS active | ☐ | `active` |
| UDP authoritative lookup works | ☐ | `dig @${LAB_IP_DNS} traefik.lab.gibbsgreatly.xyz` returns expected answer |
| TCP authoritative lookup works | ☐ | `dig +tcp @${LAB_IP_DNS} traefik.lab.gibbsgreatly.xyz` returns expected answer |
| UDP recursive lookup works | ☐ | `dig @${LAB_IP_DNS} github.com` returns public IPs |
| TCP recursive lookup works | ☐ | `dig +tcp @${LAB_IP_DNS} github.com` returns public IPs |

---

## Gate Decision

The dns canary passes only if all of the following are true:

1. The `pve` target and intended `mgmt_seg` IP/gateway were validated before apply.
2. The `pve-test` counterpart was destroyed first if the same service IP was being reused.
3. The plan and generated inventory showed direct-access behavior with no default ProxyJump.
4. Provisioning succeeded in both check mode and live mode.
5. CoreDNS is active and answers both authoritative and recursive queries over UDP and TCP.
6. No host-route priming workaround is required in the documented flow or observed provisioning path.
