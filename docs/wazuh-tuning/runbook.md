# Wazuh tuning runbook

How to measure, test and change the Wazuh stack safely. Background and results: [README.md](README.md); phases and
gates: [plan.md](plan.md). Everything runs through `./with-secrets-prod` (production controls apply, even for
read-only runs: the wrapper treats `ansible-playbook` as mutating, so a named `TASK_APPROVAL` is required).

## Where things are

| Piece | Address / location |
|---|---|
| wazuh-stack LXC | 192.168.40.15 (vmid 40015, `infra_seg`); containers `wazuh-stack-manager`, `wazuh-stack-indexer`, `wazuh-stack-dashboard`; compose in `/opt/wazuh-stack`; helper in `/opt/wazuh-stack/tuning` |
| Indexer API | 127.0.0.1:9200 on the host (HTTPS; `admin` / `WAZUH_INDEXER_ADMIN_PASSWORD`; scoped read-only users for the findings sync and the metrics exporter) |
| Manager API | 127.0.0.1:55000 on the host (HTTPS; `wazuh-wui` / `WAZUH_API_PASSWORD`) |
| Inventory | `~/git/proxmox-homelab/terraform/lxc/environments/pve/wazuh-stack/inventory.yml` (ignored file in the main checkout) |
| Tooling | `terraform/lxc/ansible/files/wazuh-tuning/` (helper, suites, unit tests), `playbooks/wazuh-tuning.yml`, `playbooks/wazuh-mustfire-live.yml` |
| Grafana | dashboard `/d/wazuh`; exporter role `wazuh_metrics` |

## Where each kind of config lives and how it gets there

| Config | Source of truth in the repo | Deploy (from a worktree of the branch you want) | Side effect |
|---|---|---|---|
| Local rules (health-check suppression, scanner, rootcheck, hAP) | `files/wazuh-stack/docker_healthchecks.json` + `gen_local_rules.py` produce `local_rules.xml` (unit test keeps it current) | `deploy-wazuh-stack.yml --tags wazuh_local_rules` (backup, `docker cp`, `wazuh-analysisd -t`, restart only on success, restore on failure) | **manager restart (1-2 min)**: batch rule changes |
| Shared agent config (FIM ignore and `nodiff`, rootkit paths) | `files/wazuh-stack/agent_conf/common.xml` (every group) + `<group>.xml` (agent-scoped blocks) | `deploy-wazuh-stack.yml --tags wazuh_agent_conf`; canary first with `-e '{"wazuh_agent_conf_groups":["game_seg"]}'` | none on the manager; agents reload themselves |
| Retention, ISM replicas | playbook var `wazuh_alert_retention_days` | `deploy-wazuh-stack.yml --tags wazuh_retention` | none |
| Versions, healthchecks, compose | `deploy-wazuh-stack.yml` (`wazuh_image_tag`) and the agent role (`wazuh_agent_version`, must be equal, a test enforces it) | a full run recreates all three containers; for one container edit the live compose in the playbook's exact form and `docker compose up -d --no-deps <svc>` | container recreate |
| Agent `ossec.conf` | role `wazuh_agent` | the stack's own provision (`scripts/provision.sh --stack <name>`) | agent restart |
| Metrics and Grafana | role `wazuh_metrics`, `dashboards/wazuh.json`, monitoring playbook targets | wazuh host: `deploy-wazuh-stack.yml --tags monitoring-integration`; monitoring-stack: see "Grafana" below | none for Wazuh |

## The measurement helper and the suites

`wazuh_tuning.py` modes (run through `wazuh-tuning.yml -e tune_mode=<mode>`; a window argument is hours like `24`
or minutes like `10m`; several words need JSON: `-e '{"tune_args":"87907 24"}'`): `health`, `alerts [window]`,
`noise <rule> [window]`, `sample <rule> [n] [agent|-] [window]`, `agents`, `retention`, `indices`, `fim <agent>`,
`fimpaths [window] [n]`, `fimdoc <agent> <path-fragment> [window]`, `fimdiff`, `fimsensitive`, `hist <rule> [window] [phrase]`,
`agentrules <agent> [window]`, `commands [hours]` (87907 command list), `sca`, `agentconf <agent>`, `vulns`,
`vulndetail`, `vulnpkg <pkg>...`, `vulncves`, `vulnhosts <pkg>...`. JSON lands in `docs/wazuh-tuning/artifacts/<tag>-<mode>.json`
(ignored; **it can contain secrets that appeared in alerts, never commit it**). `wazuh_tuning.diff_json` compares two runs and
`stop_conditions()` encodes the stop list. `vuln_triage.py` is the offline vulnerability report (needs the Debian tracker JSON).

Detection regression suites (all must pass before and after every change; the first four use the manager's logtest and
write no alerts):

| Suite (`-e tune_mode=`) | Checks | Run when |
|---|---|---|
| `mustfire` | 11: sshd, sudo, useradd, docker start/exec samples, plus presence of the FIM and disconnect rules | always |
| `suppression` | 48: each of the 40 health checks hits a level-0 rule, 8 look-alikes still fire 87907 | after any `local_rules.xml` change |
| `scanner` | 6: scanner sshd events L3, other sources stock levels, a 12-event burst | after any `local_rules.xml` change |
| `hap` | 4: router login failures from the scanner lowered, others not | after any `local_rules.xml` change |
| live (`wazuh-mustfire-live.yml`) | real marked actions on one test agent: user add/delete, ssh, FIM add/modify/delete, `nodiff`, optional rootcheck (`-e live_rootcheck=true`) and Docker (`-e live_docker=true -e live_docker_image=<img> -e live_group=portainer_stack`) | after FIM, rootcheck, agent-config or Docker-affecting changes; needs its own approval name |

Live runs need both inventories: `-i $E/apt-cacher-stack/inventory.yml -i $E/wazuh-stack/inventory.yml` (`E=.../environments/pve`).
A past run can be re-checked without acting again: `--limit wazuh_stack -e live_marker=mfire<epoch>`.
logtest cannot produce rootcheck events; rootcheck needs the live run (it triggers a scan through the API).

## Re-measure the 24 h gates

After 2026-10-16 ~23:00 NZDT (24 h after the last rule change). From a worktree of `stable`:

```bash
export TASK_APPROVAL=wazuh-tuning-24h-remeasure ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles
INV=~/git/proxmox-homelab/terraform/lxc/environments/pve/wazuh-stack/inventory.yml
T() { ./with-secrets-prod ansible-playbook -i $INV -u root terraform/lxc/ansible/playbooks/wazuh-tuning.yml </dev/null "$@"; }
T -e tune_mode=alerts -e tune_tag=after24h          # total, top-rule share, by rule/agent/level
T -e tune_mode=fimpaths -e tune_tag=after24h        # rule 550 volume (baseline 29,715/24 h)
T -e tune_mode=retention -e tune_tag=after24h       # indices vs ISM-managed, shards, cluster
T -e tune_mode=health -e tune_tag=after24h          # heap, queues, events_dropped, agents
```

Gates: alerts under 50,000 and no rule over 10% of the volume; rule 550 down at least 80% from 29,715; today's alert
index has the `wazuh-alerts-retention` policy; cluster green. The baseline numbers are in the README and the
point-in-time baseline JSON is in `docs/wazuh-tuning/artifacts/baseline-*.json` of the main checkout. Write the results into
the README "Results at a glance" table and close or reopen the gates.

## Making a change (the loop used for every phase)

1. Change the repo on a short-lived `work/*` branch in a worktree (never the shared checkout; see the memory note on deploys
   picking up the wrong branch). Unit tests plus `ansible-playbook --syntax-check`.
2. Preflight to the operator: target, exact objects, exact commands, out-of-scope items. Wait for "proceed".
3. `export TASK_APPROVAL=<named-task>`. Run `health` and the relevant suites (before), start the sampler for anything with risk.
4. Apply with the narrowest tags; canary on one lab group first for agent config.
5. Run the suites again (after) and `health`; check the stop conditions (heap over 85% for 5 min, free RAM under 800MB,
   `events_dropped` rises, any queue over 50%, a suite fails, an agent leaves `active`). Roll back first, investigate second.
6. Record the result in the README phase record; commit.

## Grafana (Phase 6)

- Dashboard: Grafana > Wazuh (`/d/wazuh`). Metrics file on the host: `/var/lib/node_exporter/textfile/wazuh.prom`, written every
  minute by `wazuh-metrics.timer` (`journalctl -u wazuh-metrics`). `wazuh_collector_ok{collector}` shows which source failed.
- Redeploy the host side alone: `deploy-wazuh-stack.yml --tags monitoring-integration`. The scoped indexer user is recreated if a
  security-config reapply (the OIDC play) wipes it.
- The monitoring-stack playbook has no tags; to add a dashboard or target without a full redeploy, edit the live
  `victoria-metrics/scrape.yml` in the playbook's exact form, `docker kill -s HUP victoriametrics`, and verify parity with
  `ansible-playbook ... --check --diff --start-at-task "Write VictoriaMetrics scrape config"`.

## Gotchas learned

- Ansible re-evaluates a `lookup('pipe', ...)` in a play var on every use; fix a per-run value
  with `set_fact` (a marker built that way once left a stray user behind).
- Docker-listener alerts have a null `full_log`; use `data.docker.*`.
- A first-time sudoer fires 5403 (L4), later ones 5402 (L3).

- The wrapper treats `bash -c` as mutating, so a named `TASK_APPROVAL` is required even
  for these read-only runs.
- A shell command that nests several levels of quoting around the Python or jq can trip
  Claude Code's safety classifier; keep scripts in files, as above.
- `track_total_hits` defaults to 10,000: use it explicitly (the scripts do) or totals
  look capped at exactly 10,000.
- `full_log` is a text field, not aggregatable; aggregate on `rule.*`, `agent.name`,
  `syscheck.path`, `data.*` fields.
- The dashboard container being `unhealthy` is the healthcheck's 401, not an outage.
- `local_rules.xml` and shared agent config live in the `wazuh_etc` named volume, not on
  the host filesystem: the playbook must deliver them (like the authd password file via
  `docker cp`) and validate with `wazuh-analysisd -t` before reloading.
- Docker health checks are logged by the agents' `docker-listener` wodle as rule 87907
  events; that is the single biggest noise source.

- **Never `docker cp` straight into a shared group directory.** The file is briefly root-owned, `wazuh-remoted` logs
  "Permission denied ... Invalid shared file" and leaves it out of the merge (the agent then complains `(1207)`). Stage
  and `chown` outside `shared/`, then `mv`. A stuck group is cured by touching its `agent.conf`. Backups must not live in a
  group directory either: everything in one is pushed to the agents.
- **A rule's `regex`/`match` sees the line after the pre-decoder** (timestamp and hostname already removed). Patterns that
  include them never match. `& < >` cannot be escaped in a pcre2 `<field>`; match them as `.`.
- **`<nodiff>` does not drop `syscheck.diff`**; it replaces the content with "Diff truncated due to 'nodiff' configuration".
- **Each `local_rules.xml` change restarts the manager** (about six restarts on 2026-10-15). Batch them.
- **A rootkit rule file only reaches agents in groups whose directory contains it.** They are copied into every group.
- **The monitoring-stack playbook has no tags**: apply scrape targets and dashboards by hand in the playbook's exact form and
  prove parity with `--check --diff --start-at-task "Write VictoriaMetrics scrape config"`.
- **`ansible` ad-hoc strings starting with `{`**, or containing Docker's `{{.Name}}` format, break Ansible's templating; wrap in
  `{% raw %}` and do not start the command with a brace.
