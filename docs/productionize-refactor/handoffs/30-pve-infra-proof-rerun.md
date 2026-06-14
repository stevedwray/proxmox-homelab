# pve Infra-Only Proof Rerun Handoff

## Purpose

Use this handoff to run a fresh full infra-only teardown/rebuild proof on
production `pve` from the current repaired branch state.

This is the next proof run after the NetBox day-2/bootstrap fix and targeted
memory-rerun recovery succeeded.

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
- commit containing the verified NetBox recovery:
  - `860df0a` `fix(prod): recover netbox bootstrap on pve`

What changed since the failed proof retry:

- `deploy-netbox-stack.yml` now uses one bounded unified bootstrap path
- `netbox-stack` memory is now `4096`
- targeted production rerun proved `./scripts/provision.sh --stack netbox-stack`
  succeeds on `pve`

Supporting handbacks:

- [docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md:1)
- [docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md:1)

Current live note:

- `portainer-stack` is still absent on `pve` from the previously stopped full
  proof attempt
- that is acceptable starting state for this full proof rerun because Portainer
  is in-scope and should be recreated by the approved packet if the run
  succeeds

## Primary Execution Packet

Use the existing controlled packet as the main operator procedure:

- [docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md:1)

Do not improvise a broader workflow if the packet already covers the step.

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
- `TASK_APPROVAL=pve-infra-proof-rerun-20260524`
- `NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true`
- `NETWORK_SDN_EXPECTED_TARGET=pve`
- `NETWORK_SDN_EXPECTED_PVE_HOST=pve.gibbsgreatly.xyz`

Before destructive action, confirm:

- `./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'` returns `pve`
- the current branch is still `work/productionize-06-canary-validation`
- the current HEAD still includes the verified NetBox recovery commit

## Suggested Work Sequence

1. Re-read:
   - `18-pve-infra-teardown-execution-packet.md`
   - `29-netbox-memory-rerun-handback.md`
   - `26-pve-infra-teardown-rebuild-retry-handback.md`
2. Confirm the branch and target-node preflight.
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

- `docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md`

That handback should include:

- whether the run started from the repaired NetBox branch state
- planner/preflight evidence path
- execution evidence path
- per-stack destroy/apply/provision outcomes
- post-redeploy validation outcome
- whether `portainer-stack` was restored as part of the full proof
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
- docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md
- docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun.md

The branch already contains the verified NetBox recovery commit:
- 860df0a fix(prod): recover netbox bootstrap on pve

Use that state exactly as-is. Do not apply stash@{0}. Do not broaden scope
beyond the 10 approved infrastructure stacks on pve.

Portainer is currently absent on pve from the previously stopped proof attempt.
That is acceptable starting state for this rerun because portainer-stack is
in-scope and should be recreated if the proof succeeds.

Use the existing execution packet as the controlling procedure. Refresh fresh
planner/preflight evidence first, perform the required human advisory review,
then run the full destroy and redeploy sequence on pve only.

Use:
- TASK_APPROVAL=pve-infra-proof-rerun-20260524
- NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true
- NETWORK_SDN_EXPECTED_TARGET=pve
- NETWORK_SDN_EXPECTED_PVE_HOST=pve.gibbsgreatly.xyz

Capture complete evidence and write a tracked handback at
docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md with:
- planner/execution evidence paths
- per-stack destroy/apply/provision outcomes
- post-redeploy validation result
- whether portainer-stack was restored
- whether out-of-scope guests remained untouched
- overall pass/fail and remaining blockers
```
