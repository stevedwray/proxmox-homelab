# Monitoring Stack — Design

## Overview

The monitoring-stack LXC (192.168.20.12, `mgmt_seg`) runs VictoriaMetrics, VictoriaLogs, Grafana, cAdvisor, and the Harbor findings exporter via Docker Compose. Grafana is the sole browser-facing service (via Traefik + Authentik). VictoriaMetrics and VictoriaLogs are internal-only data stores.

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

**Phases 1–7D complete on pve. Phase 7E (pve-test provision + teardown gate) pending. Phase 8 (VictoriaLogs MCP server) in design. Dashboard issues from Phase 7D resolved 2026-06-22 — see §7c, §9. Recent pve fixes removed the invalid Proxmox host scrape, replaced the invalid step-ca HTTPS scrape with native step-ca metrics, and confirmed the old step-ca scrape warning is no longer emitted.**

### Running services

| Service | Port | Notes |
|---------|------|-------|
| VictoriaMetrics | `:8428` | `--retentionPeriod=90d`; scrape config at `/etc/vm/scrape.yml` |
| VictoriaLogs | `:9428`, `:5140` | `--retentionPeriod=30d`; syslog TCP input on `:5140`; named Docker volume on `/var/lib/docker` mount; `v1.51.0` (tag format changed — no `-victorialogs` suffix from v1.25.0+) |
| Grafana | `:3000` | OAuth via Authentik; `victoriametrics-logs-datasource` plugin installed |
| cAdvisor | `:8080` | Container resource metrics for monitoring-stack |
| Harbor findings exporter | `:9414` internal | Harbor CVE/findings metrics scraped from the compose network |
| Promtail | — | Deprecated by syslog/VictoriaLogs forwarding; no active runtime service/container remains after cleanup. |

### Active scrape targets

| Job | Instance | Status |
|-----|----------|--------|
| node_exporter | all 10 managed LXCs | ✅ up |
| node_exporter | Proxmox host | intentionally not scraped — keep bare-metal host services minimal |
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
| victorialogs | 192.168.20.12:9428 | ✅ up |
| grafana | 192.168.20.12:3000 | ✅ up |
| step-ca | 192.168.20.11:9443 | ✅ native metrics |

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
- **step-ca scrape job**: Uses native Step CA Prometheus metrics via HTTP on `:9443`; the CA service and health endpoint remain HTTPS on `:443`.
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
| Proxmox host `node_exporter` target rendered as `http://:9100/metrics` | 2daaa8f |
| Removed inactive step-ca HTTPS scrape while confirming no real endpoint existed | 3513682 |
| Enabled native step-ca metrics on HTTP `:9443` and restored a healthy scrape | 6414d37 |

---

## Architecture

```
                         mgmt_seg (192.168.20.0/24)
                         ┌──────────────────────────────────────────────────┐
                         │  monitoring-stack (192.168.20.12)                │
                         │  ┌─────────────────┐  ┌──────────────────────┐  │
                         │  │ VictoriaMetrics │  │   VictoriaLogs       │  │
 ┌──────────────┐  scrape │  │   :8428         │  │   :9428 / :5140     │  │
 │ node_exporter│◄────────┤  │  (pull metrics) │  │  (syslog ingest)    │  │
 │    :9100     │         │  └────────┬────────┘  └──────────┬───────────┘  │
 └──────────────┘         │           │                       │              │
 ┌──────────────┐  scrape │           │           ┌──────────▼───────────┐  │
 │   cAdvisor   │◄────────┤           │           │      Grafana         │  │
 │    :8080     │         │           └──────────►│      :3000           │  │
 └──────────────┘ syslog  │                       │  (queries both)      │  │
 ┌──────────────┐ ────────►                       └──────────────────────┘  │
 │   rsyslog    │         │                                                  │
 │  (per stack) │         └──────────────────────────────────────────────────┘
 └──────────────┘
```

**Metrics flow**: VictoriaMetrics scrapes node_exporter (:9100) on managed LXCs, cAdvisor (:8080/:8081) on Docker stacks, and application metrics endpoints directly. Pull model — VictoriaMetrics initiates all scrapes. The bare-metal Proxmox host is intentionally not scraped. Step CA exposes native Prometheus metrics over HTTP on `:9443`; its CA service and health endpoint remain HTTPS on `:443`.

**Log flow**: rsyslog on each LXC forwards RFC 5424 syslog to VictoriaLogs on `192.168.20.12:5140`. Docker stacks use the Docker `syslog` logging driver to send container stdout/stderr to local rsyslog on `127.0.0.1:10514`, which then forwards to VictoriaLogs. Promtail is deprecated and should not be part of the steady-state logging path.

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
| 9443 | step-ca native metrics (HTTP) | step-ca-stack |
| 9428 | VictoriaLogs HTTP and metrics | monitoring-stack |
| 5140 | VictoriaLogs syslog TCP | monitoring-stack receives RFC 5424 from rsyslog on all LXCs |

---

## What Gets Monitored

### Platform stacks

| Stack | Zone | node_exporter | cAdvisor | App metrics | Logs |
|-------|------|:---:|:---:|---|:---:|
| dns-stack | mgmt_seg | ✓ | — | CoreDNS :9153 | rsyslog → VictoriaLogs |
| step-ca-stack | mgmt_seg | ✓ | — | step-ca :9443/metrics | rsyslog → VictoriaLogs |
| monitoring-stack | mgmt_seg | ✓ | ✓ | VM :8428, VictoriaLogs :9428, Grafana :3000 | rsyslog → VictoriaLogs |
| portainer-stack | mgmt_seg | ✓ | ✓ | — | Docker syslog → rsyslog → VictoriaLogs |
| authentik-stack | mgmt_seg | ✓ | ✓ | Authentik :9300/metrics | Docker syslog → rsyslog → VictoriaLogs |
| proxy-stack | edge_seg | ✓ | ✓ | Traefik :8082/metrics | Docker syslog → rsyslog → VictoriaLogs |
| harbor-stack | infra_seg | ✓ | ✓ | Harbor :9090/metrics | Docker/syslog mix; Harbor internal logs handled by Harbor |
| apt-cacher-stack | infra_seg | ✓ | — | — | rsyslog → VictoriaLogs |
| netbox-stack | infra_seg | ✓ | ✓ | NetBox :8080/metrics | Docker syslog → rsyslog → VictoriaLogs |
| ci-runner-01 | build_seg | ✓ | — | — | rsyslog → VictoriaLogs |

**Proxmox host** (`$PROXMOX_HOST`): host performance metrics are intentionally not scraped. Proxmox host logs should be forwarded separately via remote syslog when needed, rather than by installing monitoring agents on the host.

### Application metrics endpoints

| Service | Endpoint | Ready? | Notes |
|---------|----------|--------|-------|
| CoreDNS | `:9153/metrics` | ✓ | |
| Traefik | `:8082/metrics` | ✓ | |
| Authentik | `:9300/metrics` | ✓ | |
| Harbor | `:9090/metrics` | ✓ | |
| NetBox | `:8080/metrics` | ✓ | |
| step-ca | `:9443/metrics` | ✓ | Native Step CA metrics listener; HTTP, separate from HTTPS CA service on `:443` |
| VictoriaMetrics | `:8428/metrics` | ✓ | |
| VictoriaLogs | `:9428/metrics` | ✓ | |
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

All `LAB_IP_*` variables are in `.env`. Secrets (Grafana admin password, OAuth client secret, Harbor admin password, Authentik API token) are in `secrets.enc.yaml` and loaded by `./with-secrets`. See [STACK_CONTRACT.md](../../terraform/lxc/stacks/monitoring-stack/STACK_CONTRACT.md) for the full inputs list.

No secrets are required for VictoriaLogs or VictoriaMetrics (both are mgmt_seg-internal, no auth).

---

## Remaining Work

| Item | Notes |
|------|-------|
| Proxmox host logs | Configure bare-metal Proxmox remote syslog forwarding to VictoriaLogs/syslog listener; do not install node_exporter for host performance metrics |
| step-ca metrics dashboard | Native metrics are scraped; no dedicated Grafana dashboard yet |
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
| Auth Logs dashboard | Earlier Promtail-era queries used `{job="varlogs"}`. Post-cutover, auth events arrive via rsyslog with `facility=auth`. | Resolved in Phase 7D; keep historic queries in mind when exploring pre-cutover logs |
| Teardown test smoke test | The teardown test checks `curl http://...:9428/health` but does not verify log ingestion. A broken syslog config would pass the health gate. | Add a log ingestion verification step to the smoke test: after provision, query `{hostname=~".+"} \| limit 1` and assert non-empty |
| Port 5140 documentation | The network reachability table must include VictoriaLogs syslog TCP on `:5140`. | Resolved in Phase 7; keep the port documented because it is the active log ingest path |
| authentik static compose file | `terraform/lxc/stacks/authentik-stack/docker-compose.yml` is a static file in the repo. If daemon-level logging driver is used (Decision 3 Option C), no changes needed there. If per-service logging blocks are needed, this file must be edited — unlike other stacks where the compose is written inline by Ansible. | Decision 3 Option C eliminates the need to touch this file |
| monitoring-stack self-monitoring | monitoring-stack previously ran its own Promtail container. Desired state is Docker syslog → local rsyslog → VictoriaLogs like every other Docker host. | Source compose no longer includes Promtail; runtime cleanup should still verify no orphan remains |

### Sub-phases

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 7A | Enable VictoriaLogs syslog TCP input (`:5140`); create `rsyslog_forward` role; add to `lxc_base` | ✅ complete on pve |
| 7B | Configure Docker daemon syslog default (`docker_base` role + all playbooks); verify ingestion | ✅ complete on pve |
| 7C | Remove Promtail from all stacks (10 files: compose blocks, include_roles, vars, handlers) | ✅ complete on pve |
| 7D | Rebuild Lab Logs and Auth Logs dashboards for VictoriaLogs syslog field model | ✅ complete (2026-06-22) — all panels working, severity labels, appname filter |
| 7E | Provision all stacks on pve-test; add smoke test to teardown harness; full teardown + redeploy cycle (promotion gate for `baseline/teardown-validated`) | ⏳ pending |

### Implementation tasks

| # | Task | File(s) / Role | Status (2026-06-21) |
|---|------|----------------|---------------------|
| 1 | Enable VictoriaLogs syslog TCP input | `deploy-monitoring-stack.yml` compose block: `-syslog.listenAddr.tcp=:5140`, `-syslog.streamFields.tcp=["hostname","appname","facility","severity"]`, port 5140 | ✅ deployed on pve |
| 2 | Update network docs | `docs/monitoring-stack/design.md` port table | ✅ done |
| 3 | Create `rsyslog_forward` Ansible role | `terraform/lxc/ansible/roles/rsyslog_forward/` — installs rsyslog, writes `/etc/rsyslog.d/90-victorialogs.conf`, imtcp listener on `127.0.0.1:10514`, forwards all to VictoriaLogs:5140 | ✅ role created and running on all provisioned stacks |
| 4 | Configure Docker daemon syslog default | `docker_base` role `daemon.json`: `log-driver=syslog`, `syslog-address=tcp://127.0.0.1:10514`, `syslog-format=rfc5424`, `tag=docker-{{.Name}}`; conditional `recreate: always` when daemon config changes | ✅ deployed on pve |
| 5 | Add `rsyslog_forward` role to `lxc_base` | `terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` | ✅ done |
| 6 | Verify syslog ingestion per host | Query `{hostname="<host>"}` after each provision | ✅ system and Docker container logs confirmed in VictoriaLogs on pve |
| 7 | Remove Promtail from Docker stack playbooks (inline compose) | `deploy-portainer-stack.yml`, `deploy-proxy-stack.yml`, `deploy-netbox-stack.yml`, `deploy-monitoring-stack.yml` | ✅ done (commit `b12db11`) |
| 8 | Remove Promtail from authentik static compose | `terraform/lxc/stacks/authentik-stack/docker-compose.yml` | ✅ done (commit `b12db11`) |
| 9 | Remove `promtail` include_role from remaining playbooks | `deploy-harbor-stack.yml`, `deploy-apt-cacher-stack.yml`, `deploy-coredns.yml`, `deploy-step-ca.yml`, `deploy-ci-runner.yml` | ✅ done (commit `b12db11`) |
| 10 | Uninstall Promtail systemd service and remove runtime leftovers (idempotent) | `lxc_base`: stop/disable/purge promtail if present; compose deploys use orphan removal for removed services | ✅ done — verified no Promtail systemd services or Docker containers remain running |
| 11 | Rebuild Lab Logs dashboard | `dashboards/lab-logs.json`: hostname + severity variables, log volume timeseries, logs panel | ✅ done — see §7 for one open rendering issue |
| 12 | Rebuild Auth Logs dashboard | `dashboards/auth-logs.json`: `{facility="4"}` stream selector, SSH/sudo timeseries + log panels | ✅ done — auth panels show data only when auth events exist in window |
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
**Commit**: `ae51036` (rsyslog RFC 5424 ruleset), `334809a` (Docker tag separator change)

#### §4b — APPNAME still truncated at `/` even on imtcp path: `%programname%` behaviour

**Symptom**: After the TCP bypass fix (§3), Docker container entries still arrived in VictoriaLogs as `app_name: "docker"` instead of `app_name: "docker-authentik-worker"`.
**Root cause**: rsyslog's `%programname%` property truncates at `/`, `[`, and `:` by design — this is not parser-dependent, it is how the property works. `docker/{{.Name}}` → `%programname%` = `"docker"`.
**Fix**: Change the Docker syslog `tag` separator from `/` to `-` everywhere:
- `docker_base` role `daemon.json.j2`: `"tag": "{% raw %}docker-{{.Name}}{% endraw %}"`
- All 9 inline daemon.json blocks in stack playbooks: same change
- Now `docker-authentik-worker` → `%programname%` = `"docker-authentik-worker"` (no truncation)
**Files changed**: `roles/docker_base/templates/daemon.json.j2` + all 9 deploy playbooks
**Commit**: `334809a`
**Consequence**: LogsQL queries for Docker containers use `app_name=~"docker-.*"` (hyphen), not `docker/.*`.

#### §5 — `app_name=1` from rsyslog default parser on imtcp

**Symptom**: Docker container entries received via imtcp port 10514 showed `app_name: "1"` in VictoriaLogs.
**Root cause**: rsyslog's default imtcp parser is `pmrfc3164` (BSD syslog). RFC 5424 messages begin with a version field `1` (the literal character `1` after the PRI). `pmrfc3164` interprets this as the syslog TAG, so APPNAME becomes `"1"`.
**Fix**: Bind an explicit RFC 5424 ruleset to the imtcp input in `victorialogs.conf.j2`:
```
ruleset(name="docker-tcp" parser="rsyslog.rfc5424") {
    *.* action(type="omfwd" ...)
}
input(type="imtcp" port="10514" address="127.0.0.1" ruleset="docker-tcp")
```
Also uses a custom template with `%programname%` (clean APPNAME) instead of the default `RSYSLOG_SyslogProtocol23Format` (which uses `%syslogtag%` — appends PID and truncates to 32 chars).
**Commit**: `ae51036`

#### §7 — VictoriaLogs v1.51.0 LogsQL syntax quirks (dashboard-breaking)

These were discovered during Phase 7D dashboard work. All three affect dashboard queries.

**7a — `|~` pipe operator returns no results**
The `|~` pipe (regex filter on message) silently returns ~1 result regardless of pattern. `{hostname=~".*"} |~ ".*"` → 1 line. This appears to be a v1.51.0 bug.
**Fix**: Use the field-filter form instead: `_msg:~"pattern"`. `{hostname=~".*"} _msg:~".*"` → full result set.
Example: `{hostname=~"$hostname", facility="4"} "sshd" _msg:~"Accepted|Failed|session opened"`

**7b — `stats count() by (field)` is invalid syntax in v1.51.0**
The `by` keyword after a stats function is parsed as an alias name, not a grouping clause.
`| stats count() by (hostname)` → error: `unexpected token "(" after [count(*) as "by"]`
**Fix**: The `by` clause must precede the function: `| stats by (hostname) count()`.
With an alias: `| stats by (hostname) count() as cnt`

**7c — stats query panels require explicit `queryType: "statsRange"` — resolved 2026-06-22**
Without an explicit `queryType`, the victoriametrics-logs-datasource v0.28.0 plugin treats all queries (including `| stats by (...) count() as cnt`) as raw log queries. It returns results as log-panel data frames: a "Time" field and a "Line" field where each value is a JSON string like `{"cnt":"34","hostname":"proxy-stack"}`. There is no numeric field for a timeseries panel to plot, hence "Data is missing a number field".
**Root cause confirmed via** `/api/ds/query`: querying without `queryType` returns `{name: "Line", type: "string"}` frames; querying with `queryType: "statsRange"` returns `{name: "Value", type: "number", frame: "float64"}` per-series frames — already converted to numbers by the plugin backend, no `convertFieldType` transformation needed.
**Fix**: Add `"queryType": "statsRange"` to every timeseries panel target that uses a `| stats` query. Remove all `convertFieldType` transformations. Applied to all timeseries panels in `lab-logs.json` (Log Volume by Host) and `auth-logs.json` (SSH Successful, SSH Failed, Sudo Events). Commit: `work/syslog-collection`.

#### §9 — `appname` is not the correct stream field name for APPNAME — use `app_name` — resolved 2026-06-22

**Symptom**: The `appname` stream label in VictoriaLogs was always empty string. The `_stream` dict on syslog-ingested entries showed `{facility="3",hostname="...",severity="6"}` — no `appname` field. The Grafana dashboard `appname` variable (querying `field_values?field=appname`) returned only empty string with no real values.
**Root cause**: VictoriaLogs stores the RFC 5424 APPNAME field internally as `app_name` (underscore). The `-syslog.streamFields.tcp` flag was configured as `["hostname","appname","facility","severity"]`. VictoriaLogs looked for a stream-eligible field named `appname` (no underscore), found nothing, and indexed the stream label as empty. The `app_name` regular field was correctly populated but was not indexed as a stream label.
**Fix**: Change `-syslog.streamFields.tcp=["hostname","appname","facility","severity"]` to `-syslog.streamFields.tcp=["hostname","app_name","facility","severity"]`. After redeploying VictoriaLogs, new entries carry `app_name` in their `_stream` dict. Dashboard variable updated to `field: "app_name"`. Panel queries use `app_name:~"$appname"` (message-level filter rather than stream selector) so the filter works for both pre-fix entries (where `app_name` is a message field only) and post-fix entries (where it is also a stream label). Pre-fix entries will age out at 30-day retention.
**Commit**: `work/syslog-collection`

#### §8 — Harbor containers use per-service log config (not overridable via daemon default)

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

Forwarding config (actual deployed template — `roles/rsyslog_forward/templates/victorialogs.conf.j2`):

```
# Custom template uses %programname% (not %syslogtag%) for clean APPNAME.
# %syslogtag% appends [PID] and truncates at 32 chars; %programname% does not.
# Note: %programname% truncates at '/', so Docker tags use '-' not '/' as separator.
template(name="VictoriaLogsForward" type="string"
  string="<%PRI%>1 %TIMESTAMP:::date-rfc3339% %HOSTNAME% %programname% %PROCID% - - %msg%\n")

$WorkDirectory /var/spool/rsyslog

# Forward system logs (journald → imuxsock) to VictoriaLogs.
*.* action(type="omfwd"
           target="{{ rsyslog_forward_target_host }}"
           port="{{ rsyslog_forward_target_port }}"
           protocol="tcp"
           Template="VictoriaLogsForward"
           queue.type="LinkedList"
           queue.filename="victorialogs-fwd"
           queue.maxDiskSpace="64m"
           queue.saveOnShutdown="on"
           action.resumeRetryCount="-1")

# Accept Docker container logs via TCP on localhost with explicit RFC 5424 ruleset.
# Without the explicit ruleset, rsyslog's default pmrfc3164 parser reads the RFC 5424
# version field '1' as the syslog TAG, causing app_name="1" in VictoriaLogs (see §5).
module(load="imtcp")

ruleset(name="docker-tcp" parser="rsyslog.rfc5424") {
    *.* action(type="omfwd"
               target="{{ rsyslog_forward_target_host }}"
               port="{{ rsyslog_forward_target_port }}"
               protocol="tcp"
               Template="VictoriaLogsForward"
               queue.type="LinkedList"
               queue.filename="victorialogs-fwd-docker"
               queue.maxDiskSpace="32m"
               queue.saveOnShutdown="on"
               action.resumeRetryCount="-1")
}

input(type="imtcp" port="10514" address="127.0.0.1" ruleset="docker-tcp")
```

### Docker daemon logging config

Deployed in `docker_base` role (`daemon.json`):

```json
{
  "log-driver": "syslog",
  "log-opts": {
    "syslog-address": "tcp://127.0.0.1:10514",
    "syslog-format": "rfc5424",
    "tag": "docker-{{.Name}}"
  }
}
```

The `tag` value `docker-{{.Name}}` sets the syslog APPNAME to e.g. `docker-authentik-worker-1`. The `docker-` prefix (hyphen, not slash) distinguishes Docker container entries from native system processes (`sshd`, `cron`, `rsyslogd`) in the same syslog stream. In LogsQL, `app_name:~"docker-.*"` selects all Docker container logs; `{app_name="docker-traefik"}` selects a specific container.

> **Why hyphen not slash**: `%programname%` in rsyslog truncates at `/` by design. `docker/traefik` → `docker`. Hyphen is not a separator character so the full name passes through. See §4b.

`tcp://127.0.0.1:10514` sends directly to rsyslog's imtcp listener on the same host. This bypasses journald and preserves the full APPNAME including the `/container-name` portion (see Implementation notes §3).

> **Operational note**: With the `syslog` driver, `docker logs <container>` does not work — there is no local JSON file. Container logs exist only in VictoriaLogs. This is the expected trade-off. During debugging of container startup issues before VictoriaLogs is available (e.g. fresh provision), temporarily switch back to `json-file` in daemon.json, restart Docker, recreate the container, then switch back.

### Branch

`work/syslog-collection` (current) — Phase 7A/7B/7C/7D complete on pve (2026-06-22). Dashboard issues resolved. Next: Phase 7E (pve-test provision + teardown gate), then operational fixes documented in §health-findings below.

---

## Phase 8 — VictoriaLogs MCP Server

### Goal

Expose VictoriaLogs query capabilities to Claude Code (and any MCP client) via the Model Context Protocol, enabling LLM-driven log analysis without ad-hoc shell sessions.

The immediate motivation: systematic log health analysis (§health-findings) required constructing and running multiple API queries by hand. The same patterns, encoded as MCP tools, would make this kind of investigation a natural part of any working session.

### Architecture

**Local stdio MCP server** — a Python process on the dev machine, registered in `~/.claude/claude_code_config.json`. It makes HTTP requests to VictoriaLogs. No new lab infrastructure is required.

```
Claude Code session
      │  MCP stdio
      ▼
victorialogs-mcp/server.py  (Python, runs on dev machine)
      │  HTTP
      ▼
VictoriaLogs :9428  (monitoring-stack, 192.168.20.12)
```

```json
// ~/.claude/claude_code_config.json
{
  "mcpServers": {
    "victorialogs": {
      "command": "python3",
      "args": ["tools/victorialogs-mcp/server.py"],
      "env": { "VICTORIALOGS_URL": "http://192.168.20.12:9428" }
    }
  }
}
```

`VICTORIALOGS_URL` is non-secret (internal lab IP, no auth on VictoriaLogs). It can be hardcoded in the MCP config or read from `.env` at server startup.

### Data model context

Two data populations exist simultaneously. The MCP server's `schema_overview` tool must describe both so the LLM can write correct queries without hallucinating field names.

| Population | Stream labels | Key fields | Expires |
|---|---|---|---|
| Syslog/RFC5424 (current) | `hostname`, `app_name`, `facility`, `severity` | `level`, `facility_keyword`, `proc_id` | permanent |
| Promtail-era (legacy) | `host`, `stack`, `container` or `filename`, `job` | `logger`, `task_id`, `method`, `status`, `user.email` | ~30 days from 2026-06-21 |

Important field behaviours:
- `severity` is a **numeric string** (`"3"` not `"error"`); facility codes are also numeric
- `app_name` starts with `docker-` for Docker containers, plain name for system services
- `hostname` = LXC hostname = stack name (e.g. `netbox-stack`)
- Docker stderr → severity `"3"` (err) regardless of application log level; this is a known false-positive source for container error counts

### VictoriaLogs API endpoints (v1.51.0)

| Endpoint | Returns | Notes |
|---|---|---|
| `/select/logsql/query` | NDJSON log lines | `query`, `start`, `end` (Unix epoch), `limit` |
| `/select/logsql/hits` | `{hits:[{timestamps[], values[], total}]}` | Fast count-over-time; `step` is a duration string (`5m`, `1h`) |
| `/select/logsql/stats_query_range` | Prometheus matrix format | `\| stats by (field) count() as cnt`; `step` is duration string |
| `/select/logsql/field_values` | `{values:[{value, hits}]}` | Distinct values for a named field |
| `/select/logsql/field_names` | `{values:[{value, hits}]}` | All fields present in matching logs |
| `/select/logsql/streams` | `{values:[{value, hits}]}` | Distinct stream label combinations |

### Proposed MCP tools

| Tool | Inputs | Returns | VictoriaLogs endpoint |
|---|---|---|---|
| `search_logs` | `query`, `time_range` (`"1h"`/`"24h"`), `limit` (default 50) | Array of log entries with all fields | `/query` |
| `count_logs` | `query`, `group_by` (field name), `time_range` | `{field_value: count}` dict | `/stats_query_range` |
| `log_volume` | `query`, `time_range`, `step` | `[{time, count}]` | `/hits` |
| `field_values` | `field`, `query`, `time_range`, `limit` | `[{value, hits}]` | `/field_values` |
| `field_names` | `query`, `time_range` | `[{field, hits}]` | `/field_names` |
| `schema_overview` | — | Static description of field model and example queries | (static) |

`schema_overview` is required — without it an LLM will hallucinate field names. It should describe both data populations, numeric severity/facility codes, the `docker-` prefix convention, and example LogsQL patterns.

`search_logs` must cap result size (hard max 500 entries). Encourage callers to use `count_logs` or `aggregate_logs` for "give me a summary" questions and `search_logs` only for specific event investigation.

### Result size management

Raw log queries can return hundreds of thousands of entries. Design guardrails:
- `search_logs`: default `limit=50`, hard cap 500; tool description should recommend aggregate queries for summaries
- `count_logs`: returns a dict, always bounded by number of distinct field values
- `log_volume`: returns a list of time buckets, bounded by `time_range / step`

### LogsQL quick reference (for tool descriptions)

```
# Stream selectors (indexed — fast):
{hostname="netbox-stack"}                        # exact match
{hostname=~".*-stack"}                           # regex
{facility="4"}                                   # auth facility
{severity=~"0|1|2|3"}                           # emerg through err

# Word/phrase filter (full-text search):
"Accepted publickey"                             # phrase
error AND ssh                                    # AND
_msg:~"Accepted|Failed"                          # regex on _msg

# Field filter (message-level, covers pre-stream-label data too):
app_name:="docker-netbox-netbox-1"              # exact
app_name:~"docker-netbox-.*"                    # regex

# Stats (group_by before function):
| stats by (hostname) count() as cnt
| stats by (hostname, severity) count() as cnt

# Time range:  start/end accept Unix epoch or RFC3339
```

### Implementation plan

| # | Task | File | Status |
|---|---|---|---|
| 1 | Create `tools/victorialogs-mcp/server.py` | Python, `mcp` SDK or `fastmcp` | ⏳ pending |
| 2 | Create `tools/victorialogs-mcp/requirements.txt` | `mcp`, `httpx` | ⏳ pending |
| 3 | Register in `~/.claude/claude_code_config.json` | Non-repo config | ⏳ pending |
| 4 | Implement `schema_overview` tool | Static doc of field model | ⏳ pending |
| 5 | Implement `search_logs`, `count_logs`, `log_volume` | Core query tools | ⏳ pending |
| 6 | Implement `field_values`, `field_names` | Discovery tools | ⏳ pending |

Prerequisite: Phase 7E must be complete before this becomes a teardown-gate concern. The MCP server is dev tooling, not stack infrastructure, so it does not block Phase 7E.

---

## Syslog Health Findings — 2026-06-22

Systematic analysis of the VictoriaLogs dataset on 2026-06-22, querying across all 10 hosts over the last 24 hours (~185k log entries at the time). These are the distinct problems found, ranked by priority.

Current status after the follow-up fixes in this branch: Findings 1, 2, and 6 are resolved on pve. Fresh VictoriaMetrics checks show the Proxmox host scrape is absent, the Step CA scrape target is `up`, and fresh VictoriaLogs queries show zero new entries for the old Step CA `https://192.168.20.11:9443/metrics` failure signature. Promtail runtime cleanup is complete: no managed host has an active/enabled Promtail systemd service or running Docker Promtail container, and fresh VictoriaLogs queries show no `failed to start tailer` entries. Findings 3, 4, and 5 remain open (low-frequency/latent).

The same query patterns used here would be encoded as MCP tools in Phase 8, making this kind of investigation reusable across sessions.

### Summary

| # | Issue | Scope | Priority | Status | Fix location |
|---|---|---|---|---|---|
| 1 | VictoriaMetrics cannot scrape `http://:9100/metrics` (empty host) | monitoring-stack | High | Resolved (`2daaa8f`) | scrape config in `deploy-monitoring-stack.yml` |
| 2 | VictoriaMetrics cannot scrape `https://192.168.20.11:9443/metrics` (step-ca) | monitoring-stack | High | Resolved (`3513682`, `6414d37`) | `deploy-step-ca.yml` and scrape config in `deploy-monitoring-stack.yml` |
| 3 | rsyslogd loads `imklog` on LXC hosts (permission denied) | all 10 hosts | Medium | Open/latent; quiet in fresh window unless rsyslog restarts | `rsyslog_forward` role config |
| 4 | rsyslog TCP connection drops to VictoriaLogs `:5140` | all 10 hosts | Medium | Open/latent; quiet in fresh window | `rsyslog_forward` role `omfwd` keepalive |
| 5 | cAdvisor cannot read `/etc/machine-id` (every 5 minutes per host) | all Docker stacks | Medium | Resolved | `lxc_base` machine-id task + cAdvisor bind mounts |
| 6 | Legacy Promtail services/containers still running and logging tailer permission errors | multiple hosts | High | Resolved | `lxc_base` cleanup tasks + compose orphan removal |

### Finding 1 — VictoriaMetrics scraping `http://:9100/metrics` (empty host)

**Observed**: ~6,500 warn messages per day from `docker-victoriametrics`:
```
warn VictoriaMetrics/lib/promscrape/scrapework.go:385
cannot scrape target "http://:9100/metrics" ({instance=":9100",job="node",...})
```
The instance label is `":9100"` — the IP is blank.

**Cause**: A node_exporter entry in the VictoriaMetrics scrape config in `deploy-monitoring-stack.yml` resolved from the old `LAB_IP_PROXMOX_HOST` variable. That variable was absent in the active environment, producing `http://:9100`.

**Fix**: Remove the bare-metal Proxmox host from the `node_exporter` scrape job. The Proxmox host should not run node_exporter as part of this architecture; when Proxmox host logs are needed, configure remote syslog forwarding to the monitoring stack instead.

**Verification**: After deploying monitoring-stack, the rendered scrape config contains only managed LXC `node_exporter` targets and VictoriaLogs shows zero fresh `http://:9100/metrics` scrape failures.

### Finding 2 — VictoriaMetrics scraping `https://192.168.20.11:9443/metrics` (step-ca)

**Observed**: ~2,880 warn messages per day:
```
warn cannot scrape target "https://192.168.20.11:9443/metrics" ({instance="192.168.20.11:9443",job="step-ca",...})
```
Every 30 seconds, continuously.

**Cause**: The step-ca deployment listens on `:443`, not `:9443`. Live probes also showed `/health` returns `200` on `:443`, while `/metrics` returns `404`; `:9443` refuses connections. The VictoriaMetrics container already had the homelab root CA mounted, so this was an endpoint/configuration mismatch rather than a CA trust failure.

**Fix**: First removed the bad HTTPS scrape to stop the warning storm, then enabled Step CA's native `metricsAddress` on HTTP `:9443` and restored the scrape against that real endpoint.

**Verification**: `step-ca` now listens on both `:443` and `:9443`; `http://192.168.20.11:9443/metrics` returns `step_ca_*` metrics; VictoriaMetrics reports `step-ca 192.168.20.11:9443` as `up`; `step_ca_uptime_seconds` is queryable; VictoriaLogs shows zero fresh entries for the old bad HTTPS scrape signature.

### Finding 3 — rsyslogd `imklog` permission denied on all LXC hosts

**Observed**: 4–8 error events per host per day (fires on every rsyslog restart):
```
[rsyslogd] imklog: cannot open kernel log (/proc/kmsg): Permission denied
[rsyslogd] activation of module imklog failed
```
Affects all 10 managed LXC hosts.

**Cause**: Debian's default rsyslog package includes `imklog` (kernel log module) in `/etc/rsyslog.conf`. LXC containers do not have access to `/proc/kmsg` — this is a container security boundary.

**Fix**: Add a line to the rsyslog_forward role's `victorialogs.conf.j2` template (or a separate snippet) that explicitly unloads or disables `imklog`:
```
# Disable kernel log module — LXC containers cannot access /proc/kmsg
module(load="imklog" PermitNonKernelFacility="off")
```
Or more cleanly, write a `/etc/rsyslog.d/10-no-imklog.conf` snippet in the role that overrides the default `/etc/rsyslog.conf` include:
```
# Suppress imklog — not available in LXC containers
module(load="imklog" PermitNonKernelFacility="off")
```
Alternatively, if the role owns `/etc/rsyslog.conf` entirely, replace the default with one that omits the `imklog` include. File: `terraform/lxc/ansible/roles/rsyslog_forward/`.

### Finding 4 — rsyslog TCP connection drops to VictoriaLogs

**Observed**: All 10 hosts experience periodic TCP connection drops to `192.168.20.12:5140` — 4–20 per host per day (102 total). rsyslog reconnects automatically and re-queues; no log data is lost. Each drop generates two error log lines from rsyslogd:
```
omfwd: remote server closed connection. Server is 192.168.20.12:5140.
ptcp network driver: CheckConnection detected that peer closed connection.
```

**Cause**: VictoriaLogs closes idle TCP connections after a timeout (likely its default keepalive or idle-connection timeout). rsyslog's `omfwd` action does not send TCP keepalives by default, so idle periods (when a host has no log events for a while) cause the connection to be silently dropped by the remote side.

**Fix**: Add `tcp.KeepAliveInterval` or configure keepalive in the `omfwd` action in `victorialogs.conf.j2`:
```
action(type="omfwd"
       ...
       tcp.KeepAliveInterval="30"
       tcp.KeepAliveProbes="3"
       tcp.KeepAliveTime="300")
```
This causes rsyslog to send TCP keepalive probes on the idle connection, preventing VictoriaLogs from timing it out. File: `terraform/lxc/ansible/roles/rsyslog_forward/templates/victorialogs.conf.j2`. Apply to both the system-log `omfwd` action and the docker-tcp ruleset `omfwd` action.

### Finding 5 — cAdvisor cannot read `/etc/machine-id`

**Observed**: Every 5 minutes on every host running cAdvisor (monitoring-stack, portainer-stack, harbor-stack, netbox-stack, authentik-stack, proxy-stack):
```
[docker-cadvisor] E info.go:119] Failed to get system UUID: open /etc/machine-id: no such file or directory
```

**Cause**: cAdvisor reads `/etc/machine-id` to generate a stable machine UUID for its metrics. The relevant path is inside the cAdvisor container, not just under `/rootfs`, so having `/rootfs/etc/machine-id` available is insufficient.

**Fix**: Ensure each LXC has `/etc/machine-id` via `lxc_base`, then bind-mount that file into every cAdvisor container:
```yaml
volumes:
  - /etc/machine-id:/etc/machine-id:ro
```

This gives cAdvisor a stable LXC-local machine identity without adding any new service to the host.

**Verification**: Reprovisioned `authentik-stack`, `harbor-stack`, `monitoring-stack`, `netbox-stack`, `portainer-stack`, and `proxy-stack` on 2026-06-22. Direct Docker inspection confirmed each active cAdvisor container had `/etc/machine-id:/etc/machine-id:ro`, and `test -s /etc/machine-id` passed inside each container. VictoriaMetrics reported no unhealthy active targets. VictoriaLogs had no `Failed to get system UUID` events after `2026-06-22T02:55:00Z`, beyond the post-restart window.

### Finding 6 — Legacy Promtail still running

**Observed**: Fresh VictoriaLogs queries after the syslog cutover show Promtail still emitting repeated tailer permission errors. In a 10-minute window, each of `ci-runner-01`, `dns-stack`, `apt-cacher-stack`, and `harbor-stack` emitted roughly 240 `failed to start tailer` events from `promtail`, usually for files such as `/var/log/auth.log`, `/var/log/cron.log`, `/var/log/user.log`, and `/var/log/apt/term.log`.

Runtime checks also found legacy Promtail still active in more than one form:
- systemd `promtail` on systemd-managed stacks such as `harbor-stack`, `dns-stack`, `apt-cacher-stack`, `step-ca`, and `ci-runner-01`
- Docker Promtail containers on Docker stacks such as `portainer-stack`, `proxy-stack`, `authentik-stack`, and `netbox-stack`

**Cause**: The intended logging path is now rsyslog/VictoriaLogs. Promtail was removed from the desired architecture, but pre-existing runtime services and compose orphans were not fully cleaned up across all stacks.

**Fix**: Added idempotent systemd/package cleanup to `lxc_base` and enabled compose orphan removal for stacks that had stale Docker Promtail containers. Reprovisioned the affected stacks.

**Verification**: A live sweep of all managed hosts showed `promtail` inactive or not found in systemd and no Docker containers with `promtail` in the name. Fresh VictoriaLogs queries showed no `failed to start tailer` entries.

### Known behaviours (not bugs)

**Docker stderr → severity=3 inflation**: All Docker containers write stderr output as syslog severity `3` (err), regardless of the application's actual log level. This is a Docker syslog driver behaviour — Docker maps stderr→err, stdout→info. The result is that aggregate "error" counts by host and the `severity` stream label are not reliable indicators of real error rates for containerised services. In VictoriaLogs, `severity` is meaningful for journald/systemd service logs (where systemd correctly maps the journal priority to syslog severity) but is a blunt instrument for Docker container logs.

To get the real log level from a Docker container, parse the `_msg` content — most structured loggers (Authentik, NetBox, VictoriaMetrics) embed their level in a JSON field (`"level"`, `"severity"`, or similar). This is a target use case for the MCP server's `schema_overview` tool and for future structured log extraction work.

**cAdvisor machine-info message fragmentation**: cAdvisor logs its complete machine hardware description at startup as a single large structured string. This exceeds the rsyslog message size limit and gets split across multiple syslog frames. The continuation frames lack correct syslog headers, so VictoriaLogs parses them with garbage `hostname` values (`localhost`, `df`, numeric strings like `04886016`). These appear as valid log entries with `facility="1"` (user) and `severity="5"` (notice). They are harmless and will be eliminated by fixing Finding 5 (once cAdvisor has `/etc/machine-id`, the machine-info log line disappears from the output) or by applying rsyslog `$MaxMessageSize` limits.
