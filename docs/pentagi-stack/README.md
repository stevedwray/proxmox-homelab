# PentAGI Stack

Workspace for deploying [PentAGI](https://github.com/vxcontrol/pentagi) — an
autonomous AI pentesting-agent platform — as `pentagi-stack`, a Debian LXC on
`pve-test-vm`, driving local Ollama/SearXNG on `framework.gibbsgreatly.xyz`
(the Framework Desktop — bare-metal Ubuntu 26, not Proxmox) and exposing its
web UI through Traefik.

Status: **Phase 0 and Phase 1 are done — PentAGI is live on `pve-test-vm`.**
`pentagi-stack` (VMID `70010`, `192.168.70.10`) is up, all four containers
healthy, PentAGI's own API server responding `HTTP 200`. Phase 2 onward
(provider/tool-calling preflight, Traefik + Authentik forward-auth, layered
validation) has not started yet. [plan.md](./plan.md) is the phased plan
this was executed against — kept up to date with what actually happened,
not just what was designed.

**Phase 0 done (2026-07-26)** — MikroTik trunk tagging (§0.1), the Proxmox
SDN zone (§0.2, `tvpent` — note: had to be renamed from the originally
planned `tvpentest`, since Proxmox SDN zone names are capped at 8
characters), and the `pentagi-stack` Terraform/Ansible stack itself (§0.3)
were all built and applied live via `terragrunt apply` (5 resources added,
0 changed, 0 destroyed — clean additive-only run). Full containment was
applied at the MikroTik, going beyond every other zone on this router,
which a live check found has no actual east-west isolation today despite
the documented "default-deny" intent — worth a follow-up pass across those
zones at some point, separate from this workspace.

**Phase 1 done (2026-07-26)** — PentAGI deployed via templated `.env` +
vendored, Harbor-rewritten `docker-compose.yml`, no interactive installer.
Two real bugs were found and fixed live, both worth remembering:

1. **Harbor is reached through Traefik (`edge_seg`, `192.168.30.110`), not
   at its own `infra_seg` IP.** `harbor.${LAB_DOMAIN}` resolves to Traefik's
   address, so the zone's containment needed a `pentest_seg → edge_seg`
   rule, not just `→ infra_seg`. All four image pulls timed out for ~15
   minutes before this was caught — a real gap in the original zone design,
   not a hypothetical one. (A related, easy-to-repeat mistake: the fix rule
   was first added *after* the zone's deny-all catch-all in the MikroTik's
   rule order, so it silently didn't fire until moved — the same ordering
   trap Decision 4 already warned about for `ai_seg`.)
2. **`PENTAGI_POSTGRES_PASSWORD` must be URL-safe.** It's embedded directly
   into PentAGI's `DATABASE_URL` connection string via plain Compose
   variable substitution, which can't URL-encode it. A `base64`-generated
   secret containing `/` broke Go's URL parser (`invalid port ... after
   host`), putting `pentagi` into a restart loop even though every
   container had started. Generate this one with `openssl rand -hex 24`
   (alphanumeric only), not `-base64`. Since `pgvector`'s data volume bakes
   the password in at first `initdb`, fixing this after the fact also
   requires wiping `pentagi-stack_pentagi-postgres-data` and letting it
   reinitialize — safe here since nothing real was in it yet.

Also confirmed along the way: `llama-3.3-70b-instruct:q4_k_m`/`:q3_k_m` are
live on `framework.gibbsgreatly.xyz`'s Ollama, and `forwardAuth`'s Authentik
reconciliation is fully automated (a shared forward-auth outpost, no manual
Authentik object needed) — both were open questions in the original plan,
now resolved.

## Read in this order

1. [plan.md](./plan.md) — the phased deployment plan: SDN zone + Terraform
   stack scaffolding → install PentAGI (templated `.env`, no interactive
   installer) → provider/tool-calling preflight → Traefik + Authentik
   forward-auth → layered validation → operations/backups → worker-node
   isolation. Each phase has concrete tasks and acceptance criteria.

## Key facts up front

- **Target host: `pve-test-vm`**, not `pve` — not a production node, so no
  `TASK_APPROVAL` flow applies to this build. Promotion past `stable` onto a
  production node is a separate, later decision.
- **New dedicated SDN zone required**: `pentest_seg` (VLAN 70,
  `192.168.70.0/24`) — none of `pve-test-vm`'s existing zones
  (`build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`) are a semantic fit for a
  workload holding a Docker socket with root-equivalent reach over its own
  containers, following the same precedent as `ai_seg` on `pve-framework`.
  **Blocked on operator action**: the MikroTik and `pve-test-vm`'s trunk
  port both need VLAN 70 tagged before any Terraform SDN work can proceed.
- **No interactive installer needed.** PentAGI is a plain
  `docker-compose.yml` + `.env` app under the hood (confirmed directly from
  `vxcontrol/pentagi`'s own repo) — the console-driven setup is just a
  convenience wrapper. The Ansible role templates the `.env` and runs
  `docker compose up -d` directly.
- **Harbor + apt-cacher, like every other stack.** Images are rewritten
  through Harbor's `dockerhub`/`quay` proxy-cache projects (matching
  `graylog-stack`/`monitoring-stack`); apt-cacher is automatic via the
  shared `lxc_base` role, no PentAGI-specific work needed.
- **Traefik yes, Authentik native-OIDC no.** PentAGI's own login only
  supports Google/GitHub OAuth (confirmed from its Go source — no generic
  OIDC client exists in the app itself), so it can't be a native-OIDC party
  the way OpenWebUI/Grafana/Portainer are. The plan uses Traefik's
  `forwardAuth` mode (Authentik's forward-auth middleware) to gate the UI
  at the edge instead — PentAGI's own login stays as defense-in-depth
  behind that gate, not the primary control. **Confirmed (2026-07-26)**:
  `reconcile-authentik-edge.py` already fully automates `forwardAuth` —
  a shared forward-auth outpost serves every such route, with its own
  Proxy Provider reconciliation and live endpoint-serving checks. No
  manual Authentik object needs to be hand-created.
- **Model policy**: `PRIMARY_MODEL` is `llama-3.3-70b-instruct:q4_k_m`, not
  the Qwen models used in earlier hands-on PentAGI testing — `decisions.md`
  Decision 12 is an evidence-based ban on Qwen for reliable structured tool
  calls. **Confirmed (2026-07-26)**: this exact tag (and `:q3_k_m`) is
  already pulled and live on `framework.gibbsgreatly.xyz`'s Ollama. Decision
  12's tool-calling evidence is from VSCode/Copilot/Continue, though, not
  PentAGI's own provider calibration — Phase 2's tool-call preflight is
  still the first direct confirmation either way, not a formality.
- **Lab-target network scoping is by destination IP, not by port.** A real
  pentest needs open-ended port enumeration against an authorized target,
  so `pentest_seg`'s cross-zone policy for `LAB_TARGET` allows the full
  port range to that one host specifically, rather than a fixed allowlist
  the way `infra_seg`/`mgmt_seg`'s policies work for known application ports.

## Related documentation

- `docs/framework-integration/decisions.md` — Decision 4 (dedicated SDN
  zones for new workload classes), Decision 8 (Authentik integration
  pattern, native OIDC vs. forward-auth), Decision 12 (Qwen tool-calling
  ban, Llama-3.3-70B-Instruct as the proven alternative).
- `docs/framework-ubuntu/plan.md` §0 — current, live facts about
  `framework.gibbsgreatly.xyz` (the Framework Desktop): three Ollama/
  llama.cpp/LM Studio backends, `ai-services-stack` (OpenWebUI + SearXNG),
  all independently verified.
- `docs/framework-ubuntu/local-ai-development.md` — **PentestGPT is a
  different, already-validated tool** (2026-07-24), running client-side on
  the operator's workstation against the same Ollama endpoint. Don't
  confuse it with PentAGI (this workspace) — PentAGI is a much heavier,
  server-side deployment with its own Docker-socket-holding control plane.
- `terraform/lxc/stacks/ai-services-stack/`,
  `terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml` — the
  closest existing example of this repo's Docker-stack + Harbor + Traefik +
  Authentik conventions; `pentagi-stack` follows the same shape wherever
  PentAGI's own constraints (no native OIDC, needs a Docker socket) don't
  force a difference.
- `CLAUDE.md` — branch model, validation tiers, and production credential
  controls this plan follows (`pve-test-vm` is not production-gated;
  promotion past `stable` would be).
