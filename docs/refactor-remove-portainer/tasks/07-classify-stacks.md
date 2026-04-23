# Task 07: Classify all `stack.yaml` files with explicit `deployment_tier`

## Type

Development

## Objective

Every active `stack.yaml` must explicitly declare `deployment_tier: platform` or
`deployment_tier: apps`. No stack may rely on a silent default. Additionally, set
`portainer_agent: false` for all platform stacks and confirm `portainer_agent: true`
for any Tier 2 stacks.

## Files (platform stacks — all must be updated)

```
terraform/lxc/stacks/portainer-stack/stack.yaml
terraform/lxc/stacks/harbor-stack/stack.yaml
terraform/lxc/stacks/apt-cacher-stack/stack.yaml
terraform/lxc/stacks/ci-runner-01/stack.yaml
terraform/lxc/stacks/dns-stack/stack.yaml
terraform/lxc/stacks/step-ca-stack/stack.yaml
terraform/lxc/stacks/authentik-stack/stack.yaml
terraform/lxc/stacks/proxy-stack/stack.yaml
terraform/lxc/stacks/monitoring-stack/stack.yaml
terraform/lxc/stacks/netbox-stack/stack.yaml
```

## Preconditions

- None. This task is independent and may be run before or after Tasks 02–06.

## Background

`deployment_tier` is metadata consumed by `provision.sh` (Task 09) to determine
deployment order and method. Adding it to `stack.yaml` causes no Terraform plan diff
— Terraform does not read this field. Confirm this understanding before saving.

The following stacks have Ansible playbooks that already deploy without Portainer and
require no further playbook changes (confirmed by reading the actual playbook files):
- `portainer-stack` — playbook has no portainer_agent role
- `step-ca-stack` — playbook uses systemd, no Docker, no portainer
- `dns-stack` — playbook uses systemd, no Docker, no portainer
- `apt-cacher-stack` — playbook uses apt, no Docker, no portainer
- `ci-runner-01` — playbook has no portainer_agent role

The following stacks have playbooks being updated in Tasks 02–06:
- `harbor-stack`, `authentik-stack`, `monitoring-stack`, `proxy-stack`, `netbox-stack`

## Operations

1. Read each `stack.yaml` file before editing.

2. For every platform stack listed above, add or set:
   ```yaml
   deployment_tier: platform
   portainer_agent: false
   ```

3. If `portainer_agent` already exists in a platform stack's `stack.yaml` with value
   `true`, set it to `false`. Do not leave it as `true` on any platform stack.

4. For any Phase 06 app stack `stack.yaml` files that exist (pihole-stack, arr-stack,
   jellyfin-stack, game-stack), add `deployment_tier: apps` and confirm
   `portainer_agent: true`.

5. Do not edit `test-docker`, `test-lxc`, or `net-*` stacks.

6. Confirm `terraform plan` shows no diff after these edits (Terraform does not read
   `deployment_tier`).

## Postconditions

- Every platform stack has `deployment_tier: platform` and `portainer_agent: false`.
- No platform stack has `portainer_agent: true`.
- Terraform plan is clean.

## Validation

```bash
# Every platform stack has deployment_tier: platform
grep -rn "deployment_tier" terraform/lxc/stacks/portainer-stack/ \
  terraform/lxc/stacks/harbor-stack/ \
  terraform/lxc/stacks/apt-cacher-stack/ \
  terraform/lxc/stacks/ci-runner-01/ \
  terraform/lxc/stacks/dns-stack/ \
  terraform/lxc/stacks/step-ca-stack/ \
  terraform/lxc/stacks/authentik-stack/ \
  terraform/lxc/stacks/proxy-stack/ \
  terraform/lxc/stacks/monitoring-stack/ \
  terraform/lxc/stacks/netbox-stack/
# Expected: 10 lines, each showing "deployment_tier: platform"

# No platform stack has portainer_agent: true
grep -rn "portainer_agent: true" terraform/lxc/stacks/portainer-stack/ \
  terraform/lxc/stacks/harbor-stack/ \
  terraform/lxc/stacks/apt-cacher-stack/ \
  terraform/lxc/stacks/ci-runner-01/ \
  terraform/lxc/stacks/dns-stack/ \
  terraform/lxc/stacks/step-ca-stack/ \
  terraform/lxc/stacks/authentik-stack/ \
  terraform/lxc/stacks/proxy-stack/ \
  terraform/lxc/stacks/monitoring-stack/ \
  terraform/lxc/stacks/netbox-stack/
# Expected: no output

./with-secrets terragrunt run-all plan 2>&1 | grep -c "No changes"
# Expected: count equals the number of stack modules
```

## Stop Conditions

- Stop if a platform stack currently has `portainer_agent: true` but the corresponding
  playbook is NOT in the list of playbooks being updated in Tasks 02–06 — report the
  inconsistency before setting it to `false`.
- Stop if `terraform plan` shows any infrastructure change after these edits.
