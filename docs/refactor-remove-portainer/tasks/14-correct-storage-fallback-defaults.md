# Task 14: Correct invalid pve-test storage fallback defaults

## Type

Development

## Objective

Remove the invalid `local-zfs` fallback from the active `pve-test` Terraform
path and make the remaining fallback-dependent test stacks explicit.

This task exists because rebuild-gate layout inspection proved:

- `terraform/lxc/variables.tf` defaults `default_storage` to `local-zfs`
- `terraform/lxc/modules/lxc-docker-host/variables.tf` defaults
  `rootfs_storage` to `local-zfs`
- `test-docker` and `test-lxc` are the only current stacks still relying on
  that fallback
- `local-zfs` does not exist on `pve-test`
- the active target storage pool documented elsewhere in the repo is
  `infrastructure-containers`

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/14-correct-storage-fallback-defaults.md`
- `docs/refactor-remove-portainer/prompts/14-correct-storage-fallback-defaults.yaml`
- `terraform/lxc/variables.tf`
- `terraform/lxc/modules/lxc-docker-host/variables.tf`
- `terraform/lxc/stacks/test-docker/stack.yaml`
- `terraform/lxc/stacks/test-lxc/stack.yaml`

## Preconditions

- Task 13 complete and integrated on `dev/pve-test`.
- The rebuild-gate layout inspection evidence is treated as authoritative:
  platform stacks already pin `rootfs_storage: infrastructure-containers`,
  while `test-docker` and `test-lxc` still rely on the invalid fallback.
- Scope remains limited to correcting storage intent; do not widen into live
  rebuild-gate execution in this task.

## Background

This is an implementation fix, not a package-only wording change.

The rebuild-gate platform stacks already target `infrastructure-containers`
explicitly, so this task is not changing the Tier 1 storage model. It is
removing a bad default and making the remaining fallback users explicit so the
baseline `pve-test` Terraform path no longer points at a nonexistent Proxmox
storage backend.

## Operations

1. Add Task 14 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   with precondition on Task 13.
2. Change the root Terraform `default_storage` fallback from `local-zfs` to
   `infrastructure-containers`.
3. Change the module-level `rootfs_storage` default from `local-zfs` to
   `infrastructure-containers`.
4. Add explicit `rootfs_storage: infrastructure-containers` to:
   - `terraform/lxc/stacks/test-docker/stack.yaml`
   - `terraform/lxc/stacks/test-lxc/stack.yaml`
5. Keep this task narrow:
   - do not change platform stack storage selections already in `stack.yaml`
   - do not introduce new storage pools
   - do not run live destroy/apply/provision
6. Run the broader baseline validation helper because this task affects
   `test-docker` and `test-lxc`, which are intentionally outside the narrower
   downstream platform-only helper.

## Postconditions

- No active `pve-test` stack path in this refactor package silently falls back
  to nonexistent `local-zfs`.
- `test-docker` and `test-lxc` declare storage intent explicitly.
- The active fallback storage in Terraform aligns with the repo's documented
  `pve-test` target pool: `infrastructure-containers`.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
terraform fmt -check terraform/lxc
rg -n 'default\\s*=\\s*"local-zfs"' terraform/lxc/variables.tf terraform/lxc/modules/lxc-docker-host/variables.tf
rg -n '^rootfs_storage:\\s+infrastructure-containers' terraform/lxc/stacks/test-docker/stack.yaml terraform/lxc/stacks/test-lxc/stack.yaml
./scripts/validate-portainer-refactor-plan.sh
/home/steve/.local/bin/snyk iac test terraform/
./with-secrets /home/steve/.local/bin/sonar-scanner
```

Expected outcome:

- preflight confirms `pve-test`
- Terraform formatting is clean
- no `local-zfs` fallback remains in the active Terraform defaults
- `test-docker` and `test-lxc` explicitly declare
  `rootfs_storage: infrastructure-containers`
- the broader `pve-test` baseline validation passes
- Snyk IaC and Sonar report no new issues

## Stop Conditions

- Existing repo evidence is insufficient to justify `infrastructure-containers`
  as the correct fallback.
- Validation shows a stack in scope should intentionally use a different
  storage pool and the task would need widening.
- The broader baseline helper exposes unrelated LXC infrastructure drift
  outside the documented storage-default correction.
- Snyk IaC or Sonar reports new issues.
- Unexpected tracked changes appear outside scoped files.
