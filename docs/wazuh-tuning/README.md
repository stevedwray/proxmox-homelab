# wazuh-tuning

Test and tune the Wazuh SIEM stack with the same method used for Greenbone
(docs/gvm-scan-redesign/): baseline first, one supervised change at a time, numeric
decision gates, tooling and config in the repo, docs and memory kept current.

Status: **Phase 0 done** (2026-10-15): tooling built, baseline captured and verified, must-fire
suite green (Tier 1 11/11, Tier 2 6/6 on apt-cacher-stack). Docker live cases
also pass (Tier 2 8/8 on portainer-stack). Nothing has been changed on the live Wazuh config yet.
Branch `work/wazuh-tuning`; execution happens in a separate session, one
phase at a time, each with its own approval. See [plan.md](plan.md) for phases and
gates and [runbook.md](runbook.md) for how to run the read-only survey tooling.

## Why now

`docs/wazuh-stack/README.md` still describes the August pilot (6 agents). The fleet is
now 28 agents and the stack has never been measured or tuned. A read-only survey on
2026-10-15 found problems that are cheap to fix and one that matters for capacity.

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

### Phase 0 verification (2026-10-15)

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

## Phase 1a done (2026-10-15)

Dashboard healthcheck now accepts 401 (`deploy-wazuh-stack.yml`). Applied live without a
stack redeploy: the same two lines were written into `/opt/wazuh-stack/docker-compose.yml`
(backup `docker-compose.yml.bak-1a` left beside it) and `docker compose up -d --no-deps
wazuh.dashboard` recreated only the dashboard. Result: dashboard `healthy`; manager and indexer
not restarted; must-fire green; `events_dropped` 0, queues 0. The playbook-rendered compose
file now matches the live one, so a later full deploy is a no-op for this line. (A full deploy
still recreates all three containers whenever the compose file changes, hence the targeted path.)

## What good looks like (targets)

| Metric | Now | Target |
|---|---|---|
| Alerts per day | 500k | under 50k |
| Share of alerts from one rule | 90% | no rule over 10% |
| Indexer growth | 0.4GB/day | under 0.05GB/day |
| Retention | none | defined and enforced (operator choice, see decisions) |
| Dashboard container | unhealthy | healthy (**done 1a, 2026-10-15**) |
| Manager vs agent versions | skewed | manager >= every agent |
| Detection regression | not tested | every must-fire test passes before and after each change |

## Decisions needed from the operator

1. **Retention period** for alert indices (suggest 30 days hot, then delete; or 14 if
   disk matters more than history).
2. **Docker health-check events**: drop silently (level 0 rule, recommended) or keep a
   count-only metric. Container start, stop and exec of anything that is not a health
   check stay alerting either way.
3. **Manager upgrade** to 4.14.8 or later, or pin agents to 4.14.7. Recommended:
   upgrade the manager, then pin both.
4. **Scanner exclusions**: treat 192.168.70.11 as a known scanner for sshd alerts
   (recommended, narrowly: only rules 5710, 5712, 5740 and only from that address).
5. **Scope** of agent coverage work: which hosts are still unenrolled (framework,
   pve-tiny, others) is Phase 5 and optional.

## Out of scope (separate plans)

- Discord or other alert delivery (separate plan, same as Greenbone).
- Moving the Wazuh stack to pve-tiny (see memory `project_pve_tiny_load_shifting`;
  tuning first makes that move cheaper: much less data and indexing load).
- Feeding Wazuh findings into secpipe (already tracked in docs/wazuh-stack/).
