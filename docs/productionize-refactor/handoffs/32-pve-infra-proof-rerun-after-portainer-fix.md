# pve Infra-Only Proof Rerun After Portainer Fix

## Purpose

Use this handoff to run a fresh full infra-only teardown/rebuild proof on
production `pve` after the narrow NetBox and Portainer blockers have both been
repaired and validated in targeted reruns.

This is the next broad proof attempt from the current repaired branch state.

## Goal

Prove that the production `pve` infrastructure foundation can now be torn down
and rebuilt from source while leaving every out-of-scope guest on `pve`
untouched.

Success means:

1. all approved in-scope stacks destroy cleanly
2. all approved in-scope stacks apply and provision cleanly
3. post-redeploy validation completes
4. out-of-scope guests remain untouched

## Starting State

Use the current branch state exactly as-is:

- branch: `work/productionize-06-canary-validation`
- HEAD includes:
  - `860df0a` `fix(prod): recover netbox bootstrap on pve`
  - `81d6c33` `fix(prod): unblock portainer proof rerun on pve`

Supporting handbacks for the current repaired state:

- [docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md:1)
- [docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md:1)
- [docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md:1)

What is already proven before this run:

- `netbox-stack` now provisions successfully on `pve`
- the full proof rerun got through 9 of 10 provisions before stopping at
  Portainer
- the Portainer target-preflight bug has been fixed in source
- targeted `portainer-stack` rerun succeeded on `pve`

This full packet is needed to re-prove the entire destroy/apply/provision path
from a fresh execution stamp.

## Primary Execution Packet

Use the existing controlled packet as the main operator procedure:

- [docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md:1)

## In-Scope Stack List

Scope remains exactly these 10 stacks:

- `ci-runner-01`
- `authentik-stack`
- `step-ca-stack`
- `monitoring-stack`
- `dns-stack`
- `portainer-stack`
- `proxy-stack`
- `harbor-stack`
- `apt-cacher-stack`
- `netbox-stack`

## Out Of Scope

- every other `pve` guest
- storage, templates, backups, unrelated host config
- `pve-test` VM
- application stacks and unrelated services

## Constraints

- Do not apply `stash@{0}`.
- Do not retarget to `pve-test`.
- Do not broaden scope beyond the 10 approved stacks.
- Do not "repair in place" if the proof run fails midstream; stop, capture
  evidence, and hand back.
- Preserve all out-of-scope guests exactly as protected by the execution
  packet.

## Required Runtime Inputs

Use:

- `./with-secrets-prod ...`
- `TASK_APPROVAL=pve-infra-proof-rerun-after-portainer-fix-20260524`
- `NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true`
- `NETWORK_SDN_EXPECTED_TARGET=pve`
- `NETWORK_SDN_EXPECTED_PVE_HOST=pve.gibbsgreatly.xyz`

Before destructive action, confirm:

- `./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'` returns `pve`
- the current branch is still `work/productionize-06-canary-validation`
- the current HEAD still includes the verified NetBox recovery commit
- the working tree still includes the reviewed Portainer targeting fix
  already committed in `81d6c33`

## Suggested Work Sequence

1. Re-read:
   - `18-pve-infra-teardown-execution-packet.md`
   - `30-pve-infra-proof-rerun-handback.md`
   - `31-portainer-prod-targeting-fix-handback.md`
2. Confirm the branch, working tree, and target-node preflight.
3. Refresh planner/preflight evidence for a new execution stamp.
4. Perform the required human advisory review before destroy.
5. Execute the full in-scope destroy sequence.
6. Execute the full in-scope redeploy/provision sequence.
7. Run the post-redeploy validation steps defined by the packet.
8. Capture authoritative post-run `pve` state.
9. Write a tracked pass/fail handback.

## Minimum Validation

At minimum, the run must capture:

- fresh planner/preflight evidence path
- fresh execution evidence path
- every destroy log/status
- every apply/provision log/status
- post-redeploy validation result
- authoritative post-run `pct/qm/pvesm` state
- explicit out-of-scope guest comparison

## Required Handback Artifact

Create:

- `docs/productionize-refactor/handoffs/32-pve-infra-proof-rerun-after-portainer-fix-handback.md`

That handback should include:

- whether the run started from the repaired NetBox plus Portainer branch state
- planner/preflight evidence path
- execution evidence path
- per-stack destroy/apply/provision outcomes
- post-redeploy validation outcome
- whether `portainer-stack` restored cleanly as part of the full proof
- whether out-of-scope guests remained untouched
- final overall result: passed or failed
- any remaining blockers or operator next steps

## Done When

- a fresh full infra-only proof run has been executed or cleanly stopped
- complete evidence exists for review
- the tracked handback is written
- the next state is unambiguous: either full proof passed, or a new specific
  blocker was captured

## Suggested Copilot Brief

```text
Run a fresh full infra-only teardown/rebuild proof on production pve from the
current repaired branch state.

Start from:
- docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md
- docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md
- docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md
- docs/productionize-refactor/handoffs/32-pve-infra-proof-rerun-after-portainer-fix.md

The branch state already includes:
- the verified NetBox recovery work
- the reviewed Portainer production-targeting fix in
  terraform/lxc/reconcile-edge.py

Use that state exactly as-is. Do not apply stash@{0}. Do not broaden scope
beyond the 10 approved infrastructure stacks on pve.

Use the existing execution packet as the controlling procedure. Refresh fresh
planner/preflight evidence first, perform the required human advisory review,
then run the full destroy and redeploy sequence on pve only.

Use:
- TASK_APPROVAL=pve-infra-proof-rerun-after-portainer-fix-20260524
- NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true
- NETWORK_SDN_EXPECTED_TARGET=pve
- NETWORK_SDN_EXPECTED_PVE_HOST=pve.gibbsgreatly.xyz

Capture complete evidence and write a tracked handback at:
docs/productionize-refactor/handoffs/32-pve-infra-proof-rerun-after-portainer-fix-handback.md

The handback must include:
- planner/execution evidence paths
- per-stack destroy/apply/provision outcomes
- post-redeploy validation result
- whether portainer-stack restored cleanly
- whether out-of-scope guests remained untouched
- overall pass/fail and remaining blockers
```
