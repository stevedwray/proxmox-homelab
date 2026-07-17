# Plan — Integrating `fe-pve` (Framework Desktop) into the Platform

Status: **Phases 0-1 executed and live-verified against the current
(disposable, exploration-only) box; Phase 3 has real hand-validated
findings but no Terraform/Ansible wrapping yet.** Follows the decisions in
[decisions.md](./decisions.md); see [current-state.md](./current-state.md)
for the facts it's based on.

**This is a historical/architectural record of what was done and why —
for what to actually do next, read
[post-reinstall-plan.md](./post-reinstall-plan.md) instead.** The
operator has confirmed the current box is disposable and will be wiped
and reinstalled under its real name (`pve-framework`); the phases below
describe real work already validated once (host bootstrap, `ai_seg`
networking, the ComfyUI bake-off) that now needs to survive a clean
reinstall via already-written or still-to-be-written automation, not be
redone by hand again.

Goal: turn `fe-pve` from an unmanaged, flat-LAN, hand-built box into a
fully IaC-managed environment (`pve-framework`) that plugs into the existing
Traefik / Authentik / step-ca / Technitium / Harbor / NetBox platform the
same way `pve` and `pve-test-vm` do, and hosts a new AI/LLM application
stack behind that platform.

## Phase 0 — Host bootstrap (Ansible)

Nothing else in this plan is trustworthy until this phase is done, per
Decision 7.

1. **Done (2026-07-17).** Ran `ansible/00-initial-setup/proxmox-initial-setup.yml`
   against `fe-pve` directly (ad-hoc inventory, root SSH — not yet wired
   into `ansible/inventory/dev.yml`, since it isn't part of the shared
   inventory until Phase 1). This single playbook already covers repo
   fix, subscription-nag removal, and Terraform user/token creation in
   one pass — the plan originally assumed the `01-base-system` playbooks
   would do this separately; in practice `00-initial-setup` already had
   it all. Result: 33 ok / 10 changed / 0 failed. Confirmed via the
   playbook's own assertions plus a separate read-only
   `proxmox-initial-tests.yml` run: enterprise repo gone, no-subscription
   repo active, subscription nag removed, 0 pending package upgrades,
   Terraform token created and **live-verified** against the real API
   (`GET /api2/json/version` → HTTP 200 with the new token). The token
   secret was captured straight from the Ansible run into a new
   `terraform/secrets.pve-framework.enc.yaml` (`TF_VAR_pm_api_token_id`/
   `_secret` only so far) without ever being displayed in chat, and the
   plaintext-containing log file was shredded immediately after. This is
   what turned `./with-secrets-prod-framework` from "fails cleanly, file
   not found" into a working production path — verified live, including
   that its mutating-command approval gate still correctly blocks
   `terragrunt apply` without `TASK_APPROVAL`.
   - Firewall backend (nftables) correctly stayed off — no inventory var
     enabled it, matching the "out of scope for this pass" call.
   - Not yet added to `terraform/secrets.pve-framework.enc.yaml`:
     `PROXMOX_READONLY_TOKEN_ID/SECRET` (a separate read-only discovery
     token — this playbook only creates the full-privilege Terraform
     token) and `TF_VAR_lxc_password` (no value to capture yet — nothing
     has generated one for this node). Both needed before any stack
     deployment (Phase 3).
2. **Done (2026-07-17).** Both are now real, parameterized, idempotent
   Ansible tasks, not hand-applied one-offs:
   - `ansible/00-initial-setup/proxmox-gpu-unified-memory-tuning.yml` +
     `tasks/proxmox-gpu-unified-memory-tuning.yml` — computes
     `ttm.pages_limit`/`ttm.page_pool_size` from the host's *actual*
     reported RAM (`ansible_memtotal_mb`) minus an operator-set reserved
     margin (`pmx_gpu_gtt_reserved_host_mb`, passed as `32768` for this
     box to match the 32GB margin already chosen in
     `proxmox-strix-halo-setup-notes.md` §6), rather than a hardcoded page
     count baked in for one specific box. Preserves the rest of
     `GRUB_CMDLINE_LINUX_DEFAULT` (`quiet`, etc.) untouched. Validated via
     `--check --diff` before applying for real (a real bug was caught
     this way — a `command` task got silently skipped under `--check`,
     which would have made the dry-run's preview wrong; fixed with
     `check_mode: false` on the read-only step). Applied for real:
     `GRUB_CMDLINE_LINUX_DEFAULT` updated, `update-grub` run. **Reboot
     still required** for the new GTT ceiling to actually take effect —
     deliberately not done automatically; needs its own explicit
     approval since it will interrupt the running `9001` LXC.
   - `ansible/00-initial-setup/proxmox-vlan-aware-bridge.yml` +
     `tasks/proxmox-vlan-aware-bridge.yml` — parameterized by bridge name
     and VID range (defaults `vmbr0` / `2-4094`), idempotently sets
     `bridge-vlan-aware yes` / `bridge-vids 2-4094` on the trunk bridge
     and runs `ifreload -a` to apply immediately. Applied for real against
     `fe-pve` after the operator confirmed the physical switch port was
     already added to the relevant VLANs. Verified via a **fresh** SSH
     connection afterward (not just the same Ansible run completing) that
     the host stayed reachable, `bridge vlan show dev vmbr0` reflects the
     new config, and both existing LXCs (9000 stopped, 9001 running) were
     unaffected by the reload.
   - Both playbooks are currently invoked ad-hoc (`-i "192.168.1.121,"`),
     same as Phase 0 step 1 — not yet wired into `ansible/inventory/dev.yml`.
3. Validate with `scripts/check-proxmox-status.sh` against `fe-pve`
   (not yet run).
4. Decide fate of guests 9000/9001 (Decision 7 says retire once
   `llm-gpu-stack` replaces them — don't destroy them before that
   replacement is proven, since they're the only currently-working
   reference for "GPU passthrough actually works on this box").

Validation tier: this is host-bootstrap + Terraform-adjacent, so treat it
at the "Terraform / network / SDN" tier per `CLAUDE.md` — a full rebuild
cycle proves the bootstrap is real IaC, not another hand-tuned snapshot.

## Phase 1 — Network onboarding

1. **Out-of-band prerequisite — done and fully verified end-to-end
   (2026-07-17).** This took several rounds to get right; full trail kept
   here since each round found a genuine, non-obvious bug rather than a
   repeat of the same mistake:
   - Clarified mid-Phase-0 that the switch port `fe-pve` is connected to
     was initially only configured to match `pve`'s *existing* VLAN set
     (10/20/30/40) — VLAN 50 didn't exist anywhere yet.
   - Operator added VLAN 50 on the MikroTik via RouterOS CLI (declined the
     Ansible/REST automation built for this — reasonable given the blast
     radius of the single router serving the whole network). First
     attempt silently rolled back: the CLI session was in RouterOS "safe
     mode" (`<SAFE>` prompt) and was disconnected without an explicit
     clean exit, so RouterOS reverted the whole session automatically.
     Caught by re-querying and finding nothing there; redone outside safe
     mode.
   - Operator updated the separate physical switch to carry VLAN 50 on
     `fe-pve`'s port. Live test from `fe-pve` still failed —
     "Destination Host Unreachable", no ARP reply. Root cause: every
     existing SDN zone is tagged on **both** `ether1` and `ether5` in the
     MikroTik's bridge VLAN table — `fe-pve`'s traffic actually arrives
     via `ether1` (confirmed via the bridge host table), `pve`/others via
     `ether5`. The VLAN 50 entry only had `ether5` tagged, and `ether1`
     has `ingress-filtering: true`, so it hard-dropped every VLAN 50
     frame. Fixed with `tagged=bridgeLocal,ether1,ether5`.
   - Retested: ARP now resolved and ICMP echo *requests* reached the
     router correctly (confirmed via `tcpdump` on `fe-pve`'s `nic0`), but
     no echo *reply* ever came back — a different failure mode than
     before, and progress, not a repeat. Root cause: the MikroTik's input
     firewall chain has an explicit `accept icmp` rule per zone
     (`vlan10-build`, `vlan20-mgmt`, `vlan30-edge`, `vlan40-infra`, even
     the throwaway `vlan90-test-dhcp`) ending in a catch-all drop —
     `vlan50-ai` had no such rule, so the router silently dropped its own
     reply. Fixed by adding matching `accept icmp`/`udp:53`/`tcp:53`
     rules for `vlan50-ai`, placed before the catch-all drop (rule order
     matters in RouterOS — a plain append would land after the drop and
     never fire).
   - **Final verified state**: `ping 192.168.50.1` from `fe-pve` itself
     (via a temporary `vmbr0.50` sub-interface + temporary `bridge vlan
     add vid 50 dev vmbr0 self`, both removed after testing — the host
     needed its own bridge self-VLAN-membership added for this specific
     test, which real containers won't need since they attach with their
     own per-port VLAN tag) — **0% packet loss**. `ai_seg`/VLAN 50 is
     genuinely live end-to-end: MikroTik interface + gateway + bridge
     tagging (both trunk ports) + physical switch + router firewall all
     confirmed working, not just individually present.
   - `ansible/00-initial-setup/mikrotik-ai-seg-vlan50-reconcile.yml`
     corrected to tag both `ether1`/`ether5` and to patch an existing
     bridge-VLAN entry missing a required interface. Still does not cover
     the firewall-rule gap found in the last round — would need extending
     before being trusted as a complete reconcile path. Never run by me;
     operator did every MikroTik step via CLI directly.
2. **Done (2026-07-17).** `terraform/lxc/network/pve-framework.yaml`
   added, mirroring `pve.yaml`'s structure — defines only the `ai_seg`
   attachment/zone (no local `mgmt_seg`/`edge_seg`/`infra_seg`, per the
   original plan: `fe-pve` has no local Authentik/Traefik/Harbor and
   reuses `pve`'s). `containers: []` for now — Phase 3 populates it.
3. **Done.** `terraform/lxc/storage/pve-framework.yaml` added per
   Decision 3 (LVM-thin only, profile names kept for `stack.yaml`
   compatibility).
4. **Done.** Cross-zone policies added to both files (not just
   `pve-framework.yaml` — `edge_seg` is defined in `pve.yaml`, so the
   reciprocal entry belongs there too, otherwise a reader of `pve.yaml`
   would never discover it now reaches another node):
   - `edge_seg (on pve) → ai_seg`: added to **both** `pve.yaml` and
     `pve-framework.yaml`.
   - `ai_seg → mgmt_seg (on pve)`: added to `pve-framework.yaml` (source
     zone is defined there).
   - `ai_seg → infra_seg (on pve)`: confirmed **not** needed as a separate
     entry — already covered by `pve.yaml`'s existing wildcard
     `all_zones → infra_seg` policy.
   - None of this is enforced by Terraform (known cross-zone firewall gap,
     `NETWORK_CONTRACT.md`) — it documents what the MikroTik firewall
     should allow. The MikroTik-side rules for these specific cross-node
     paths aren't applied yet; only the `ai_seg`-to-router rules from step
     1's troubleshooting exist so far.
5. **Done.** SDN zone applied via `pvesh` directly against `fe-pve`
   (matching the documented manual procedure — Terraform/Ansible VLAN-zone
   automation remains a known gap, not fixed here): zone `tvai` (type
   vlan, node `pve-framework`), VNet `tvai` (tag 50), subnet
   `192.168.50.0/24`/gateway `192.168.50.1`. Verified present via
   `pvesh get /cluster/sdn/zones`/`vnets`; existing LXCs (9000/9001)
   confirmed unaffected. The `tvai` Linux bridge device doesn't exist yet
   at the OS level — expected, not a bug: Proxmox SDN VNet bridges
   materialize lazily once a container actually attaches (matches the
   existing repo note that "SDN VNet bridges do not appear in
   `/nodes/<node>/network`").
6. **Nothing to apply yet** — no `ai_seg` containers exist. This becomes a
   `stack.yaml` convention (`dns_server: "${lab_gw_ai}"`) for each stack
   added in Phase 3, same as every other zone.

Validation tier: SDN/network change → full teardown cycle on `pve-framework`
still owed before this is promoted past a `work/*` branch (per Decision 2,
there's no separate test copy of this physical box — the teardown cycle
*is* the validation environment here). Not done as part of this pass.

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
5. **Authentik**: per-service, following Decision 8 — default to native
   OIDC (OpenWebUI: yes, well-supported; n8n: unconfirmed, check its
   self-hosted docs when built; SearXNG: no native auth exists, so this
   is Traefik forward-auth or no exposure, not a choice), validated
   end-to-end per app rather than assumed to work. `llama-server` does
   not go through Authentik at all — see the resolved "Open questions"
   entry below (native API-key auth instead).

## Phase 3 — AI/LLM stack, as managed Terraform/Ansible LXCs

Per Decision 5 (revised), one GPU-passthrough exception container **per
distinct GPU workload class** plus one-LXC-per-service for everything
else, all in `ai_seg`:

| Stack | LXC | GPU passthrough? | Notes |
|---|---|---|---|
| `llm-gpu-stack` | 1 (native, replaces 9001) | yes | `llama-server` router mode + standalone embedding process, per `docs/framework/llamacpp-router-mode-deployment.md` |
| `comfyui-stack` | 1, separate from `llm-gpu-stack` (replaces ad hoc 9002) | yes | **Bake-off complete and successful (2026-07-17)** — see `docs/framework/comfyui-image-video-gen-findings.md`. Image + video generation confirmed working (Z-Image Turbo, Wan 2.2 TI2V-5B/I2V-14B), real GPU compute verified via `rocm-smi`. Kept in its own container deliberately — see Decision 5's revision for why, including the host-wide OOM incident that validated the separation. Still ad hoc (systemd-run, no Terraform/Ansible role), same status 9001 was in before Phase 0. |
| `openwebui-stack` | 1 | no | talks to `llm-gpu-stack`'s router endpoint over `ai_seg` |
| `n8n-stack` | 1 | no | |
| `searxng-stack` | 1 | no | |
| `postgres-stack` (or shared with n8n's own) | 1 | no | backing store for OpenWebUI/n8n |
| `redis-stack` | 1 | no | |
| `qdrant-stack` (or Chroma) | 1 | no | vector DB, per project-brief's original candidate list |

**New cross-cutting component, design only, not yet built:**
`docs/framework/dual-workload-gateway-design.md` — a wake-on-connect TCP
gateway running on the Proxmox host itself (not in a container) that
keeps only one of `llm-gpu-stack`/`comfyui-stack` actually *resident* at a
time (via `pct exec ... systemctl stop/start` on the specific service,
not the container), so the host's memory isn't statically halved between
two workloads that are rarely needed simultaneously. Runs with real
host-level privileges triggered by arbitrary incoming connections — needs
the same implementation-review care as any other host-level automation
before it's deployed as an always-on service (the design doc's own
"Blast-radius note" already flags this). Where this fits in the
Terraform/Ansible model is still open — it's host-level, not a
`stack.yaml`-shaped container, so it doesn't obviously fit the existing
per-stack pattern; needs its own placement decision when this is built.

Build order: `llm-gpu-stack` first (proves GPU passthrough survives being
Terraform/Ansible-managed, the highest-risk new capability), then
`comfyui-stack` (wrap the already-proven ad hoc 9002 setup the same way),
then the supporting services, then the dual-workload gateway once both
GPU stacks are Terraform/Ansible-managed, then wire Traefik/Authentik
routes last once there's something real to route to.

New Terraform work required (doesn't exist anywhere in `terraform/lxc/modules`
today, confirmed by grep):

- A GPU-passthrough LXC module/role: `/dev/kfd` + `/dev/dri` mount entries,
  `lxc.cgroup2.devices.allow` lines, and (only if nesting Docker per the
  setup-notes doc) the AppArmor-unconfined + empty `cap.drop` pair. Shared
  by both `llm-gpu-stack` and `comfyui-stack` (same passthrough mechanism,
  two separate container instances) — everything else reuses the existing
  `lxc-docker-host` module pattern unchanged.
- Memory-ceiling sizing must follow the empirical discipline from the
  findings doc §6 — size close to real observed `anon` usage (not raw
  peak, which includes disk-page-cache noise), not generously loose. A
  loose ceiling doesn't make a GPU-heavy container safer on this
  hardware's unified-memory architecture — it escalates OOM failures from
  "this one process dies" to "the kernel starts killing unrelated
  containers," exactly as happened during the ComfyUI bake-off.

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

- ~~Does the llama-server endpoint sit behind Authentik forward-auth/OIDC,
  or is `ai_seg`-internal-only access acceptable?~~ — **resolved
  2026-07-17**: neither exactly. `llama-server` supports native API-key
  auth (`--api-key`/`--api-key-file`, `Authorization: Bearer` header) —
  that's the right mechanism for a machine-to-machine API, not a
  browser-login flow. Decide only whether it also gets a Traefik route
  (with the API key enforced) or stays `ai_seg`-internal-only; either way
  it does not go through Authentik.
- **Authentik integration per AI-stack service — see Decision 8.** Default
  to native OIDC (this platform's actual established pattern — Grafana/
  Portainer/Harbor/Technitium all already use it, not Traefik
  forward-auth), but validate each integration end-to-end before trusting
  it; Technitium's own OIDC integration is known to be clunky with an
  unresolved step-ca-vs-Traefik cert-path issue (operator-flagged,
  explicitly deferred, not part of this plan). Still genuinely open:
  whether n8n's self-hosted/community edition has usable native OIDC at
  all (historically an Enterprise-tier feature in some versions) or needs
  Traefik forward-auth as the fallback — check when n8n is actually built,
  don't assume either way now.
- Embedding-model process placement (CPU vs GPU) — flagged as untested in
  `docs/framework/llamacpp-router-mode-deployment.md`'s own "Not yet done"
  section; decide once `llm-gpu-stack` is live and real latency numbers
  exist.
- Whether `qdrant-stack` or a Chroma-based stack is preferred — no
  retrieval-quality benchmark has been run for either (same doc).
- ~~ComfyUI (`comfyui-stack`) — gated entirely behind a dedicated GPU
  bake-off~~ — **cleared 2026-07-17**, bake-off complete and successful,
  now a committed Phase 3 stack (see the table above and Decision 5's
  revision). Remaining open sub-items from the findings/design docs: which
  image model becomes the real default beyond the initial Z-Image
  Turbo/Wan 2.2 survey (SDXL/Flux/Qwen-Image/HunyuanVideo/LTX-2 not yet
  tried), whether the Vulkan/`stable-diffusion.cpp` path is worth testing
  as a ROCm alternative, and the dual-workload-gateway's open
  implementation decisions (daemon language/runtime, idle-timeout
  auto-stop, cold-start UX, final `llm-gpu-stack` memory ceiling) listed
  in `docs/framework/dual-workload-gateway-design.md`.
