# Docker log-driver audit (LXC stacks)

**Status:** audit + proposal only. Nothing in this document has been applied.
No playbook, role, or template was changed on the branch that added it.

**Scope:** every `terraform/lxc/ansible/playbooks/deploy-*.yml` (39 playbooks),
the compose files under `terraform/lxc/stacks/*/docker-compose.yml` and
inline compose content, plus `roles/docker_base`, `roles/lxc_base`, and
`roles/rsyslog_forward`. Bare-metal Framework
(`ansible/00-initial-setup/framework-desktop-bootstrap.yml`) is mentioned only
where it cross-references `docker_base`.

**Method:** static read of the repo on `stable` (2026-09-27). No live host was
inspected. The on-host `/etc/docker/daemon.json`, Docker versions, and actual
log volumes are **not verified**. See "Read-only checks still owed" at the end.

---

## 1. How logs reach Graylog today

```
container stdout/stderr
   │  Docker "syslog" log-driver, set daemon-wide in /etc/docker/daemon.json
   │  syslog-address tcp://127.0.0.1:10514, syslog-format rfc5424,
   │  tag docker-{{.Name}}
   ▼
local rsyslog imtcp 127.0.0.1:10514  (ruleset "docker-tcp", RFC 5424 parser)
   │  omfwd TCP, LinkedList queue graylog-fwd-docker, maxDiskSpace 32m,
   │  resumeRetryCount -1
   ▼
Graylog host  $LAB_IP_GRAYLOG : 514/tcp   (and 514/udp)
   │  rsyslog on the graylog-stack LXC (rsyslog_inbound_enabled=true)
   │  ruleset "ext-tcp" → omfwd 127.0.0.1:5140
   ▼
Graylog SyslogTCPInput "syslog-tcp-5140" (container publishes 127.0.0.1:5140)
```

Where each piece is defined:

| Piece | File:line |
|---|---|
| Graylog container port `127.0.0.1:5140` (plus UI `9000`) | `playbooks/deploy-graylog-stack.yml:286-288` |
| Graylog input `syslog-tcp-5140` (`SyslogTCPInput`, global) | `playbooks/deploy-graylog-stack.yml:525-556` |
| Graylog-host rsyslog relay (`:514` tcp+udp → `127.0.0.1:5140`) | `playbooks/deploy-graylog-stack.yml:118-124`, `roles/rsyslog_forward/templates/graylog_inbound.conf.j2` |
| Per-host forwarder (all system logs + Docker `:10514` → `$LAB_IP_GRAYLOG:514`) | `roles/rsyslog_forward/templates/log-forwarding.conf.j2:12-42`, defaults `roles/rsyslog_forward/defaults/main.yml:2-3` |
| Per-host forwarder is installed on every LXC | `roles/lxc_base/tasks/main.yml:126-129` (gated on `monitoring_enabled`, default true, never set false in the repo) |
| Docker waits for rsyslog at boot (fixes the syslog-driver boot race) | `roles/docker_base/tasks/main.yml:29-55` |

There is **no GELF input** anywhere in the repo. The only ingestion path for
container logs is the syslog driver → local rsyslog → Graylog `:514` → `:5140`.

Every stack that runs `lxc_base` already ships its **host** system logs (journald
via imuxsock) to Graylog. The only question this audit answers is whether
**container** stdout/stderr gets there too.

`docker_base` does **not** write `daemon.json` and sets no log-driver default.
Each stack sets it (or doesn't) in its own playbook, almost always inside the
same `copy` task that sets `insecure-registries`/`dns`.

---

## 2. Per-stack table

Legend for "Reaches Graylog":
**Yes** = container logs go through the syslog driver.
**Host only** = host system logs go to Graylog, container logs don't.
**N/A** = no Docker workload.

Paths are relative to `terraform/lxc/ansible/`.

### 2a. Daemon-wide `syslog` → Graylog (23 playbooks)

All use the same options: `syslog-address: tcp://127.0.0.1:10514`,
`syslog-format: rfc5424`, `tag: docker-{{.Name}}`. None set `max-size` or
`max-file`. Those options don't apply to the syslog driver, and Docker's
dual-logging local cache is bounded by default. "Extra daemon keys" lists the
other things the same task controls, which matters for the proposal in §4.

| Stack / playbook | Where configured (file:line) | Extra daemon keys | docker_base? | Notes |
|---|---|---|---|---|
| authentik-stack | `playbooks/deploy-authentik-stack.yml:429` (task at :421) | insecure-registries, dns, storage-driver | yes | Login-critical. See §3 risk R7. |
| ci-runner | `playbooks/deploy-ci-runner.yml:345` (task at :338) | insecure-registries, storage-driver | **no** | Doesn't include `docker_base`, so it lacks the rsyslog-ordering drop-in (R6). |
| cse-code-eval | `playbooks/deploy-cse-code-eval.yml:50` | storage-driver, live-restore | yes | Fixed 2026-09 (cse-panel-14). |
| cse-controller | `playbooks/deploy-cse-controller.yml:39` | storage-driver, live-restore | yes | Fixed 2026-09 (cse-panel-14). |
| cse-panel-stack | `playbooks/deploy-cse-panel-stack.yml:26` | insecure-registries, storage-driver, live-restore | yes | Runs on pve-tiny. |
| gaming-stack-lab | `playbooks/deploy-gaming-stack-lab.yml:39` | insecure-registries, storage-driver | yes | Also the host for minecraft-wildworks (2c). |
| graylog-stack | `playbooks/deploy-graylog-stack.yml:28` | insecure-registries, dns, storage-driver | yes | **Ships its own logs to itself** (R4). Its playbook runs `docker logs` at :383 (R5). |
| greenbone-stack | `playbooks/deploy-greenbone-stack.yml:55` | insecure-registries | yes | Switched from json-file on 2026-09-08. |
| harbor-stack | `playbooks/deploy-harbor-stack.yml:21` (var at :18, written at :35) | dns, storage-driver | yes | **Only partly in Graylog.** Harbor's own services log to `/var/log/harbor` (`roles/harbor_installer/templates/harbor.yml.j2:56-61`, rotate 50 × 200M, no `external_endpoint`). See R8. |
| media-stack-lab | `playbooks/deploy-media-stack-lab.yml:44` | insecure-registries, storage-driver | yes | |
| monitoring-stack | `playbooks/deploy-monitoring-stack.yml:37` | insecure-registries, dns, storage-driver | yes | |
| netbox-stack | `playbooks/deploy-netbox-stack.yml:101` | insecure-registries, dns, storage-driver | yes | Force-recreate on change at :255. |
| nextcloud-stack | `playbooks/deploy-nextcloud-stack.yml:42` | storage-driver | yes | |
| opensearch-stack | `playbooks/deploy-opensearch-stack.yml:56` | insecure-registries, dns, storage-driver | yes | |
| pangolin-proxy | `playbooks/deploy-pangolin-proxy.yml:20` | insecure-registries, storage-driver | yes | |
| portainer-agent | `playbooks/deploy-portainer-agent.yml:25` | insecure-registries, storage-driver | yes | |
| portainer-stack | `playbooks/deploy-portainer-stack.yml:22` (var `docker_daemon_config_base`, written at :46 pre-task and :66) | dns, insecure-registries (conditional), storage-driver | yes | Only stack that builds daemon.json from a dict + `combine`. The proposal copies this pattern. |
| proxy-stack (Traefik) | `playbooks/deploy-proxy-stack.yml:22` | insecure-registries, storage-driver | yes | Routing-critical (R7). |
| pterodactyl-lab | `playbooks/deploy-pterodactyl-lab.yml:35` | insecure-registries, storage-driver | yes | |
| deploy-stack.yml (generic app stacks) | `playbooks/deploy-stack.yml:24` | insecure-registries, storage-driver | yes | |
| technitium-stack | `playbooks/deploy-technitium-stack.yml:27` | insecure-registries, storage-driver | yes | **Lab DNS.** A Docker restart means a DNS outage (R7). |
| torrent-stack-lab | `playbooks/deploy-torrent-stack-lab.yml:52` | insecure-registries, storage-driver | yes | |
| wazuh-stack | `playbooks/deploy-wazuh-stack.yml:61` | insecure-registries, dns, storage-driver | yes | |

### 2b. Daemon-wide `json-file` with rotation, not in Graylog (5 playbooks)

All use `max-size: 50m`, `max-file: 7`, so the cap is about 350 MB per container.
Disk growth is bounded, but container logs **never reach Graylog**. Only the
host's system logs do.

| Stack / playbook | Where configured (file:line) | Per-service overrides | Reaches Graylog | Notes |
|---|---|---|---|---|
| ai-services-stack | `playbooks/deploy-ai-services-stack.yml:33` (daemon) | `deep-research` and `deep-research-files` override to syslog at `:564-569` and `:614-619` | **Mixed**: 2 services yes, `openwebui`/`searxng`/others no | The compose comment at `:373-374` says the services "inherit the host-level Docker daemon **syslog** log-driver". That's wrong: the daemon default here is json-file (R3). |
| mcp-utility-stack | `playbooks/deploy-mcp-utility-stack.yml:64` | none | Host only | No comment explaining why it's json-file. |
| pentagi-stack | `playbooks/deploy-pentagi-stack.yml:38` (daemon) | compose `logging: options: {max-size: 50m, max-file: "7"}` with **no `driver:`** at `:591`, `:616`, `:645`, `:663` | Host only | Deliberate, per `docs/mcp-stack/plan.md:621`. The driver-less per-service options block a daemon-level switch (R2). PentAGI also starts worker containers through docker.sock, and those inherit the daemon default. |
| pentagi-upstream-control | `playbooks/deploy-pentagi-upstream-control.yml:43` | unknown: compose read verbatim from an external `/home/steve/git/pentagi` ref at `:14` | Host only | Intentionally a vanilla upstream control. Its compose can't be audited from this repo (R2). |
| pentagi-upstream-vanilla-companion | `playbooks/deploy-pentagi-upstream-vanilla-companion.yml:57` | unknown: verbatim upstream compose, `:25` | Host only | Same as above. |

> The task brief said "about 6" json-file stacks. On current `stable` there
> are 5 explicit json-file playbooks. greenbone-stack (2026-09-08),
> media-stack-lab, and cse-controller/cse-code-eval have since moved to
> syslog. Separately, 4 Docker stacks have **no** config at all (2c). That's
> the worse case.

### 2c. Docker workload, no `daemon.json` written: Docker's built-in default (5 playbooks)

With no `daemon.json`, Docker uses `json-file` **with no rotation**, so log
files grow without limit.

| Stack / playbook | Where configured | Effective driver | Rotation | Reaches Graylog | Notes |
|---|---|---|---|---|---|
| cse-kali | nowhere (compose `terraform/lxc/stacks/cse-kali/docker-compose.yml` has no `logging:`) | json-file (Docker default) | **none** | Host only | Container runs `sleep infinity`, so there's little stdout. Low practical risk. |
| docker-socket-proxy-test | nowhere (`stacks/docker-socket-proxy-test/docker-compose.yml`) | json-file (Docker default) | **none** | Host only | Test stack. |
| harness-target | nowhere (`stacks/harness-target*/docker-compose.yml`) | json-file (Docker default) | **none** | Host only | Pentest target. Traffic-driven logs can grow. |
| newt-connector | nowhere | json-file (Docker default) | **none** | Host only | Long-lived tunnel connector. Most likely of these to grow unnoticed. |
| minecraft-wildworks | none of its own (`deploy-minecraft-wildworks.yml` targets the gaming-stack-lab LXC, which has no `lxc_base`/`docker_base`) | **inherits the host's daemon.json**, which `deploy-gaming-stack-lab.yml:39` sets to syslog | n/a (syslog) | Yes, only while gaming-stack-lab's daemon.json is in place | Counted here because it doesn't configure anything itself. Actual effective state is "syslog via host". |

### 2d. No Docker workload (6 playbooks)

All run `lxc_base`, so their host/systemd logs reach Graylog through rsyslog.

| Stack | Service type | Source |
|---|---|---|
| apt-cacher-stack | systemd (apt-cacher-ng) | `playbooks/deploy-apt-cacher-stack.yml` |
| comfyui-stack | native systemd (ROCm) | `roles/comfyui_stack/tasks/main.yml:1` |
| coredns (dns-stack) | systemd | `playbooks/deploy-coredns.yml` |
| llm-gpu-stack | native systemd (llama-router) | `roles/llm_gpu_stack/tasks/main.yml:1` |
| secpipe-stack | Python + systemd timers | `playbooks/deploy-secpipe-stack.yml:1-6` |
| step-ca | systemd (step-ca) | `playbooks/deploy-step-ca.yml` |

### 2e. `roles/docker_base`

| Item | File:line | Finding |
|---|---|---|
| daemon.json / log-driver | none | The role doesn't write `daemon.json` or set any log driver. |
| rsyslog ordering drop-in | `roles/docker_base/tasks/main.yml:29-55` | Only helps stacks that include `docker_base`. ci-runner doesn't. |
| Comment at `:9-13` | `roles/docker_base/tasks/main.yml:9-13` | Says "every stack's own deploy playbook configures … syslog". That's false for 9 of the 33 Docker-bearing playbooks (all of 2b and 2c except minecraft-wildworks). |

### Counts

| Logging state | Playbooks |
|---|---|
| syslog → Graylog, daemon-wide | 23 |
| json-file with rotation (50m × 7), not in Graylog (1 of these partly overridden to syslog) | 5 |
| No config: Docker default json-file, **no rotation** | 4 (+ minecraft-wildworks, which inherits syslog from its host) |
| No Docker workload | 6 |
| **Total** | **39** |

---

## 3. Risks and inconsistencies

**R1: unbounded json-file logs on 4 stacks (disk-fill).** cse-kali,
docker-socket-proxy-test, harness-target, and newt-connector have no
`daemon.json`, so container logs grow without limit under
`/var/lib/docker/containers/*/*-json.log`. `docker-image-prune` doesn't clean
them. The fleet's disk-full history (greenbone 2026-09-08) makes this the
highest-priority fix. newt-connector and harness-target matter most. Their
container logs also don't reach Graylog.

**R2: per-service `logging.options` without `driver:` (pentagi family).**
In `deploy-pentagi-stack.yml:591/616/645/663`, the compose `logging:` blocks
set only `options` (`max-size`, `max-file`). Compose applies those to the
**daemon default** driver. If the daemon default changes to syslog, those
options become invalid for the syslog driver and container create/recreate
fails. Any daemon-level change on pentagi-stack must first add
`driver: json-file` to those blocks, remove them, or switch to syslog options.
pentagi-upstream-control and -vanilla-companion deploy upstream compose
verbatim from an external repo, so this can't be checked here. Treat them the
same way and leave them on an explicit json-file override.

**R3: misleading comments and docs that describe a default that doesn't exist.**
- `deploy-ai-services-stack.yml:373-374` says services inherit a daemon
  *syslog* default, but the daemon is json-file (`:33`), so
  `openwebui`/`searxng` logs stay local.
- `roles/docker_base/tasks/main.yml:9-13` says every stack sets syslog.
- `deploy-greenbone-stack.yml:38-39` says "docker_base's syslog default".
- `docs/torrent-stack-modernization/plan.md:432-433` says containers "inherit
  docker_base's syslog-to-Graylog default".
- `ansible/00-initial-setup/framework-desktop-bootstrap.yml:490` refers to
  "docker_base role's daemon.json.j2". No such template exists.
- `terraform/lxc/README.md:169` says docker_base "optionally configures a
  registry mirror via /etc/docker/daemon.json … `docker_base_configure_mirror`".
  Neither the behaviour nor the variable exists.
- `docs/monitoring-stack/design.md:836` says `docker logs` "does not work"
  with the syslog driver. That's stale. Since Docker Engine 20.10, *dual
  logging* keeps a local read cache for remote drivers by default
  (`cache-disabled=false`, about 20 MB × 5 files per container, compressed).
  The template installs Debian 13 `docker.io` (26.x) or upstream `docker-ce`,
  both well past 20.10. deploy-graylog-stack.yml already depends on this
  (R5). Live Docker version is unverified.

These comments are how the "json-file gap" spread: new stacks copied whichever
playbook they started from.

**R4: Graylog ships its own container logs to itself.**
graylog-stack uses the syslog driver, so its Graylog, DataNode, and Mongo
containers log through rsyslog `:10514` → `127.0.0.1:5140` on the same host.
When Graylog is unhealthy, which is exactly when its logs matter most, those
lines sit in rsyslog's 32 MB disk-assisted queue (`graylog-fwd-docker`) and
are dropped once it fills. The only other copy is Docker's dual-logging cache.
This is the **existing** state, not something the proposal introduces. The
proposal keeps graylog-stack on syslog and never sets `cache-disabled`, so
`docker logs` stays usable for triage.

**R5: automation that depends on `docker logs`.**
Only one place: `deploy-graylog-stack.yml:379-393` greps the first-boot
preflight password from `docker logs graylog-stack-graylog-1`. That works
under syslog only because of the dual-logging cache. Any change that sets
`cache-disabled: "true"`, or a Docker downgrade below 20.10, breaks cold-start
Graylog provisioning. The `docker_container_info` call in
`deploy-ai-services-stack.yml:310` reads container state, not logs, so it's
unaffected. No other playbook, role, or `scripts/` file runs `docker logs`.

**R6: ci-runner writes a syslog daemon.json but skips `docker_base`.**
So it doesn't get the `After=rsyslog.service` drop-in that fixed the
2026-09-07 boot race, where a container fails with "failed to initialize
logging driver" and isn't retried. Runner job containers are short-lived, so
impact is low, but this is inconsistent.

**R7: any change to daemon.json restarts Docker, and containers keep their
old driver until recreated.**
Every daemon.json task notifies a `Restart Docker` handler. Only the cse-*
stacks set `live-restore`, so everywhere else the restart bounces every
container. On technitium-stack (lab DNS), proxy-stack (Traefik), and
authentik-stack (SSO), that's a real outage. Also, per
`docs/monitoring-stack/design.md` §2, a daemon restart does **not** change the
log driver of existing containers. They must be force-recreated, which only
some playbooks do (for example netbox `:255`). A migration that doesn't
recreate will look applied in daemon.json while containers keep logging the
old way.

**R8: Harbor's application logs aren't in Graylog even though its daemon is syslog.**
Harbor's installer-generated compose points each Harbor service at its own
`harbor-log` container, which writes to `/var/log/harbor` (rotate 50 × 200M,
up to about 10 GB). This is standard upstream Harbor installer behaviour. The
generated compose isn't in this repo, so verify it on the host. Only
`harbor-log` itself (and cadvisor) use the daemon syslog default. Getting
Harbor app logs into Graylog would mean setting `log.external_endpoint` in
`harbor.yml.j2`, which is a separate Harbor-tier change and out of scope here.

**R9: daemon.json is owned by a copy-pasted per-playbook task (structural).**
23+5 near-identical `copy` tasks each own the whole `daemon.json`, mixing
log config with `insecure-registries`, `dns`, `storage-driver`, and
`live-restore`. This duplication caused the json-file gap and the hardcoded
dns-stack IP incident (`reference_dns_stack_docker_daemon_dependency`).

**R10 (minor, unverified): syslog driver uses the default "blocking" mode.**
No stack sets `mode: non-blocking`. Local TCP to rsyslog with a disk queue is
low risk, but a wedged rsyslog could apply back-pressure to container stdout
writes. Not proposed as a default change. Listed as an open question.

---

## 4. Proposal: a docker_base-owned daemon.json with per-stack overrides

> **NOT APPLIED.** The diffs below are a proposal. Nothing on this branch
> changes runtime behaviour.

### Design

1. `docker_base` becomes the single owner of `/etc/docker/daemon.json`,
   behind an opt-in flag `docker_base_manage_daemon_json` (default
   **false**). With the flag off, merging the role change does nothing on
   any stack.
2. The log driver defaults to the fleet convention (syslog → `127.0.0.1:10514`,
   rfc5424, `docker-{{.Name}}`). A stack overrides it with
   `docker_base_log_driver`. For any non-syslog driver the role **always**
   adds rotation (`max-size`/`max-file`), so the unbounded case (R1) can't
   occur on a managed stack.
3. Non-logging keys (`insecure-registries`, `dns`, `storage-driver`,
   `live-restore`) move into one per-stack dict, `docker_base_daemon_extra`,
   merged with `combine`. This is the same pattern `deploy-portainer-stack.yml`
   already uses.
4. The role registers `docker_base_daemon_json`, so stacks can force-recreate
   containers when the driver changes (R7).
5. Stacks migrate one at a time. Each migration sets the flag, moves its
   extras into the dict, and **deletes its own daemon.json task in the same
   commit**. If both wrote the file, it would flap and restart Docker on every
   run.

### Proposed diff: `roles/docker_base/defaults/main.yml` (NOT APPLIED)

```diff
--- a/terraform/lxc/ansible/roles/docker_base/defaults/main.yml
+++ b/terraform/lxc/ansible/roles/docker_base/defaults/main.yml
@@ -27,3 +27,40 @@ docker_base_image_prune_min_age: "24h"
 # harbor_repull_on_calendar's own reasoning).
 docker_base_image_prune_on_calendar: "*-*-* 03:47:00"
+
+# --- /etc/docker/daemon.json ownership (docs/logging/docker-log-driver-audit.md) ---
+# Opt-in per stack while stacks migrate off their own hand-written
+# daemon.json copy task. A stack that sets this true MUST delete its own
+# daemon.json task in the same change, or the two will flap.
+docker_base_manage_daemon_json: false
+
+# Fleet default: container stdout/stderr -> local rsyslog :10514 -> Graylog.
+# Override per stack only with a written reason (e.g. pentagi-stack's
+# per-service json-file options, see audit R2).
+docker_base_log_driver: syslog
+
+docker_base_log_opts_by_driver:
+  syslog:
+    syslog-address: "tcp://127.0.0.1:10514"
+    syslog-format: rfc5424
+    tag: "{% raw %}docker-{{.Name}}{% endraw %}"
+    # Never set cache-disabled: deploy-graylog-stack.yml reads `docker logs`
+    # via Docker's dual-logging cache (audit R5).
+  json-file:
+    max-size: "50m"
+    max-file: "7"
+  local:
+    max-size: "50m"
+    max-file: "7"
+
+# Rotation is always present for non-syslog drivers; a stack can still
+# replace the whole dict if it really needs to.
+docker_base_log_opts: "{{ docker_base_log_opts_by_driver[docker_base_log_driver] | default({'max-size': '50m', 'max-file': '7'}) }}"
+
+# Everything else a stack needs in daemon.json (insecure-registries, dns,
+# storage-driver, live-restore, ...). Merged over the logging keys.
+docker_base_daemon_extra: {}
+
+docker_base_daemon_config: >-
+  {{ {'log-driver': docker_base_log_driver, 'log-opts': docker_base_log_opts}
+     | combine(docker_base_daemon_extra) }}
```

### Proposed diff: `roles/docker_base/tasks/main.yml` (NOT APPLIED)

This goes before "Ensure Docker service is running", so a fresh host starts
Docker with the right config the first time.

```diff
--- a/terraform/lxc/ansible/roles/docker_base/tasks/main.yml
+++ b/terraform/lxc/ansible/roles/docker_base/tasks/main.yml
@@ -54,6 +54,41 @@
     daemon_reload: true
   when: docker_rsyslog_order_dropin.changed

+# Single owner of /etc/docker/daemon.json, opt-in per stack
+# (docs/logging/docker-log-driver-audit.md §4). Off by default, so this
+# block is a no-op until a stack sets docker_base_manage_daemon_json: true.
+- name: Ensure /etc/docker exists
+  ansible.builtin.file:
+    path: /etc/docker
+    state: directory
+    owner: root
+    group: root
+    mode: "0755"
+  when: docker_base_manage_daemon_json | bool
+
+- name: Write Docker daemon.json (log driver + per-stack extras)
+  ansible.builtin.copy:
+    dest: /etc/docker/daemon.json
+    owner: root
+    group: root
+    mode: "0644"  # nosonar: ansible:S2612 - daemon.json holds no secrets
+    content: "{{ docker_base_daemon_config | to_nice_json }}\n"
+  register: docker_base_daemon_json
+  when: docker_base_manage_daemon_json | bool
+
+# A daemon restart alone does NOT change existing containers' log driver
+# (docs/monitoring-stack/design.md §2). Callers must force-recreate their
+# compose project when docker_base_daemon_json.changed.
+- name: Restart Docker to apply daemon.json
+  ansible.builtin.systemd:
+    name: docker
+    state: restarted
+  when:
+    - docker_base_manage_daemon_json | bool
+    - docker_base_daemon_json.changed
+    - not ansible_check_mode
+
 - name: Ensure Docker service is running
   ansible.builtin.systemd:
     name: docker
```

Also fix the stale comment at `roles/docker_base/tasks/main.yml:9-13`, and
`terraform/lxc/README.md:169`, in the same change.

### Example stack migration: `deploy-netbox-stack.yml` (NOT APPLIED)

```diff
--- a/terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml
+++ b/terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml
@@ -84,6 +84,12 @@
     netbox_lab_ip_dns: "{{ lookup('env', 'LAB_IP_TECHNITIUM') | default(dns_server, true) | mandatory('LAB_IP_TECHNITIUM env var or dns_server inventory var is required') }}"
     netbox_api_token: "{{ ... unchanged ... }}"
+    docker_base_manage_daemon_json: true
+    docker_base_daemon_extra:
+      insecure-registries: ["{{ docker_registry_host }}"]
+      dns: ["{{ netbox_lab_ip_dns }}"]
+      storage-driver: overlay2
   roles:
     - lxc_base
     - docker_base
@@ -92,22 +98,6 @@
   tasks:
-    - name: Trust Harbor HTTP registry in Docker daemon
-      ansible.builtin.copy:
-        dest: /etc/docker/daemon.json
-        mode: "0644"
-        content: |
-          {
-            "insecure-registries": ["{{ docker_registry_host }}"],
-            "dns": ["{{ netbox_lab_ip_dns }}"],
-            "log-driver": "syslog",
-            "log-opts": { ... },
-            "storage-driver": "overlay2"
-          }
-      notify: Restart Docker
-      register: docker_daemon_config
-
-    - name: Flush handlers to apply Docker daemon config before stack deploy
-      ansible.builtin.meta: flush_handlers
@@ -255 @@
-          {{ '--force-recreate' if docker_daemon_config.changed else '' }}
+          {{ '--force-recreate' if (docker_base_daemon_json.changed | default(false)) else '' }}
```

For a stack with no config today (2c: newt-connector, harness-target,
cse-kali, docker-socket-proxy-test), the whole migration is one line in the
play's `vars:`, plus a one-time force-recreate:

```diff
+    docker_base_manage_daemon_json: true
```

For stacks that must stay on json-file for now (pentagi-stack,
pentagi-upstream-control, pentagi-upstream-vanilla-companion):

```diff
+    docker_base_manage_daemon_json: true
+    docker_base_log_driver: json-file   # R2: per-service logging.options without driver:
+    docker_base_daemon_extra:
+      insecure-registries: ["{{ docker_registry_host }}"]
```

### Rollout order (proposed)

Each step goes through the Ansible task/role tier: `scripts/provision.sh
--stack <name>` on `pve`, under the production approval flow, run
`--syntax-check` first, and force-recreate the stack's containers once.

| Order | Stacks | Why this order |
|---|---|---|
| 0 | Role change only (flag default false) | No-op everywhere. `--syntax-check` all 39 playbooks. |
| 1 | newt-connector, harness-target, cse-kali, docker-socket-proxy-test | Closes R1 (unbounded logs) and gains Graylog. Low blast radius. |
| 2 | mcp-utility-stack, ai-services-stack | json-file → syslog. No driver-less per-service opts. Fix the ai-services comment (R3). |
| 3 | Routine syslog stacks (monitoring, netbox, opensearch, wazuh, media/torrent/pterodactyl/gaming-lab, nextcloud, cse-*, portainer-*, pangolin, deploy-stack.yml, greenbone) | Pure refactor. The effective driver doesn't change. `to_nice_json` reorders keys, so expect one Docker restart per stack. |
| 4 | ci-runner | Also add `docker_base` to fix R6. |
| 5 | pentagi family | Move to the explicit json-file override first. A later syslog move needs the compose `logging:` blocks fixed (R2). |
| 6 | harbor-stack | Docker restart blocks pulls fleet-wide for the duration. Harbor app logs are a separate item (R8). |
| 7 | graylog-stack | Keep syslog. Confirm the cold-start `docker logs` path (R5) still works. |
| 8 | technitium-stack, proxy-stack, authentik-stack | Last, in a window. A Docker restart is a DNS, routing, or SSO outage (R7). Consider adding `live-restore: true` to their extras at the same time, which also cuts future restart impact. |

### Guardrail (optional, NOT APPLIED)

Once migration finishes, add a CI check that fails if any
`playbooks/deploy-*.yml` contains `dest: /etc/docker/daemon.json`, so the
copy-paste pattern (R9) can't come back.

---

## 5. Read-only checks still owed (not possible from this sandbox)

- `docker info --format '{{.ServerVersion}} {{.LoggingDriver}}'` on each Docker
  LXC, to confirm the effective driver matches this table and Docker is ≥ 20.10
  (dual logging).
- `docker inspect -f '{{.Name}} {{.HostConfig.LogConfig.Type}}' $(docker ps -q)`
  on each, to catch containers still on an old driver because they were never
  recreated (R7).
- `du -sh /var/lib/docker/containers` on newt-connector, harness-target,
  cse-kali, and docker-socket-proxy-test, to size R1.
- In Graylog, search `application_name:docker-*` grouped by `source`, to
  confirm which hosts actually deliver container logs.
- On harbor-stack, inspect the generated `docker-compose.yml` `logging:` blocks
  and `du -sh /var/log/harbor` (R8).
