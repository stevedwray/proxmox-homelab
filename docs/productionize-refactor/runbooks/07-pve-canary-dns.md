# Production Canary Runbook: dns-stack on pve

**Target:** `dns-stack` on production Proxmox host `pve`
**Zone:** `mgmt_seg` (VLAN 20, gateway from `${LAB_GW_MGMT}`)
**Difficulty:** Low
**Risk:** Low-to-moderate — low state volume, but this stack is shared DNS infrastructure and must not be cut over with a duplicate IP still live on `pve-test`

## Purpose

Prepare the next low-risk production canary after the successful `apt-cacher-stack`
validation. This run verifies that the direct-access model also holds for
`mgmt_seg` on `pve` and that `dns-stack` can be provisioned and validated without
reintroducing ProxyJump, host-route priming, or pve-test-only assumptions.

**Not a speculative production mutation.** This runbook is an operator-reviewed,
production-guarded command plan. Production apply and provisioning require
explicit operator approval in chat and `TASK_APPROVAL` at execution time.

`./with-secrets-prod` uses a conservative allowlist. In this runbook, read-only
checks use only commands the wrapper actually permits (`pvesh get`,
`terragrunt plan`) or workstation-side commands that do not go through the
wrapper (`ssh`, `dig`, `grep`, `rg`). Do not treat `bash`, `ansible`, or
`pct exec` under `./with-secrets-prod` as read-only shortcuts.

## Why dns-stack

1. `dns-stack` is the next low-risk candidate named in Task 07 after `apt-cacher-stack`.
2. It already passed direct-access representative validation on `pve-test` for `mgmt_seg`.
3. Its health checks are concrete and meaningful: direct SSH, CoreDNS service state,
   authoritative lookup, recursive lookup, and TCP/UDP 53 behavior.
4. It exercises the production management segment without starting with a more central
   stateful application such as `authentik-stack` or `harbor-stack`.

## Important Differences From The apt-cacher Canary

Do **not** reuse the `apt-cacher-stack` checklist or runbook text as-is.

Stale apt-cacher-specific items that do not apply here:

1. `scripts/preflight-network-refactor.sh` is still `pve-test`-oriented and is **not** the sole production gate.
2. HTTP/3142 health checks and `apt-cacher-ng` service checks are irrelevant for `dns-stack`.
3. `infra_seg` IP/gateway expectations must be replaced with `mgmt_seg` IP/gateway expectations.
4. DNS validation for this canary must prove both authoritative and recursive behavior on port 53.

## Pre-Canary Checklist

**Do not proceed past any FAIL without operator intervention.**

### 1. Code State

- [ ] Work is being prepared from a short-lived branch (`work/*`, `feat/*`, `fix/*`, or `task/*`)
- [ ] The branch is not `baseline/teardown-validated`, `dev/pve-test`, or `main`
- [ ] No uncommitted changes in `terraform/` or `ansible/` that are unrelated to this canary prep
- [ ] Productionize Task 06 findings are available to the operator for review

### 2. Repository Preconditions

- [ ] `terraform/lxc/network/pve.yaml` contains `mgmt_seg` on `vmbr0` with VLAN 20
- [ ] `terraform/lxc/stacks/dns-stack/stack.yaml` remains environment-decoupled and does not hardcode `pve-test`
- [ ] `terraform/lxc/stacks/dns-stack/STACK_CONTRACT.md` still matches the intended deploy contract
- [ ] `terraform/lxc/ansible/playbooks/deploy-coredns.yml` remains environment-agnostic

**How to verify:**

```bash
grep -r 'pve-test' terraform/lxc/stacks/dns-stack/ terraform/lxc/ansible/playbooks/deploy-coredns.yml || echo 'PASS'
```

### 3. Target Validation And Duplicate-IP Guard

`dns-stack` is assumed to reuse the same service IP on `pve-test` and `pve`. If
that remains true at execution time, the disposable `pve-test` counterpart must
be destroyed before the `pve` cutover.

- [ ] `./with-secrets-prod` resolves `TF_VAR_proxmox_node=pve`
- [ ] Production `LAB_IP_DNS` and `LAB_GW_MGMT` resolve to the intended `mgmt_seg` values
- [ ] The operator has confirmed whether `LAB_IP_DNS` is reused between `pve-test` and `pve`
- [ ] If the same IP is reused, the `pve-test` `dns-stack` counterpart is destroyed first

**How to verify targeting:**

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_DNS=%s\nLAB_GW_MGMT=%s\n' "$LAB_IP_DNS" "$LAB_GW_MGMT"
./with-secrets-prod pvesh get /nodes/pve
```

**How to inspect and dispose the disposable `pve-test` counterpart:**

```bash
./scripts/dispose-pve-test-counterpart.sh --stack dns-stack --plan
```

The helper must be run from the repo root. It preflights `TF_VAR_proxmox_node=pve-test`,
stops the counterpart if needed, then destroys the managed `dns-stack` resources on `pve-test`.
Run `./scripts/dispose-pve-test-counterpart.sh --stack dns-stack --execute` only
if the production canary is reusing the same dns service IP as the `pve-test`
counterpart.

### 4. Network Preconditions

Network setup is **out of scope** for this runbook and must already be in place,
but the production router state is now a required read-only preflight because
the first `pve` dns canary exposed real MikroTik drift.

- [ ] The live `pve` uplink learned by the MikroTik is trunked for VLANs `10`, `20`, `30`, and `40`
- [ ] `${LAB_GW_MGMT}` is assigned on `vlan20-mgmt`
- [ ] `vlan20-mgmt` input ACLs allow ICMP plus UDP/TCP 53 from `${LAB_SUBNET_MGMT_CIDR}` to `${LAB_GW_MGMT}`
- [ ] Recursive egress path from `mgmt_seg` through the MikroTik/upstream DNS path is available
- [ ] The operator can resolve both an internal and a public name against `${LAB_GW_MGMT}` before cutover

**How to verify from the operator workstation:**

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

**Expected result:**

1. `Verdict: PASS`
2. The report shows the live `pve` uplink bridge port and confirms VLANs `10/20/30/40` are tagged there
3. Gateway interfaces match `vlan10-build`, `vlan20-mgmt`, `vlan30-edge`, and `vlan40-infra`
4. `mgmt icmp acl`, `mgmt dns udp acl`, and `mgmt dns tcp acl` all pass for the current `192.168.x.0/24` design
5. The gateway answers both an internal lab query and a public recursive query

### 5. Production Proxmox Preconditions

- [ ] `pve.gibbsgreatly.xyz` responds and the production API token is valid
- [ ] The required storage backends exist on `pve`
- [ ] The Debian 13 LXC template expected by `dns-stack` exists on `pve`

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

---

## Pre-Apply Validation

**Run these checks in order. Stop on any FAIL.**

### Preflight 1: Terragrunt Plan For dns-stack On pve

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/dns-stack -no-color
```

**Expected plan signals:**

1. `target_node = pve`
2. `hostname = dns-stack`
3. `ip_address = ${LAB_IP_DNS}/24`
4. `gateway = ${LAB_GW_MGMT}`
5. `network.zone = mgmt_seg`
6. `dns_server = ${LAB_GW_MGMT}`

**Red flags (stop if any appear):**

1. Any plan output still targets `pve-test`
2. Any plan output indicates `infra_seg` or another non-`mgmt_seg` zone
3. Any unexpected destroy or change outside `dns-stack`
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
7. `mgmt gateway internal dns`
8. `mgmt gateway public dns`

### Preflight 2: Generated Inventory Inspection

The stack-local generated inventory is the primary artifact to inspect.

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/stacks/dns-stack/inventory.yml
```

If a shared production inventory snapshot exists, inspect the `dns-stack` stanza there too:

```bash
rg -n 'dns-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server' terraform/lxc/.generated/inventory.pve.yml || true
```

**Expected result:**

1. `ansible_host` is the direct `dns-stack` guest IP
2. `ssh_access_mode: direct`
3. No `ProxyJump`
4. No `pve_host` fallback for the default SSH path
5. `ansible_playbook: deploy-coredns`
6. `dns_server` and `contract_dns_server` resolve to `${LAB_GW_MGMT}`

### Preflight 3: Direct-Access Contract Check

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host' terraform/lxc/stacks/dns-stack/inventory.yml
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

> I approve deploying dns-stack to production pve as the next canary validation.

### Apply Command

```bash
export TASK_APPROVAL="canary-dns-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/dns-stack -auto-approve -no-color
```

**Monitor for:**

1. `pve` as the target node, not `pve-test`
2. Correct `mgmt_seg` IP and gateway assignment
3. No unexpected destroy/recreate outside the stack
4. Successful inventory rendering after apply

### Post-Apply Provisioning Check

Now that the stack inventory and target guest should exist, run the check-mode
provisioning pass through the production wrapper:

```bash
export TASK_APPROVAL="canary-dns-pve-$(date +%Y%m%d)"
./with-secrets-prod ./scripts/provision.sh --stack dns-stack --check
```

**Expected result:** play recap ends with `unreachable=0 failed=0`.

If this fails, stop before the live provisioning step. Fix the direct-access,
inventory, or environment issue first.

### Provisioning Command

After a successful apply, run live provisioning through the production wrapper:

```bash
export TASK_APPROVAL="canary-dns-pve-$(date +%Y%m%d)"
./with-secrets-prod ./scripts/provision.sh --stack dns-stack
```

**Expected result:** provisioning completes with `unreachable=0 failed=0` and
the CoreDNS deploy tasks finish cleanly.

### Rollback Guidance

If apply or provisioning fails partway through, stop and hand control back to the
operator. Do not improvise extra production mutations. The recovery path should
be explicitly approved before any destroy/retry action.

---

## Post-Deploy Service Validation

Run the following evidence collection promptly after a successful deploy.

### 1. LXC Presence And Intended mgmt_seg IP/Gateway

```bash
./with-secrets-prod pct list | grep -E '(dns-stack|20013)'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_DNS" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_MGMT'"
```

**Success criteria:**

1. VMID `20013` exists on `pve`
2. `eth0` shows the intended `${LAB_IP_DNS}/24`
3. Default route points at `${LAB_GW_MGMT}`
4. Gateway ping succeeds

### 2. Direct SSH Works With No Default ProxyJump

```bash
ssh -G root@"$LAB_IP_DNS" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_DNS" hostname
```

**Success criteria:**

1. `proxyjump=none`
2. SSH reaches the guest directly by IP
3. No manual host-route priming or Proxmox-side jump path is needed

### 3. CoreDNS Service State

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_DNS" 'systemctl is-active coredns'
```

**Expected result:** `active`

### 4. TCP/UDP 53 Behavior, Authoritative Lookup, And Recursive Lookup

```bash
echo 'UDP authoritative:'
dig @"$LAB_IP_DNS" traefik.lab.gibbsgreatly.xyz +short
echo 'TCP authoritative:'
dig +tcp @"$LAB_IP_DNS" traefik.lab.gibbsgreatly.xyz +short
echo 'UDP recursive:'
dig @"$LAB_IP_DNS" github.com +short
echo 'TCP recursive:'
dig +tcp @"$LAB_IP_DNS" github.com +short
```

**Success criteria:**

1. UDP authoritative lookup returns the expected proxy IP for `traefik.lab.gibbsgreatly.xyz`
2. TCP authoritative lookup also succeeds
3. UDP recursive lookup for `github.com` returns one or more public IPs
4. TCP recursive lookup for `github.com` also succeeds

### 5. Counterpart Safety Recheck

```bash
./scripts/dispose-pve-test-counterpart.sh --stack dns-stack --plan
```

**Expected result:** the `pve-test` counterpart is absent or at least not running.

---

## Evidence Checklist

Collect and save the following for the execution record:

| Item | Source | Expected |
|---|---|---|
| Target validation | `.env.pve` values + `./with-secrets-prod pvesh get /nodes/pve` | `TF_VAR_proxmox_node=pve` |
| Counterpart disposition | `dispose-pve-test-counterpart.sh --plan/--execute` | `pve-test` counterpart destroyed first if IP reused |
| Terraform plan | `terragrunt plan` | `pve`, `mgmt_seg`, intended IP/gateway |
| Generated inventory | `terraform/lxc/stacks/dns-stack/inventory.yml` | direct host IP, no ProxyJump |
| Provision check | `./with-secrets-prod ./scripts/provision.sh --stack dns-stack --check` | `unreachable=0 failed=0` after apply and approval export |
| Provision live run | `./with-secrets-prod ./scripts/provision.sh --stack dns-stack` | `unreachable=0 failed=0` |
| Guest IP/gateway | direct SSH to `root@${LAB_IP_DNS}` | intended `mgmt_seg` IP and `${LAB_GW_MGMT}` |
| Direct SSH | `ssh root@${LAB_IP_DNS}` | succeeds with no ProxyJump |
| CoreDNS service | direct SSH `systemctl is-active coredns` | `active` |
| Authoritative lookup | `dig @${LAB_IP_DNS} traefik.lab.gibbsgreatly.xyz` | expected proxy IP |
| Recursive lookup | `dig @${LAB_IP_DNS} github.com` | one or more public IPs |
| Direct-access contract | `inventory.yml` + SSH/provision evidence | no default ProxyJump or host-route priming step |

---

## Success Criteria

The dns canary passes if all of the following are true:

1. The container receives the intended `mgmt_seg` IP and gateway on `pve`.
2. Direct SSH works by guest IP with no default ProxyJump.
3. `coredns` is active after live provisioning.
4. TCP and UDP 53 behavior are both validated.
5. `dig @<dns-ip> traefik.lab.gibbsgreatly.xyz` succeeds authoritatively.
6. `dig @<dns-ip> github.com` succeeds recursively.
7. No host-route priming workaround is required in the documented flow or observed provisioning path.
8. If the same IP is reused, the `pve-test` counterpart was destroyed first.

## Related Documents

- [Task 06: Canary Validation Gate](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md)
- [Task 07: Incremental Migration Plan](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md)
- [Production Canary Runbook: apt-cacher-stack on pve](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/06-pve-canary-apt-cacher.md)
- [Production Canary Execution Checklist](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/EXECUTION-CHECKLIST.md)
- [dns-stack Stack Contract](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/dns-stack/STACK_CONTRACT.md)
- [Session 7 Summary](/home/steve/git/proxmox-homelab/docs/network-refactor/session-7-summary.md)

## Residual Open Questions

1. Does production `LAB_IP_DNS` intentionally match the `pve-test` service IP at execution time, or is the duplicate-IP safeguard only a fallback?
2. Should the operator prefer full destroy (`--execute`) or a temporary stop-only action if the counterpart must be kept for rollback?
3. What exact authoritative answer should be treated as the pass value for `traefik.lab.gibbsgreatly.xyz` if the proxy IP changes before execution?
4. Is there any production firewall policy outside the current runbook that would allow SSH but block TCP 53, requiring a separate operator sign-off?
