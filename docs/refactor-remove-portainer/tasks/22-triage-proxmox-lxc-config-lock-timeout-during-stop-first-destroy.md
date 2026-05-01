# Task 22: Triage Proxmox LXC config-lock timeout during stop-first destroy

## Type

Development

## Objective

Gather non-mutating evidence for the new stop-path failure surfaced by Task 21:
`pct stop` now parses correctly, but stopping `authentik-stack` (`vmid=150`)
times out acquiring `/run/lock/lxc/pve-config-150.lock`.

This is an evidence-only triage step, not a new implementation task and not a
rebuild-gate retry.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/22-triage-proxmox-lxc-config-lock-timeout-during-stop-first-destroy.md`
- `docs/refactor-remove-portainer/prompts/22-triage-proxmox-lxc-config-lock-timeout-during-stop-first-destroy.yaml`

## Preconditions

- Task 21 is blocked and recorded in:
  - `docs/refactor-remove-portainer/reports/21-pct-stop-compatibility-fix-report.md`
- Treat the Task 21 stop condition as authoritative:
  - the original `Unknown option: timeout` defect is resolved
  - the new live failure is lock acquisition timeout on:
    - `/run/lock/lxc/pve-config-150.lock`
- Scope is evidence capture and classification only.
- Do not rerun the full rebuild gate in this task.
- Do not edit `scripts/rebuild-gate-destroy.sh`, Terraform, Ansible, or
  runbook files in this task.
- Treat the latest live host snapshot as additional authoritative evidence for
  this task:
  - on April 26, 2026, `pct status 150` still returned `status: running`
  - active processes included:
    - `/usr/sbin/pct stop 150`
    - `lxc-stop -n 150 --kill`
  - `/run/lock/lxc/pve-config-150.lock` still existed on disk
  - do not assume the config lock is stale while a live stop task is still
    present
- Preserve the local workspace hazards:
  - modified `terraform/secrets.enc.yaml`
  - modified `scripts/rebuild-gate-destroy.sh`
  - untracked `.worktrees/`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
  - local uncommitted architect package updates under
    `docs/refactor-remove-portainer/`

## Background

Task 21 corrected the helper's unsupported `--timeout` option and verified that
`pct stop` now parses on `pve-test`. The next live validation surfaced a
different blocker: stopping CT `150` times out on the Proxmox LXC config lock.

The architecture session needs to know whether this is:

- stale host lock state
- an active concurrent Proxmox task
- a repeatable stop-path interaction with this CT
- or a wider host/runtime issue outside the helper scope

Current evidence already suggests the second case is plausible, because a live
`pct stop 150` / `lxc-stop -n 150 --kill` pair was still present when the
architecture session re-checked host state after Task 21.

## Operations

1. Cut a clean short-lived branch from `dev/pve-test`.
2. Preserve local hazards non-destructively.
3. Re-read the Task 21 report and use `vmid=150` / `authentik-stack` as the
   focal case.
4. Gather only non-mutating host evidence from `pve-test`.
5. Explicitly classify whether the lock timeout is associated with a still-live
   stop task versus an orphaned/stale lock artifact.
6. Do not stop CTs manually.
7. Do not kill tasks.
8. Do not remove lock files.
9. Do not rerun the full helper or rebuild gate.
10. Write the triage report to:
   - `docs/refactor-remove-portainer/reports/22-lxc-config-lock-timeout-triage-report.md`

## Postconditions

- The package has enough evidence to decide whether the next step is:
  - host cleanup / no-op confirmation
  - narrow helper adjustment
  - or broader Proxmox runtime triage outside the current implementation path

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/21-pct-stop-compatibility-fix-report.md && echo present
git status --short --branch
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'ls -l /run/lock/lxc/ | grep pve-config-150.lock || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "pct|lxc-start|lxc-stop|lxc-attach|vzshutdown|pvedaemon|pveproxy|pvestatd" | grep -v grep'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pstree -ap | grep -E "pct stop 150|lxc-stop|lxc-start -F -n 150|pvedaemon" || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'tail -n 200 /var/log/pve/tasks/active'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'grep -R -n "150\\|pve-config-150.lock\\|trying to acquire lock\\|got timeout" /var/log/pve/tasks 2>/dev/null | tail -n 120'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'stat /run/lock/lxc/pve-config-150.lock 2>/dev/null || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct config 150 | sed -n "1,160p"'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 21 evidence is present on disk
- host evidence shows whether the config lock is stale, actively held, or part
  of a repeatable stop-path interaction
- host evidence explicitly distinguishes a live in-progress stop task from an
  orphaned lock file
- no live mutation is performed
- no rebuild-gate commands are executed

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 21 evidence is missing from disk.
- Required evidence cannot be gathered non-mutatively.
- The only way forward would require killing live tasks, force-stopping CTs, or
  removing runtime lock files.
- Host evidence reveals a wider Proxmox/runtime defect outside the config-lock
  timeout classification boundary.
- Unexpected tracked changes appear outside scoped package files.
