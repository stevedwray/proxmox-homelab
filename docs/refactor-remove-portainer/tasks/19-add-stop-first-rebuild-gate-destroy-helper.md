# Task 19: Add a stop-first rebuild-gate destroy helper

## Type

Development

## Objective

Add an explicit helper for rebuild-gate destroy that stops targeted `pve-test`
containers before invoking the Terragrunt destroy command, so the rebuild gate
does not depend on Proxmox guest shutdown succeeding for active Docker LXCs.

This is a narrow rebuild-unblocker implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/19-add-stop-first-rebuild-gate-destroy-helper.md`
- `docs/refactor-remove-portainer/prompts/19-add-stop-first-rebuild-gate-destroy-helper.yaml`
- `docs/refactor-remove-portainer/runbook.md`
- `scripts/rebuild-gate-destroy.sh`

## Preconditions

- Task 18 is complete and its report exists on disk:
  - `docs/refactor-remove-portainer/reports/18-shutdown-timeout-triage-report.md`
- Task 18 classification is treated as authoritative:
  destroy is blocked by repeatable container shutdown behavior, not by the
  earlier stale storage-lock issue.
- Scope is limited to the rebuild-gate destroy path. Do not widen into:
  - Terraform module refactors
  - container runtime changes inside LXCs
  - rebuild-gate apply/provision/smoke validation
- Preserve the local workspace hazards:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`

## Background

Task 17 failed on:

- `./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- destroy -auto-approve`

Task 18 then showed:

- repeated `vzshutdown` UPID entries ending with `container did not stop`
- the stale `infrastructure-containers` storage lock was no longer the active
  blocker
- the named failing units were active Docker-based LXCs, including:
  - `portainer-stack` (`120`)
  - `net-build-01` (`139`)
  - `monitoring-stack` (`154`)

The rebuild gate therefore needs an explicit stop-first destroy path instead of
depending on guest shutdown behavior during Terraform destroy.

## Operations

1. Add Task 19 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the destroy-unblocker follow-up to Task 18.
2. Create `scripts/rebuild-gate-destroy.sh` as the explicit destroy entrypoint
   for the rebuild gate.
3. The helper must:
   - run from repo root
   - require `pve-test` preflight via `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'`
   - derive the target stack set from `terraform/lxc/stacks/*/stack.yaml`
     rather than a hardcoded VMID list
   - collect each stack's `vmid`
   - non-destructively support a dry-run/plan mode
   - when executing, stop currently running target CTs on `pve-test` before
     running the documented Terragrunt destroy command
   - treat already-stopped or already-absent CTs as no-op cases
   - preserve the existing stack-only Terragrunt destroy invocation after the
     stop-first phase
4. Update `docs/refactor-remove-portainer/runbook.md` so rebuild-gate destroy
   uses the new helper instead of calling Terragrunt destroy directly.
5. Keep this task narrow:
   - do not change rebuild-gate apply/provision/smoke commands
   - do not rerun the full rebuild gate in this task
6. Write the implementation report to:
   - `docs/refactor-remove-portainer/reports/19-stop-first-destroy-helper-report.md`

## Postconditions

- The rebuild gate has an explicit, documented stop-first destroy entrypoint.
- The stop-first helper derives its scope from stack metadata, not an ad hoc
  hardcoded VMID list.
- The runbook and helper agree on the destroy path.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/18-shutdown-timeout-triage-report.md && echo present
shellcheck scripts/rebuild-gate-destroy.sh
./scripts/rebuild-gate-destroy.sh --dry-run
rg -n "rebuild-gate-destroy.sh" docs/refactor-remove-portainer/runbook.md
./with-secrets /home/steve/.local/bin/sonar-scanner
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 18 evidence is present on disk
- `shellcheck` passes for the new helper
- dry-run mode prints the stop-first target scope and Terragrunt destroy
  command without mutating host state
- runbook destroy step references the new helper
- Sonar reports no new issues

## Stop Conditions

- Preflight does not confirm `pve-test`.
- A stop-first helper cannot be implemented without widening into unrelated
  Terraform/module/runtime changes.
- Dry-run mode cannot derive a stable target set from `stack.yaml` metadata.
- Validation reveals a wider rebuild-gate contract inconsistency outside the
  destroy-path scope.
- Sonar reports new issues.
- Unexpected tracked changes appear outside scoped files.
