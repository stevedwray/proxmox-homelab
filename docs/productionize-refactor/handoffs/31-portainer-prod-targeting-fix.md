# Portainer Production Targeting Fix Handoff

## Purpose

Use this handoff to fix the narrow remaining blocker from the latest full
infra-only proof run on production `pve`.

The next task is not another broad teardown/rebuild. It is a focused fix for
`portainer-stack` provision so the edge reconcile path can run correctly on
production and the stack can be rerun in isolation.

## Goal

Make `./with-secrets-prod ./scripts/provision.sh --stack portainer-stack`
succeed on `pve` from the current branch state.

Success means:

1. the production-target preflight no longer fails with `EGR200`
2. the Portainer edge reconcile path reaches real apply mode on `pve`
3. the targeted `portainer-stack` rerun either converges successfully or
   fails at a new, narrower, evidence-backed blocker

## Starting State

Use the current branch state exactly as-is:

- branch: `work/productionize-06-canary-validation`
- HEAD includes:
  - `860df0a` `fix(prod): recover netbox bootstrap on pve`

Known live state after the failed full proof rerun:

- all 10 in-scope stacks were destroyed and reapplied successfully
- 9 of 10 provision phases succeeded
- `netbox-stack` stayed fixed during the full proof run
- `portainer-stack` CT `20020` exists again on `pve` but provision did not
  converge

Primary evidence:

- [docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md:1)
- [docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/provision-portainer-stack.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/provision-portainer-stack.log:1)

## What Is Proven Already

The first real blocker is production target preflight, not yet a proven
Authentik apply-path bug.

What the current evidence supports:

- `scripts/provision.sh` calls `terraform/lxc/reconcile-edge.py` for Portainer
  route publication
- `reconcile-edge.py` currently shells out through `./with-secrets` for target
  preflight
- on production, that preflight fails with `EGR200` because `./with-secrets`
  expects `pve-test`
- the reconcile therefore remained in `dry-run`
- missing Authentik-owned Portainer route objects were discovered, but their
  creation path was not actually exercised in apply mode

This means the next task should first make the Portainer reconcile path
production-compatible, then rerun only `portainer-stack` and observe what
happens next.

## Likely Change Area

Start by reviewing:

- [scripts/provision.sh](/home/steve/git/proxmox-homelab/scripts/provision.sh:76)
- [terraform/lxc/reconcile-edge.py](/home/steve/git/proxmox-homelab/terraform/lxc/reconcile-edge.py:43)
- [terraform/lxc/stacks/portainer-stack/edge.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack/edge.yaml:1)
- [terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md:1)

The most likely repair area is one of:

- make the target preflight in `reconcile-edge.py` production-aware
- or have the Portainer provision path pass an explicit production-safe
  preflight expectation/command

Do not assume the missing Authentik objects require a second fix until the
apply path has actually been allowed to run on `pve`.

## Out Of Scope

- another full infra-only proof rerun
- unrelated stack repairs
- NetBox changes
- broad in-place mutation outside targeted Portainer diagnosis/recovery
- applying `stash@{0}`

## Required Runtime Inputs

Use:

- `./with-secrets-prod ...`
- `TASK_APPROVAL=portainer-prod-targeting-fix-20260524`

Before mutation, confirm:

- `./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'` returns `pve`
- the branch is still `work/productionize-06-canary-validation`
- `stash@{0}` remains unapplied

## Suggested Work Sequence

1. Re-read:
   - `30-pve-infra-proof-rerun-handback.md`
   - `provision-portainer-stack.log`
2. Reproduce the targeted Portainer rerun with complete evidence capture if
   needed, but keep scope to `portainer-stack`.
3. Patch the production-target preflight/reconcile behavior in source.
4. Validate syntax or local checks for changed files.
5. Rerun:
   - `./with-secrets-prod ./scripts/provision.sh --stack portainer-stack`
6. Capture whether the reconcile reached apply mode and whether the Authentik
   objects were created or updated.
7. Write a tracked handback with the exact resulting state.

## Minimum Validation

At minimum, capture:

- the targeted rerun log
- the exact `EGR200` behavior before and after the fix
- whether `reconcile-edge.py` stayed in dry-run or reached apply mode
- whether Portainer provision succeeded
- resulting live state for CT `20020`

## Required Handback Artifact

Create:

- `docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md`

That handback should include:

- root cause actually proven
- files changed
- validation steps run
- whether `portainer-stack` provision now succeeds
- whether missing Authentik-owned Portainer route objects were created
- resulting live state on `pve`
- whether the repo is now ready for another fresh full proof rerun

## Done When

- the Portainer targeting fix has been applied and validated, or
- the targeted rerun failed at a new narrower blocker with complete evidence,
- and the tracked handback is written

## Suggested Copilot Brief

```text
Fix the remaining Portainer blocker on production pve from the current repaired
branch state.

Start from:
- docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md
- docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix.md
- docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260524-015437/logs/provision-portainer-stack.log

The full proof rerun already proved that all 10 in-scope stacks destroy/apply
successfully and that 9 of 10 provision successfully. The only remaining
blocker is portainer-stack provision.

Treat the currently proven blocker narrowly:
- `reconcile-edge.py` target preflight fails with `EGR200` on production
  because it still shells out through `./with-secrets`, which expects
  `pve-test`
- missing Authentik-owned Portainer route objects were discovered, but the
  reconcile remained in dry-run, so the apply/create path has not yet been
  proven broken

Fix the production-targeting/preflight path in source, keep scope tight to
Portainer, and then rerun only:
./with-secrets-prod ./scripts/provision.sh --stack portainer-stack

Do not apply stash@{0}. Do not rerun the full infra-only proof packet yet. Do
not broaden scope into unrelated stack repairs.

Use TASK_APPROVAL=portainer-prod-targeting-fix-20260524 for production mutation
steps.

Capture complete evidence and write a tracked handback at:
docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md

The handback must say:
- what the actual proven root cause was
- which files changed
- whether `EGR200` is resolved
- whether reconcile reached apply mode on `pve`
- whether missing Authentik-owned Portainer route objects were created
- whether `portainer-stack` provision now succeeds
- whether the repo is ready for another fresh full proof rerun
```
