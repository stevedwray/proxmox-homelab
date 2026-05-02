# Session Report: session-baseline-full-cycle-03

- Session ID: `session-baseline-full-cycle-03`
- Branch: `work/baseline-full-cycle-02`
- Issue: `#162`
- Stamp: `20260502-baseline-full-03`
- Baseline SHA: `fa3224b454010be128621cae75bf8ba40f34b10d`
- Runtime validated SHA: `5372c5fa4ed9b81f8883024ce818d056d5e0bd8a`
- Timestamp (UTC): `2026-05-01T23:03:14Z`

## Objective

Recover the interrupted full-cycle run at `activate-edge`, remove the post-Authentik startup race, and complete the remaining deployment and validation gates on `pve-test`.

## Summary

1. Original cycle run for stamp `20260502-baseline-full-03` failed in `activate-edge` at `reconcile-edge-apply` immediately after Authentik startup.
2. Recovery implemented:
   - Added an Authentik API readiness gate in `scripts/teardown-deploy-test.sh` before `reconcile-edge-apply`.
   - Targeted Authentik rebuild performed (`destroy` + `apply` + provision for VMID 150).
3. Resume execution outcomes:
   - `activate-edge`: passed.
   - `deploy-platform`: passed.
   - `final-validation`: passed.
4. User validation confirmed all six browser portals were accessible.

## Code Change

- Commit: `5372c5fa4ed9b81f8883024ce818d056d5e0bd8a`
- Message: `Add Authentik API readiness gate before edge reconcile`
- Files:
  - `scripts/teardown-deploy-test.sh`
  - `certs/homelab-root.crt`

## Root Cause and Fix

- Failure mode: `reconcile-edge-apply` encountered transient Authentik API authorization/readiness failures during immediate post-boot activation.
- Fix: added `wait-authentik-api-ready` gated probe using `AUTHENTIK_SUPERUSER_API_TOKEN` against `/api/v3/core/applications/?page_size=1` with bounded retries before running reconcile.

## Runtime Evidence

- Stamp state:
  - `docs/teardown-test/evidence/20260502-baseline-full-03/state.json`
- Original failure evidence:
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/reconcile-edge-apply.log`
- Recovery evidence:
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/wait-authentik-api-ready.log`
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/reconcile-edge-apply.log`
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/reconcile-edge-post-activate-dry-run.log`
- Platform and final validation evidence:
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/deploy-monitoring-stack.log`
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/deploy-netbox-stack.log`
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/deploy-portainer-stack.log`
  - `docs/teardown-test/evidence/20260502-baseline-full-03/logs/teardown-deploy-test-20260502-baseline-full-03.log`

## Gate Outcome Notes

- The `cycle` phase remains marked failed in stamp state because that historical phase captured the original `activate-edge` failure.
- All downstream required runtime gates were successfully completed from the recovery point with the fix in place.
