# OP-06 Destructive Approval Packet

Date: 2026-04-21
Status: Pending operator approval
Scope: Final human gate before any destructive action

This packet does not run destroy/apply commands. It prepares the go/no-go
decision for the destroy phase only.

## Approval Model Decision

Selected model: batch destroy approval for OP-07 through OP-16, stopping on
first failure.

Rationale:
- Selected `pve-test` stacks are not currently in use.
- Downtime and service data loss are acceptable for this rehearsal except where
  `backup-plan.md` explicitly says material must be preserved.
- Execution still requires strict machine/target guardrails.

Bounded authorization rule:
- If this OP-06 packet is approved, authorization covers destroy phase only:
  OP-07 `netbox-stack` through OP-16 `portainer-stack`.
- This approval does not authorize rebuild apply, edge publish, or later live
  validation phases.

## Guardrails (Required)

| Item | Value | Result |
|---|---|---|
| Branch | `docs/teardown-test-execution-variables` | pass |
| Commit | `1568602e7db166a6cffc4b9f1ca6eec08425a415` | pass |
| Target guard command | `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` | pass |
| Target guard output | `pve-test` | pass |
| Working tree clean confirmation | `git status --short --branch` -> `## docs/teardown-test-execution-variables` | pass |
| VMID scope contract | Destroy touches only VMIDs listed in `inventory.md` | required |

Destroy-phase execution constraints:
1. Before every destructive component (OP-07 to OP-16), target guard must
   return exactly `pve-test`.
2. Destroy must only touch VMIDs listed in `docs/teardown-test/inventory.md`.
3. Continue in approved order only if the current stack's approved VMID is
   verified absent.

## OP-05 Evidence Snapshot

Execution mode: non-destructive source and edge preflight.

| Check | Evidence | Result |
|---|---|---|
| Edge manifest validation | `Edge manifest validation passed. Checked 6 manifest(s).` | pass |
| Unit tests | `Ran 35 tests ... OK` | pass |
| Generated artifacts refreshed | Traefik render passed (`stack_count: 6`, `legacy_route_count: 0`, `issue_count: 0`); CoreDNS render passed (`generated_record_count: 6`, `issue_count: 0`) | pass |
| Reconciler dry-run status | `status: passed`, `mode: dry-run`, Authentik reconcile `action_counts: noop: 7`, `stop_condition_count: 0` | pass |

Notes:
- Generated runtime artifacts under `terraform/lxc/.generated/` were refreshed.
- No tracked source file changes were introduced by OP-05 execution.

## Approved Destroy Scope

Source of truth: `docs/teardown-test/inventory.md`.

Approved destroy order:
1. `netbox-stack`
2. `monitoring-stack`
3. `authentik-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `dns-stack`
7. `ci-runner-01`
8. `harbor-stack`
9. `apt-cacher-stack`
10. `portainer-stack`

## Backup/Data-Loss Policy Summary (OP-03)

Source of truth: `docs/teardown-test/backup-plan.md`.

Policy posture:
- No data loss accepted: step-ca authority material, Authentik state, Harbor
  registry/config metadata, NetBox state.
- Conditional/no-impact loss accepted: Monitoring historical metrics/logs,
  Portainer state, Traefik ACME cache/state, CI runner registration state,
  apt-cacher cache (with documented rebuild/restore plans).

Global stop rule from OP-03:
- Stop if required backup evidence is missing and accepted data-loss posture is
  not documented.

## Rollback/Stop Deadline And Stop Conditions

Rollback/stop deadline:
- `2026-04-21 11:30 NZST (+1200)`.

Explicit stop conditions:
- Stop immediately if target guard output is not exactly `pve-test`.
- Stop immediately if a destroy action affects any VMID outside approved
  inventory scope.
- Stop immediately on first destroy failure in OP-07 through OP-16.
- Stop if required preservation material from `backup-plan.md` is missing for a
  service where preservation is explicitly required.

## Requested Approval Text

Approve OP-06 with simplified service-use posture and bounded batch destroy
authorization:

- Service-use posture: the selected `pve-test` stacks are not currently in use.
  Downtime and service data loss are acceptable for this rehearsal except where
  `backup-plan.md` explicitly says material must be preserved.
- Approval model: batch destroy approval for OP-07 through OP-16, stopping on
  first failure. Each destroy still starts with the target guard returning
  exactly `pve-test` and verifies only the approved VMID is absent before
  continuing.
- Rollback/stop deadline: `2026-04-21 11:30 NZST (+1200)`.
- This approval authorizes the destroy phase only: OP-07 `netbox-stack`
  through OP-16 `portainer-stack`. It does not authorize rebuild apply,
  edge publish, or later live validation phases without the next approval.

If approved, the next commandable action is OP-07 and execution may continue
through OP-16 as a bounded batch under the stop conditions above.
