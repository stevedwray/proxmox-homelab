# Next Session Note

## Current State

- `work/step-ca-authentik-direct-tls-01` has been promoted to
  `baseline/teardown-validated`.
- Promotion merge commit on baseline: `7ed6044`
- Successful full teardown/redeploy evidence remains:
  `docs/teardown-test/reports/20260516-052235.md`
- The `step-ca` / Authentik direct-TLS rollout is complete for the intended
  scope:
  - Grafana backchannel migrated
  - Portainer backchannel migrated
  - Traefik forward-auth migrated
  - Harbor direct/Auth backchannel remains intentionally deferred

## What Is Done Enough

Do not reopen these without a new explicit requirement:

- stack-owned edge architecture basics
- Stage 9 teardown/redeploy proof
- baseline promotion decision for the step-ca direct-TLS branch
- Grafana/Portainer/Traefik Authentik direct-TLS migration work

## What Actually Needs Attention Next

The next useful work is convergence and hardening, not more platform redesign.

Priority order:

1. Documentation convergence
   - align stale docs with the current branch model and validated baseline
   - remove old `dev/pve-test` / `refactor/stack-lifecycle` assumptions where
     they are no longer authoritative
   - update stale app-migration and ingress references that still mention
     `homelab.internal`, NPM, or pre-refactor routing behavior

2. Teardown harness hardening
   - treat `scripts/teardown-deploy-test.sh` as product code
   - add stronger approval-packet validation, self-tests, and cleaner summary
     output

3. Shared stack-contract tidyup
   - close small real contract gaps like explicit `dns_server` coverage and
     validation so rebuild behavior is less implicit

4. Re-plan app migration against the repo as it exists now
   - update Phase 06 docs to the stack-owned edge model and current naming
     (`*.lab.gibbsgreatly.xyz`)
   - only then start app-stack implementation slices

5. Narrow `step-ca` follow-up
   - Harbor-specific posture
   - direct-cert renewal/expiry checks
   - CA rotation/compromise response docs

## Recommended Execution Style

- Do small bookkeeping/tidyup directly in-session.
- For broader edits, code changes, or multi-file command-heavy work, prefer a
  Copilot handoff prompt with bounded scope and explicit validation.

## Prompt Pack

Use:

- [docs/prompts/post-baseline-evolution-pack.md](../prompts/post-baseline-evolution-pack.md)

Start with prompt 01, then 02, then 03, then 04. Prompt 05 is optional and
should wait until the earlier convergence/hardening work is finished.
