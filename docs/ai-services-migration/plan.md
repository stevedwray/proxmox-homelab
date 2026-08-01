# AI Services Migration: OpenWebUI + SearXNG off `framework`, onto `pve` via `pve-test-vm`

Status: **planned, ready to implement.** Both open questions that could
have blocked starting (free `vmid`, router auth exposure) are resolved
below — nothing left to research before Step 1.

## Getting started (fresh session)

1. This plan currently lives on `feat/mcp-utility-stack` (the branch's
   own commit history is hundreds of commits ahead of `main`, which is
   stale/unmerged in this repo — that's pre-existing repo state, not
   something to fix as part of this work). Cut a fresh branch for the
   actual implementation per the normal workflow — e.g.
   `task/ai-services-migration` — from current HEAD; don't keep piling
   implementation commits onto `feat/mcp-utility-stack` itself.
2. Start at Step 1 below. `mcp-utility-stack`'s own directories
   (`terraform/lxc/stacks/mcp-utility-stack/`,
   `terraform/lxc/environments/{pve,pve-test-vm}/mcp-utility-stack/`) are
   the concrete template to copy from — they're real, live, and proven,
   not just referenced.

## Goal

After this work, `framework.gibbsgreatly.xyz` (bare-metal Ubuntu, the GPU
host) runs **only** things directly tied to serving/storing AI models:
`llamacpp-router`, `ollama`, `comfyui` (needs local GPU/VRAM — see
"Why ComfyUI stays" below), and the model files themselves under
`/storage/models/`. OpenWebUI and SearXNG — both pure network clients of
the model-serving layer, no GPU need — move to a new `ai-services-stack`
LXC on `pve`, validated first on `pve-test-vm`, in the `ai_seg` zone
(VLAN 50) alongside `mcp-utility-stack`.

## Why ComfyUI stays on framework

ComfyUI loads diffusion checkpoints/LoRAs/VAEs directly into its own
PyTorch runtime with local GPU/VRAM access — there's no llama.cpp-style
remote serving layer for diffusion models the way there is for LLMs. It
*is* the model-serving engine for images, not a client of one, so it has
to stay wherever the GPU lives. `cadvisor` and `portainer-agent` are
low-cost host tooling, not consumer AI services — left as-is unless a
later cleanup pass wants them gone too; not blocking this migration.

## Current state (confirmed live, 2026-08-01)

**What's actually running on `framework` today** (`docker ps`):
`llamacpp-router` (:8080), `ollama` (:11434), `comfyui` (:8188),
`openwebui` (:8081), `searxng` (:8082), `cadvisor` (:8083),
`portainer-agent` (:9001). Plus host-level `postfix`,
`prometheus-node-exporter`, `chrony`, etc. — none of that is in scope
here.

**OpenWebUI + SearXNG's real deployment** is
`ansible/00-initial-setup/framework-desktop-openwebui.yml` (not the
`terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml` path —
see "Stale scaffolding to ignore" below). Compose file rendered to
`/opt/openwebui-docker/docker-compose.yml`, data in
`/mnt/container-storage/{openwebui,searxng}-data`. Key details this
migration must preserve:

- Images pinned by digest, not floating tags: `open-webui@sha256:...`
  (v0.10.2), `searxng@sha256:...` (2026.7.19+6da6eee26) — both pulled
  through `harbor.lab.gibbsgreatly.xyz`.
- OpenWebUI reaches llama.cpp and Ollama via
  `http://host.docker.internal:8080/v1` and `:11434` — a same-host
  shortcut that **will not work once OpenWebUI moves to a different
  host**. This is the one config value that must genuinely change, not
  just relocate (see Step 3).
  The LM Studio route (`https://llm.{{lab_domain}}/v1`, `LLM_GPU_STACK_API_KEY`
  auth) already goes through Traefik/the public path and needs no change.
- OIDC via Authentik app `edge-ai-services-stack-openwebui`
  (`OPENID_PROVIDER_URL`, `OAUTH_CLIENT_ID/SECRET`) — reused as-is, no
  Authentik-side change needed since the public hostname
  (`openwebui.lab.gibbsgreatly.xyz`) doesn't change, only its backend IP.
- SearXNG: `settings.yml` seeded with `formats: [html, json]` (needed for
  OpenWebUI's RAG web search — this is the same JSON-format requirement
  that turned out to matter for PentAGI's own SearXNG integration this
  session, see `docs/pentagi-stack/lessons-learned.md`), a managed
  `secret_key`, health-checked before OpenWebUI starts.
- A one-off Python/sqlite reconciliation task fixes up OpenWebUI's
  DB-stored connection settings (`openai.api_base_urls`,
  `ollama.base_urls`, `web.search.searxng_query_url`, `webui.url`)
  in case the compose env vars alone don't take effect on a config
  change — copy this pattern into the new deployment, don't skip it.
- Secrets already in `terraform/secrets.common.enc.yaml`:
  `OPENWEBUI_OIDC_CLIENT_SECRET`, `OPENWEBUI_WEBUI_SECRET_KEY`,
  `SEARXNG_SECRET_KEY`, `LLM_GPU_STACK_API_KEY` — reusable as-is, no new
  secrets needed for the move itself.

**Stale scaffolding to ignore, not reuse:**
`terraform/lxc/stacks/{llm-gpu-stack,comfyui-stack,ai-services-stack}/`,
their ansible playbooks, and
`terraform/lxc/environments/pve-framework/*` all describe LXCs on a
Proxmox node called `pve-framework` that was physically wiped when
`framework` became bare-metal (`docs/framework-ubuntu/decisions.md`
Decision 1 — an LXC memory-ceiling OOM bug, misdiagnosed for a night as
a GPU driver crash, was the actual reason Proxmox was dropped from this
box entirely). That cleanup is separately tracked as "Phase 8" in
`docs/framework-ubuntu/plan.md` and is **not** this migration's job —
don't resurrect or delete it here, just don't copy from it. The generic
Terragrunt stack/environment mechanism itself (not the AI-specific
`stack.yaml`s) is very much alive and is exactly what this migration
reuses, proven by `mcp-utility-stack`'s real deployment on `pve-test-vm`
and `pve` (see Step 1).

**`ai_seg` (VLAN 50, `192.168.50.0/24`, gateway `.1`)** is the confirmed
intended target zone — the operator already wrote this down twice, in
`terraform/lxc/network/{pve,pve-test-vm}.yaml`, before this session:
*"Operator intends to also move ai-services-stack (OpenWebUI/SearXNG,
currently flat-LAN on the Ubuntu framework host) onto this VLAN in a
future session."* Currently the zone's only tenant is `mcp-utility-stack`
(`192.168.50.110` on `pve-test-vm`, `192.168.50.10` on `pve`). Its
egress allowlist is scoped narrowly to named CVE/threat-intel API hosts
— **not sufficient for SearXNG**, which needs broad outbound reach to
arbitrary search engines. This migration must extend that policy, not
just reuse it (Step 4).

## Target architecture

```
pve-test-vm (validate) / pve (production)
  ai_seg (VLAN 50, 192.168.50.0/24)
    mcp-utility-stack   (existing, unaffected)
    ai-services-stack   (NEW — OpenWebUI + SearXNG, Docker Compose LXC)
        │
        │ cross-subnet, new firewall rule
        ▼
framework.gibbsgreatly.xyz (192.168.1.8, flat LAN)
    llamacpp-router :8080, ollama :11434, comfyui :8188
    (openwebui/searxng containers removed once cutover is verified)
```

## Steps

1. **Scaffold `ai-services-stack` fresh**, following `mcp-utility-stack`'s
   proven shape (not the stale `pve-framework` version):
   - `terraform/lxc/stacks/ai-services-stack/stack.yaml` — rewrite from
     scratch: `network.zone: ai_seg`, `vmid: 50013` (confirmed free —
     `50010`/`50011` are the stale `llm-gpu-stack`/`comfyui-stack`
     entries, `50011` is also live-reused by `mcp-utility-stack`,
     `50012` is the stale old `ai-services-stack` — `50013` is the next
     unused slot in this range as of 2026-08-02), Docker host template
     (matches the old file's shape here — it was already Docker-based,
     unlike `llm-gpu-stack`/`comfyui-stack`), no `device_passthrough`
     (no GPU need). `depends_on: [apt-cacher-stack]`.
   - `edge.yaml` — one route, `openwebui.{{LAB_DOMAIN}}` → new LXC's
     `ai_seg` IP:8081, `auth.mode: oidc` unchanged (reuses the existing
     Authentik app). SearXNG itself stays unrouted/no public Traefik
     entry, matching today's posture (LAN-reachable only, no auth, same
     as the LM Studio/llama.cpp/Ollama endpoints).
   - `terraform/lxc/environments/pve-test-vm/ai-services-stack/` and
     `.../pve/ai-services-stack/` — `terragrunt.hcl`/`inventory.yml`,
     copying `mcp-utility-stack`'s files as the template.
   - New ansible playbook (or heavily adapted copy of
     `ansible/00-initial-setup/framework-desktop-openwebui.yml`) that
     targets the new LXC instead of `framework` directly, with the
     `host.docker.internal` endpoints replaced per Step 3.

2. **Firewall**: add a MikroTik rule, `ai_seg → framework:8080,11434`
   (cross-subnet, `192.168.50.0/24 → 192.168.1.8`). This is a new,
   narrowly-scoped cross-zone rule — additive only, so per CLAUDE.md's
   validation tiers this needs `terragrunt plan` showing zero
   changes/deletions to existing resources, then apply +
   `scripts/provision.sh --stack ai-services-stack` on `pve-test-vm`
   against 1-2 adjacent stacks to confirm no regression. Full teardown
   is owed before promotion past `stable`, not required per iteration.

3. **The one real config change, not just a relocation**: point
   OpenWebUI's `OPENAI_API_BASE_URLS`/`OLLAMA_BASE_URL` at
   `http://<framework-lan-ip>:8080/v1` and `:11434` instead of
   `host.docker.internal`. **Checked live (2026-08-02): the llama.cpp
   router does not enforce `LLM_GPU_STACK_API_KEY` (or any auth) on
   direct `:8080` access** — a request with no key and a request with a
   deliberately wrong key both returned `200`. It's already reachable
   unauthenticated to anything on the flat LAN today (the port is
   published to `0.0.0.0`); making it reachable from `ai_seg` too is a
   wider network surface but not a new *authentication* gap — access
   control here is firewall-only already, same posture as Ollama's
   `:11434`. Worth flagging to the operator as a "do we want real auth
   on this now that it's a formal cross-zone dependency" question, but
   it does not block this migration — no router config change needed.

4. **Egress allowlist for `ai_seg`**: SearXNG needs to reach whatever
   search engines it's configured to query (by default a broad set —
   Google, Bing, DuckDuckGo, Wikipedia, etc.), which is fundamentally
   incompatible with the current named-FQDN allowlist built for
   `cve-mcp-server`. Decide explicitly (don't default silently) between:
   a broader named-engine allowlist (more maintenance, tighter control)
   or a more permissive default-egress-allowed-with-logging posture
   scoped to just the `ai-services-stack` IP (less maintenance, wider
   exposure). Either way this is a real, visible policy change to
   `terraform/lxc/network/*.yaml`, not just code.

5. **Data migration**: copy `/mnt/container-storage/openwebui-data` and
   `/mnt/container-storage/searxng-data` from `framework` to the new
   LXC's equivalent volumes before first start, so existing chat
   history/users/settings aren't lost. Validate the sqlite
   connection-reconciliation task (from the current playbook) still
   runs cleanly against the copied DB.

6. **Validate on `pve-test-vm`** (per CLAUDE.md's Docker Compose stack
   tier — `scripts/provision.sh --stack ai-services-stack`): OpenWebUI
   reachable, OIDC login works, chat completions succeed against both
   the llama.cpp and Ollama routes over the new cross-subnet path,
   SearXNG-backed RAG web search returns real results (the exact thing
   this session found broken for PentAGI's own SearXNG integration —
   retest that class of failure here too), no regression to
   `mcp-utility-stack` sharing the same zone.

7. **Promote to `stable`, then incremental deploy to `pve`** per the
   normal branch model. Re-point the `openwebui.{{LAB_DOMAIN}}` edge
   route at the `pve`-side LXC's IP; DNS/Traefik reconcile picks this up
   automatically (same mechanism already proven for `mcp-utility-stack`'s
   `pve-test-vm` → `pve` promotion).

8. **Decommission on `framework`**: once the `pve` instance is verified
   stable (recommend a short soak period, not an immediate same-session
   cutover), `docker compose down` the `openwebui`/`searxng` containers
   on `framework`, and remove `ansible/00-initial-setup/framework-desktop-openwebui.yml`
   from any playbook run lists (keep the file itself for reference/
   rollback until confident). Leave `llamacpp-router`, `ollama`,
   `comfyui`, `cadvisor`, `portainer-agent` untouched.

## Verification

- `docker ps` on `framework` shows only `llamacpp-router`, `ollama`,
  `comfyui` (plus `cadvisor`/`portainer-agent` if kept) once Step 8
  completes.
- OpenWebUI on `pve` serves real chat completions through both the
  llama.cpp and Ollama backends, and RAG web search returns real
  SearXNG results — not just "container is up."
- The existing Authentik OIDC login still works unchanged.
- `mcp-utility-stack` (the existing `ai_seg` tenant) shows no regression
  after the new stack and firewall/egress changes land alongside it.
- Existing OpenWebUI chat history/users are present after the data
  migration, not reset to a fresh install.

## Open questions still to resolve during implementation

1. Broad vs. narrow egress allowlist decision for SearXNG (Step 4) —
   a real tradeoff, not something to default silently.
2. Whether to also decommission `cadvisor`/`portainer-agent` on
   `framework` as part of this pass or leave them (leaning: leave them,
   they're host tooling, not consumer AI services — but worth a
   deliberate call, not silence).
3. Whether the operator wants real auth added to the llama.cpp router's
   `:8080` endpoint now that it's a formal cross-zone dependency (see
   Step 3) — not required to proceed, but worth a deliberate answer.
