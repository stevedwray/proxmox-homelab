# wazuh-tuning

Test and tune the Wazuh SIEM stack and its agents with the method used for Greenbone
([docs/gvm-scan-redesign/](../gvm-scan-redesign/)): baseline first, one supervised change at a
time, numeric decision gates, tooling and config in the repo, docs and memory kept current.
Scope (operator, 2026-10-15): Wazuh and agent configuration only. Host patching, package removal
and alert delivery (Discord) are out of scope.

## Status (2026-10-15)

**Executed, merged to `stable` (PR #478) and live on `pve`.** Phases 0, 1a-1d, 2a-2d, 3 and 6 are
done and verified; the repo reproduces the live state. What is left is waiting on the clock (the 24 h
gates), Phase 4 (needs a week of data) and the optional Phase 5. See [Open items](#open-items-and-next-steps).

How it is organised: [plan.md](plan.md) (phases, gates, status per phase), [runbook.md](runbook.md)
(how to measure, test and deploy), and this file (baseline, results, one record per phase, lessons).
The fleet is 27 enrolled agents in 11 zone groups plus the manager's own local agent (28 entries in
the API), all on 4.14.8.

## Results at a glance

| Area | Baseline (2026-10-15) | Now | Target / gate |
|---|---|---|---|
| Alerts per day | ~500,000 | **1,246 in the last hour (~30k/day)** at the end of the day; the 24 h figure still contains hours from before 1d | under 50k: **24 h re-measure pending** (after 2026-10-16 ~23:00 NZDT) |
| Share of the noisiest rule | 90% (87907) | 24% in the first 10 min after 1d (mostly the GVM sampler, since stopped); the 24 h stat still carries old hours | no rule over 10%: **pending** |
| FIM rule 550 (24 h) | 29,715 | 0 in the first 3 min window after 2a | down 80%: met in the first window, 24 h to confirm |
| Retention | none | 90-day ISM policy on 47/47 indices + host cron for the manager's raw logs | defined and enforced: **done** |
| Indexer growth | ~0.4GB/day | pending (needs days of data) | under 0.05GB/day: **pending** |
| Dashboard container | unhealthy 8 days | healthy | **done** |
| Manager vs agents | 4.14.7 vs 4.14.8 | all 4.14.8; role pinned to the same version | manager >= every agent: **done** |
| Secrets in FIM alerts | 672 alerts in 14 d carried `/etc/shadow`, PVE keys/tokens, TLS keys, `.env` | `<nodiff>` fleet-wide (past alerts age out at 90 d) | **done** |
| Rootkit file/trojan checks | silently off on every agent | on, verified with a signature file | **done** |
| Grafana | no Wazuh data at all | host + container metrics and a Wazuh dashboard (`/d/wazuh`) | **done** |
| Detection regression | untested | Tier 1 11/11, suppression 48/48, scanner 6/6, hap 4/4, live suites on apt-cacher-stack and (Docker) portainer-stack | all pass before and after each change: **done** |
| Safety | | 28/28 agents active and `events_dropped` 0 after every change | stop conditions never tripped |

## Open items and next steps

1. **Re-measure the 24 h gates after 2026-10-16 ~23:00 NZDT** (commands in the runbook): alerts per day, noisiest
   rule share, FIM 550 volume, indexer growth. Also confirm the new daily alert index carries the retention
   policy and that the new `.opendistro-*` history index has 0 replicas (the cluster should stay green).
2. **Phase 4, capacity and sizing:** after ~7 days of steady state, from the Wazuh dashboard: heap, RSS, shards, disk,
   events per second. Decide LXC RAM / heap and the one-shard-per-index template for new alert indices (175 shards
   today, about 330 at 90 days). The host has ~1.3GB free of 8GB and dipped to 329MB during the 4.14.8 recreate.
3. **Phase 5, coverage (optional):** known unenrolled: `framework`, `pve-tiny` (hypervisor) and `pentagi-stack`;
   the authoritative list is the first output of the phase. Per-agent-type test matrix and an agent upgrade procedure.
   `pve-test` (laptop, 192.168.1.40) and `pve-tiny` (192.168.1.250) are both surveyed: no agent, manager ports open; the plan is
   in plan.md Phase 5a (manager ports already reachable, no firewall change; needs operator decisions).
4. **Small follow-ups:** Grafana alert rules (the repo has no provisioned alert mechanism; delivery to Discord is a
   separate plan); put the manager's `ossec.log`/`api.log` into Graylog (host, indexer and dashboard container logs
   already arrive; the manager writes files, not stdout; an rsyslog `imfile` drop-in was proposed, not yet
   decided); SCA baseline is 43% with ~105 failing checks per host (a baseline, not noise).
5. **Leftover backups on hosts** from the supervised changes: `/opt/wazuh-stack/docker-compose.yml.bak-1a` and
   `.bak-1b`, the monitoring stack's `victoria-metrics/scrape.yml.bak-p6`, and the manager's
   `/var/ossec/etc/agent-conf-backup/`. Safe to delete once nobody needs a rollback.
6. **Known and accepted:** the nextcloud Redis health check carries its password on the command line (it showed up in
   Docker events and indexed alerts; a 4-character prefix of it is in the git history of #478); the operator decided
   not to purge or rotate. 97% of the 3,957 vulnerability findings are Debian-tracker items with no urgency assigned
   yet (patching is out of scope; `vuln_triage.py` is the repeatable report).

## Decisions

| Decision | Outcome (2026-10-15) |
|---|---|
| Retention for alert indices | **90 days** (and the manager's raw logs pruned to the same age); one-shard template as a separate later step |
| Docker health-check events | **dropped silently** (level-0 rules for exact, anchored commands; real `exec`s and container lifecycle still alert) |
| Manager version | **upgrade to 4.14.8** (the fleet's version), pin the agent role to the same; 4.14.9 (released 14 Oct) deliberately not taken |
| Backup for the upgrade | the nightly PBS snapshot (operator confirmed); no extra backup |
| Scanner 192.168.70.11 | lowered to level 3 for **5710, 5712, 5760** (and the router's `login failure` lines), that address only; 5740 has no source address, so it is not scoped |
| Rootcheck 87915/87916 volume mount events | left alone: 238/day each, container-lifecycle audit records |
| GVM sampler | stopped (it tripped FIM and produced leftover 87907 noise) |
| Agent coverage (Phase 5) | optional, not started |
| Patching / package removal / pip pins | out of scope for this plan |
| Purging already-stored FIM diffs | not done (operator: fine while the secrets are not in git) |

## Baseline (read-only survey, 2026-10-15)

All numbers are from the live stack and are the "before" values every later change is
compared against.

| Area | Measured |
|---|---|
| Host | wazuh-stack LXC 40015 on pve, 4 cores, 8GB RAM, 2GB swap; load average 3.3; RAM 6.4GB used, 1.7GB available; no OOM kills |
| Containers (8 days up) | indexer 4.9GB RSS, JVM heap 69% of 4GB; manager 1.1GB; dashboard 0.2GB |
| Disk | docker volume 12G of 20G (58%); indexer volume 8.5G of 50G |
| Agents | 28, all `active`; 27 on 4.14.8, 1 on 4.14.7; **manager is 4.14.7**, so 27 agents are newer than their manager (unsupported combination) |
| Manager pipeline | 12.2M events received, 0 dropped, 3.77M alerts written; all queues at 0% |
| Alert volume | **about 500,000 alerts per day, about 410-470MB per day** of indexer storage |
| Retention | **no ISM policy**: daily alert indices are never deleted (15 days kept so far, 175 shards in a single-node cluster) |
| Dashboard | container `unhealthy` for 8 days (69,187 failed checks) |
| Vulnerability detector | 3,957 open findings, 148 per agent; vim packages are 3,000 of them |

### Where the noise is (24 h, 500,346 alerts)

| Share | Rule | Cause |
|---|---|---|
| **90.4% (452,193)** | 87907 "Docker: Command launched in container" | Docker health checks being logged as security events: netbox-redis and netbox-redis-cache `valkey-cli ping` (81k each per day, about one per second), cadvisor, docs-rag-pgvector, gluetun, greenbone pg-gvm |
| 5.9% (29,618) | 550 FIM "Integrity checksum changed" | `/etc/pve/nodes/pve/lrm_status` alone is 17,275 (a pmxcfs status file that changes every few seconds); `/opt/greenbone-stack/mem.log` and `tuning.log` (our own sampler and runner) another 2,877; `/opt/actions-runner/_diag` logs; routine package updates (curl, ld.so.cache) |
| 0.5% | 2501 syslog auth failure | all 2,754 on `graylog-stack`, no source IP: something retries a bad login there |
| 0.5% | 510 rootcheck | 2,408 per day from 26 agents, the same anomaly repeating every scan |
| 0.4% | 5710 sshd non-existent user | all 215 from 192.168.70.11, the Greenbone scanner itself (expected, but it hides real attempts) |

The 87907 rule alone means that fixing one rule removes about 90% of alert volume,
storage growth and indexing load. The real security signal (logins, sudo, FIM on
sensitive paths, vulnerability changes) is in the remaining 10% and is currently hard to
see.

### Health findings that are not noise

1. **Dashboard healthcheck is wrong.** It curls `/api/status` and expects 200 or 302, but
   the OIDC-protected dashboard answers 401, so Docker marks it unhealthy forever. The
   dashboard itself works. It also blocks any "wait until healthy" logic.
2. **Version skew.** Manager 4.14.7, 27 agents 4.14.8. Wazuh requires the manager to be
   at least as new as the agents. The deploy playbook pins 4.14.7 while the agent role
   installs the latest.
3. **No retention.** Indices grow about 0.4GB per day with no deletion. 42GB free is
   about 100 days at today's volume, but the alert stream is currently inflated 10x.
4. **Heap at 69% of 4GB** with 175 shards on one node. Fine today, no headroom for
   tuning mistakes or growth.
5. **Our own monitoring tools trip FIM.** The Greenbone sampler (`mem.log`) is still
   running after tuning ended and should be stopped (GVM housekeeping, not Wazuh).

## Phase records

One section per phase, in plan order, each with what changed, how it was verified, and the lessons.
These are the original work records and keep their detail.

### Phase 0 done: tooling, baseline and regression suites (2026-10-15)

- The new helper reproduces the survey: 500,321 alerts/24 h, 90.4% rule 87907, 47 alert
  indices (10.2GB), 175 shards, no ISM policy, 3,957 findings, 28 agents active.
- **Second source:** the manager's raw archive for 2026-10-13 has 512,796 alerts against
  512,802 in the index (0.001% apart), so index counts can be trusted. 87907 was 87.8% of
  that day (450,465).
- **New finding:** the manager keeps `alerts.json` and `alerts.log` uncompressed for the
  current day (0.8GB + 1.6GB on 14 Oct) plus about 330MB/day gzipped, all on the same
  20GB docker volume (58% used). Cutting alert volume 10x also fixes this; manager-side
  log rotation is a retention item for 1c.
- Docker-listener alerts have a null `full_log`; the event lives in `data.docker.*`, so
  the must-fire docker cases rebuild the event from those fields.
- **Must-fire Tier 1 (logtest + ruleset) is green on the current config, 11/11** (2026-10-15). Calibration: a first-time sudoer fires 5403 (L4), later ones 5402 (L3); the suite accepts both.
- **Must-fire Tier 2 (real agent events) is green 6/6 on apt-cacher-stack**: new user 5902,
  user deleted 5903 (L3, not 5905), sshd non-existent user 5710, FIM add/modify/delete
  554/550/553. **Docker host test: portainer-stack, 8/8** (87903 start, 87907 non-health-check exec, plus
  87901 created, 87902 destroyed L5, 87924 signal L7 observed). Run with `-e live_group=portainer_stack
  -e live_docker=true -e live_docker_image=harbor.lab.gibbsgreatly.xyz/dockerhub/tecnativa/docker-socket-proxy:latest`
  (image already local, so no pull; the host has only 512MB RAM). 1d must keep all of these alerting.
- Live-action test host for the non-docker cases: `apt-cacher-stack` (no Docker). The
  Docker cases need a Docker-running agent; to be chosen before Tier 2 (operator wants the
  suite extensible to a Docker host).


### Phase 1a done (2026-10-15)

Dashboard healthcheck now accepts 401 (`deploy-wazuh-stack.yml`). Applied live without a
stack redeploy: the same two lines were written into `/opt/wazuh-stack/docker-compose.yml`
(backup `docker-compose.yml.bak-1a` left beside it) and `docker compose up -d --no-deps
wazuh.dashboard` recreated only the dashboard. Result: dashboard `healthy`; manager and indexer
not restarted; must-fire green; `events_dropped` 0, queues 0. The playbook-rendered compose
file now matches the live one, so a later full deploy is a no-op for this line. (A full deploy
still recreates all three containers whenever the compose file changes, hence the targeted path.)

### Phase 1b done (2026-10-15)

Manager, indexer and dashboard upgraded 4.14.7 -> 4.14.8 (matches the 27 agents; the manager's own
agent 000 is now 4.14.8 too, so all 28 are 4.14.8). Backup was the nightly PBS snapshot (operator
confirmed). Method: image tags edited in the live `docker-compose.yml` (backup
`docker-compose.yml.bak-1b`), `docker compose pull`, one `docker compose up -d` (all three recreated,
volumes kept, about 1 minute of downtime). Verified: 28/28 agents active, `events_dropped` 0,
vulnerability findings unchanged (3,957), ISM 47/47 managed, suppression 48/48, Tier 1 11/11, dashboard
healthy. The agent role is pinned to the same version (`wazuh_agent_version`), tested equal.
Rollback would have been: tag back to 4.14.7 in the compose file and `up -d`, or PBS restore.
Caveat noticed: docker volume went from 57% to 73% (both image generations are on disk);
`docker image prune` for the old 4.14.7 images is a follow-up (reclaims about 4.4GB).

**Open from 1c:** the cluster is `yellow` since the ISM plugin created three system indices
(`.opendistro-ism-config`, `.opendistro-ism-managed-index-history-*`, `.opendistro-job-scheduler-lock`)
with a replica a single node cannot place. Fix: set replicas to 0 on them and add a template for
`.opendistro-*`; the alert indices themselves are fine.

### Phase 1c done (2026-10-15)

ISM policy `wazuh-alerts-retention` (hot, then delete at 90 days) exists, is attached to all 47
existing alert indices (its `ism_template` attaches it to new daily indices automatically), and a host
cron (`/etc/cron.d/wazuh-log-retention`, 03:30 daily) prunes the manager's raw alert/archive logs to the
same 90 days. Delivered by `deploy-wazuh-stack.yml --tags wazuh_retention`; a second run changed nothing.
Nothing was deleted (oldest index is from 2026-08-29, so the first deletions fall on 2026-11-27).
**Gate follow-up:** tomorrow's new daily index must show the policy attached (`retention` mode,
`ism_managed_alert_indices` = indices). The one-shard index template is a separate follow-up step.

### Phase 1d done (applied live 2026-10-15; the 24 h gate is re-measured later)

- 75 distinct commands sit behind rule 87907 (452,146 events/24 h). 40 are container
  health checks (listed in `files/wazuh-stack/docker_healthchecks.json`); each gets a level-0
  child rule (ids 100101+) matching the **whole** Action string, anchored `^exec_start: <cmd>\z`,
  so an exec that merely contains a health-check string still alerts. The rest keep alerting:
  Greenbone's own `redis-cli info/type/config get` (about 11k/day, our sampler and exporter;
  goes away when the sampler stops) and one-off operator commands.
- `local_rules.xml` is generated (`gen_local_rules.py`), delivered into the `wazuh_etc` volume
  by `deploy-wazuh-stack.yml` (tag `wazuh_local_rules`): backup, `docker cp`, `wazuh-analysisd -t`,
  restart only on success, restore on failure.
- Suppression test (`must_fire.py suppression`, 48 checks): before = 40 health checks FAIL
  (still 87907) and 8 look-alikes/attacks PASS; after = all 48 must pass.
- **Security finding:** the nextcloud-stack-redis healthcheck passes its Redis password on the
  command line (`redis-cli -a <pw> ping`), so it is visible in `ps`, in Docker events and in about
  8.6k indexed alerts per day. The rule matches `\S+` so the repo never holds it. Recommended
  follow-up (not in this plan's scope): switch that healthcheck to `REDISCLI_AUTH` and rotate the
  password; the old alerts age out under the retention policy (1c).

#### 1d result so far

- Applied with `deploy-wazuh-stack.yml --tags wazuh_local_rules` (no container recreation); the
  manager restarted twice (second time after a fix: Wazuh does not unescape `& < >` inside a
  pcre2 field, so those characters match as `.`). Agents: 28 active after each restart,
  `events_dropped` 0, no stop condition.
- Suppression suite 48/48; Tier 1 11/11; Tier 2 6/6 (apt-cacher-stack) and 8/8 (portainer-stack,
  Docker) after the change, so a real non-health-check `exec` and container start still alert.
- First 10 minutes after the change (includes our own Tier 2 test events): 517 alerts, about
  74k/day against 500k/day before; 87907 down from 90% to 24% (what is left is mainly Greenbone's
  sampler/exporter `redis-cli`). **Gate (at least 85% drop over 24 h) is re-measured 24 h later**:
  run `wazuh-tuning.yml -e tune_mode=alerts -e tune_tag=post-1d-24h` after 2026-10-16 ~22:00 NZDT.
- Newly visible in the remaining noise: rule 550 FIM (about 26k/day, Phase 2a), and rules 87915/87916
  (Docker volume mounted/unmounted on `/etc/filebeat`, 66 each per 10 min), which need a look in Phase 2.

### Phase 2a done (2026-10-15)

FIM ignore lists are repo-managed shared agent config (`files/wazuh-stack/agent_conf/{default,build_seg,pentest_seg}.xml`,
each block scoped to one agent by name, delivered by `deploy-wazuh-stack.yml --tags wazuh_agent_conf`): pve host
`lrm_status` (57% of FIM alerts), ci-runner `_diag` and `_work/_update`, Greenbone `mem.log`/`tuning.log`. Result: FIM
events 62 per 3 min -> 0 on the first post-reload window; everything under /etc, /usr, /bin, /sbin, /root still
monitored (Tier 2 live FIM add/modify/delete pass). A unit test refuses any ignore entry on protected paths.

**Lesson (cost one failed rollout):** `docker cp` into a group dir made `agent.conf` briefly root-owned;
`wazuh-remoted` logged "Permission denied ... Invalid shared file" and left it out of the merge, and the pve agent
then reported (1207) "remote configuration is corrupted". Fix: stage and chown outside `shared/`, then `mv`
atomically; backups live in `/var/ossec/etc/agent-conf-backup/`, never in a group dir (everything in a group dir is
pushed to the agents). Remedy for a stuck group: touch its `agent.conf` (remoted logs "is valid after last
modification").

### Phase 2b / 2c done (2026-10-15)

- **2b rootcheck 510 (3,320/day):** 3,314 were `File '/dev/.lxc…' present on /dev` (LXC's own `/dev/.lxc-boot-id` and
  `/dev/.lxc/proc/*`, 48 distinct names, in every container); rule 100210 (level 0) matches that exact anchored shape only.
  The other 6/day (`Files hidden inside directory '/var/lib/docker/overlay2/…'`, overlayfs link-count quirks) are left alone.
  Live proof on apt-cacher-stack (`-e live_rootcheck=true`): a hidden `/dev/.mfire<epoch>` marker still alerts 510 L7
  while no `lxc` file alerts in the same scan.
- **2c rule 2501 on graylog-stack (2,754/day):** not a graylog problem and not an outside attack. They are MikroTik hAP
  router log lines (`login failure for user nsroot/karaf/insight … from 192.168.70.11 via ssh`) forwarded into graylog-stack's
  syslog: 100% (2,754 of 2,754) from the Greenbone scanner, clustered in scan windows, default-credential user names.
  Rule 100211 lowers exactly that (scanner address, ssh, hAP) to level 3; other sources, other protocols and look-alike
  addresses keep level 5 (`must_fire.py hap`, 4 checks).
- **Lessons:** the pre-decoder strips the timestamp and hostname before a rule's regex runs (a pattern that included
  `hAP` could never match); logtest cannot produce rootcheck events, so that needs a live scan (API `PUT /rootcheck`
  on one agent); in the live playbook the scan must be triggered before the wait; the manager was restarted five
  times on 2026-10-15 for rule changes, so batch local_rules.xml changes next time.

### Phase 2d done (2026-10-15)

Local rules 100200 (5710), 100201 (5712 brute force, was level 10) and 100202 (5760) lower sshd events
from the Greenbone scanner 192.168.70.11 to level 3, for that address only (parent rules keep stock levels
for everything else). Test `must_fire.py scanner` (6 checks incl. a 12-event burst): before the change the
three scanner checks failed; after, 6/6. 5740 (connection reset, about 800/day) has no source address, so it
is not scoped and stays as is. Also done 2026-10-15: GVM sampler stopped (operator), 87915/87916 volume
mount/unmount (238/day each, container lifecycle audit records) deliberately left alerting, ISM system-index
replicas set to 0 (cluster green), old 4.14.7 images pruned.

### Phase 3 analysis: the 3,957 vulnerability findings (read-only, informational)

All 3,957 findings come from the Debian Security Tracker via Wazuh's CTI feed ("Package default status"), so they are
Debian's own open items for trixie, not Wazuh false positives. `vuln_triage.py` (offline, tested) classifies every
Debian package/CVE pair by the tracker's status for trixie:

| Class | Findings | What it means |
|---|---|---|
| open, urgency not yet assigned | 3,831 (97%) | Debian has not triaged these CVEs yet; nothing to install; accept pending triage, re-check weekly |
| fix available in trixie | 105 (3%) | `urllib3 1.26.20` (4 CVEs) and `requests 2.32.2` (1 CVE) on the 21 Docker hosts: the **pip pins in our own `wazuh_agent` role** (docker-listener wodle) |
| open, urgency low | 3 | Debian judges them minor |
| non-Debian | 18 | Amazon Linux 2023 inside the Wazuh manager container image (vendor image; goes with Wazuh image updates) |

Where the volume is: the **vim family is 3,074 findings (78%)** (`vim`, `vim-runtime`, `vim-tiny`, `vim-common`, 29 CVEs, same
version `2:9.1.1230-2` on about 27 hosts). Those packages are manually installed in the **base LXC template** (dpkg
dates 10 May), not by our playbooks, and every host also has `nano`. Next: libxml2 271, urllib3 147, containerd 78 +
runc 78 (3 High each, CVE-2025-31133/52565/52881 and 2026-46680, real container-runtime items still awaiting Debian
triage), python3-urllib3 54, requests 42, libexpat1 and zlib1g 27 each (+26 each for their `-dev` packages, pulled in by
`libpython3.13-dev`). zlib1g's CVE-2026-85091 affects "1.3.1.2 through 1.3.2" while the installed version is 1.3.1: a
probable false positive that Debian has not yet marked. The pve host carries libthrift (39 CVEs), amd64-microcode (10),
libcups2t64 (8): hypervisor patching, the operator's call.

**Scope note (operator, 2026-10-15):** this session tunes Wazuh and its agents; it does not apply host updates.
Package removal, pip pin upgrades and pve patching are therefore *not* part of this plan. The analysis above is
kept as a note for whoever owns patching, and `vuln_triage.py` is the repeatable report. The Wazuh-side Phase 3
work is the detector's own configuration, what the agents feed it (syscollector), SCA, and how findings are
surfaced (Phase 6); the detector has no per-CVE exclusion, so nothing is hidden in the index.

### Phase 3 done: Wazuh-side configuration (2026-10-15)

Reviewed and left alone (evidence: nothing to gain): vulnerability-detection settings (defaults, sensible), syscollector
`processes` and `ports all="yes"` (the whole inventory is 1-3MB per index), SCA (the right `cis_debian13` policy runs on 27
agents, no alert noise, fleet score 43% with about 105 failing and 22 invalid checks per host, a baseline not a fault).

Fixed, as shared agent config (`agent_conf/common.xml`, every group) plus the same settings in the `wazuh_agent` role for
newly provisioned hosts:
- **Secrets stored in FIM alerts.** `report_changes` puts the content of a changed text file into the alert. 672 alerts in
  14 days carried a stored diff of `/etc/shadow(-)`, `/etc/gshadow(-)`, Proxmox keys and tokens (`/etc/pve/priv/*`), a TLS
  key and an `.env` file. `<nodiff>` now keeps the change alert and replaces the content with Wazuh's placeholder
  ("Diff truncated due to 'nodiff' configuration detected for this file."). Verified live: a changed `.key` file alerts with
  the placeholder and none of its content; an ordinary file still stores its diff. Past alerts are not purged (operator:
  fine while the secrets are not in git); they age out at 90 days.
- **Rootkit file and trojan checks were silently off** on every agent ("No rootcheck_files file configured"), and the rule
  files exist only in the `default` group directory, so 18 agents could never have had them. The files are now copied into
  every group and referenced from the shared config. Verified live: a known signature file (`/tmp/mcliZokhb`, "Bash door")
  now raises a rootcheck alert.
- `config-profile` said `ubuntu24.04` on Debian 13 hosts; now `debian, debian13` (role only; it takes effect when a stack is
  next provisioned).

Rollout: canary on `game_seg` (gaming-stack-lab: config received, agent reloaded, no errors), then all 11 groups. 28 of 28
agents active, `events_dropped` 0. The vulnerability findings (3,957, 97% open and unassigned in the Debian tracker) are a
feed property; `vuln_triage.py` is the repeatable report. Patching is out of scope for this plan.

### Phase 6 (Grafana) done (2026-10-15)

Before: wazuh-stack was missing from the monitoring stack's `node_exporter` and `cadvisor` target lists (node_exporter ran on
:9100 but nothing scraped it, no cAdvisor, no textfile collector), so the standard Node Detail, Docker Containers and Lab Overview
dashboards had no Wazuh data, and nothing Wazuh-specific existed in Grafana beyond the vulnerability panels (UVM).

Now:
- **Standard metrics:** `wazuh-stack` is scraped for host (`:9100`) and containers (cAdvisor `:8080`, its own compose project at
  `/opt/wazuh-cadvisor`, capped at 256MB because the host has only about 1.3GB free). Both targets `up = 1`; the existing dashboards
  pick it up through the `stack="wazuh-stack"` label.
- **Wazuh dashboard** (`dashboards/wazuh.json`, uid `wazuh`, 32 panels): health at a glance (agents not active, events dropped, queue fill,
  heap, cluster status, container health, 24h alerts, noisiest-rule share, index count and age, metrics age, failing collectors),
  alerts (per hour, top rules, by level, FIM per hour, vulnerabilities), agents and pipeline (per-agent table, events/s, queues,
  remoted sessions), indexer and storage (heap, disk, index size, shards, containers). The README targets are drawn as thresholds.
- **Exporter:** role `wazuh_metrics` (`wazuh_metrics.py`, 1-minute systemd timer, textfile `wazuh.prom`). Six independent collectors
  (`wazuh_collector_ok{collector}`); reads the indexer with a scoped read-only user (`wazuh_metrics_reader`, cluster monitor plus
  read on alert and vulnerability-state indices), agent status from `agent_control`, counters from the analysisd and remoted state
  files; a unit test fails if the dashboard queries a metric the exporter does not emit.
- **Deployed:** wazuh-stack via `deploy-wazuh-stack.yml --tags monitoring-integration` (re-applies the node_exporter role with the
  textfile collector on, cAdvisor, the role). monitoring-stack by hand in the playbook's exact rendering (the playbook has no tags and
  a full run redeploys everything): two scrape targets plus the dashboard file, VictoriaMetrics reloaded with SIGHUP; the playbook's own
  scrape task in `--check --diff` reports no change, so a later full run will not churn it. All 29 dashboard queries return data.
- First readings: 1,246 alerts in the last hour (about 30k a day, under the 50k target). The 24h panels still include the hours before
  the 1d change and fall as those age out.
- **Not built:** Grafana alert rules (the repo has no provisioned alert mechanism, only a manual coredns example; delivery is a
  separate plan).

## Out of scope (separate plans)

- Discord or other alert delivery (separate plan, same as Greenbone).
- Moving the Wazuh stack to pve-tiny (see memory `project_pve_tiny_load_shifting`;
  tuning first makes that move cheaper: much less data and indexing load).
- Feeding Wazuh findings into secpipe (already tracked in docs/wazuh-stack/).
