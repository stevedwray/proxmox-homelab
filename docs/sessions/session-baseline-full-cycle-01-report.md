# Session Report: session-baseline-full-cycle-01

- Session ID: `session-baseline-full-cycle-01`
- Branch: `work/baseline-full-cycle-01`
- Issue: `#162`
- Stamp: `20260502-baseline-full-01`
- Baseline SHA: `557bbe87feac2f6e4928e46ed3255fd690eb0d8f`
- Runtime validated SHA: `277de23447cb9592a6e791c00908b9a2bff96f7b`
- Timestamp (UTC): `2026-05-01T21:13:22Z`

## Objective

Execute a full `pve-test` teardown and redeploy validation cycle from `baseline/teardown-validated` and collect runtime evidence for destroy, redeploy, edge activation, platform deployment, and final validation.

## Summary

The full lifecycle was completed across the required phases for stamp `20260502-baseline-full-01`:

1. `approval-preflight` passed.
2. `destroy` passed.
3. `deploy-foundation` passed.
4. `deploy-edge` passed.
5. `activate-edge` initially failed only due clean-tree enforcement after expected certificate rotation, then passed after committing the expected cert update.
6. `deploy-platform` passed.
7. `final-validation` passed.
8. `platform-status` passed with all stacks healthy.

`cycle` remains recorded as failed in state due the mid-run clean-tree stop condition, but all downstream required runtime phases were completed successfully by resume from `activate-edge`.

## Notable Runtime Event

- The harness stopped at `activate-edge` with:
  - `ERROR working tree is dirty`
  - Dirty file: `certs/homelab-root.crt`
- This change was expected after full teardown/rebuild (root cert rotation) and was preserved as an intentional artifact.
- Commit created:
  - `277de23447cb9592a6e791c00908b9a2bff96f7b`
  - Message: `Record expected homelab root cert rotation after teardown/rebuild`

## Gate Evidence

- Approval preflight:
  - `docs/teardown-test/evidence/20260502-baseline-full-01/logs/teardown-deploy-test-20260502-baseline-full-01.log`
  - contains `DONE approval-preflight`
- Destroy completed:
  - same log contains `PASS verify-destroy-portainer-stack`
- Foundation completed:
  - same log contains `PASS health-ci-runner-01`
- Edge deploy completed:
  - same log contains `PASS health-authentik-stack`
- Edge activate resumed and passed:
  - same log contains `DONE activate-edge`
- Platform deploy completed:
  - same log contains `DONE deploy-platform`
- Final validation completed:
  - same log contains `DONE final-validation`
- Post-cycle platform health:
  - `docs/teardown-test/evidence/20260502-baseline-full-01/logs/platform-status.tsv`
  - `docs/teardown-test/evidence/20260502-baseline-full-01/logs/platform-status.json`
  - all stacks `healthy`

## Platform Status Snapshot

From `platform-status` at `2026-05-01T21:12:30Z`:

- `apt-cacher-stack` healthy
- `harbor-stack` healthy
- `ci-runner-01` healthy
- `dns-stack` healthy
- `proxy-stack` healthy
- `step-ca-stack` healthy
- `authentik-stack` healthy
- `monitoring-stack` healthy
- `netbox-stack` healthy
- `portainer-stack` healthy

## Result

The `pve-test` environment was torn down and rebuilt with successful runtime validation of edge and platform services. The expected root cert rotation was recorded and committed, and the remaining gates were completed from the recorded resume point.
