# gvm-scan-redesign

Reshapes the GVM scan program so each scan has one job, nothing is scanned twice,
and every scan stays inside the night window. Plan: [plan.md](plan.md).

## Status

**2026-10-14: planned, Phase 1 not started.** Decisions below are the operator's.
This follows docs/gvm-coverage-cleanup/ (credentialed scans now work, 14 tasks,
weekly, VLAN-grouped) and uses what its tuning found.

## Why

Found while tuning (2026-10-13/14):

- The 12 `LAN scan: <zone> full-vuln` tasks scan whole VLAN ranges at
  `max_hosts=20`, so they rescan every managed host the credentialed tasks already
  cover. On the five zones compared (build, edge, infra, ai, game) the uncredentialed
  scans found nothing extra on managed hosts. Their only unique findings were on
  other addresses: each VLAN's gateway (`.1`, the MikroTik: weak SSH algorithms,
  DNS cache snooping) and a few unidentified addresses (`.110`-`.112`).
- The per-zone Discovery tasks (find hosts, ports, services; no vulnerability
  tests) exist but are unscheduled. The rollout plan's "daily discovery" half
  was never turned on, so full-vuln is also the only thing that notices new devices.
- The web-app probes in "Web application abuses" (9,594 tests) cached thousands of
  responses in Redis per web UI and were the cause of the mgmt_seg runaway
  (docs/gvm-coverage-cleanup/). That is wasted work on managed hosts, where the
  credentialed scan exists for local package checks.
- Exclusions live in three places (`tier_a_exclude`, `FIXTURE_EXCLUDE`,
  `SPLIT_HOSTS`) and are hand-maintained.

## Decisions (operator, 2026-10-14)

| Question | Decision |
|---|---|
| Lean config (no web-app probing) on managed hosts | **Yes**, after the experiment in Phase 2 shows what it costs |
| Unmanaged-device vulnerability scanning cadence | **Weekly** |
| NetBox auto-push of discovered devices | **Later** (deferred, not in this plan) |
| Grafana metrics for the scan host | **Later** (deferred; follow-up 8 in docs/gvm-coverage-cleanup/README.md) |
| Where Greenbone runs | Stays on pve, scans only in the 22:00-07:00 window (pve-tiny survey: memory `project_pve_tiny_load_shifting`) |

## Target design

| Scan | Targets | Config | Cadence |
|---|---|---|---|
| Credentialed (14 tasks, unchanged) | managed hosts | lean (after Phase 2) | weekly, VLAN slots |
| Discovery (12 tasks, now scheduled) | whole zone | Discovery | weekly |
| Full-vuln (12 tasks, narrowed) | **unmanaged addresses only** (zone CIDR minus managed hosts minus fixtures) | Full and fast | weekly, about 6 hosts at once |

The managed-host list comes from the same inventory that builds the credentialed
targets (`scripts/gvm_fleet_targets_generate.py`), so there are no hand lists.

## Out of scope

NetBox push, Grafana metrics, Discord alerting, moving anything to pve-tiny, the
workstation (192.168.1.104) sshd decision.
