# T-Pot monitoring integration plan (Graylog logs, Grafana metrics, Wazuh agent)

Workspace: `docs/tpot-honeypot/`. Branch: `work/tpot-monitoring`.
Written 2026-10-15, right after the host's apt upgrade (17 packages incl. Docker
29.9.1; all 30 containers and ES green afterwards).

Goal: make the T-Pot Raspberry Pi 5 (`tpot.gibbsgreatly.xyz`, 192.168.1.28,
Debian 13 arm64) visible in the same Graylog / Grafana / Wazuh systems as the
rest of the lab, **without touching `~/tpotce/`** (see the "Management boundary"
in `plan.md`). Every change is host-layer only: rsyslog, one extra container
outside T-Pot's compose project, and an agent package.

## Facts established (all verified live 2026-10-15)

- Host arch is `arm64`. `packages.wazuh.com` serves `wazuh-agent` 4.14.8-1 for
  arm64 (the version `wazuh_agent_version` pins). `ghcr.io` is reachable from
  the Pi. No `rsyslog` and no `prometheus-node-exporter` installed.
- **TCP 9100 on the host is already bound by `docker-proxy`** (a T-Pot
  container publishes it), so the repo's `node_exporter` role (fixed at 9100,
  TLS + basic auth) cannot be used as-is. cAdvisor on **8083** (free on the
  host) is used instead; it reports per-container CPU/memory/network plus host
  totals. Host disk/temperature panels are deferred (see "Not in this plan").
- Docker's daemon log driver is `json-file`. Switching it to syslog means
  recreating all containers, which this plan avoids. Attack events already reach
  OpenSearch via `tpot_findings_ingest`; Graylog only needs host-level logs.
- **Firewall: no new MikroTik rules are needed for logs or Wazuh.**
  - Graylog: the live rule `shared Graylog TCP syslog ingress (managed zones)`
    accepts `192.168.1.0/24` -> 192.168.20.14:514
    (`mikrotik-firewall-shared-graylog-ingress.yml`).
  - Wazuh: the live rule `wazuh-stack: lan (pve host) to Wazuh manager`
    accepts `192.168.1.0/24` -> 192.168.40.15:1514,1515.
  - Metrics (monitoring-stack 192.168.20.12 -> tpot:8083): no explicit rule
    found in the router export, and framework (also on the flat LAN) is scraped
    the same way. **Unverified** whether it passes by a general rule; step
    `tpotmon-06` verifies it from the scraper's side before anything is added.
- **IP collision hits Wazuh.** `ip route get 192.168.40.15` on T-Pot resolves
  into Docker bridge `br-97fc492054e5` (192.168.32.0/20 covers 192.168.32-47).
  Wazuh (192.168.40.15) is unreachable without a host route, exactly like
  secpipe (192.168.50.12) was. Graylog (192.168.20.14) and monitoring
  (192.168.20.12) are **not** in a colliding range and route via eth0 already.

## Order

1. Logs (`tpotmon-01`), 2. metrics (`tpotmon-02`..`tpotmon-04`, `-06`),
3. Wazuh (`tpotmon-05`, `-07`). Each deploy is a separate operator action; do
not chain them.

### tpotmon-01-playbook-skeleton-rsyslog

```yaml
id: tpotmon-01-playbook-skeleton-rsyslog
title: New host-layer monitoring playbook for T-Pot, rsyslog forwarding only
depends_on: []

change: >
  Create ansible/00-initial-setup/tpot-monitoring.yml with one play, `hosts:
  tpot`, `become: true`, whose only task is `ansible.builtin.include_role:
  name: rsyslog_forward` with `vars: rsyslog_forward_disable_imklog: false`
  (bare metal keeps its kernel log, same as framework-desktop-bootstrap.yml
  line ~456). Header comment must state: host layer only, never touches
  ~/tpotce/, run with ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles and
  LAB_IP_GRAYLOG exported (use ./with-secrets-prod for the env), and that the
  firewall already allows 192.168.1.0/24 -> Graylog 514.

scope:
  allowed_paths:
    - ansible/00-initial-setup/tpot-monitoring.yml
  forbidden_actions:
    - "Any edit to ~/tpotce/ or any T-Pot file on the host"
    - "Running ansible-playbook against the host -- syntax-check only"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles LAB_IP_GRAYLOG=192.168.20.14 ansible-playbook --syntax-check -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-monitoring.yml"
    expect: "exit 0"
    critical: true
```

### tpotmon-02-cadvisor-task

```yaml
id: tpotmon-02-cadvisor-task
title: Add a standalone cAdvisor container (port 8083) to the T-Pot monitoring playbook
depends_on: [tpotmon-01-playbook-skeleton-rsyslog]

change: >
  In ansible/00-initial-setup/tpot-monitoring.yml add play vars
  `tpot_cadvisor_image: "ghcr.io/google/cadvisor:v0.60.5"`,
  `tpot_cadvisor_port: 8083`, `tpot_cadvisor_dir: /opt/cadvisor-docker`, then
  tasks that (a) create that directory (mode 0755), (b) copy a
  docker-compose.yml there and (c) run `docker compose up -d` in it, copying
  the three tasks and the compose content of
  ansible/00-initial-setup/framework-desktop-cadvisor.yml (lines ~44-95)
  literally, renaming `framework_cadvisor_*` to `tpot_cadvisor_*`. Do NOT copy
  that playbook's "Install Docker" and "Ensure docker service" tasks -- Docker
  is already installed and owned by T-Pot; installing or restarting it is
  forbidden. The compose project name must differ from T-Pot's (it lives in
  /opt/cadvisor-docker, so the default project name `cadvisor-docker` already
  does).

scope:
  allowed_paths:
    - ansible/00-initial-setup/tpot-monitoring.yml
  forbidden_actions:
    - "Adding apt install of docker.io / docker-compose-v2, or any systemd action on docker"
    - "Putting the cAdvisor service in ~/tpotce/docker-compose.yml"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles LAB_IP_GRAYLOG=192.168.20.14 ansible-playbook --syntax-check -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-monitoring.yml"
    expect: "exit 0"
    critical: true
  - id: no-docker-install
    cmd: "! grep -n -E 'docker\\.io|docker-compose-v2|name: docker$' ansible/00-initial-setup/tpot-monitoring.yml"
    expect: "exit 0"
    critical: true
```

### tpotmon-03-grafana-scrape-target

```yaml
id: tpotmon-03-grafana-scrape-target
title: Add T-Pot to monitoring-stack's cadvisor scrape job
depends_on: []

change: >
  In terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml, inside the
  `job_name: cadvisor` static_configs list (directly after the framework entry
  that ends `labels: {stack: framework}` with port 8083), add exactly two
  lines at the same indentation as that entry:
  `- targets: ["tpot.gibbsgreatly.xyz:8083"]` and
  `  labels: {stack: tpot-honeypot}`.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  forbidden_actions:
    - "Any other edit to that file"
    - "Running the playbook / provision.sh -- operator deploys it"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
  - id: one-new-target
    cmd: "git diff --stat -- terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml | tail -1"
    expect: "1 file changed, 2 insertions(+)"
    critical: true
```

### tpotmon-04-wazuh-host-route

```yaml
id: tpotmon-04-wazuh-host-route
title: Add the Wazuh manager to T-Pot's colliding-range host routes
depends_on: []

change: >
  In ansible/00-initial-setup/tpot-host-baseline.yml, append one entry to the
  `tpot_extra_host_routes` list, directly under the secpipe entry, exactly:
  `      - host: "192.168.40.15"  # wazuh-stack manager (infra_seg) -- inside T-Pot's Docker 192.168.32.0/20; Wazuh agent 1514/1515`.
  No other edit.

scope:
  allowed_paths:
    - ansible/00-initial-setup/tpot-host-baseline.yml
  forbidden_actions:
    - "Any edit outside the tpot_extra_host_routes list"
    - "Running the playbook -- it also does an apt upgrade; the operator applies the route with a targeted --tags/--start-at-task or by hand"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-host-baseline.yml"
    expect: "exit 0"
    critical: true
  - id: one-new-line
    cmd: "git diff --stat -- ansible/00-initial-setup/tpot-host-baseline.yml | tail -1"
    expect: "1 file changed, 1 insertion(+)"
    critical: true
```

### tpotmon-05-wazuh-agent-role

```yaml
id: tpotmon-05-wazuh-agent-role
title: Add the wazuh_agent role to the T-Pot monitoring playbook (docker monitoring OFF)
depends_on: [tpotmon-01-playbook-skeleton-rsyslog, tpotmon-04-wazuh-host-route]

change: >
  In ansible/00-initial-setup/tpot-monitoring.yml add a second
  `include_role: name: wazuh_agent` task AFTER the rsyslog task, with `vars:`
  `wazuh_agent_group: "tpot-honeypot"`, `wazuh_agent_docker_monitoring_enabled:
  false` (docker.sock access on a honeypot host is deliberately refused), and
  `wazuh_agent_fim_paths: []`. Add header lines naming the extra required env
  (LAB_IP_WAZUH, WAZUH_AGENT_AUTHD_PASSWORD, WAZUH_API_PASSWORD) and that the
  route from tpotmon-04 must be applied first.

scope:
  allowed_paths:
    - ansible/00-initial-setup/tpot-monitoring.yml
  forbidden_actions:
    - "Enabling docker monitoring or adding /home/steve/tpotce to wazuh_agent_fim_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles LAB_IP_GRAYLOG=192.168.20.14 LAB_IP_WAZUH=192.168.40.15 WAZUH_AGENT_AUTHD_PASSWORD=x WAZUH_API_PASSWORD=x ansible-playbook --syntax-check -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-monitoring.yml"
    expect: "exit 0"
    critical: true
  - id: docker-monitoring-off
    cmd: "grep -n 'wazuh_agent_docker_monitoring_enabled: false' ansible/00-initial-setup/tpot-monitoring.yml"
    expect: "one matching line"
    critical: true
```

## Operator actions (not step blocks)

Each needs its own go-ahead; none are chained.

**tpotmon-06 -- verify scrape reach before deploying cAdvisor.** After the
cAdvisor deploy below, check from monitoring-stack's side that
`tpot.gibbsgreatly.xyz:8083` answers (read-only `curl` from LXC 192.168.20.12 or
VictoriaMetrics target page). If it times out, add a narrowly-scoped
`192.168.20.12 -> 192.168.1.28 tcp/8083` MikroTik rule, using
`mikrotik-firewall-secpipe-to-tpot.yml` as the template (comment-anchored,
idempotent, placed before the zone's deny rule).

**tpotmon-07 -- Wazuh agent registration** also needs reach to the manager API
(55000) from wherever the role's group step runs; that is the same path the
other agents already use, so no change is expected.

Run order, with the exact commands:

1. Logs + cAdvisor (tpotmon-01/02), from the repo root:
   `ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles TASK_APPROVAL=<task> ./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-monitoring.yml --tags <logs|cadvisor>`
   (add tags to the tasks if the operator wants them separable).
   Check: `curl -s tpot.gibbsgreatly.xyz:8083/metrics | head`; a test line
   `logger -t tpot-monitoring-test hello` on T-Pot appears in Graylog.
2. Scrape target (tpotmon-03): `scripts/provision.sh --stack monitoring-stack`
   under the production approval flow. Check the `cadvisor` job shows
   `tpot-honeypot` as UP in VictoriaMetrics, then build a Grafana panel from
   the existing "Docker Containers" dashboard filtered on `stack=tpot-honeypot`.
3. Wazuh route (tpotmon-04) applied on T-Pot, `ip route get 192.168.40.15`
   must say `via 192.168.1.1 dev eth0`; then the Wazuh play.

After each deploy re-run the health check used on 2026-10-15: 30 containers up,
ES `green`, `tpot-findings-ingest` still syncing.

## Not in this plan

- Host disk/temperature metrics (needs a node_exporter on a non-9100 port plus
  step-ca TLS issuance; revisit if the cAdvisor host totals are not enough).
- Docker-log-driver change / container logs into Graylog (needs container
  recreation).
- Moving T-Pot's `.env` secrets into OpenBao beyond a recovery copy.
- Alerting rules for the new scrape target.
