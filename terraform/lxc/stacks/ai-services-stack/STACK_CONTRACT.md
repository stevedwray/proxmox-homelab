# ai-services-stack — Stack Contract

## Purpose

Runs OpenWebUI (chat UI/gateway) and its private SearXNG search backend
(used for OpenWebUI's RAG web search). Both are pure network clients of the
model-serving layer — llamacpp-router and Ollama, which stay on
`framework.gibbsgreatly.xyz` (bare-metal Ubuntu, the GPU host) — with no
GPU need of their own, so they've moved off that shared host onto this
dedicated `ai_seg` LXC. See `docs/ai-services-migration/plan.md` for the
full migration design and why this is a rewrite of the old, stale
`pve-framework`-era `stack.yaml`, not a reuse of it.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `ai_seg` (SDN VLAN 50) — shares this zone with `mcp-utility-stack` |
| IP           | `${lab_ip_ai_services}/24` |
| Gateway      | `${lab_gw_ai}` |
| VMID         | `50013` (`50010`/`50011` are the stale `llm-gpu-stack`/`comfyui-stack` entries, `50011` is also live-reused by `mcp-utility-stack`, `50012` is the stale old `ai-services-stack` — `50013` is the next unused slot) |

Deployed on `pve-test-vm` (`192.168.50.111`, validation) then `pve`
(`192.168.50.11`, production) — `.11`/`.111` follow the base+100
convention, the next slot after `mcp-utility-stack`'s `.10`/`.110`.

Needs two cross-zone rules beyond the zone's existing egress allowlist
(which is scoped narrowly to `mcp-utility-stack`'s CVE/threat-intel API
hosts — not sufficient here):

- Egress: `ai_seg → framework:8080,11434` (`192.168.50.0/24 →
  192.168.1.8`) so OpenWebUI can reach llamacpp-router/Ollama.
- Ingress: `edge_seg → ai_seg:8081` so Traefik can reach OpenWebUI — the
  zone's generic `edge_seg → ai_seg:[80,443]` entry is not enough on its
  own, same pattern `mcp-utility-stack` needed for its own `:8000`.
- Egress: SearXNG needs broad outbound reach to arbitrary search engines,
  fundamentally incompatible with the CVE-server-era named-FQDN allowlist
  — see plan.md Step 4 for the explicit broad-vs-narrow policy decision.

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `LAB_FQDN_HARBOR` (falls back to `harbor.${LAB_DOMAIN}`) | env var, optional | Registry host — both app images and the SearXNG-settings-seed helper image are pulled through Harbor's proxy-cache, not directly from ghcr.io/Docker Hub. FQDN via Traefik/`edge_seg`, not `LAB_IP_HARBOR`'s raw `infra_seg` IP: `ai_seg` is a contained zone (like `pentest_seg`) with no direct route to `infra_seg` — confirmed live 2026-08-02, a raw-IP pull timed out. Reuses the same `ai_seg -> edge_seg:443` rule the LM Studio route needs |
| `FRAMEWORK_HOST` (falls back to `framework.gibbsgreatly.xyz`) | env var, optional | framework's FQDN — OpenWebUI's llama.cpp/Ollama routes point here, not `LAB_IP_AI_SERVICES` (this stack's own address) or `host.docker.internal` (only valid same-host, which this LXC no longer is). Matches `deploy-pentagi-stack.yml`'s identical `pentagi_framework_host` pattern, the other contained zone reaching framework the same way |
| `LAB_DOMAIN` | env var (mandatory) | Public hostname base (`openwebui.${LAB_DOMAIN}`) |
| `LAB_FQDN_AUTHENTIK_INTERNAL` (falls back to `authentik-int.${LAB_DOMAIN}`) | env var, optional | OIDC discovery URL — deliberately the step-ca-issued **internal** direct-TLS endpoint (`mgmt_seg`), not the public `authentik.${LAB_DOMAIN}` route. That route's cert is Let's Encrypt staging on `pve-test-vm` (untrusted by design), which breaks `authlib`'s backend-side discovery fetch even though a human can click through it in a browser. See `docs/design/lessons-learned.md`'s Authentik section. Needs its own `ai_seg -> 192.168.20.110(Authentik):443` firewall rule — the first cross-zone rule into `mgmt_seg` from a contained zone. |
| `OPENWEBUI_OIDC_CLIENT_SECRET` | SOPS (`terraform/secrets.common.enc.yaml`), mandatory | Authentik app `edge-ai-services-stack-openwebui`, reused as-is — public hostname doesn't change, only its backend IP |
| `OPENWEBUI_WEBUI_SECRET_KEY` | SOPS, mandatory | Signs OpenWebUI sessions/JWTs — reused as-is so the migrated DB's existing sessions stay valid |
| `SEARXNG_SECRET_KEY` | SOPS, mandatory | SearXNG's own session secret |
| `LLM_GPU_STACK_API_KEY` | SOPS, mandatory | Sent to both the LM Studio (Traefik) and llama.cpp (direct) routes — the direct route does not actually enforce it (confirmed live 2026-08-02, see plan.md Step 3) |
| `BRAVE_SEARCH_API_KEY` | SOPS, optional | Enables SearXNG's `braveapi` engine (official API, no bot-detection issues) for OpenWebUI's RAG web search. Web search works without it, just via `bing`/`mwmbl`/`searchmysite` only — see "What Must Not Be Edited Casually" below |

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `openwebui-http` | 8081 | tcp | Container's own :8080 published as host :8081 — :8080 stays free (no LAN-facing port collision on this LXC, unlike framework which also runs llamacpp-router on :8080 there) |

SearXNG itself is intentionally unrouted — no public Traefik entry, LAN
(in-LXC compose network) reachable only, no auth, matching the LM
Studio/llama.cpp/Ollama endpoints' posture and today's framework
deployment.

## Dependencies

| Stack | Why |
|-------|-----|
| `apt-cacher-stack` | apt proxy during LXC provisioning |

`framework.gibbsgreatly.xyz` is a hard runtime dependency (OpenWebUI has
no model-serving capability of its own) but is not a Terragrunt-managed
stack — it's a bare-metal host, tracked via the `ai_seg → framework`
firewall rule above instead of `depends_on:`.

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `/var/lib/docker` | `docker_storage` (24G) | Docker image/container layers plus both named volumes below |
| `ai-services-openwebui-data` (Docker named volume) | Docker volume | OpenWebUI's `webui.db` (chat history, users, settings) — migrated from framework's `/mnt/container-storage/openwebui-data` on first deploy, see plan.md Step 5 |
| `ai-services-searxng-data` (Docker named volume) | Docker volume | SearXNG's `settings.yml` — migrated from framework's `/mnt/container-storage/searxng-data` on first deploy |

## What May Depend On This Stack

Any authenticated LAN user reaching `openwebui.${LAB_DOMAIN}` through
Traefik/Authentik OIDC. No other stack depends on it programmatically.

## What Must Not Be Edited Casually

- **`LAB_IP_AI_SERVICES` names this stack's own `ai_seg` address, not
  framework's.** Before 2026-08-02 this variable held framework's flat-LAN
  IP (`192.168.1.8`) — reusing it for OpenWebUI's backend routes would
  point OpenWebUI at itself. Use `FRAMEWORK_HOST`/`framework.gibbsgreatly.xyz`
  (FQDN, not `LAB_IP_FRAMEWORK`'s raw IP) for anything that needs to reach
  framework's own services.
- **The llama.cpp router enforces no authentication on `:8080`** (checked
  live 2026-08-02 — a request with no key and a request with a
  deliberately wrong key both returned `200`). Widening `ai_seg`'s reach
  to it is a wider network surface, not a new auth gap — it was already
  reachable unauthenticated on the flat LAN. Don't treat `LLM_GPU_STACK_API_KEY`
  on this route as real access control.
- **`OPENWEBUI_WEBUI_SECRET_KEY` must stay the value already in live use**,
  not be rotated as part of this migration — rotating it would silently
  invalidate every session in the migrated database.
- **SearXNG's `formats: [html, json]` setting is load-bearing**, not
  optional — OpenWebUI's RAG web search needs the JSON format; the same
  requirement broke PentAGI's own SearXNG integration this session (see
  `docs/pentagi-stack/lessons-learned.md`).
- **OpenWebUI's `openwebui` service has two CA bundle bind mounts, both
  required, for two different reasons.** The system path
  (`/etc/ssl/certs/ca-certificates.crt`) covers `urllib`/`aiohttp`; the
  `certifi` path (`.../site-packages/certifi/cacert.pem`) covers `authlib`
  (OpenWebUI's actual OAuth library, via `httpx`), which ignores the
  system trust store entirely. Removing either one silently breaks OIDC
  discovery with no error surfaced anywhere except a wrong/missing
  redirect. See `docs/design/lessons-learned.md`'s Authentik section.
- **Deploying via `scripts/provision.sh --stack ai-services-stack` alone
  does not publish the Traefik edge route or reconcile the Authentik
  app.** That requires a separate, manual
  `terraform/lxc/reconcile-edge.py --apply` run scoped to this stack's
  `edge.yaml`, followed by pushing the result through
  `deploy-proxy-stack.yml`. Skipping this leaves the container fully
  correct but genuinely unreachable at its public hostname — see
  `docs/design/lessons-learned.md`'s Authentik section for the exact
  commands.
- **SearXNG's `use_default_settings: true` engine set is mostly
  non-functional for OpenWebUI's RAG web search from this network** —
  confirmed live 2026-08-02: `duckduckgo`/`duckduckgo web` are TCP-level
  unreachable (reproduced from a separate workstation on the same WAN
  uplink, and confirmed at the router level — this isn't an `ai_seg`
  firewall gap), and `google cse`/`startpage`/`brave`/`qwant`/`yahoo`/
  `presearch` all bot-detect and suspend/CAPTCHA a self-hosted SearXNG's
  scraped requests. The playbook's "Ensure SearXNG's engine selection
  matches what's actually reachable" task disables those and enables
  `mwmbl`/`searchmysite`/`bing` (confirmed working) plus `braveapi` (the
  official Brave Search API, if `BRAVE_SEARCH_API_KEY` is set — optional,
  not mandatory) via an idempotent `blockinfile` on the volume's
  `settings.yml` — this survives a settings file migrated in from
  `framework` (which has the same underlying default-engine problem, just
  never surfaced because nobody stress-tested web search there).
- **Google general web search is not viable** — new Programmable Search
  Engines can't enable "search the entire web" anymore, and SearXNG's
  built-in `google_cse` engine is hardcoded to a shared third-party token
  that ignores any credentials you configure (confirmed against both this
  image and upstream SearXNG's current master). A curated-site Google
  search *is* wired up via a custom engine module
  (`searxng-engines/google_customsearch.py`, bind-mounted into the
  container — do not mount the whole directory over
  `/usr/local/searxng/searx/engines/`, that masks every built-in engine
  including bing/braveapi/mwmbl) if both `GOOGLE_CSE_ID` and
  `GOOGLE_CSE_API_KEY` are set, but it only searches whatever site list
  the CSE was configured with, not the general web. As of 2026-08-02 this
  is live in code but disabled on `pve-test-vm` pending the operator
  resolving a Google Cloud "project doesn't have access to Custom Search
  JSON API" error (API key and enabled-API project mismatch) — re-running
  `provision.sh --stack ai-services-stack` will re-enable it automatically
  once that's fixed, no playbook change needed. See
  `docs/design/lessons-learned.md`'s SearXNG section.

## Playbook

`deploy-ai-services-stack`

`docker_base` role + a single templated `docker-compose.yml`
(`community.docker.docker_compose_v2`), same pattern as
`deploy-mcp-utility-stack.yml`, adapted from the app-layer config in
`ansible/00-initial-setup/framework-desktop-openwebui.yml` (the bare-metal
deployment this stack replaces — kept for reference/rollback until the
cutover is confirmed stable, see plan.md Step 8).

## Implementation Files

| File | Role | Status |
|------|------|--------|
| `terraform/lxc/stacks/ai-services-stack/stack.yaml` | Terraform-side stack definition | existing |
| `terraform/lxc/environments/{pve,pve-test-vm}/ai-services-stack/terragrunt.hcl` | Terragrunt entrypoint (boilerplate) | existing |
| `terraform/lxc/stacks/ai-services-stack/inventory.yml` | Generated Terraform→Ansible handoff — do not hand-edit, regenerated by `terragrunt apply` | generated |
| `terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml` | Stack playbook | existing |
