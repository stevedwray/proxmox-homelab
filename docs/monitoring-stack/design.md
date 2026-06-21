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

**Phases 1–6 complete on pve. Phase 7 (syslog-based log collection) in progress — additive infrastructure deployed on pve (2026-06-21), Promtail removal and dashboard rebuild pending.**

### Running services

| Service | Port | Notes |
|---------|------|-------|
| VictoriaMetrics | `:8428` | `--retentionPeriod=90d`; scrape config at `/etc/vm/scrape.yml` |
| VictoriaLogs | `:9428`, `:5140` | `--retentionPeriod=30d`; syslog TCP input on `:5140`; named Docker volume on `/var/lib/docker` mount; `v1.24.0-victorialogs` |
| Grafana | `:3000` | OAuth via Authentik; `victoriametrics-logs-datasource` plugin installed |
| Promtail (self) | — | Still running pending Phase 7C removal; will be removed once syslog collection is verified |

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
| 5140 | VictoriaLogs syslog TCP | monitoring-stack receives RFC 5424 from rsyslog on all LXCs |

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
| VictoriaLogs smoke test | Provision pve-test and verify ingestion via `/select/logsql/query?query=*` after Phase 7 syslog collection is in place |

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

### Known limitations (current Promtail approach)

The Promtail-based collection scrapes Docker container stdout/stderr via the Docker socket and ships raw lines to VictoriaLogs. This bypasses the syslog transport layer entirely, meaning:

- **No facilities** — all logs arrive without RFC 5424 facility classification
- **No reliable severity** — containers write plain text or application-specific JSON to stdout; severity must be inferred by heuristic regex, which silently misfires on services that don't embed level keywords
- **Host attribution is fragile** — Promtail sets a `host` stream label from `relabel_configs`, but VictoriaLogs auto-parses JSON bodies and surfaces any `host` key found there (e.g. HTTP Host headers, bind addresses) alongside the transport label, polluting the host field
- **App-specific workarounds compound** — `?_msg_field=event` for authentik, per-stack `replace` pipeline stages, dashboard regex filters: each is a patch on a structural problem

These limitations are inherent to scraping stdout rather than using the syslog protocol. Phase 7 addresses this properly.

### Branch

`work/victorialogs` — rebased onto PR #384 (portainer-teardown-restore)

Promotion gate: full teardown + redeploy cycle on pve-test confirms log ingestion resumes and all dashboards show data after rebuild.

---

## Phase 7 — syslog-based log collection

### Motivation

The Promtail stdout-scraping approach (Phase 6) does not model logs correctly. Syslog is the established Unix log transport: it carries facility (what kind of process), severity (how important), hostname (transport-layer, not application-set), and a process tag — all as structured header fields, separate from the message body. These have been defined in the protocol since RFC 3164 (1984) and formalised in RFC 5424 (2009).

Replacing Promtail with rsyslog-based collection restores this model: the syslog envelope is authoritative, severity filtering is real, and host attribution is clean by design.

### Research findings

These facts were confirmed before writing this plan and should not be re-investigated during implementation.

**rsyslog**
- rsyslog is **not** currently installed on any LXC host. All hosts show `un rsyslog` (uninstalled, never configured).
- rsyslog **8.2504.0-1** is available in apt on Debian 12 (very recent, 2025-04). No backports or third-party repos needed.
- Modules needed: `omfwd` (TCP forwarding — built into the base package), `imuxsock` (receives from `/dev/log` — built in), `imjournal` (reads journald — built in). There is no separate `rsyslog-module-imtcp` package; TCP input is built into the base `rsyslog` package.
- The `rsyslog-docker` package exists in apt but is for enriching logs with Docker container metadata — not required for our approach since we use the Docker syslog driver.

**VictoriaLogs syslog input**
- Confirmed present in v1.24.0. Flags verified via `docker run --rm ... -help`.
- `-syslog.listenAddr.tcp=:5140` enables TCP listener. UDP also available.
- `-syslog.streamFields.tcp=hostname,appname,facility` controls which syslog header fields become VictoriaLogs stream labels (indexed for fast filtering).
- `-syslog.extraFields.tcp=...` adds arbitrary static metadata to all ingested messages.
- Both RFC 3164 and RFC 5424 are parsed. Timezone handling is configurable for RFC 3164.
- No compression needed for LAN-local traffic.
- The existing VictoriaLogs container currently runs with only `-storageDataPath=/vlogs -retentionPeriod=30d`. Port 5140 is not yet exposed.

**Network reachability**
- Port 5140 will work: all stacks already push to monitoring-stack:9428 successfully, which uses the same inter-VLAN routing. No new firewall rules are required.
- VictoriaLogs container will need port 5140 mapped in the Docker compose definition.

**Promtail deployment inventory**

There are three distinct Promtail patterns in use, each requiring a different removal approach:

| Pattern | Stacks | How deployed |
|---------|--------|-------------|
| Docker container in stack compose (inline) | portainer-stack, proxy-stack, netbox-stack, monitoring-stack | Compose written inline in playbook `content:` block; Promtail has `/var/log` and `/var/run/docker.sock` mounts |
| Docker container in static compose file | authentik-stack | Compose is a static file at `terraform/lxc/stacks/authentik-stack/docker-compose.yml` checked into the repo; Promtail defined there |
| systemd service via `promtail` role | harbor-stack, apt-cacher-stack, dns-stack (coredns), step-ca-stack, ci-runner-01 | `promtail` Ansible role installs via Grafana apt repo, writes config from `config.yml.j2` template, manages systemd unit |

**Harbor special case**
- Harbor installs its own containers via a separate installer at `/opt/harbor/`. The installer writes its own `docker-compose.yml` which we do not control.
- Harbor's Promtail is a **systemd** service (role-based, same as apt-cacher/dns/step-ca), not a container in Harbor's compose. So Harbor container logs currently flow via Docker socket scraping by this systemd Promtail.
- After Phase 7: Harbor container logs need to reach rsyslog. **Decision required** — see Decision 3 below.

**step-ca special case**
- Promtail on step-ca uses `promtail_scrape_varlogs: false` and `promtail_scrape_journal: true`, meaning it reads from systemd journal rather than `/var/log`. This was set because step-ca logs to journal rather than to files.
- With rsyslog: step-ca's journal entries are naturally readable by rsyslog's `imjournal` module. This is actually cleaner — no special-casing needed.

**App-native syslog support audit**

| Service | Stack | Native syslog support | Notes |
|---------|-------|-----------------------|-------|
| nginx (direct_tls) | authentik-stack | ✓ | `error_log syslog:server=/dev/log;` / `access_log syslog:...` |
| postgres | authentik-stack | ✓ | `log_destination = 'syslog'` in postgresql.conf — but requires mount into container or env var |
| redis | authentik-stack | ✓ | `syslog-enabled yes` in redis.conf — but requires config mount |
| authentik server/worker | authentik-stack | Partial | Python `logging.handlers.SysLogHandler` available but requires app-level config; not exposed as an env var in goauthentik |
| traefik | proxy-stack | ✗ | Logs to stdout only; no native syslog output option |
| portainer | portainer-stack | ✗ | Logs to stdout only |
| Harbor services | harbor-stack | Unknown | Harbor manages its own services; syslog config would require Harbor-level configuration |
| NetBox/gunicorn | netbox-stack | Partial | gunicorn supports `--error-logfile=syslog:` but requires config change |
| CoreDNS | dns-stack | ✗ | Logs to stdout/stderr only |
| step-ca | step-ca-stack | ✗ | Logs to stdout only |
| cadvisor | all Docker stacks | ✗ | Logs to stdout only |

**Conclusion**: native syslog configuration is possible for postgres and nginx but requires mounting config files into containers or env vars. For most services (traefik, portainer, CoreDNS, step-ca, cadvisor, authentik), stdout is the only output. The Docker `syslog` logging driver is the correct mechanism for these — it intercepts stdout/stderr at the Docker daemon level, wrapping each line in a syslog envelope before delivery to rsyslog. The key difference from Promtail is that the **transport layer** (rsyslog header) carries the authoritative hostname and appname, not the message body.

---

### How Docker container logging via syslog works

Docker has a pluggable logging driver. The default `json-file` writes each log line to a file on the host (what Promtail was scraping). With the `syslog` driver, Docker intercepts stdout/stderr at the daemon level and formats each line as a syslog message:

```
container process writes to stdout/stderr
        ↓
Docker daemon captures it (this always happens internally)
        ↓  syslog driver
Formats as RFC 5424 message:
  HOSTNAME = LXC hostname        e.g. authentik-stack
  APPNAME  = tag option          e.g. docker/authentik-worker-1
  FACILITY = configurable        e.g. daemon
  SEVERITY = stdout→info, stderr→err
  MSG      = the log line
        ↓
Sends to unixgram:///dev/log (local rsyslog socket)
        ↓
rsyslog receives, queues, forwards → VictoriaLogs :5140
```

The stdout→`info` / stderr→`err` mapping is real signal: many services write normal output to stdout and error conditions to stderr. It is not perfectly reliable (some apps write everything to stderr) but it is genuine severity rather than a regex heuristic.

**Important operational caveat**: with the `syslog` driver, `docker logs <container>` does not work — there is no local JSON file. Logs exist only in VictoriaLogs. Bear this in mind when debugging container startup issues before VictoriaLogs is available.

---

### Confirmed design decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Docker log routing | `tcp://127.0.0.1:10514` → local rsyslog imtcp → VictoriaLogs TCP | Direct TCP to rsyslog bypasses journald; journald mangles RFC 5424 APPNAME on the `/dev/log` path (see Implementation notes §3). rsyslog `imtcp` correctly parses RFC 5424 — container name preserved in full. System logs (non-Docker) still flow via imuxsock from journald. |
| 2 | Stack identity in queries | `hostname` field (no synthetic `stack` label) | Each LXC hostname is already the stack name; `hostname` is set by the transport layer, not the application |
| 2a | Container as metadata | `appname` field carries Docker container name via `tag` option | Grafana can filter by `appname=~"docker/authentik.*"` to drill into individual containers within a host |
| 3 | Docker logging config scope | Daemon-level default in `docker_base` role (`daemon.json`) | Applies to all containers on every host; persists through upgrades; no per-compose `logging:` blocks needed. Harbor exception: Harbor's installer-managed compose has per-service `logging:` blocks pointing to its own log aggregator — these override daemon default and are not overridden by us (accepted). |
| 4 | Cutover strategy | Parallel — verify syslog per host, then remove Promtail | Safe; brief duplicate logs are acceptable; no risk of losing logs if syslog config is wrong |

---

### Architecture (confirmed)

**Important**: the original design routed Docker container logs via `unixgram:///dev/log`. This was changed to `tcp://127.0.0.1:10514` after discovering that journald mangles RFC 5424 APPNAME on the `/dev/log` path — see Implementation notes §3.

```
Each LXC host
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  Docker containers (stdout/stderr via daemon syslog driver)          │
│  ┌──────────────┐   syslog driver: tcp://127.0.0.1:10514            │
│  │ any container├────────────────────────────────────────────►       │
│  └──────────────┘                           ┌────────────────────┐  │
│                                             │                    │  │
│  System logs (auth, kern, daemon, etc)      │   rsyslog          │  │
│  via journald → imuxsock ──────────────────►│                    │  │
│                                             │  - imtcp :10514    │  │
│                                             │  - imuxsock        │  │
│                                             │    (journald path) │  │
│                                             └────────┬───────────┘  │
│                                                      │               │
└──────────────────────────────────────────────────────┼──────────────┘
                                                       │ TCP :5140 (RFC 5424)
                                           ┌───────────▼────────────────┐
                                           │  VictoriaLogs              │
                                           │  :9428 (HTTP/LogsQL/Loki)  │
                                           │  :5140 (syslog TCP input)  │
                                           │                            │
                                           │  Stream labels:            │
                                           │    hostname, appname,      │
                                           │    facility, severity      │
                                           └───────────┬────────────────┘
                                                       │
                                           ┌───────────▼────────────────┐
                                           │  Grafana                   │
                                           │  filter by severity,       │
                                           │  facility, hostname,       │
                                           │  appname (container)       │
                                           └────────────────────────────┘
```

### VictoriaLogs fields from syslog ingestion

| Field | Source | Example values | Notes |
|-------|--------|----------------|-------|
| `hostname` | syslog RFC 5424 header | `authentik-stack`, `harbor-stack` | Stream label |
| `app_name` | syslog APPNAME field | `docker/traefik`, `sshd`, `rsyslogd` | Regular field; stream label flag uses `appname` (without underscore) — VictoriaLogs stores it as `app_name` internally |
| `facility` | syslog facility | `3` (daemon), `10` (auth) | Stream label (numeric code) |
| `severity` | syslog severity | `6` (info), `3` (err) | Stream label (numeric code) |
| `_msg` | syslog MSG field | the log line | |
| `proc_id` | syslog PROCID (PID) | `1234` | Regular field |

`severity` and `facility` are first-class LogsQL filter fields. Grafana variable queries against `field_values?field=severity` return real severity values — no regex heuristics.

**Field naming note**: VictoriaLogs stores APPNAME as `app_name` (underscore) in regular fields. The `-syslog.streamFields.tcp` flag references `appname` (no underscore) to index it as a stream label. Testing showed `appname` appeared in the `_stream` label set while `app_name` holds the value in the message fields. Use `{appname=~"docker/.*"}` in LogsQL stream selectors and `app_name` for message-level filtering.

### Regression risks

| Risk | Detail | Mitigation |
|------|--------|------------|
| Log gap during cutover | If Promtail is removed before rsyslog+syslog is confirmed, logs stop flowing | Option A (parallel) cutover — confirm per host before removing Promtail |
| Docker daemon restart | Changing `daemon.json` requires Docker restart, causing brief container outage on each host | Schedule during maintenance; restart Docker before provisioning compose stacks |
| Harbor containers | Harbor's own compose is managed by Harbor installer; Docker daemon default covers this without touching Harbor config | Verify Harbor log ingestion after daemon restart |
| VictoriaLogs data continuity | Existing logs ingested via Loki-push (Promtail) use different stream fields than syslog-ingested logs. Both live in the same VictoriaLogs storage. Historic Promtail-era logs have `stack`, `host` fields; new syslog logs have `hostname`, `appname`, `facility`, `severity`. | Dashboard queries need to handle both, OR accept that pre-cutover logs require different query fields. Dashboards will be rebuilt for the new field set; historic data remains queryable via LogsQL explore. |
| Auth Logs dashboard | Currently queries `{job="varlogs"}` to find auth events. This label is set by Promtail. Post-cutover, auth events arrive via rsyslog with `facility=auth`. | Rebuild Auth Logs dashboard to use `{facility="auth"}` — cleaner and correct |
| Teardown test smoke test | The teardown test checks `curl http://...:9428/health` but does not verify log ingestion. A broken syslog config would pass the health gate. | Add a log ingestion verification step to the smoke test: after provision, query `{hostname=~".+"} \| limit 1` and assert non-empty |
| Port 5140 not documented | The network reachability table in this doc lists port 9428 for VictoriaLogs. Port 5140 needs to be added. | Update network docs as part of Phase 7 |
| authentik static compose file | `terraform/lxc/stacks/authentik-stack/docker-compose.yml` is a static file in the repo. If daemon-level logging driver is used (Decision 3 Option C), no changes needed there. If per-service logging blocks are needed, this file must be edited — unlike other stacks where the compose is written inline by Ansible. | Decision 3 Option C eliminates the need to touch this file |
| monitoring-stack self-monitoring | monitoring-stack runs its own Promtail container. Removing it means monitoring-stack's own Docker logs go via rsyslog+Docker daemon syslog driver like every other host. | No special handling needed — same pattern applies |

### Implementation tasks

| # | Task | File(s) / Role | Status (2026-06-21) |
|---|------|----------------|---------------------|
| 1 | Enable VictoriaLogs syslog TCP input | `deploy-monitoring-stack.yml` compose block: `-syslog.listenAddr.tcp=:5140`, `-syslog.streamFields.tcp=["hostname","appname","facility","severity"]`, port 5140 | ✅ deployed on pve |
| 2 | Update network docs | `docs/monitoring-stack/design.md` port table | ✅ done |
| 3 | Create `rsyslog_forward` Ansible role | `terraform/lxc/ansible/roles/rsyslog_forward/` — installs rsyslog, writes `/etc/rsyslog.d/90-victorialogs.conf`, imtcp listener on `127.0.0.1:10514`, forwards all to VictoriaLogs:5140 | ✅ role created and running on all provisioned stacks |
| 4 | Configure Docker daemon syslog default | `docker_base` role `daemon.json`: `log-driver=syslog`, `syslog-address=tcp://127.0.0.1:10514`, `syslog-format=rfc5424`, `tag=docker/{{.Name}}`; conditional `recreate: always` when daemon config changes | ✅ deployed; pending re-provision after §3 APPNAME fix |
| 5 | Add `rsyslog_forward` role to `lxc_base` | `terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` | ✅ done |
| 6 | Verify syslog ingestion per host | Query `{hostname="<host>"}` after each provision | ⏳ system logs confirmed working; Docker container logs pending re-provision with TCP fix |
| 7 | Remove Promtail from Docker stack playbooks (inline compose) | `deploy-portainer-stack.yml`, `deploy-proxy-stack.yml`, `deploy-netbox-stack.yml`, `deploy-monitoring-stack.yml` | ⏳ Phase 7C — after Docker container log verification |
| 8 | Remove Promtail from authentik static compose | `terraform/lxc/stacks/authentik-stack/docker-compose.yml` | ⏳ Phase 7C |
| 9 | Remove `promtail` role from systemd-Promtail stacks | `deploy-harbor-stack.yml`, `deploy-apt-cacher-stack.yml`, `deploy-coredns.yml`, `deploy-step-ca.yml`, `deploy-ci-runner.yml` | ⏳ Phase 7C |
| 10 | Uninstall Promtail systemd service (idempotent) | `apt: name=promtail state=absent`, disable+stop systemd unit | ⏳ Phase 7C |
| 11 | Rebuild Lab Logs dashboard | `dashboards/lab-logs.json`: `{hostname=~"$hostname"}`, severity variable | ⏳ Phase 7D |
| 12 | Rebuild Auth Logs dashboard | `dashboards/auth-logs.json`: `{facility="auth"}` | ⏳ Phase 7D |
| 13 | Add log ingestion smoke test to teardown harness | `scripts/teardown-deploy-test.sh`: query VictoriaLogs for recent entries | ⏳ Phase 7E |
| 14 | Provision all stacks on pve-test | Full provision; verify ingestion, dashboards, severity filter | ⏳ Phase 7E |
| 15 | Full teardown + redeploy on pve-test | Promotion gate for `baseline/teardown-validated` | ⏳ Phase 7E |

### Implementation notes (Phase 7 — live deployment on pve, 2026-06-21)

These are issues discovered during live deployment and their resolutions. Read before making changes to the syslog collection path.

#### §1 — VictoriaLogs `-syslog.streamFields.tcp` requires JSON array format

**Symptom**: VictoriaLogs crashed on startup with:
```
cannot parse -syslog.streamFields.tcp="hostname" for -syslog.listenAddr.tcp=":5140":
invalid character 'h' looking for beginning of value
```
**Root cause**: The flag expects a JSON array string `["hostname","appname","facility","severity"]`, not a comma-separated list.
**Fix**: Wrap the flag value in single quotes in the YAML compose `command:` block to prevent YAML from interpreting the JSON array:
```yaml
command:
  - '-syslog.streamFields.tcp=["hostname","appname","facility","severity"]'
```
**Commit**: `fix(monitoring): correct syslog.streamFields.tcp flag to JSON array format`

#### §2 — `docker compose up -d` does not recreate containers when `daemon.json` changes

**Symptom**: After provisioning a stack with the syslog log driver in daemon.json, `docker inspect <container>` showed `json-file` — the old driver. The containers were running fine but using the old log config.
**Root cause**: `docker compose up -d` only recreates containers when their compose service definition changes. `daemon.json` is external to compose — Docker daemon restart (triggered by the handler) restarts containers, but they restart with whatever log config they were originally created with, not the new daemon default.
**Fix**: Register the daemon.json write task result in each playbook (`register: docker_daemon_config`), then pass `recreate: "{{ 'always' if docker_daemon_config.changed else 'auto' }}"` to the `community.docker.docker_compose_v2` task. For the NetBox playbook (uses shell-based compose), pass `{{ '--force-recreate' if docker_daemon_config.changed else '' }}` in the command string.
**One-time remediation**: For stacks already provisioned before this fix, manually ran `docker compose up -d --force-recreate` via SSH on `/opt/monitoring-stack`, `/opt/authentik-stack`, `/opt/harbor-cadvisor`.
**Commit**: `fix(ansible): force-recreate containers when Docker log driver changes`

#### §3 — APPNAME truncated at `/` via the journald path (CRITICAL)

**Symptom**: After provisioning proxy-stack, sent a test message with `logger -t 'docker/test-container' 'phase7 test'`. VictoriaLogs received it but showed `app_name: "docker"` — the container name portion was lost. Traefik container logs were not appearing in VictoriaLogs at all.
**Root cause**: Docker's syslog driver with `syslog-address: unixgram:///dev/log` writes to journald's socket. journald receives the RFC 5424 message and converts it to RFC 3164 format when forwarding to rsyslog's syslog socket. In this conversion, the APPNAME field `docker/traefik` is truncated at `/` because rsyslog's traditional BSD syslog parser treats `/` as a separator in the TAG field. The `$programname` variable (which maps to APPNAME in the RFC 5424 output template) is extracted as everything before the first `[` or `/`. Result: container name is entirely lost in transport.
**Fix**: Bypass journald entirely. Configure rsyslog to listen on a local TCP socket that Docker connects to directly:
- rsyslog: add `module(load="imtcp")` + `input(type="imtcp" port="10514" address="127.0.0.1")` in `90-victorialogs.conf`
- Docker daemon.json: change `syslog-address` from `unixgram:///dev/log` to `tcp://127.0.0.1:10514`
- rsyslog's `imtcp` module correctly parses the full RFC 5424 message including APPNAME with `/` characters
- System logs (non-Docker) continue to flow via journald → rsyslog `imuxsock` as before — no change there
**Files changed**: `roles/rsyslog_forward/templates/victorialogs.conf.j2`, `roles/docker_base/templates/daemon.json.j2`, and inline daemon.json in all 9 stack playbooks
**Status**: Fix implemented (2026-06-21), pending re-provision of all stacks

#### §4 — Harbor containers use per-service log config (not overridable via daemon default)

**Symptom**: After deploying Harbor and enabling the syslog daemon default, Harbor containers continued using their original log driver.
**Root cause**: Harbor's installer-managed `docker-compose.yml` (at `/opt/harbor/`) contains per-service `logging:` blocks that send to `tcp://localhost:1514` (Harbor's built-in log aggregator). Per-service config takes precedence over the daemon default. We do not control this file.
**Resolution**: Accepted as expected behavior. Harbor's own log aggregator handles Harbor container logs internally. Only cAdvisor (managed by our `/opt/harbor-cadvisor/` compose) uses the daemon default and sends via syslog.

---

### rsyslog_forward role

Role at `terraform/lxc/ansible/roles/rsyslog_forward/`. What it does:
1. Installs `rsyslog` package
2. Writes `/etc/rsyslog.d/90-victorialogs.conf` via Jinja2 template, parameterised by `rsyslog_forward_target_host` (defaults to `$LAB_IP_MONITORING`) and `rsyslog_forward_target_port` (default `5140`)
3. Enables and starts rsyslog service
4. Handler: restart rsyslog on config change

Forwarding config (actual deployed template):

```
# Accept Docker container logs directly via TCP on localhost, bypassing journald.
# journald mangles RFC 5424 APPNAME on the /dev/log path (truncates at '/'),
# which would lose the container name from docker/<name> tags.
module(load="imtcp")
input(type="imtcp" port="10514" address="127.0.0.1")

# Forward all syslog messages to VictoriaLogs TCP syslog input.
# Queue persists to disk so messages survive a brief VictoriaLogs outage.
$WorkDirectory /var/spool/rsyslog

*.* action(type="omfwd"
           target="{{ rsyslog_forward_target_host }}"
           port="{{ rsyslog_forward_target_port }}"
           protocol="tcp"
           Template="RSYSLOG_SyslogProtocol23Format"
           queue.type="LinkedList"
           queue.filename="victorialogs-fwd"
           queue.maxDiskSpace="64m"
           queue.saveOnShutdown="on"
           action.resumeRetryCount="-1")
```

`RSYSLOG_SyslogProtocol23Format` is the built-in rsyslog template for RFC 5424 (syslog protocol version 2.3) format.

### Docker daemon logging config

Deployed in `docker_base` role (`daemon.json`):

```json
{
  "log-driver": "syslog",
  "log-opts": {
    "syslog-address": "tcp://127.0.0.1:10514",
    "syslog-format": "rfc5424",
    "tag": "docker/{{.Name}}"
  }
}
```

The `tag` value `docker/{{.Name}}` sets the syslog APPNAME to e.g. `docker/authentik-worker-1`. The `docker/` prefix distinguishes Docker container entries from native system processes (`sshd`, `cron`, `rsyslogd`) in the same syslog stream. In LogsQL, `{appname=~"docker/.*"}` selects all Docker container logs; `{appname="docker/traefik"}` selects a specific container.

`tcp://127.0.0.1:10514` sends directly to rsyslog's imtcp listener on the same host. This bypasses journald and preserves the full APPNAME including the `/container-name` portion (see Implementation notes §3).

> **Operational note**: With the `syslog` driver, `docker logs <container>` does not work — there is no local JSON file. Container logs exist only in VictoriaLogs. This is the expected trade-off. During debugging of container startup issues before VictoriaLogs is available (e.g. fresh provision), temporarily switch back to `json-file` in daemon.json, restart Docker, recreate the container, then switch back.

### Branch

`work/victorialogs` (current) — Phase 7 planning complete, design decisions confirmed. Implementation begins on a new branch cut from this one.
