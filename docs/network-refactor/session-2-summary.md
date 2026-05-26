# Session 2 Summary: Implementation Inventory Complete

## Work Completed

✅ **1. ProxyJump Injection Path Documented**

ProxyJump is injected via conditional logic in the Ansible inventory template:

- **Template file:** `terraform/lxc/templates/inventory.tpl` (lines 8–12)
- **Condition:** Adds `ProxyJump=root@<pve_host>` only if `pve_host` template variable is not empty
- **Variable source:** `local.effective_pve_host` (main.tf line 137)
- **Resolution:**
  - If stack has `network.zone` → use network intent's `proxmox.pve_host`
  - Otherwise → legacy fallback: `stack.proxmox_host` or `var.proxmox_host`
- **Network intent value:** `pve-test.yaml` line 55 sets `pve_host: ${proxmox_host}` (template-substituted)

**How to disable ProxyJump:** Empty `pve_host` at inventory generation time (either in network intent or via `-var proxmox_host=""`).

✅ **2. prime_sdn_host_route Trigger Conditions Documented**

The resource runs only when ALL four conditions are met:

- **Location:** `terraform/lxc/main.tf` lines 593–614
- **Count condition (line 594):**
  ```
  count = local.stack_network_zone != null &&
          local.resolved_attachment_type == "sdn_vnet" &&
          try(local.stack.ansible_playbook, "") != "" &&
          local.effective_pve_host != "" ? 1 : 0
  ```

**Breakdown:**
1. Stack has `network.zone` defined in stack.yaml
2. Network intent attachment type is `sdn_vnet` (not `bridge`)
3. Stack has `ansible_playbook` defined (non-empty)
4. `pve_host` is not empty

**What it does:** After LXC creation, SSH to Proxmox host and:
- Add `.254` bridge IP to SDN VNet bridge (for example `192.168.40.254/24`
  in the current `pve-test` addressing model)
- Add host route for the subnet through that bridge
- Verify with `ip route get <guest_ip>`

**How to disable without removal:** Omit any of the four conditions above.

✅ **3. SDN VLAN Attachment Automation Verified**

**Status:** ✅ Already fully automated for pve-test

- **Playbook:** `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml`
- **Trigger:** Runs when `stack_network_zone != null && attachment_type == "sdn_vnet"`
- **Timing:** Before LXC container is created (independent resource)
- **Creates:** SDN zone, VNet, subnet with gateway IP and SNAT settings

**Remains manual (MikroTik side):**
- VLAN interfaces for each zone
- Gateway IPs on each VLAN
- DNS forwarding rules
- Firewall ACLs for cross-zone policy

Documentation is in `terraform/lxc/network/pve-test.yaml` lines 26–52.

✅ **4. Stale Assumptions Corrected**

**Found and updated:**

1. **docs/network-refactor/plan.md Session 3:**
   - Changed task 2 from "decide whether...becomes conditional" to more precise "decide the logic for when to set pve_host"
   - Now lists four concrete options: always empty, conditional on type, conditional on env, or explicit per-stack flag

2. **docs/network-refactor/target-model.md Temporary Exceptions:**
   - Added detailed control mechanisms for both ProxyJump and prime_sdn_host_route
   - Clarified that pve_host controls ProxyJump generation via network intent
   - Listed all four ways to disable prime_sdn_host_route without code removal

**Verified as accurate (no changes needed):**

- Non-goals section correctly identifies that `.254` addresses are temporary
- Target model correctly states Proxmox should not be permanent L3 gateway
- Network design doc accurately describes zone-based architecture

✅ **5. New Documentation Created**

**File:** `docs/network-refactor/implementation-inventory.md`

This focused document provides:
- File-anchored paths for every injection point and trigger
- Complete call chain from template variable to inventory output
- Current generated inventory examples
- Summary table for Session 3+ planning
- Quick reference section for disabling each component

## Summary of Current Implementation State

| Component | Where | Trigger | Status |
|---|---|---|---|
| **ProxyJump generation** | inventory.tpl lines 8–12 | `pve_host != ""` | ✅ Working conditionally |
| **pve_host value** | main.tf line 137 | Zone set → network intent; else → legacy | ✅ Dual path working |
| **prime_sdn_host_route** | main.tf lines 593–614 | Four conditions (zone + vnet + playbook + host) | ✅ Working conditionally |
| **SDN automation** | configure-network-sdn-vnet.yml | Zone + sdn_vnet attachment | ✅ Already automated |
| **MikroTik side** | pve-test.yaml lines 26–52 | Manual | 🔄 Documented, out of band |

## Key Insights for Session 3

1. **pve_host is the control knob:** Setting it empty disables both ProxyJump AND prime_sdn_host_route simultaneously.

2. **Four ways to disable prime_sdn_host_route without removal:**
   - Omit `network.zone` → falls back to legacy bridge path
   - Change attachment type to `bridge` → skips SDN automation
   - Remove `ansible_playbook` → stops host route priming
   - Empty `pve_host` → both ProxyJump and host priming disabled

3. **SDN zone/VNet creation is already automated:** No work needed here; focus on inventory generation and host route removal.

4. **Network intent template substitution is important:** The network intent file gets `${proxmox_host}` replaced with `var.proxmox_host` during evaluation, so the value flows: variable → intent → effective_pve_host → inventory.

5. **Session 3 decision is narrower than stated:** Not "whether to make conditional" but "which condition controls it"—the mechanism is already there.

## Recommendation: Can Session 3 Begin?

### ✅ YES, Session 3 can begin immediately

**Prerequisites met:**
1. Implementation is fully mapped with file references
2. All trigger conditions are documented
3. Control mechanisms (how to disable without removal) are clear
4. No code changes are needed before Session 3 design work begins
5. Stale assumptions have been corrected

**What Session 3 should do:**
1. Decide: Should pve_host default to empty for new SDN zones (direct SSH only)?
2. If yes, update network intent loading to distinguish new stacks from legacy bridge stacks
3. Define the inventory contract for direct-SSH (no ProxyJump, no .254 bridges expected)
4. Plan preflight checks to validate router reachability before apply
5. Decide: Remove prime_sdn_host_route immediately or gate it behind a temporary flag?

**What Session 3 should NOT do yet:**
- Do not modify inventory.tpl or main.tf until design is final
- Do not remove prime_sdn_host_route
- Do not remove ProxyJump from any stacks
- Do not run teardown

## Updated Files

1. [docs/network-refactor/implementation-inventory.md](../../docs/network-refactor/implementation-inventory.md) — NEW: File-anchored implementation reference
2. [docs/network-refactor/plan.md](../../docs/network-refactor/plan.md) — UPDATED: Session 3 task clarification
3. [docs/network-refactor/target-model.md](../../docs/network-refactor/target-model.md) — UPDATED: Temporary Exceptions with control mechanisms

## Session Outputs

1. ✅ ProxyJump injection path fully documented with file references
2. ✅ prime_sdn_host_route lifecycle and all trigger conditions documented
3. ✅ SDN VLAN automation verified as already present and working
4. ✅ Stale assumptions identified and corrected
5. ✅ Implementation inventory created as focused reference doc
6. ✅ Recommendation: Session 3 can proceed immediately

---

**Next: Session 3 - Design the migration mechanics (ready to start)**
