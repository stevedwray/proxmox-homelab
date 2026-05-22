# Production Canary Execution Checklist

**Task:** Deploy apt-cacher-stack to pve as low-risk network validation
**Target:** pve (production)
**Canary:** apt-cacher-stack, infra_seg, 192.168.40.11
**Date:** [to be filled in at execution time]

---

## Phase 1: Pre-Execution Network Validation

**These are operator responsibilities — AI system cannot perform these.**

| Check | Status | Notes |
|---|---|---|
| MikroTik VLAN 40 configured on production switch | ☐ | Must be in place before canary |
| MikroTik gateway IP 192.168.40.1 assigned and reachable | ☐ | `ping 192.168.40.1` from workstation |
| Firewall rules allow TCP 22 (SSH) and TCP 3142 (apt-cacher) | ☐ | Check MikroTik ACL rules |
| Workstation has route to 192.168.40.0/24 | ☐ | `route -n` on workstation |
| DNS forwarding on MikroTik working | ☐ | `dig @192.168.20.1 github.com` returns IPs |

**If any check fails:** Stop and do not proceed. Contact network operator.

---

## Phase 2: Production Proxmox Verification

**Run before attempting apply:**

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'pveversion && echo "---" && pvesh get /nodes/pve && echo "---" && pvesh get /storage | grep infrastructure-containers'
```

| Check | Status | Expected |
|---|---|---|
| pve host responds | ☐ | `pveversion` returns version |
| Proxmox token valid | ☐ | No HTTP 401 errors |
| Storage backends exist | ☐ | `infrastructure-containers`, `local-zfs` listed |

**If any check fails:** Stop. Verify Proxmox token or host access.

---

## Phase 3: Environment Setup

```bash
# Confirm these files exist (not in git):
ls -l .env .env.pve

# Confirm secrets are accessible:
./with-secrets-prod bash -c 'echo $TF_VAR_proxmox_node'  # Should print: pve
./with-secrets-prod bash -c 'echo $PROXMOX_TOKEN_SECRET' # Should print: (token value, starred out)
```

| Check | Status | Expected |
|---|---|---|
| .env exists | ☐ | Non-secret config |
| .env.pve exists | ☐ | Production overrides |
| TF_VAR_proxmox_node = pve | ☐ | Verified by command above |
| SOPS secrets accessible | ☐ | No errors, environment loads |

**If any check fails:** Stop. Check env file sourcing order.

---

## Phase 4: Pre-Apply Validation

**Run these in sequence. Stop on any failure.**

### 4a. Preflight Script

```bash
./with-secrets bash -c 'TF_VAR_proxmox_node=pve scripts/preflight-network-refactor.sh \
  --save-evidence docs/productionize-refactor/evidence/ 192.168.40.11'
```

| Check | Status | Expected |
|---|---|---|
| Preflight exit code | ☐ | 0 (all checks pass) |
| TF_VAR_proxmox_node guard | ☐ | pve |
| SDN gateways reachable | ☐ | All 4 gateways (x.40.1, x.20.1, x.30.1, x.10.1) ping successful |
| DNS via MikroTik | ☐ | Resolves internal and public names |

**Evidence file location:** `docs/productionize-refactor/evidence/preflight-evidence-*.txt`

### 4b. Terraform Plan

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'cd terraform/lxc && terragrunt plan \
  -target=module.apt-cacher-stack \
  -out=/tmp/apt-cacher.plan 2>&1 | tee /tmp/plan.log'
```

| Check | Status | Expected |
|---|---|---|
| Plan exits successfully | ☐ | Exit code 0 |
| Plan targets pve not pve-test | ☐ | `node = "pve"` in plan output |
| Plan creates only apt-cacher resources | ☐ | No other stacks affected |
| Storage backend correct | ☐ | Uses `infrastructure-containers` |

### 4c. Generated Inventory Check

```bash
ls -l terraform/lxc/.generated/inventory.pve.yml
grep -A 5 'apt-cacher-stack' terraform/lxc/.generated/inventory.pve.yml | head -10
```

| Check | Status | Expected |
|---|---|---|
| Inventory file exists | ☐ | Recent timestamp |
| ansible_host is direct IP | ☐ | `192.168.40.11` not ProxyJump |
| dns_nameservers is zone gateway | ☐ | `192.168.40.1` |
| No ProxyJump lines | ☐ | Not present in file |

**If any check fails:** Do not apply. Review environment and stack decoupling.

---

## Phase 5: Operator Approval

**Required before proceeding to apply.**

**Operator must confirm in chat:**

> I approve deploying apt-cacher-stack to production pve as a low-risk canary validation.

Once confirmed, proceed to Phase 6.

---

## Phase 6: Apply

**Execute only after Phase 1–5 complete and operator approval received.**

```bash
export ALLOW_PVE=true
export TASK_APPROVAL="canary-apt-cacher-pve-$(date +%Y%m%d)"
./with-secrets-prod bash -c 'cd terraform/lxc && terragrunt apply \
  -target=module.apt-cacher-stack \
  /tmp/apt-cacher.plan 2>&1 | tee /tmp/apply.log'
```

| Check | Status | Notes |
|---|---|---|
| Apply exits code 0 | ☐ | No errors in log |
| Terraform state updated | ☐ | Container created on pve |
| Ansible provisioning completed | ☐ | All plays ran without error |
| No rollback messages | ☐ | Apply did not destroy and retry |

**If apply fails at any point:**
- Immediately run: `export ALLOW_PVE=true && ./with-secrets-prod bash -c 'cd terraform/lxc && terragrunt destroy -target=module.apt-cacher-stack -auto-approve'`
- Save logs from `/tmp/apply.log`
- Document failure root cause
- Do not proceed to evidence collection
- Fix issue and retry from Phase 4

---

## Phase 7: Post-Apply Evidence Collection

**Run within 5 minutes of successful apply. Save all results.**

### 7a. Container Confirmation

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'pct list | grep -E "(apt-cacher|40011)"'
```

**Record:** VMID, container name, status (should be "running").

### 7b. IP Address

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'pct exec 40011 ip -4 addr show eth0'
```

**Record:** Exact IP and subnet mask (should be `192.168.40.11/24`).

### 7c. Gateway Reachability

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'pct exec 40011 ping -c 3 192.168.40.1'
```

**Record:** RTT min/avg/max, packet loss %.

### 7d. DNS Resolution

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'pct exec 40011 dig @192.168.40.1 github.com +short'
```

**Record:** First IP resolved.

### 7e. Workstation SSH

**From your workstation (no ./with-secrets-prod needed):**

```bash
ssh -v -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@192.168.40.11 \
  'echo "SSH SUCCESS: $(hostname)"'
```

**Record:** SSH exit code (should be 0), hostname returned.

### 7f. Service Health

```bash
curl -s -w '\nHTTP %{http_code}\n' http://192.168.40.11:3142/acng-report.html | head -3
```

**Record:** HTTP status code (should be 200).

### 7g. Terraform State

```bash
cd terraform/lxc && terragrunt show -json module.apt-cacher-stack 2>/dev/null | jq '.values.outputs' | head -20
```

**Record:** State reflects pve deployment.

---

## Phase 8: Success Criteria & Next Steps

**Canary PASSES if all 7 evidence items are collected AND:**

1. ✅ Container IP is 192.168.40.11/24
2. ✅ Gateway 192.168.40.1 reachable (0% loss)
3. ✅ DNS resolves via zone gateway
4. ✅ SSH from workstation succeeds (direct, no ProxyJump)
5. ✅ HTTP 200 response from apt-cacher service
6. ✅ Terraform state reflects pve deployment
7. ✅ No manual Proxmox config required

**Next steps:**

1. Create session notes doc with evidence results
2. Update Task 06 doc with execution timestamp and evidence link
3. Close Task 06
4. Proceed to Task 07: Incremental Migration Plan

---

## Failure Handling

**If any evidence check fails:**

1. Stop (do not mark as complete)
2. Document which check failed and why
3. Investigate root cause (network, service, state)
4. Consider whether to destroy and retry, or troubleshoot in place
5. If unrecoverable, destroy via `terragrunt destroy -target=module.apt-cacher-stack`
6. Document findings in session notes

---

## References

- **Detailed Runbook:** [docs/productionize-refactor/runbooks/06-pve-canary-apt-cacher.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/06-pve-canary-apt-cacher.md)
- **Task 06:** [docs/productionize-refactor/tasks/06-canary-validation-gate.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md)
- **Production Controls:** [CLAUDE.md](/home/steve/git/proxmox-homelab/CLAUDE.md)
- **Network Design:** [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md)
