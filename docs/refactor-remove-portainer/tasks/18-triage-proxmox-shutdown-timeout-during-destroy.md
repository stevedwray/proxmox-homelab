# Task 18: Triage Proxmox container shutdown timeout during rebuild-gate destroy

## Type

Development

## Objective

Capture and classify the rebuild-gate destroy failure caused by Proxmox
container shutdown timeouts, without changing code or rerunning the full
rebuild gate.

This is an evidence-only triage step, not a new implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/18-triage-proxmox-shutdown-timeout-during-destroy.md`
- `docs/refactor-remove-portainer/prompts/18-triage-proxmox-shutdown-timeout-during-destroy.yaml`

## Preconditions

- Task 17 is blocked and the report file exists on disk:
  - `docs/refactor-remove-portainer/reports/17-rebuild-gate-after-lock-cleanup-report.md`
- Scope is evidence capture and classification only.
- Do not rerun the full rebuild gate in this task.
- Do not edit Terraform, Ansible, scripts, or runbook files in this task.
- Preserve the local workspace hazards:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`

## Background

Task 17 reached the first rebuild-gate live step and then stopped on:

- `terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- destroy -auto-approve`

The reported failure was no longer the stale storage lock. Instead, Proxmox
container destroy paths reported shutdown timeouts while waiting for UPID tasks
to complete. The report specifically named failures in:

- `monitoring-stack`
- `net-build-01`
- `portainer-stack`

This task exists to determine whether the destroy failure is:

- transient host/runtime state that can clear before a retry,
- stale CT/task state on `pve-test`,
- or a repeatable infrastructure behavior that should open a fix task.

## Operations

1. Add Task 18 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the explicit triage follow-up to blocked Task 17.
2. Preserve local workspace hazards non-destructively.
3. Run preflight to confirm the target is still `pve-test`.
4. Re-read the Task 17 report and map the named failing units to CT IDs and
   stack names where possible.
5. Gather non-mutating host evidence from `pve-test` about:
   - current CT inventory and status
   - active Proxmox tasks / UPIDs
   - recent task log entries relevant to shutdown/destroy failures
   - any running container processes or stuck shutdown state for the named CTs
   - current lock files or runtime artifacts that might explain the timeout
6. Classify whether the rebuild gate is blocked by transient/stale host state
   or by a repeatable infrastructure behavior needing a follow-up fix task.
7. Do not stop containers manually, kill tasks, remove runtime files, or edit
   configs in this task.
8. Write the task report to:
   - `docs/refactor-remove-portainer/reports/18-shutdown-timeout-triage-report.md`
9. Stop after reporting. Do not start another task.

## Postconditions

- We have concrete evidence for why destroy hit shutdown timeouts.
- We know whether the next step should be:
  - retry rebuild gate after host state clears, or
  - open a new fix task for repeatable destroy behavior.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/17-rebuild-gate-after-lock-cleanup-report.md && echo present
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "pct|lxc|vz|qm|pvedaemon|pveproxy|pvestatd" | grep -v grep'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'tail -n 200 /var/log/pve/tasks/active'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'grep -R -n "shutdown\\|timeout\\|UPID" /var/log/pve/tasks 2>/dev/null | tail -n 120'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ls -l /var/lock/pve-manager/ | sed -n "1,120p"'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'for vmid in 120 154; do echo \"=== $vmid ===\"; pct status \"$vmid\" 2>/dev/null || true; done'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 17 evidence is present on disk
- host evidence shows whether the shutdown timeout is stale/transient or
  points to a repeatable Proxmox/container destroy behavior
- no live mutation is performed
- no rebuild-gate commands are executed

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Required evidence cannot be gathered non-mutatively.
- The only way forward would require killing live tasks, force-stopping CTs, or
  manually editing/removing runtime state.
- Host evidence reveals a wider defect outside the destroy-timeout
  classification boundary.
- Unexpected tracked changes appear outside scoped package files.
