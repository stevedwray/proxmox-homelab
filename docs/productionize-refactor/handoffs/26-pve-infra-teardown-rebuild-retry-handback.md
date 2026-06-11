# pve Infra-Only Teardown/Rebuild Retry Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation
Task approval: pve-infra-teardown-rebuild-retry-20260524
Scope: fresh full infra-only teardown/rebuild retry on production `pve`, using only committed source fixes.

## Starting State

- Starting git status: clean working tree on `work/productionize-06-canary-validation`
- Stash state at start: `stash@{0}: netbox in-place recovery debug patch`
- Stash usage: not applied during this retry

## Evidence Paths

- Planner/preflight evidence: `docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-232209`
- Planner summary: `docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-232209/summary.md`
- Execution evidence: `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209`
- Human review note before destroy: `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/pre-destroy-human-review.txt`
- Manual stop note: `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/manual-stop-summary.txt`
- Authoritative post-stop `pve` state: `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/post-stop-pve-authoritative.log`
- Direct NetBox host snapshot after stop: `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/netbox-direct-health-after-stop.log`

## Planner / Preflight Review

The fresh planner/preflight for stamp `20260523-232209` was reviewed before destructive action.

Confirmed from `summary.md` and the detailed planner logs:

- target remained `pve`
- no `pve-test` targeting in the in-scope destroy plans
- no out-of-scope VMIDs in the in-scope destroy plans
- all approved in-scope guests were present in the planner scope:
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

## Destroy Results

All approved in-scope destroy phases completed successfully.

Successful destroys:

- `portainer-stack`
- `netbox-stack`
- `monitoring-stack`
- `harbor-stack`
- `authentik-stack`
- `proxy-stack`
- `step-ca-stack`
- `dns-stack`
- `ci-runner-01`
- `apt-cacher-stack`

Supporting evidence:

- per-stack destroy logs under `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/`
- per-stack destroy status files under `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/phase-status/`
- post-destroy platform checks:
  - `logs/post-destroy-pct-list.log`
  - `logs/post-destroy-qm-list.log`
  - `logs/post-destroy-pvesm-status.log`

## Rebuild / Provision Results

Fully rebuilt and provisioned successfully:

- `apt-cacher-stack`
- `ci-runner-01`
- `dns-stack`
- `step-ca-stack`
- `proxy-stack`
- `authentik-stack`
- `harbor-stack`
- `monitoring-stack`

Partially rebuilt:

- `netbox-stack`
  - apply succeeded
  - provision did not complete

Not rebuilt after the stop point:

- `portainer-stack`
  - destroy succeeded earlier in the packet
  - no apply/provision phase ran in this retry after execution stopped at `netbox-stack`

Supporting status evidence from `phase-status/`:

- `apply-netbox-stack.status`: `succeeded`
- `provision-netbox-stack.status`: `attempted`
- no `apply-portainer-stack.status` or `provision-portainer-stack.status` exists in this execution directory

## Failure / Stop Point

Broad execution stopped at `netbox-stack` provision and did not continue to later rebuild/validation phases.

Exact failure behavior:

- Log path: `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/provision-netbox-stack.log`
- Last emitted task in the log:
  - `TASK [Create superuser if not exists] ******************************************`
- The play advanced through:
  - Docker base configuration
  - NetBox configuration file provisioning
  - compose deployment
  - `Wait for NetBox to be healthy`
- It then stopped emitting task results at the superuser/bootstrap step.

Additional evidence captured before manual stop:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/netbox-direct-health-after-stop.log`
  - `netbox-netbox-1` was healthy
  - `netbox-netbox-worker-1` and `netbox-netbox-housekeeping-1` were still `health: starting`
- a direct `manage.py` inspection from inside `netbox-netbox-1` also failed to return promptly
- the local ansible process was manually stopped to comply with the stop-on-failure rule and prevent silent indefinite runtime

Execution stopped: yes

## Post-Redeploy Validation

Full post-redeploy validation for all in-scope stacks was not run because the rebuild did not complete.

What was validated successfully before the stop:

- the eight fully provisioned stacks above completed their apply/provision phases successfully
- `monitoring-stack` is the last fully completed stack before the stop and its provision log ends with `PLAY RECAP` and `[provision] Completed provision orchestration`

What was not fully validated:

- `netbox-stack` end-to-end provision and admin/bootstrap automation
- `portainer-stack` rebuild and any post-redeploy validation tied to it

## Out-of-Scope Guest Verification

Out-of-scope verification compared the planner's out-of-scope inventory to the authoritative post-stop `pve` checks.

Planner out-of-scope baseline:

- `docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-232209/logs/platform-status-out-of-scope-guests.log`

Authoritative post-stop state:

- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/post-stop-pve-authoritative.log`

Observed result:

- out-of-scope guests remained present with the same running/stopped disposition seen in the planner baseline
- `pve-test` remained untouched and still `stopped`
- no evidence was captured of changes to out-of-scope VMs, containers, storage pools, templates, backups, or unrelated host configuration

## Overall Result

Result: failed

Reason:

- the fresh infra-only destroy phase succeeded in scope
- the rebuild progressed through eight stacks successfully
- `netbox-stack` apply succeeded but provision hung at the admin bootstrap step
- `portainer-stack` was therefore not rebuilt in this retry
- the full approved objective, a completed fresh infra-only teardown/rebuild proof from committed source, was not met

## Operator Next Steps

1. Treat this retry as a failed full-run proof, not as teardown/redeploy sign-off.
2. Investigate and fix the `netbox-stack` source-controlled admin/bootstrap path around `Create superuser if not exists` before the next production proof run.
3. Do not use the stashed in-place NetBox debug patch for the next attempt.
4. After the source fix is committed, decide whether to:
   - restore the missing `portainer-stack` and resolve `netbox-stack` operationally, then schedule another fresh full infra-only retry for proof, or
   - immediately rerun a fresh full infra-only teardown/rebuild packet from source if the production window allows.
