# NetBox Day-2 Bootstrap Fix Handoff (pve)

## Purpose

Use this handoff to fix the source-controlled NetBox day-2/bootstrap path on
production `pve` so `./scripts/provision.sh --stack netbox-stack` can converge
cleanly on rerun without requiring a full teardown/rebuild.

## Problem Statement

The full infra-only retry proved that the broad production parity issues were
not the remaining blocker:

- the production template was replaced with the same artifact used on
  `pve-test`
- the shared non-secret env baseline was converged
- the missing prod-only secret-key surface was filled in without changing
  existing prod values
- `netbox-stack` apply succeeds on `pve`
- NetBox reaches a healthy main-container state

The remaining blocker is now narrow and source-controlled:

- `deploy-netbox-stack.yml` hangs during the day-2 bootstrap path
- the rebuild stopped at `TASK [Create superuser if not exists]`
- a direct `manage.py` probe inside the container also failed to return
  promptly

This should be treated as a NetBox day-2/bootstrap code defect, not as a
template, wrapper, or broad platform-parity issue.

## Current Live State

Current infrastructure containers visible on `pve` after the stopped retry:

- present:
  - `10063` `ci-runner-01`
  - `20010` `authentik-stack`
  - `20011` `step-ca`
  - `20012` `monitoring-stack`
  - `20013` `dns-stack`
  - `30010` `proxy-stack`
  - `40010` `harbor-stack`
  - `40011` `apt-cacher-stack`
  - `40012` `netbox-stack`
  - `910` `debian13-template-builder`
- absent:
  - `20020` `portainer-stack`

Do not broaden this session into a Portainer restore or another full teardown
unless the operator explicitly asks for it.

## Evidence To Start From

Primary retry evidence:

- [docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md:1)
- [docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/provision-netbox-stack.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/provision-netbox-stack.log:1)
- [docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/netbox-direct-health-after-stop.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/netbox-direct-health-after-stop.log:1)
- [docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/manual-stop-summary.txt](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/manual-stop-summary.txt:1)
- [docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/post-stop-pve-authoritative.log](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/post-stop-pve-authoritative.log:1)

Useful earlier NetBox recovery context:

- [docs/productionize-refactor/handoffs/25-netbox-pve-recovery-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/25-netbox-pve-recovery-handback.md:1)
- [docs/productionize-refactor/handoffs/27-codex-continuation-handoff.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/27-codex-continuation-handoff.md:1)

## Code Paths To Inspect First

- [terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml:1)
- [terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md:1)
- [terraform/lxc/stacks/netbox-stack/README.md](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/netbox-stack/README.md:1)
- [scripts/provision.sh](/home/steve/git/proxmox-homelab/scripts/provision.sh:1)

## Current Behavior To Explain

From the retry evidence:

- Terraform/LXC creation path for `netbox-stack` succeeded
- the playbook advanced through Docker host prep, config copy, compose deploy,
  and `Wait for NetBox to be healthy`
- it then stopped at `Create superuser if not exists`
- the container was not broadly dead:
  - `netbox-netbox-1` was healthy
  - `netbox-netbox-worker-1` was healthy
  - `netbox-netbox-housekeeping-1` was still `health: starting`

From the code:

- the playbook currently uses two bootstrap mechanisms:
  - `manage.py createsuperuser`
  - a later ORM-based `manage.py shell` admin-sync script

The next session should explain which of those paths is actually unsafe on
production rerun and simplify the bootstrap behavior accordingly.

## Goal

Make `netbox-stack` day-2 provisioning on `pve` converge safely:

1. `./scripts/provision.sh --stack netbox-stack` should finish without hanging.
2. The superuser/local-admin/API-token bootstrap path should be idempotent on
   rerun.
3. Failures in bootstrap should fail fast with bounded evidence, not block
   indefinitely.
4. `pve-test` should remain the reference behavior and must not regress.

## Acceptable Fix Shapes

Any solution that meets the goal is fine. Likely shapes:

- remove `createsuperuser` as the primary path and use one deterministic ORM
  sync path instead
- keep `createsuperuser` only if it can be proven bounded and rerunnable
- wrap the admin/bootstrap commands in an explicit timeout and fail fast on
  hangs
- capture stdout/stderr/exit code for the bootstrap commands so future review
  does not depend on transient terminal output

## Constraints

- Do not apply `stash@{0}`.
- Do not rerun the full infra teardown/rebuild packet in this task.
- Do not broaden scope into Portainer recovery unless the operator explicitly
  asks for it.
- Prefer a narrow source-controlled playbook fix over in-place one-off
  mutations inside the live container.
- Preserve idempotence.
- Treat `pve-test` as the reference model for intended lifecycle behavior.

## Suggested Work Sequence

1. Re-read the handbacks and logs listed above.
2. Reproduce only the stuck NetBox bootstrap commands on the existing
   `netbox-stack`, with an explicit timeout and captured evidence.
3. Determine whether the hang is in:
   - `createsuperuser`
   - the later local-admin ORM sync
   - both
4. Patch `deploy-netbox-stack.yml` to use one bounded, idempotent bootstrap
   path.
5. Run syntax validation on the changed playbook.
6. Run targeted production validation only for `netbox-stack`:
   - `./with-secrets-prod ./scripts/provision.sh --stack netbox-stack`
7. Capture post-run evidence showing pass/fail and the resulting live state.

## Minimum Validation

At minimum, the next session should do:

- code-path inspection with `rg` / `sed`
- Ansible syntax check for `deploy-netbox-stack.yml`
- bounded targeted live validation on `netbox-stack`
- a tracked handback with evidence paths

If live validation is not performed, the handback must say so clearly.

## Required Runtime Inputs

Use the existing production wrapper and explicit task approval for any mutation:

- `./with-secrets-prod ...`
- `TASK_APPROVAL=netbox-day2-bootstrap-fix-20260524`

Before any live mutation, confirm:

- `./with-secrets-prod bash -lc 'echo $TF_VAR_proxmox_node'` returns `pve`
- the task stays scoped to `netbox-stack`

## Required Handback Artifact

The next session must create a tracked handback note at:

- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md`

That note should include:

- what root cause it confirmed
- what files it changed
- what exact bootstrap path it kept or removed
- what validation it ran
- whether live production validation was executed
- the resulting state of `netbox-stack`
- any remaining operator steps or risks

## Done When

- the NetBox day-2/bootstrap root cause is explained
- code changes are made if needed
- targeted validation is run or explicitly deferred
- the handback file exists and is populated
- the branch is left in a state that can be reviewed without re-deriving the
  issue

## Suggested Copilot Brief

```text
Fix the source-controlled NetBox day-2/bootstrap path on production pve.
Start from docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md,
docs/productionize-refactor/handoffs/25-netbox-pve-recovery-handback.md,
and docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix.md.

The current issue is narrow: netbox-stack apply succeeds and NetBox reaches a
healthy main-container state, but the production retry hangs in
terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml at
`Create superuser if not exists`. Treat this as a day-2/bootstrap code defect,
not a template, wrapper, or broad platform-parity problem.

Read the cited evidence first. Reproduce only the stuck bootstrap commands on
the existing netbox-stack with explicit timeout and captured evidence. Then
patch deploy-netbox-stack.yml so the admin/bootstrap path is bounded and
idempotent on rerun. Prefer one deterministic bootstrap path over multiple
overlapping ones.

Do not apply stash@{0}. Do not rerun the full infra teardown/rebuild packet.
Do not broaden scope into Portainer recovery unless explicitly asked.

Validate with syntax checks plus targeted production rerun of:
./with-secrets-prod ./scripts/provision.sh --stack netbox-stack

Use TASK_APPROVAL=netbox-day2-bootstrap-fix-20260524 for production mutation
steps. Write a tracked handback at
docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md
with root cause, files changed, validation, resulting state, and remaining
risks.
```
