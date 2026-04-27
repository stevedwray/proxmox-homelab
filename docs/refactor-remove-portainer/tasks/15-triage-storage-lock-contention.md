# Task 15: Triage Proxmox storage lock contention on `infrastructure-containers`

## Type

Development

## Objective

Capture and classify the `pve-test` rebuild-gate failure caused by Proxmox
storage lock contention on `infrastructure-containers` without making code
changes.

This task exists because rebuild-gate execution reached live `apply` and
reported errors like:

- `can't lock file '/var/lock/pve-manager/pve-storage-infrastructure-containers' - got timeout`

for multiple platform CTs, including:

- CT 153 (`proxy-stack`)
- CT 151 (`dns-stack`)
- CT 142 (`apt-cacher-stack`)
- CT 143 (`netbox-stack`)

This evidence shows the rebuild gate is targeting the intended storage pool
(`infrastructure-containers`), but apply is blocked by runtime lock contention
on the Proxmox host.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/15-triage-storage-lock-contention.md`
- `docs/refactor-remove-portainer/prompts/15-triage-storage-lock-contention.yaml`

## Preconditions

- Task 13 complete and integrated on `dev/pve-test`.
- Scope is evidence capture and classification only.
- Do not change Terraform, Ansible, or runbook files in this task.
- Do not rerun the full rebuild gate in this task.

## Background

The key question is no longer which storage pool the rebuild gate intends to
use. Current evidence already shows the platform stacks target
`infrastructure-containers`, and the Proxmox errors reference that same pool.

This task is therefore limited to determining whether the rebuild gate is
blocked by:

- a transient Proxmox lock held by another running task,
- stale runtime state on `pve-test`,
- or a repeatable infrastructure behavior that should open a new fix task.

## Operations

1. Add Task 15 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   with precondition on Task 13.
2. Gather non-mutating evidence from `pve-test` about:
   - current CT inventory
   - running Proxmox tasks
   - lock files referencing `infrastructure-containers`
   - storage status for `infrastructure-containers`
3. Map the errored CT IDs back to stack names where possible.
4. Classify whether the rebuild gate is blocked by transient host state or a
   repeatable infrastructure issue.
5. Do not kill tasks, remove lock files, edit configs, or change code in this
   task.

## Postconditions

- We have concrete evidence for what is holding or contending on the
  `infrastructure-containers` storage lock.
- We know whether the next step should be:
  - retry rebuild gate after host state clears, or
  - open a new implementation task for a repeatable infrastructure fix.

## Validation

```bash
git branch --show-current
git status --short --branch
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'pvesm status'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'pvesm list infrastructure-containers | sed -n "1,80p"'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ls -l /var/lock/pve-manager/ | grep infrastructure-containers || true'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'ps -ef | grep -E "pvedaemon|pveproxy|pvestatd|zfs|pct|qm|proxmox" | grep -v grep'
./with-secrets ssh root@pve-test.gibbsgreatly.xyz 'tail -n 100 /var/log/pve/tasks/active'
```

Expected outcome:

- preflight confirms `pve-test`
- evidence shows whether the storage lock is actively held, stale, or already
  cleared
- CT inventory and storage state are captured
- no live mutation is performed

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Required evidence cannot be gathered non-mutatively.
- The only way forward would require killing live tasks or manually deleting
  lock files.
- Unexpected tracked changes appear outside scoped package files.
