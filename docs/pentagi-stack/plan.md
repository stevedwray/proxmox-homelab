# PentAGI on Proxmox — Debian LXC Deployment Plan

A phased implementation plan for running PentAGI as a semi-productionised service in a Debian LXC on `pve-test-vm`, driving local Ollama and SearXNG services on `framework.gibbsgreatly.xyz` (the Framework Desktop — bare-metal Ubuntu 26, not Proxmox; see `docs/framework-ubuntu/plan.md` §0), and exposing the PentAGI web UI to the LAN.

**Target host for this build: `pve-test-vm`**, not `pve`. `pve-test-vm` is not a production node (`terraform/PRODUCTION_NODES` lists only `pve` and `pve-framework`), so this work uses the normal `./with-secrets` path — no `TASK_APPROVAL`/production-approval flow applies here. Promotion past `stable` onto a production node is a separate, later decision, gated the normal way per `CLAUDE.md`'s branch model.

**Always reference the Framework host by DNS name** (`framework.gibbsgreatly.xyz`), never by its raw IP directly — matches how every other cross-host reference in this repo works (Technitium-resolved names, not hardcoded IPs), and survives the host being re-addressed without every script/config needing an edit.

This plan incorporates lessons learned while testing PentAGI with:

- PentAGI running under Docker on a Kali VM
- Ollama running in Docker on a headless Framework Desktop
- SearXNG running in Docker on the same Framework Desktop
- Tool-capable Qwen and Command-R models
- A dedicated Ollama embedding model
- PentAGI execution containers targeting Metasploitable 2

It is written to be executed with an AI coding assistant in VS Code. Each phase includes concrete tasks and acceptance criteria. Pay attention to the **[WHERE]** tag because the work occurs on multiple systems.

---

## 0. Architecture and known-good configuration

### Current topology

```text
Garuda desktop
└── Browser / VS Code
      │
      ▼
pve-test-vm (Proxmox)
└── Debian LXC: PentAGI control plane (pentagi-stack)
    ├── pentagi
    ├── pgvector
    ├── scraper
    ├── pgexporter
    └── pentagi-terminal-* worker containers
          │
          ├── Lab targets
          └── Internet/search access

framework.gibbsgreatly.xyz (bare-metal Ubuntu 26, separate physical host)
├── Ollama: 11434
└── SearXNG: 8082
```

### Docker execution model — clarifying "PentAGI controls Docker"

PentAGI does not run *instead of* Docker at the LXC level — it runs **inside** Docker, nested inside the LXC. The shape is:

```text
pve-test-vm
└── Debian LXC (unprivileged, nesting=1, keyctl=1)
    └── dockerd (one daemon, running inside the LXC)
        ├── pentagi          ← has /var/run/docker.sock bind-mounted in
        ├── pgvector
        ├── scraper
        ├── pgexporter
        └── pentagi-terminal-*  ← spawned BY the pentagi container, as siblings, via that socket
```

This is the standard Docker-outside-of-Docker (DooD) pattern: one nested Docker daemon inside the LXC, with the `pentagi` container given a socket-mount into that same daemon so it can launch sibling containers alongside itself. "PentAGI controls Docker" means it controls *that LXC's own* nested daemon — not Proxmox's host Docker (there isn't one) and not the LXC itself. This is exactly why the security boundary note below treats the LXC as the disposable/blast-radius unit: a compromised `pentagi-terminal-*` container can pivot to anything else in that same nested Docker daemon, but not to Proxmox or sibling LXCs, unless it also escapes the LXC boundary itself.

### Network zone

`pve-test-vm` already runs a full SDN VLAN zone model (`build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`, `terraform/lxc/network/pve-test-vm.yaml`) plus a legacy flat `vmbr0`/`lan` attachment used only by `test-lxc`/`test-docker`. None of the existing zones are a semantic fit for a workload that (a) holds a Docker socket with effective root-equivalent reach over its own container set, and (b) needs to originate traffic toward pentest lab targets — mixing that into `infra_seg` (Harbor/apt-cacher/NetBox) or `mgmt_seg` (Authentik/step-ca) would violate the same NFR-03 default-deny reasoning that justified a dedicated `ai_seg` for AI workloads on `pve-framework` (`docs/framework-integration/decisions.md` Decision 4).

Decision: new dedicated zone, following that same precedent.

```text
pentest_seg — VLAN 70, 192.168.70.0/24, gateway 192.168.70.1
```

**Done (2026-07-26) — MikroTik side.** Cross-zone policy applied directly on the MikroTik (`hAP ax^3`, RouterOS 7.23.1) as forward-chain rules, going beyond the minimum and giving `pentest_seg` real containment (no other zone on this router currently has explicit east-west isolation — verified live via read-only query during this rollout that `build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`/`ai_seg` all currently have unrestricted forward-chain reachability to each other; the documented "default-deny" model is intent, not enforced state, for those zones):

- `pentest_seg → infra_seg` (`192.168.40.0/24`): TCP 3142 (apt-cacher, reached directly at its own IP)
- `pentest_seg → 192.168.30.110` (edge_seg, Traefik): TCP 80/443 (Harbor — **not** infra_seg. `harbor.${LAB_DOMAIN}` resolves to Traefik's edge_seg IP, not Harbor's own infra_seg IP. Discovered live, 2026-07-26: all four PentAGI image pulls timed out for ~15 minutes until this was corrected — infra_seg-only was the wrong destination zone entirely.)
- `pentest_seg → framework.gibbsgreatly.xyz` (`192.168.1.8`, flat LAN): TCP 11434 (Ollama), TCP 8082 (SearXNG)
- `pentest_seg → 192.168.1.113` (`LAB_TARGET`): full port/protocol range, scoped by **destination IP** only — pentesting needs open-ended port enumeration against an authorized target, so the containment is "only this one host," not a fixed port list (see Phase 4 Test 3 for why)
- `edge_seg → pentest_seg`: TCP 8443, for Traefik to reach the PentAGI UI once Phase 3 is live
- `pentest_seg → vlan1-wan`: unrestricted egress — PentAGI's DuckDuckGo/Sploitus search providers call out directly, not only via SearXNG
- `pentest_seg → everything else`: explicit deny, added last so the accepts above take precedence

Still needed: mirror this into `terraform/lxc/network/pve-test-vm.yaml`'s declarative `policies:` block (documentation of intent — the MikroTik enforces it regardless, but the YAML should reflect live reality) and create the actual Proxmox SDN zone/VNet/subnet (`0.2` below) — the MikroTik/L3 side being live doesn't mean Proxmox knows about this zone yet.

**Out-of-band prerequisite, same as `ai_seg`'s rollout — done (2026-07-26).** The MikroTik and `pve-test-vm`'s physical trunk port both now carry VLAN 70 as an 802.1Q tag, verified live: bridge-VLAN tagging on **both** `ether1` and `ether5` (the same dual-tag every existing zone needs — the exact gap that originally broke `ai_seg`), gateway `192.168.70.1/24` up with a connected route, and `ping 192.168.70.1` from the workstation at 0% packet loss. (A self-ping run directly on the MikroTik's own CLI failed first — that's a red herring, not a real fault; RouterOS self-pings to a bridge-VLAN sub-interface's own address aren't a reliable test. Verify from a remote host, matching how `ai_seg` was verified.)

PentAGI is not simply a Kali host containing pentest utilities. It is an autonomous agent platform with:

- A long-running Go service
- PostgreSQL with pgvector
- A scraper/browser service
- Prometheus PostgreSQL exporter
- Ephemeral worker containers spawned through the Docker socket
- LLM orchestration, planning, task state, evidence storage and reporting

The actual pentest commands run in ephemeral sibling containers such as `pentagi-terminal-*`.

### Security boundary

When PentAGI has access to `/var/run/docker.sock`, it has effective root-equivalent control of the Docker host. The initial Debian LXC must therefore be treated as a dedicated and potentially disposable execution boundary.

For stronger isolation, move execution containers to a dedicated worker VM or host later.

### Known-good values

```text
PROXMOX_NODE            = pve-test-vm
LXC_HOSTNAME            = pentagi-stack
LXC_CORES               = 8
LXC_MEMORY_MB           = 8192          # right-sized for the pve-test-vm validation run 2026-07-26; revisit if pgvector/scraper get memory-starved under real load
LXC_SWAP_MB             = 2048
LXC_ROOTFS_GB           = 30          # weights/data are external; see storage note below
DOCKER_STORAGE_GB       = 50          # separate docker_mount, not rootfs
NETWORK_ZONE            = pentest_seg (VLAN 70, 192.168.70.0/24, gw 192.168.70.1) — new, see above
TEMPLATE                = debian-13.1-2-docker-template.tar.gz

AI_BOX_HOST             = framework.gibbsgreatly.xyz   # DNS name, never the raw IP
OLLAMA_PORT             = 11434
SEARXNG_PORT            = 8082
PENTAGI_UI_PORT         = 8443

PRIMARY_MODEL           = llama-3.3-70b-instruct:q4_k_m  # confirmed pulled live 2026-07-26 (also :q3_k_m available)
TESTED_FALLBACK_MODEL   = command-r-35b-dark-horror-v2-d_au:q4_k_s
REJECTED_FOR_TOOLS      = qwen3.6-35b-a3b-ud:q4_k_m     # Decision 12 — do not use as primary
ANALYSIS_CANDIDATE      = deepseek-r1-distill-qwen-32b:q4_k_m   # non-tool roles only
EMBEDDING_MODEL         = nomic-embed-text:latest

LAB_TARGET              = 192.168.1.113   # Metasploitable 2 — confirm still authorized/in-scope before Phase 4
```

**Storage note:** don't size `LXC_ROOTFS_GB` the way the original draft did (a flat 80G rootfs). Every Docker-enabled stack in this repo (`ai-services-stack`, `minecraft-stack`, etc.) keeps Docker's own data on a separate `docker_mount`/`docker_storage_size`, not inside rootfs — `pentagi-stack`'s `stack.yaml` should do the same, sized for `pgvector`'s data plus pulled images (`vxcontrol/pentagi`, `vxcontrol/scraper`, `vxcontrol/pgvector`, `vxcontrol/kali-linux`), not folded into a single oversized rootfs.

**Model policy note:** `docs/framework-integration/decisions.md` Decision 12 is an explicit, evidence-based policy to stop using Qwen models (2.5-Coder-32B, 3.6-35B-A3B) for anything requiring reliable structured tool calls, after repeated malformed/hallucinated tool-call failures in VSCode/Copilot/Continue — Llama-3.3-70B-Instruct is the model already proven reliable for tool-calling on this stack. Since PentAGI's entire execution loop depends on clean tool-call parsing, Phase 2's preflight tests Llama-3.3-70B-Instruct as `PRIMARY_MODEL` first.

**Important caveat, not yet resolved**: Decision 12's evidence is from VSCode/Copilot/Continue clients, not PentAGI itself — PentAGI calibrates tool-call parsing independently (the "failed to determine tool call ID template" error below is PentAGI-specific, not something the VSCode investigation ever hit). Llama-3.3-70B-Instruct is the *strongest available prior* going into Phase 2's preflight, not a confirmed-for-PentAGI fact yet — treat Phase 2.2's tool-call test against it as still genuinely load-bearing, not a formality.

### Model lessons learned (from earlier hands-on PentAGI testing)

The primary PentAGI model must support structured tool calls. These are the concrete results from testing PentAGI directly (Kali VM + Framework Desktop, before this plan existed) — kept because they're real evidence about which models fail and how, even though the *choice* of primary model above has since changed:

`qwen3.6-35b-a3b-ud:q4_k_m` was the model actually used in that earlier testing and did calibrate — its Ollama metadata exposes:

```json
{
  "capabilities": [
    "tools",
    "thinking",
    "completion"
  ]
}
```

**Do not use it as `PRIMARY_MODEL` regardless** — per the policy note above, Qwen's tool-calling reliability problems are broader than this one PentAGI session happened to catch. Kept only as `REJECTED_FOR_TOOLS` context.

The fallback model confirmed to work with PentAGI tools in that same testing is:

```text
command-r-35b-dark-horror-v2-d_au:q4_k_s
```

— still a reasonable `TESTED_FALLBACK_MODEL` if Llama-3.3-70B-Instruct's PentAGI-specific preflight (Phase 2) unexpectedly fails.

The DeepSeek model:

```text
deepseek-r1-distill-qwen-32b:q4_k_m
```

performed well in offensive-security reasoning tests, but failed PentAGI provider calibration because it did not produce usable structured tool calls:

```text
failed to determine tool call ID template:
no tool call ID samples collected
```

It may still be useful for separately tested non-tool analysis roles (`ANALYSIS_CANDIDATE` above), but it should not be a provider for PentAGI agents that must invoke terminal, browser, search or delegation tools.

### Actual execution path

```text
Agent produces a tool call
        ↓
PentAGI invokes terminal/browser/search tool
        ↓
Worker container executes it
        ↓
PentAGI embeds and stores the result in pgvector
        ↓
Result is returned to the agent
        ↓
Agent chooses the next action
```

This is operationally important.

A command can execute successfully but still be treated as failed if PentAGI cannot embed and store the result. During testing, a misspelled embedding model caused PentAGI to repeat a successful ping several times:

```text
Configured incorrectly: nomic-embed-txt
Installed model:        nomic-embed-text:latest
```

Until the complete execution-and-storage path is validated, smoke-test commands must be harmless and idempotent.

---

## Phase 0 — Zone and stack scaffolding

**[WHERE: MikroTik/operator action, then workstation]**

This replaces raw `pct create`/manual Docker install with this repo's normal path: every service is a `terraform/lxc/stacks/<name>/stack.yaml` + Ansible role, built via `terraform/lxc/scaffold-stack.sh`, not hand-run commands. The original draft's separate "install Docker inside the LXC" phase is **not needed as a manual step** — `debian-13.1-2-docker-template.tar.gz` already ships Docker preinstalled (`ansible/00-initial-setup/build-debian-13-template.yml`), and the standard `docker_mount`/`docker_storage_size` stack-contract fields handle the rest, the same way `ai-services-stack` and every other Docker-based stack in this repo already work. Nothing PentAGI-specific is needed there — Phase 1 below picks up directly with templating and deploying PentAGI's own Compose stack once the container exists (no interactive installer — see Phase 1's note).

### 0.1 Out-of-band: MikroTik trunk tagging (operator action) — **done, 2026-07-26**

The MikroTik and `pve-test-vm`'s physical trunk port both now carry the new `pentest_seg` VLAN (70) as an 802.1Q tag — same prerequisite Decision 4 hit for `ai_seg`, done via RouterOS CLI directly (operator, over SSH), not Ansible/REST automation, matching how `ai_seg` was done too. Full command trail and the live-verified cross-zone firewall policy are in §0's Network zone section above. Verified via `ping 192.168.70.1` from the workstation (0% loss) — **not** a self-ping on the router, which isn't a reliable test on RouterOS for a bridge-VLAN sub-interface's own address.

### 0.2 Declare the zone — **done, 2026-07-26**

`pentest_seg` was added to `terraform/lxc/network/pve-test-vm.yaml` (attachment, `zones:` entry, and `policies:` entries), following the exact shape of `infra_seg`/`mgmt_seg`. **Real gotcha hit and fixed**: Proxmox SDN zone names are capped at **8 characters** — the originally planned `tvpentest` (9 chars) was rejected by `pvesh` with `zone: value may only be 8 characters long`. Renamed to `tvpent` throughout (attachment `bridge`/`zone`/`vnet` in `network.yaml`, matching what the MikroTik-side commands in §0 above already used). Also required two new Terraform variables that didn't exist yet — `lab_ip_pentagi`, `lab_gw_pentest`, `lab_subnet_pentest_cidr` in `terraform/lxc/variables.tf` and `main.tf`'s `stack_template_vars` map — every zone needs its own declared Terraform variable, not just an env var.

Validated per `CLAUDE.md`'s "Terraform/network/SDN — additive only" tier: `terragrunt plan` showed a clean `5 to add, 0 to change, 0 to destroy` before applying.

### 0.3 Scaffold the stack — **done, 2026-07-26**

**Not actually scaffolded via `scaffold-stack.sh`.** That OpenCode-agent-driven scaffolder turned out to be effectively unused in this repo — its own exemplar (`minecraft-stack`) doesn't exist anywhere in the tree anymore, and two of its five "agents" (`stack-yaml-writer`, `playbook-writer`) just write exact content verbatim rather than generating anything, so there was no real benefit over authoring directly. Instead, `pentagi-stack` was hand-built following the actual, currently-deployed convention (`graylog-stack`'s shape): `stack.yaml` + `edge.yaml` under `terraform/lxc/stacks/pentagi-stack/`, `terragrunt.hcl` under `terraform/lxc/environments/pve-test-vm/pentagi-stack/` (fixed boilerplate, identical to every other stack's), and the full deploy logic in `terraform/lxc/ansible/playbooks/deploy-pentagi-stack.yml` — Harbor-rewritten vendored `docker-compose.yml` embedded via Jinja, `.env` templated separately. Passed `ansible-playbook --syntax-check` and this repo's stack validators (which, like the scaffolder, only cover a narrow hardcoded stack list that `pentagi-stack` isn't part of — consistent with most real stacks here).

Applied via `terragrunt apply`: 5 resources added (LXC container VMID `70010`, the SDN zone/vnet/subnet, ansible inventory, container epoch), 0 changed, 0 destroyed.

### Acceptance criteria

- ✅ `pentest_seg` exists as a live SDN zone on `pve-test-vm` (`tvpent`), confirmed the same way `ai_seg` was verified (workstation ping, not a router self-ping)
- ✅ `terraform/lxc/stacks/pentagi-stack/` has `stack.yaml` + `edge.yaml`; `terragrunt.hcl` lives under `environments/pve-test-vm/pentagi-stack/`
- ✅ `scripts/provision.sh --stack pentagi-stack` runs clean against `pve-test-vm` (`failed=0`)
- ✅ The LXC started, `unprivileged: true`, VMID `70010`, IP `192.168.70.10`, landed in `pentest_seg`
- ✅ `docker info` inside the container reports a working driver with no setup steps taken beyond what the template already provides
- ✅ `registry_host`/`apt_cacher_host` set and match the values every other `pve-test-vm` stack uses

---

## Phase 1 — Install PentAGI

**[WHERE: inside the Debian LXC, driven by the `pentagi_stack` Ansible role]**

**No interactive installer.** The console-driven setup you had to work through by hand is a convenience wrapper around a plain `docker-compose.yml` + `.env` file — confirmed directly from `vxcontrol/pentagi`'s own repo (`docker-compose.yml`, `.env.example`). The Ansible role templates that `.env` from the stack's variables and runs `docker compose up -d` directly; nothing here needs a console session. If you still have your original install directory, it's worth sharing so the role's default values (model names, thresholds, anything you tuned by hand) can be cross-checked against what actually worked for you, rather than re-guessed from the vendor's defaults.

### 1.1 Vendor the compose file and template the `.env`

Pull `docker-compose.yml` from the pinned PentAGI release into `terraform/lxc/ansible/roles/pentagi_stack/templates/docker-compose.yml.j2`, with images rewritten to pull through Harbor's `dockerhub`/`quay` proxy-cache projects — the same pattern `deploy-graylog-stack.yml` and `deploy-monitoring-stack.yml` already use (`terraform/lxc/ansible/roles/harbor_postconfigure` creates these proxy projects):

```yaml
# was: image: vxcontrol/pentagi:latest
image: {{ pentagi_registry_host }}/dockerhub/vxcontrol/pentagi:latest
# was: image: vxcontrol/pgvector:latest
image: {{ pentagi_registry_host }}/dockerhub/vxcontrol/pgvector:latest
# was: image: vxcontrol/scraper:latest
image: {{ pentagi_registry_host }}/dockerhub/vxcontrol/scraper:latest
# was: image: quay.io/prometheuscommunity/postgres-exporter:v0.16.0
image: {{ pentagi_registry_host }}/quay/prometheuscommunity/postgres-exporter:v0.16.0
```

`pentagi_registry_host` is derived from `LAB_FQDN_HARBOR`/`LAB_IP_HARBOR`, same as every other Harbor-routed stack. The role's first play also needs the standard `insecure-registries` stanza in `/etc/docker/daemon.json` (see `deploy-graylog-stack.yml:24` for the exact task) — Docker won't trust Harbor's HTTP-only registry endpoint otherwise.

`apt-cacher-ng` needs **no equivalent work** — it's handled generically by the shared `lxc_base` role (every stack's first included role) purely from `apt_cacher_host` in `stack.yaml`. Just set it like every other stack does; nothing PentAGI-specific here.

The pentest worker image also needs the same rewrite, since it's pulled independently by PentAGI itself, not by this Compose file:

```dotenv
DOCKER_DEFAULT_IMAGE_FOR_PENTEST={{ pentagi_registry_host }}/dockerhub/vxcontrol/kali-linux:latest
```

### 1.2 Template `.env` — provider settings

Values below replace what the interactive installer would have asked for, sourced directly from `.env.example`'s real variable names:

```dotenv
OLLAMA_SERVER_URL=http://framework.gibbsgreatly.xyz:11434
OLLAMA_SERVER_API_KEY=
OLLAMA_SERVER_MODEL={{ pentagi_stack_primary_model }}   # llama-3.3-70b-instruct:q4_k_m

EMBEDDING_URL=http://framework.gibbsgreatly.xyz:11434
EMBEDDING_MODEL=nomic-embed-text:latest
EMBEDDING_PROVIDER=ollama
EMBEDDING_STRIP_NEW_LINES=true
```

Use the native Ollama base URL — do not append `/v1`. The model name must match `ollama list` on `framework.gibbsgreatly.xyz` exactly; do not configure `nomic-embed-txt`.

**Model policy**: default `pentagi_stack_primary_model` to `llama-3.3-70b-instruct:q4_k_m` — confirmed actually pulled and available on `framework.gibbsgreatly.xyz`'s Ollama via a live `/api/tags` check (2026-07-26; `:q3_k_m` is also present as a smaller/faster alternative) — not `qwen3.6-35b-a3b-ud`, per Decision 12's evidence-based ban on Qwen for reliable structured tool calls. If Llama-3.3-70B-Instruct's own preflight (Phase 2) fails, fall back to `command-r-35b-dark-horror-v2-d_au:q4_k_s` (`TESTED_FALLBACK_MODEL`, also confirmed present) next — not Qwen, which stays rejected regardless of how the other two perform.

### 1.3 Template `.env` — search tools

```dotenv
SEARXNG_URL=http://framework.gibbsgreatly.xyz:8082
DUCKDUCKGO_ENABLED=true
SPLOITUS_ENABLED=true
```

Leave every paid-API search key (`GOOGLE_API_KEY`, `TAVILY_API_KEY`, `PERPLEXITY_API_KEY`, etc.) blank unless intentionally configured later.

### 1.4 Template `.env` — agent execution settings

```dotenv
ASK_USER=true
ASSISTANT_USE_AGENTS=false
EXECUTION_MONITOR_ENABLED=true
EXECUTION_MONITOR_SAME_TOOL_LIMIT=5
EXECUTION_MONITOR_TOTAL_TOOL_LIMIT=10
MAX_GENERAL_AGENT_TOOL_CALLS=100
MAX_LIMITED_AGENT_TOOL_CALLS=20
AGENT_PLANNING_STEP_ENABLED=true
```

Same reasoning as before: user interaction lets the agent ask rather than guess; execution monitoring catches loops; task planning trades a bit of latency for discipline. Initial local-model runs may take minutes between visible commands.

### 1.5 Template `.env` — server, auth and secrets

```dotenv
PENTAGI_LISTEN_IP=0.0.0.0
PENTAGI_LISTEN_PORT=8443
PUBLIC_URL=https://pentagi.{{ lab_domain }}
CORS_ORIGINS=https://pentagi.{{ lab_domain }}
SERVER_USE_SSL=false
COOKIE_SIGNING_SALT={{ pentagi_stack_cookie_salt }}   # from terraform/secrets.common.enc.yaml
PENTAGI_POSTGRES_PASSWORD={{ pentagi_stack_postgres_password }}   # from terraform/secrets.common.enc.yaml
```

`SERVER_USE_SSL=false` is deliberate: Traefik terminates TLS externally (Phase 3), so PentAGI serves plain HTTP internally, matching how every other web UI in this platform is fronted — no self-signed-cert handling needed on the Traefik side. `PUBLIC_URL`/`CORS_ORIGINS` use `pve-test-vm`'s own domain (`LAB_DOMAIN=test.gibbsgreatly.xyz`), not `lab.gibbsgreatly.xyz` (that's `pve`'s domain — see `.env.pve-test-vm`).

**`PENTAGI_POSTGRES_PASSWORD` must be generated URL-safe — real bug hit live, 2026-07-26.** This value gets embedded directly into `DATABASE_URL=postgres://...:${PENTAGI_POSTGRES_PASSWORD}@pgvector:5432/...` via plain Docker Compose variable substitution, which has no way to URL-encode it. A `base64`-generated secret (`openssl rand -base64 24`) can contain `/`, which Go's URL parser reads as the path separator — `pentagi` went into a silent restart loop with `invalid port ... after host` in its logs, even though every container had actually started successfully. Generate this secret with `openssl rand -hex 24` instead (alphanumeric only). Because `pgvector` bakes the password into its data volume at first `initdb`, discovering this after the fact also means wiping `pentagi-stack_pentagi-postgres-data` and letting it reinitialize — cheap here since nothing real was in it, but don't assume a password rotation is ever just an `.env` edit once real data exists.

**OAuth reality check**: PentAGI's own login only supports Google and GitHub OAuth — confirmed directly from its Go source (`backend/pkg/server/oauth/{google,github}.go`, no generic/custom OIDC client). `OAUTH_GOOGLE_CLIENT_ID`/`OAUTH_GITHUB_CLIENT_ID` are real env vars but neither is Authentik. Leave both blank; Authentik integration happens at the Traefik layer instead (Phase 3), not here.

### 1.6 Deploy and verify

```bash
docker compose up -d
docker compose ps
```

Expect four long-lived containers:

```text
pentagi
pgvector
scraper
pgexporter
```

PentAGI creates temporary execution containers later, for example `pentagi-terminal-4`.

Inspect logs and mounts:

```bash
docker logs --tail 100 pentagi

docker inspect pentagi \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

### Acceptance criteria — all met, 2026-07-26

- ✅ `pentagi`, `pgvector`, `scraper` and `pgexporter` are running, all images pulled through Harbor (`docker inspect` confirms `harbor.test.gibbsgreatly.xyz/dockerhub/...` / `.../quay/...`, not a raw Docker Hub/quay.io reference)
- ✅ `pgvector` is healthy
- ✅ PentAGI starts without provider or database errors — `goose: successfully migrated database to version: 20260511`, `API server listening on 0.0.0.0:8443`, and `curl http://localhost:8443/` returns `HTTP 200`
- ✅ The Docker socket is mounted as intended
- ✅ No unexpected cloud LLM provider is configured
- ✅ No console/TUI installer session was required at any point

Two real bugs hit and fixed along the way, both documented above and in `README.md`: `pentest_seg`'s containment initially missed the Harbor-via-Traefik path (all pulls timed out), and the first `PENTAGI_POSTGRES_PASSWORD` was base64-generated and broke `DATABASE_URL` parsing (silent restart loop despite every container "running").

---

## Phase 2 — Provider and dependency preflight

**[WHERE: Framework, LXC and test containers]**

Complete these checks before running a real autonomous flow.

### 2.1 Confirm the primary model capabilities

Test `PRIMARY_MODEL` first (default `llama-3.3-70b-instruct:q4_k_m` — see the model policy note in §0). On the Framework:

```bash
curl -s http://127.0.0.1:11434/api/show \
  -d '{"model":"llama-3.3-70b-instruct:q4_k_m"}' |
jq '{capabilities, model_info}'
```

Required capabilities:

```text
completion
tools
thinking
```

`context_length` lives under a family-specific key in `model_info` (e.g. `llama.context_length` for Llama, `qwen35moe.context_length` for Qwen) — dump the whole `model_info` object first rather than guessing the key, then narrow the `jq` filter once you know it.

### 2.2 Verify structured tool calling directly

```bash
curl -s http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "llama-3.3-70b-instruct:q4_k_m",
    "stream": false,
    "messages": [{
      "role": "user",
      "content": "Call run_command with exactly: printf PENTAGI_TOOL_TEST_OK"
    }],
    "tools": [{
      "type": "function",
      "function": {
        "name": "run_command",
        "description": "Run a harmless shell command",
        "parameters": {
          "type": "object",
          "properties": {
            "command": {"type": "string"}
          },
          "required": ["command"]
        }
      }
    }]
  }' |
jq '.message | {content, thinking, tool_calls}'
```

Acceptance requires a populated `tool_calls` array. **This is the check that actually resolves the caveat in §0** — Decision 12's evidence covers VSCode/Copilot/Continue, not PentAGI's own provider calibration; this is the first direct confirmation either way. If it fails, fall back to `TESTED_FALLBACK_MODEL` (`command-r-35b-dark-horror-v2-d_au:q4_k_s`) before considering Qwen at all.

If PentAGI later reports:

```text
failed to determine tool call ID template:
no tool call ID samples collected
```

the provider calibration did not receive usable tool calls. That is a model or template compatibility failure, not a Docker failure.

### 2.3 Verify the embedding model

From the LXC:

```bash
curl -s http://framework.gibbsgreatly.xyz:11434/api/embed \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "nomic-embed-text:latest",
    "input": "PentAGI embedding preflight"
  }' |
jq '{
  model,
  dimensions: (.embeddings[0] | length),
  error
}'
```

Acceptance:

- No error
- A non-zero embedding dimension
- The exact model tag is accepted

This check is mandatory because embedding failure can make PentAGI retry commands that already completed successfully.

### 2.4 Verify SearXNG JSON output

```bash
curl -sG 'http://framework.gibbsgreatly.xyz:8082/search' \
  --data-urlencode 'q=Metasploitable vulnerabilities' \
  --data-urlencode 'format=json' |
jq '{
  result_count: (.results | length),
  first: .results[0]
}'
```

On the Framework, SearXNG `settings.yml` must include:

```yaml
search:
  formats:
    - html
    - json
```

Restart SearXNG after modifying its configuration.

### 2.5 Test reachability from inside Docker

Testing from the LXC host alone is insufficient.

```bash
docker run --rm curlimages/curl:latest \
  -fsS http://framework.gibbsgreatly.xyz:11434/api/tags
```

```bash
docker run --rm curlimages/curl:latest \
  -fsSG http://framework.gibbsgreatly.xyz:8082/search \
  --data-urlencode 'q=test' \
  --data-urlencode 'format=json'
```

### 2.6 Verify the effective Ollama context

Load or use the primary model, then run on the Framework:

```bash
docker exec ollama ollama ps
```

Check:

- Model name
- Effective context allocation
- `100% GPU`
- Memory size
- Keep-alive time

Do not automatically create a custom model tag only because the model advertises a large maximum context.

Use this sequence:

1. Load the model.
2. Check `ollama ps`.
3. If the effective context is already at least 64K, and preferably around 110K–131K, keep the existing tag.
4. Create a custom tag only if the allocated context is too small.

Example only when needed:

```text
FROM llama-3.3-70b-instruct:q4_k_m
PARAMETER num_ctx 131072
```

### Acceptance criteria — all met, 2026-07-26

- ✅ `PRIMARY_MODEL` (`llama-3.3-70b-instruct:q4_k_m`) produces structured tool calls via Ollama's own `/api/chat` — a clean populated `tool_calls` array with correct `function.name`/`function.arguments`, no malformed JSON. **This is the first direct confirmation for PentAGI's own provider calibration path** (Decision 12's evidence was from VSCode/Copilot/Continue, not Ollama's native tool-calling API) — resolved, not just a strong prior anymore.
- ✅ The embedding API returns a valid vector — `nomic-embed-text:latest`, 768 dimensions, no error.
- ✅ SearXNG returns valid JSON with `format=json` — **but note**: at test time, most of SearXNG's underlying engines were rate-limited/blocked (`brave`/`google cse`: "too many requests", `startpage`: "CAPTCHA", `duckduckgo`: "timeout"), a pre-existing operational state on `framework.gibbsgreatly.xyz`'s SearXNG instance, not something this deployment caused. Format works; actual result yield may be degraded until those engines cool down. Worth rechecking before relying on SearXNG results in Phase 4.
- ✅ A Docker container on `pentagi-stack` can reach both Ollama and SearXNG (`docker run curlimages/curl` → both `HTTP 200`).
- ✅ Ollama reports an adequate effective context and full GPU execution — confirmed via `/api/ps`: `context_length: 131072`, `size_vram` equals `size` (85.6GB), i.e. 100% GPU-resident, no CPU offload.
- ✅ No cloud provider keys are unintentionally configured (`.env` has them all blank, per Phase 1).

---

## Phase 3 — Expose the PentAGI UI through Traefik, with Authentik forward-auth in front

**[WHERE: `pentagi-stack`'s `edge.yaml`, Traefik, Authentik]**

This repo doesn't do ad hoc reverse-proxy config per stack — every service gets a declarative `terraform/lxc/stacks/<stack>/edge.yaml`, rendered into Traefik dynamic config by `terraform/lxc/render-edge-traefik.py` and (for OIDC-capable apps) reconciled against Authentik by `terraform/lxc/reconcile-authentik-edge.py`. There's no "direct LAN access, no proxy" option to choose between — PentAGI joins that same path.

### 3.1 `edge.yaml`

```yaml
metadata:
  annotations: {}
spec:
  routes:
    - name: pentagi
      host: pentagi.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_PENTAGI}:8443
      tls:
        resolver: letsencrypt   # or step-ca's resolver, matching pve-test-vm's convention
      auth:
        mode: forwardAuth
```

`auth.mode: forwardAuth`, not `oidc` — PentAGI's own login only supports Google/GitHub OAuth (confirmed from source, Phase 1), so it can't be the native-OIDC party the way OpenWebUI/Grafana/Portainer are. `forwardAuth` routes through Traefik's `authentik` middleware (`render-edge-traefik.py`'s `router["middlewares"] = ["authentik"]` branch) instead, gating access to the whole UI at the edge before any request reaches PentAGI's own login page — same fallback Decision 8 already describes for apps without usable native OIDC.

**Confirmed (2026-07-26): `forwardAuth` reconciliation is real and automated, not a manual step.** `reconcile-authentik-edge.py` has dedicated `forwardAuth` handling — it creates/updates an Authentik **Proxy Provider** (`create_proxy_provider`/`update_proxy_provider`, distinct from the `oidc`-mode `create_oauth2_provider` path), attaches it to a single **shared forward-auth outpost** (`SHARED_FORWARD_OUTPOST`) that already serves every `forwardAuth`-mode host, and actively probes each host's forward-auth endpoint (`_validate_forwardauth_endpoint_serving`, error code `AKR004` if a host 404s or doesn't respond) as part of reconcile. Adding `pentagi.${LAB_DOMAIN}` as a `forwardAuth` route means joining that existing shared outpost's host list — no new per-app Authentik object to hand-create, and no separate client-id/secret pair the way `oidc` mode needs.

### 3.2 PentAGI's own login stays as defense-in-depth, not the primary gate

Authentik forward-auth controls *who reaches the UI at all*; PentAGI's own account system still exists behind it. A fresh install creates:

```text
Email:    admin@pentagi.com
Password: admin
```

Change this password immediately after first login regardless of the Authentik layer in front — don't rely on forward-auth alone to cover a default credential.

### 3.3 Practical requirements carried over from the original draft

Traefik still needs to, same as any other backend here:

- Preserve WebSocket upgrades (terminal streaming)
- Support long-lived GraphQL subscriptions
- Use timeouts long enough for multi-minute local-model calls — check this against whatever default `render-edge-traefik.py` applies; PentAGI's agent turns can run far longer than a typical web request

### Acceptance criteria

- `pentagi.${LAB_DOMAIN}` resolves and routes through Traefik, not a direct `<LXC_IP>:8443` connection
- Authentik forward-auth actually gates the route — an unauthenticated request is redirected to Authentik login, not straight to PentAGI
- PentAGI's own login succeeds using the changed password, behind the Authentik gate
- The default PentAGI password no longer works
- Browser live updates and terminal streaming work end-to-end through Traefik
- Port 8443 is not reachable directly from outside `pentest_seg` — only Traefik's route reaches it

---

## Phase 4 — Layered validation

**[WHERE: PentAGI UI and LXC logs]**

Do not begin with a full autonomous penetration test. Validate the platform one layer at a time.

### Test 1 — direct Assistant tool call

Create an Assistant with **Use Agents disabled**.

Prompt:

```text
Use the terminal tool directly.

Run:
printf 'PENTAGI_TOOL_TEST_OK\n'
uname -a

Return the output and finish.
```

Expected command output resembles:

```text
PENTAGI_TOOL_TEST_OK
Linux <container-id> <kernel> x86_64 GNU/Linux
```

Acceptance:

- One `pentagi-terminal-*` container appears
- The terminal command completes
- PentAGI returns the output
- The command is not repeated
- Logs contain no embedding or provider errors

### Test 2 — agent delegation

Repeat with **Use Agents enabled**.

Expect more latency because PentAGI may:

- Delegate to a specialist
- Generate a plan
- Call the model several times
- Interpret the result
- Invoke a reflector on malformed output
- Generate a final response

Use PentAGI Analytics to inspect:

- Agent roles invoked
- Model calls
- Token counts
- Tool-call counts
- Duration by agent

### Test 3 — scoped Metasploitable flow

**Prerequisite, and a real tension worth naming rather than glossing over**: `pentest_seg`'s cross-zone policy (§0) is written as "only the specific ports/protocols the authorized test actually needs" — but a real pentest against `LAB_TARGET` (`192.168.1.113`) legitimately needs enumeration across a wide, not-known-in-advance port range (that's what "enumerate exposed services" in the prompt below means). Don't try to force a narrow allowlist the way `infra_seg`/`mgmt_seg`'s policies do for known, fixed application ports. The honest version of "scoped" here is scoping by **destination IP** (only `LAB_TARGET`, nothing else on the LAN) rather than by port — add a `pentest_seg → 192.168.1.113` policy allowing the full TCP/UDP range to that one host specifically, and rely on the single-destination restriction (plus the "no other IP" restriction in the prompt itself) as the actual containment, not a port list.

```text
Perform an authorised penetration test against the single lab target
192.168.1.113, which is Metasploitable 2.

Objectives:
- Enumerate exposed services.
- Identify plausible vulnerabilities.
- Validate findings using non-destructive techniques.
- Record exact commands and evidence.
- Produce a final report.

Restrictions:
- Do not scan or contact any other IP address.
- Do not perform denial-of-service testing.
- Do not establish persistence.
- Do not pivot to other systems.
- Do not modify or delete target data.
- Ask before any potentially disruptive action.
```

### Monitor logs

```bash
docker logs --since 30m pentagi 2>&1 |
grep -Ei \
  'error|warning|failed|embedding|tool call|provider|flow_id'
```

Explicitly fail validation if logs contain:

```text
no tool call ID samples collected
```

or:

```text
model "nomic-embed-txt" not found
```

Also investigate if harmless terminal commands repeat without a clear agent-level reason.

### Lesson from the repeated ping

The initial repeated ping was not necessarily a model loop.

PentAGI successfully executed:

```bash
ping -c 2 -W 2 192.168.1.113
```

but failed to store the result because the embedding model name was incorrect. It retried the complete tool call and eventually aborted after reaching its retry limit.

This demonstrates why end-to-end storage validation is necessary before testing non-idempotent actions.

### Acceptance criteria

- Direct tool mode completes once
- Agent mode completes successfully
- PentAGI spawns and removes execution containers as expected
- A scoped flow progresses from reachability to enumeration
- Tool results are stored in long-term vector memory
- No cloud LLM fallback occurs
- The final report contains traceable evidence

---

## Phase 5 — Operations, backups and upgrades

**[WHERE: LXC and Proxmox]**

### 5.1 Back up configuration and data

Preserve:

- `.env`
- Compose files and overrides
- Custom provider YAML
- PentAGI data directory
- PostgreSQL/pgvector data
- TLS certificates
- Reverse-proxy configuration
- Image names and digests
- Any custom prompts and templates

### 5.2 Database backup

Determine the actual database variables from the deployment configuration, then create a compressed PostgreSQL dump.

Example:

```bash
mkdir -p /opt/pentagi/backups

docker exec pgvector pg_dump \
  -U "$PENTAGI_POSTGRES_USER" \
  -d "$PENTAGI_POSTGRES_DB" \
  -Fc >"/opt/pentagi/backups/pentagi-$(date +%F).dump"
```

Do not rely only on a live filesystem snapshot for database recovery.

### 5.3 Proxmox backups

Use regular Proxmox backups for the LXC.

Recommended pattern:

- Daily retained backups for recent recovery
- Weekly longer-retention backup
- Manual snapshot before a PentAGI upgrade
- Restore testing into a cloned LXC

### 5.4 Pin tested container images

Avoid leaving the deployment indefinitely on mutable `latest` tags — remember every image here is pulled through Harbor's `dockerhub`/`quay` proxy-cache projects (Phase 1), so reference the Harbor-prefixed name, not the raw upstream one:

```text
{{ pentagi_registry_host }}/dockerhub/vxcontrol/pentagi:latest
{{ pentagi_registry_host }}/dockerhub/vxcontrol/scraper:latest
{{ pentagi_registry_host }}/dockerhub/vxcontrol/pgvector:latest
{{ pentagi_registry_host }}/dockerhub/vxcontrol/kali-linux:latest
{{ pentagi_registry_host }}/quay/prometheuscommunity/postgres-exporter:v0.16.0
```

After validating a release:

1. Record the image IDs and digests.
2. Pin production to those versions or digests.
3. Test upgrades in a cloned LXC.
4. Back up before promotion.
5. Retain the previous images for rollback.

Capture digests:

```bash
docker image inspect \
  {{ pentagi_registry_host }}/dockerhub/vxcontrol/pentagi:latest \
  {{ pentagi_registry_host }}/dockerhub/vxcontrol/scraper:latest \
  {{ pentagi_registry_host }}/dockerhub/vxcontrol/pgvector:latest \
  {{ pentagi_registry_host }}/dockerhub/vxcontrol/kali-linux:latest \
  --format '{{index .RepoDigests 0}}'
```

### 5.5 Monitoring

At minimum, alert on:

- PentAGI unavailable or restarting
- pgvector unhealthy
- Scraper unavailable
- Disk usage above 80%
- Repeated provider errors
- Repeated embedding errors
- Excessive worker-container accumulation
- Ollama unavailable
- SearXNG returning HTML, 403 or invalid JSON
- Docker daemon failure
- LXC memory pressure or OOM events

### Acceptance criteria

- Configuration and database backups complete successfully
- A test restore is documented
- Image digests are captured and pinned
- Disk and container health are monitored
- An upgrade and rollback procedure exists

---

## Phase 6 — Split execution onto a worker node

**[WHERE: dedicated worker VM or host]**

This is the target architecture for stronger isolation.

The official worker model is more involved than changing a single Docker URL. It typically uses:

- TLS-secured Docker API on TCP 2376
- Optionally a Docker-in-Docker daemon on TCP 3376
- Client certificates on the PentAGI control plane
- Worker network access to assessed targets
- Optional out-of-band ports in the 28000–30000 range

Prefer a dedicated VM or physical host over another unprivileged LXC. The documented Docker-in-Docker worker mode may require privileged container capabilities.

### 6.1 Worker responsibilities

The worker should:

- Run PentAGI execution containers
- Reach approved assessment networks
- Reach Ollama or other required services if execution tools need them
- Be isolated from sensitive management and production networks
- Be disposable or straightforward to rebuild

### 6.2 Control-plane changes

After remote Docker is working:

- Remove the local Docker socket mount from the PentAGI control plane
- Configure `DOCKER_HOST` for the TLS-secured worker daemon
- Enable `DOCKER_TLS_VERIFY=1`
- Install the Docker client certificate and key
- Restrict worker Docker API access to the PentAGI control-plane address
- Keep the UI, database, Ollama configuration and SearXNG integration on the control plane

When PentAGI no longer needs the local Docker socket, investigate running the main service without root privileges.

### 6.3 Network controls

- Only the worker should route to assessment target networks
- The control plane should reach only the worker management API, Ollama, SearXNG, reverse proxy and required update services
- Restrict TCP 2376/3376 to the control-plane LXC
- Restrict any OOB listener range to expected target paths
- Log worker network activity

### Acceptance criteria

- Execution containers appear on the worker
- No execution containers appear on the control-plane LXC
- The local Docker socket is no longer mounted into PentAGI
- Worker Docker API requires valid client certificates
- The control plane has no direct route to sensitive target networks
- A compromised execution container is contained to the worker boundary

---

## Updated risk register

| Risk | Mitigation |
|---|---|
| Nested Docker fails in an unprivileged LXC | Enable `nesting=1,keyctl=1`; conditionally enable FUSE |
| Docker storage-driver failure | Test `overlay2`; use `fuse-overlayfs` only if required |
| Docker socket gives PentAGI root-equivalent LXC access | Use a dedicated LXC; move execution to a worker VM later |
| Worker code escapes its own container | Treat the LXC as disposable; use a dedicated worker VM for stronger isolation |
| Embedding model typo causes successful commands to repeat | Use exact tags and run `/api/embed` preflight |
| Model cannot produce structured tool calls | Run an `/api/chat` tool test before starting flows |
| DeepSeek (or any non-tool-calibrated model) is selected as the only provider | Use Llama-3.3-70B-Instruct (`PRIMARY_MODEL`) or Command-R (`TESTED_FALLBACK_MODEL`) for tool roles — not Qwen, not DeepSeek (Decision 12) |
| Thinking and orchestration cause excessive latency | Use Analytics and tune per-agent models and thinking settings |
| Ollama silently uses an inadequate effective context | Check `ollama ps`; create custom tags only when required |
| SearXNG returns HTML or HTTP 403 | Enable JSON output and test `format=json` |
| A container cannot reach Ollama or SearXNG | Run preflight tests from an ordinary Docker container |
| PentAGI UI remains bound to localhost | Set listen IP, public URL and CORS together |
| The UI is exposed with a self-signed certificate | Use a reverse proxy with a trusted certificate |
| Default administrator password remains active | Change it before LAN exposure |
| Secrets are committed to Git | Gitignore `.env`; commit only sanitised examples |
| Docker and flow data exhaust the LXC disk | Allocate a larger root disk, rotate logs and monitor usage |
| Mutable `latest` tags break a working deployment | Pin tested versions or image digests |
| Non-idempotent commands repeat after downstream failure | Layered preflight, user interaction and log monitoring |
| Remote Docker API is exposed insecurely | Require mutual TLS and firewall it to the control plane |

---

## Deployment layout — in this repo, not a standalone one

This does **not** get a separate `pentagi-deploy/` repository. It lands in `proxmox-homelab` as another stack, matching `ai-services-stack`/`llm-gpu-stack`/every other service here:

```text
terraform/lxc/stacks/pentagi-stack/
├── stack.yaml               # hostname, zone (pentest_seg), vmid, storage_profile,
│                             #   docker_mount, template_name, tags, provides,
│                             #   registry_host, apt_cacher_host
├── edge.yaml                # Traefik route + auth.mode: forwardAuth (Phase 3)
├── stack-request.yaml       # scaffolding input (kept or deleted after scaffolding)
└── (remaining standard stack files per scaffold-stack.sh's layout)

terraform/lxc/ansible/
├── playbooks/deploy-pentagi-stack.yml
└── roles/pentagi_stack/
    ├── templates/
    │   ├── docker-compose.yml.j2   # vendored from vxcontrol/pentagi, images
    │   │                            #   rewritten through {{ pentagi_registry_host }}
    │   └── env.j2                  # the whole .env — see Phase 1
    ├── tasks/main.yml               # insecure-registries daemon.json, template
    │                                 #   both files above, docker compose up -d
    └── defaults/main.yml             # PRIMARY_MODEL, EMBEDDING_MODEL, ports, etc.

terraform/lxc/network/pve-test-vm.yaml    # + pentest_seg zone (Phase 0)
terraform/lxc/discover-authentik-edge.py  # + a ("pentagi-stack", "pentagi") entry
                                            #   if forwardAuth needs one — verify (Phase 3)
terraform/secrets.common.enc.yaml         # PENTAGI_POSTGRES_PASSWORD, cookie salt,
                                            #   any future license key
```

Secrets (Postgres password, cookie-signing salt, any future license key) go through SOPS/`terraform/secrets.common.enc.yaml` and `./with-secrets`, not a bespoke `.env` in a separate repo — consistent with every other stack's secret handling in this repo (`docs/reference/secrets-management.md`).

Include an `ollama/Modelfile.*` template in the role only if preflight testing (Phase 2 below) proves the effective context or tool-call template must be changed — not by default.

---

## How to drive this with an AI coding assistant

### Agent-accessible phases

An AI assistant operating in this repo can own:

- `stack.yaml` / Ansible role / playbook content
- `pentest_seg` zone declaration in `terraform/lxc/network/pve-test-vm.yaml`
- Preflight and validation scripts
- Reverse-proxy (Traefik) configuration
- Backup scripts
- Documentation

### Tasks requiring access to other systems

The assistant needs SSH, `./with-secrets`, or a manual handoff for:

- MikroTik trunk tagging for `pentest_seg` (VLAN 70) — operator-only, out-of-band
- `terragrunt apply` for the new zone and the `pentagi-stack` LXC itself
- Anything touching Framework's Ollama/SearXNG configuration (a different host, `docs/framework-ubuntu/` owns that)
- Reverse-proxy/Authentik/firewall changes on the shared platform
- Dedicated worker deployment (Phase 6)

### Completion discipline

Use each phase's acceptance criteria as an automated or semi-automated test loop.

The agent is not finished when files merely exist. It is finished only when:

- Commands have been executed
- Expected services are running
- Preflight tests pass
- Logs are checked for known failure modes
- The phase acceptance criteria are demonstrably satisfied

---

## Official references

- PentAGI repository: <https://github.com/vxcontrol/pentagi>
- PentAGI worker-node guide: <https://github.com/vxcontrol/pentagi/blob/main/examples/guides/worker_node.md>
- Ollama API documentation: <https://docs.ollama.com/api>
- Ollama tool calling: <https://docs.ollama.com/capabilities/tool-calling>
- Ollama embeddings: <https://docs.ollama.com/capabilities/embeddings>
- Ollama context length: <https://docs.ollama.com/context-length>
- SearXNG search API: <https://docs.searxng.org/dev/search_api.html>
- Proxmox Linux Containers: <https://pve.proxmox.com/wiki/Linux_Container>
- Docker Engine installation on Debian: <https://docs.docker.com/engine/install/debian/>
