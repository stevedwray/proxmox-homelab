# Production Stack Reboot Audit (via Graylog)

## Purpose

First real-world use of the newly-deployed production Graylog rollout
(see [graylog-migration-plan.md](./graylog-migration-plan.md)): the operator
is rebooting each managed `pve` stack in turn, and Graylog is used to watch
each stack's boot sequence for errors or latent breakage that hadn't been
noticed before centralized logging existed.

## Method

For each stack: reboot it, then query Graylog's search API
(`source:<stack>`, recent time range) and read the actual boot sequence —
not just severity-filtered (`level:0-3`) results. See the note under
ci-runner-01 below: real failures can log at informational severity, so
filtering by level alone is not sufficient.

## Findings by stack

### ci-runner-01 (2026-07-06)

**🔴 GitHub Actions runner service down — needs re-registration.**

Boot itself was clean (Docker containers, Portainer agent, networking all
came up normally, ~1.6s systemd startup). But the GitHub Actions self-hosted
runner failed to reconnect:

```
runsvc.sh: √ Connected to GitHub
runsvc.sh: Failed to create a session. The runner registration has been deleted from the server,
           please re-configure. Runner registrations are automatically deleted for runners that
           have not connected to the service recently.
runsvc.sh: Runner listener exited with error code 1
runsvc.sh: Runner listener exit with terminated error, stop the service, no retry needed.
systemd:   actions.runner.stevedwray-proxmox-homelab.ci-runner-01.service: Deactivated successfully.
```

GitHub auto-deletes a self-hosted runner's registration if it hasn't
connected in a while. The systemd service gave up after one failed attempt
rather than retrying indefinitely.

**Impact:** the runner is currently down and will not pick up any GitHub
Actions jobs for this repo until fixed.

**Fix required (not yet done):** generate a fresh registration token from
the GitHub repo/org settings (Settings → Actions → Runners → New
self-hosted runner), then re-run the runner's `config.sh` with that token
on `ci-runner-01`, and restart the `actions.runner.*` systemd service.

**Notable methodology finding:** all of the failure messages above logged at
`level:6` (informational) — a `level:(0 1 2 3)` severity-filtered search on
`ci-runner-01` over the same window returned **zero** results. Severity
alone would have missed this entirely; the failure was only visible by
reading actual message content.

**Status:** identified, not yet fixed.

---

### step-ca-stack (2026-07-06)

**✅ Clean boot, no issues.**

Two benign warnings during systemd-networkd/docker.service startup
(`Referenced but unset environment variable... DOCKER_OPTS`, `Failed to
increase receive buffer size for general netlink socket, ignoring:
Operation not permitted`, `Unable to load sysctl monitor BPF program,
ignoring`) — all expected in an unprivileged LXC container (no
`CAP_NET_ADMIN` for those specific kernel tuning operations); explicitly
"ignoring" in the log, no functional impact.

**Methodology note:** `step-ca` runs as a **native systemd service**
(`step-ca.service`), not a Docker container — searching
`application_name:docker-*` for this source found nothing (only
`portainer-agent`, which *is* Docker), which looked like a missing-service
red flag until re-checked without that filter. The actual CA process starts
and logs cleanly:

```
systemd:  Started step-ca.service - step-ca internal certificate authority.
step-ca:  badger: All 1 tables opened in 1ms, replay took 12.143µs (no corruption)
step-ca:  Starting Smallstep CA/0.30.2 (linux/amd64)
step-ca:  Serving HTTPS on :443 ...
step-ca:  Serving HTTP on :9443 ...
```

No `level:(0 1 2 3)` messages at all for this source over the reboot window.

**Status:** verified healthy, no action needed.

---

### apt-cacher-stack (2026-07-06)

**✅ Clean boot, no issues.**

Same benign unprivileged-LXC warnings as the other stacks (`DOCKER_OPTS`
unset, netlink buffer size, sysctl BPF — all "ignoring", no impact). Only
`portainer-agent` shows Docker Compose activity; the actual caching daemon
is confirmed via systemd's own service-start line:

```
systemd: Started apt-cacher-ng.service - Apt-Cacher NG software download proxy.
```

`apt-cacher-ng` doesn't log anything beyond systemd's start confirmation on
a normal healthy boot, so an `application_name:apt*` search alone came up
empty — same "quiet native service" pattern as `step-ca`. No `level:(0 1 2
3)` messages for this source over the reboot window.

**Status:** verified healthy, no action needed.

---

### netbox-stack (2026-07-06)

**🔴 `netbox-populate.service` failed on boot.**

Docker side came up cleanly (redis, `netbox-worker`, `netbox` app server all
started normally, granian serving on `:8080`, workers spawned). Correctly
surfaced at proper severity levels this time (not buried in informational,
unlike the ci-runner-01 finding):

```
systemd (level 5): netbox-populate.service: Main process exited, code=exited, status=1/FAILURE
systemd (level 4): netbox-populate.service: Failed with result 'exit-code'.
systemd (level 3): Failed to start netbox-populate.service - Populate NetBox with live Proxmox topology.
```

**Impact:** this one-shot service syncs NetBox's DCIM records with the live
Proxmox topology (VMs/containers/inventory). It failed after this reboot,
so NetBox's device/inventory records may be stale relative to actual
running infrastructure until this is re-run successfully.

**Gap found in the process, not just the target:** the script's own
stdout/stderr (which would explain *why* it exited 1) never reached
Graylog — searched `application_name:netbox-populate` and the exact
timestamp window (`00:40:44`–`00:40:52Z`) with no source filter narrower
than the whole stack, found nothing beyond the generic systemd
start/exit/failed lifecycle lines. Unlike `step-ca`/`apt-cacher-ng`
(oneshot/long-running native services whose own print output *does* reach
Graylog fine), this particular script's output didn't come through for this
failure. Root cause not yet investigated — will need `journalctl -u
netbox-populate.service` directly on the host to see the actual error.

**Fix required (not yet done):** investigate why `netbox-populate.service`
exited 1 (likely needs direct host access, since Graylog doesn't have the
detail) and re-run it manually once fixed:
`systemctl status/restart netbox-populate.service` on `netbox-stack`.

Also noted: `GET /api/ HTTP/1.1" 403` shortly after startup — expected
behavior (unauthenticated API root request), not an error.

No other `level:(0 1 2 3)` messages for this source over the reboot window.

**Status:** identified, not yet fixed.

---

### harbor-stack (2026-07-06)

**⚠️ Blind spot, not a break — Harbor's own containers are invisible to
Graylog.** No `level:(0 1 2 3)` messages, and the *only* `application_name`
values seen for this source across the whole reboot were system-level
(`systemd`, `dockerd`, `containerd`, `sshd`, `cron`, `postfix`,
`rsyslogd`, etc.) plus `docker-cadvisor` and generic `docker-compose`
lines. **No `docker-harbor-*` entries at all** — core, registry,
jobservice, portal, database, redis, and trivy are all silent here.

This is a known, pre-existing, *accepted* limitation, not a new regression:
Harbor's own installer (`/opt/harbor/`) writes its own `docker-compose.yml`
with per-service `logging:` blocks that override the Docker daemon's global
syslog default the rest of the stacks rely on (documented back in Phase 7
research — see `design.md`'s "Harbor special case" notes).

**Practical consequence:** this reboot audit **cannot confirm Harbor's
actual internal services came back up correctly** — Graylog has no
visibility into them. Verify Harbor itself via Portainer, `docker ps` on
the host, or Harbor's own UI/health API, not via this log review.

**Status:** no action needed for the audit itself, but flagging the blind
spot — a real fix (if ever prioritized) would mean overriding Harbor's
installer-generated compose to route through the shared logging driver,
which was previously evaluated and explicitly deferred as not worth the
complexity/risk of touching installer-managed config.

---

### portainer-stack (2026-07-06)

**✅ Clean boot — but a good real example of the stderr→level:3 false-positive
pattern.**

`level:(0 1 2 3)` returned a batch of hits from `docker-cadvisor` and
`docker-portainer-portainer-1`, which looked alarming until the actual
message content was read:

- `docker-cadvisor`: "Registration of the crio/mesos/podman container
  factory failed" — expected; cAdvisor probes for multiple container
  runtimes on startup and only Docker is actually present here. "Could not
  configure a source for OOM detection... /dev/kmsg: no such file or
  directory" — expected unprivileged-LXC limitation (same class as the
  netlink-buffer/BPF restrictions seen on other stacks); cAdvisor degrades
  gracefully rather than crashing.
- `docker-portainer-portainer-1`: every line is genuinely `INF`
  (informational) per Portainer's own log text — DB load, per-environment
  post-init migrations, HTTPS/HTTP servers starting on `:9443`/`:9000`,
  Chisel reverse-tunnel service starting. Nothing wrong.

**Root cause of the false positive:** both cAdvisor and Portainer write
their *entire* log output to stderr regardless of actual severity, and
Docker's syslog driver maps stderr→`level:3` (err) unconditionally — this
is the exact "not perfectly reliable" caveat already documented for the
stdout→info/stderr→err mapping (see `design.md`'s Phase 7 notes), now
concretely observed. Where ci-runner-01 was a **false negative** (a real
failure logged at `level:6`), this is the mirror-image **false positive**
(routine output logged at `level:3`) — reinforcing the same lesson from
both directions: read actual message content, don't trust severity alone.

**Status:** verified healthy, no action needed.

---

### monitoring-stack (2026-07-06)

**✅ Fundamentally healthy — Grafana and VictoriaMetrics both came up
cleanly** (`HTTP Server Listen address=[::]:3000`, migrations completed
`skipped=23` = no pending migrations, VictoriaMetrics `static_configs: added
targets: 30`, scrape service discovery started). `level:(0 1 2 3)` returned
zero results for the whole stack. Two minor, non-blocking items surfaced by
reading actual content, neither a functional break:

1. **Grafana logs genuine `level=error`** (its own structured logging, not a
   stderr-mapping artifact this time) for two provisioning directories that
   don't exist:
   ```
   logger=provisioning.plugins  error="open /etc/grafana/provisioning/plugins: no such file or directory"
   logger=provisioning.alerting error="open /etc/grafana/provisioning/alerting: no such file or directory"
   ```
   `deploy-monitoring-stack.yml` only creates the `datasources` and
   `dashboards` provisioning subdirectories — `plugins` and `alerting` were
   never created, and Grafana logs this as an error even though it's a
   completely normal, harmless condition (no file-based plugin/alerting
   provisioning is used here). Third variant of the severity-reliability
   theme from this audit: unlike ci-runner-01 (real problem, low severity)
   or portainer-stack (routine output, high severity via stderr-mapping),
   this is genuinely-tagged `error` for a harmless condition. Optional
   cosmetic fix: add empty `plugins`/`alerting` directories to the same
   "Create Grafana directories" task that already creates
   `datasources`/`dashboards`.
2. **Leftover `victoriametrics-logs-datasource` plugin binary still loads**
   (`logger=plugin.victoriametrics-logs-datasource msg="Starting VL
   datasource"`) even though its datasource instance was deleted in P4 and
   `GF_INSTALL_PLUGINS` no longer installs it. `GF_INSTALL_PLUGINS` only
   controls fresh installs — the plugin binary itself persists in Grafana's
   plugins volume from before P4 and isn't uninstalled by removing it from
   the env var. Harmless (loaded but unused, no datasource references it),
   but an incomplete cleanup worth closing out if ever revisited.

Also observed (unrelated, pre-existing, not a regression): VictoriaMetrics
logs periodic `warn`-level "dropping N labels for
`container_blkio_device_usage_total`... increase
`-maxLabelsPerTimeseries=30`" — a well-known cAdvisor high-cardinality
metric interaction, generic to any Prometheus-compatible store scraping
cAdvisor, not specific to this reboot or the Graylog work.

**Status:** verified healthy. Two optional cosmetic cleanup items noted,
neither blocking.

---

## Query pattern used

```
source:<stack-name>
```
over a relative time range covering the reboot, sorted by timestamp,
reading `application_name` and `message` fields directly rather than
relying on `level` filtering alone.
