# Task 08b: Retire legacy stack_cleanup Ansible path before inventory-handoff validation

## Type

Development

## Objective

Retire the legacy destroy-time `null_resource.stack_cleanup` Ansible cleanup
path so Task 08a can safely generate or validate a real
`terraform/lxc/stacks/harbor-stack/inventory.yml` handoff artifact without
triggering hidden Ansible execution during Terraform apply.

This is a narrow Terraform remediation task. It is not Task 08a, not Task 09,
and not the rebuild gate.

## Scope Classification

This is **Terraform-code-change scope** with tightly scoped state-cleanup
validation.

- Not platform-only orchestration scope.
- Not a broad rebuild/state migration scope.
- Not a `scripts/provision.sh` implementation scope.

## Files

Primary:
- `terraform/lxc/main.tf`

State-inspection scope (harbor-stack only):
- `terraform/lxc/stacks/harbor-stack/terraform.tfstate`

## Preconditions

- Task 08 complete.
- Runbook preflight returns `pve-test`.
- Task 08a remains blocked until this task completes.

## Preflight

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
git branch --show-current
git status --short --branch
```

Expected outcome:

- `TF_VAR_proxmox_node` is exactly `pve-test`.
- Execution is on the Task 08b short-lived branch.
- No unexpected tracked-file changes are present outside this task scope.

Stop condition:

- any target other than `pve-test`

## Source-only validation

```bash
grep -n "resource \"null_resource\" \"stack_cleanup\"" terraform/lxc/main.tf
grep -n "when        = destroy" terraform/lxc/main.tf
grep -n "ansible-playbook -i localhost, playbooks/cleanup.yml" terraform/lxc/main.tf
./with-secrets bash -c 'cd terraform/lxc/stacks/harbor-stack && terragrunt plan'
```

Expected outcome:

- Current source confirms the legacy destroy-time cleanup path exists before the
  edit and is the direct blocker for Task 08a safety.
- Plan output stays within harbor-stack scope.

Stop conditions:

- the legacy path cannot be located in source and the blocker cannot be
  confirmed
- `terragrunt plan` widens outside harbor-stack or reveals unrelated
  infrastructure drift

## Operations

1. Edit `terraform/lxc/main.tf` and retire destroy-time Ansible cleanup behavior
   from `null_resource.stack_cleanup`.
2. Keep the change narrow: remove or neutralize only the
   `ansible-playbook -i localhost, playbooks/cleanup.yml` execution path.
3. Do not reintroduce Terraform-driven LXC Ansible orchestration.
4. Run `terraform fmt terraform/lxc/main.tf`.
5. Run source checks again to prove the cleanup playbook invocation is gone.
6. Inspect harbor-stack state to ensure no stale destroy-time behavior will block
   the next Task 08a retry:

   ```bash
   ./with-secrets bash -c 'cd terraform/lxc/stacks/harbor-stack && terragrunt state list | grep stack_cleanup || true'
   ```

   If state still includes `null_resource.stack_cleanup[0]` and the next apply
   path would still execute legacy behavior, stop and return the state-cleanup
   detail in the report for architecture confirmation before continuing.

## Task-complete validation

```bash
grep -n "ansible-playbook -i localhost, playbooks/cleanup.yml" terraform/lxc/main.tf
terraform fmt -check terraform/lxc/main.tf
./with-secrets bash -c 'cd terraform/lxc/stacks/harbor-stack && terragrunt plan'
./scripts/validate-portainer-refactor-platform-plan.sh
```

Expected outcome:

- `terraform/lxc/main.tf` no longer contains the destroy-time cleanup playbook
  invocation.
- Terraform formatting passes.
- Harbor-stack dry plan remains scoped and does not rely on hidden Ansible
  cleanup behavior.
- Downstream platform plan validation passes with no unrelated LXC
  infrastructure drift.

## Stop Conditions

- Solving this requires bundling Task 08a live artifact-generation in the same
  session.
- Solving this requires implementing Task 09 orchestration behavior.
- Retirement of the destroy-time cleanup path requires reopening broader
  architecture decisions not covered by current package decisions.
- Validation surfaces unexpected tracked-file changes outside declared task
  scope.

## Rollback

If validation fails after edits:

- revert only Task 08b-scoped Terraform changes on the branch
- do not retry Task 08a in the same session
- report the exact command/output that blocked safe retirement

If no safe narrow rollback exists without widening scope, stop and return a
package update request.

## Rebuild gate note

This task does not execute the rebuild gate and does not perform Task 08a or
Task 09 behavior. It only clears the legacy blocker so Task 08a can be retried
safely using source-first checks.
