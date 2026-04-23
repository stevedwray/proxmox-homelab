# Task 07: Classify all `stack.yaml` files with explicit `deployment_tier`

## Type

Development

## Objective

Every active `stack.yaml` must explicitly declare `deployment_tier: platform` or
`deployment_tier: apps`. No stack may rely on a silent default. Additionally, set
`portainer_agent: false` for all platform stacks and confirm `portainer_agent: true`
for any Tier 2 stacks.

This is an execution-intent task. It establishes the metadata that the future
orchestration path depends on.

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

- Task 00a complete. Task-complete validation for this refactor is currently
  blocked on the scoped Terragrunt validation baseline.

## Current Status Note

- Task 00a is complete. Task 07 is now unblocked and should use the scoped
  dry-plan path from `./scripts/validate-portainer-refactor-plan.sh`.

## Background

`deployment_tier` is metadata consumed by `provision.sh` (Task 09) to determine
deployment order and method. Terraform does not read `deployment_tier`, but it
does read `portainer_agent` for `null_resource.stack_cleanup`, so a plan may
show cleanup-resource metadata changes for stacks that currently still declare
`portainer_agent: true`. That is acceptable for this task as long as no LXC
infrastructure changes appear.

The following stacks do not currently use Portainer roles directly, but they are
still part of the Tier 1 masking sweep in Task 06a:
- `portainer-stack` — playbook has no portainer_agent role
- `step-ca-stack` — playbook uses systemd, no Docker, no portainer
- `dns-stack` — playbook uses systemd, no Docker, no portainer
- `apt-cacher-stack` — playbook uses apt, no Docker, no portainer
- `ci-runner-01` — playbook has no portainer_agent role

The following stacks have direct Portainer-path playbook changes in Tasks 02–06:
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

6. Confirm `terraform plan` shows no LXC infrastructure diff after these edits.
   Metadata-only changes tied to `portainer_agent` / `stack_cleanup` are
   acceptable in the current implementation boundary.

7. Create `terraform/lxc/test_stack_classification.py`:

   ```python
   import os
   import unittest
   import yaml

   PLATFORM_STACKS = [
       "portainer-stack",
       "harbor-stack",
       "apt-cacher-stack",
       "ci-runner-01",
       "dns-stack",
       "step-ca-stack",
       "authentik-stack",
       "proxy-stack",
       "monitoring-stack",
       "netbox-stack",
   ]


   class TestStackClassification(unittest.TestCase):
       STACKS_DIR = "terraform/lxc/stacks"

       def _load_stack_yaml(self, stack):
           path = os.path.join(self.STACKS_DIR, stack, "stack.yaml")
           with open(path) as f:
               return yaml.safe_load(f)

       def test_platform_stacks_have_deployment_tier_platform(self):
           for stack in PLATFORM_STACKS:
               with self.subTest(stack=stack):
                   data = self._load_stack_yaml(stack)
                   self.assertEqual(
                       data.get("deployment_tier"), "platform",
                       f"{stack}/stack.yaml must have deployment_tier: platform",
                   )

       def test_platform_stacks_have_portainer_agent_false(self):
           for stack in PLATFORM_STACKS:
               with self.subTest(stack=stack):
                   data = self._load_stack_yaml(stack)
                   self.assertFalse(
                       data.get("portainer_agent", False),
                       f"{stack}/stack.yaml must have portainer_agent: false",
                   )
   ```

8. Register the test in the teardown-test harness. In `scripts/teardown-deploy-test.sh`,
   inside `run_source_preflight_checks`, extend the `run_logged "edge-unit-tests"`
   invocation to include `terraform/lxc/test_stack_classification.py`:

   ```bash
   run_logged "edge-unit-tests" \
       python3 -m unittest \
         terraform/lxc/test_edge_manifest.py \
         terraform/lxc/test_render_edge_traefik.py \
         terraform/lxc/test_render_edge_coredns.py \
         terraform/lxc/test_discover_authentik_edge.py \
         terraform/lxc/test_reconcile_authentik_edge.py \
         terraform/lxc/test_reconcile_edge.py \
         terraform/lxc/test_inventory_template.py \
         terraform/lxc/test_stack_classification.py
   ```

   Note: `test_inventory_template.py` was added by Task 00 and should already be present.

## Postconditions

- Every platform stack has `deployment_tier: platform` and `portainer_agent: false`.
- No platform stack has `portainer_agent: true`.
- Terraform plan shows no LXC infrastructure changes.
- `python3 -m unittest terraform/lxc/test_stack_classification.py` passes.
- `scripts/teardown-deploy-test.sh source-preflight` includes `test_stack_classification.py`
  in the `edge-unit-tests` step and it passes.

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

./scripts/validate-portainer-refactor-plan.sh
# Expected: no LXC infrastructure changes. stack_cleanup/null_resource metadata
# diffs may appear for stacks that are switching portainer_agent from true to false.

python3 -m unittest terraform/lxc/test_stack_classification.py
# Expected: two tests pass, each covering all 10 platform stacks
```

## Stop Conditions

- Stop if a platform stack currently has `portainer_agent: true` but the
  corresponding playbook is not covered by Tasks 02–06 or Task 06a — report the
  inconsistency before setting it to `false`.
- Stop if `terraform plan` shows any LXC infrastructure change after these
  edits.
