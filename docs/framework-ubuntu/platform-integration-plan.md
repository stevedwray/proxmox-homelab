# Framework platform integration — Graylog, Grafana, NetBox

Status: **Plans A (Grafana/monitoring) and B (Graylog) deployed and
verified live, 2026-07-25** (branch `task/framework-platform-integration`)
— `node_exporter` and `cadvisor` both confirmed `health: up` in
VictoriaMetrics' `/api/v1/targets` on `pve`, rsyslog/Docker log forwarding
to Graylog confirmed running on framework. Plan C (NetBox) not started.
See "Live deployment notes" below for the two real bugs hit and fixed
along the way (not just the happy path). Companion to
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

## Plan C — NetBox (inventory)

This is genuinely new code, not a config change — size it like a small
feature, not a wiring task.

1. In `terraform/lxc/stacks/netbox-stack/integrations/populate.py`, add:
   - `PLATFORMS`: `{"name": "Ubuntu 26.04", "slug": "ubuntu-26-04"}`.
   - `DEVICE_ROLES`: a role for a bare-metal compute host (e.g.
     `"AI Workstation"` or reuse a broader `"Compute"` role if one gets
     added for other future bare-metal hosts).
   - `DEVICE_TYPES`: the existing `"Generic Device"` entry may already
     cover this, or add a `"Generic Server"` type if `"Generic Device"` is
     semantically reserved for network gear (check current usage before
     reusing it, since MikroTik is Generic Device today).
   - A small `_ensure_bare_metal_host(nb, site, name, ip, role, platform,
     description)` helper, modeled directly on `_ensure_proxmox_hypervisor`
     minus the Proxmox-cluster parts — device + one interface + one IP,
     called once for `framework` / `192.168.1.8`.
2. Represent the host's services (LM Studio `:8090`, llama.cpp `:8080`,
   Ollama `:11434`, OpenWebUI `:8081`, SearXNG `:8082`) as `ipam/services`
   entries attached to the new device — same model already used for
   `stack.yaml`'s `provides:` list elsewhere, just sourced from a small
   static list instead of a `stack.yaml` (framework has no `stack.yaml`,
   and reviving the stale `terraform/lxc/network/pve-framework.yaml` file
   flagged for cleanup in `plan.md` §7 would resurrect the wrong,
   LXC-shaped model — don't do that; a fresh static block matching the
   MikroTik pattern is the right size for one host).
3. Add a corresponding `test_populate_*.py` test following the existing
   convention in `integrations/tests/` before this ships, per the repo's
   validation tier for Python logic with tests.
4. This mutates NetBox's live data on `pve` (a production node) — runs
   through the same `CLAUDE.md` approval flow as any other `pve` mutation,
   even though it's an application-level change rather than
   infrastructure. Treat it as a normal, low-blast-radius mutation
   (additive-only NetBox records), not a structural change.

## Sequencing and risk

1. **Graylog — done, deployed, verified.** (Lowest friction, most
   precedent: MikroTik/NAS/Proxmox-host already prove cross-segment
   syslog into the live production Graylog; the `imklog` fix was small
   and self-contained.)
2. **Grafana/monitoring — done, deployed, verified.** (Same role-wiring
   shape as Graylog; the mgmt_seg↔LAN step-ca path is confirmed working.)
3. **NetBox — not started.** Actual development work (new populate.py
   path + test), do it as its own reviewed change rather than folding it
   into the Ansible wiring above.

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

- Exact NetBox device-role/device-type naming (`"AI Workstation"` vs. a
  more generic `"Compute"` role reusable for future non-Proxmox hosts) —
  operator call, not decided here.
- Whether GPU metrics (ROCm/AMDGPU exporter) belong in a future Grafana
  pass — noted as out of scope for this plan, not decided against.
- `.env.pve-framework`'s stale Proxmox-era contents are a separate cleanup
  item (`plan.md` §7) — not blocking this plan, but shouldn't be built on.
- **Worth checking, not checked here**: every other stack's cadvisor
  still runs the same `v0.49.1`/`gcr.io` image that turned out broken on
  framework (silently reports raw cgroups instead of failing). Whether
  those LXCs' own Docker versions are old enough to still accept the
  1.41 client (so they're actually fine) or have the same silent gap
  (just never investigated because nobody compared `health: up` against
  actual `name` labels) is unknown — this plan only found and fixed the
  framework instance.
