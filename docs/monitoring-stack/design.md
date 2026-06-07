# Monitoring Stack — Design

## Overview

The monitoring-stack LXC (192.168.20.12, `mgmt_seg`) runs VictoriaMetrics, Loki, Grafana, and Promtail via Docker Compose. Grafana is the sole browser-facing service (via Traefik + Authentik). VictoriaMetrics and Loki are internal-only data stores — they receive data from agents and are queried by Grafana.

Currently none of the other stacks ship metrics or logs. This document defines what will be collected, how, and in what order.

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

---

## Network Reachability

VictoriaMetrics and Loki need to reach all segments. Inter-VLAN routing is handled by MikroTik. The MikroTik forward chain has **no inter-VLAN rules** — only WAN and parental-control rules targeting `bridgeLocal`. Traffic between vlan10-build, vlan20-mgmt, vlan30-edge, and vlan40-infra is unrestricted, which is already demonstrated by every stack reaching apt-cacher and Harbor across segments.

**No MikroTik firewall changes are required.** The following ports will be reachable from 192.168.20.12 as soon as the exporters are deployed:

| Port | Service | Stacks |
|------|---------|--------|
| 9100 | node_exporter | All LXCs |
| 8080 | cAdvisor | Docker stacks |
| 9153 | CoreDNS metrics | dns-stack |
| 8082 | Traefik metrics | proxy-stack |
| 9300 | Harbor / Authentik metrics | harbor-stack, authentik-stack |
| 9443 | step-ca metrics | step-ca-stack |
| 3100 | Loki ingest (from Promtail) | monitoring-stack receives only |

---

## What Gets Monitored

### Platform stacks

| Stack | Zone | node_exporter | cAdvisor | App metrics | Promtail |
|-------|------|:---:|:---:|---|:---:|
| dns-stack | mgmt_seg | ✓ | — | CoreDNS :9153 | ✓ (systemd) |
| step-ca-stack | mgmt_seg | ✓ | — | step-ca :9443/metrics | ✓ (systemd) |
| monitoring-stack | mgmt_seg | ✓ | ✓ | VM :8428, Loki :3100, Grafana :3000 | ✓ (already deployed) |
| portainer-stack | mgmt_seg | ✓ | ✓ | — | ✓ (Docker) |
| authentik-stack | mgmt_seg | ✓ | ✓ | Authentik :9300/metrics | ✓ (Docker) |
| proxy-stack | edge_seg | ✓ | ✓ | Traefik :8082/metrics | ✓ (Docker) |
| harbor-stack | infra_seg | ✓ | ✓ | Harbor :9300/metrics | ✓ (Docker) |
| apt-cacher-stack | infra_seg | ✓ | — | — | ✓ (systemd) |
| netbox-stack | infra_seg | ✓ | ✓ | NetBox :8080/metrics | ✓ (Docker) |
| ci-runner-01 | build_seg | ✓ | — | — | ✓ (systemd) |

**Proxmox host** (192.168.1.2 / pve.gibbsgreatly.xyz): node_exporter will be installed directly on the Proxmox host to monitor hypervisor-level CPU, memory, disk, and LXC/VM count. This is a manual one-time bootstrap, not managed by the LXC provisioning pipeline.

### Application metric endpoints

Where built-in Prometheus scrape endpoints already exist, they will be scraped directly by VictoriaMetrics with no sidecar needed:

- **CoreDNS** — `:9153/metrics` — query counts, error rates, cache hit rate
- **Traefik** — `:8082/metrics` — request rate, latency, error rate per router/service
- **Authentik** — `:9300/metrics` — active sessions, failed logins, provider health
- **Harbor** — `:9300/metrics` — registry pull/push counts, replication status
- **step-ca** — `:9443/metrics` — certificate issuance/renewal rate, ACME requests
- **VictoriaMetrics** (self) — `:8428/metrics`
- **Loki** (self) — `:3100/metrics`
- **Grafana** (self) — `:3000/metrics`

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
- Image: `gcr.io/cadvisor/cadvisor:latest` (pinned version) — pulled from Harbor mirror
- Mount `/:/rootfs:ro`, `/var/run:/var/run:ro`, `/sys:/sys:ro`, `/var/lib/docker:/var/lib/docker:ro`
- Port: `8080:8080`
- Restart policy: `unless-stopped`
- Harbor mirror must have the image available before stacks redeploy

### Phase 3 — VictoriaMetrics scrape config

**Goal**: VictoriaMetrics pulls metrics from all targets on a schedule.

Tasks:
- Write a `victoria-metrics/scrape.yml` (via Ansible template) to the monitoring-stack compose directory
- Mount the file into the VictoriaMetrics container
- Add `--promscrape.config=/etc/vm/scrape.yml` to the VictoriaMetrics command flags
- Scrape interval: 30s globally, 15s for Traefik/CoreDNS (higher-frequency services)

Scrape config structure:

```yaml
global:
  scrape_interval: 30s

scrape_configs:
  - job_name: node_exporter
    static_configs:
      - targets:
          - 192.168.20.10:9100   # authentik-stack
          - 192.168.20.11:9100   # step-ca-stack
          - 192.168.20.12:9100   # monitoring-stack (self)
          - 192.168.20.13:9100   # dns-stack
          - 192.168.20.20:9100   # portainer-stack
          - 192.168.30.10:9100   # proxy-stack
          - 192.168.40.10:9100   # harbor-stack
          - 192.168.40.11:9100   # apt-cacher-stack
          - 192.168.40.12:9100   # netbox-stack
          - 192.168.10.63:9100   # ci-runner-01
          - 192.168.1.2:9100     # proxmox host (pve)
        labels:
          job: node_exporter

  - job_name: cadvisor
    static_configs:
      - targets:
          - 192.168.20.10:8080   # authentik-stack
          - 192.168.20.12:8080   # monitoring-stack (self)
          - 192.168.20.20:8080   # portainer-stack
          - 192.168.30.10:8080   # proxy-stack
          - 192.168.40.10:8080   # harbor-stack
          - 192.168.40.12:8080   # netbox-stack

  - job_name: coredns
    scrape_interval: 15s
    static_configs:
      - targets: [192.168.20.13:9153]

  - job_name: traefik
    scrape_interval: 15s
    static_configs:
      - targets: [192.168.30.10:8082]

  - job_name: authentik
    static_configs:
      - targets: [192.168.20.10:9300]

  - job_name: harbor
    static_configs:
      - targets: [192.168.40.10:9300]

  - job_name: victoriametrics
    static_configs:
      - targets: [192.168.20.12:8428]

  - job_name: loki
    static_configs:
      - targets: [192.168.20.12:3100]

  - job_name: grafana
    static_configs:
      - targets: [192.168.20.12:3000]
```

The IPs in the scrape config must be sourced from Ansible variables (not hardcoded literals) to stay in sync with `.env` values. Use `lookup('env', 'LAB_IP_*')` variables, same pattern as the rest of the stack.

### Phase 4 — Promtail on all stacks

**Goal**: Every LXC ships its logs to Loki.

**Docker stacks** (harbor, authentik, netbox, proxy, portainer):
- Add a `promtail` service to each stack's Docker Compose definition
- Config: push to `http://192.168.20.12:3100/loki/api/v1/push`
- Collect `/var/log/**/*.log` with labels `job`, `host`, `stack`
- Also collect Docker container stdout/stderr via Docker log discovery using Promtail's `docker_sd_configs`
- Image: `grafana/promtail:3.0.0` (same version already used by monitoring-stack) — pulled from Harbor

**Non-Docker stacks** (dns-stack, step-ca-stack, apt-cacher-stack, ci-runner-01):
- Install Promtail binary as a systemd service via a new `promtail` Ansible role
- Config written to `/etc/promtail/config.yml`
- Same labels and Loki endpoint as above
- Service: `promtail.service` enabled and started

**monitoring-stack** (self):
- Promtail already deployed and collecting from `/var/log/**/*.log`
- Extend to also use Docker discovery for the compose stack containers

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

Dashboards will be stored as JSON files in `terraform/lxc/stacks/monitoring-stack/dashboards/` and deployed by the monitoring playbook via a provisioning volume mount.

---

## Variables and Secrets

New env vars needed (add to `.env` and `.env.template`):

```
LAB_IP_PROXMOX_HOST=192.168.1.2    # Proxmox bare-metal host — for node_exporter scrape
```

No new secrets required. Loki and VictoriaMetrics have no auth (`auth_enabled: false` in Loki; VictoriaMetrics has no auth by default). This is acceptable since both are mgmt_seg-internal.

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
| 4 | Add cAdvisor service to Docker Compose in each Docker stack playbook | 2 | 6 playbooks |
| 5 | Pull cAdvisor image into Harbor mirror | 2 | Harbor |
| 6 | Write VictoriaMetrics scrape config template; update monitoring compose | 3 | Ansible |
| 7 | Validate VictoriaMetrics scrape targets via `/api/v1/targets` | 3 | Manual + health gate |
| 8 | New `promtail` Ansible role for systemd-based stacks | 4 | Role creation |
| 9 | Add Promtail Docker service to each Docker stack playbook | 4 | 5 playbooks |
| 10 | Extend monitoring-stack Promtail config with Docker discovery | 4 | Ansible |
| 11 | Validate Loki is receiving streams (`/loki/api/v1/labels`) | 4 | Manual |
| 12 | Create dashboard JSON files; add provisioning mount to monitoring compose | 5 | Grafana |
| 13 | Update teardown health gate to check Loki `/ready` and VM target count | — | `teardown-deploy-test.sh` |
