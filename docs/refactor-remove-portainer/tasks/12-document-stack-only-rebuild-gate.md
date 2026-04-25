# Task 12: Document stack-only, non-interactive rebuild-gate contract

## Type

Documentation

## Objective

Correct the package command contract for the final rebuild gate so operators run
Terragrunt in stack-only scope and non-interactive mode.

This task exists because `rebuild-gate-post-task11-report.md` shows a
package-level stop condition, not an implementation failure:

- repo-root `terragrunt run --all` includes `terraform/lxc`
- the root unit requires `stack_name` and `stack_yaml_path`
- `apply` behavior also requires explicit non-interactive handling in the
  documented gate flow

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/runbook.md`
- `docs/refactor-remove-portainer/tasks/12-document-stack-only-rebuild-gate.md`
- `docs/refactor-remove-portainer/prompts/12-document-stack-only-rebuild-gate.yaml`
- `docs/refactor-remove-portainer/02-terraform-ansible-separation.md`
- `docs/refactor-remove-portainer/03-refactor-plan.md`
- `terraform/lxc/README.md`

## Preconditions

- Task 11 complete and integrated on `dev/pve-test`.
- `docs/refactor-remove-portainer/reports/rebuild-gate-post-task11-report.md`
  is treated as authoritative stop-condition evidence.
- Scope remains package/documentation only. Do not run rebuild-gate execution
  in this task.

## Background

The active design remains unchanged:

- Terraform provisions infrastructure only.
- Generated inventory is the Terraform -> Ansible handoff artifact.
- `scripts/provision.sh` is the explicit configuration phase.
- Final success still requires the rebuild gate.

This task only corrects command-contract documentation so the next rebuild retry
uses the right Terragrunt entrypoint and interaction model.

## Operations

1. Add Task 12 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   with precondition on Task 11.
2. Add this task document and the matching prompt file.
3. Update `runbook.md` to document the stack-only Terragrunt rebuild-gate
   entrypoint and explicit non-interactive apply behavior.
4. Update closely related operator-facing docs in scope so they no longer
   conflict with the corrected runbook language.
5. Keep all changes decision-first and operational:
   - explicitly avoid repo-root `terraform/lxc` inclusion
   - explicitly document the stack-only Terragrunt entrypoint
   - explicitly document non-interactive behavior and `-auto-approve`
6. Do not execute destroy/apply/provision in this task.

## Postconditions

- Task 12 is represented cleanly in package sequence and prompt index.
- `runbook.md` no longer instructs repo-root all-units Terragrunt flow that
  includes `terraform/lxc`.
- Scoped operator-facing docs do not conflict with the runbook contract.
- Package now documents stack-only Terragrunt rebuild-gate entrypoint with
  non-interactive apply behavior.

## Validation

```bash
grep -nF "| 12 |" docs/refactor-remove-portainer/task-sequence.md
grep -n "12-document-stack-only-rebuild-gate" -A4 docs/refactor-remove-portainer/prompts/index.yaml
grep -n "stack-only\|working-dir\|terraform/lxc/stacks\|non-interactive\|auto-approve" docs/refactor-remove-portainer/runbook.md
rg -n "terragrunt run --all|terragrunt apply --all|terragrunt destroy --all|--working-dir|non-interactive|auto-approve" docs/refactor-remove-portainer/02-terraform-ansible-separation.md docs/refactor-remove-portainer/03-refactor-plan.md terraform/lxc/README.md docs/refactor-remove-portainer/runbook.md
rg -n "stack_name|stack_yaml_path" docs/refactor-remove-portainer/reports/rebuild-gate-post-task11-report.md
./with-secrets /home/steve/.local/bin/sonar-scanner
```

Expected outcome:

- Task 12 registry entries exist and are internally consistent
- runbook and scoped docs consistently point to stack-only Terragrunt flow
- non-interactive and `-auto-approve` behavior is explicitly documented for
  rebuild-gate apply
- no scoped doc still instructs the broken repo-root all-units rebuild path
- Sonar reports no new issues

## Stop Conditions

- The stack-only Terragrunt contract cannot be documented confidently from
  existing repo/tool evidence without rerunning rebuild-gate execution.
- Completing documentation correction requires implementation-code changes.
- Validation reveals a wider package inconsistency outside scoped docs.
- Sonar reports new issues.
- Unexpected tracked changes appear outside scoped files.
