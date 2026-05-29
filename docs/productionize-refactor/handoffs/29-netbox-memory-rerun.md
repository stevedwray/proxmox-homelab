# NetBox Memory Bump And Rerun Handoff (pve)

## Purpose

Use this handoff to apply the already-prepared NetBox source changes on
production `pve`, specifically:

- the bounded/idempotent NetBox bootstrap-playbook fix
- the NetBox memory increase from `1 GiB` to `4 GiB`

Then rerun `netbox-stack` provisioning to determine whether the remaining
blocker was primarily bootstrap-code behavior, memory starvation, or both.

## Problem Statement

The narrow NetBox bootstrap-fix session completed the code change but could not
prove live convergence because the existing production container became
unreachable during validation.

What is already known:

- the old bootstrap path was unsafe and could hang
- `deploy-netbox-stack.yml` was patched to use one bounded bootstrap path
- `netbox-stack` was still running on `pve`, but SSH stopped responding
- Proxmox status showed the container under extreme pressure while capped at
  `1 GiB` RAM
- the current source still needed a matching memory bump to give the rerun a
  fair chance

This task is not to redesign NetBox further. It is to apply the current source
state to the existing stack and gather the next decisive evidence.

## Source State To Apply

Current branch state now includes:

- [terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml:1)
  with the bounded unified bootstrap path
- [terraform/lxc/stacks/netbox-stack/stack.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/netbox-stack/stack.yaml:1)
  with `memory: 4096`

Do not silently revert either of those changes in this task.

## Evidence To Start From

- [docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md:1)
- [docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix.md:1)
- [docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/pve-netbox-status-current.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/pve-netbox-status-current.log:1)
- [docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/provision-netbox-stack-rerun-after-fix.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/provision-netbox-stack-rerun-after-fix.log:1)
- [docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md:1)

## Goal

Prove or disprove that the combined source fixes are sufficient for targeted
NetBox convergence on `pve`.

Success means:

1. the memory increase is applied to CT `40012`
2. the container becomes reachable enough for targeted validation
3. `./scripts/provision.sh --stack netbox-stack` reaches the patched bootstrap
   path
4. the rerun either succeeds or fails with sharper bounded evidence than before

## Scope

In scope:

- targeted `netbox-stack` plan/apply on `pve`
- if needed, targeted CT restart after the resize
- targeted `netbox-stack` provisioning rerun
- post-rerun health/evidence capture

Out of scope:

- full infra teardown/rebuild
- Portainer restoration
- unrelated stack changes
- new NetBox playbook refactors unless the rerun produces fresh evidence that
  clearly requires them

## Constraints

- Do not apply `stash@{0}`.
- Keep the task scoped to `netbox-stack`.
- Use `./with-secrets-prod` for production commands.
- Before apply, confirm `./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'`
  returns `pve`.
- If the container is still too unhealthy to validate after the resize and
  restart, stop and hand back evidence rather than broadening scope.

## Suggested Work Sequence

1. Read the handback and evidence listed above.
2. Confirm the current branch includes:
   - the patched `deploy-netbox-stack.yml`
   - `memory: 4096` in `terraform/lxc/stacks/netbox-stack/stack.yaml`
3. Run targeted plan for `netbox-stack`.
4. Apply only `netbox-stack`.
5. Confirm the new memory limit is visible from `pve`.
6. If the CT is still effectively wedged, restart only CT `40012`.
7. Rerun:
   - `./with-secrets-prod ./scripts/provision.sh --stack netbox-stack`
8. Capture post-run evidence:
   - apply log
   - restart output if used
   - provision rerun log
   - current Proxmox CT status
   - direct health/SSH reachability notes

## Required Runtime Inputs

Use:

- `TASK_APPROVAL=netbox-memory-rerun-20260524`

Recommended commands:

```bash
./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'
TASK_APPROVAL=netbox-memory-rerun-20260524 ./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/netbox-stack -no-color
TASK_APPROVAL=netbox-memory-rerun-20260524 ./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color
TASK_APPROVAL=netbox-memory-rerun-20260524 ./with-secrets-prod ./scripts/provision.sh --stack netbox-stack
```

If a restart is needed, keep it limited to CT `40012` and record it in the
evidence and handback.

## Minimum Validation

- targeted plan succeeds and shows only the expected `netbox-stack` change
- targeted apply completes
- post-apply evidence shows CT `40012` has the higher memory limit
- targeted provision rerun is executed
- resulting pass/fail state is captured in a tracked handback

## Required Handback Artifact

Create:

- `docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md`

That handback should include:

- whether the memory change applied cleanly
- whether a CT restart was required
- whether SSH/host responsiveness improved
- whether the patched bootstrap path ran
- whether `netbox-stack` provision now succeeds
- the resulting operational state of `netbox-stack`
- remaining blockers, if any

## Done When

- the `netbox-stack` memory bump is applied on `pve`
- targeted rerun evidence exists
- the next state is clearer than “container wedged at 1 GiB”
- the tracked handback is written

## Suggested Copilot Brief

```text
Apply the already-prepared NetBox source changes on production pve and rerun
only netbox-stack.

Start from:
- docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md
- docs/productionize-refactor/handoffs/29-netbox-memory-rerun.md

The branch already contains two important source changes:
- terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml has the bounded
  unified bootstrap fix
- terraform/lxc/stacks/netbox-stack/stack.yaml now sets memory: 4096

Do not revert either change. Do not apply stash@{0}. Do not broaden scope into
Portainer or a full teardown/rebuild.

Run a targeted netbox-stack plan/apply on pve, confirm the memory increase
took effect on CT 40012, restart only that CT if needed, and then rerun:
./with-secrets-prod ./scripts/provision.sh --stack netbox-stack

Use TASK_APPROVAL=netbox-memory-rerun-20260524 for mutation steps.

Capture complete evidence and write a tracked handback at
docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md with:
- whether the memory change applied
- whether the CT needed restart
- whether SSH responsiveness improved
- whether the patched bootstrap path ran
- whether netbox-stack provision now succeeds
- the resulting live state and remaining blockers
```
