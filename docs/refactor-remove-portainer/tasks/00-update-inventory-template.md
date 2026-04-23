# Task 00: Update `inventory.tpl` to render `ansible_playbook`

## Type

Development

## Objective

The Terraform inventory template currently passes `ansible_playbook` as a template
variable but never renders it into the output file. `provision.sh` (Task 09) reads
this field from generated inventories to determine which playbook to run for each
stack. Without this change, `provision.sh` will silently skip every stack.

## Files

- `terraform/lxc/templates/inventory.tpl`

## Preconditions

- None.

## Background

`terraform/lxc/main.tf` passes `ansible_playbook = try(local.stack.ansible_playbook, "")`
to the template (line 327). The template receives the value but does not render it.
Other optional fields use a conditional block pattern:

```
%{ if network_zone != "" ~}
          network_zone: ${network_zone}
%{ endif ~}
```

`ansible_playbook` requires the same treatment.

## Operations

1. Read `terraform/lxc/templates/inventory.tpl` in full.
2. Add a conditional block for `ansible_playbook` following the same pattern as
   `network_zone` and `app_stack_name`. Place it after the `stack_name` line and
   before the `vmid` line:

   ```
   %{ if ansible_playbook != "" ~}
             ansible_playbook: ${ansible_playbook}
   %{ endif ~}
   ```

   Preserve the indentation exactly — this is a YAML host vars block and indentation
   is significant.

3. Do not add `ansible_playbook` unconditionally. Stacks without an
   `ansible_playbook` set in `stack.yaml` should produce no `ansible_playbook` line
   in the inventory, and `provision.sh` will SKIP them.

## Postconditions

- Any stack whose `stack.yaml` has `ansible_playbook: deploy-harbor-stack` (or any
  non-empty value) will produce an inventory.yml containing:
  ```yaml
  ansible_playbook: deploy-harbor-stack
  ```
- Stacks with no `ansible_playbook` set produce no such line.
- `terraform plan` after this change shows only `local_file.ansible_inventory` content
  diffs for stacks that have `ansible_playbook` set — no infrastructure changes.

## Validation

```bash
# Check the template renders correctly (dry-run via plan)
./with-secrets terragrunt run-all plan 2>&1 | grep -A5 "ansible_inventory"

# After apply, verify a stack with ansible_playbook set has it in inventory
grep "ansible_playbook" terraform/lxc/stacks/harbor-stack/inventory.yml

# Verify a stack without ansible_playbook set does not have the line
grep "ansible_playbook" terraform/lxc/stacks/apt-cacher-stack/inventory.yml
# Expected: no output (apt-cacher has no ansible_playbook in stack.yaml)
```

## Stop Conditions

- Stop if `ansible_playbook` is already present in inventory.tpl — report the
  existing rendering and do nothing.
- Stop if the template uses a different indentation style from what is shown above —
  report the actual indentation before editing.
- Stop if `terraform plan` shows any infrastructure changes (LXC resource changes) as
  a result of this edit.
