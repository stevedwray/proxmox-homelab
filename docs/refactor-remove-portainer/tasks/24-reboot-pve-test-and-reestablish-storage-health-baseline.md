# Task 24: Reconcile `pve-test` post-reboot storage health baseline

## Type

Development

## Objective

Reconcile the immediate post-reboot storage/runtime baseline for `pve-test`,
because live host evidence showed a wider ZFS I/O suspension event beyond the
scoped CT-150 stop-task cleanup path.

This is a host recovery reconciliation step, not a new implementation task and
not a rebuild gate retry.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/24-reboot-pve-test-and-reestablish-storage-health-baseline.md`
- `docs/refactor-remove-portainer/prompts/24-reboot-pve-test-and-reestablish-storage-health-baseline.yaml`

## Preconditions

- Task 22 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/22-lxc-config-lock-timeout-triage-report.md`
- Treat the latest host-state evidence as authoritative:
  - as of April 26, 2026, `pct status 150` still returned `status: running`
    while live `pct stop 150` / `lxc-stop -n 150 --kill` processes remained
  - `zpool status` showed:
    - `apps` state: `SUSPENDED`
    - `infrastructure` state: `SUSPENDED`
    - `storage` state: `SUSPENDED`
  - host logs included repeated:
    - `pool I/O is currently suspended`
- Treat this as a wider host/runtime defect outside the narrow Task 23 cleanup
  boundary.
- If a manual reboot or CT shutdown already occurred before the executor run,
  treat that recovered host state as the starting point and reconcile it from
  live post-recovery evidence instead of trying to recreate the incident.
- Do not use this task to recreate pre-reboot failure state just to satisfy the
  report contract.
- Preserve the local workspace hazards:
  - modified `terraform/secrets.enc.yaml`
  - modified `scripts/rebuild-gate-destroy.sh`
  - untracked `.worktrees/`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
  - local uncommitted architect package updates under
    `docs/refactor-remove-portainer/`

## Background

The refactor hit a host-level failure mode that was not specific to the
destroy helper: ZFS pools on `pve-test` were suspended, host logs showed
ongoing I/O suspension errors, and CT `150` was left in a "running but
shutting down" state.

A narrow process cleanup was no longer the right next step. The immediate goal
is to record whether the host reboot and CT shutdown already performed out of
band cleared the storage and stop-task symptoms, without mixing in rebuild-gate
or implementation work.

## Operations

1. Cut a clean short-lived branch from `dev/pve-test`.
2. Preserve local hazards non-destructively.
3. Determine whether reboot recovery already happened before the executor run.
4. If recovery has not yet happened, capture pre-reboot evidence from
  `pve-test`:
  - hostname / uptime
  - `zpool status`
  - `pct status 150`
  - active `pct stop 150` / `lxc-stop -n 150 --kill` processes if present
5. If recovery has not yet happened, reboot `pve-test` and wait for SSH
  availability to return.
6. Capture post-reboot or post-recovery baseline evidence:
   - hostname / uptime
   - `zpool status`
   - `pvesm status`
   - `pct status 150`
   - whether the old stop-task processes are gone
   - whether `pool I/O is currently suspended` continues in recent logs
7. Explicitly state whether the reboot and CT shutdown were executed in-task or
  were already completed manually out of band before evidence capture.
8. Do not rerun the rebuild gate in this task.
9. Do not edit helper, Terraform, Ansible, or runbook files in this task.
10. Write the recovery report to:
   - `docs/refactor-remove-portainer/reports/24-pve-test-reboot-recovery-report.md`

## Postconditions

- Either:
  - reboot recovery clears the suspended-pool / hung-stop-task state and
    establishes a new baseline for the next architecture step
  - or the host returns still degraded, with evidence captured for broader
    host/runtime escalation

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/22-lxc-config-lock-timeout-triage-report.md && echo present
# if recovery has not already happened, capture pre-reboot evidence and reboot
# if recovery already happened manually, skip directly to the post-recovery checks
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'hostname; uptime'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'zpool status -xv || zpool status'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pvesm status | sed -n "1,120p"'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "pct stop 150|lxc-stop -n 150 --kill" | grep -v grep || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'journalctl -n 120 --no-pager | grep -E "pool I/O is currently suspended|zfs error|zed|I/O|ZFS|storage" || true'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 22 evidence is present on disk
- if recovery has not yet happened, pre-reboot evidence captures the suspended
  pool state and the host returns after reboot
- if recovery already happened manually, the report explicitly records that the
  task is reconciling post-recovery state rather than reproducing the failure
- post-reboot or post-recovery evidence shows whether storage pools remain
  suspended
- post-reboot or post-recovery evidence shows whether CT `150` is still in an
  active stop-task state
- no rebuild-gate commands are executed

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 22 evidence is missing from disk.
- Host state degrades further such that reboot cannot be initiated normally
  when recovery has not yet happened.
- Host does not return after reboot within a reasonable wait window when the
  task is the one performing the reboot.
- Post-reboot or post-recovery evidence shows a broader storage/hardware defect
  that requires escalation beyond the refactor package.
- Unexpected tracked changes appear outside scoped package files.
