# Production Canary Runbook: apt-cacher-stack on pve

**Target:** `apt-cacher-stack` on production Proxmox host `pve`
**Zone:** `infra_seg` (VLAN 40, gateway `192.168.40.1`)
**Difficulty:** Low
**Risk:** Minimal — no data loss, no authentication required, simple service health check

## Purpose

Validate that production networking, environment targeting, and provisioning work
end-to-end on `pve` before attempting a higher-value service migration.

**Not a full production rollout.** This is a single, isolated test of the direct-access
network model that was validated on `pve-test`.

**Status note:** this canary later passed on 2026-05-22. Keep this runbook as
the reference workflow for future reruns and similar low-risk `pve` cutovers.

## Why apt-cacher-stack

1. **No external dependencies** — Does not require Authentik, Harbor, or any other
   stack to be deployed.
2. **Simple health check** — `curl -s http://192.168.40.11:3142/acng-report.html | head -1`
   returns the HTTP response code.
3. **Easy remediation** — If it fails, destroy and retry; minimal cleanup required.
4. **Known working baseline** — Already deployed and validated on `pve-test` via
   direct-access network model.

## Pre-Canary Checklist

**Do not proceed past any FAIL without operator intervention.**

### 1. Code State

- [ ] Branch is `work/productionize-06-canary-validation` (short-lived, not a promotion target)
- [ ] Latest main or baseline has been merged in
- [ ] All productionize Task 01–05 commits are in this branch
- [ ] No uncommitted changes in terraform/ or ansible/

### 2. Repository Preconditions

- [ ] `terraform/lxc/network/pve.yaml` exists and includes infra_seg, mgmt_seg, edge_seg, build_seg
- [ ] `terraform/lxc/storage/pve.yaml` exists and specifies production storage backends
- [ ] `terraform/lxc/terraform.tfvars` or generated config targets `pve` when `TF_VAR_proxmox_node=pve`
- [ ] Stack metadata in `terraform/lxc/stacks/apt-cacher-stack/stack.yaml` does NOT hardcode `proxmox_node: pve-test`
- [ ] `ansible/roles/` and `ansible/playbooks/` are environment-agnostic

**How to verify:** Run `grep -r 'pve-test' terraform/lxc/stacks/apt-cacher-stack/ ansible/playbooks/deploy-apt-cacher-stack.yml || echo "PASS"`

### 2b. Duplicate-IP Guard

- [ ] Any existing `apt-cacher-stack` instance on `pve-test` is stopped before bringing up the
      production canary on `pve`
- [ ] No other live guest is currently using `192.168.40.11`

This stack reuses the same service IP on `pve` and `pve-test`. During the
2026-05-22 canary, the `pve-test` counterpart had not been torn down first,
which would have created a duplicate-IP condition on the network. The operator
noticed and shut the `pve-test` instance down before continuing.

**Required rule for future runs:** before any `pve` canary, retry, or migration
that reuses the same service IP, stop the
matching `pve-test` instance first unless the IP assignment has been changed.

**How to verify / enforce:**
```bash
./with-secrets bash -lc 'ssh root@pve-test.gibbsgreatly.xyz "pct status 40011 || true"'
./with-secrets bash -lc 'ssh root@pve-test.gibbsgreatly.xyz "pct shutdown 40011 || pct stop 40011 || true"'
./scripts/dispose-pve-test-counterpart.sh --stack apt-cacher-stack --plan
./scripts/dispose-pve-test-counterpart.sh --stack apt-cacher-stack --execute
```

If the `pve-test` counterpart is disposable, prefer the helper above in
`--execute` mode. It stop-first destroys the managed stack on `pve-test` before
the `pve` cutover.

### 3. Network Preconditions

Network configuration is **out of scope** for this runbook. These MUST be in place
before attempting the canary (the operator, not the AI system, is responsible):

- [ ] MikroTik VLAN 40 interface is configured on the production switch (uplink to pve)
- [ ] MikroTik gateway IP `192.168.40.1` is assigned and reachable
- [ ] DNS forwarding from `192.168.40.1` is working (forwards internal/external names via MikroTik upstream)
- [ ] Firewall rules on MikroTik allow workstation → `192.168.40.0/24` on TCP 22 (SSH) and TCP 3142 (apt-cacher HTTP)
- [ ] (Optional but recommended) Workstation can ping `192.168.40.1` before proceeding

**How to verify:** Run from workstation:
```bash
ping -c 1 192.168.40.1
dig @192.168.20.1 github.com  # DNS upstream via MikroTik
```

If either fails, stop and do not proceed. Contact network operator.

### 4. Production Proxmox Preconditions

- [ ] `pve` host is reachable at `pve.gibbsgreatly.xyz` and responds to HTTPS
- [ ] Proxmox API token (`TF_VAR_pm_api_token_id` + `TF_VAR_pm_api_token_secret`) is valid and has
      permission to create/destroy LXC on pve (not just read-only)
- [ ] Storage backends on pve exist: `infrastructure-containers`, `local-zfs`
- [ ] Debian 13 LXC template is available on `pve` at `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz`
      (or equivalent per `.env.pve` template var)

**How to verify:** Run (requires production secrets):
```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'pveversion && pvesh get /nodes/pve && pvesh get /storage'
```

If any command fails, stop. Verify Proxmox API token, host reachability, or storage setup.

### 5. Session Environment

- [ ] `.env` and `.env.pve` files exist in repo root (must not be in git)
- [ ] Session is ready to use `./with-secrets-prod` for production commands
- [ ] Terminal has no lingering `TF_VAR_*` exports (run `env | grep TF_VAR | wc -l`, should be 0)

**How to verify:**
```bash
./with-secrets-prod bash -c 'echo $TF_VAR_proxmox_node'  # Should print: pve
```

If it prints anything other than `pve`, stop and check environment sourcing order.

---

## Pre-Apply Validation

**Run these checks in sequence. Stop on any FAIL.**

### Preflight 1: Direct-Access Network Model

The legacy `scripts/preflight-network-refactor.sh` is still pve-test-gated, so do
not use it as the production canary gate. For pve, verify the production target
and the direct-access plan instead:

```bash
cd terraform/lxc/stacks/apt-cacher-stack
/home/steve/git/proxmox-homelab/with-secrets-prod terragrunt plan -no-color
```

**Expected result:** The plan shows `node_name = "pve"`, `ip_address = "192.168.40.11/24"`,
`gateway = "192.168.40.1"`, and `ssh_access_mode: direct`.

**What this checks:**
1. Production wrapper targeting is pve
2. The stack renders the direct-access model
3. The intended subnet, gateway, and SSH mode match the production canary

### Preflight 2: Terraform Apply Readiness

```bash
cd terraform/lxc/stacks/apt-cacher-stack
TASK_APPROVAL='canary-apt-cacher-pve-20260522' \
   /home/steve/git/proxmox-homelab/with-secrets-prod terragrunt apply -auto-approve
```

**Expected result:** OpenTofu creates the container and renders `ssh_access_mode: direct`.

**Red flags (stop if you see these):**
- Plan attempts to destroy something on pve-test (wrong target)
- Plan targets `proxmox_node: pve-test` (environment not decoupled)
- Error: "Proxmox API 401" (token invalid or expired)
- Error: "Storage backend not found" (pve infrastructure missing)
- The matching `pve-test` stack is still running on the same IP (`192.168.40.11`)

### Preflight 3: Generated Inventory Check

After plan or apply, verify the generated inventory uses direct-access (no ProxyJump):

```bash
grep -E '(ProxyJump|ansible_host|ssh_access_mode|pve_host)' terraform/lxc/stacks/apt-cacher-stack/inventory.yml
ssh -G root@192.168.40.11 | rg '^proxyjump ' || echo 'proxyjump=none'
```

**Expected:**
- `ansible_host: 192.168.40.11`
- `ssh_access_mode: direct`
- NO `ProxyJump` entries
- `proxyjump=none`
- NO `pve_host` fallback needed for the direct SSH path

**Red flag:** If `ProxyJump` appears or `ansible_host` is not the direct IP, **stop**.
This indicates the network model has regressed.

---

## Apply Phase

### Authorization Requirement

**Production mutations require explicit operator approval.**

Before running apply, the operator must confirm in chat:

> I approve deploying apt-cacher-stack to production pve as a low-risk canary validation.

The AI system will then proceed with apply using `./with-secrets-prod`.

### Apply Command

```bash
cd terraform/lxc/stacks/apt-cacher-stack
export TASK_APPROVAL="canary-apt-cacher-pve-20260522"
/home/steve/git/proxmox-homelab/with-secrets-prod terragrunt apply -auto-approve
```

**Monitor the apply output for:**

1. **Proxmox API calls** — Verify node is `pve` not `pve-test`
2. **LXC creation** — Container VMID, IP assignment, zone attachment
3. **Ansible provisioning** — Expected plays: network bootstrap, apt-cacher-ng install, systemd start
4. **No errors** — Any Ansible task failure → stop, do not continue to validation

### Apply Rollback

If apply fails partway through, **do not attempt recovery**. Instead:

```bash
export ALLOW_PVE=true
./with-secrets-prod bash -c 'cd terraform/lxc && terragrunt destroy \
  -target=module.apt-cacher-stack -auto-approve'
```

Then investigate the failure, document findings, and prepare for retry once issues are resolved.

---

## Post-Apply Evidence Collection

**Run within 5 minutes of successful apply.**

### 1. LXC Container Confirmation

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.40.11 hostname
```

**Expected output:**
```
VMID    NAME            STATUS      NODE
40011   apt-cacher-     running      pve
        stack-lxc-...
```

**Record:** VMID and container name to evidence doc.

### 2. IP Address Verification

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@192.168.40.11 'ip -4 addr show eth0'
```

**Expected output:**
```
inet 192.168.40.11/24 brd 192.168.40.255 scope global eth0
```

**Record:** Exact IP, subnet mask, and interface name.

**Stop condition:** If IP is not in 192.168.40.0/24 range, provisioning failed at network layer.

### 3. Gateway Reachability

```bash
ping -c 1 -W 3 192.168.40.1
```

**Expected output:** 1 packet sent, 1 received, 0% packet loss.

**Record:** Latency and loss %.

**Stop condition:** If ping fails, the container cannot reach the gateway; network is misconfigured.

### 4. DNS Resolution

```bash
dig @192.168.40.1 +short github.com
```

**Expected output:** One or more IP addresses (e.g., `140.82.113.4`).

**Record:** First resolved IP address.

**Stop condition:** If no result or SERVFAIL, DNS is not working through the zone gateway.

### 5. Workstation → Container SSH Reachability

From your workstation (no need for `./with-secrets-prod`; this is direct-access validation):

```bash
ssh -v -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@192.168.40.11 \
  'echo $HOSTNAME'
```

**Expected output:** Container hostname (e.g., `apt-cacher-stack-lxc-container`), no authentication errors.

**Record:** SSH connection time, authentication method used.

**Stop condition:** If SSH fails with "Connection refused" or "Connection timed out", the
container is not reachable via direct IP routing. Network layer has failed.

### 6. apt-cacher-ng Service Health

```bash
curl -s -w '\nHTTP %{http_code}\n' http://192.168.40.11:3142/acng-report.html | head -5
```

**Expected output:**
```
<DOCTYPE html>
<html>
<head>
...
HTTP 200
```

**Record:** HTTP status code and first 2 lines of response.

**Stop condition:** If HTTP is not 200, the service did not start correctly. Check container
logs with `pct exec 40011 journalctl -u apt-cacher-ng -n 50`.

### 6b. Counterpart Safety Check

Before declaring the canary healthy, confirm the old `pve-test` counterpart is
still stopped so the service result is not polluted by duplicate addressing or
ambiguous replies:

```bash
./with-secrets bash -lc 'ssh root@pve-test.gibbsgreatly.xyz "pct status 40011 || true"'
```

**Expected result:** `stopped` or `does not exist`.

### 7. Terraform State Consistency

```bash
cd terraform/lxc/stacks/apt-cacher-stack
set -a && [ -f ../../../../.env ] && source ../../../../.env || true && [ -f ../../../../.env.pve ] && source ../../../../.env.pve || true && set +a
PVE_ENV=pve terragrunt state list
```

**Expected output:** State reflects the actual pve deployment (node = pve, IP = 192.168.40.11, zone = infra_seg).

**Record:** State snapshot timestamp.

---

## Evidence Checklist

Collect and save all of the following in a session doc (NOT committed to git):

| Item | Source | Value | Pass/Fail |
|---|---|---|---|
| Preflight exit code | `preflight-network-refactor.sh` | 0 | ☐ |
| Terraform plan node | `terragrunt plan` output | pve | ☐ |
| Generated inventory SSH type | inventory file | direct (no ProxyJump) | ☐ |
| Container VMID | `pct list` | 40011 | ☐ |
| Container IP | `pct exec / ip addr` | 192.168.40.11/24 | ☐ |
| Container gateway | `pct exec / ping` | reachable | ☐ |
| DNS resolution | `dig @192.168.40.1` | github.com resolves | ☐ |
| Workstation SSH to container | `ssh root@192.168.40.11` | successful | ☐ |
| HTTP service health | `curl http://192.168.40.11:3142` | HTTP 200 | ☐ |
| Terraform state | `terragrunt show` | reflects pve | ☐ |

---

## Success Criteria

The canary PASSES if ALL of the following are true:

1. ✅ Container is created on pve with the intended IP (192.168.40.11)
2. ✅ Container receives the intended gateway (192.168.40.1)
3. ✅ Container can ping the gateway and reach other zones if tested
4. ✅ DNS resolution works via the zone gateway (MikroTik)
5. ✅ Workstation can SSH directly to container (no ProxyJump, no host-route priming needed)
6. ✅ apt-cacher-ng service is running and responds to HTTP requests
7. ✅ Terraform state reflects the actual pve deployment (no drift)
8. ✅ No manual Proxmox host route configuration was required during deployment

## Failure Conditions

**Stop immediately and document findings if:**

| Symptom | Root cause likely in | Next step |
|---|---|---|
| Container IP is outside 192.168.40.0/24 | VLAN attachment or subnet config | Check pve.yaml network intent |
| Ping to gateway fails | MikroTik VLAN interface missing or firewall blocked | Verify with network operator |
| DNS fails but ping works | MikroTik DNS forwarding not configured | Check MikroTik FWD rules for zone |
| SSH connection refused from workstation | Firewall rule missing on MikroTik or Proxmox firewall | Verify firewall ACLs allow TCP 22 |
| SSH times out from workstation | Container not in routed path; may be using ProxyJump | Regenerate inventory, check for ProxyJump reintroduction |
| apt-cacher-ng returns HTTP 500 or 503 | Service failed to start or storage permission issue | Check container logs, verify storage mounts |
| Terraform state shows pve-test | Stack targeting still coupled to hardcoded pve-test | Verify stack.yaml and terraform vars decoupling |

---

## Remediation and Cleanup

### If Canary Fails at Pre-Apply Stage

1. Document the specific failure (preflight check, terraform plan, or network validation)
2. **Do not apply**
3. Fix the root cause (environment config, network, or code)
4. Re-run the pre-apply validation
5. Retry apply only after all preflight checks pass

### If Canary Fails During Apply

1. **Immediately destroy** the partial deployment:
   ```bash
   export ALLOW_PVE=true
   ./with-secrets-prod bash -c 'cd terraform/lxc && terragrunt destroy \
     -target=module.apt-cacher-stack -auto-approve'
   ```
2. Save all logs from the apply failure
3. Investigate the failure (Ansible logs, Proxmox API logs, network diagnostics)
4. Fix the issue
5. Retry the full flow starting from pre-apply validation

### If Canary Passes But apt-cacher-ng Service Is Unhealthy

1. Check service status:
   ```bash
   export ALLOW_PVE=true
   ./with-secrets-prod bash -c 'pct exec 40011 systemctl status apt-cacher-ng'
   ```
2. If service is not running:
   ```bash
   export ALLOW_PVE=true
   ./with-secrets-prod bash -c 'pct exec 40011 systemctl start apt-cacher-ng && sleep 5 && systemctl status apt-cacher-ng'
   ```
3. If service still fails, check logs:
   ```bash
   export ALLOW_PVE=true
   ./with-secrets-prod bash -c 'pct exec 40011 journalctl -u apt-cacher-ng -n 100'
   ```
4. If it remains unhealthy after investigation, destroy and re-run the canary.

### If Canary Passes and Must Be Retained for Further Testing

1. Document the success with timestamp and evidence file location
2. Do not apply other stacks to pve until this canary is fully validated
3. Use this container for follow-up tests (e.g., cross-zone connectivity if needed)
4. When done, destroy via `terragrunt destroy -target=module.apt-cacher-stack`

---

## Post-Canary Actions

### If Canary Passes

1. ✅ Document in `docs/productionize-refactor/sessions/` with evidence checklist
2. ✅ Update `docs/productionize-refactor/tasks/06-canary-validation-gate.md` to mark as validated
3. ✅ Close any related issues
4. ✅ Carry forward any newly discovered cutover safeguards
5. ✅ Prepare for **Task 07: Incremental Migration Plan** (next production service candidate)

### If Canary Fails and Is Unrecoverable

1. ❌ Document root cause in a session notes file
2. ❌ Identify which component needs fixing (code, network, Proxmox setup)
3. ❌ Plan remediation
4. ❌ **Do not proceed to Task 07** until root cause is resolved and canary can pass

---

## Related Documents

- [Task 06: Canary Validation Gate](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md)
- [Task 04: Production Network Intent](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/04-production-network-intent.md)
- [Production Readiness Plan](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md)
- [Network Refactor Validation Gate](/home/steve/git/proxmox-homelab/docs/network-refactor/validation-gate.md)
- [Session 8 Summary — pve-test Teardown/Redeploy](/home/steve/git/proxmox-homelab/docs/network-refactor/session-8-summary.md)
- [CLAUDE.md — Production Credential Controls](/home/steve/git/proxmox-homelab/CLAUDE.md)
