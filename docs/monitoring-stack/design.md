# Monitoring Stack — Design

## Overview

The monitoring-stack LXC (192.168.20.12, `mgmt_seg`) runs VictoriaMetrics, VictoriaLogs, Grafana, and Promtail via Docker Compose. Grafana is the sole browser-facing service (via Traefik + Authentik). VictoriaMetrics and VictoriaLogs are internal-only data stores.

---

## Location

| | |
|---|---|
| VMID | 20012 |
| Zone | mgmt_seg (192.168.20.12) |
| URL | https://grafana.lab.gibbsgreatly.xyz |
| Auth | Authentik OIDC |
| RAM | 1536 MB |
| Docker mount | 52 GB at `/var/lib/docker` (`infrastructure-containers:subvol-20012-disk-1`) |

---

## Current State

**Phases 1–5 complete; Phase 6 (VictoriaLogs) implemented, pending pve-test smoke test.**

### Running services

| Service | Port | Notes |
|---------|------|-------|
| VictoriaMetrics | `:8428` | `--retentionPeriod=90d`; scrape config at `/etc/vm/scrape.yml` |
| VictoriaLogs | `:9428` | `--retentionPeriod=30d`; named Docker volume on `/var/lib/docker` mount; `v1.24.0-victorialogs` |
| Grafana | `:3000` | OAuth via Authentik; `victoriametrics-logs-datasource` plugin installed |
| Promtail (self) | — | Docker discovery + `/var/log` on monitoring-stack; pushes to VictoriaLogs |

### Active scrape targets

| Job | Instance | Status |
|-----|----------|--------|
| node_exporter | all 10 managed LXCs | ✅ up |
| node_exporter | 192.168.1.2 (Proxmox host) | ❌ down — node_exporter not installed on bare-metal host |
| cadvisor | authentik, monitoring, portainer, proxy, harbor, netbox stacks | ✅ up |
| coredns | 192.168.20.13:9153 | ✅ up |
| traefik | 192.168.30.10:8082 | ✅ up |
| authentik | 192.168.20.10:9300 | ✅ up |
| harbor-exporter | 192.168.40.10:9090 | ✅ up |
| harbor-core | 192.168.40.10:9090?comp=core | ✅ up |
| harbor-registry | 192.168.40.10:9090?comp=registry | ✅ up |
| harbor-jobservice | 192.168.40.10:9090?comp=jobservice | ✅ up |
| harbor-findings-exporter | monitoring-stack internal | ✅ up |
| netbox | 192.168.40.12:8080 | ✅ up |
| victoriametrics | 192.168.20.12:8428 | ✅ up |
| victorialogs | 192.168.20.12:9428 | ⏳ pending smoke test |
| grafana | 192.168.20.12:3000 | ✅ up |
| step-ca | — | ❌ not deployed — TLS complexity deferred (see Remaining Work) |

### Deployed dashboards

| Dashboard | Notes |
|-----------|-------|
| Lab Overview | Per-host CPU/mem/disk across all stacks |
| Node Detail | Full node_exporter breakdown for selected stack |
| Docker Containers | Per-container CPU/mem/net/disk (cAdvisor) |
| Traefik Ingress | Request rate, latency, error rate |
| CoreDNS | Query rate, NXDOMAIN rate, cache hit % |
| Harbor Operations | Component health, queue state, proxy-cache activity |
| Harbor Scan Coverage | Findings exporter health, scan coverage, severity totals |
| Harbor CVE Inventory | Detailed CVE rows from the live Harbor findings feed |
| Lab Logs | Full-stack log explorer (VictoriaLogs / LogsQL) |
| Auth Logs | SSH/sudo/auth.log across all hosts (VictoriaLogs / LogsQL) |

### Notable deviations from original plan

- **Stack labels**: Both `node_exporter` and `cadvisor` use per-target `static_configs` with `labels: {stack: <name>}` rather than flat IP lists.
- **Traefik metrics**: Added `metrics: prometheus` block on `:8082` post-deploy when Traefik Ingress dashboard showed no data.
- **step-ca scrape job**: Deferred — TLS complexity (homelab CA mount into VictoriaMetrics).
- **Scrape config written inline**: `deploy-monitoring-stack.yml` writes scrape config via `ansible.builtin.copy` with inline `content:` block, not a separate `.j2` template.

### Post-deploy fixes

| Fix | Commit |
|-----|--------|
| `grafana` DNS record pointed to monitoring IP instead of proxy | d7c8a8d |
| `portainer` and `netbox` DNS A records missing from seed zone | 14003fa |
| `provision.sh` regenerates CoreDNS zone before dns-stack deploy | 90f9ead |
| Traefik metrics endpoint not configured | d884991 |
| node_exporter and cadvisor scrape jobs had no stack labels | d884991, 9cc83dc |
| `notify: Restart VictoriaMetrics` placed inside `content: \|` block | 9cc83dc |
| `docker-containers.json` and `node-detail.json` used `instance` variable | d884991, 9cc83dc |

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

**Metrics flow**: VictoriaMetrics scrapes node_exporter (:9100) and cAdvisor (:8080) on each LXC, plus application metrics endpoints directly. Pull model — VictoriaMetrics initiates all scrapes.

**Log flow**: Promtail on each LXC pushes to Loki at `http://192.168.20.12:3100/loki/api/v1/push`. Docker stacks run Promtail as a Docker container; non-Docker stacks run it as a systemd service.

---

## Network Reachability

Inter-VLAN routing via MikroTik. No firewall changes required — the forward chain has no inter-VLAN rules, so all VLAN segments can reach monitoring-stack freely.

| Port | Service | Notes |
|------|---------|-------|
| 9100 | node_exporter | All LXCs |
| 8080 | cAdvisor | Docker stacks |
| 8081 | cAdvisor (netbox-stack only) | Port conflict with NetBox app on :8080 |
| 9153 | CoreDNS metrics | dns-stack |
| 8082 | Traefik metrics | proxy-stack |
| 9090 | Harbor metrics | harbor-stack |
| 9300 | Authentik metrics | authentik-stack |
| 9443 | step-ca metrics (HTTPS) | step-ca-stack — TLS, needs CA or skip-verify |
| 3100 | Loki ingest | monitoring-stack receives from Promtail agents |

---

## What Gets Monitored

### Platform stacks

| Stack | Zone | node_exporter | cAdvisor | App metrics | Promtail |
|-------|------|:---:|:---:|---|:---:|
| dns-stack | mgmt_seg | ✓ | — | CoreDNS :9153 | ✓ (systemd) |
| step-ca-stack | mgmt_seg | ✓ | — | step-ca :9443/metrics | ✓ (systemd) |
| monitoring-stack | mgmt_seg | ✓ | ✓ | VM :8428, Loki :3100, Grafana :3000 | ✓ |
| portainer-stack | mgmt_seg | ✓ | ✓ | — | ✓ (Docker) |
| authentik-stack | mgmt_seg | ✓ | ✓ | Authentik :9300/metrics | ✓ (Docker) |
| proxy-stack | edge_seg | ✓ | ✓ | Traefik :8082/metrics | ✓ (Docker) |
| harbor-stack | infra_seg | ✓ | ✓ | Harbor :9090/metrics | ✓ (Docker) |
| apt-cacher-stack | infra_seg | ✓ | — | — | ✓ (systemd) |
| netbox-stack | infra_seg | ✓ | ✓ | NetBox :8080/metrics | ✓ (Docker) |
| ci-runner-01 | build_seg | ✓ | — | — | ✓ (systemd) |

**Proxmox host** (192.168.1.2): node_exporter must be installed manually — not managed by LXC provisioning pipeline.

### Application metrics endpoints

| Service | Endpoint | Ready? | Notes |
|---------|----------|--------|-------|
| CoreDNS | `:9153/metrics` | ✓ | |
| Traefik | `:8082/metrics` | ✓ | |
| Authentik | `:9300/metrics` | ✓ | |
| Harbor | `:9090/metrics` | ✓ | |
| NetBox | `:8080/metrics` | ✓ | |
| step-ca | `:9443/metrics` | ✗ | HTTPS — needs homelab CA in VictoriaMetrics container |
| VictoriaMetrics | `:8428/metrics` | ✓ | |
| Loki | `:3100/metrics` | ✓ | |
| Grafana | `:3000/metrics` | ✓ | |

---

## How to Provision

```bash
./with-secrets scripts/provision.sh --stack monitoring-stack
```

This is a pve-test-only operation during development. For production (`pve`), use `./with-secrets-prod` with `TASK_APPROVAL` set (see [Production Credentials Reference](../reference/production-credentials.md)).

On pve-test, the full stack must already be up (harbor-stack, authentik-stack, proxy-stack, dns-stack) before monitoring-stack can be provisioned — it pulls images from Harbor and reconciles an Authentik OIDC client during provisioning.

---

## Variables and Secrets

```
LAB_IP_PROXMOX_HOST=192.168.1.2    # Proxmox bare-metal host — for node_exporter scrape
```

All other `LAB_IP_*` variables are in `.env`. Secrets (Grafana admin password, OAuth client secret, Harbor admin password, Authentik API token) are in `secrets.enc.yaml` and loaded by `./with-secrets`. See [STACK_CONTRACT.md](../../terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md) for the full inputs list.

No secrets are required for VictoriaLogs or VictoriaMetrics (both are mgmt_seg-internal, no auth).

---

## Remaining Work

| Item | Notes |
|------|-------|
| Proxmox host node_exporter | Manual bootstrap — install node_exporter directly on 192.168.1.2 |
| step-ca scrape job | Mount homelab CA into VictoriaMetrics container; add `scheme: https` + `tls_config.ca_file` to scrape config |
| Authentik dashboard | Metrics scraped but no Grafana dashboard built |
| Harbor alerting | CVE/operations dashboards live; alert rules not defined |
| VictoriaLogs smoke test | Provision pve-test and verify ingestion via `/select/logsql/query?query=*`; tune dashboard queries post-deploy if needed |

---

## Teardown Health Gate

The monitoring-stack health check in `teardown-deploy-test.sh` asserts Grafana, VictoriaMetrics, and VictoriaLogs are all responding:

```bash
curl -fsS "http://${ip}:3000/login" && \
curl -fsS "http://${ip}:8428/-/ready" && \
curl -fsS "http://${ip}:9428/health"
```

---

## Phase 6 — VictoriaLogs

### Goal

Replace Loki with VictoriaLogs for full-text log search and a per-source LLM analysis pipeline.

**Why replace Loki**: Loki indexes only labels, not log content. Full-text search requires a scan query that degrades with volume. VictoriaLogs indexes content and supports fast substring and field-extraction queries via LogsQL. It is from the VictoriaMetrics team (same operational patterns, already in the stack), runs as a single container, and stores data as a Docker volume on the existing 52 GB `/var/lib/docker` mount — no second LXC mount required.

### Design

```
                         monitoring-stack (192.168.20.12)
                         ┌──────────────────────────────────────────┐
                         │  VictoriaMetrics  VictoriaLogs  Grafana  │
 Promtail (per stack) ───►  (metrics)        :9428         :3000    │
                         │                       ▲                  │
                         │              LLM analysis pipeline        │
                         │              (query API → Claude API)     │
                         └──────────────────────────────────────────┘
```

VictoriaLogs exposes a Loki-compatible ingest endpoint at `/insert/loki/api/v1/push`, so all existing Promtail agents redirect with a single URL change. LogsQL queries are issued against `/select/logsql/query`.

### VictoriaLogs container

```yaml
victorialogs:
  image: docker.io/victoriametrics/victoria-logs:v1-victorialogs
  ports:
    - "9428:9428"
  volumes:
    - victorialogs-data:/vlogs
  command:
    - -storageDataPath=/vlogs
    - -retentionPeriod=30d
  restart: unless-stopped
```

Data stored in a named Docker volume — lives on the existing `/var/lib/docker` mount. No additional LXC mount point needed.

### Migration path

1. Add VictoriaLogs container to monitoring-stack compose (alongside Loki initially)
2. Add VictoriaLogs Grafana datasource plugin (`victoriametrics-logs-datasource`)
3. Update all Promtail configs to push to VictoriaLogs: change `url` from `http://192.168.20.12:3100/loki/api/v1/push` to `http://192.168.20.12:9428/insert/loki/api/v1/push`
4. Rebuild Lab Logs and Auth Logs dashboards using VictoriaLogs datasource + LogsQL
5. Verify log ingestion and dashboard queries
6. Remove Loki container and volumes

### LLM analysis pipeline

A lightweight script (or small service) that fetches recent logs for a named source and sends them to the Claude API for analysis. Query pattern:

```bash
# Fetch last N lines from a stream and pipe to LLM
curl -G "http://192.168.20.12:9428/select/logsql/query" \
  --data-urlencode 'query=_stream:{stack="harbor-stack"} | limit 200' \
  | <send to Claude API>
```

LogsQL stream selectors map directly to the `stack` and `job` labels already set by Promtail, so per-source retrieval is precise and fast.

Implementation: a small Python script invoked ad-hoc (or triggered via Grafana panel button). Kept outside the monitoring-stack compose definition — it's a tooling concern, not an infrastructure service.

### Tasks

| # | Task | Status |
|---|------|--------|
| 1 | Pin VictoriaLogs release version | ✅ `v1.24.0-victorialogs` |
| 2 | Mirror VictoriaLogs image to Harbor | ✅ via `dockerhub/` proxy cache — no explicit push needed |
| 3 | Add `victoriametrics-logs-datasource` Grafana plugin | ✅ `GF_INSTALL_PLUGINS` |
| 4 | Add VictoriaLogs service to compose; remove Loki | ✅ port 9428, 30d retention, named volume |
| 5 | Add VictoriaLogs datasource to Grafana provisioning | ✅ uid=VictoriaLogs |
| 6 | Update Promtail push URL across all stacks | ✅ all 9 stacks: `:9428/insert/loki/api/v1/push` |
| 7 | Rebuild Lab Logs and Auth Logs dashboards with LogsQL | ✅ `field_values()` vars, `stats count()` timeseries |
| 8 | Verify ingestion | ⏳ requires pve-test provision |
| 9 | Write LLM analysis script | ✅ `scripts/victorialogs-analyze.py` |
| 10 | Update teardown health gate | ✅ `:9428/health` added to monitoring-stack check |
| 11 | Provision + smoke test on pve-test | ⏳ gate for promotion to baseline |

### Branch

`work/victorialogs` — rebased onto PR #384 (portainer-teardown-restore)

Promotion gate: full teardown + redeploy cycle on pve-test confirms log ingestion resumes and all dashboards show data after rebuild.
