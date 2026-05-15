# Handoff

## Current State

- Stages 1–5 are complete.
- Exemplar pair `apt-cacher-stack` and `harbor-stack` validated end-to-end on branch `task/slr-05-exemplar-validation`.
- Check mode, live reconcile, health checks, and approval-gated post-infra path all pass for both exemplars.
- First Stage 6 implementation slice for `ci-runner-01` is complete with check mode, live reconcile, and systemd health validation passing.

## Current Phase

- Stage 6: first implementation slice complete for `ci-runner-01`.
- Current branch name is `task/slr-06-rollout-ci-runner-01`, matching the approved platform deployment order.

## Established Working Assumptions

- Terraform owns day-1 infrastructure and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- Shared inventory is an evolution of `stack.yaml`.
- Generated artifacts are derived only.
- Terraform may offer an approved post-change day-2 reconcile path.

## Suggested Next Step

Choose the next bounded Stage 6 platform rollout target after `ci-runner-01` before further Stage 6 work.

Stage 6 scope definition for this branch:

- First rollout target: `ci-runner-01` (single-stack slice)
- Why chosen: next in the approved platform deployment order after the validated exemplar pair, with a contained systemd service boundary and fewer cross-stack touchpoints than later stacks
- Expected changes (next implementation session):
  - apply exemplar-proven reconcile pattern to `ci-runner-01` only
  - make only bounded fixes required for check-mode and idempotent rerun behavior
  - keep those fixes inside `deploy-ci-runner.yml`, specifically around GitHub token generation, `config.sh` registration/removal, `svc.sh install`, runner service start, and GitHub online verification
  - keep contract and workflow updates limited to what `ci-runner-01` needs
- Validation evidence required:
  - check-mode pass for the stack-specific reconcile path
  - live reconcile pass with no fatal failures
  - health check pass against the runner service or unit status path used for `ci-runner-01`
  - evidence captured under a stack-specific Stage 6 evidence directory for `ci-runner-01`
  - check-mode log should show local configuration tasks converging without requiring a live GitHub registration side effect
  - live health log should confirm `actions.runner.*.service` is running, matching the existing repo health check model
- Risks:
  - stack-specific bootstrap tasks may expose new check-mode edge cases
  - GitHub token lifecycle and online-registration checks are external dependencies that can make dry-run behavior noisier than the earlier exemplar pair unless explicitly handled
  - branch naming now matches the `ci-runner-01` rollout target
- Non-goals:
  - no multi-stack rollout in the first Stage 6 slice
  - no special-case redesign work
  - no broad Terraform/Ansible architecture rewrites

## Open Questions To Carry Forward

- acceptable non-idempotent output threshold for exemplar bootstrap/reconcile runs
- whether drift handling remains reporting-only or needs early hard-fail rules for exemplars
- whether any exemplar-specific contract extension is needed before wider rollout

## Stage 6 Kickoff Outcomes

- Stage: 6 — Clean Platform Stack Rollout.
- Branch: `task/slr-06-rollout-ci-runner-01`.
- What changed:
  - corrected Stage 6 candidate list and first-rollout scope to follow the approved platform deployment order after the validated exemplar pair
  - documented `ci-runner-01` as the actual next rollout target and deferred `portainer-stack` because its current implementation also depends on later identity and proxy publication flows
  - defined the bounded first implementation slice for `ci-runner-01` around `deploy-ci-runner.yml` registration, service install/start, and runner health verification tasks
  - updated `deploy-ci-runner.yml` so check mode skips non-materialized runner install and GitHub-side registration steps while still validating local configuration work
- What was validated:
  - check mode: `./with-secrets ./scripts/provision.sh --stack ci-runner-01 --check` exited 0 after the bounded playbook fixes
  - live reconcile: `./with-secrets ./scripts/provision.sh --stack ci-runner-01` exited 0 and completed runner registration plus GitHub online verification
  - health check: runner unit `actions.runner.stevedwray-proxmox-homelab.ci-runner-pve-test.service` is active and running
  - evidence: `docs/sessions/evidence/slr-06-rollout-ci-runner-01/check.log`, `docs/sessions/evidence/slr-06-rollout-ci-runner-01/live.log`, `docs/sessions/evidence/slr-06-rollout-ci-runner-01/health.log`
- Remaining risks / follow-up:
  - this session first had to recover the generated `inventory.yml` handoff artifact for `ci-runner-01`; the targeted recovery apply also recreated the stack LXC and SDN attachment because they were absent from local state
  - the branch name still reflects the superseded Portainer-first planning assumption
  - next Stage 6 work should decide whether to continue on the next platform stack or first clean up the branch naming mismatch

## Session Closeout Checklist

- update [decisions.md](./decisions.md) if a decision is made
- update [plan.md](./plan.md) if phase or scope changes
- update this file with:
  - what changed
  - what was validated
  - what remains next

## Stage 3 Outcomes

- Stage: 3 — Exemplar selection and scoped documentation.
- Session: `slr-03-main-work-01` on branch `task/slr-03-exemplar-scope`.
- Outcome:
  - selected exemplar pair: `apt-cacher-stack` and `harbor-stack`
  - scope and non-goals captured in `stage-03-exemplar-scope.md`

## Stage 4 Outcomes

- Stage: 4 — Exemplar scaffolding.
- Session: `slr-04-main-work-01` on branch `task/slr-04-exemplar-scaffolding`.
- What changed:
  - added `scripts/reconcile-exemplar-stacks.sh` as a bounded day-2 reconcile entrypoint for the exemplar pair only
  - added optional approval-gated `--post-infra` mode with required `--approval-text`
  - preserved existing deployment behavior by delegating execution to `scripts/provision.sh --stack <name>`
  - updated Stage 4 status in `plan.md`
  - updated this handoff for Stage 5 start
- What was validated in-session:
  - branch is `task/slr-04-exemplar-scaffolding`
  - script argument parsing and gating logic pass static shell parsing (`bash -n`)
  - help output and command wiring are in place for exemplar-only scope
- Next:
  - execute Stage 6 rollout for additional platform stacks

## Stage 5 Outcomes

- Stage: 5 — Exemplar Validation And Adjustment.
- Branch: `task/slr-05-exemplar-validation`.
- What changed:
  - fixed check-mode failures in `deploy-apt-cacher-stack.yml`: added `ignore_errors: "{{ ansible_check_mode }}"` to service and lineinfile tasks that cascade when the package is not yet installed in check mode
  - fixed check-mode failures in `harbor_installer` role: added `and not ansible_check_mode` to download/unpack block, `ignore_errors` to enable/start service tasks
  - fixed check-mode robustness in `harbor_postconfigure` role: `meta: end_play` guard at top (all tasks are Harbor API calls requiring a live instance), `default([])` on registries loop, `when` guard on display task
- What was validated:
  - check mode: both stacks exit 0 with no fatal unignored failures
  - live reconcile: apt-cacher (ok=6, changed=3, failed=0); harbor (ok=63, changed=14, failed=0)
  - health checks: apt-cacher HTTP 406 (PASS); harbor v2 registry HTTP 401 (PASS); pct status running for both
  - post-infra approval gate: apt-cacher (ok=5, changed=0, failed=0); gate correctly accepted approval text
  - evidence: `docs/sessions/evidence/slr-05-exemplar-validation/`
- What remains:
  - Stage 6: rollout to additional platform stacks using the validated model
