# Task 00c: Harden downstream plan validation and null-resource expectations

## Type

Development

## Objective

Keep the platform-only downstream validation helper, but make it safe for
non-interactive use and align downstream task contracts with the current
Terraform boundary where `null_resource.ansible_provision` still exists.

Task 00 showed two contract gaps:

- `scripts/validate-portainer-refactor-platform-plan.sh` can stop on an
  interactive backend migration prompt, which makes downstream validation
  unreliable in executor sessions.
- Task 00 still treats `null_resource.ansible_provision` replacement as a
  blocker even though inventory-content changes legitimately affect that
  null-resource trigger until Task 08 removes it.

## Files

- `scripts/validate-portainer-refactor-platform-plan.sh`
- `docs/refactor-remove-portainer/runbook.md`
- `docs/refactor-remove-portainer/tasks/00-update-inventory-template.md`
- `docs/refactor-remove-portainer/tasks/07-classify-stacks.md`
- `docs/refactor-remove-portainer/prompts/00-update-inventory-template.yaml`
- `docs/refactor-remove-portainer/prompts/07-classify-stacks.yaml`
- `docs/refactor-remove-portainer/prompts/index.yaml`

## Preconditions

- Task 00a complete.
- Task 00b complete.

## Background

The platform-only helper introduced by Task 00b is the right validation scope,
but it is not yet robust enough for repeated executor use:

- `apt-cacher-stack` can trigger an interactive backend migration prompt during
  helper execution
- Task 00 can show expected `local_file.ansible_inventory` diffs plus
  `null_resource.ansible_provision` replacement because that resource tracks
  `inventory_content` in `terraform/lxc/main.tf`

That orchestration-only null-resource churn is acceptable until Task 08 removes
`null_resource.ansible_provision`, but the current downstream task contracts do
not describe it correctly.

## Operations

1. Read `scripts/validate-portainer-refactor-platform-plan.sh`,
   `terraform/lxc/main.tf`, `terraform/lxc/terragrunt.hcl`, the runbook, Task 00
   doc, Task 07 doc, and both prompts in full.
2. Update `scripts/validate-portainer-refactor-platform-plan.sh` so downstream
   validation remains platform-only and runs non-interactively for all ten
   platform stacks.
3. Preserve the existing stack list and fail-fast behavior.
4. Do not widen the helper back to `test-docker`, `test-lxc`, the root
   `terraform/lxc` unit, or any `net-*` validation stack.
5. Update the runbook so downstream task-complete dry-plan checks explicitly
   distinguish:
   - unacceptable LXC infrastructure changes
   - acceptable orchestration-only null-resource churn documented before Task 08
6. Update Task 00 and its prompt so task-complete validation allows:
   - `local_file.ansible_inventory` content diffs
   - `null_resource.ansible_provision` replacement driven only by
     `inventory_content`
   - no LXC infrastructure changes
7. Keep the existing Task 00 rule that generated `inventory.yml` greps are
   optional local evidence only when those files already exist.
8. Update Task 07 and its prompt only as needed so they reference the hardened
   non-interactive downstream helper and remain consistent with the runbook.
9. Unblock Task 00 and Task 07 in the package once the revised contract is in
   place.

## Postconditions

- `scripts/validate-portainer-refactor-platform-plan.sh` remains platform-only
  and runs non-interactively.
- Downstream validation no longer stops on an interactive backend-migration
  prompt in normal executor use.
- Task 00 now treats inventory-content-driven
  `null_resource.ansible_provision` replacement as acceptable orchestration-only
  churn until Task 08.
- Task 00 and Task 07 are unblocked in the package.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

shellcheck scripts/validate-portainer-refactor-platform-plan.sh

./scripts/validate-portainer-refactor-platform-plan.sh
# Expected: non-interactive completion across all ten platform stacks.

rg -n "null_resource.ansible_provision|inventory_content|non-interactive|validate-portainer-refactor-platform-plan.sh" \
  docs/refactor-remove-portainer/runbook.md \
  docs/refactor-remove-portainer/tasks/00-update-inventory-template.md \
  docs/refactor-remove-portainer/tasks/07-classify-stacks.md \
  docs/refactor-remove-portainer/prompts/00-update-inventory-template.yaml \
  docs/refactor-remove-portainer/prompts/07-classify-stacks.yaml
```

## Stop Conditions

- Stop if making the helper non-interactive would require widening validation
  scope beyond the ten platform stacks.
- Stop if `null_resource.ansible_provision` replacement is found to imply real
  LXC infrastructure drift rather than orchestration-only churn.
- Stop if resolving the backend prompt would require a live apply or manual
  state surgery outside normal dry-plan initialization.
