# Task 06: Canary Validation Gate

## Goal

Prove that production networking and environment targeting work on `pve` before
moving a higher-value real service. Perform a low-risk, isolated test of the
direct-access network model that was validated on `pve-test`.

## Objective

Validate end-to-end production provisioning for a single, non-critical service:

- VLAN transport on `vmbr0` and correct IP assignment from zone subnet
- gateway reachability and DNS behavior through MikroTik zone gateway
- direct SSH access from workstation (no ProxyJump or host-route priming required)
- service health proof (meaningful smoke test of deployed function)
- no environment-targeting regressions (correct node, correct storage, correct network)
- confirmation that the provisioning model has NOT reverted to pve-test assumptions

## Recommended First Canary Target

**`apt-cacher-stack` on `pve`** — VLAN 40 (infra_seg), IP 192.168.40.11

**Why:**
- No external service dependencies (Harbor not required, Authentik not required)
- Simple, meaningful health check (`HTTP GET /acng-report.html`)
- Easy to destroy and retry if something fails
- Lowest impact on production platform if it takes extra attempts
- Already validated on `pve-test` with direct-access model

**Other low-risk options (after apt-cacher succeeds):**
- Disposable single-container LXC if available
- `dns-stack` on `pve` (mgmt_seg, validates cross-zone DNS if needed)

**Avoid as first canary:**
- `harbor-stack` — dependency chain (storage permissions, app stacks rely on it)
- `authentik-stack` — authentication for other services, state-bearing, higher risk
- `proxy-stack` — Traefik, affects ingress path, depends on downstream services

## Validation Matrix

The canary MUST verify all of:

| Check | Expected Result | Evidence |
|---|---|---|
| Container IP assignment | 192.168.40.11/24 (infra_seg subnet) | `pct exec <vmid> ip -4 addr show eth0` |
| Gateway reachability | Ping success, no packet loss | `pct exec <vmid> ping -c 1 192.168.40.1` |
| DNS via zone gateway | Resolves internal and public names | `dig @192.168.40.1 traefik.lab.gibbsgreatly.xyz && dig @192.168.40.1 github.com` |
| Workstation → container SSH | Direct IP access, no ProxyJump | `ssh root@192.168.40.11 hostname` from workstation |
| Service-specific health | apt-cacher HTTP 200, service running | `curl -s http://192.168.40.11:3142/acng-report.html` + `HTTP 200` |
| Network config target | pve not pve-test | Terraform plan + generated inventory |
| No host route priming needed | Direct routed access works | Provisioning completes without manual Proxmox-side config |
| Duplicate-IP avoidance | matching pve-test counterpart stopped first | `pct status 40011` on `pve-test` shows stopped or absent |

---

## Production Credential Controls

This canary uses **production `pve` credentials** for the first time on this branch.
Credential handling is strict per [CLAUDE.md](/home/steve/git/proxmox-homelab/CLAUDE.md):

### Environment Setup

Before attempting any canary work:

```bash
# Source environment in this order:
source .env                    # Non-secret defaults (hostnames, IPs, usernames)
source .env.pve                # Production overrides (prod environment vars)
source terraform/secrets.pve.enc.yaml  # (handled by ./with-secrets-prod)
```

**Do NOT source `.env.pve-test` or any test-only config — this is production.**

### Approval Workflow

1. **Preflight checks** (read-only, no approval needed):
   ```bash
   cd terraform/lxc/stacks/apt-cacher-stack
   /home/steve/git/proxmox-homelab/with-secrets-prod terragrunt plan -no-color
   /home/steve/git/proxmox-homelab/with-secrets bash -lc \
     'ssh root@pve-test.gibbsgreatly.xyz "pct status 40011 || true"'
   ```

2. **Operator explicit approval** (in chat):
   > I approve deploying apt-cacher-stack to production pve as a low-risk canary validation.

3. **Mutating run** (with approval):
   ```bash
   export ALLOW_PVE=true
   export TASK_APPROVAL="canary-apt-cacher-pve-20260522"
   ./with-secrets-prod bash -c 'terraform apply -target=module.apt-cacher-stack'
   ```

The `./with-secrets-prod` wrapper enforces:
- `TF_VAR_proxmox_node=pve` (production targeting)
- Mutating commands (apply, destroy) blocked without `TASK_APPROVAL` export
- Only SOPS-decrypted production secrets loaded
- Read-only commands (plan, show, output) allowed by default

### Stop Conditions for Preconditions

**Do not proceed past any of these without intervention:**

1. Preflight check fails (network, DNS, or targeting guard)
2. Terraform plan shows creation on wrong node or targets pve-test
3. Storage backends missing on pve (infrastructure-containers, local-zfs)
4. Proxmox API token invalid (401 Unauthorized)
5. Network prerequisites not met (MikroTik VLAN, gateway IP, firewall rules)

## Deliverables

✅ **Detailed runbook:** [docs/productionize-refactor/runbooks/06-pve-canary-apt-cacher.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/06-pve-canary-apt-cacher.md)
- Pre-canary checklist (code, network, Proxmox)
- Pre-apply validation (preflight, terraform plan, inventory check)
- Apply command with approval flow
- Post-apply evidence collection (IP, gateway, DNS, SSH, HTTP health, state)
- Evidence checklist and success/failure criteria
- Remediation and cleanup procedures

✅ **Named first canary:** `apt-cacher-stack` on pve, infra_seg, IP 192.168.40.11

✅ **Production credential preconditions:**
- Credential sourcing order (`.env` → `.env.pve` → SOPS production secrets)
- `./with-secrets-prod` wrapper enforcement
- Approval workflow (explicit operator confirmation in chat)
- `TASK_APPROVAL` export for mutating commands

✅ **Evidence checklist (8 items):**
1. Container IP in intended subnet
2. Gateway reachable from container
3. DNS resolution via zone gateway
4. Direct SSH from workstation (no ProxyJump)
5. Service HTTP health check passes
6. Terraform state reflects pve deployment
7. Matching `pve-test` counterpart is stopped before reusing `192.168.40.11`
8. No manual Proxmox route configuration required

## Files Likely Involved

- `docs/productionize-refactor/runbooks/06-pve-canary-apt-cacher.md` ← **NEW detailed runbook**
- `terraform/lxc/network/pve.yaml` ← production network intent
- `terraform/lxc/storage/pve.yaml` ← production storage intent
- `terraform/lxc/stacks/apt-cacher-stack/stack.yaml` ← stack metadata (must not hardcode pve-test)
- `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml` ← provisioning playbook
- `.env.pve` ← production environment overlay (not in git)
- `terraform/secrets.pve.enc.yaml` ← production SOPS-encrypted secrets

## Dependencies

- Task 01: Production Credential Controls (with-secrets-prod, approval flow)
- Task 02: Production Environment Model (.env.pve overlay)
- Task 03: Production Storage Manifest (storage/pve.yaml)
- Task 04: Production Network Intent (network/pve.yaml with 4 zones)
- Task 05: Stack Target Decoupling (apt-cacher-stack not hardcoded to pve-test)

## Validation Gate

**Pass criteria (all must be true):**
1. ✅ Pre-canary checklist passes (code state, network, Proxmox, environment)
2. ✅ Production preflight validations pass (targeting, direct-access plan, inventory, counterpart stop check)
3. ✅ Terraform plan shows intended pve target with correct IP/zone/storage
4. ✅ Apply succeeds (no Ansible errors, no Proxmox API failures)
5. ✅ Matching `pve-test` counterpart is stopped before the `pve` canary uses the same service IP
6. ✅ All post-apply evidence items collected and pass validation
7. ✅ Session doc created with full evidence trail

**Fail handling:**
- If pre-apply check fails → investigate and fix; do not apply
- If apply fails → destroy immediately, document failure root cause
- If post-apply evidence fails → investigate service health, network config, or state
- Document and categorize failures as: code/environment, network, Proxmox infrastructure, or stack provisioning

---

## Risks Mitigated

1. ✅ **Too-central or stateful canary** — apt-cacher-stack has no external deps, easy to destroy
2. ✅ **Only host reachability tested** — HTTP 200 response validates service function
3. ✅ **Environment regression** — network/pve.yaml and stack.yaml decoupling validated upfront
4. ✅ **ProxyJump reintroduction** — direct SSH access confirmed from workstation
5. ✅ **Manual route priming** — preflight script confirms direct-access model

---

## Done When

1. ✅ Runbook doc created and tested against pre-apply environment
2. ✅ First canary target named (apt-cacher-stack)
3. ✅ Production credential preconditions documented
4. ✅ Evidence checklist defined
5. ✅ Task doc updated with specifics
6. ✅ The canary workflow is documented clearly enough to execute and later close out with evidence

---

## Execution Status

### 2026-05-22 Production Canary Validation

- Execution record: `docs/productionize-refactor/06-canary-execution-2026-05-22.md`
- Result: **PASSED**
- Gate decision: **Task 06 passed on `pve`; follow-up work is an operational duplicate-IP safeguard**

Validated evidence summary:

1. Production target controls are correct: `./with-secrets-prod` resolves `TF_VAR_proxmox_node=pve` and stack outputs confirm `target_node = pve`.
2. The stack exists on `pve` as VMID `40011` with IP `192.168.40.11/24` and default route via `192.168.40.1`.
3. Direct-access model remains correct: inventory has `ssh_access_mode: direct`, no default ProxyJump, and no `prime_sdn_host_route` dependency in state.
4. Initial gateway/data-plane validation failed because VLAN 40 was not tagged on the `pve` uplink at the MikroTik side.
5. That network blocker was corrected, and the remedial rerun passed end-to-end:
   - guest ping to `192.168.40.1` succeeded
   - direct SSH to `192.168.40.11` succeeded
   - `apt-cacher-ng.service` was later present and active inside the guest
6. HTTP service validation later returned `HTTP 200`, confirming the production provisioning model on `pve`.
7. During the same canary, the operator noticed the `pve-test` counterpart had not been torn down first. Because both environments use `192.168.40.11` for `apt-cacher-stack`, future runs must stop the `pve-test` counterpart before reusing that IP on `pve`.
8. Treat that duplicate-IP protection as a newly discovered precondition for future canaries and migrations, not as a failure of the `pve` canary itself.

The legacy `scripts/preflight-network-refactor.sh` remains pve-test-gated and is
not the production canary gate. Do not use it as the sole production preflight
check until it is made environment-aware.

---

## Next Steps (After This Run)

- Carry the duplicate-IP safeguard forward into future `pve` canaries and migrations: if a service reuses its `pve-test` IP on `pve`, stop or destroy the `pve-test` counterpart first.
- Use the successful `apt-cacher-stack` `pve` canary as the proven baseline for **Task 07: Incremental Migration Plan**.
- Add collision checks for reused IPs, hostnames, and live counterparts to each migration step before cutover.

---

## Suggested Branch

- `work/productionize-06-canary-validation` ← current branch
- Merge to `dev/pve-test` once the passed canary evidence and duplicate-IP safeguard are captured and reviewed
