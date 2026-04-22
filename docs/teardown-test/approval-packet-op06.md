# OP-06 Destructive Approval Packet

Date: 2026-04-22
Status: Pending explicit operator approval
Scope: Human go/no-go gate for destroy batch only

This packet does not run destroy, apply, publish, or reconcile apply commands.
It requests explicit approval for OP-07 through OP-16 only.

## Guardrails And Session State

| Item | Value | Result |
|---|---|---|
| Branch | `docs/teardown-test-execution-variables` | pass |
| Commit | `c633423d30d9b7b93f008c85db691b9e3b5fbbf9` | pass |
| Working tree clean confirmation | `git status --short --branch` returned `## docs/teardown-test-execution-variables` with no tracked changes | pass |
| Target guard command | `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` | pass |
| Target guard output | `pve-test` | pass |
| Scope contract | Destroy touches only approved stack VMIDs from `docs/teardown-test/inventory.md` | required |

Execution constraints for destroy window:
1. Re-run target guard immediately before each OP-07 through OP-16 stack destroy.
2. Stop immediately if target guard output is not exactly `pve-test`.
3. Stop immediately if a destroy touches any VMID outside approved inventory scope.
4. Stop immediately on first failure in OP-07 through OP-16.

## OP-05 Evidence Summary (Non-Destructive Preflight)

Validated execution context from OP-05:

| Check | Evidence | Result |
|---|---|---|
| Edge manifest validation | Passed; 6 manifests checked | pass |
| Unit test suite | Passed; 47 tests OK | pass |
| Git whitespace check | `git diff --check` passed | pass |
| Traefik render | Passed; `stack_count: 6`, `legacy_route_count: 0`, `issue_count: 0` | pass |
| CoreDNS render | Passed; `generated_record_count: 6`, `issue_count: 0` | pass |
| Edge reconciler dry-run | Passed; `terraform_state_mutation: false`, Authentik `write_count: 0`, `action_counts.noop: 7` | pass |
| Tracked working tree | Clean after verification | pass |

## Generated Artifact Cleanup Caveat (OP-05)

Observed caveat:
- The ignored artifact cleanup command (`rm -rf terraform/lxc/.generated/...`) was
  not executed in the earlier planning/advice session because of safety posture.

OP-06 handling decision:
- Record this as a controlled caveat, not as a contradiction with OP-05 outcomes,
  because all OP-05 verification checks passed and tracked tree was clean.
- Add an execution-window prerequisite: re-run OP-05 preflight in the live
  session with cleanup limited to ignored generated outputs under
  `terraform/lxc/.generated/traefik` and `terraform/lxc/.generated/coredns`
  before any OP-07 destroy command.

## Approved Destroy Scope And Order (From Inventory)

Source of truth: `docs/teardown-test/inventory.md`.

Approved OP-07 through OP-16 destroy order:
1. `netbox-stack` (VMID 143)
2. `monitoring-stack` (VMID 154)
3. `authentik-stack` (VMID 150)
4. `step-ca-stack` (VMID 152)
5. `proxy-stack` (VMID 153)
6. `dns-stack` (VMID 151)
7. `ci-runner-01` (VMID 141)
8. `harbor-stack` (VMID 121)
9. `apt-cacher-stack` (VMID 142)
10. `portainer-stack` (VMID 120)

No additional stacks, edge activation actions, or rebuild actions are in scope
for this approval.

## Backup And Data-Loss Policy Summary (From OP-03)

Source of truth: `docs/teardown-test/backup-plan.md`.

Loss not accepted (must preserve with required evidence):
- `step-ca` authority material
- `authentik` identity state
- `harbor` registry and configuration metadata (Trivy cache may be lossy)
- `netbox` state

Conditional/accepted loss with documented restore/rebuild readiness:
- Monitoring historical metrics/logs (configuration must be preserved)
- Portainer state
- Traefik ACME cache/state if re-issuance path is validated
- CI runner registration state if re-registration procedure is captured
- apt-cacher cache

Global OP-03 stop rule:
- Stop if required backup evidence is missing and accepted data-loss posture is
  not documented for the affected service.

## Required Backup Evidence Paths

Evidence root for live window:
- `docs/teardown-test/evidence/${STAMP}/backups/`

Required per-service directories:
- `docs/teardown-test/evidence/${STAMP}/backups/portainer/`
- `docs/teardown-test/evidence/${STAMP}/backups/harbor/`
- `docs/teardown-test/evidence/${STAMP}/backups/authentik/`
- `docs/teardown-test/evidence/${STAMP}/backups/netbox/`
- `docs/teardown-test/evidence/${STAMP}/backups/monitoring/`
- `docs/teardown-test/evidence/${STAMP}/backups/traefik-certs/`
- `docs/teardown-test/evidence/${STAMP}/backups/step-ca/`
- `docs/teardown-test/evidence/${STAMP}/backups/ci-runner/`
- `docs/teardown-test/evidence/${STAMP}/backups/apt-cacher/`

Destroy start must be blocked until required evidence for non-loss services is
present and validated in the live evidence stamp.

## Rollback/Stop Deadline

Operator must supply a single explicit stop deadline before OP-07 begins.

Approved deadline:
- `2026-04-22 17:30 NZST (+1200)`.

Stop when deadline is reached, regardless of partial completion state.

## Requested Explicit Approval Text

Requested operator response (copy/paste):

"I explicitly approve OP-06 destructive window for OP-07 through OP-16 destroy
only, in the documented order, stopping on first failure and enforcing target
guard `pve-test` before each destroy. This approval does not authorize any
rebuild apply operations, edge publish operations, OP-25, OP-28, OP-29, or any
`reconcile-edge.py --apply` execution."

If approved, the next commandable step is OP-07 only.

## Operator Approval Log

Approval status: APPROVED

Operator-provided approval text:

"I approve the OP-06 bounded batch destroy authorization for OP-07 through
OP-16 on pve-test, stopping on first failure. This approval covers only the
destroy phase for the approved stacks in inventory order. It does not authorize
rebuild apply, edge publish, OP-25, OP-28, OP-29, or reconcile --apply."

Validation of scope:
- Authorizes destroy only for OP-07 through OP-16.
- Requires stop on first failure.
- Explicitly excludes rebuild apply.
- Explicitly excludes edge publish.
- Explicitly excludes OP-25, OP-28, and OP-29.
- Explicitly excludes reconcile apply.
