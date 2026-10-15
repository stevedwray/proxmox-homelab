# Wazuh Stack

## Status

**LIVE in production on `pve` (vmid `40015`, `192.168.40.15`, `infra_seg`), version 4.14.8, tuned.**
Manager + indexer + dashboard (three Docker containers) behind Traefik with real Authentik OIDC login at
`https://wazuh.lab.gibbsgreatly.xyz`. **27 enrolled agents in 11 zone groups, plus the manager's own local agent
(28 entries in the API), all `active` and all on 4.14.8.** Roughly 30,000 alerts a day (it was about 500,000 before the
2026-10-15 tuning; the 24 h figure is being re-confirmed), a 90-day retention policy, and a Grafana dashboard.

The August pilot (6 agents) grew into the fleet rollout recorded in
[docs/lxc-scan-and-monitoring-rollout/](../lxc-scan-and-monitoring-rollout/README.md). The baseline, the tuning work, the
results and the open items are in [docs/wazuh-tuning/](../wazuh-tuning/README.md); how to measure, test and change
the stack is its [runbook](../wazuh-tuning/runbook.md). This file describes what the stack is and where its configuration lives.

Per agent, verified against real indexer data (not just configured): **FIM** (`syscheck`, per-stack extra watch paths, ignore
lists and `<nodiff>` for secrets via shared config), **rootcheck** (including the rootkit-file and trojan checks), **SCA**
(the `cis_debian13` policy; fleet score 43%), **vulnerability detection** (Debian tracker feed, about 3,957 open findings,
97% not yet triaged upstream) and **Docker container monitoring** (`docker-listener` wodle, opt-in, on the Docker stacks).

Not enrolled: `framework` (bare-metal Ubuntu), the `pve-tiny` hypervisor, `pentagi-stack` and the operator's own desktop
(see "What's not built yet").

## What this is

A standalone `wazuh-stack` LXC running Wazuh's official all-in-one single-node deployment (manager + indexer + dashboard),
plus a shared `wazuh_agent` Ansible role (`terraform/lxc/ansible/roles/wazuh_agent/`) deployed as an explicit opt-in addition
to each stack's own playbook (not wired into `lxc_base`, so enrolment stays deliberate per host). Agents enrol with
`agent-auth` against `wazuh-authd` (`use_password: yes`) into one zone group per host (`infra_seg`, `mgmt_seg`, ...).

## Where the configuration lives

| What | Where (repo) | How it is deployed |
|---|---|---|
| Stack, versions, healthchecks, indexer/manager config | `terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml` (`wazuh_image_tag` must equal the agent role's `wazuh_agent_version`) | the stack's provision; a compose change recreates all three containers |
| Local rules (health-check suppression, scanner, rootcheck, router logins) | `terraform/lxc/ansible/files/wazuh-stack/`: `docker_healthchecks.json` + `gen_local_rules.py` generate `local_rules.xml`, unit-tested | `--tags wazuh_local_rules` (validated with `wazuh-analysisd -t`, then a manager restart) |
| Shared agent config (FIM ignore lists, `<nodiff>`, rootkit file paths) | `files/wazuh-stack/agent_conf/common.xml` (every group) + `<group>.xml` (agent-scoped) | `--tags wazuh_agent_conf` (no restart; agents reload) |
| Alert retention (90 days) | ISM policy `wazuh-alerts-retention` + host cron for the manager's raw logs; `wazuh_alert_retention_days` | `--tags wazuh_retention` |
| Agent `ossec.conf` | role `wazuh_agent` | each stack's provision |
| Metrics and dashboard | role `wazuh_metrics`, `terraform/lxc/stacks/monitoring-stack/dashboards/wazuh.json` | `--tags monitoring-integration`; monitoring-stack targets |
| Findings to opensearch-stack | role `wazuh_findings_ingest` (vulnerability state, daily 06:00 UTC) | the stack's provision |
| Measurement and regression suites | `files/wazuh-tuning/`, `playbooks/wazuh-tuning.yml`, `playbooks/wazuh-mustfire-live.yml` | by hand through `./with-secrets-prod` |

Secrets are in OpenBao (`kv/services/wazuh`: `WAZUH_INDEXER_ADMIN_PASSWORD`, `WAZUH_API_PASSWORD`,
`WAZUH_OIDC_CLIENT_SECRET`, `WAZUH_AGENT_AUTHD_PASSWORD`); the stack's address is the `LAB_IP_WAZUH` variable.

## What's built and live

- `terraform/lxc/stacks/wazuh-stack/` (contract, `stack.yaml`, terragrunt, `edge.yaml`), the manager playbook (including
  `wazuh-authd` enrolment with the password file injected via `docker cp`), the shared `wazuh_agent` role (idempotency keyed on
  the agent's real connection status, not on a leftover `client.keys`), and `ansible/00-initial-setup/proxmox-wazuh-agent.yml`
  for hypervisors and bare metal.
- Agent fleet: 27 agents, 18 of them in a zone group only (no `default`), which is why the rootkit rule files are copied into
  every group directory.
- Full edge: Authentik application and provider, Traefik route, Technitium record.
- The 2026-10-15 tuning (details in docs/wazuh-tuning/): dashboard healthcheck, 4.14.8 upgrade, 90-day retention and manager
  log pruning, 40 health-check suppression rules, FIM ignore lists, scanner and LXC rootcheck rules, `<nodiff>` for secrets,
  rootkit checks enabled, Grafana metrics and dashboard, and the regression suites that guard all of it.
- Logs: the host, the indexer container and the dashboard container ship to Graylog (rsyslog forward; Docker uses the syslog
  log-driver). The manager's own `ossec.log` and `api.log` are files in the `wazuh_logs` volume and are not shipped yet.

## What's not built yet

- **Agents for `framework`, `pve-tiny`, `pentagi-stack` and the operator's desktop** (Phase 5 of the tuning plan, optional). The
  desktop is a different category (personal daily driver, not IaC-managed) and is the operator's call.
- **Grafana alert rules** (the repo has no provisioned alert mechanism; delivery to Discord is a separate plan).
- **The manager's `ossec.log` / `api.log` in Graylog** (proposed: an rsyslog `imfile` drop-in, not decided).
- **Phase 4 sizing**: right-sizing the LXC and a one-shard-per-index template for new alert indices, after ~7 days of data.
- Wazuh's own default `kibanaserver` password is still at the vendor demo value (same precedent as `opensearch-stack`).
- The dashboard's numeric API-connection label (`1513629884013`): a same-day rename caused a real regression (the app
  re-injects a stale duplicate entry on a non-numeric key) and was reverted; needs investigation of the app's validation logic.
- Moving the stack to `pve-tiny` is a separate plan (tuning makes it cheaper: much less data and indexing load).

## Lessons worth not re-learning

- **`wazuh-states-*` indices are per cluster-node, not per agent.** A
  real, multi-hour false diagnosis this session concluded vulnerability-
  detection only worked for the manager's own local agent, because
  every index name ends in `-wazuh.manager`. That suffix is the
  *writing node's* name, not an agent scope — a single index holds
  every agent's data, distinguished by the `agent.name` field inside
  each document. Always aggregate/filter on that field before
  concluding an agent "has no data" — see
  `reference_wazuh_states_index_per_agent_field` memory.
- **Idempotency checks need to verify real state, not a cheap proxy for
  it.** Both real bugs fixed this session (agent enrollment,
  `authd.pass`) followed the same shape: a check that looked at "did
  something on the host/container change" instead of "is the thing I
  actually care about true right now" — silently wrong exactly when a
  container gets rebuilt independently of whatever the cheap proxy was
  tracking.

- **Never `docker cp` into a shared agent-group directory** (it is briefly root-owned and `wazuh-remoted` skips the file);
  stage outside `shared/`, `chown`, then `mv`. Backups in a group directory get pushed to the agents.
- **Rules see the line after the pre-decoder** (timestamp and hostname are gone), and logtest cannot produce rootcheck events.
- **An unmeasured SIEM is mostly noise**: one Docker health-check rule was 90% of all alerts, and the real signal was
  invisible. Measure first, tune one thing at a time, and keep a must-fire test for every suppression.
- **FIM `report_changes` stores file content in the alert**; without `<nodiff>` that put password hashes, private keys and
  tokens into the indexer.
- **The `wazuh_agent` role used to install the latest package**, which let agents get ahead of the manager; the version is
  now pinned and a test keeps the manager tag and the agent version equal.
