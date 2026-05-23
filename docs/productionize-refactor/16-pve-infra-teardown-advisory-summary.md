# pve Infra-Only Teardown Advisory Summary

## Purpose

Capture the practical outcome of the first read-only `pve` infra-only teardown
planning pass.

This summary is intentionally operational and advisory. It is not a destroy
approval packet.

## Current State

The repo now has:

- a frozen `pve` infra-only stack inventory:
  [pve-infra-teardown-inventory.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-infra-teardown-inventory.md:1)
- a planner design doc:
  [15-pve-infra-only-teardown-planner.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/15-pve-infra-only-teardown-planner.md:1)
- an advisory read-only planner script:
  [plan-pve-infra-teardown.sh](/home/steve/git/proxmox-homelab/scripts/plan-pve-infra-teardown.sh:1)
- a Copilot handback for that implementation:
  [15-pve-infra-only-teardown-planner-handback.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/15-pve-infra-only-teardown-planner-handback.md:1)

## What The Planner Already Proves

For the stamped read-only run `20260523-154500`, the planner successfully:

- validated the frozen infra-only inventory against current `stack.yaml` data
- captured live read-only `pve` guest and storage status
- ran per-stack `terragrunt plan -destroy` for the in-scope infrastructure set
- produced a consolidated summary packet under the ignored evidence directory

Primary evidence:

- [summary.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-154500/summary.md:1)

## What It Does Not Yet Prove

This planner is useful, but advisory only.

It does **not** yet prove enough to authorize destructive execution without
human log review because:

- per-stack destroy plans still resolve to `review detailed destroy-plan log`
  rather than a strong automated pass/fail verdict
- blocker detection is currently narrower than a full resource-address scope
  check
- shared-storage impact is visible through evidence, but not yet classified into
  a trusted machine-checked safety verdict

## Input Parity Clarifications (Audit Follow-Up)

The current advisory posture for infra-only teardown planning is:

1. Runner auth is an operator preflight prerequisite when `ci-runner-01` is in
   scope.
   - required check: `gh auth status`
   - planner runs should be treated as blocked for runner-inclusive scope if
     this preflight is not healthy

2. Grafana OAuth tuning parity remains a known review item.
   - keys: `GRAFANA_OAUTH_SCOPES`, `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH`
   - canonical production owner: `.env.pve`
   - if absent there, playbook defaults are expected and should be reviewed as
     intentional behavior, not assumed parity

3. Harbor `HARBOR_OIDC_PRIMARY_AUTH_MODE` ownership is documented as
   non-secret env overlay input.
   - canonical production owner: `.env.pve`
   - a parallel definition in `terraform/secrets.pve.enc.yaml` is treated as
     precedence ambiguity and should be reviewed before teardown approval

## Practical Safety Reading

Treat the planner as a read-only preparation aid for these questions:

1. Which stacks are in scope?
2. Which live guests on `pve` are explicitly out of scope and must remain
   untouched?
3. Do the in-scope destroy plans target `pve` and avoid obvious `pve-test`
   bleed-through?
4. What logs must a human inspect before any real teardown approval?
5. Have runner auth preflight and OIDC parity review items been explicitly
  acknowledged for this run?

Do **not** treat it as:

- a go/no-go authority for production destroy
- a substitute for human review of destroy-plan logs
- proof that storage effects are fully constrained

## Out-Of-Scope Guests Observed On pve

The planner evidence explicitly observed live out-of-scope guests on `pve`,
including:

- `torrent-stack`
- `management-stack`
- `media-stack`
- `gaming-stack`
- `cloud-stack`
- `proxmox-backup-server`
- `wazuh`
- `security-stack`
- `analysis-stack`
- `elastic-stack`
- `omada-controller`
- `scanning-stack`
- `ai-stack`
- `pve-test`
- `test-docker`
- `debian13-template-builder`
- the out-of-scope VMs listed in the same summary packet

This is the practical reason the planner must remain conservative: the host is
shared with many non-platform workloads that must not be touched.

## Practical Next Step

Before any future teardown approval discussion, the operator should use the
planner output this way:

1. Re-run the advisory planner to refresh live evidence.
2. Review the generated summary.
3. Inspect each `plan-destroy-*.log` manually.
4. Stop if any scope ambiguity or storage ambiguity appears.

## If More Automation Is Wanted

Any next implementation slice should be treated as Copilot work, not direct
assistant implementation. The most useful future improvement would be stronger
resource-scope parsing so the planner can detect cross-scope references more
reliably.
