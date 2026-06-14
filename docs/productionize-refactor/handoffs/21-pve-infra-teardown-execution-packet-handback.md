# 21 pve Infra Teardown Execution Packet Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation

## Summary

Created the operator-facing execution packet for a real infra-only teardown test
on production `pve`, using existing approved scope and advisory evidence.

This handback documents what changed, assumptions, unresolved ambiguities, and
remaining risk.

## Files Created Or Changed

- Created `docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md`
- Created `docs/productionize-refactor/handoffs/21-pve-infra-teardown-execution-packet-handback.md`

## Assumptions Made

1. Human review and approval already cover shared-host blast radius for an
   infra-only test, as stated in the task prompt.
2. The in-scope stack list and VMIDs remain exactly as frozen in
   `docs/productionize-refactor/pve-infra-teardown-inventory.md` and reflected
   in the reviewed planner evidence stamp `20260523-173500`.
3. `./with-secrets-prod` is the required production wrapper for both read-only
   and mutating production commands.
4. Because `ci-runner-01` is in scope, `gh auth status` is a mandatory preflight
   condition before destroy execution.
5. `scripts/teardown-deploy-test.sh` is not used for production mutation because
   it is explicitly a `pve-test`-oriented harness.

## Command-Sequence Ambiguities Requiring Human Judgment

1. There is no dedicated production mutating harness equivalent to
   `scripts/teardown-deploy-test.sh`; the packet therefore uses explicit
   per-stack `terragrunt destroy/apply` and `scripts/provision.sh --stack`
   commands.
2. The inventory candidate deploy order and the broad platform ordering embedded
   in `scripts/provision.sh` are not identical in all positions. The packet
   resolves this by running `--stack` one stack at a time in explicit order,
   but operators should continue to treat order changes as review-triggering.
3. Advisory planner summary still contains human-review notes such as
   `review detailed destroy-plan log`; it is evidence for judgment, not
   machine authorization.
4. Storage impact interpretation remains operator-reviewed from `pvesm status`
   and logs; there is no automated storage-ownership safety classifier.

## Ready For Operator Use

Status: **Yes, with caution**.

The packet is ready for operator use as written for an infra-only pve teardown
exercise, provided the operator follows stop conditions exactly and does not
improvise beyond the documented scope.

## Remaining Risks The Packet Cannot Eliminate

1. Human log interpretation error (destroy-plan or storage interpretation).
2. Unexpected runtime behavior from shared-host dependencies not visible in
   static scope docs.
3. Partial failure during destroy/redeploy requiring operator judgment on retry
   versus pause.
4. Any undiscovered drift between documented out-of-scope guest set and live
   host state at execution time.

## Notes

- No teardown, destroy, apply, or provision command was executed in this task.
- This pass only produced documentation for controlled operator execution.
- Post-review corrections were later applied to the packet to:
  - require `set -euo pipefail` for logged command sequences
  - use SSH-capable host-state capture for `pct`, `qm`, and `pvesm`
  - keep live execution evidence under an ignored path
