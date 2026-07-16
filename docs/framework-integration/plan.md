# Plan — Integrating `fe-pve` (Framework Desktop) into the Platform

Status: **planning only — nothing in this phase touches `fe-pve`, the
MikroTik, or any tracked Terraform/Ansible state.** Follows the decisions
in [decisions.md](./decisions.md); see [current-state.md](./current-state.md)
for the facts it's based on.

Goal: turn `fe-pve` from an unmanaged, flat-LAN, hand-built box into a
fully IaC-managed environment (`pve-framework`) that plugs into the existing
Traefik / Authentik / step-ca / Technitium / Harbor / NetBox platform the
same way `pve` and `pve-test-vm` do, and hosts a new AI/LLM application
stack behind that platform.

## Phase 0 — Host bootstrap (Ansible)

Nothing else in this plan is trustworthy until this phase is done, per
Decision 7.

1. Write/extend `ansible/00-initial-setup` role coverage for `fe-pve`:
   - apt repo fix (already done by hand — codify it so a reinstall doesn't
     need the manual step again)
   - `ttm.pages_limit`/`ttm.page_pool_size` grub cmdline (from
     `docs/framework/proxmox-strix-halo-setup-notes.md` §6) — new, not
     covered by any existing role today
   - `vmbr0` → VLAN-aware bridge (prerequisite for Phase 1)
2. Run `ansible/01-base-system/proxmox-terraform-setup.yml` +
   `terraform-token-management.yml` against `fe-pve` — creates
   `automation@pve` + Terraform API token, matching `pve`/`pve-test-vm`.
   The resulting token secret goes into a new
   `terraform/secrets.pve-framework.enc.yaml` (SOPS-encrypted, same shape
   as `secrets.pve.enc.yaml`) — this is what turns
   `./with-secrets-prod-framework` (already scaffolded, see Decision 6)
   from "fails cleanly, file not found" into a working production path.
3. Validate with `scripts/check-proxmox-status.sh` against `fe-pve`.
4. Decide fate of guests 9000/9001 (Decision 7 says retire once
   `llm-gpu-stack` replaces them — don't destroy them before that
   replacement is proven, since they're the only currently-working
   reference for "GPU passthrough actually works on this box").

Validation tier: this is host-bootstrap + Terraform-adjacent, so treat it
at the "Terraform / network / SDN" tier per `CLAUDE.md` — a full rebuild
cycle proves the bootstrap is real IaC, not another hand-tuned snapshot.

## Phase 1 — Network onboarding

1. **Out-of-band, mandatory first** (blocks everything below): trunk
   `fe-pve`'s physical switch port to carry the new `ai_seg` VLAN (and any
   others it needs — see Phase 3) into the MikroTik, per Decision 4 and
   the existing "adding a new segment" procedure in
   `docs/reference/sdn-segment-routing.md`. Verify with
   `ping 192.168.50.1` from a workstation before touching Proxmox.
2. Add `terraform/lxc/network/pve-framework.yaml` (new file, mirrors `pve.yaml`
   structure) defining `ai_seg` (and `mgmt_seg`/`edge_seg` *attachments*
   only if Phase 3 needs `fe-pve` to run its own Traefik/Authentik-adjacent
   pieces locally — default assumption is it doesn't; it reuses the
   existing `pve` Traefik/Authentik instances over the MikroTik-routed
   `ai_seg ↔ mgmt_seg`/`ai_seg ↔ edge_seg` policies instead).
3. Add `terraform/lxc/storage/pve-framework.yaml` per Decision 3.
4. Add cross-zone policies to `pve-framework.yaml`'s `policies:` block (and the
   MikroTik firewall, out-of-band, same as every existing policy):
   - `edge_seg (on pve) → ai_seg`: Traefik → AI-stack web UIs (OpenWebUI,
     n8n, SearXNG) and the llama-server API, if exposed directly.
   - `ai_seg → mgmt_seg (on pve)`: forward-auth callback to Authentik,
     ACME to step-ca.
   - `ai_seg → infra_seg (on pve)`: Harbor image pulls, apt-cacher (matches
     the existing "all zones → infra_seg" policy — confirm it already
     covers a cross-node zone, since `infra_seg` today only lists `pve` as
     a node).
5. Apply SDN zone via the existing manual `pvesh` procedure (Terraform/
   Ansible VLAN-zone automation is a known gap per `NETWORK_CONTRACT.md` —
   don't block this phase on fixing that gap first).
6. Point `fe-pve`'s LXCs' resolver at the MikroTik `ai_seg` gateway
   (`192.168.50.1`), same DNS-standard pattern as every other zone.

Validation tier: SDN/network change → full teardown cycle on `pve-framework`
before promoting.

## Phase 2 — Platform onboarding (DNS, PKI, IPAM, registry)

1. **Technitium**: add `pve-framework` host record and any AI-stack service names
   under `lab.gibbsgreatly.xyz` (or a dedicated subzone if you want AI
   services namespaced separately — not required, just optional).
2. **step-ca**: no new CA work needed — internal service-to-service TLS
   for `ai_seg` containers reuses the existing step-ca ACME resolver in
   Traefik, same as every other internal route. Only add `ai_seg` to
   step-ca's reachability if any container in that zone needs to call
   step-ca directly (e.g. for a cert outside Traefik's terminated routes).
3. **NetBox**: register `fe-pve` as a device, `ai_seg`'s subnet, and each
   new container's IP — same discovery pattern already used for the other
   environments (confirm whether NetBox's Docker-socket-proxy discovery
   pattern, seen in `harbor-stack/stack.yaml`, needs a matching
   `docker_socket_proxy_targets` entry once `ai_seg` containers exist).
4. **Harbor**: no new Harbor instance — `ai_seg` containers pull through
   the existing Harbor/apt-cacher over the `ai_seg → infra_seg` policy from
   Phase 1. Custom images this stack needs (a `llama-server` HIP build
   image, if containerized rather than native) get pushed to the existing
   Harbor, matching NFR-05 ("images must source from Harbor").
5. **Authentik**: add `ai_seg`'s Traefik routes as new forward-auth (or
   native-OIDC, matching whichever pattern Technitium's integration
   settled on — see `docs/dns-refactor/decisions.md`) protected
   applications — OpenWebUI, n8n, SearXNG admin, and the llama-server
   endpoint if it should require auth rather than being ai_seg-internal
   only.

## Phase 3 — AI/LLM stack, as managed Terraform/Ansible LXCs

Per Decision 5, one GPU-passthrough exception container plus
one-LXC-per-service for everything else, all in `ai_seg`:

| Stack | LXC | GPU passthrough? | Notes |
|---|---|---|---|
| `llm-gpu-stack` | 1 (native, replaces 9001) | yes | `llama-server` router mode + standalone embedding process, per `docs/framework/llamacpp-router-mode-deployment.md` |
| `openwebui-stack` | 1 | no | talks to `llm-gpu-stack`'s router endpoint over `ai_seg` |
| `n8n-stack` | 1 | no | |
| `searxng-stack` | 1 | no | |
| `postgres-stack` (or shared with n8n's own) | 1 | no | backing store for OpenWebUI/n8n |
| `redis-stack` | 1 | no | |
| `qdrant-stack` (or Chroma) | 1 | no | vector DB, per project-brief's original candidate list |

Build order: `llm-gpu-stack` first (proves GPU passthrough survives being
Terraform/Ansible-managed, the highest-risk new capability), then the
supporting services, then wire Traefik/Authentik routes last once there's
something real to route to.

New Terraform work required (doesn't exist anywhere in `terraform/lxc/modules`
today, confirmed by grep):

- A GPU-passthrough LXC module/role: `/dev/kfd` + `/dev/dri` mount entries,
  `lxc.cgroup2.devices.allow` lines, and (only if nesting Docker per the
  setup-notes doc) the AppArmor-unconfined + empty `cap.drop` pair. This is
  the single piece of net-new Terraform/Ansible capability this plan
  needs; everything else reuses the existing `lxc-docker-host` module
  pattern unchanged.

Each stack still gets a `stack.yaml`, a per-environment `terragrunt.hcl`
under `terraform/lxc/environments/pve-framework/<stack>/` (per the pattern in
`docs/environment-isolation/current-state.md` — do this correctly from
day one for every `ai_seg`-zoned stack, so `pve-framework` doesn't create its own
version of the `technitium-stack` per-environment-layout gap), and an
Ansible playbook under `terraform/lxc/ansible/playbooks/`.

## Phase 4 — Validation and promotion

Per Decision 2, `pve-framework` earns trust the same way any other environment
does — there is no separate "test-tier `fe-pve`" vs "lab-tier `fe-pve`":

1. Cut `feat/pve-framework-bootstrap` (Phase 0), validate, promote to `stable`,
   promote to `main` (host bootstrap only — low external risk, no live
   services yet).
2. Cut `feat/pve-framework-network` (Phase 1), full teardown cycle on `pve-framework`
   itself (there's no separate test copy of this physical box — the
   teardown cycle *is* the validation environment here), promote through
   `stable → main`.
3. Cut `feat/ai-stack-gpu` (Phase 3's `llm-gpu-stack` only), validate GPU
   passthrough survives a teardown/recreate cycle specifically (this is
   the highest-risk net-new capability — confirm `/dev/kfd` passthrough
   and the Vulkan batch-size workaround both still apply after a
   Terraform-driven recreate, not just a hand-built one), promote.
4. Remaining stacks (Phase 3's non-GPU services, Phase 2's platform
   onboarding) follow the Ansible-task-or-role tier from `CLAUDE.md`'s
   Validation Tiers table — lighter than a full teardown, since they don't
   touch SDN/network/PKI once Phase 1/2's plumbing is in place.
5. Decision 6's `./with-secrets-prod-framework` wrapper exists now, but is
   inert until `terraform/secrets.pve-framework.enc.yaml` exists — Phase 0
   step 2 (the Terraform token run) is what creates the value that file
   needs to hold. Until then, everything in this plan runs through
   `./with-secrets` with `ALLOW_PVE=true` for read-only inspection, never
   `./with-secrets-prod-framework`.

## Explicitly out of scope for this plan

- Rebuilding/replacing the MikroTik's role as L3 gateway — `fe-pve` adopts
  the existing model unchanged (Decision 4).
- Automating VLAN-zone creation via Terraform — the known gap in
  `configure-network-sdn-vnet.yml` (Simple zones only) is not fixed by this
  plan; `pve-framework`'s VLAN zone is applied manually like every other VLAN
  zone today.
- Model selection/benchmarking work — already done in
  `docs/framework/model-quality-and-vuln-bench-2026-07-17.md`; this plan
  only wires the already-chosen deployment pattern into the platform.
- Multi-node Proxmox clustering (`pvecm`) between `pve-framework` and `pve` — not
  needed; every zone-sharing mechanism used here already works between
  standalone nodes (proven by `pve`/`pve-test-vm` today).

## Open questions carried forward (not blocking, but need an answer before Phase 3 finishes)

- Does the llama-server endpoint sit behind Authentik forward-auth/OIDC,
  or is `ai_seg`-internal-only access (no Traefik route at all) acceptable
  for API clients, with only the web UIs (OpenWebUI etc.) going through
  Traefik+Authentik? Affects Phase 2 step 5 and Phase 1's policy list.
- Embedding-model process placement (CPU vs GPU) — flagged as untested in
  `docs/framework/llamacpp-router-mode-deployment.md`'s own "Not yet done"
  section; decide once `llm-gpu-stack` is live and real latency numbers
  exist.
- Whether `qdrant-stack` or a Chroma-based stack is preferred — no
  retrieval-quality benchmark has been run for either (same doc).
