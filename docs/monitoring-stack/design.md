# Monitoring Stack — Design

## Overview

The monitoring-stack LXC (192.168.20.12, `mgmt_seg`) runs VictoriaMetrics, Loki, Grafana, and Promtail via Docker Compose. Grafana is the sole browser-facing service (via Traefik + Authentik). VictoriaMetrics and Loki are internal-only data stores — they receive data from agents and are queried by Grafana.

Currently none of the other stacks ship metrics or logs. This document defines what will be collected, how, and in what order.

---

## Current State

The monitoring-stack LXC is **already provisioned and deployed** via `deploy-monitoring-stack.yml`. The following are running:

| Service | Status | Notes |
|---------|--------|-------|
| VictoriaMetrics | Running, `:8428` | `--retentionPeriod=90d` set; **no `--promscrape.config` flag** — not scraping anything |
| Loki | Running, `:3100` | Filesystem storage, schema v13; **no retention period configured** |
| Grafana | Running, `:3000` | OAuth via Authentik wired; datasources provisioned (VM + Loki) |
| Promtail (self) | Running | Collecting `/var/log/**/*.log` from monitoring-stack host only; no Docker discovery |

**Nothing is being scraped or collected from other stacks yet.** Phase 1–4 below is the remaining work.

---

## Architecture

```
                          mgmt_seg (192.168.20.0/24)
                         ┌──────────────────────────────────────────────────┐
                         │  monitoring-stack (192.168.20.12)                │
                         │  ┌─────────────────┐  ┌──────────────────────┐  │
                         │  │ VictoriaMetrics │  │       Loki           │  │
 ┌──────────────┐  scrape │  │   :8428         │  │       :3100          │  │
 │ node_exporter│◄────────┤  │  (pull metrics) │  │  (receive log push)  │  │
 │    :9100     │         │  └────────┬────────┘  └──────────┬───────────┘  │
 └──────────────┘         │           │                       │              │
 ┌──────────────┐  scrape │           │           ┌──────────▼───────────┐  │
 │   cAdvisor   │◄────────┤           │           │      Grafana         │  │
 │    :8080     │         │           └──────────►│      :3000           │  │
 └──────────────┘  push   │                       │  (queries both)      │  │
 ┌──────────────┐ ────────►                       └──────────────────────┘  │
 │   Promtail   │         │                                                  │
 │  (per stack) │         └──────────────────────────────────────────────────┘
 └──────────────┘
```

**Metrics flow**: VictoriaMetrics scrapes node_exporter (port 9100) and cAdvisor (port 8080) running on each LXC, plus application metrics endpoints directly. Pull model — VictoriaMetrics initiates all scrapes. No push agents (vmagent) required at this scale.

**Log flow**: A Promtail instance on each LXC pushes log lines to Loki at `http://192.168.20.12:3100/loki/api/v1/push`. Promtail runs as a Docker container on Docker stacks and as a systemd service on non-Docker stacks.

**Note on step-ca metrics**: step-ca exposes Prometheus metrics at `https://192.168.20.11:9443/metrics` (HTTPS with TLS). VictoriaMetrics must be configured with `tls_config.insecure_skip_verify: true` for this target, or the homelab root CA must be mounted into the VictoriaMetrics container. The homelab CA path is already available on the host at `/usr/local/share/ca-certificates/homelab-root.crt`.

---

## Network Reachability

VictoriaMetrics and Loki need to reach all segments. Inter-VLAN routing is handled by MikroTik. The MikroTik forward chain has **no inter-VLAN rules** — only WAN and parental-control rules targeting `bridgeLocal`. Traffic between vlan10-build, vlan20-mgmt, vlan30-edge, and vlan40-infra is unrestricted, which is already demonstrated by every stack reaching apt-cacher and Harbor across segments.

**No MikroTik firewall changes are required.** The following ports will be reachable from 192.168.20.12 as soon as the exporters are deployed:

| Port | Service | Stacks |
|------|---------|--------|
| 9100 | node_exporter | All LXCs |
| 8080 | cAdvisor | Docker stacks (except netbox-stack — see port conflict note below) |
| 8081 | cAdvisor (netbox-stack only) | netbox-stack exposes app metrics on :8080, so cAdvisor uses host port 8081 |
| 9153 | CoreDNS metrics | dns-stack |
| 8082 | Traefik metrics | proxy-stack |
| 9090 | Harbor metrics | harbor-stack — metrics disabled by default; must be enabled in `harbor.yml` |
| 9300 | Authentik metrics | authentik-stack — port not published in compose; must be added |
| 9443 | step-ca metrics (HTTPS) | step-ca-stack — TLS, needs CA or skip-verify in scrape config |
| 3100 | Loki ingest (from Promtail) | monitoring-stack receives only |

**Port conflict — netbox-stack**: NetBox's web service is published on `:8080`. cAdvisor also defaults to `:8080`. On netbox-stack, cAdvisor must be published on host port `8081` (`8081:8080`) to avoid the collision. VictoriaMetrics scrapes cAdvisor on netbox-stack at `:8081`.

**Authentik metrics not yet published**: The `server` container in `authentik-stack/docker-compose.yml` only publishes port `9000`. Port `9300` needs to be added and `AUTHENTIK_LISTEN__METRICS: "0.0.0.0:9300"` must be set in the Authentik server environment.

**Harbor metrics disabled**: The `harbor_installer` role's `harbor.yml.j2` template has no `metric:` block. Harbor metrics are off by default. The template needs a `metric: enabled: true, port: 9090` block added before Harbor exposes anything scrapeable.

**NetBox has no native Prometheus metrics**: NetBox does not expose `:8080/metrics` out of the box. The `django-prometheus` middleware must be added to the NetBox configuration (via `METRICS_ENABLED: true` in the netbox-docker stack) before VictoriaMetrics can scrape it. This is a prerequisite for that scrape job; see Phase 3 notes.

---

## What Gets Monitored

### Platform stacks

| Stack | Zone | node_exporter | cAdvisor | App metrics | Promtail |
|-------|------|:---:|:---:|---|:---:|
| dns-stack | mgmt_seg | ✓ | — | CoreDNS :9153 | ✓ (systemd) |
| step-ca-stack | mgmt_seg | ✓ | — | step-ca :9443/metrics | ✓ (systemd) |
| monitoring-stack | mgmt_seg | ✓ | ✓ | VM :8428, Loki :3100, Grafana :3000 | ✓ (already deployed) |
| portainer-stack | mgmt_seg | ✓ | ✓ | — | ✓ (Docker) |
| authentik-stack | mgmt_seg | ✓ | ✓ | Authentik :9300/metrics ⚠️ | ✓ (Docker) |
| proxy-stack | edge_seg | ✓ | ✓ | Traefik :8082/metrics | ✓ (Docker) |
| harbor-stack | infra_seg | ✓ | ✓ | Harbor :9090/metrics ⚠️ | ✓ (Docker) |
| apt-cacher-stack | infra_seg | ✓ | — | — | ✓ (systemd) |
| netbox-stack | infra_seg | ✓ | ✓ | NetBox :8080/metrics ⚠️ | ✓ (Docker) |
| ci-runner-01 | build_seg | ✓ | — | — | ✓ (systemd) |

**Proxmox host** (192.168.1.2 / pve.gibbsgreatly.xyz): node_exporter will be installed directly on the Proxmox host to monitor hypervisor-level CPU, memory, disk, and LXC/VM count. This is a manual one-time bootstrap, not managed by the LXC provisioning pipeline.

### Application metric endpoints

Where Prometheus scrape endpoints exist (or will be enabled), they will be scraped directly by VictoriaMetrics:

| Service | Endpoint | Ready? | Notes |
|---------|----------|--------|-------|
| CoreDNS | `:9153/metrics` | ✓ | Enabled by default in CoreDNS config |
| Traefik | `:8082/metrics` | ✓ | Enabled via `--metrics.prometheus` flag |
| Authentik | `:9300/metrics` | ✗ | Port not published; needs `AUTHENTIK_LISTEN__METRICS` env var + port 9300 added to compose |
| Harbor | `:9090/metrics` | ✗ | Metrics disabled by default; needs `metric.enabled: true` in `harbor.yml.j2` |
| NetBox | `:8080/metrics` | ✗ | Requires `django-prometheus`; needs `METRICS_ENABLED: true` in netbox-docker env |
| step-ca | `:9443/metrics` | ✓ | HTTPS; scrape requires homelab CA in VictoriaMetrics container |
| VictoriaMetrics (self) | `:8428/metrics` | ✓ | Always available |
| Loki (self) | `:3100/metrics` | ✓ | Always available |
| Grafana (self) | `:3000/metrics` | ✓ | Always available |

---

## Implementation Phases

### Phase 1 — node_exporter on all LXCs

**Goal**: Every managed LXC exposes OS metrics on :9100.

Tasks:
- Add a `node_exporter` role (new) that installs the node_exporter binary via apt or a downloaded release, creates a systemd unit, and starts it
- Apply the role from `lxc_base` using a conditional variable `monitoring_enabled: true` (default true) so it can be skipped for template/test containers
- Verify port 9100 is accessible from monitoring-stack after provisioning
- Re-provision all platform stacks to pick up the role

Role behaviour:
- Install `prometheus-node-exporter` from apt (available in Debian 13)
- Enable and start `prometheus-node-exporter.service`
- Expose metrics on all interfaces, port 9100
- No authentication needed — mgmt_seg firewall restricts access

### Phase 2 — cAdvisor on Docker stacks

**Goal**: Each Docker-based LXC exposes container-level CPU/memory/net/disk metrics on :8080.

Tasks:
- Add a `cadvisor` service to the Docker Compose definition in each Docker stack's deploy playbook (harbor, authentik, monitoring, netbox, proxy, portainer)
- Image: `gcr.io/cadvisor/cadvisor:v0.49.1` (pinned) — mirrored to Harbor as `harbor.lab.gibbsgreatly.xyz/dockerhub/cadvisor/cadvisor:v0.49.1`
- Mount `/:/rootfs:ro`, `/var/run:/var/run:ro`, `/sys:/sys:ro`, `/var/lib/docker:/var/lib/docker:ro`
- Port: `8080:8080` on all stacks **except** netbox-stack where it must be `8081:8080` (port conflict with NetBox web service on :8080)
- Restart policy: `unless-stopped`
- Harbor mirror must have the image available before stacks redeploy

### Phase 2a — Enable application metrics endpoints

**Goal**: Enable the Prometheus endpoints on Authentik, Harbor, and NetBox so that Phase 3 can scrape them.

**Authentik** (`stacks/authentik-stack/docker-compose.yml`):
- Add `- "9300:9300"` to the `server` service `ports` section
- Add `AUTHENTIK_LISTEN__METRICS: "0.0.0.0:9300"` to the `server` service `environment` block

**Harbor** (`ansible/roles/harbor_installer/templates/harbor.yml.j2`):
- Add the following block to the template:
  ```yaml
  metric:
    enabled: true
    port: 9090
    path: /metrics
  ```
- Re-run `deploy-harbor-stack.yml` to regenerate harbor configuration and restart Harbor

**NetBox** (`stacks/netbox-stack/docker-compose.yml`):
- Add `METRICS_ENABLED: "True"` to the `netbox` service environment block
- Note: `netbox-docker` v4.x includes `django-prometheus` and respects `METRICS_ENABLED`. Verify against the upstream `netbox-docker` changelog for the exact variable name.

### Phase 3 — VictoriaMetrics scrape config

**Goal**: VictoriaMetrics pulls metrics from all targets on a schedule.

Tasks:
- Write a `victoria-metrics/scrape.yml` (via Ansible template) to the monitoring-stack compose directory
- Mount the file into the VictoriaMetrics container at `/etc/vm/scrape.yml`
- Mount the homelab root CA into VictoriaMetrics at `/etc/ssl/certs/homelab-root.crt:ro` (needed for step-ca TLS scrape)
- Add `--promscrape.config=/etc/vm/scrape.yml` to the VictoriaMetrics `command` flags in the compose definition
- Scrape interval: 30s globally, 15s for Traefik/CoreDNS (higher-frequency services)

Scrape config template (use `lookup('env', 'LAB_IP_*')` variables — all already defined in `.env`):

```yaml
global:
  scrape_interval: 30s

scrape_configs:
  - job_name: node_exporter
    static_configs:
      - targets:
          - "{{ lookup('env', 'LAB_IP_AUTHENTIK') }}:9100"    # authentik-stack
          - "{{ lookup('env', 'LAB_IP_STEP_CA') }}:9100"      # step-ca-stack
          - "{{ lookup('env', 'LAB_IP_MONITORING') }}:9100"   # monitoring-stack (self)
          - "{{ lookup('env', 'LAB_IP_DNS') }}:9100"          # dns-stack
          - "{{ lookup('env', 'LAB_IP_PORTAINER') }}:9100"    # portainer-stack
          - "{{ lookup('env', 'LAB_IP_PROXY') }}:9100"        # proxy-stack
          - "{{ lookup('env', 'LAB_IP_HARBOR') }}:9100"       # harbor-stack
          - "{{ lookup('env', 'LAB_IP_APT_CACHER') }}:9100"  # apt-cacher-stack
          - "{{ lookup('env', 'LAB_IP_NETBOX') }}:9100"       # netbox-stack
          - "{{ lookup('env', 'LAB_IP_CI_RUNNER') }}:9100"   # ci-runner-01
          - "{{ lookup('env', 'LAB_IP_PROXMOX_HOST') }}:9100" # proxmox host (pve)

  - job_name: cadvisor
    static_configs:
      - targets:
          - "{{ lookup('env', 'LAB_IP_AUTHENTIK') }}:8080"    # authentik-stack
          - "{{ lookup('env', 'LAB_IP_MONITORING') }}:8080"   # monitoring-stack (self)
          - "{{ lookup('env', 'LAB_IP_PORTAINER') }}:8080"    # portainer-stack
          - "{{ lookup('env', 'LAB_IP_PROXY') }}:8080"        # proxy-stack
          - "{{ lookup('env', 'LAB_IP_HARBOR') }}:8080"       # harbor-stack
          - "{{ lookup('env', 'LAB_IP_NETBOX') }}:8081"       # netbox-stack (8081 — port conflict with NetBox app metrics)

  - job_name: coredns
    scrape_interval: 15s
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_DNS') }}:9153"]

  - job_name: traefik
    scrape_interval: 15s
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_PROXY') }}:8082"]

  - job_name: authentik
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_AUTHENTIK') }}:9300"]

  - job_name: harbor
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_HARBOR') }}:9090"]

  - job_name: step_ca
    scheme: https
    tls_config:
      ca_file: /etc/ssl/certs/homelab-root.crt
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_STEP_CA') }}:9443"]

  - job_name: netbox
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_NETBOX') }}:8080"]

  - job_name: victoriametrics
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_MONITORING') }}:8428"]

  - job_name: loki
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_MONITORING') }}:3100"]

  - job_name: grafana
    static_configs:
      - targets: ["{{ lookup('env', 'LAB_IP_MONITORING') }}:3000"]
```

All `LAB_IP_*` env vars are already present in `.env` except `LAB_IP_PROXMOX_HOST` (see Variables section).

**Note**: The scrape config must be written as an Ansible Jinja2 template file (`.j2`) so that `lookup('env', ...)` expressions are resolved at playbook runtime. Save it as `victoria-metrics/scrape.yml.j2` in the playbook's template search path and use `ansible.builtin.template` (not `copy`) to deploy it.

**Pre-requisites before Phase 3 scrape config will work:**
- Phase 1 (node_exporter) must be deployed on all targets
- Phase 2 (cAdvisor) must be deployed before cadvisor job targets will resolve
- Authentik port 9300 must be published (see Phase 2a)
- Harbor metrics must be enabled (see Phase 2a)
- NetBox `METRICS_ENABLED: true` must be set (see Phase 2a)

**Compose changes needed** (deploy-monitoring-stack.yml):
- Add `--promscrape.config=/etc/vm/scrape.yml` to VictoriaMetrics `command`
- Add volume mount: `./victoria-metrics/scrape.yml:/etc/vm/scrape.yml:ro`
- Add volume mount: `/usr/local/share/ca-certificates/homelab-root.crt:/etc/ssl/certs/homelab-root.crt:ro`
- Add directory creation task for `{{ monitoring_compose_dir }}/victoria-metrics`

### Phase 4 — Promtail on all stacks

**Goal**: Every LXC ships its logs to Loki.

**Docker stacks** (harbor, authentik, netbox, proxy, portainer):
- Add a `promtail` service to each stack's Docker Compose definition
- Config: push to `http://{{ lookup('env', 'LAB_IP_MONITORING') }}:3100/loki/api/v1/push` (via Ansible template)
- Collect `/var/log/**/*.log` with labels `job`, `host`, `stack`
- Also collect Docker container stdout/stderr via Docker log discovery using Promtail's `docker_sd_configs`
- Docker discovery requires `/var/run/docker.sock:/var/run/docker.sock:ro` volume mount
- Image: `grafana/promtail:3.0.0` (same version already used by monitoring-stack) — pulled from Harbor

**Non-Docker stacks** (dns-stack, step-ca-stack, apt-cacher-stack, ci-runner-01):
- Install Promtail binary as a systemd service via a new `promtail` Ansible role
- Config written to `/etc/promtail/config.yml`
- Same labels and Loki endpoint as above
- **dns-stack / apt-cacher-stack / ci-runner-01**: collect from `/var/log/**/*.log` + `journald` scrape config
- **step-ca-stack**: step-ca logs go to journal; no `/var/log` files. Use `journal` scrape source only
- Service: `promtail.service` enabled and started

**monitoring-stack** (self):
- Promtail already deployed and collecting from `/var/log/**/*.log`
- Extend config to add Docker discovery for the compose stack containers
- Requires adding `/var/run/docker.sock:/var/run/docker.sock:ro` volume to the `promtail` service in the monitoring compose definition

### Phase 5 — Grafana dashboards

**Goal**: Pre-provisioned dashboards in Grafana so the data is immediately useful after a fresh deploy.

Dashboards to provision via `grafana/provisioning/dashboards/`:

| Dashboard | Data source | Key panels |
|-----------|-------------|------------|
| Lab Overview | VictoriaMetrics | Per-host CPU %, memory %, disk % — all stacks in one view |
| Node Detail | VictoriaMetrics | Full node_exporter breakdown for a selected host |
| Docker Containers | VictoriaMetrics | cAdvisor: per-container CPU/mem/net/disk |
| Traefik Ingress | VictoriaMetrics | Request rate, p50/p99 latency, error rate per service |
| CoreDNS | VictoriaMetrics | Query rate, NXDOMAIN rate, cache hit %, latency |
| Authentik | VictoriaMetrics | Active sessions, auth event rate, provider health |
| Harbor | VictoriaMetrics | Pull/push rate, replication job status |
| Lab Logs | Loki | Full-stack log explorer, filterable by host/stack/severity |
| Auth Logs | Loki | SSH logins, sudo, auth.log across all hosts |

Dashboards will be stored as JSON files in `terraform/lxc/stacks/monitoring-stack/dashboards/` and deployed by the monitoring playbook.

**Compose/playbook changes needed** (deploy-monitoring-stack.yml):
- Add directory creation tasks for `{{ monitoring_compose_dir }}/grafana/provisioning/dashboards` and `{{ monitoring_compose_dir }}/grafana/dashboards`
- Add a Grafana dashboard provider config to `{{ monitoring_compose_dir }}/grafana/provisioning/dashboards/providers.yml`:
  ```yaml
  apiVersion: 1
  providers:
    - name: homelab
      type: file
      options:
        path: /etc/grafana/dashboards
  ```
- Copy JSON dashboard files from `stacks/monitoring-stack/dashboards/*.json` into `{{ monitoring_compose_dir }}/grafana/dashboards/`
- Add volume mount to Grafana container: `./grafana/dashboards:/etc/grafana/dashboards:ro`

---

## Variables and Secrets

New env vars needed (add to `.env` and `.env.template`):

```
LAB_IP_PROXMOX_HOST=192.168.1.2    # Proxmox bare-metal host — for node_exporter scrape
```

All other `LAB_IP_*` variables required by the scrape config are **already present** in `.env`.

No new secrets required. Loki and VictoriaMetrics have no auth (`auth_enabled: false` in Loki; VictoriaMetrics has no auth by default). This is acceptable since both are mgmt_seg-internal.

---

## Loki Retention

The current Loki config has no retention period set. Add a `compactor` block and `retention_period` to the Loki config in `deploy-monitoring-stack.yml`:

```yaml
compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150

limits_config:
  allow_structured_metadata: false
  volume_enabled: true
  retention_period: 30d    # adjust as needed; 30d is a reasonable lab default
```

Note: Loki filesystem compactor with retention requires Loki >= 2.9. The current deployment uses `3.0.0` so this is supported.

---

## Health Gate Updates

After implementation, the teardown-deploy-test cycle health check for monitoring-stack should be extended:

```bash
# current
curl -fsS 'http://${ip}:3000/login' && curl -fsS 'http://${ip}:8428/-/ready'

# target (post Phase 3)
curl -fsS 'http://${ip}:3000/login' \
  && curl -fsS 'http://${ip}:8428/-/ready' \
  && curl -fsS 'http://${ip}:3100/ready' \
  && curl -fsS "http://${ip}:8428/api/v1/targets" | python3 -c "import sys,json; t=json.load(sys.stdin); up=[x for x in t['data']['activeTargets'] if x['health']=='up']; print(len(up),'targets up'); sys.exit(0 if len(up)>0 else 1)"
```

The final check verifies at least one scrape target is healthy — confirming the scrape config is loaded and working, not just that VictoriaMetrics started.

---

## Task Breakdown

| # | Task | Phase | Scope |
|---|------|-------|-------|
| 1 | New `node_exporter` Ansible role; apply from `lxc_base` | 1 | Role creation |
| 2 | Re-provision all platform stacks to deploy node_exporter | 1 | Ansible |
| 3 | Install node_exporter on Proxmox host directly (one-time, manual) | 1 | Bootstrap |
| 4 | Add `LAB_IP_PROXMOX_HOST` to `.env` and `.env.template` | 1 | Config |
| 5 | Mirror `cadvisor/cadvisor:v0.49.1` into Harbor | 2 | Harbor |
| 6 | Add cAdvisor service to Docker Compose in each Docker stack playbook | 2 | 6 playbooks |
| 7 | Use port `8081:8080` for cAdvisor on netbox-stack (port conflict) | 2 | netbox playbook |
| 7a | Publish Authentik port 9300 + set `AUTHENTIK_LISTEN__METRICS` env var | 2a | authentik compose |
| 7b | Add `metric.enabled: true, port: 9090` to Harbor `harbor.yml.j2` template | 2a | harbor role |
| 7c | Add `METRICS_ENABLED: True` to NetBox compose environment | 2a | netbox compose |
| 8 | Write VictoriaMetrics scrape config template; update monitoring compose | 3 | Ansible |
| 9 | Add homelab CA volume mount to VictoriaMetrics container (for step-ca TLS) | 3 | Ansible |
| 10 | Add `--promscrape.config` flag to VictoriaMetrics command in compose | 3 | Ansible |
| 11 | Validate VictoriaMetrics scrape targets via `/api/v1/targets` | 3 | Manual + health gate |
| 12 | Add Loki retention config (compactor + `retention_period: 30d`) to monitoring deploy | 3 | Ansible |
| 13 | New `promtail` Ansible role for systemd-based stacks (with journald support) | 4 | Role creation |
| 14 | Add Promtail Docker service to each Docker stack playbook (with docker.sock mount) | 4 | 5 playbooks |
| 15 | Extend monitoring-stack Promtail config with Docker discovery + docker.sock mount | 4 | Ansible |
| 16 | Validate Loki is receiving streams (`/loki/api/v1/labels`) | 4 | Manual |
| 17 | Create dashboard JSON files in `stacks/monitoring-stack/dashboards/` | 5 | Grafana |
| 18 | Add dashboard provider config and volume mount to monitoring compose | 5 | Ansible |
| 19 | Update teardown health gate to check Loki `/ready` and VM target count | — | `teardown-deploy-test.sh` |
