# Task 16: Clear or confirm absence of stale Proxmox storage lock

## Type

Development

## Objective

Clear the stale Proxmox lock file for `infrastructure-containers` on `pve-test`,
or confirm that it is already absent as a no-op, without widening into rebuild
execution.

This is a host-only cleanup step, not a new implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/16-clear-stale-proxmox-storage-lock.md`
- `docs/refactor-remove-portainer/prompts/16-clear-stale-proxmox-storage-lock.yaml`

## Preconditions

- Task 15 triage is complete and classified the blocker as stale host lock
  state rather than a code defect.
- Task 15a is complete and integrated on `dev/pve-test`.
- The local workspace hazards must be preserved:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
- Scope is limited to the specific lock file:
  - `/var/lock/pve-manager/pve-storage-infrastructure-containers`
- Do not rerun the rebuild gate in this task.
- Do not edit Terraform, Ansible, or runbook files in this task.

## Background

Task 15 captured evidence that:

- the rebuild gate was targeting the intended storage pool
  (`infrastructure-containers`)
- the lock file existed on `pve-test`
- no active lock-holder process was identified at triage time
- the next operational step should be host stale-lock cleanup followed by a
  fresh rebuild-gate retry step

Because live host state may have changed since triage, this task must first
re-check whether the lock still exists. If it is already gone, report a no-op
and stop. If it still exists and there is still no sign of an active holder,
remove only that stale lock file and verify absence.

## Operations

1. Add Task 16 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the explicit host-cleanup step after Task 15a.
2. Preserve local workspace hazards non-destructively.
3. Run preflight to confirm the target is still `pve-test`.
4. Gather fresh host evidence:
   - current lock-file presence for `infrastructure-containers`
   - current Proxmox-related processes that could indicate an active holder
   - current active task log snapshot
   - storage status for `infrastructure-containers`
5. If the lock file is already absent, classify the task as a no-op and stop
   after writing the report.
6. If the lock file exists but evidence indicates it may be actively held,
   stop and report `blocked` without deleting it.
7. If the lock file exists and evidence still indicates stale/inactive state,
   remove only:
   - `/var/lock/pve-manager/pve-storage-infrastructure-containers`
8. Verify the lock file is absent after cleanup and capture the post-cleanup
   host state.
9. Write the task report to:
   - `docs/refactor-remove-portainer/reports/16-stale-lock-cleanup-report.md`
10. Stop after reporting. Do not start the rebuild gate in this task.

## Postconditions

- The stale `infrastructure-containers` lock file is absent after the task, or
  the task is reported as a no-op because it was already absent.
- No other host files or services are changed.
- We have fresh evidence for whether the next step should be a rebuild-gate
  retry.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
git merge-base --is-ancestor de717554a3f91a9261bd6b40e7586d4405144d4e dev/pve-test && echo yes || echo no
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ls -l /var/lock/pve-manager/ | grep infrastructure-containers || true'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "vzcreate|pct|vzdump|zfs|pvedaemon|pvesm" | grep -v grep'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'tail -n 100 /var/log/pve/tasks/active'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'pvesm status | sed -n "1,120p"'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'rm -f /var/lock/pve-manager/pve-storage-infrastructure-containers'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ls -l /var/lock/pve-manager/ | grep infrastructure-containers || true'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 15a is integrated on `dev/pve-test`
- host evidence shows one of two valid outcomes:
  - the lock file is already absent and the task is a no-op, or
  - the lock file is stale/inactive, is removed, and is absent afterward
- no rebuild-gate commands are executed
- no Terraform, Ansible, or runbook files change

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Evidence suggests the lock file is actively held by a running Proxmox task.
- Cleanup would require deleting anything other than the single scoped lock
  file.
- Host evidence reveals a wider storage or Proxmox runtime defect beyond the
  stale-lock classification from Task 15.
- Unexpected tracked changes appear outside scoped package files.
