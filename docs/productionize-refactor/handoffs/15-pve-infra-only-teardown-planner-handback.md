# 15 pve Infra-Only Teardown Planner Handback

Date: 2026-05-23
Branch: work/productionize-06-canary-validation
Script: scripts/plan-pve-infra-teardown.sh
Validation stamp: 20260523-154500
Evidence root: docs/productionize-refactor/evidence/pve-infra-teardown-plan-20260523-154500/

## What Changed

- Completed the read-only planner implementation in scripts/plan-pve-infra-teardown.sh for the four intended phases only:
  - source-preflight
  - platform-status
  - plan
  - summary
- Kept scope tied to docs/productionize-refactor/pve-infra-teardown-inventory.md and stack metadata under terraform/lxc/stacks/*/stack.yaml.
- Fixed the known summary shell bug where printf format strings beginning with `-` were parsed as options.
- Added log-name sanitization for command-derived log file names.
- Hardened live read-only Proxmox collection with:
  - local command path when available
  - SSH fallback with read-only command invocation and safer options (`BatchMode`, `ConnectTimeout`, `StrictHostKeyChecking=accept-new`)
  - per-command status capture (`*.status`) for platform checks
- Added platform-status evidence derivation files:
  - logs/platform-status-in-scope-present.log
  - logs/platform-status-missing-in-scope.log
  - logs/platform-status-out-of-scope-guests.log
- Extended summary output to include:
  - platform check exit table (`pct-list`, `qm-list`, `pvesm-status`)
  - explicit out-of-scope guest listing from live pve output
  - missing in-scope VMID table when present
  - per-stack plan blocker checks for:
    - `pve-test` references
    - out-of-scope VMIDs parsed from plan logs

## Phase Status (Now)

- source-preflight: working
  - Validates inventory-table rows against stack.yaml VMID/IP.
  - Validates destroy-order entries map to inventory rows.
  - Fails if any in-scope stack is disabled.
- platform-status: working
  - Collects live read-only `pct list`, `qm list`, `pvesm status`.
  - Produces explicit in-scope present, missing in-scope, and out-of-scope guest evidence.
  - Fails phase if any of the read-only platform commands fail.
- plan: working
  - Runs per-stack `terragrunt plan -destroy` through with-secrets-prod.
  - Captures per-stack logs and status without adding any mutating action.
- summary: working
  - Builds consolidated evidence summary.
  - Includes platform-status and per-stack plan interpretation blocks.

## Validation Run

Commands executed (read-only):

1. scripts/plan-pve-infra-teardown.sh source-preflight --stamp 20260523-154500
2. scripts/plan-pve-infra-teardown.sh platform-status --stamp 20260523-154500
3. scripts/plan-pve-infra-teardown.sh plan --stamp 20260523-154500
4. scripts/plan-pve-infra-teardown.sh summary --stamp 20260523-154500

Observed results:

- source-preflight: pass
- platform-status: pass
  - pct-list exit 0
  - qm-list exit 0
  - pvesm-status exit 0
- plan: pass
  - all in-scope stacks produced exit 0 plan logs
- summary: pass after fixing the remaining leading-`-` printf call

## Remaining Blockers

No immediate read-only execution failure was observed for this planner run.

This planner should still be treated as advisory only, not as an approval-packet
authority.

Known review-required items before trusting approval packets:

- Per-stack logs currently report "review detailed destroy-plan log" when no explicit blocker match is found; a deeper parser for resource-address boundaries and shared-storage ownership would improve confidence.
- Summary checks include VMID and `pve-test` guards, but do not yet produce a machine-checked allowlist of all Terraform resource addresses per stack.

## Real pve SSH Read-Only Validation Result

Succeeded.

- Live read-only collection against pve completed via SSH fallback path.
- Out-of-scope guests were explicitly enumerated in evidence and summary.
- In-scope VMIDs were all observed as present for this run.

## Follow-Up Work Before Approval-Packet Trust

- Add stricter per-stack parser checks for resource-address scope boundaries (not only VMID presence).
- Add explicit shared-storage impact classification beyond raw `pvesm status` output.
- Add an optional final verdict line (`SAFE TO REVIEW FURTHER` vs `BLOCKED`) driven by computed blocker conditions.
- Add a small regression test harness (fixture logs) for summary parser logic to prevent future shell/regex regressions.

## Planner Contract Changes

No planner contract change was required in the two planning docs.

Implementation stayed within the existing read-only design and scope guardrails.
