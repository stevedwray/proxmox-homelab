# Task 13: Fix Terragrunt flag forwarding for rebuild-gate destroy/apply

## Type

Documentation

## Objective

Correct the package command contract for rebuild-gate destroy/apply so OpenTofu
flags are forwarded correctly under `terragrunt run --all`.

This task exists because `rebuild-gate-post-task12-report.md` shows a
package-level stop condition, not an implementation-level failure:

- the package currently documents `-auto-approve` directly after `destroy` /
  `apply` in `terragrunt run --all ...`
- Terragrunt 1.0.2 rejects this and stops before stack execution
- the command must forward OpenTofu flags after `--`

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/runbook.md`
- `docs/refactor-remove-portainer/tasks/13-fix-terragrunt-flag-forwarding.md`
- `docs/refactor-remove-portainer/prompts/13-fix-terragrunt-flag-forwarding.yaml`
- `docs/refactor-remove-portainer/02-terraform-ansible-separation.md`
- `docs/refactor-remove-portainer/03-refactor-plan.md`
- `terraform/lxc/README.md`

## Preconditions

- Task 12 complete and integrated on `dev/pve-test`.
- `docs/refactor-remove-portainer/reports/rebuild-gate-post-task12-report.md`
  is treated as authoritative stop-condition evidence.
- Scope remains package/documentation only. Do not execute rebuild-gate
  destroy/apply/provision in this task.

## Background

The active refactor design is unchanged:

- Terraform provisions infrastructure only.
- Generated inventory is the Terraform -> Ansible handoff artifact.
- `scripts/provision.sh` is the explicit configuration phase.
- Final success still requires the rebuild gate.

This task only corrects command syntax in the package so the next rebuild-gate
retry uses valid Terragrunt flag forwarding.

## Operations

1. Add Task 13 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   with precondition on Task 12.
2. Add this task document and the matching prompt file.
3. Update `runbook.md` to document valid Terragrunt flag forwarding for
   destroy/apply under `terragrunt run --all`.
4. Update closely related docs in scope so they do not repeat invalid syntax.
5. Keep all changes decision-first and operational:
   - preserve stack-only `--working-dir terraform/lxc/stacks`
   - preserve non-interactive behavior
   - forward `-auto-approve` after `--`
6. Do not execute rebuild-gate commands in this task.

## Postconditions

- Task 13 is represented cleanly in package sequence and prompt index.
- `runbook.md` no longer documents non-forwarded destroy/apply flag forms under
  `terragrunt run --all`.
- Scoped docs now align on valid forwarded syntax:
  - `run --all -- destroy -auto-approve`
  - `run --all -- apply -auto-approve`
- Package remains documentation-only with no implementation behavior changes.

## Validation

```bash
grep -nF "| 13 |" docs/refactor-remove-portainer/task-sequence.md
grep -n "13-fix-terragrunt-flag-forwarding" -A4 docs/refactor-remove-portainer/prompts/index.yaml
rg -n "run --all (destroy|apply) -auto-approve" docs/refactor-remove-portainer terraform/lxc/README.md
rg -n "run --all -- destroy -auto-approve|run --all -- apply -auto-approve" docs/refactor-remove-portainer terraform/lxc/README.md
rg -n "flag `-auto-approve` is not a Terragrunt flag|use `--` to forward it" docs/refactor-remove-portainer/reports/rebuild-gate-post-task12-report.md
./with-secrets /home/steve/.local/bin/sonar-scanner
```

Expected outcome:

- Task 13 registry entries exist and are internally consistent
- runbook and scoped docs consistently use valid Terragrunt flag forwarding
- no scoped operator doc still instructs the invalid syntax
- report evidence still captures why Task 13 was required
- Sonar reports no new issues

## Stop Conditions

- The Terragrunt flag-forwarding contract cannot be documented confidently from
  existing repo/tool evidence.
- Completing documentation correction requires implementation-code changes.
- Validation reveals a wider package inconsistency outside scoped docs.
- Sonar reports new issues.
- Unexpected tracked changes appear outside scoped files.
