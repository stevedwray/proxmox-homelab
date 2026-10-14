# gvm-scan-redesign

Reshapes the GVM scan program so each scan has one job, nothing is scanned twice,
and every scan stays inside the night window. Plan: [plan.md](plan.md). How to
run and tune scans: [runbook.md](runbook.md).

## Status

**2026-10-14: Phase 1 applied** (`--tags scan-program,schedule-program`, verified in
GVM; merged to `stable` as #474). 11 of 12 full-vuln tasks now exclude their managed
hosts (plus fixtures), run 6 hosts at a time, and are scheduled; all 12 Discovery
tasks are scheduled weekly (Thursday 22:00 NZ, 30 minutes apart); 38 tasks carry a
schedule (14 credentialed, 12 full-vuln, 12 discovery).

- **Phase 0 baseline done.** `LAN scan: lan full-vuln` (whole /24, old target, started
  2026-10-14 14:51 NZ) ran about 2 h 04 min before I stopped it: 21 hosts produced
  results, 19 had non-Log findings, **none High or Critical**. Unmanaged devices with
  Medium findings: 192.168.1.128 (weak certificate signature, TLS 1.0/1.1),
  .177 (TLS 1.0/1.1), .251 (DNS cache snooping, weak SSH). It used up to 20 hosts at
  once (load 48 on 4 vCPUs, peak 4.3 GB, Redis 673 MB, no OOM), which confirms 20 was
  too many. The last 15 minutes were spent on **192.168.1.253, which had left the
  network mid-scan**: the scanner waited out about 100 s per web-detection plugin and
  would have run for hours. A vanished host can therefore stall a task past the
  night window; the `DURATION` hard stop (Phase 3) is the guard.
- The `lan` full-vuln task now has the narrow excludes (12), `max_hosts=6` and its
  schedule (re-applied after the baseline). All 38 schedules are live.
- Phases 2 (lean config) and 3 (night-window `DURATION`) are not started. Next work
  branches from `stable` (worktree `work/gvm-redesign-phase2`).
- Tooling for supervised runs is in the repo (`gvm_tuning.py`,
  `playbooks/gvm-scan-tuning.yml`).

Decisions below are the operator's.

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
