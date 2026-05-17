# Next Session Work Plan

## Current State
- Baseline rehearsal cycle `20260516-235620` passed end-to-end and was documented.
- `platform-status` hardening was completed to report explicit `blocked` collection states instead of false `stopped` summaries when SSH/DNS collection fails.
- Branch to land: `task/platform-status-hardening-01`.

## Priority Slices
1. Add a run-level SSH collection banner in `platform-status`.
   - Add one early Proxmox SSH probe.
   - If unreachable, print a top-level collection blocker note before per-stack rows.
   - Keep per-stack rows and evidence outputs unchanged.
2. Harden post-cycle host status checks.
   - Fix defects in `scripts/check-proxmox-status.sh` and ensure gate output includes durable evidence paths.
   - Align with teardown harness evidence conventions.
3. Continue stack lifecycle refactor contract cleanup.
   - Resolve remaining Stage-1/Stage-2 contract and packet validation mismatches.
   - Keep `.git/ai/plan-state.yaml` and report artifacts consistent.
4. Finish remaining hardcoded infra value parameterization.
   - Replace leftover literals with env/variable-backed values.
   - Validate no regression in `pve-test` guard and edge renders.

## Suggested Session Start Commands
```bash
git checkout work/post-baseline-followups-integration-01
git pull --ff-only
git checkout -b task/platform-status-banner-01
./with-secrets /home/steve/.local/bin/sonar-scanner
```

## Acceptance Reminder
- Use short-lived working branches only.
- Run required scans before merge:
  - Shell/Python/YAML changes: `./with-secrets /home/steve/.local/bin/sonar-scanner`
  - Terraform changes: `/home/steve/.local/bin/snyk iac test terraform/`
- Do not run destructive teardown unless explicitly approved for that session.
