# Framework platform integration — Graylog, Grafana, NetBox, Portainer

Status: **Everything deployed and verified live, 2026-07-25**
(branch `task/framework-platform-integration`) — `node_exporter` and
`cadvisor` both confirmed `health: up` in VictoriaMetrics' `/api/v1/targets`
on `pve`; rsyslog/Docker log forwarding to Graylog confirmed running on
framework; `framework` device (id=7) plus all 5 AI service records
confirmed live in NetBox via direct API query; all four Docker stacks
(`ollama`, `comfyui`, `ai-services-stack`, `llamacpp`) confirmed
`Status: 1` as fully Portainer-managed stacks, endpoint 9. Also added a
"Local AI" Grafana dashboard (GPU + Ollama stats) beyond the original
three-platform scope, on operator request. See "Live deployment notes",
"NetBox deployment notes", and "Portainer" below for the real bugs hit
and fixed along the way — not just the happy path. Companion to
[`local-ai-development.md`](./local-ai-development.md) (agent/orchestration
layer) and [`plan.md`](./plan.md) (inference layer, done) — this covers
wiring the already-working `framework.gibbsgreatly.xyz` host into the three
platform services the rest of the lab uses: Graylog (logging), Grafana/
VictoriaMetrics (metrics), NetBox (asset/service inventory).

## Why this wasn't already done

`framework.gibbsgreatly.xyz` is a bare-metal Ubuntu 26 host, not an LXC
container provisioned by `terraform/lxc/`. Every other stack in this repo
gets logging/monitoring/inventory "for free" because `lxc_base`'s role
defaults and the `terraform/lxc/stacks/*/stack.yaml` + edge-manifest system
apply to all of them uniformly. Framework sits outside that system entirely
(`docs/framework-ubuntu/plan.md` §7 explicitly found "NetBox — nothing to
do" and "Monitoring — nothing to do" back when the old *Proxmox-LXC* version
of this host was decommissioned — those findings were about removing a
stale placeholder, not about the new bare-metal host, and `plan.md` itself
still flags `node_exporter`/`rsyslog_forward` as "not yet added to this
playbook").

**The three platforms don't share one blocker — they split into two very
different categories:**

| Platform | Blocker type | Why |
|---|---|---|
| Grafana/VictoriaMetrics | None — just wiring | `node_exporter` and `rsyslog_forward` are already generic Linux-host roles (`plan.md` line 466: "these already target 'a Linux host,' not 'an LXC guest specifically'"). Framework already gets Ansible-managed via `ansible/00-initial-setup/framework-desktop-*.yml` — adding a role call is the same shape of change as any other playbook edit. |
| Graylog | None — just wiring | Same roles, same host-vs-LXC independence. Also already proven cross-segment: MikroTik and the Proxmox host itself (`configure-proxmox-syslog.yml`) forward syslog into Graylog today, and neither is an LXC either. |
| NetBox | **Real gap** | `netbox-stack/integrations/populate.py` doesn't run generic "host discovery" — it builds its whole topology from the Proxmox API (`proxmox_client.discover_from_proxmox`) plus `terraform/lxc/stacks/*/stack.yaml` files. A bare-metal host with no Proxmox VM and no `stack.yaml` is structurally invisible to it. This needs new code, not configuration — same category of gap MikroTik had before it got its own `mikrotik_client.py` + static device block. |

So: Graylog and Grafana are low-risk, mechanical follow-ups to work already
started (the roles exist, just aren't invoked yet). NetBox is a small,
well-precedented feature addition.

## Current state, verified directly (2026-07-25)

- `framework-desktop-bootstrap.yml` installs the GPU/storage bootstrap only;
  no `node_exporter` or `rsyslog_forward` role call anywhere in any
  `framework-desktop-*.yml` playbook.
- Four of the five services on this host now run as Docker Compose
  containers — `llama.cpp`, `Ollama`, `ComfyUI` (Decision 5 was reversed
  2026-07-20, "dockerise everything that can be"), and `ai-services-stack`
  (OpenWebUI + SearXNG). Only LM Studio stays native systemd (no
  GPU-capable Docker path for it). Each of the four `framework-desktop-*.yml`
  playbooks independently `apt install docker.io` with no shared
  `docker_base`-equivalent role and no `daemon.json` management at all —
  every container currently logs via plain `json-file`, no syslog
  log-driver. Since it's one Docker daemon on the host, a single
  `daemon.json` change reaches all four compose stacks at once — this is
  a bigger, cheaper win than it first looks, not a per-stack change.
- `.env` already defines `LAB_IP_GRAYLOG` (`192.168.20.14`) and
  `LAB_IP_STEP_CA` (`192.168.20.11`) as shared, lab-wide values — framework
  doesn't need its own copies; the existing `docker_base`/`node_exporter`/
  `rsyslog_forward` roles already read these generically.
- `.env.pve-framework` is stale, still shaped around the old Proxmox-node
  era (`TF_VAR_proxmox_node=pve-framework`, etc.) and is separately flagged
  for cleanup in `plan.md` §7's decommission list — don't build new
  integration on top of it; the shared `.env` already carries what's needed.
- Graylog itself is **production-live on `pve`** (not just `pve-test-vm` —
  confirmed via `git log`: `54a8da26`..`e241840d`, Sprints P0–P7, merged to
  `stable`/`main`), already ingesting managed-LXC logs, Docker-container
  logs, Proxmox host syslog, and MikroTik syslog. Framework would be one
  more source into an already-proven pipeline, not a new one.
- NetBox's `populate.py` already has the exact pattern needed for a
  non-Proxmox device: `_ensure_proxmox_hypervisor()` (static device +
  interface + IP, no VM discovery) and the separate `mikrotik_client.py`
  module are both precedent for "a device that isn't a Proxmox guest."
  `ipam/services` (driven from `stack.yaml`'s `provides:` list elsewhere)
  is the existing model for exposing per-service ports once a device
  exists.

## Plan A — Grafana / VictoriaMetrics (metrics) — deployed and verified live

1. **Done**: added a `node_exporter` role call to
   `framework-desktop-bootstrap.yml` (the only playbook that runs as part
   of base host setup) — syntax-checked clean.
2. **Verified live**: cross-segment reachability works. Framework
   (`192.168.1.x`, LAN) reaches step-ca (`192.168.20.11`, `mgmt_seg`)
   fine — the `wait_for` probe passed and the cert issued successfully.
   The open question going in (whether this L3 path even worked) is
   settled; see "Live deployment notes" for what *did* go wrong instead.
3. Secrets: `NODE_EXPORTER_SCRAPE_PASSWORD(_HASH)` and
   `STEP_CA_PROVISIONER_PASSWORD` already live in
   `terraform/secrets.common.enc.yaml` (shared, not per-node) — no new
   secret needed, just running the framework playbook through
   `./with-secrets-prod-framework` instead of bare `ansible-playbook`.
4. **Done**: added `ansible/00-initial-setup/framework-desktop-cadvisor.yml`,
   a new standalone playbook (matching this repo's one-playbook-per-service
   convention for this host) running a single cAdvisor container on port
   `8083` — it sees every container on the host regardless of which
   compose project started it, so one instance covers
   `llama.cpp`/`Ollama`/`ComfyUI`/`ai-services-stack` at once.
5. **Done**: added scrape targets in `deploy-monitoring-stack.yml`'s
   `scrape_configs` — `node_exporter` job (`${LAB_IP_FRAMEWORK}:9100`,
   HTTPS + basic auth, matching the other 10 hosts) and `cadvisor` job
   (`${LAB_IP_FRAMEWORK}:8083`), both labelled `stack: framework`. Added
   `LAB_IP_FRAMEWORK='192.168.1.8'` to `.env` — the three older
   `LAB_IP_LLM_GPU`/`LAB_IP_COMFYUI`/`LAB_IP_AI_SERVICES` vars already
   pointed at the same IP from the old per-service-era naming; left them
   alone rather than folding them in, since that's the `plan.md` §7
   cleanup item's job, not this one's.
6. **Node Detail and Docker Containers needed no dashboard edits** — their
   `stack` dropdown is already a dynamic `label_values(...)` query, so
   framework just appears once scraped. **Lab Overview did need a fix,
   found and applied while checking this**: its six panels legended by
   raw `{{instance}}` (the pre-existing gap `design.md` already flagged),
   and two of them (`CPU Usage by Host`, `Current CPU %`) aggregated
   `avg by (instance) (...)` in the PromQL itself, not just the legend —
   changing only the legend format would have rendered a blank `{{stack}}`
   for those two, since `by (instance)` drops every other label including
   `stack`. Fixed both the aggregation and the legend for all six panels
   in `terraform/lxc/stacks/monitoring-stack/dashboards/lab-overview.json`,
   deployed to `pve` and confirmed (`changed` on that file specifically
   in the "Copy Grafana dashboard JSON files" task). One thing worth
   knowing when reading a "framework" row on Docker Containers: it's the
   whole host's containers (all four compose stacks) under one `stack`
   label, not split out like every other host is — see the "one cAdvisor
   per host" note in Plan A above.
7. Out of scope for this pass (flag, don't build): GPU utilization
   (ROCm/AMDGPU exporter) isn't one of the three platforms asked about —
   worth a follow-up idea, not bundled in here.

## Plan B — Graylog (logging) — deployed and verified live

1. **Done**: added an `rsyslog_forward` role call alongside `node_exporter`
   in `framework-desktop-bootstrap.yml`. Needs only `LAB_IP_GRAYLOG`,
   already a shared `.env` value — no per-node secret or config.
2. **One real difference from the LXC role default, worth checking before
   applying as-is**: `rsyslog_forward`'s tasks disable `imklog` because LXC
   containers can't reach `/proc/kmsg`. Framework is real hardware with a
   real kernel log — that disable is LXC-specific and shouldn't carry over
   unmodified, or framework loses kernel-level syslog for no reason. Either
   make the task conditional on a "bare metal vs LXC" var, or add a small
   host-specific override — small fix, but don't skip it.
3. Docker log driver: add the same `daemon.json` `syslog` log-driver
   (`tcp://127.0.0.1:10514`, `rfc5424`) the `docker_base` role installs
   elsewhere — but since all four Docker Compose stacks
   (llama.cpp/Ollama/ComfyUI/ai-services) share one Docker daemon on this
   host, apply it once at the host level (best done in
   `framework-desktop-bootstrap.yml` alongside `rsyslog_forward`, before
   any of the four service playbooks run) rather than duplicating it per
   playbook. This one change reaches all four stacks' container logs at
   once. LM Studio needs no Docker-side work (native systemd) — its logs
   reach Graylog via `rsyslog`/`imjournal` once step 1 lands, same as any
   other systemd service.
4. No Graylog-side config expected — inputs/pipelines already attribute by
   hostname/syslog tag generically (same mechanism the Proxmox host and
   MikroTik already use); worth a quick look at
   `docs/monitoring-stack/graylog-migration-plan.md`'s pipeline rules to
   confirm nothing hardcodes a stack allowlist, but no evidence of that so
   far.

## Live deployment notes (2026-07-25)

Three real bugs surfaced during the actual rollout, none of them design
flaws in the plan above — worth recording since they'll recur if this
pattern (bare-metal host joining LXC-era shared roles) is reused elsewhere.

1. **Framework had no homelab root CA trusted, at all.** Every LXC gets
   this via `lxc_base`'s CA-install task; framework never runs `lxc_base`
   (it's not an LXC), so `node_exporter`'s step-ca cert issuance failed
   outright: `open /usr/local/share/ca-certificates/homelab-root.crt: no
   such file or directory`. Root cause found via a temporary `no_log:
   false` override on the (normally password-hiding) cert-issuance task,
   reverted immediately after diagnosis. Fix: reproduced `lxc_base`'s
   exact CA-resolution logic (env-specific cert if one exists for this
   `PVE_ENV`, else the shared `certs/homelab-root.crt`) as a new task
   block in `framework-desktop-bootstrap.yml`, since this host has no
   `lxc_base` include to lean on.
2. **`node_exporter`'s cert had no IP SAN, so IP-based scraping failed
   TLS verification** (`x509: cannot validate certificate for
   192.168.1.8 because it doesn't contain any IP SANs`). Cause: the
   role issues SANs from `ansible_host`/`inventory_hostname`, and
   `ansible/inventory/inventory.yml`'s `framework` group defaults
   `ansible_host` to the FQDN string unless `FRAMEWORK_HOST_IP` is set
   — which it never was. Every other managed host in this repo is an
   LXC whose `ansible_host` is already a raw IP, so this gap is specific
   to framework's inventory shape. Fixed by adding
   `FRAMEWORK_HOST_IP='192.168.1.8'` to `.env` (so future reissuance is
   correct by default) plus a small self-correcting task in
   `framework-desktop-bootstrap.yml` that force-reissues the cert only if
   it's missing the IP SAN — a one-time fix that becomes a permanent
   no-op once the cert is right.
3. **Pushing the monitoring-stack scrape-config change to `pve` hit a
   known, already-documented, unrelated flake**: apt-cacher-ng serving a
   corrupted/GPG-unverifiable cached `deb.debian.org` `trixie`
   `InRelease` file, breaking the generic `node_exporter` apt-cache
   update that `lxc_base` runs on *every* stack provision — the exact
   same failure `plan.md` §"Pushing the rendered config..." already
   recorded against `proxy-stack`/`technitium-stack`. Not transient
   (reproduced twice identically). Worked around the same documented way:
   `-e monitoring_enabled=false` (the existing guard on `node_exporter`'s
   role include in `lxc_base`) on a direct `ansible-playbook` invocation
   using the same inventory/playbook/extra-vars `scripts/provision.sh`
   itself would use — `provision.sh` has no passthrough for extra `-e`
   flags, so this bypassed it rather than extending it. apt-cacher-ng's
   underlying corrupted cache is still unfixed; it'll block the *next*
   `node_exporter`/`rsyslog_forward`-touching change to any `pve` stack
   the same way, not just this one.
4. **cAdvisor `health: up` was misleading** — the scrape itself succeeded,
   but every series it returned was a raw systemd/cgroup path (`id:
   "/system.slice/..."`) with `name` and `image` both empty, so framework
   never appeared in the Docker Containers dashboard's `stack` dropdown
   (that dropdown's `label_values(...)` query explicitly filters
   `name!=""`). Root cause, found via `docker logs cadvisor`:
   `gcr.io/cadvisor/cadvisor:v0.49.1` (the version used by every
   LXC-based cadvisor in this repo) embeds a Docker client speaking API
   1.41 — Ubuntu 26.04's Docker daemon here requires >= 1.44 and rejects
   it outright ("client version 1.41 is too old"), so the Docker
   container factory never registers and cadvisor silently falls back to
   raw cgroup discovery instead of failing loudly. Fixed by bumping to
   `v0.60.5` (latest stable) — which also required switching the image's
   *registry*, not just its tag: cAdvisor moved from `gcr.io/cadvisor/cadvisor`
   to `ghcr.io/google/cadvisor` at v0.53.0 (per the project's own
   README), so the old `gcr.io` path 404s for any version past that.
   Confirmed at the source (`curl 127.0.0.1:8083/metrics` on framework)
   and in VictoriaMetrics: `framework` now appears in
   `/api/v1/label/stack/values` filtered to `name!=""`, with real
   container names (`cadvisor`, `comfyui`, `ollama`, `openwebui`,
   `searxng`) instead of cgroup paths.

All four are now resolved for framework specifically: `node_exporter`
and `cadvisor` both confirmed `health: up` with no `lastError` in
VictoriaMetrics' `/api/v1/targets`, and cadvisor is now reporting real
per-container metrics, not just host cgroups.

## Local AI dashboard (added 2026-07-25, deployed and verified live)

Follow-on from Plan A: the operator asked for GPU utilization/memory and
Ollama stats specifically, since that's the primary local-AI workload now.
Checked live before building anything, rather than assuming: neither
llama.cpp's server nor Ollama expose a native Prometheus `/metrics`
endpoint on this host (`/metrics` returned empty and 404 respectively).
GPU stats *are* available, but not from `rocm-smi`'s default VRAM query —
that reports a tiny, fixed 512MB pool irrelevant to LLM workloads on this
unified-memory APU. The number that matters is **GTT** (shared system
memory, the same pool the `ttm.pages_limit` GRUB tuning governs) —
`mem_info_gtt_total`/`mem_info_gtt_used` in
`/sys/class/drm/card*/device/`, ~90.8GB total, tracking almost exactly
with what Ollama itself reports as loaded.

Built two small Python scripts (`ansible/00-initial-setup/files/{gpu_stats_textfile,ollama_stats_textfile}.py`),
run every 15s via a new `framework-ai-stats.service`/`.timer` systemd pair,
writing to node_exporter's textfile collector — reusing the
already-scraped `node_exporter` job rather than standing up new scrape
targets or exporter containers:
- `gpu_stats_textfile.py`: `amdgpu_busy_percent`, `amdgpu_gtt_used_bytes`/`_total_bytes`,
  plus the (mostly irrelevant but included for completeness)
  `amdgpu_vram_used_bytes`/`_total_bytes`, and `amdgpu_scrape_up`.
- `ollama_stats_textfile.py`: polls `/api/ps` (not Prometheus, but real
  per-loaded-model JSON) and emits `ollama_model_{loaded,size_bytes,vram_bytes,context_length,expires_in_seconds}`
  per model, plus `ollama_scrape_up`.

**Required a `node_exporter` role change**, opt-in and additive: added
`node_exporter_textfile_dir` (default `""`, so the other 10+ managed
hosts are unaffected) which, when set, creates the directory and adds
`--collector.textfile.directory=...` to the systemd drop-in's
`ExecStart`. Verified the rendered `ExecStart` line is byte-identical to
before for any host that doesn't set the var.

New dashboard: `terraform/lxc/stacks/monitoring-stack/dashboards/local-ai.json`
("Local AI") — GPU utilization/GTT memory (timeseries + current-value
stat panels, matching Lab Overview's existing style), Ollama per-model
memory and time-to-unload, and two `_scrape_up` health panels (a direct
lesson from the cadvisor incident above: a healthy *scrape* doesn't mean
the *data* is meaningful, so the dashboard says so explicitly rather than
assuming). No `$stack` template variable — these metric names only ever
exist on framework, so filtering isn't needed.

Verified end-to-end: read the `.prom` files directly on framework,
confirmed node_exporter's own `/metrics` output includes them (via
`curl` with the real scrape credentials), and confirmed VictoriaMetrics
has them queryable with the `stack="framework"` label. Deployed via the
same `provision.sh --stack monitoring-stack` / `monitoring_enabled=false`
path as everything else in this doc.

**Not covered** (flagged, not built): token/sec, request latency, queue
depth — neither engine exposes these, so this dashboard is
utilization/memory/what's-loaded, not throughput. Would need either
enabling llama.cpp's own metrics flag (if this build supports it) or a
real request-level exporter, a separate piece of work.

## Plan C — NetBox (inventory) — deployed and verified live

Turned out much cheaper than scoped above, because a closer look at
`populate.py` found an already-built, already-precedented mechanism this
plan didn't know about when it was first written: `populate_static_hosts()`
(device + interface + IP, no Proxmox VM discovery needed), data-driven
from `network/pve.yaml`'s `inventory.static_hosts` list — already used
live for `pve-test-vm`, `linux-desktop`, and two Raspberry Pis. No new
`_ensure_bare_metal_host()` helper needed; the MikroTik-style precedent
this plan expected to have to build already existed one level up.

What was actually built:
1. **Added `framework` to `network/pve.yaml`'s `static_hosts`** (role
   `ai-workstation`, IP `192.168.1.8`) — this alone gets the device,
   interface, and primary IP for free via the existing function.
2. **Extended `populate_static_hosts()` with an optional `services:` key**
   per static host (small, additive — ~15 lines), since the existing
   function had no service-attachment path at all (services elsewhere in
   this script come from live Portainer/socket-proxy probing of VMs,
   which doesn't apply to a static host). Declared, not live-probed:
   `network/pve.yaml`'s `framework` entry now lists all 5 AI services
   (LM Studio `:8090`, llama.cpp `:8080`, Ollama `:11434`, OpenWebUI
   `:8081`, SearXNG `:8082`) with `parent_object_type: dcim.device`.
3. Added `integrations/tests/test_populate_static_hosts.py` (3 tests:
   plain device-only case doesn't regress, framework's full service list
   registers correctly, a malformed service entry fails loudly rather
   than silently). Full suite: 128/128 passing.
4. Ran `populate.py --plan` first (dry run), confirmed the plan was
   additive-only (1 device, 1 interface, 1 IP, 5 services — nothing
   existing touched), then applied for real. Verified directly against
   the live NetBox API afterward: `framework` device id=7, all 5 services
   present with correct ports.

**Real bug found and fixed along the way, unrelated to this change**:
`populate.py --plan` crashed outright with `ConnectionRefusedError`
before ever reaching the static-hosts step — `management-stack.gibbsgreatly.xyz:9443`
(the Portainer instance the script always tries to probe first, for live
VM service discovery) was unreachable, and unlike `PortainerClient`'s own
constructor a few lines away (which already degrades gracefully),
`portainer.get_endpoints()` in `discover.py` had no equivalent try/except
— any momentary Portainer outage crashed the *entire* populate run, not
just VM service discovery. Fixed with the same graceful-degrade pattern
already used one function up. Portainer itself is still down as of this
writing — worth checking separately, but no longer blocks NetBox
population.

## Portainer (added 2026-07-25, fully deployed and verified — including the stack push)

Follow-on from Plan A/framework's Docker-heavy shape, on operator
request: connect framework's four Docker Compose stacks (llama.cpp,
Ollama, ComfyUI, ai-services-stack) to the lab's Portainer so they're
manageable from its UI, not just plain `docker compose` deployments only
Ansible knows about.

**Not the same Portainer as the "still down" note above** — that one is
`management-stack.gibbsgreatly.xyz:9443`, a legacy instance
`network/pve.yaml`'s `proxmox_nodes[0].portainer_url` still points at for
NetBox's VM-service discovery, unrelated to this. The lab's actual
current Portainer server is the `portainer-stack` LXC (`192.168.20.20:9000`),
which is up and is what this section registers framework with.

**Key finding, checked live before building anything**: Portainer only
shows a compose deployment as an editable "Stack" (not just loose
containers) if it was deployed *through Portainer's own API*
(`/api/stacks/create/standalone/string`), not via plain `docker compose
up`. Framework's four stacks are deployed the second way (by their own
`framework-desktop-*.yml` playbooks), so getting real management, not
just visibility, needs an extra step beyond registering the agent.

**Existing precedent found and reused**: this repo already has a pattern
for exactly "a pre-existing physical/LAN host, not created via the
LXC/Terraform lifecycle" — `torrent-stack`/`media-stack`/`gaming-stack`/
`cloud-stack` all use the `portainer_api` (register/update the endpoint)
and `portainer_stack` (push compose content via the API) roles this way.
No step-ca/mTLS anywhere in this subsystem — agent↔server trust is
self-signed/skip-verify by design, matching every other agent
registration in this repo.

New playbook: `ansible/00-initial-setup/framework-desktop-portainer.yml`.
Deploys the agent directly via `docker compose up -d` (no pre-baked
systemd unit needed, unlike the LXC `portainer_agent` role — matches
every other `framework-desktop-*.yml` playbook's own style instead), then
reuses `portainer_api` as-is for registration. Deliberately does **not**
reuse `portainer_stack`'s stack-push task unchanged: that task reads
compose content via `lookup('file', stack_dir + '/' + item.compose_file)`
— a local file in this repo — but framework's four compose files are
rendered directly onto the remote host by their own playbooks, not
stored locally. This playbook instead `slurp`s each file back from
framework itself before pushing it to Portainer, guaranteeing
byte-for-byte identity with what's actually running rather than a second
copy that could drift.

**Deployed and confirmed live**: agent running on framework, environment
registered (endpoint ID 9), confirmed via direct Portainer API query —
`Status: 1` (up), meaning `mgmt_seg` (`192.168.20.20`) → framework
(`192.168.1.8:9001`) reachability, the one open question from Plan A/B,
is now settled for this port too.

**Stack push is deliberately paused, not broken**: attempting it hit a
real, expected conflict — Portainer's stack-create actually runs `docker
compose up` itself to take ownership, which fails outright ("Conflict.
The container name ... is already in use") against containers Ansible's
own `docker compose up -d` already created. Making the swap means
removing the existing containers first, i.e. **real downtime** on all
four in-use AI services while each recreates. Checked for orphaned state
after the failed attempt (via the Portainer API) — none; zero stack
records exist on the endpoint, confirming Portainer rolled the failure
back cleanly rather than leaving something half-registered.

Given the operator's own AI workloads were live at the time, this was
paused rather than pushed through — the playbook's default run only
does the (downtime-free, fully idempotent, re-verified) agent/registration
steps; the container swap requires an explicit opt-in:
```bash
ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ./with-secrets-prod-framework \
  ansible-playbook -i ansible/inventory/ \
  ansible/00-initial-setup/framework-desktop-portainer.yml \
  -e framework_portainer_push_stacks=true
```
That flag also gates a container-removal step (by exact `container_name`,
one stack at a time in the same loop) added specifically so this can be
triggered later without re-deriving what's needed.

### Stack push completed (follow-on session, operator-approved downtime window)

Ran the opt-in flag above once the operator confirmed a downtime window.
Three stacks (Ollama, ComfyUI, ai-services-stack) swapped over cleanly on
the first attempt. **The fourth, llama.cpp, caused a real, live outage**
— worth recording precisely, not just "it got fixed":

1. llama.cpp's compose file has a `build: {context: .}` section (it's
   compiled from source on this host, unlike the other three which just
   reference pre-built images). Portainer's stack-create actually runs
   `docker compose build` itself, which failed ("listing workers for
   Build ... frame too large") — not the naming-conflict error from the
   first attempt, a different failure, because by this point the
   container-removal step had already run. **llama.cpp was down with no
   container running** until fixed.
2. Root cause: Portainer's `create/standalone/string` API only transmits
   the compose YAML *text*, not the Dockerfile/build-context files
   `context: .` refers to — structural, not a network glitch. No
   `build:`-based stack can ever deploy through this API path.
3. **Immediate recovery, prioritized over the underlying fix**: re-ran
   `framework-desktop-llamacpp.yml` directly (bypasses Portainer
   entirely, plain `docker compose up -d --build` like normal) to
   restore service first. Confirmed via `docker ps` and a `/health`
   check before doing anything else.
4. **Underlying fix**: added a transform step to
   `framework-desktop-portainer.yml` that strips any `build:` key from
   every service in every stack before pushing (generic, not
   llama.cpp-specific, in case a future stack adds one) — the image
   (`llamacpp-router:hip`) is already built locally by that stack's own
   playbook, so `build:` was never actually needed for Portainer's copy,
   only `image:`.
5. **The first version of this fix was itself broken** (`map('combine',
   {'value': dict(item.value...)})` — `item` isn't bound the way that
   pattern assumes; Jinja2 has no dict-comprehension syntax at all,
   unlike Python) — caught by `--syntax-check` and, more importantly, by
   testing the actual transform logic standalone against all four of
   framework's *real* compose files (pulled live via `sudo cat`) before
   touching production again, given the first attempt had just caused an
   outage. The working form uses a real `{% for %}` loop with `.update()`
   accumulation. Verified: every key survives except `build:`, and the
   transform is a confirmed no-op for the three stacks that never had a
   `build:` key to begin with.
6. **Two more idempotency bugs**, both cosmetic/edge-case, caught by
   deliberately re-running the playbook to confirm a clean idempotent
   pass rather than assuming success from one green run: a stale
   `item.item.item.name` reference in the final report task (left over
   from an earlier, differently-nested version of the payload structure),
   and `framework_portainer_stack_payloads` being entirely undefined
   (not even an empty list) on a run where zero stacks need pushing,
   since a `set_fact` task with a zero-item loop never executes at all.
   Fixed by pre-declaring the variable at play level.

**Final verified state**: all four stacks (`ollama`, `comfyui`,
`ai-services-stack`, `llamacpp`) show `Status: 1` in Portainer; all seven
containers on the host (`llamacpp-router`, `ollama`, `comfyui`,
`openwebui`, `searxng`, `portainer-agent`, `cadvisor`) confirmed running
via `docker ps`; health endpoints on ports 8080/11434/8081 all responded.
A second full playbook run confirmed `changed=0, failed=0` — genuinely
idempotent, not just "worked once."

## Sequencing and risk

1. **Graylog — done, deployed, verified.** (Lowest friction, most
   precedent: MikroTik/NAS/Proxmox-host already prove cross-segment
   syslog into the live production Graylog; the `imklog` fix was small
   and self-contained.)
2. **Grafana/monitoring — done, deployed, verified.** (Same role-wiring
   shape as Graylog; the mgmt_seg↔LAN step-ca path is confirmed working.)
3. **NetBox — done, deployed, verified.** See Plan C above.
4. **Portainer — done, deployed, verified, including the stack push.**
   See below — completed in a follow-on session once a downtime window
   was available.

1 and 2 are implemented on `task/framework-platform-integration`,
syntax-checked (including a check that the `rsyslog_forward` role change
doesn't break the other 10+ LXCs that already consume it via `lxc_base`),
and now confirmed live against both `framework.gibbsgreatly.xyz` and
`pve` — see "Live deployment notes" above for the three bugs found and
fixed along the way.

All three are `pve`-side mutations in the sense that they change what a
production node's dashboards/log platform/inventory show, but none require
any change to `framework.gibbsgreatly.xyz`'s Proxmox status (it has none)
or to production Terraform state. Ansible changes against framework itself
go through `./with-secrets-prod-framework` + `TASK_APPROVAL` per `CLAUDE.md`
since it's a declared production node; there's no `pve-test-vm`-equivalent
staging copy of this specific host, so lean on `--check` mode plus the fact
that both roles are already battle-tested on 10 other hosts, rather than
a full teardown-style rehearsal.

## Open questions

- ~~Exact NetBox device-role/device-type naming~~ — resolved: `ai-workstation`
  role, `Generic Device` type (matching MikroTik's existing usage of that
  type — didn't need a new `Generic Server` type).
- ~~Whether GPU metrics belong in a future Grafana pass~~ — resolved: built
  as part of the "Local AI dashboard" section above.
- `.env.pve-framework`'s stale Proxmox-era contents are a separate cleanup
  item (`plan.md` §7) — not blocking this plan, but shouldn't be built on.
- Portainer (`management-stack.gibbsgreatly.xyz:9443`) was down during
  this session's NetBox work — the crash-on-outage bug is fixed, but the
  outage itself wasn't investigated; worth checking separately.
- Every other stack's cadvisor is still on the broken `v0.49.1`/`gcr.io`
  image (see "Live deployment notes" above) — not re-verified here.
- **Worth checking, not checked here**: every other stack's cadvisor
  still runs the same `v0.49.1`/`gcr.io` image that turned out broken on
  framework (silently reports raw cgroups instead of failing). Whether
  those LXCs' own Docker versions are old enough to still accept the
  1.41 client (so they're actually fine) or have the same silent gap
  (just never investigated because nobody compared `health: up` against
  actual `name` labels) is unknown — this plan only found and fixed the
  framework instance.
