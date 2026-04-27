# Task 23: Clear hung Proxmox stop task for `authentik-stack` (`vmid=150`)

## Type

Development

## Objective

Perform a narrow host-only cleanup of the stuck `pct stop 150` task that Task
22 classified, so `vmid=150` is no longer left in an in-progress shutdown path
while still running.

This is a host cleanup step, not a new implementation task and not a rebuild
gate retry.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/23-clear-hung-proxmox-stop-task-for-vmid-150.md`
- `docs/refactor-remove-portainer/prompts/23-clear-hung-proxmox-stop-task-for-vmid-150.yaml`

## Preconditions

- Task 22 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/22-lxc-config-lock-timeout-triage-report.md`
- Treat the Task 22 classification as authoritative:
  - `vmid=150` / `authentik-stack` remained `status: running`
  - a live `/usr/sbin/pct stop 150` task was still present
  - a live `lxc-stop -n 150 --kill` child was still present
  - `/run/lock/lxc/pve-config-150.lock` still existed
- Scope is limited to this single live stop-task cleanup on `pve-test`.
- Do not rerun the rebuild gate in this task.
- Do not edit `scripts/rebuild-gate-destroy.sh`, Terraform, Ansible, or
  runbook files in this task.
- Preserve the local workspace hazards:
  - modified `terraform/secrets.enc.yaml`
  - modified `scripts/rebuild-gate-destroy.sh`
  - untracked `.worktrees/`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
  - local uncommitted architect package updates under
    `docs/refactor-remove-portainer/`

## Background

Task 22 established that the current blocker is not just a stale file. CT `150`
is still running while an in-progress `pct stop 150` / `lxc-stop -n 150 --kill`
pair remains live on the host.

The next step is to clear only that hung stop task so the host is no longer in
an ambiguous "running but shutting down" state. This task is intentionally
narrow and should not widen into broader Proxmox service restarts, runtime lock
removal, or a rebuild-gate retry.

## Operations

1. Cut a clean short-lived branch from `dev/pve-test`.
2. Preserve local hazards non-destructively.
3. Re-check live state for `vmid=150`:
   - `pct status 150`
   - active `pct stop 150` / `lxc-stop -n 150 --kill` processes
   - lock file presence
4. If the stuck stop task has already cleared and no live stop processes remain,
   treat the step as a no-op and report that explicitly.
5. If the stop task is still live while CT `150` remains running, perform a
   narrow host-only cleanup by terminating only the specific hung `pct stop 150`
   task and its `lxc-stop` child.
6. Do not stop CT `150` directly in this task.
7. Do not remove runtime lock files in this task.
8. Do not restart Proxmox services in this task.
9. Verify the live stop-task state is cleared after cleanup.
10. Write the cleanup report to:
   - `docs/refactor-remove-portainer/reports/23-hung-stop-task-cleanup-report.md`
11. Stop after reporting. Do not start another task.

## Postconditions

- Either:
  - no-op: the stuck stop task has already cleared on its own
  - cleanup complete: the specific live `pct stop 150` / `lxc-stop` pair is no
    longer running
- The host is no longer left in an in-progress stop-task state for `vmid=150`.
- No rebuild-gate commands are executed.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/22-lxc-config-lock-timeout-triage-report.md && echo present
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "pct stop 150|lxc-stop -n 150 --kill" | grep -v grep'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'ls -l /run/lock/lxc/ | grep pve-config-150.lock || true'
# if cleanup is required, terminate only the specific hung stop processes
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'kill <pct_stop_pid> <lxc_stop_pid>'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "pct stop 150|lxc-stop -n 150 --kill" | grep -v grep || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'tail -n 120 /var/log/pve/tasks/active'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 22 evidence is present on disk
- if the stop task already cleared, the step closes as a no-op
- otherwise, the specific hung stop-task processes are no longer running after
  cleanup
- CT `150` is no longer simultaneously `running` while an in-progress stop task
  remains active
- no rebuild-gate commands are executed

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 22 evidence is missing from disk.
- Additional live Proxmox tasks touching `vmid=150` make targeted cleanup
  unsafe.
- Cleanup would require stopping CT `150` directly, removing runtime lock
  files, or restarting Proxmox services.
- Clearing the specific stop-task processes leaves CT `150` in an ambiguous
  runtime state that needs broader architecture review.
- Unexpected tracked changes appear outside scoped package files.
