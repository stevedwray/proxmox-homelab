# Wazuh tuning plan

**Status (2026-10-15): executed and merged to `stable` (PR #478); live on `pve`.** The phase text below is the
original plan (intent and gates). What actually happened, including every deviation, is in the table here and in the
per-phase records in [README.md](README.md#phase-records). Results against the targets: README "Results at a glance".

| Phase | Status | Where reality differed from the plan |
|---|---|---|
| 0 baseline, tooling, regression suites | **done** | Added a second tier (live actions on apt-cacher-stack) and a Docker tier (portainer-stack); counts cross-checked against the raw `alerts.json` (0.001% apart) |
| 1a dashboard healthcheck | **done** | Applied by editing the live compose and recreating only the dashboard (a playbook run would recreate all three containers) |
| 1b version skew | **done** | Upgraded to 4.14.8 (the fleet's version), not 4.14.9; backup was the nightly PBS snapshot (operator choice) instead of a manager-volume copy + indexer snapshot |
| 1c retention | **done** | 90 days (operator); plus pruning of the manager's raw logs, which Wazuh never rotates; the ISM plugin's system indices needed 0 replicas (cluster went yellow, fixed) |
| 1d rule 87907 | **done** | 40 exact, anchored level-0 rules generated from `docker_healthchecks.json`; `& < >` cannot be escaped in a pcre2 field, so they match as `.`; the 24 h gate is **pending** |
| 2a FIM ignore lists | **done** | Shared `agent.conf` per group, each block scoped to one agent by name; delivery needed stage-then-`mv` (a root-owned `docker cp` race made `remoted` skip the file) |
| 2b rootcheck 510 | **done** | 3,314 of 3,320 were LXC's own `/dev/.lxc*` files: one anchored level-0 rule; the 6 overlayfs events/day are left alone |
| 2c auth failures on graylog-stack | **done** | Not a graylog fault: MikroTik hAP log lines, 100% from the Greenbone scanner; lowered to L3 for that address and protocol only |
| 2d scanner sshd | **done** | Rules for 5710, 5712 (was L10) and 5760; 5740 has no source address, so it is not scoped |
| 3 vulnerability detector | **done, re-scoped** | Operator scoped the session to Wazuh and agents (no patching). Delivered `<nodiff>` for secrets, rootkit checks enabled fleet-wide, Debian profile, `vuln_triage.py`; syscollector and SCA reviewed and left alone |
| 4 capacity and sizing | **pending** | Needs ~7 days of post-tuning data; the Wazuh dashboard is the instrument |
| 5 coverage and detection testing | **pending, optional** | Known unenrolled: framework, pve-tiny, pentagi-stack |
| 6 steady state | **done, except** alert rules and a scheduled weekly review | Dashboard, exporter and scrape targets live; no provisioned Grafana alert mechanism exists in the repo; the noisiest-rule share is a dashboard stat instead of a scheduled task |

Method (carried over from the Greenbone work, where it found and fixed the scanner OOM
crashes and the 2x scan duplication):

1. **Baseline before touching anything.** The 2026-10-15 survey in README.md is the
   baseline; each phase re-runs the same queries afterwards.
2. **One change at a time, supervised, with a stop condition.** Never batch tuning
   changes: if a number moves we must know which change moved it.
3. **Numeric decision gates written down first** (adopt / do not adopt), like the lean
   config experiment. A change that fails its gate is reverted and recorded, not kept.
4. **Detection must not regress.** Every suppression is paired with a must-fire test
   (Phase 0) that proves the signal we care about still alerts. Tuning is allowed to make
   Wazuh quieter, never blinder.
5. **Config lives in the repo, not only on the host.** Live-only changes are used for
   experiments and are then moved into `deploy-wazuh-stack.yml` / role files before the
   phase closes. A later deploy must reproduce the tuned state.
6. **Read-only tooling first, mutation behind approval.** Survey modes never write. Any
   write goes through `./with-secrets-prod` with a named `TASK_APPROVAL` and a preflight
   summary, one task per approval.
7. **Resource guards.** Sampler running during every experiment; stop conditions below.
8. **Docs, memory and PRs kept current as each phase closes; everything merges to
   `stable` before the plan is called done.** No work left on branches.

Stop conditions for any supervised change: indexer heap above 85% for 5 minutes, free
RAM under 800MB, any `events_dropped` increase, any queue usage above 50%, a must-fire
test failing, an agent leaving `active`. Roll back first, investigate second.

## Phase 0 - baseline and tooling (read-only) - DONE

Goal: repeatable measurements and a regression suite, so every later phase has a
before/after.

1. Promote the three survey scripts (`terraform/lxc/ansible/files/wazuh-tuning/`) into a
   single helper `wazuh_tuning.py` with modes: `health` (containers, heap, disk, queues,
   agent versions), `alerts` (24 h by rule, agent, level, group), `noise <rule>` (breakdown
   of one rule), `agents`, `vulns`, `retention`, `fim <agent>`. Output also written as
   JSON so runs can be diffed.
2. A playbook `wazuh-tuning.yml` like `gvm-scan-tuning.yml`: copies the helper, runs a
   mode, supports the sampler (30 s: heap, RSS, free RAM, queue usage, events/s, disk).
3. Capture a **baseline report** (`docs/wazuh-tuning/artifacts/baseline-*.json`, ignored)
   and record the headline numbers in README.md.
4. Build the **must-fire suite** (small script run on the manager with `wazuh-logtest`
   plus a few live actions on one test agent): sshd failed and successful login, sudo
   to root, a new user, FIM change on a watched path (`/etc/passwd` on a test host), a
   container start and a non-health-check `docker exec`, a vulnerability-state change,
   an agent disconnect. Expected rule ids and levels are listed in the script. It runs
   before and after every change in later phases and must pass 100%.
5. Verify the survey counts against a second source (dashboard or `alerts.json`) once, so
   later numbers are trusted.

Gate: baseline recorded, must-fire suite green on current config.

## Phase 1 - quick wins (each is its own supervised change) - DONE

1a. **Dashboard healthcheck** - accept 401 as healthy (it proves the app answers) in
    `deploy-wazuh-stack.yml`; recreate only the dashboard container.
    Gate: container reports `healthy`; dashboard login still works.

1b. **Version skew** - decide per README decision 3. If upgrading: back up the manager
    volume and indexer snapshot first, upgrade manager, then indexer and dashboard to the
    same tag, verify all 28 agents `active`, pin the agent role to the same version.
    Gate: no agent disconnected, vulnerability detector and FIM still reporting, must-fire
    suite green. This is the highest-risk step of the plan, so it gets its own session
    slot and a stop-and-ask checkpoint after the backup.

1c. **Retention** - create an ISM policy (hot, then delete after N days; N from decision
    1) and attach it to `wazuh-alerts-4.x-*` plus an index template so new indices get it.
    Dry run first: list which existing indices the policy would delete and confirm with
    the operator. Gate: oldest index age equals N after one cycle; free disk non-decreasing.

1d. **Docker health-check noise (rule 87907)** - add a repo-managed `local_rules.xml`
    (delivered into the `wazuh_etc` volume by the playbook, with a validation step using
    `wazuh-analysisd -t` before reload) containing level-0 child rules of 87907 that match
    only health-check exec commands: `valkey-cli ... ping`, `healthcheck.sh`,
    `test -e $STATE_FILE`, and the other health commands found in the survey. Do not
    blanket-disable 87907. Experiment first on `logtest` with real sample events, then
    live, then compare 24 h later.
    Gate: alerts per day drop by at least 85%; the must-fire container tests pass;
    non-health-check `docker exec` still alerts.

## Phase 2 - FIM and rootcheck tuning - DONE

2a. **FIM ignore list**, repo-managed through agent groups' shared `agent.conf` (the
    mechanism already used for segments) rather than per-host ossec.conf edits:
    `/etc/pve/nodes/*/lrm_status` and other pmxcfs status files, our own sampler and
    runner logs under `/opt/greenbone-stack` and `/opt/actions-runner/_diag`, log files
    in general. Review the top 30 paths per agent first; ignore rules are per path,
    never per directory unless the directory is all logs.
    Gate: rule 550 volume down at least 80%; sensitive paths (`/etc`, `/usr/bin`,
    `/root/.ssh`, `/etc/sudoers.d`) still alert in the must-fire suite.
2b. **Rootcheck (rule 510)** - read the actual messages on three agents. Fix the cause
    where it is real (a genuine anomaly) and suppress only the specific known benign
    signature where it is not.
2c. **Auth failures on graylog-stack (rule 2501, 2,754/day)** - find the retrying
    client; this may be a real misconfiguration or an attack, so investigate before
    suppressing anything. Output: a note, a fix or a narrowly scoped rule.
2d. **Scanner-origin sshd events (192.168.70.11)** - narrow rules for 5710/5712/5740
    from the Greenbone scanner address only, level lowered not removed, so other sources
    still alert.
    Gate for phase: total alerts per day under 50k and no single rule above 10%.

## Phase 3 - vulnerability detector, SCA and inventory configuration (Wazuh side only) - DONE

Scope: Wazuh's own configuration and what the agents feed it. Applying host updates, removing packages and
changing pinned libraries are out of scope for this plan (operator, 2026-10-15).

1. Done: read-only analysis of the 3,957 findings against the Debian tracker (`vuln_triage.py`, README).
   Result: 97% are open/unassigned upstream, so the volume is a feed property, not a Wazuh fault.
2. Review the detector configuration on the manager (`<vulnerability-detection>`: enabled, index-status,
   feed update interval, offline vs online feed) and its cost on the indexer; tune only with evidence.
3. Review syscollector on the agents (package/OS inventory interval, hardware, ports, processes) for what the
   detector needs versus what is collected for nothing; check every agent reports a package inventory.
4. Review SCA (policies in use, run interval, result volume, failing checks that are LXC artefacts).
5. Decide how findings are surfaced (Phase 6 dashboard / weekly `vuln_triage.py` report), not hidden.
   Gate: documented settings with their reasons; any change has a before/after and keeps detection intact.

## Phase 4 - capacity and sizing - PENDING

1. With the noise gone, measure for ~7 days from the Wazuh dashboard (`/d/wazuh`; raw numbers via the helper's `health`
   and `retention` modes): indexer heap and RSS, shards, events per second, alert-index growth per day, disk used.
   Baseline for comparison: heap 69% of 4GB at 175 shards, ~0.4GB/day, ~1.3GB free RAM of 8GB.
   2026-10-16: LXC memory raised 8192 -> 12288 MB (`stack.yaml`, applied live with `pct set 40015 -memory 12288`, no restart)
   after a manager restart lost wazuh-apid at ~400MB free. Re-measure free RAM and the indexer heap after a week; the heap itself
   (4GB) and container limits were not changed.
2. Right-size the LXC (RAM, `wazuh_indexer_heap_gb`) and shard count: a one-shard-per-index template for new alert indices
   (a single node does not need 3-4 shards per index; 90-day retention would otherwise reach ~330 shards). Use the
   Proxmox-change-then-set-in-config pattern so Terraform sees no drift (as done for greenbone-stack).
3. Decide with the numbers whether the stack is a pve-tiny candidate (separate plan).
   Gate: documented steady-state numbers and headroom of at least 30% on RAM and heap.

## Phase 5 - coverage and detection testing (optional, operator decides) - PENDING

1. List unenrolled hosts (known: `framework`, `pve-tiny` hypervisor, `pentagi-stack`) and enrol per the existing role
   (`ansible/00-initial-setup/proxmox-wazuh-agent.yml` is the pattern for hypervisors and bare metal). Each enrolment
   needs the MikroTik rule for 1514/1515/55000 from its zone and a group in `agent_conf/`.
2. Per-agent-type test matrix (LXC Docker stack, hypervisor, bare metal): FIM paths, Docker monitoring, SCA results,
   syscollector inventory, rootkit checks. The live suite (`wazuh-mustfire-live.yml`) already takes `live_group`,
   `live_docker` and `live_rootcheck`, so a new host type is an inventory plus its case list.
3. Agent upgrade procedure documented and tested on one host before the fleet (the role now pins the version, so an
   upgrade is a deliberate change of `wazuh_agent_version` with the manager first).
4. Optional: a custom SCA policy that skips the CIS checks that cannot apply inside an LXC (baseline 43%, ~105 failing
   and 22 invalid checks per host).

### Phase 5a - `pve-test` (laptop) and `pve-tiny` (hypervisors) - PLANNED, checks done 2026-10-16

Checked read-only, nothing changed. `pve-test` is a non-production Proxmox 9.2 node (Debian 13, kernel 7.0.14-17-pve,
4 CPU, 16GB RAM with ~11GB free) at `192.168.1.40`, on the default VLAN (`lan`, 192.168.1.0/24). It runs CT 910
(stopped template builder), CT 70010 `cse-kali` (running) and VM 70011 (stopped), no Docker, and has no Wazuh agent
(`/var/ossec` absent, no package).

| Check | Result |
|---|---|
| Manager reachable from `lan` | **yes**: 1514, 1515 and 55000 on 192.168.40.15 are open from both the workstation and `pve-test` itself, so **no MikroTik change is needed** (the same path serves `framework`, 192.168.1.18) |
| Existing pattern | `ansible/00-initial-setup/proxmox-wazuh-agent.yml` enrols the `pve` hypervisor with the `wazuh_agent` role (hosts: `pve.gibbsgreatly.xyz`); `pve-test.gibbsgreatly.xyz` is already in `ansible/inventory/production.yml` and `dev.yml` |
| Role fit | `wazuh_agent` is a plain apt install on Debian 13, so it fits as is (version pinned 4.14.8, `debian13` config profile, `/etc/pve/priv` already in `<nodiff>`) |
| Not production | not in `terraform/PRODUCTION_NODES`, so it does **not** go through `with-secrets-prod`; the secrets wrapper to use is still to be settled (see decision 1) |

**`pve-tiny` (production, 192.168.1.250, surveyed read-only under `wazuh-survey-pve-tiny`):** Proxmox 9.2.21 on Debian 13
(same kernel as `pve-test`), 16 threads, 32GB RAM with ~22GB available, no Docker. No Wazuh agent (no package, no
`/var/ossec`). Ports 1514, 1515 and 55000 on the manager are open from the node, so no firewall change. It hosts 8 LXCs
(technitium-tiny, cse-panel, opensearch, cse-controller, mcp-utility, secpipe, ai-services, cse-code-eval) plus a stopped
template builder; the LXC guests are separate agents and are not covered by enrolling the hypervisor. Differences from
`pve-test`: it is production (uses `./with-secrets-prod-tiny` with a named `TASK_APPROVAL`; it is not yet in
`ansible/inventory/`), and it is the planned target for moving Wazuh/Graylog, so keep the hypervisor agent light. Enrol
`pve-test` first as the canary, then `pve-tiny` with the same playbook and `proxmox_host` group.

Decisions (operator, 2026-10-16): `pve-test` first as the canary, then `pve-tiny`.

1. **Secrets wrapper: settled.** `secrets/manifest.json` already has a `pve-test` profile (role `deploy-dev`, includes
   `services/wazuh`). `PVE_ENV=pve-test ./with-secrets` loads `WAZUH_AGENT_AUTHD_PASSWORD`, `WAZUH_API_PASSWORD` and
   `LAB_IP_WAZUH` and targets node `pve-test` (verified: all three set). Not production, so no `TASK_APPROVAL`; the
   operator's "proceed" in chat still gates the run. `pve-tiny` uses `./with-secrets-prod-tiny` with a named approval.
2. **Group: keep `default` for now.** `pve` already lives in `default` with an agent-name-scoped ignore, so the
   hypervisors follow that pattern and no new group is created (a new group would also need a manager redeploy of the
   group list in `deploy-wazuh-stack.yml`). Revisit only if measurement shows hypervisor FIM skewing the fleet numbers.
3. **FIM scope: the `pve` playbook's list, measured.** `/etc/pve`, `/etc/network`, `/etc/ssh/sshd_config`, `/root/.ssh`,
   `/etc/sudoers.d`. The pmxcfs `lrm_status` flood that was 57% of FIM alerts on `pve` exists on every node, so
   `agent_conf/default.xml` now ignores `/etc/pve/nodes/pve-test/lrm_status` for the agent `pve-test.gibbsgreatly.xyz`
   (add `pve-tiny` the same way), delivered before the agent enrols.

Found on enrol (2026-10-16): `pve-test` has journald only (no rsyslog), so the role's fixed `/var/log/syslog` and
`/var/log/auth.log` localfiles logged error 1103 on every start and SSH/sudo events were invisible. The role now has
`wazuh_agent_log_source` (`auto` | `files` | `journald`, default `auto` = journald when `/var/log/auth.log` is missing);
the files layout renders byte-identical to before, pinned by `test_agent_conf.py`, so the LXC fleet is unaffected.

Steps (each its own approval or go-ahead, in order):

1. Done in the repo (branch `work/wazuh-phase5-pve-test`): `proxmox-wazuh-agent.yml` takes `wazuh_agent_target`
   (default `pve.gibbsgreatly.xyz`); `default.xml` ignore for `pve-test`; `test_agent_conf.py` updated; tests and
   `--syntax-check` pass.
2. Deliver the shared config (production manager, mutating): `deploy-wazuh-stack.yml --tags wazuh_agent_conf -e
   '{"wazuh_agent_conf_groups":["default"]}'` through `./with-secrets-prod` with `TASK_APPROVAL=wazuh-agent-conf-pve-test`
   (the manager is on `pve`). Out of scope: any other group, the manager containers, rules.
3. Enrol (mutating, one non-production host): `PVE_ENV=pve-test ./with-secrets ansible-playbook -i
   ansible/inventory/production.yml ansible/00-initial-setup/proxmox-wazuh-agent.yml -e
   wazuh_agent_target=pve-test.gibbsgreatly.xyz`. Out of scope: the node's LXCs/VM, Proxmox config, MikroTik, other hosts.
4. Verify: agent `active`, version 4.14.8, `agent.conf` merged (`verify-agent-conf`), syscollector and SCA
   (`cis_debian13`) results present, vulnerability detection populated, no `lrm_status` FIM alerts.
5. Measure one hour then 24 h with `wazuh_tuning.py agents/alerts/noise`. Gates: agent stays active, no rule above 10%
   of fleet alerts, no `events_dropped` increase, manager free RAM stays above 800MB. Then repeat for `pve-tiny`
   (repo side done: inventory group `proxmox_tiny`, deliberately outside `proxmox`/`proxmox_production` so the storage and
   terraform playbooks cannot target it, and the `lrm_status` ignore in `default.xml`; still to run: shared-config delivery
   and enrol via `./with-secrets-prod-tiny`, each with its own preflight and approval).
6. Record results in README "Results at a glance" and open items; `docs/wazuh-stack/README.md` enrolled count 27 -> 28.

Roll back: stop and disable `wazuh-agent`, `apt remove --purge wazuh-agent` on `pve-test`, and delete the agent on the
manager (`DELETE /agents`). `framework` follows the same shape after this proves out (Ubuntu, so the `debian13`
config profile and `cis_debian13` SCA policy need checking against its OS).

### Upgrade to 4.14.9 (decided 2026-10-16) - DONE 2026-10-16: manager stack and all 32 agents

Why: `framework` was upgraded to 4.14.9 by hand while the manager was 4.14.8 (an agent must not be newer than its manager), and
4.14.9 (released 2026-10-14) is a maintenance release with security hardening (authd/cluster idle connections, API access log
escaping, remoted bounds) and no listed breaking changes, indexer changes or manual upgrade steps. The `4.14.9` tags exist on
Docker Hub for the manager, indexer and dashboard. The repo now pins `wazuh_image_tag` and `wazuh_agent_version` to 4.14.9
(a test keeps them equal) and the agent role holds the package after install, lifting the hold only for a version change.

Manager stack done (2026-10-16 14:58 NZDT, task `wazuh-upgrade-4149`): compose tags edited on the host (backup
`/opt/wazuh-stack/docker-compose.yml.bak-4149`), `docker compose pull`, one `docker compose up -d`; about 30 s from start to all
10 daemons running. Before/after: the four suites pass, cluster green, `events_dropped` 0, 32 agents active, vulnerability
documents 10,513 before and after, ISM 49/49, heap 15% after the restart, 5.3GB RAM available, no `wazuh-apid` failure. 30 agents are
still on 4.14.8 (supported: the manager is newer); `framework` and the manager's own agent are on 4.14.9. Not done: the
agent rollout (step 4), the Authentik login check on the dashboard (browser), and the `docker image prune` for the 4.14.8
images (docker volume 75% with both generations; the prune reclaims about 4.4GB).

Agent rollout done (2026-10-16, play `playbooks/wazuh-agent-upgrade.yml`, PRs #499/#500): upgrade-only (never touches
`ossec.conf`, group or keys), explicit agent list, one host at a time, stops on failure, refuses to pass the manager version, holds
the package afterwards. Order: canary `apt-cacher-stack`; `pve-test` + ci-runner, netbox, harbor; app/game/media/edge (10);
management/observability (6); core DNS/ingress/SSO + the Wazuh LXC (5); `pve`, then `pve-tiny`; `greenbone-stack`; finally `tpot`,
which needs `upgrade_host_overrides` (user steve through the ssh alias `tpot`, with sudo). After every batch: agents active at 4.14.9,
`events_dropped` 0, cluster green. Final state: 32/32 agents on 4.14.9, manager 4.14.9, suites pass, cluster green, heap 37%,
4.8GB RAM available. Left: Authentik login check on the dashboard (browser), `docker image prune` of the 4.14.8 images, host
`.bak` files. The LXC agents do not self-upgrade (the unattended-upgrades allow-list is Debian security only), so a future version
change is a deliberate bump of `wazuh_image_tag` + `wazuh_agent_version`, the manager first, then this play.

Procedure (Phase 1b method; each step its own approval; stop and roll back on any stop condition):
1. Before: suites (`mustfire`, `suppression`, `scanner`, `hap`), `health` and `agents` baselines; cluster green; PBS backup is the
   nightly snapshot (confirm it is recent).
2. Manager stack (production, mutating): on the host edit the image tags in the live `docker-compose.yml` (backup
   `docker-compose.yml.bak-4149`), `docker compose pull`, one `docker compose up -d`. About 1-2 minutes of downtime; volumes kept.
   Watch free RAM (12GB LXC now) and `wazuh-control status` (expect 10 daemons) during the start.
3. After: the same suites, `agents` (all active, nobody newer than the manager), `events_dropped` 0, vulnerability finding count
   unchanged (about 3,957), ISM 49/49, cluster green, dashboard healthy, Authentik login to the dashboard.
4. Agents: canary first (one LXC agent, then `pve-test`), then the fleet by zone group, via each stack's normal agent role run
   (the role installs `wazuh-agent=4.14.9-1` and re-holds it). `framework` is already on 4.14.9.
5. Follow-up: `docker image prune` for the 4.14.8 images (about 4.4GB) once stable.

Rollback: tags back to 4.14.8 in the compose file and `up -d`, or PBS restore. Agents on 4.14.9 against a 4.14.8 manager are
unsupported, so do not start step 4 until step 3 passes.

### Gate read, 2026-10-17 (interim; the clean 24 h read is after ~17:00 NZDT, 24 h past the last change)

A rolling 24 h read at 05:30 was not a clean window (the rule deploys, the manager outage and restart, the 4.14.9 upgrade, agent
restarts, three new agents' first scans and a lot of automation all fell inside it), so only an 11 h interim (since ~18:30 the day
before) is recorded: 9,886 alerts (about 21,600 a day, gate under 50,000 passes), FIM rule 550 240, cluster green, 0 dropped, 32/32
agents on 4.14.9, suites pass. The "no rule over 10%" gate failed on two self-inflicted groups, now fixed in the repo (deploy pending the
clean read so the baseline stays measurable): rule 87907 at 37% was entirely six metrics-collector commands that run once a minute
(the Wazuh manager's two `.state` reads and `agent_control -l`, and three `redis-cli` queries in Greenbone's Redis; added to the
suppression list), and the sshd/PAM login rules were mostly the Greenbone credentialed scan (`gvm-scan` from 192.168.70.11, publickey):
its successful sshd logins (5715) are now rule 100203 at level 0, limited to that user and that address, while the PAM session pair
(5501/5502) has no source address and is left alone. The gate's intent is "no single noise rule", so login audit trails that remain are
accepted. `framework` had no rule 510 in the last 12 h; `pve-test` and `pve-tiny` had 4 alerts each in 11 h.

### Cluster yellow on 2026-10-16 (ISM history replica)

Status check found one unassigned shard: the replica of `.opendistro-ism-managed-index-history-2026.10.15-000002`, created
by ISM's daily rollover with 1 replica. The earlier fix (0 replicas on existing `.opendistro-*` indices plus a template) did not
cover rollovers because the plugin creates the index with an explicit count from the cluster setting
`plugins.index_state_management.history.number_of_replicas` (default 1). The deploy play now sets it to 0
(`--tags wazuh_retention`, which also re-applies 0 replicas to the existing index). Check after the next rollover that the
cluster stays green.

### Phase 5a result: `pve-test`, `pve-tiny` and `framework` enrolled (2026-10-16)

All three agents are 4.14.8 in the `default` group, connected, secrets protected by `nodiff`. The role reads journald
when the host has no rsyslog (the two Proxmox nodes); `framework` (Ubuntu 26.04.1, rsyslog) reads the log files.
`framework` was enrolled with `-e '{"wazuh_agent_fim_paths":["/root/.ssh","/home/steve/.ssh"]}'` (the play's default
paths are hypervisor paths) through `./with-secrets-prod-framework`.

Ubuntu 26.04 findings:
- **SCA:** the agent ships only `cis_ubuntu22-04`, which skips itself on version check, so `framework` has no CIS score.
  A custom 26.04 policy belongs to the optional SCA item below.
- **Rootcheck false positives:** 48 L7 "Trojaned version of file" alerts per scan (every 12 h), on `/bin` and `/usr/bin`
  tools. Ubuntu 26.04 uses Rust uutils coreutils whose binaries contain strings the generic trojan signatures look for.
  Rules 100212 (`<hostname>`) and 100213 (`<location>`), both level 0, are limited to agent `framework.gibbsgreatly.xyz` (the manager
  shows an agent's events as `(<agent name>) any->rootcheck`; both options take OS_Match syntax, `^(name) `, where a backslash is
  literal. The first two attempts used regex escapes and never matched, the safe failure; both candidates ship until the live
  scan shows which field carries the prefix, then the other is removed), rule 510 parent, Generic signatures and a
  single `/bin` or `/usr/bin` file name; named rootkit signatures, other paths and every other host keep 510 at L7, and
  FIM still watches `/bin` and `/usr/bin`. logtest cannot produce rootcheck events, so the scoping is proven by unit
  tests on the pattern and the generated XML, then live: trigger a rootcheck scan on `framework` and on one LXC agent
  after the deploy (`PUT /rootcheck`), expect no new trojan alerts for `framework` and an unchanged picture elsewhere.
  Result (2026-10-16, deployed by in-place reload): a rootcheck scan on `framework` stored 20 Trojaned detections in the
  manager and raised 0 alerts; `apt-cacher-stack` scanned clean and unchanged. One of the two candidates matches, the live test
  cannot say which (level-0 matches are not logged), so both stay; prune one by deploying `hostname`-only, scanning, and
  swapping if alerts return. The earlier deploy with a container restart lost `wazuh-apid` to a SIGKILL during start (8GB LXC with
  the indexer at ~4.9GB, about 400MB free at the low point) and the manager was down ~11 minutes until a second restart; rule
  deploys now use `-e wazuh_rules_apply=reload` (no restart). Phase 4 sizing should treat the LXC RAM as the first item.
- **FIM:** one benign `fopen` error on a dangling `pollinate.service` symlink; add an agent-scoped ignore only if it repeats.
- **Vulnerability detection:** not yet checked for Ubuntu 26.04 (the feed may not cover it).

## Phase 6 - steady state - DONE (alert rules and weekly review aside)

1. Done: Grafana via the Greenbone pattern (role `wazuh_metrics`, textfile exporter, dashboard `wazuh.json`, scrape
   targets, cAdvisor on the host). The host also appears in Node Detail, Docker Containers and Lab Overview.
2. Open: alert rules. The repo has no provisioned Grafana alert mechanism (only a manual coredns example) and delivery
   (Discord) is a separate plan.
3. Weekly noise review: the "noisiest rule share" stat on the dashboard covers it; `wazuh_tuning.py alerts` is the
   detail view. Not scheduled as a task.
4. Done: docs pass (this workspace and `docs/wazuh-stack/README.md`) and memory.

## Order, risk and sessions

| Phase | Risk | Status | Notes |
|---|---|---|---|
| 0 | none (read-only) | done | produced the baseline and the regression suites |
| 1a, 1c, 1d | low | done | 1d gave the biggest win; each was its own approval |
| 1b | highest | done | own slot; PBS snapshot as the safety net |
| 2 | low-medium | done | per-path review with the operator; one delivery race found and fixed |
| 3 | low | done | re-scoped to Wazuh-side configuration |
| 4 | medium | pending | a resize needs a maintenance moment |
| 5 | low | pending, optional | |
| 6 | low | done | alert rules aside |

Every production change followed the same loop: preflight, operator "proceed", a named `TASK_APPROVAL`, the change, the
regression suites, the after-action summary. The manager was restarted about six times on 2026-10-15 for rule changes:
batch `local_rules.xml` changes in future.

## Next session

1. Take the 24 h measurements (runbook, "Re-measure the 24 h gates") and write the "after" values into the README.
2. Decide on Phase 4 once ~7 days of data exist; Phase 5 and the small follow-ups are listed in README "Open items".

## Done when

All phases accepted or explicitly dropped by the operator; every change is in the repo and reproduced by a clean
deploy; README has "after" values; docs and memory are current; everything merged to `stable`.

State: everything above is merged (#478) and reproduced by the repo, docs and memory are current. Remaining before the plan
can be closed: the 24 h "after" values, then Phase 4, and a decision on Phase 5.
