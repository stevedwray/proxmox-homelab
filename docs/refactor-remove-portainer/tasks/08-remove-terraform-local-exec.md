# Task 08: Remove `null_resource.ansible_provision` from Terraform

## Type

Development

## Objective

Remove the `null_resource.ansible_provision` block from `terraform/lxc/main.tf`. This
is the only null_resource that invokes `ansible-playbook` for LXC stack configuration.
After this change, `terragrunt apply` provisions infrastructure only.

## Files

- `terraform/lxc/main.tf`

## Preconditions

- Tasks 02, 03, 04, 05, 06, and 06a complete — all Tier 1 playbooks updated.
  Removing the local-exec invocation before the playbooks and masking coverage
  are ready would leave the task package in an incomplete boundary state.

## Background

`terraform/lxc/main.tf` contains multiple `null_resource` blocks. Their purposes are:

| Resource name | Purpose | Action |
|---|---|---|
| `configure_network_sdn_attachment` | SDN VNet create/destroy on Proxmox host | **RETAIN** |
| `configure_keyctl` | keyctl feature flag on Proxmox host | **RETAIN** |
| `prime_sdn_host_route` | SDN host route for Ansible reachability | **RETAIN** |
| `configure_network_firewall` | Proxmox firewall rules | **RETAIN** |
| `configure_network_vnet_firewall` | Proxmox VNet firewall rules | **RETAIN** |
| `ansible_provision` | LXC stack playbook runner (~line 425) | **REMOVE** |
| `stack_cleanup` | Cleanup on destroy (~line 553) | Check — retain unless it only calls the provision playbook |

`null_resource.ansible_provision` is at approximately line 425 in `main.tf`. It is
gated by `count = try(local.stack.ansible_playbook, "") != "" ? 1 : 0` and runs
`ansible-playbook playbooks/<playbook>.yml`.

**Do not remove any null_resource that runs commands against the Proxmox host itself**
(not the LXC container). Those are infrastructure operations that remain Terraform's
responsibility.

**The `ansible_playbook` field in `stack.yaml` is retained** and continues to be
passed to `local_file.ansible_inventory` (line 327) so `provision.sh` can read it
from the generated inventory. Do not remove it from the `local_file` resource.

## Operations

1. Read `terraform/lxc/main.tf` in full before editing.

2. Locate `null_resource.ansible_provision` (search for `"ansible_provision"`). Read
   its full block including `triggers`, `provisioner "local-exec"`, and `depends_on`.

3. Remove the entire `null_resource.ansible_provision` block.

4. Check whether any locals referenced exclusively by `ansible_provision` (not by any
   retained resource or `local_file.ansible_inventory`) can be removed. Common
   candidates if they appear: `local.ansible_dir`, `local.ansible_cfg`,
   `local.ansible_roles_path`. **Only remove a local if it is not referenced by any
   retained null_resource.** The retained resources (`configure_keyctl`, etc.) also
   set ANSIBLE_ env vars and may use these locals.

5. Check `null_resource.stack_cleanup` (~line 553). Read its full block. If it invokes
   the stack configuration playbook on destroy, remove only the ansible-playbook
   invocation from its `local-exec`. If it performs other cleanup (e.g. deregistration
   logic), retain those parts or flag for architecture review.

6. Remove any `depends_on` entries in other resources that reference the now-deleted
   `null_resource.ansible_provision`.

7. Run `terraform fmt` on the file after editing.

## Postconditions

- `null_resource.ansible_provision` no longer exists in `main.tf`.
- All five retained null_resources are present and unchanged.
- `local_file.ansible_inventory` still passes `ansible_playbook` to the template.
- `terraform plan` shows removal of `null_resource.ansible_provision[0]` from state
  and no other infrastructure changes.

## Validation

```bash
# Confirm the provision resource is gone
grep -n "ansible_provision" terraform/lxc/main.tf
# Expected: no output

# Confirm retained resources are present
grep -n "configure_network_sdn_attachment\|configure_keyctl\|prime_sdn_host_route\|configure_network_firewall\|configure_network_vnet_firewall" terraform/lxc/main.tf
# Expected: 5 matches

# Confirm ansible_playbook is still passed to inventory
grep -n "ansible_playbook" terraform/lxc/main.tf
# Expected: at least one line (the local_file.ansible_inventory assignment)

# Terraform format
terraform fmt -check terraform/lxc/main.tf

# Terraform plan — must show no infra changes
./with-secrets terragrunt run-all plan

# Snyk IaC
/home/steve/.local/bin/snyk iac test terraform/
```

## Stop Conditions

- Stop if `null_resource.ansible_provision` does not exist at the expected location —
  search for it by the `local-exec` string `playbooks/${try(local.stack.ansible_playbook`
  and report what is found.
- Stop if any retained null_resource has `depends_on = [null_resource.ansible_provision]`
  — removing this dependency could alter execution order; flag before removing.
- Stop if `terraform plan` shows any LXC infrastructure change (not just null_resource
  removals) after the edit.
- Stop if `null_resource.stack_cleanup` invokes both the stack playbook and other
  non-playbook cleanup in the same local-exec block — report the block content before
  editing.
