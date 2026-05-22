# Implementation Inventory: ProxyJump and SDN Provisioning

This document maps exactly where ProxyJump is injected and records that
`prime_sdn_host_route` was removed in Session 5. The remaining compatibility
path is explicit `ProxyJump` only.

## ProxyJump Injection: Complete Path

### Where ProxyJump is generated

**File:** [terraform/lxc/templates/inventory.tpl](../../terraform/lxc/templates/inventory.tpl)

```yaml
%{ if use_proxyjump ~}
          ansible_ssh_common_args: '-F /dev/null -o ProxyJump=root@${pve_host} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
%{ else ~}
          ansible_ssh_common_args: '-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
%{ endif ~}
          ssh_access_mode: ${ssh_access_mode}
```

**Condition:** ProxyJump is added if and only if `use_proxyjump` is true.

### How pve_host reaches the template

**File:** [terraform/lxc/main.tf](../../terraform/lxc/main.tf) line 533

```hcl
content = templatefile("${local.lxc_root}/templates/inventory.tpl", {
  ...
  pve_host            = local.effective_pve_host
  ssh_access_mode     = local.effective_network_access_path
  use_proxyjump       = local.use_proxyjump
})
```

The template now receives both effective access mode metadata and a dedicated
ProxyJump gate.

### How effective access mode is computed

**File:** [terraform/lxc/main.tf](../../terraform/lxc/main.tf)

```hcl
requested_network_access_path = try(local.stack.network.access_path, null)
normalized_network_access_path = local.requested_network_access_path == null ? null : try(lower(trimspace(local.requested_network_access_path)), null)

effective_network_access_path = local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet" ? coalesce(local.normalized_network_access_path, "direct") : coalesce(local.normalized_network_access_path, "proxyjump_compat")

use_proxyjump = local.effective_network_access_path == "proxyjump_compat" && local.effective_pve_host != ""
```

Rules implemented by these locals:

1. SDN-backed (`sdn_vnet`) stacks default to `direct` when `network.access_path` is absent.
2. Bridge/default path stacks preserve compatibility behavior by default (`proxyjump_compat`).
3. Explicit `network.access_path` may override defaults using `direct` or `proxyjump_compat`.
4. `pve_host` presence alone no longer enables `ProxyJump`.

### How effective_pve_host is computed

**File:** [terraform/lxc/main.tf](../../terraform/lxc/main.tf) line 137

```hcl
effective_pve_host = local.stack_network_zone != null ?
                     local.network_intent.proxmox.pve_host :
                     try(local.stack.proxmox_host, var.proxmox_host)
```

**Two paths:**

1. **If stack has a network zone** (`stack.yaml` contains `network.zone`):
   - Use `local.network_intent.proxmox.pve_host` (from the network intent YAML)
2. **Otherwise (legacy fallback)**:
   - Use `stack.proxmox_host` if present, else fall back to `var.proxmox_host`

### How pve_host gets its value in network intent

**File:** [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml) line 55

```yaml
proxmox:
  target_node: pve-test
  pve_host: ${proxmox_host}
```

The value `${proxmox_host}` is a template variable that gets substituted during main.tf processing.

**Template variable source:** [terraform/lxc/main.tf](../../terraform/lxc/main.tf) lines 26-42

```hcl
locals {
  stack_template_vars = {
    # ... other vars ...
    proxmox_host = var.proxmox_host
    # ...
  }
  stack = yamldecode(templatefile(var.stack_yaml_path, local.stack_template_vars))
```

The network intent file is also templated with the same `stack_template_vars`:

```hcl
network_intent = local.stack_network_zone != null ?
                 yamldecode(templatefile(local.effective_network_intent_path, local.stack_template_vars)) :
                 null
```

**Implication:** `pve_host` in the network intent still resolves from `var.proxmox_host` on `pve-test`,
but inventory `ProxyJump` behavior now follows `network.access_path`.

## prime_sdn_host_route: Removed in Session 5

`prime_sdn_host_route` no longer exists in `terraform/lxc/main.tf`. Session 5
removed the host-side `.254` bridge IP and route mutation entirely so SDN-
backed provisioning no longer depends on Proxmox-side reachability priming.

What remains relevant for provisioning is the explicit inventory access mode:

1. `network.access_path: direct` is the default for `sdn_vnet`
2. `network.access_path: proxyjump_compat` is the only remaining temporary
  compatibility path
3. `pve_host` still feeds the explicit `ProxyJump` path, but no longer implies
  host-route mutation

## SDN Zone and VNet Automation

### What is already automated

**File:** [terraform/lxc/main.tf](../../terraform/lxc/main.tf) lines 423-496

Automation path:
1. Calls [terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml](../../terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml)
2. Runs before LXC container creation (no dependency on container)
3. Triggered when: `local.stack_network_zone != null && local.resolved_attachment_type == "sdn_vnet"`

What the playbook creates (lines 1–177 of configure-network-sdn-vnet.yml):
- **SDN Zone** if missing (e.g., `tvinfra`, `tvmgmt`, `tvedge`, `tvsegc`)
- **SDN VNet** if missing (e.g., `tvinfra` with VLAN tag 40)
- **SDN Subnet** with gateway IP and SNAT settings
- **Apply pending SDN changes** to make them live
- **Validate proxmox-firewall compilation** to catch syntax errors

### What remains manual

**File:** [terraform/lxc/network/pve-test.yaml](../../terraform/lxc/network/pve-test.yaml) lines 26-52

MikroTik prerequisites (must exist before direct-SSH provisioning is viable):
- VLAN interfaces for each zone (e.g., `vlan10-build`, `vlan20-mgmt`, etc.)
- Gateway IPs on each VLAN (for the current `pve-test` environment:
  `192.168.10.1`, `192.168.20.1`, `192.168.30.1`, `192.168.40.1`)
- DNS forwarding rules (public DNS resolution + lab.gibbsgreatly.xyz delegation)
- Firewall ACLs for cross-zone policy (documented in pve-test.yaml policies section)

### Example: How a stack triggers SDN automation

When deploying `apt-cacher-stack` with this stack.yaml:

```yaml
network:
  zone: infra_seg
ansible_playbook: deploy-apt-cacher.yml
```

1. Network zone is set → `local.stack_network_zone = "infra_seg"`
2. Network intent attachment `infra_seg` has type `sdn_vnet` → automation path is enabled
3. Before container creation: configure-network-sdn-vnet.yml runs
4. Creates zone `tvinfra`, VNet `tvinfra`, subnet `192.168.40.0/24` if missing
5. Container is created with bridge `tvinfra` and IP `192.168.40.11`
6. Ansible inventory is generated with either direct SSH or explicit
  `ProxyJump` compatibility metadata

## Current Generated Inventory Example

For a stack with network zone and pve_host set:

```yaml
all:
  children:
    infra_seg_stack:
      hosts:
        infra-container:
          ansible_host: 192.168.40.11
          ansible_user: root
          ansible_ssh_private_key_file: /path/to/key
          ansible_ssh_common_args: '-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
          ssh_access_mode: direct
          network_zone: infra_seg
          dns_server: 192.168.40.1
          vmid: 40011
          stack_name: infra_seg_stack
```

For an SDN stack explicitly labeled for temporary fallback:

```yaml
all:
  children:
    infra_seg_stack:
      hosts:
        infra-container:
          ansible_host: 192.168.40.11
          ansible_user: root
          ansible_ssh_private_key_file: /path/to/key
          ansible_ssh_common_args: '-F /dev/null -o ProxyJump=root@pve-test -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
          ssh_access_mode: proxyjump_compat
          network_zone: infra_seg
          dns_server: 192.168.40.1
          vmid: 40011
          pve_host: pve-test
          stack_name: infra_seg_stack
```

For a non-zone or legacy bridge stack (no ProxyJump):

```yaml
all:
  children:
    test_stack:
      hosts:
        test-container:
          ansible_host: 192.168.1.100
          ansible_user: root
          ansible_ssh_private_key_file: /path/to/key
          ansible_ssh_common_args: '-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
```

## Summary for Session 3+ Planning

| Item | Location | Current State |
|---|---|---|
| ProxyJump generation | inventory.tpl | Conditional on `use_proxyjump` (`ssh_access_mode == proxyjump_compat` and `pve_host` set) |
| Access path resolution | main.tf locals | `sdn_vnet` defaults to `direct`; bridge/default path preserves `proxyjump_compat` |
| pve_host source | main.tf | From network intent if zone set, else legacy fallback |
| prime_sdn_host_route | removed in Session 5 | No longer present; host-side route priming is not part of the current model |
| SDN automation | configure-network-sdn-vnet.yml | Already automated; MikroTik side still manual |
| Network intent template | pve-test.yaml line 55 | pve_host set via template var substitution |

## How to Reference This Document

- **For removing ProxyJump:** Reference the template path and condition.
- **For validating the Session 5 removal:** Confirm `terraform/lxc/main.tf` no longer contains a `prime_sdn_host_route` resource and that inventories still choose only between direct SSH and explicit `proxyjump_compat`.
- **For understanding SDN prerequisites:** See the MikroTik setup section in pve-test.yaml.
- **For planning direct-SSH path:** Understand that effective_pve_host now only influences the explicit `ProxyJump` compatibility path.
