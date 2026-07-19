# Ubuntu 26 Bare-Metal Migration — Plan

Status: **planned, not started.** No changes have been made against
`pve-framework` as a result of this document. The current Proxmox install
stays in place and fully operational until this plan says otherwise (see
§11 Rollback).

Date: 2026-07-20.

Related documents:

- [`README.md`](./README.md) — workspace entry point
- [`decisions.md`](./decisions.md) — the specific decisions this plan is
  built on, with rationale
- [`docs/framework-integration/lessons-learned.md`](../framework-integration/lessons-learned.md)
  — durable findings from the Proxmox/LXC chapter, carried forward by
  reference rather than repeated here
- [`docs/framework-integration/findings-plan.md`](../framework-integration/findings-plan.md)
  — still the live reference for model/server/client selection
  (LM Studio + Qwen3-Coder-30B-A3B-Instruct + VS Code Copilot BYOK).
  Nothing in that document is superseded by this move; the AI-stack
  findings are platform-independent.
- [`docs/framework/proxmox-strix-halo-setup-notes.md`](../framework/proxmox-strix-halo-setup-notes.md)
  — §6–8 (unified memory, Vulkan/HIP performance, the Vulkan
  long-context reliability bug) are **not** Proxmox-specific and are
  carried forward into this plan directly (§4, §8 below).

## 1. Why this move

Two things converged to trigger this:

1. **Root cause of the recurring "probabilistic Vulkan crash"**: it was
   never a driver race. Every crash observed (6 for 6, cross-referenced
   against the host kernel log) was the Linux OOM-killer terminating
   `llama-server` because `llm-gpu-stack`'s LXC container had a `memory:
   8192` (8GB) cgroup ceiling — a value that had nothing to do with the
   model's actual GPU/GTT memory use and was never sized for a 30B model
   at long context. This is documented as an addendum to
   `findings-plan.md`.
2. **The operator's stated purpose for this hardware**: the Framework
   Desktop was bought to run local AI as effectively as possible — one
   flexible GPU resource used for LLM inference or ComfyUI image/video
   generation, coding or chat, not two permanently and separately
   memory-partitioned services. Two static LXC containers each guessing
   an independent memory split fights that goal directly: it works only
   under a "one heavy workload at a time" discipline anyway (see
   `decisions.md` Decision 5's host-wide-OOM incident), so the LXC
   boundary is not buying real concurrency safety, just an extra layer
   of ceiling-guessing on top of the one boundary that actually matters
   (`ttm.pages_limit`, the host-RAM-vs-GTT kernel split).

Given the operator is not counting migration effort as a cost here, the
conclusion is to remove the redundant layer rather than keep re-tuning
it: bare-metal Ubuntu 26, no Proxmox, no LXC, Ansible-managed.

## 2. Scope

**In scope**: `pve-framework` (Framework Desktop) only. Rebuilt as a
bare-metal Ubuntu 26.04 LTS host, no hypervisor.

**Naming**: the rebuilt host is named `framework.gibbsgreatly.xyz` (the
`pve-` prefix is dropped along with Proxmox itself), at the same IP,
`192.168.1.8`. Wherever this document says `pve-framework`, it means the
*current, still-Proxmox* host being migrated from; `framework.gibbsgreatly.xyz`
is the name the rebuilt host takes on. DNS, Ansible inventory, and any
other reference to the old name get updated to the new one as part of
Phase 7.

**Workloads moving**:
- `llm-gpu-stack` — LLM inference (currently LM Studio + Qwen3-Coder-30B,
  ad hoc; the Ansible role still encodes the earlier, abandoned native
  llama.cpp router-mode approach — see §5).
- `comfyui-stack` — image/video generation (native ROCm/PyTorch build,
  systemd-managed).
- `ai-services-stack` — OpenWebUI + SearXNG (already Docker Compose
  based). Moves with the host, as a Docker container on the new
  bare-metal install — same Compose shape, different host underneath
  (`decisions.md` Decision 8). Not GPU-bound, not a hard dependency of
  this plan's GPU-focused phases.

**Explicitly not affected**: `pve` and `pve-test-vm` remain Proxmox
nodes, unchanged. The shared platform services this box integrates with
(Traefik, Authentik, step-ca, Technitium DNS, Harbor, NetBox, all on
`lab.gibbsgreatly.xyz` per Decision 2 in the old workspace) are unaffected
— `pve-framework`'s services keep integrating with them the same way,
just from a bare-metal host instead of an LXC guest.

## 3. Target platform

- **Ubuntu 26.04 LTS**, bare metal. Matches the OS already used inside
  the current `llm-gpu-stack`/`comfyui-stack` containers (`mesa-vulkan-drivers
  26.0.3-1ubuntu1` confirmed live), so the userspace driver stack is a
  known quantity — only the LXC boundary underneath it is being removed.
  Reasoning for Ubuntu over Debian: already established in
  `proxmox-strix-halo-setup-notes.md` §5 — ROCm/HIP and current-Mesa
  Vulkan are meaningfully easier on Ubuntu than Debian for this
  hardware; no reason to revisit that now.
- **No Proxmox, no LXC, no Terraform** for this node (§6).
- **Ansible-managed** (§5), same repo, adapted roles.
- **Docker**: `ai-services-stack` stays Docker Compose (no change in
  kind, just host). `llm_gpu_stack`/`comfyui_stack` are currently native
  systemd services inside their LXC containers, but **that's not a
  performance-driven default** — `proxmox-strix-halo-setup-notes.md` §7
  directly measured Docker vs. native GPU throughput on this hardware
  and found no meaningful difference either way. **ComfyUI now defaults
  to an existing Docker image instead** (§5), specifically since that
  also helps contain its known fragile, version-sensitive dependency
  stack. `llm_gpu_stack`'s backends (Ollama/llama.cpp/LM Studio) get the
  same "use an existing image unless there's a concrete reason not to"
  evaluation in Phase 3 (§9) — not assumed either way yet, since
  llama.cpp specifically needs a pinned commit and explicit batch/ubatch
  flags (§8) that a generic image would need to accommodate.

**Filesystem layout**, grounded in the current disk (`lsblk` against the
live host: single 1.8TB NVMe, GPT/UEFI, currently `pve-root` 96G ext4 at
6.4GB used, an 8G swap at ~2.3GB actual use, and a 984GB `pve-storage`
LVM volume carrying the Proxmox-era dir-storage split):

- **No ZFS for root** — same reasoning as the old workspace's Decision 3,
  more directly applicable with no LXC layer to buffer it: ZFS's ARC
  cache competes with unified GPU memory for the same physical pool.
  Plain **ext4**.
- **Models are served locally, not from NFS** (see §4 — NFS is backup
  only) — so, unlike the LXC-era split, this host still needs a
  generously-sized local partition/logical volume for the model library
  (currently ~258GB combined LLM+ComfyUI, expected to grow). Simpler
  than the old Proxmox dir-storage scheme (no separate ISO/template/
  backup dir-stores needed — those were Proxmox-specific), but the space
  allocation itself doesn't shrink.
- Recommend keeping **LVM** (thick-provisioned, not thin — the old
  thin-pool existed specifically for Proxmox's per-container rootfs
  sizing, moot now) purely for resize flexibility later, without ZFS's
  memory cost: a `root` LV (ext4, ~100GB is ample given current 6.4GB
  actual use) and a `models` LV (ext4, sized generously against the
  remaining ~1.7TB — most of the disk) mounted wherever
  `llm_gpu_stack`/`comfyui_stack`'s adapted roles expect it.
- **Decided: only the minimum needed to boot is done by hand in the
  installer** — EFI partition + enough of a root LV to get Ubuntu
  installed and Ansible-reachable (Ubuntu's installer's own built-in LVM
  option is fine for this). Everything else — extending the VG, creating
  and formatting/mounting the `models` LV, GRUB `ttm.pages_limit` tuning,
  Mesa/RADV+ROCm install, the NFS-backed model restore, all of Ansible's
  own bootstrap — happens via Ansible post-install, not manually during
  the OS install. Matches this repo's existing discipline (old
  workspace's Decision 7: state lives in Git, not in a box's memory) and
  keeps the manual, error-prone part of the install as small as possible.
- **Modest swap** (8–16GB, matching current ~2.3GB actual usage) as a
  last-resort safety net only, not for real capacity — real capacity is
  `ttm.pages_limit` (§8).
- Standard GPT/EFI System Partition (already UEFI hardware, confirmed
  live).
- **Not yet decided, operator's call**: whether to rename the host at
  install time (already decided — see §2) affects nothing here; whether
  a second NVMe (mentioned as "planned" in the old workspace, not
  actually installed as of this writing) materializes before the rebuild
  changes the exact partition sizes but not this shape.

## 4. Model storage: NFS/NAS is backup only, models are served locally

**Correction from an earlier draft of this plan**: models are **not**
served live from the NFS mount. The NAS/NFS relationship is backup and
restore only — the operator rsyncs the working model set to the NAS as
a durable off-host copy, and a rebuild restores from that copy onto the
new host's local disk. The live-serving copy always lives on local NVMe
(§3's `models` LV), matching how the current Proxmox box already works
(`/storage/models/{llm,comfyui}`, local disk, bind-mounted into the
LXC).

**Current state, verified directly against the live host (2026-07-20)**:
- `/storage/models/llm` (238GB) and `/mnt/nas-models/llm` (238GB) match
  exactly — the LLM model set is already fully backed up.
- `/storage/models/comfyui` (20GB) has **no NAS counterpart** — the NFS
  mount only contains an `llm/` directory. Operator is backing this up
  now (in progress as of this writing) — confirm it lands before wipe.
- The NAS's existing fstab entry
  (`nfs4 rw,_netdev,noauto,x-systemd.automount,x-systemd.idle-timeout=600`)
  is already shaped correctly for a backup-only relationship — mounts on
  demand, not a boot-time dependency. Carry this same mount-option shape
  forward on the new host rather than a boot-critical always-mounted
  path, since backup/restore is occasional, not continuous.

Plan:

1. Before wipe: confirm the ComfyUI models backup (in progress) has
   completed and matches size against source.
2. New host build: local `models` LV/partition (§3), NFS mount present
   but on-demand only (same `noauto`/automount shape as today).
3. Restore: rsync from the NAS back onto the new host's local `models`
   partition as part of Phase 1/3 bring-up, not a live dependency
   thereafter.
4. UID/GID matching: the current LXC is unprivileged with subuid-mapped
   file ownership (see `lessons-learned.md`); bare metal has no such
   mapping, so local file ownership just needs to match whatever local
   user runs the LLM/ComfyUI services directly — simpler than the LXC
   case, not harder.

Open question carried to §9: exact NAS export path/permissions on the
NAS side aren't detailed here — confirm before Phase 1 runs.

## 5. Ansible adaptation

Existing roles, current state, and what changes:

| Role | Current shape | Change needed |
| --- | --- | --- |
| `llm_gpu_stack` | Native (no Docker) HIP build of llama.cpp, router-mode systemd service. **This is the abandoned approach** — `findings-plan.md` established LM Studio + Vulkan + Qwen3-Coder-30B as the actual winning configuration, deployed ad hoc (manually via SSH sessions, never captured in this role). | **Decided: not either/or — all three backends installed and available side by side**, since this is an active development environment, not a single fixed production endpoint (see the expanded note below the table). Remove the `/dev/kfd`/`/dev/dri` passthrough-sanity-check tasks entirely — meaningless on bare metal, the devices are simply always there. |
| `comfyui_stack` | Native (no Docker) ROCm/PyTorch build, systemd-managed, two upstream bug fixes + launch flags per `comfyui-image-video-gen-findings.md`. | **Reversed: use an existing ComfyUI Docker container/image in the first instance**, not a native from-source build — reasoning below the table. Application-level content (the two upstream bug fixes, launch flags, model layout from `comfyui-image-video-gen-findings.md`) still needs to carry forward regardless of packaging — confirm they apply/are already handled inside whichever image is used. |
| `ai_services_stack` (via `app_stack`/`direct_stack` generic roles) | Docker Compose (OpenWebUI + SearXNG), no external DB dependency. | Straightforward port — same Compose shape, different host, no LXC-specific assumptions to strip. |
| `lxc_base`, `lxc_tun_device`, `docker_socket_proxy`, `portainer_agent`/`portainer_api`/`portainer_stack`/`portainer_backup` | LXC-provisioning and Portainer-fleet-management roles. | **Not used at all** for this node going forward — these exist to provision/manage LXC guests via Portainer, which no longer applies once `pve-framework` isn't running LXC containers. Not deleted (still used by `pve`/`pve-test-vm`), just never invoked against this host. |
| `node_exporter`, `rsyslog_forward` | Generic host observability roles. | Carry forward as-is — these already target "a Linux host," not "an LXC guest specifically." |

Inventory: new group/host entry for `framework.gibbsgreatly.xyz`
(`192.168.1.8`, §2) as a bare host — no `vmid`/`pve_host`/
Terraform-derived connection details, just a normal Ansible inventory
host — replacing the three Terraform-state-derived container
inventories.

**Three LLM backends, not one — this is a development box, not a fixed
production endpoint.** Install and run **Ollama, native llama.cpp
(`llama-server`), and LM Studio server** side by side, each its own
systemd unit on its own port, rather than picking a single winner:

- **LM Studio + Qwen3-Coder-30B-A3B-Instruct stays the validated default**
  for the actual VS Code Copilot acceptance path (`findings-plan.md`) —
  the config with real end-to-end evidence behind it.
- **Native llama.cpp** is exactly what the current `llm_gpu_stack` role
  already builds (HIP, router-mode) — kept, not discarded just because
  LM Studio won the earlier comparison. Needs the Vulkan batch/ubatch
  fix (§8) applied explicitly if run under Vulkan rather than HIP.
- **Ollama** is a genuinely new addition, not previously covered by any
  role — needs its own install task and systemd unit.
- "Available side by side" means installed and startable on demand, not
  necessarily all three loaded with large models and serving
  simultaneously — the same unified-memory constraint from §9 Phase 5
  still applies if more than one is actually in heavy concurrent use;
  this just removes the artificial restriction to a single backend for
  a box that's explicitly meant for active development/comparison.

**Correction: Docker vs. native GPU performance on this hardware is
already tested, not an open unknown — an earlier version of this plan
got this wrong.** `proxmox-strix-halo-setup-notes.md` §7 directly
measured it (TinyLlama 1.1B, concurrency 4, 60s stress test, full GPU
utilization verified via `rocm-smi`/sysfs, not log text alone):

| Deployment | HIP tok/s | Vulkan tok/s |
| --- | ---: | ---: |
| Ubuntu bare-metal + Incus + Docker (reference) | 446 | 461 |
| Proxmox LXC + Docker | 454–455 | 536–566 |
| Proxmox LXC, native (no Docker) | 464 | 549 |

With the doc's own explicit conclusion: **"Docker vs. native inside the
LXC makes no measurable difference for either backend. The LXC boundary
is what matters, not whether Docker sits inside it."** GPU device
passthrough into a Docker container costs nothing here, confirmed with
real numbers — it isn't an untested risk to avoid.

**Decided: use an existing ComfyUI Docker image in the first instance,
not a native from-source build.** With the performance question settled,
the remaining case for native was continuity + avoiding an unverified
risk — the risk premise doesn't hold, so use whatever well-maintained
ComfyUI image exists with ROCm/this-hardware support, and only fall back
to a native build if no suitable image actually exists or it can't be
made to work. This also directly addresses ComfyUI's known fragile,
version-sensitive custom-node dependency stack (the reason it got its
own separate container in the original bake-off) — an image with
pinned, known-working dependencies is a better fit for that fragility
than a native venv, not just an equally-good alternative.

Confirm during Phase 4 (§9) whether the image needs the two upstream bug
fixes / `--vram-headroom 6` / `--disable-smart-memory` launch flags from
`comfyui-image-video-gen-findings.md` applied on top, or whether a
current image already handles them.

**Candidate image, checked directly (2026-07-20), not just taken on
faith**: `yanwk/comfyui-boot` (Docker Hub, 1M+ pulls, updated within
days) — three ROCm variants exist: `rocm` (PyTorch's own ROCm 7 build),
`rocm7` (AMD's ROCm 7 build), `rocm6` (stable ROCm 6). Ships
ComfyUI-Manager by default. **Neither the Docker Hub listing nor the
upstream `YanWenKun/ComfyUI-Docker` GitHub repo mentions `gfx1151`
(Strix Halo) anywhere** — confirms the caveat about not blindly using
`latest-rocm`: this needs actual runtime verification on the new host
(does the image work as-is, or does it need
`HSA_OVERRIDE_GFX_VERSION` set, the standard workaround when ROCm's
official GPU list hasn't caught up to a newer architecture — not yet
tested, don't assume either way). `ai-dock/comfyui` is the other option
surfaced, but is more cloud/auth-oriented (provisioning scripts, its own
auth layer) — unnecessary complexity for one local box; `yanwk/comfyui-boot`
is the better starting point for a straightforward local Compose
deployment.

**Open question this reopens**: the same logic (existing Docker image >
native build, now that performance is a non-issue) plausibly applies to
`llm_gpu_stack`'s backends too — Ollama and llama.cpp both have official
Docker images with ROCm/Vulkan support. Not applied here without
checking first: llama.cpp specifically needs the pinned commit and
Vulkan batch/ubatch flags this project already validated (§8), so an
official image would need to support those, not just "any llama.cpp
image." Worth the same "use the image unless there's a concrete reason
not to" evaluation in Phase 3, not assumed either way yet.

## 6. Terraform and credential-model removal

Remove, once the bare-metal build is validated (not before — see §11):

- `terraform/lxc/environments/pve-framework/` (all three stacks' configs
  and `.tfstate`)
- `terraform/lxc/network/pve-framework.yaml`,
  `terraform/lxc/storage/pve-framework.yaml`
- `terraform/secrets.pve-framework.enc.yaml`, `.env.pve-framework`
- `pve-framework` entry in `terraform/PRODUCTION_NODES`

**Secrets and the credential wrapper are repurposed, not deleted along
with Terraform** — decided in `decisions.md` Decision 9, implemented as
part of Phase 7/8 below rather than now (no bare-metal host yet exists
to validate the new command-classifier categories against):

- `terraform/secrets.pve-framework.enc.yaml` keeps its name and SOPS/age
  mechanism, but its content shifts from Proxmox-API identity secrets
  (Terraform token, LXC root password — both genuinely gone) to this
  host's own service secrets (LLM API keys, anything not already covered
  by `terraform/secrets.common.enc.yaml`'s existing Authentik/DNS
  integration secrets).
- `with-secrets-prod-framework` keeps its shape (decrypt secrets,
  classify commands, `TASK_APPROVAL` gate, chat-based preflight
  approval) but its command classifier gets new categories for an
  Ansible-managed host (`ansible-playbook --check`, `systemctl status`,
  `docker compose config`/`logs` as read-only; actual playbook applies,
  `systemctl restart`/`stop`, `docker compose up`/`down`, and
  secret-writing tasks as mutating) instead of Terraform/Proxmox-API
  categories.
- `CLAUDE.md`'s Production Nodes section needs a matching update:
  `pve-framework` keeps the same approval-gated access discipline,
  redefined as a property of the host rather than of having a Proxmox
  API token.

## 7. Platform integration cleanup (Traefik, Authentik, DNS, NetBox, Portainer, monitoring, PKI)

The three AI stacks aren't wired into these platform services as static,
hand-maintained config — this repo uses a data-driven "edge manifest"
system: `terraform/lxc/stacks/{llm-gpu-stack,comfyui-stack,ai-services-stack}/edge.yaml`
is the single source of truth that `terraform/lxc/reconcile-edge.py` (and
the per-target `render-edge-*.py`/`reconcile-authentik-edge.py` scripts)
render into Traefik/DNS config and reconcile against Authentik. Deleting
these three `edge.yaml` files is the actual decommission action for most
of this — but not all of it self-heals equally. Surveyed directly
against the live code (not assumed), 2026-07-20:

- **Traefik — self-heals, no manual action needed.** `render-edge-traefik.py`
  fully re-renders `.generated/traefik/*.yml` from whichever `edge.yaml`
  files currently exist. Delete the three files, re-run `provision.sh`
  (which calls `reconcile_all_edge` unconditionally on every invocation,
  `scripts/provision.sh` `reconcile_all_edge`), and the `openwebui`/
  `comfyui`/`llm-gpu` routers and their `192.168.50.1{0,1,2}` backends
  drop out automatically. Just make sure that re-run actually happens
  post-decommission.
- **DNS (Technitium) — real gap, manual deletion needed regardless of
  whether stacks are retired or recreated.** The publish step
  (`deploy-technitium-stack.yml`, "Publish A records to the parity zone")
  checks for an existing match on **name AND IP together**
  (`selectattr('rData.ipAddress', 'equalto', item.item.ip)`), not name
  alone, then calls `zones/records/add` if no match — there is no
  update/delete path for A records anywhere in that playbook (only the
  SOA/NS records get that treatment). Two scenarios, same conclusion:
  - *Stack retired outright* (`edge.yaml` deleted, not recreated):
    publishing simply stops re-adding the record; the existing one stays
    published forever until manually deleted.
  - *Stack recreated with the same identity at a new backend address*
    (the actual migration case — same `openwebui.lab.gibbsgreatly.xyz`
    etc., new IP once the bare-metal host exists): the name+IP match
    fails against the *new* IP, so `zones/records/add` fires again,
    creating a **second A record** for the same hostname — the old,
    now-dead IP is left alongside the new one, not replaced.
  Either way, the stale/duplicate record needs manual deletion in
  Technitium; recreating the service does not make this self-correct.
  (The parallel CoreDNS zone file is fully re-rendered each run and does
  self-correct, unlike Technitium.)
- **Authentik — updates cleanly in place when a stack is recreated with
  the same identity; only needs manual deletion if a stack is retired
  outright.** Checked the actual reconcile logic: existing Provider/
  Application objects are matched by the `edge-<stack>-<route>` naming
  key and PATCHed in place (`_reconcile_provider_for_intent`/
  `_reconcile_application_for_intent`). Better still, Authentik's config
  is purely host/routing-based — it proxies through Traefik and never
  stores a backend IP at all — so a pure backend-address change with the
  same external hostname doesn't even register as a diff; nothing to do.
  **Only if a stack is retired outright** (`edge.yaml` deleted, not
  recreated) does this become a manual step: `reconcile-authentik-edge.py`
  explicitly logs that "delete actions are reported only and never
  applied by this tool," so `discover-authentik-edge.py` will correctly
  flag the orphaned `edge-ai-services-stack-openwebui` (OIDC) or
  `edge-comfyui-stack-comfyui` (forwardAuth) objects as unmanaged drift,
  but won't remove them — delete manually in that case, or future
  edge-reconcile runs keep reporting failure. `llm-gpu-stack` has zero
  Authentik footprint either way (`auth.mode: none` — `llama-server`'s
  own API-key auth is used instead, per the old workspace's Decision 8).
- **NetBox — nothing to do.** Checked directly: despite an aspirational
  `network/pve-framework.yaml` inventory stanza, `pve-framework` was
  never actually a supported key in the NetBox populate script's
  environment map, and the real live network intent (`network/pve.yaml`,
  since NetBox itself runs on `pve`) has no entry for this node or its
  guests at all. Nothing was ever registered — nothing to remove.
- **Portainer — currently opted out (all three stacks explicitly set
  `portainer_agent: false`, none are in `provision.sh`'s
  `register_portainer_environments` list), but the new host reverses
  this for whichever stacks are actually Docker.** Decided: any Docker
  Compose/container stack on the new host gets registered in the lab's
  Portainer. Today that means `ai-services-stack` only — it's the sole
  Docker-based one of the three (Decision 5: `llm_gpu_stack`/
  `comfyui_stack` stay native systemd, not Docker, so they're outside
  Portainer's scope entirely unless that changes). Phase 7 needs to flip
  `portainer_agent: false` → `true` for `ai-services-stack`, add its
  `portainer_agent` role to the deploy playbook, and add it to
  `register_portainer_environments`'s opt-in list.
- **Monitoring (VictoriaMetrics scrape config) — nothing to do.**
  `deploy-monitoring-stack.yml`'s `scrape_configs` has no entries for
  any of the three stacks' IPs — they ran `node_exporter` locally (via
  the shared `lxc_base` role default) but were never actually centrally
  scraped. A pre-existing gap, not something this decommission needs to
  fix.
- **step-ca/PKI — nothing to do.** No per-host cert enrollment exists;
  all three containers install the generic shared `homelab-root.crt`
  (no `homelab-root.pve-framework.crt` exists), matching `.env.pve-framework`'s
  own stated intent to reuse `pve`'s existing Authentik/step-ca/Harbor/
  NetBox/Traefik rather than standing up node-specific instances.

**Also needs cleanup, adjacent to the above** (mechanical, tracked
alongside Terraform removal in §6): `terraform/PRODUCTION_NODES`'s
`pve-framework` entry; `.env.pve-framework`; `with-secrets-prod-framework`;
`terraform/secrets.pve-framework.enc.yaml`; `terraform/lxc/network/
pve-framework.yaml` and `storage/pve-framework.yaml` (the `ai_seg`
VLAN/storage intent files); and `.env`/`.env.template`'s `LAB_IP_LLM_GPU`/
`LAB_IP_COMFYUI`/`LAB_IP_AI_SERVICES` definitions (`192.168.50.10/.11/.12`,
each commented `ai_seg, pve-framework`) that feed every `edge.yaml`/
`stack.yaml` reference above.

**Decided: drop `ai_seg` VLAN segmentation for these services.** The
`LAB_IP_*` variables above assumed the old scheme — one IP per LXC on
`192.168.50.x`. Considered keeping it (the underlying switch/MikroTik
trunk is switch-side config, not Proxmox-dependent, so it would likely
still work), but decided against: Docker's only way to give a container
its own VLAN IP is a macvlan network, which has a standing gotcha (the
host itself can't reach macvlan containers without an extra shim
interface — real friction for the local diagnostics workflow this whole
project has leaned on) and reintroduces exactly the kind of extra
networking layer this migration is otherwise removing, for isolation
value that's mostly redundant once Traefik is already the sole external
entry point regardless of container IP. `terraform/lxc/network/
pve-framework.yaml` and the `ai_seg` VLAN/SDN zone are removed as part of
§6/Phase 8, not recreated on the new host.

New addressing convention: single IP (`192.168.1.8`), per-service ports
(`edge.yaml` backend URLs become `192.168.1.8:<port>` rather than
per-service IPs). Host-level `ufw`/`nftables` rules if traffic-source
restriction is wanted, in place of VLAN-level isolation.

**Dropping `ai_seg` means real cleanup on the MikroTik and physical
switch, not just deleting repo files** — checked directly, neither is
automatic:
- `ansible/00-initial-setup/mikrotik-ai-seg-vlan50-reconcile.yml`
  provisions the MikroTik side (VLAN 50 interface, gateway IP
  `192.168.50.1`, bridge VLAN tagging on both `ether1`/`ether5`) but is
  purely additive/idempotent-create — confirmed no teardown/remove logic
  exists anywhere in it or the sibling VLAN10 reconcile it mirrors.
  Removing it needs either a small new teardown playbook or manual
  RouterOS commands (remove the VLAN interface, the gateway IP object,
  and the bridge VLAN table's tagged-interface entries for VLAN 50) —
  not automatic, and not yet built either way.
- **The physical switch's own VLAN 50 trunk membership was never
  managed by this repo at all** — the reconcile playbook's own header is
  explicit: "this does NOT configure the separate physical switch...
  that switch's own VLAN 50 membership (trunk + the host's access port)
  is a separate, out-of-band step outside what this repo can reach."
  It was configured manually the first time; reverting it is equally
  manual, on the switch's own management interface, and isn't something
  I have a path to verify or automate.
- `terraform/lxc/network/pve.yaml` (the `pve` node's own network intent,
  not `pve-framework`'s) has a live firewall policy entry —
  `from: edge_seg, to: ai_seg, ports: [80, 443]` — allowing Traefik
  through to the AI-stack web UIs. This becomes a stale, harmless-but-dead
  rule once `ai_seg` is gone; worth removing for hygiene when `pve.yaml`
  is next touched, though it doesn't block anything on its own.

Update the three stacks' `edge.yaml`/`.env` `LAB_IP_*`/port definitions
accordingly as part of Phase 7.

## 8. Carried-forward technical requirements (platform-independent)

These apply regardless of Proxmox vs. bare metal — already learned, not
being re-derived:

- **`ttm.pages_limit`/`ttm.page_pool_size` GRUB tuning** — the deprecated
  `amdgpu.gttsize=` parameter must not be used. Size the GTT ceiling
  generously (it's a ceiling, not a reservation — confirmed `free -h`
  showed the same free RAM immediately after setting a 96GB ceiling) but
  keep real host-side margin, because the failure mode on the host side
  (general OOM-killer, can kill anything) is worse than the failure mode
  on the GPU side (a clean, reported allocation failure). **Current live
  value, confirmed via `/proc/cmdline` on `pve-framework` (2026-07-20)**:
  `ttm.pages_limit=24401920 ttm.page_pool_size=24401920` (~93GB) —
  carry this exact value into the new host's GRUB config rather than
  re-deriving it, unless the operator wants to revisit the split (the
  16/112 split mentioned earlier in this workspace's history remains an
  option, not a default).
- **The Vulkan long-context reliability bug is real and separate from
  the OOM issue.** `proxmox-strix-halo-setup-notes.md` §8 documents a
  genuine kernel-level GPU ring timeout/reset (`ring comp_1.1.0 timeout
  ... device wedged`) at default batch sizes with Llama-3.3-70B at
  ~65-80K tokens — a known upstream issue
  ([ggml-org/llama.cpp#21724](https://github.com/ggml-org/llama.cpp/issues/21724),
  [#20515](https://github.com/ggml-org/llama.cpp/issues/20515)) on this
  exact hardware (Radeon 8060S / RADV STRIX_HALO). Fix: explicit
  `--batch-size 512 --ubatch-size 128` (or lower) rather than trusting
  llama.cpp/LM Studio defaults. **This has not yet been confirmed as set
  in the current LM Studio deployment** — needs checking before or
  during Phase 3 below, independent of the memcg-OOM fix, since it's a
  distinct failure mode that the 6 observed crashes did not happen to
  trigger but that 256K-context real usage could.
- **A container's own memory cgroup limit is unrelated to GPU/GTT
  allocation** — already proven twice now (a 17GB model loaded fine
  inside an 8GB-ceilinged container; an 82GB GPU workload ran inside a
  16GB-ceilinged container with no conflict). This mechanism disappears
  entirely on bare metal (no cgroup ceiling at all unless deliberately
  added), which is the actual point of this migration — not a change in
  GPU memory behavior, just removal of an unnecessary second ceiling.

## 9. Phased execution

**Phase 0 — Prep (in progress)**
- LLM model backup to NAS: **done**, verified 2026-07-20 — `/storage/
  models/llm` (238GB) matches `/mnt/nas-models/llm` (238GB) exactly.
- ComfyUI model backup to NAS (20GB, `/storage/models/comfyui`): **done**,
  verified 2026-07-20 — `/mnt/nas-models/comfyui` now matches the 20GB
  source exactly (`diffusion_models/`, `text_encoders/`, `vae/`).
- **Pulled `/root/download-llm-models.sh` and
  `/root/download-comfyui-models.sh` into the repo**: done, now
  [`docs/framework-ubuntu/model-sources/`](./model-sources/) — see that
  directory's `README.md` for what they cover (not the current
  Qwen3-Coder-30B default, which was obtained a different way).
- Confirm NFS export path/permissions on the NAS side.
- Snapshot the current known-good LM Studio config as the rebuild target:
  Qwen3-Coder-30B-A3B-Instruct Q4_K_M, 256K context, DRY multiplier 0,
  `--parallel 1`, identifier `qwen3-coder-30b-phase6`, plus the
  batch/ubatch settings from §8 once confirmed.
- No action needed on the `LLM_GPU_STACK_API_KEY` exposure flagged
  earlier this session — let it die in the wipe rather than rotate it
  manually; a fresh key gets issued naturally on the new install.

**Phase 1 — Ubuntu 26 base install**

*Manual (installer), kept to the minimum needed to boot and become
Ansible-reachable (§3):*
- Fresh install, bare metal, no Proxmox. Hostname
  `framework.gibbsgreatly.xyz`, same IP `192.168.1.8` (§2).
- EFI partition + a root LV via the installer's own built-in LVM option
  — nothing more by hand.

*Ansible-driven, everything else (§3):*
- Extend the VG and create/format/mount the `models` LV (most of the
  remaining ~1.7TB). No ZFS anywhere, modest swap (8–16GB).
- GRUB `ttm.pages_limit`/`ttm.page_pool_size` tuning, carrying forward
  the exact current value (§8): `ttm.pages_limit=24401920
  ttm.page_pool_size=24401920`.
- Mesa/RADV + ROCm install per `proxmox-strix-halo-setup-notes.md` §5.
- Restore models from NAS onto the local `models` LV (§4) — NFS mounted
  on-demand for this, not a live-serving dependency thereafter.
- Base Ansible bootstrap proper (node_exporter, rsyslog_forward).

**Phase 2 — GPU access validation**
- Prove `/dev/dri`/`/dev/kfd` access and `rocm-smi`/`vulkaninfo` work
  directly on the host before deploying anything real — this is now a
  strictly simpler check than the LXC passthrough case (no cgroup device
  ACLs, no `device_passthrough` root@pam-only API fields to fight).

**Phase 3 — LLM service bring-up (three backends, per §5)**
- Deploy LM Studio, native llama.cpp (`llama-server`), and Ollama, each
  its own systemd unit and port.
- Apply the Vulkan batch/ubatch fix from §8 explicitly wherever Vulkan
  is in use, don't rely on defaults.
- Validate the LM Studio + Qwen3-Coder path specifically against the
  existing harness — `replay_runner.py`, `agent_loop.py`,
  `ensure_model_loaded.sh` are all server-endpoint parameters, not
  Proxmox-coupled, and are reusable unchanged against the new bare-metal
  endpoint.
- Validate with a real VS Code Copilot session, same acceptance bar as
  `findings-plan.md` §12 — this remains the one path with a real
  acceptance gate; native llama.cpp/Ollama are available for development
  use without needing to clear the same bar themselves.

**Phase 4 — ComfyUI bring-up**
- Try `yanwk/comfyui-boot`'s `rocm`/`rocm7`/`rocm6` variants first (§5)
  — fall back to the native from-source build only if none can be made
  to work on this GPU.
- Verify `gfx1151` actually works with the chosen tag — neither the
  image nor its upstream repo documents Strix Halo support explicitly
  (§5); test whether it works as-is or needs `HSA_OVERRIDE_GFX_VERSION`
  set, before assuming it just works.
- Confirm whether the image already handles the two upstream bug fixes
  and `--vram-headroom 6`/`--disable-smart-memory` launch flags from
  `comfyui-image-video-gen-findings.md`, or whether they need applying
  on top.
- Validate against that same findings doc's existing test workflow.

**Phase 5 — GPU workload exclusivity (not a memory-sizing problem)**
- Confirmed with the operator: running LLM coding assistance and ComfyUI
  generation simultaneously is not a real use case here. That reframes
  this phase — it isn't about safely sizing memory for two workloads
  that might both be heavy at once (the old two-LXC design's actual
  failure mode: each container's ceiling might look reasonable
  individually, but the *sum* of both being near-full at once is what
  produced the real host-wide OOM that justified Decision 5 in the old
  workspace). With only one workload ever active, there's no sum to
  guess — the only real ceiling left is `ttm.pages_limit` (§8), which
  was always the correct boundary.
- What's actually needed is **releasing the memory of whichever workload
  you just finished with**, not necessarily stopping its container/unit
  permanently. Both can stay resident as always-on systemd units (cheap
  when idle) — the switch action just needs to actually free the memory
  of the one you're leaving.
- **ComfyUI's unload behavior: revisit and re-test fresh on the new
  host, don't just carry the old finding forward unchanged.**
  `comfyui-image-video-gen-findings.md` §6c documented real incidents on
  the *old* setup: switching models within ComfyUI left residue
  ("Unloaded partially: 858MB freed, 486MB remains loaded..." stacking
  with the next model's requirements), and even with
  `--disable-smart-memory` set, a model "stayed fully resident in the
  container's memory even after its job completed." The validated fix
  at the time was restarting the process, not trusting ComfyUI's
  in-place unload. That was real, but it's also from an earlier ComfyUI
  version on the old LXC setup — worth actually re-testing on the fresh
  Ubuntu install (current ComfyUI version, current drivers) rather than
  assuming the exact same residue behavior still holds. Concretely:
  load a model, unload/switch to a different one, check `anon` in
  `/sys/fs/cgroup/.../memory.stat` (or the equivalent on a non-cgroup-
  bounded native process) before and after. Fall back to "restart
  required" only if re-testing actually reproduces the same residue —
  don't presume it without checking.
- LM Studio is architecturally cleaner — server process and loaded-model
  state are already independent (observed directly: `lms server status`
  reports "running" independent of `lms ps`'s loaded-model list) — so
  `lms unload --all` plausibly frees GTT memory cleanly while leaving the
  lightweight server daemon resident. **Unverified, not assumed**: test
  this empirically once the new host exists (load a model, unload it,
  confirm GTT usage actually drops via `/sys/class/drm/card1/device/
  mem_info_gtt_used`) before relying on it. Fall back to a full restart
  if unload proves incomplete.
- Concrete mechanism, pending both re-tests above: a small two-line
  switch script per direction — `lms unload --all` (or `systemctl
  restart` if that proves necessary) when moving to ComfyUI work, and
  the ComfyUI equivalent (unload call or restart, per whichever the
  re-test confirms) when moving to LLM work — triggered manually or via
  a lightweight hook. Lighter-weight than a full `systemd Conflicts=`
  mutual-exclusion rule or `dual-workload-gateway-design.md`'s full
  gateway design, and grounded in what's actually tested on this
  specific host rather than carried-over assumption.
- Until built, operator discipline (manually run the appropriate restart/
  unload before switching) is the interim state — acceptable short-term
  given actual usage is already sequential, but call this out explicitly
  as unfinished rather than silently relying on it indefinitely.

**Phase 6 — `ai-services-stack` bring-up**
- Docker Compose port, mechanical (§5).

**Phase 7 — Ansible role adaptation and platform integration cutover**
- New bare-host inventory group.
- Strip passthrough-check tasks from `llm_gpu_stack`/`comfyui_stack`.
- Confirm idempotent re-run against the live bare host (same standard
  the rest of this repo holds Ansible changes to).
- Apply the new `edge.yaml` backend addressing scheme decided in §7
  (per-service port on `192.168.1.8`, no `ai_seg` VLAN) — update the
  three stacks' `edge.yaml`/`.env` `LAB_IP_*`/port definitions
  accordingly.
- Register `ai-services-stack` with Portainer per §7's decision
  (`portainer_agent: true`, add the role, add to
  `register_portainer_environments`); `llm_gpu_stack`/`comfyui_stack`
  stay outside Portainer's scope (native systemd, not Docker).
- Re-run `provision.sh`/`reconcile_all_edge` to let Traefik self-heal
  (§7) and Authentik update in place (§7, since the same stack/route
  identities are being reused) — then manually delete the stale
  Technitium A records (§7), which don't self-correct either way.

**Phase 8 — Decommission Proxmox/Terraform for this node**
- Only after Phase 3–7 are validated end-to-end (§11).
- Terraform/credential-model removal per §6.

**Phase 9 — Documentation cleanup**
- Per `decisions.md` and the mapping table in
  `docs/framework-integration/lessons-learned.md`.

## 10. Risks and open questions

- **Vulkan performance on bare Ubuntu vs. Proxmox LXC is not a known
  win.** `proxmox-strix-halo-setup-notes.md` §7's own measurement (small
  model, short prompt) found Vulkan **~15-20% faster inside Proxmox's
  LXC** than bare Ubuntu+Incus, cause unconfirmed — plausibly a host
  kernel build difference (`7.0.2-6-pve` vs `7.0.0-27-generic`), not the
  container boundary itself. Recorded here for honesty: the motivation
  for this migration is memory-model simplicity and reliability, not a
  guaranteed throughput win, and that prior data point should be
  re-measured once the new host exists rather than assumed to resolve
  itself.
- LM Studio's compatibility with (or need for) Docker/GPU-in-container
  access is unverified either way — moot under the native-systemd
  default recommendation in §5, but worth confirming if Docker is chosen
  instead.
- The new command-classifier categories for `with-secrets-prod-framework`
  (§6) haven't been validated against a real host yet — decided in
  principle, implementation deferred to Phase 7/8.
- Exact NFS export configuration lives on the NAS side and isn't
  detailed here.

## 11. Rollback and safety

- The current Proxmox install is not touched until Phases 3–4 pass their
  validation bar on the new bare-metal build. No destructive action
  against the existing `pve-framework` Proxmox install happens before
  then.
- Models are being duplicated to the NAS before any wipe — the rebuild
  is not the only copy at any point.
- Terraform/credential removal (§6, Phase 8) happens last, after the
  bare-metal build has already proven itself — not as part of the
  cutover itself.
