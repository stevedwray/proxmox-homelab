# Supervising and tuning GVM scans

How to run, watch and change the Greenbone scans safely. Tooling:
`terraform/lxc/ansible/files/greenbone-scan-setup/gvm_tuning.py` (modes listed in
its docstring) driven by `terraform/lxc/ansible/playbooks/gvm-scan-tuning.yml`.

## Setup

- Work from a worktree of the branch you want shipped, never the shared checkout
  (see the memory note on deploys picking up the wrong branch).
- The greenbone inventory is an ignored file in the main checkout:
  `~/git/proxmox-homelab/terraform/lxc/environments/pve/greenbone-stack/inventory.yml`.
- Production approval applies: preflight summary, operator "proceed", then
  `export TASK_APPROVAL=<task>`.

```bash
export TASK_APPROVAL=gvm-scan-tuning ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles
INV=~/git/proxmox-homelab/terraform/lxc/environments/pve/greenbone-stack/inventory.yml
T() { ./with-secrets-prod ansible-playbook -i $INV -u root \
      terraform/lxc/ansible/playbooks/gvm-scan-tuning.yml </dev/null "$@"; }

T -e tune_mode=report                      # every credentialed task, per-host login/LSC tally
T -e tune_mode=lancheck                    # LAN tasks: excludes, max_hosts, schedule
T -e tune_mode=listsched                   # what has a schedule
T -e tune_mode=start -e '{"tune_task":"LAN scan: lan full-vuln"}'
T -e tune_mode=stop  -e '{"tune_task":"LAN scan: lan full-vuln"}'
T -e tune_mode=vulns -e '{"tune_task":"LAN scan: lan full-vuln"}'   # non-Log findings by host
T -e tune_mode=sample_start                # 30 s memory/Redis sampler -> mem.log
T -e tune_mode=runhosts -e '{"tune_zones":"mgmt_seg 192.168.20.16:skip8200"}'
```

Use JSON for any `-e` value containing spaces: `-e key=value` splits on spaces.

## A supervised run

1. **Idle check.** No `openvas: openvas: testing` processes and no `gvm-tools-run`
   container, or the numbers are not solo numbers.
2. **Sampler on** (`sample_start`), then **start** the task.
3. **Watch** `mem.log`: container memory, Redis size, load, and the per-host
   knowledge bases (`dbN=keys`). Healthy: memory 2.5-4 GB, Redis 350-700 MB.
4. **Runaway signature:** Redis jumps from hundreds of MB to GBs in minutes while key
   counts stay small (tens of thousands). Redis is capped at 6 GB (`--maxmemory`),
   so the scan degrades instead of crashing, but results for hosts scanned while it is
   pinned are incomplete (missing LSC consolidation). Find the host: list
   `openvas: openvas: testing <ip>` processes, sample the big databases' key families
   and `MEMORY USAGE` of random keys. The first one found was a web UI that returns
   the same ~1 MB page with HTTP 200 for any path under `/ui/`.
5. **Fix pattern:** scan that host as its own task without the port
   (`SPLIT_HOSTS` in setup_credentials.py) and keep it out of the unmanaged
   full-vuln scan (the managed-host list does this).
6. **Results:** `report` shows per host `failed/ok/lsc/total`. `ok>=1` and `lsc>=1`
   means it authenticated and the local checks ran. A `failed` beside an `ok` is
   normal for MikroTik (several parallel SSH sessions, one refused).

## Applying a change

Deploy from the worktree with only the tags you need. A full playbook run
recreates the scanner containers and interrupts running scans.

| Change | Tags |
|---|---|
| credentialed tasks (`setup_credentials.py`) | `credential-program` (re-attaches ALL credentialed schedules) |
| LAN discovery/full-vuln targets (`setup_scan_program.py`) | `scan-program` |
| schedules (`setup_schedules.py`) | `schedule-program` |
| findings ingest / coverage check | `findings-ingest`, but only through `provision.sh --stack greenbone-stack`: a direct `ansible-playbook` leaves `gvm_findings_ingest_enabled` unset and skips the role |

The setup scripts leave a **running** task alone (they print a WARN), so re-run the
same tags after it ends. Changing a target's hosts, excludes or credential rebuilds
the task and loses its report history.

## Pitfalls we hit

- `get_reports` crashes in this feed; read `get_results` instead. The GMP
  `name~` filter combined with `task_id=` is ignored; tally names locally.
- `mem.log` spans days. Filtering it by time of day matches earlier days; take the
  last N lines instead (30 s per sample, so 120 lines is an hour).
- The host's clock and the logs are UTC; schedules are NZ (`Pacific/Auckland`).
- Killing a runner (`stoprun`) leaves its `TEMP calibrate` task and target; run
  `cleanup` before any credential rebuild or it fails with "Credential is in use".
- Stopping a task in the web UI does not stop a background runner; it moves on to the
  next host.
- A deploy that runs the credential or schedule tags re-attaches every schedule. To
  pause scans, `unschedule_all` after the deploy and note it (see the memory note
  `project_gvm_schedules_paused`).
- A host that goes offline mid-scan does not end the task: the scanner waits out each
  plugin's timeout (about 100 s for the web detections) for thousands of plugins. Check
  `ping` and a port test from the scanner host, then `stop <task>`. (192.168.1.253 did
  this on 2026-10-14.) The schedule `DURATION` hard stop is meant to make this safe
  unattended.
- Wait for a task to be Done before comparing runs: `last_report/scan_start` is only
  filled in after a run completes.

## Measured durations (2026-10-12/14)

| Task | Hosts | Time | Notes |
|---|---|---|---|
| credentialed: apps / build / connector / pentest | 1 each | 32 / 22 / 19 / 44 min | solo |
| credentialed: cse / game / media | 2 each | 25 / 32 / 61 min | |
| credentialed: edge / ai / infra | 2 / 3 / 5 | 55 / 51 / 85 min | |
| credentialed: lan | 10 | 108 min | measured on 2 vCPU / 8 GB, before the resize |
| credentialed: mgmt_seg | 8 (max_hosts 2) | 192 min | peak 3.6 GB, Redis 538 MB |
| credentialed: mgmt_seg (openbao) | 1, no port 8200 | 24 min | Redis 351 MB |
| credentialed: MikroTik | 1 | 71 min | |
| discovery (2026-08-29) | zone | 6 (build) to 41 (lan) min | |
| full-vuln, whole zone (before narrowing) | zone | 21 (build) to 66 (infra) min | |
| full-vuln: lan, whole /24 (old target) | 21 hosts with results | stopped at about 2 h 04 min | stalled on an offline host; peak 4.3 GB, Redis 673 MB, load 48 |
