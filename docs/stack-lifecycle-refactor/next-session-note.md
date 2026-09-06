# Next Session Note

## Current State

- `work/step-ca-authentik-direct-tls-01` has been promoted to
  `baseline/teardown-validated`.
- Post-baseline convergence/hardening follow-up work is also now promoted to
  `baseline/teardown-validated`.
- Current promotion merge commit on baseline: `cf908a4`
- Latest successful full teardown/redeploy evidence:
  `docs/teardown-test/reports/20260516-235620.md`
- The following post-baseline slices are complete and merged:
  - teardown harness hardening slice: structural approval-packet validation
  - stack-contract tidyup: explicit `dns_server` coverage and validation
  - Phase 06 replanning pass
  - `step-ca` follow-up: CA compromise/rotation runbook
  - homelab teardown approval simplification (`--approval-text "approve"`)

## What Is Done Enough

Do not reopen these without a new explicit requirement:

- stack-owned edge architecture basics
- Stage 9 teardown/redeploy proof
- baseline promotion decision for the step-ca direct-TLS branch
- Grafana/Portainer/Traefik Authentik direct-TLS migration work
- Prompts 01 through 05 from the post-baseline evolution pack
- teardown approval wording bikeshedding

## What Actually Needs Attention Next

The next useful work is operational trust hardening and then Phase 06 execution.

Priority order:

1. `platform-status` hardening
   - the successful `20260516-235620` cycle passed, but a later
     `platform-status` rerun falsely reported every stack as stopped because SSH
     to `pve-test.gibbsgreatly.xyz` failed name resolution on the operator host
   - treat this as the top harness trust issue: either make the host lookup
     resilient or fail explicitly as a status-collection blocker instead of
     reporting the platform as stopped

2. Phase 06 Task 06-01
   - perform real workload discovery and inventory capture
   - replace the remaining `discovery required` placeholders with actual source
     workload state

3. Phase 06 Task 06-02
   - confirm or create the `app_seg` / `game_seg` target zones
   - only then choose the first app migration slice

4. Later `step-ca` follow-up if needed
   - Harbor-specific posture
   - renewal/expiry/reload checks

## Recommended Execution Style

- Do small bookkeeping/tidyup directly in-session.
- For broader edits, code changes, or multi-file command-heavy work, prefer a
  Copilot handoff prompt with bounded scope and explicit validation.

## Working Packet

The earlier prompt pack has been removed as transient agent-support material.
If this historical note is reused, create a fresh task or short session note
for:

1. `platform-status` hardening
2. then the first Phase 06 implementation-planning slice
