# Ubuntu 26 Bare-Metal Migration — Plan

Status: **in execution.** `framework.gibbsgreatly.xyz` is up and being
built out live — Phases 0–3 are done and verified (see §0 checkpoint
below). The old Proxmox host on this same physical hardware no longer
exists (it was the same box, same IP, already repurposed) — the §11
rollback plan's premise (keep Proxmox running until validated) is
already moot for this hardware specifically; the models were fully
backed up to NAS before that happened, so no data was at risk.

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

## 0. Execution checkpoint — 2026-07-20

### TL;DR

`framework.gibbsgreatly.xyz` (192.168.1.8) is a live, working Ubuntu
26.04 host with three LLM backends and ComfyUI all running
simultaneously, each independently verified. The platform cutover
against `pve` (Traefik/Authentik/Technitium) is also done — real HTTPS
requests through `llm.lab.gibbsgreatly.xyz`/`comfyui.lab.gibbsgreatly.xyz`
now correctly reach the new host. Everything below is done and
re-runnable via committed Ansible, not ad hoc — safe to pick this up
cold from this section alone.

### Done

- **Phase 0 (prep)**: LLM (238GB) and ComfyUI (20GB) models fully backed
  up to NAS, verified byte-for-byte matching. Two previously
  host-local-only model-download scripts pulled into
  `docs/framework-ubuntu/model-sources/`.
- **Phase 1 (base install)**: manual install kept minimal (EFI + root +
  swap as plain partitions, empty `vg0` VG). Everything else via
  `ansible/00-initial-setup/framework-desktop-bootstrap.yml`: `models`
  LV created/mounted at `/storage`, `video`/`render` group membership,
  `ttm.pages_limit`/`page_pool_size` GRUB tuning (recomputed from this
  host's real RAM, not the old host's literal value), Mesa/ROCm
  packages, NFS client + on-demand NAS automount, and the actual model
  restore (rsync from NAS onto local disk — hit and immediately fixed a
  self-inflicted command-syntax mistake mid-transfer, no data lost).
  Rebooted and re-verified: GTT ceiling active, GPU still functional.
- **Phase 2 (GPU validation)**: `vulkaninfo`/`rocm-smi`/`rocminfo` all
  confirmed working as the actual non-root service user — no LXC
  passthrough plumbing needed at all.
- **Phase 3 (three LLM backends, all verified with real requests)**:
  - **LM Studio** (`ansible/00-initial-setup/framework-desktop-lmstudio.yml`) —
    Qwen3-Coder-30B-A3B-Instruct, 256K context, port 8090. Real systemd
    unit built (fixing the old ad-hoc-SSH-session reliability gap) — hit
    and fixed a real bug here too: `Type=forking` doesn't work for a
    self-daemonizing process with no PID file (it was tearing the
    service back down right after startup); fixed to `Type=oneshot` +
    `RemainAfterExit=yes` plus a 2-minute health-check timer.
  - **llama.cpp** (`ansible/00-initial-setup/framework-desktop-llamacpp.yml`) —
    HIP backend, port 8080, router mode. Originally native (reusing
    `llm_gpu_stack`); converted to a custom-built Docker image 2026-07-20
    (see decisions.md Decision 5 supersession) — same pinned commit,
    same `gfx1151` HIP build, same serving flags, verified via a real
    chat completion plus a `rocm-smi` sample showing 79% GPU utilization
    mid-generation.
  - **Ollama** (`ansible/00-initial-setup/framework-desktop-ollama.yml`) —
    ROCm (`gfx1151`), port 11434. Originally native; converted to Docker
    (`ollama/ollama:rocm`, Harbor-proxied) 2026-07-20 — the prior
    "Ollama-in-Docker has a GPU problem" belief didn't hold up (see
    decisions.md), confirmed via logs showing the real GPU device and a
    real generate call at GPU speed (1498 tok/s prompt eval, 287 tok/s
    generation). The old native binary/unit/build dir were removed from
    the host.
- **Ansible inventory**: new `framework` group added to
  `ansible/inventory/{inventory.yml,dev.yml,production.yml}`, confirmed
  working (`ansible framework -m ping` → `pong`).
- **Phase 4 (ComfyUI, via `ansible/00-initial-setup/framework-desktop-comfyui.yml`)**:
  Docker + `yanwk/comfyui-boot:rocm`, pulled through Harbor's `dockerhub`
  proxy-cache project (`harbor.lab.gibbsgreatly.xyz/dockerhub/yanwk/
  comfyui-boot:rocm`) — see `lessons-learned.md` §10 for how this was
  found (a real gap in this session's own first check, corrected once
  challenged) and `apt-cacher-ng` wired in alongside it, same host, same
  session. Real bug hit and fixed:
  `gfx1151` isn't in this image's bundled ROCm hardware table — crash-
  looped until `HSA_OVERRIDE_GFX_VERSION=11.5.1` was set (that's
  `gfx1151`'s own literal version decomposition, not a workaround
  substitute). Confirmed via logs and the live API: correct GPU/VRAM
  detected, restored models (`z_image_turbo_bf16.safetensors`,
  `ae.safetensors`) visible through the right loader nodes. Port 8188.
  Real end-to-end generation confirmed too (Phase 5 testing pulled the
  actual official Z-Image-Turbo workflow and ran it — succeeded, a real
  PNG produced).
- **Phase 5 (GPU workload exclusivity)**: both re-tests done for real,
  neither assumed. `lms unload --all` cleanly frees LM Studio's GTT
  memory (41.7 GiB). ComfyUI's `POST /free` also cleanly frees its GTT
  memory (19.4 GiB, confirmed stable across a repeat call) — **this
  corrects the old LXC-era finding** (partial-unload residue, restart
  required) rather than repeating it; different ComfyUI version/image/
  host. `switch-to-comfyui`/`switch-to-llm` scripts installed to
  `/usr/local/bin` via `ansible/00-initial-setup/framework-desktop-gpu-switch.yml`,
  both confirmed working. No systemd `Conflicts=` or gateway design
  needed.

### Current state of the host, as of this checkpoint

Four services running concurrently, each independently verified,
switchable via two tested scripts:

| Service | Backend | Port | Unit |
| --- | --- | --- | --- |
| LM Studio | Vulkan | 8090 | `lmstudio.service` + `lmstudio-healthcheck.timer` (native — no viable GPU-capable Docker path, see decisions.md); runs as dedicated `lmstudio` user (no sudo), not `steve` — see Decision 6 follow-up, 2026-07-20 |
| llama-router | HIP (Docker) | 8080 | `docker compose` (`/opt/llamacpp-docker`), `restart: unless-stopped` |
| Ollama | ROCm (Docker) | 11434 | `docker compose` (`/opt/ollama-docker`), `restart: unless-stopped` |
| ComfyUI | ROCm (Docker) | 8188 | `docker compose` (`/opt/comfyui-docker`), `restart: unless-stopped` |

`/usr/local/bin/switch-to-comfyui` and `/usr/local/bin/switch-to-llm`
release the other service's GPU memory on demand (§9 Phase 5).

### Not yet done / open items

- **Phase 4 remainder**: confirming whether
  `comfyui-image-video-gen-findings.md`'s two upstream bug fixes /
  `--vram-headroom 6`/`--disable-smart-memory` flags are needed on top
  of this image or already handled (not blocking — real generation
  already confirmed working without them).
- **Phase 6 (`ai-services-stack`) — done, 2026-07-23.** Playbook written
  and running
  (`framework-desktop-openwebui.yml`, commits `0cca6d81`/`58ff5cdb`/
  `3ed64fdb`, 2026-07-21), addressing updated, local verification
  passed at deploy time (playbook's own task confirms OpenWebUI
  discovers models from all three LLM routes, including Ollama's
  `/api/tags`). **Production reconcile against `pve` confirmed live,
  2026-07-23** — a read-only dry-run via `./with-secrets-prod python3
  terraform/lxc/reconcile-edge.py terraform/lxc/stacks/ai-services-stack/
  edge.yaml --authentik-url ... --json` (no `--apply`) showed Traefik
  already matching desired state exactly, the Authentik Application
  object already matching, and DNS already resolving correctly — this
  corrects the earlier "still unconfirmed" note in
  `local-ai-development.md`, which was stale. `https://openwebui.
  lab.gibbsgreatly.xyz/` independently confirmed returning a real `200`
  with OpenWebUI's own page. One dry-run item flagged
  (`edge-ai-services-stack-openwebui-provider`, "differs from desired
  state") is a tooling false positive, not real drift: Authentik's
  OAuth2Provider API never returns `client_secret` on GET (write-only
  field), so `reconcile-authentik-edge.py`'s blind `current != value`
  comparison (line ~698) always flags it regardless of whether the live
  secret is actually correct — operator declined to `--apply` over this
  since everything else already matches live. **Step 7 (human
  verification) done, 2026-07-23** — operator confirmed Authentik SSO
  login works, then ran a real chat with web search enabled
  ("Research CVE recently published affecting Linux") against
  `eval-qwen3-coder-30b-a3b:q6_k` (served via Ollama): response showed
  the `search_web` tool call firing and a "3 Sources" citation strip
  with real external URLs (theregister.com, app.opencve.io,
  ubuntu.com/blog) — confirms SearXNG is actually being queried and its
  results actually cited, not just the model answering from its own
  training data. **Phase 6 is complete.** Old `ai-stack` LXC on `pve`
  (VMID 116) is explicitly out of scope — operator wants to rebuild it
  separately, later.
- **Phase 7 (platform integration cutover) — done and verified
  end-to-end**, including the production piece against `pve` (Traefik +
  Authentik + Technitium), done with explicit per-step approval. Real
  mistake caught along the way: an earlier "probably succeeded" claim
  about the first `proxy-stack` push turned out wrong on direct
  verification (the live Traefik container still had the old backend
  address) — corrected by re-running it properly. Also hit and worked
  around a real, separate apt-cacher-ng issue breaking `node_exporter`
  installs on both `proxy-stack` and `technitium-stack`. Confirmed live:
  `https://llm.lab.gibbsgreatly.xyz/v1/models` → `200`,
  `https://comfyui.lab.gibbsgreatly.xyz/` → `302` (Authentik redirect,
  correct for its forwardAuth route). Only Portainer registration for
  `ai-services-stack` remains, blocked on Phase 6.
- **Phase 8 (decommission old Terraform/credential-model footprint)** —
  blocked on the above; also genuinely can't "roll back" to the old
  Proxmox install on this hardware anymore (see Status line above), so
  this is now cleanup of dead references rather than a real fallback
  decision. Now also includes `terraform/lxc/ansible/roles/llm_gpu_stack`
  itself: unused by this host as of the Docker conversion (2026-07-20)
  but deliberately left in place since the retired `pve-framework` stack
  definition still references it — delete alongside that stack, not before.
- **Crash-mechanism re-verification done, 2026-07-20** (`findings-plan.md`
  "Bare-metal re-verification" section): re-ran the existing tool-calling
  harness against `framework.gibbsgreatly.xyz` — clean 15-rep sweep of the
  full-84-tool fixture came back **0 crashes** (12 pass, 3 fail on the
  same pre-existing, already-documented tool-call-parser quirk, not
  anything new). This empirically supports the memcg-OOM root cause
  actually being fixed by the move to bare metal, not just theoretically.
- **Not yet validated**: full Phase 8 acceptance testing (`findings-plan.md`
  §12, the 12-point list) and a real VS Code Copilot session on the new
  host — still the one remaining gate before this is a fully accepted
  production path, separate from the crash-mechanism check above.
- **Known, accepted limitation**: LM Studio's CLI/headless mode has no
  way to set `--batch-size`/`--ubatch-size` (checked directly against
  the official docs) — the Vulkan long-context ring-timeout fix can't be
  applied to it. Native llama.cpp (HIP, unaffected by this specific bug
  per the original test matrix) remains available as the fallback if
  this ever manifests in practice.
- **Host hardening, 2026-07-20**: `wpa_supplicant.service` stopped/
  disabled/masked (host is wired-only, wifi radio unused/down) — now in
  `framework-desktop-bootstrap.yml`, not just a manual change. `upowerd`
  and the `amd-pstate-epp` CPU power state were checked and found benign
  (no battery, no power-profiles-daemon/TLP consuming upowerd's signals;
  `powersave` governor + `balance_performance` EPP is the standard modern
  AMD tuning, not legacy aggressive throttling — left as-is, no evidence
  it's limiting the real inference throughput already measured). LM
  Studio moved off `steve` (passwordless sudo) onto a dedicated `lmstudio`
  system user with no sudo access — see `decisions.md` Decision 6
  follow-up for the three real migration bugs hit and fixed along the way.
- **Dedicated `containers` LV, 2026-07-20**: root (a plain 96GB
  partition, not LVM) was down to 27G free with `/var/lib/docker` +
  `/var/lib/containerd` alone accounting for ~47G, growing with every
  benchmark image pulled/built. Shrank `models` (1.71TB → 1.41TB, only
  258G actually used, ample margin either side) to free space in `vg0`
  for a new dedicated `containers` LV (300G), bind-mounted onto
  `/var/lib/docker`/`/var/lib/containerd`. Full live migration (stop
  everything touching `/storage` → `e2fsck` → `resize2fs` → `lvreduce`
  → `e2fsck` → remount → `lvcreate`/`mkfs` the new LV →
  `rsync -aHAX` the existing docker/containerd data across → bind mounts
  → bring everything back up) done with zero data loss, verified via
  real inference requests against all three backends plus ComfyUI GPU
  detection afterward. `framework-desktop-bootstrap.yml` updated to
  match (fixed-size `models`, new `containers` LV + bind-mount tasks) and
  confirmed idempotent by re-running it against the already-migrated
  live host (only two harmless directory-mode-normalization changes, no
  disruption). Old `/var/lib/docker.old`/`containerd.old` intentionally
  left in place as a rollback safety net — delete after a confidence
  period, not immediately.
- **First real VS Code Copilot attempt, 2026-07-20 — failed, then fixed**:
  first live Copilot Chat request against `qwen3-coder-30b-phase6` hit
  `net::ERR_INCOMPLETE_CHUNKED_ENCODING`. Root cause: `lmstudio-
  healthcheck.timer` was unconditionally restarting the server on every
  2-minute tick regardless of health, and this one landed mid-request.
  This reopens (and partially corrects) the "duplicate test process, timer
  is innocent" conclusion from the bare-metal re-verification above — see
  `decisions.md` Decision 6's second follow-up and
  `lessons-learned.md` §12's correction. Fixed by checking real API
  reachability before ever touching daemon/server state; verified live
  with a deliberately long request spanning an actual timer tick (tick
  fired, took no action, request completed in full). Also fixed two
  stale URLs in the operator's local `chatLanguageModels.json` (still
  pointed at the old LXC container IP / a long-stopped diagnostic proxy)
  while investigating.
- **Second real VS Code Copilot attempt, 2026-07-20 — a genuine
  multi-file agentic task, diagnosed from the LM Studio server log**:
  after the healthcheck fix above, retried with "generate a Python
  quicksort script plus synthetic test data." Reconstructed the full
  session from the server log (every request logs the complete message
  history, so this needed no special capture proxy): the model built
  `quicksort.py`, then (a follow-up turn) split test data into a separate
  `test_data.txt`, iterated on real data-format bugs a few times — then
  **VS Code's own client-side context-budget management force-triggered
  a lossy conversation summary** ("the conversation has grown too large
  for the context"), because `chatLanguageModels.json` capped this model
  at `maxInputTokens: 57344` + `maxOutputTokens: 8192` = 65536 total even
  though the server has 262144 available. This is the exact risk flagged
  earlier in `findings-plan.md` ("revisit further only if this proves
  insufficient") — now confirmed insufficient for a real multi-file task.
  After the summary, the model's understanding of `test_data.txt`'s real
  content went stale, causing repeated failed `replace_string_in_file`
  attempts, a `create_file`-on-existing-file tool-usage error, an `rm` of
  the data file out of apparent frustration, a brand-new self-contained
  `quicksort_clean.py` created instead of fixing the original, and three
  redundant "I've completed everything" `manage_todo_list` calls before
  it finally noticed the original script was now broken. **Fix applied**:
  raised `maxInputTokens`/`maxOutputTokens` to 180000/24000 (204000
  total, comfortable margin under the server's 262144).
- **Verification, 2026-07-20**: operator retried with a larger real task
  (quicksort in Python, Go, Rust, and Prolog) and reported it went well.
  Confirmed from the server log
  (`2026-07-20.2.log`): 24 requests, conversation history grew smoothly
  and monotonically from 31 to 77 messages with no resets, and zero
  occurrences of the "too large for the context" forced-summary phrase
  anywhere in the log. The client-side token-budget fix holds — no
  compaction-induced confusion spiral on a comparably-sized multi-file
  task. This item is now closed.

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

**Filesystem layout — verified live against the actual fresh install**
(`framework.gibbsgreatly.xyz`, 2026-07-20, superseding the pre-install
assumption below the line):

- Manual partitioning done: `nvme0n1p1` (1G, EFI), `nvme0n1p2` (96G,
  ext4, root — **plain partition, not inside an LVM VG**), `nvme0n1p3`
  (10G, ext4, separate `/boot`), `nvme0n1p4` (10G, swap),
  `nvme0n1p5` (~1.7TB, LVM PV) — already assembled into an empty VG
  (`vg0`, confirmed via `vgs`: 1 PV, 0 LVs, `<1.71t` free). This is
  actually cleaner than originally planned: root has no LVM involvement
  at all, so nothing Ansible does to `vg0`/the `models` LV can ever
  touch root.
- **No ZFS** — plain **ext4** throughout, same reasoning as the old
  workspace's Decision 3 (ZFS's ARC cache competing with unified GPU
  memory), more directly applicable with no LXC layer to buffer it.
- **Ansible's job from here**: create a `models` LV inside the existing
  `vg0` (sized generously against the ~1.7TB free — models are currently
  ~258GB combined LLM+ComfyUI, expected to grow), format ext4, mount
  wherever `llm_gpu_stack`/`comfyui_stack`'s adapted roles expect it.
  GRUB `ttm.pages_limit` tuning, Mesa/RADV+ROCm install, the NFS-backed
  model restore, and Ansible's own bootstrap all still pending (verified
  live: no `ttm.pages_limit` in `/proc/cmdline` yet, no ROCm/Docker/
  Ansible installed yet) — matches Phase 1 (§9) exactly where expected.
- **Two gaps found during the live check, needed before GPU workloads
  can run**: the `steve` user isn't yet in the `video`/`render` groups
  that own `/dev/dri`/`/dev/kfd` — add this as part of Phase 1/2's
  Ansible bootstrap. And a leftover installer USB stick is still
  attached (`/dev/sda`, exFAT+vfat, not part of the actual system) —
  harmless, but unplug it so it's never mistaken for real storage.
- Swap: 10G configured, matches the "modest, last-resort safety net
  only" recommendation — real capacity is `ttm.pages_limit` (§8), not
  swap.
- GPT/UEFI confirmed live.

*Original pre-install planning assumption, for reference*: root and
`models` both as LVs in one shared VG. Superseded by the above —
the manual partitioning ended up cleaner (root fully outside LVM), not
worse; no need to redo anything to match the original assumption.

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

**Inventory: done**, verified live 2026-07-20. New `framework` group
added to `ansible/inventory/{inventory.yml,dev.yml,production.yml}`
(mirroring the existing `debian_template_builder`-style pattern — a
standalone host with no dev/test tiering, present in all three files
since there's only one instance of this box). Host
`framework.gibbsgreatly.xyz`, `ansible_user: steve`, matching
`FRAMEWORK_HOST_IP` env var added to `.env.template`
(`ansible_host_ip_map` pattern's sibling — direct inline lookup, same
shape as `pve.gibbsgreatly.xyz`'s entry in `production.yml`, not the
`ansible_host_ip_map` indirection used for the template-builder
containers). Confirmed working: `ansible framework -i ansible/inventory/
-m ping` → `pong`. No `vmid`/`pve_host`/Terraform-derived connection
details — this is a normal static inventory host, replacing the three
Terraform-state-derived container inventories entirely.

**Nothing to clean up in this inventory system for the old
`pve-framework`** — checked directly: it was never onboarded into
`ansible/inventory/*.yml` at all. It only ever existed via the
gitignored, Terraform-generated per-stack `inventory.yml` files under
`terraform/lxc/environments/pve-framework/`, which aren't touched until
Phase 8 (§9) per the rollback plan (§11) — they'll simply stop being
regenerated once that Terraform environment is torn down.

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

*Manual (installer) — **done**, verified live 2026-07-20:*
- Fresh install, bare metal, no Proxmox. Hostname `framework`
  (FQDN `framework.gibbsgreatly.xyz`), IP `192.168.1.8` (§2). SSH with
  key auth, passwordless sudo for `steve`.
- Partitioning done (§3): EFI + separate `/boot` + root as a plain ext4
  partition (not LVM) + swap, plus an empty `vg0` VG already assembled
  on the remaining ~1.7TB ready for the `models` LV.

*Ansible-driven (§3) — mostly done, verified live 2026-07-20 via
`ansible/00-initial-setup/framework-desktop-bootstrap.yml`, added to the
new `framework` inventory group (§5):*
- **Done**: `models` LV created inside `vg0` (all remaining ~1.7TB),
  formatted ext4, mounted at `/storage`; `/storage/models/{llm,comfyui}`
  created. No ZFS anywhere.
- **Done**: `steve` added to the `video`/`render` groups (the gap found
  during the live check).
- **Done, but not yet active — reboot required**: GRUB
  `ttm.pages_limit`/`ttm.page_pool_size` tuning applied via the existing
  shared task (`tasks/proxmox-gpu-unified-memory-tuning.yml`), computed
  from this host's actual RAM with a 32GB host-side reservation
  (matching the documented policy, not re-derived from scratch) —
  `ttm.pages_limit=23811072 ttm.page_pool_size=23811072` (~93GB out of
  125780MB total). Deliberately recomputed rather than hardcoding the
  old host's literal `24401920` — same policy, this host's own actual
  RAM reading. `/proc/cmdline` confirmed still on the old boot; nothing
  GPU-related should be assumed to reflect this until the host reboots.
- **Done**: Mesa Vulkan drivers + ROCm/HIP packages installed
  (`vulkaninfo`, `rocm-smi` confirmed present).
- **Not yet done**: restore models from NAS onto the local `models` LV
  (§4) — NFS mounted on-demand for this, not a live-serving dependency
  thereafter. Base Ansible bootstrap proper (node_exporter,
  rsyslog_forward) — not yet added to this playbook.
- Housekeeping: leftover installer USB stick — **removed**.

**Rebooted and verified, 2026-07-20**: `ttm.pages_limit`/`page_pool_size`
confirmed active in `/proc/cmdline` and cross-checked against the GPU
driver's own sysfs (`mem_info_gtt_total` ≈ 90.8GB, matching the computed
~93GB ceiling). `vulkaninfo`/`rocm-smi` both still work post-reboot;
`/storage` survived via its fstab entry. Operator also ran `apt update` +
`fwupdmgr update` — the only firmware change applied was a routine UEFI
Secure Boot `dbx` (forbidden-signature database) update from LVFS, not a
BIOS/GPU firmware change; nothing here affects anything above. Kernel is
now `7.0.0-28-generic` (from the `apt update`).

**Phase 1 complete, 2026-07-20.** NFS client (`nfs-common`) and an
on-demand automount fstab entry added for the NAS export (matching the
old host's `noauto`/`x-systemd.automount` shape) — needed a
`systemctl daemon-reload` after the fstab edit for the automount unit to
register, since it was added post-boot rather than present at boot.
Models restored from NAS onto `/storage/models/{llm,comfyui}`: sizes
verified matching exactly on both ends (238GB LLM, 20GB ComfyUI, 0
processes left running, no errors in either rsync log).

One operational note for next time: the two restores were launched as a
single concatenated `rsync src1 dst1 src2 dst2` command — rsync
interpreted that as multiple sources into one destination, and it
started copying an LLM `.gguf` into the ComfyUI directory before being
killed a few seconds in. Only a partial temp file (rsync's own
`.<name>.<random>` staging convention, never a committed file) resulted;
deleted, then re-run as two separate correctly-scoped commands. No data
loss, but worth remembering rsync takes many sources and exactly one
destination, not multiple src/dest pairs concatenated.

**Phase 2 — GPU access validation — complete, 2026-07-20.**
Verified as the actual non-root user (`steve`, no sudo — the case that
actually matters, since real services run as this user, not root):
`vulkaninfo` detects `Radeon 8060S Graphics (RADV STRIX_HALO)` via Mesa
26.0.3; `rocm-smi` sees the device (idle, 40°C); `rocminfo` confirms
`gfx1151` directly. No LXC passthrough plumbing, no
`device_passthrough` root@pam-only fields to fight — plain group
membership (§1's `video`/`render` fix) was sufficient, confirming the
strictly-simpler case the plan predicted.

**Phase 3 — LLM service bring-up (three backends, per §5)**

**LM Studio: done, verified live 2026-07-20**, via
`ansible/00-initial-setup/framework-desktop-lmstudio.yml`:
- Installed via the official `install.sh` (reviewed before running, same
  as the original setup); Vulkan engine auto-selected this time (Phase
  1's Mesa install meant the original "No GPUs detected" issue never
  recurred — `lms runtime survey` correctly reported "Radeon 8060S
  Graphics (RADV STRIX_HALO)" immediately).
- Qwen3-Coder-30B-A3B-Instruct-Q4_K_M imported via symlink from
  `/storage/models/llm/`, loaded at 262144 context, `--parallel 1`,
  identifier `qwen3-coder-30b-phase6` — the known-good snapshot from
  Phase 0.
- **Real systemd unit built, fixing the ad-hoc-session reliability gap**
  (decisions.md Decision 6): `lmstudio.service` runs an idempotent
  supervisor script (daemon up → wait for ready → load model if not
  already → start server if not already). **Real mistake caught and
  fixed during this**: first attempt used `Type=forking`, which failed —
  `llmster` self-daemonizes with no PID file anywhere (confirmed live),
  so systemd couldn't track the forked process and immediately ran
  `ExecStop` right after the setup script exited, tearing the whole
  thing back down. Fixed to `Type=oneshot` + `RemainAfterExit=yes` (run
  the idempotent setup once, mark active, don't try to supervise a
  specific long-running process) — confirmed stable afterward
  (`active (exited)`, model stays loaded, server stays up).
- Since oneshot doesn't detect a later independent crash the way a
  properly-tracked `forking` unit would, added
  `lmstudio-healthcheck.timer` (every 2 minutes, `OnBootSec=2min`/
  `OnUnitActiveSec=2min`) re-running the same idempotent supervisor
  script — actually a better fit than process-restart-on-failure for
  this project's known crash mode (needs a full daemon/model/server
  re-check, not just a process restart), not just a workaround for the
  missing PID file.
- Confirmed end-to-end: real `/v1/chat/completions` request through the
  systemd-managed service returns correctly (`pong`, `finish_reason:
  stop`).
- Vulkan batch/ubatch fix (§8) **confirmed NOT applicable to LM Studio**:
  checked `lms load --help` and the official headless docs directly —
  no `--batch-size`/`--ubatch-size` flags, no documented config-file
  passthrough for them at all. This is now a confirmed constraint, not
  an open question — watch for the ring-timeout symptom during real use
  at long context; native llama.cpp remains available specifically
  because it does support these flags.

**Native llama.cpp: done, verified live 2026-07-20**, via
`ansible/00-initial-setup/framework-desktop-llamacpp.yml`, which reuses
the existing `llm_gpu_stack` role directly rather than reinventing it —
confirmed only ever used by the now-retired `pve-framework` LXC
deployment, so safe to adapt in place: removed the
`device_passthrough`-sanity-check tasks (meaningless with no container
boundary) and repointed `llm_gpu_stack_models_dir` from the old LXC
bind-mount target (`/data/models`) to the real host path
(`/storage/models/llm`). Pinned-commit HIP build compiled cleanly,
`llama-router.service` up on port 8080 (distinct from LM Studio's 8090),
real request against the same Qwen3-Coder model returns correctly
(`pong`, `finish_reason: stop`). Vulkan batch/ubatch fix (§8) doesn't
apply here — this build targets HIP, and
`proxmox-strix-halo-setup-notes.md` §8's own test matrix showed HIP
completing cleanly at default batch sizes in the exact scenario where
Vulkan crashed.

**Ollama: done, verified live 2026-07-20**, via
`ansible/00-initial-setup/framework-desktop-ollama.yml`. Simpler than
LM Studio — Ollama's official installer sets up its own systemd unit
and does its own AMD GPU detection (reviewed directly in the install
script's `configure_systemd()`/`check_gpu()` functions), no custom unit
needed. GPU correctly detected via ROCm (`gfx1151`, 90.8GB total/74.6GB
available) — notably, Ollama drops the Vulkan candidate by default
policy ("dropping integrated GPU" — it excludes iGPUs from the Vulkan
path unless `OLLAMA_IGPU_ENABLE=1`) but accepts the same iGPU via ROCm
without that restriction. Port 11434 (Ollama's default, no conflict).
Smoke-tested with a small pulled model (`llama3.2:1b`), real generation
confirmed working.

**All three backends now up simultaneously**, each on its own port,
confirmed with real inference requests to each: LM Studio (Vulkan,
:8090), native llama.cpp (HIP, :8080), Ollama (ROCm, :11434).

**Still to validate**: the LM Studio + Qwen3-Coder path against the
existing harness (`replay_runner.py`, `agent_loop.py`,
`ensure_model_loaded.sh` — all server-endpoint parameters, reusable
unchanged) and a real VS Code Copilot session, same acceptance bar as
`findings-plan.md` §12 — this remains the one path with a real
acceptance gate; native llama.cpp/Ollama are for development use without
needing to clear the same bar themselves.

**Phase 4 — ComfyUI bring-up — done, verified live 2026-07-20**, via
`ansible/00-initial-setup/framework-desktop-comfyui.yml`:
- Docker + Compose plugin installed (`docker.io`/`docker-compose-v2`
  directly from Ubuntu 26.04's own repos — recent enough, no need for
  Docker's upstream apt repo).
- `yanwk/comfyui-boot:rocm` deployed via docker-compose, exact run
  command sourced directly from the upstream repo's ROCm README and
  adapted to mount the already-populated `/storage/models/comfyui`
  directly as the models volume.
- **`gfx1151` needed the override, confirmed live, not assumed**: first
  attempt (no `HSA_OVERRIDE_GFX_VERSION`) crash-looped —
  `/dev/kfd`/`/dev/dri` were correctly visible with the right
  permissions (ruling out a passthrough problem), but PyTorch's
  ROCm/HIP backend reported "No CUDA GPUs are available" (normal
  ROCm-PyTorch terminology — `torch.cuda` is aliased to HIP, not a sign
  of a CUDA-vs-ROCm image mismatch). Set
  `HSA_OVERRIDE_GFX_VERSION=11.5.1` — `gfx1151`'s own literal version
  decomposition (matching the documented `gfx1100→11.0.0`/
  `gfx1201→12.0.1` pattern, not a same-family substitute) — and the
  container came up stable. Confirmed in logs: `Total VRAM 93012 MB`
  (matching the `ttm.pages_limit` ceiling exactly), `pytorch version:
  2.13.0+rocm7.2`, `Device: cuda:0 AMD Radeon 8060S Graphics : native`.
- Confirmed via the API, not just logs: HTTP 200 on the web root,
  `/system_stats` reports the correct GPU device and VRAM, and both
  restored models (`z_image_turbo_bf16.safetensors`,
  `ae.safetensors`) are visible through the correct loader nodes
  (`UNETLoader`, `VAELoader`) — the volume mount is wired up correctly.
- **Not yet done**: an actual end-to-end image generation run (needs a
  real workflow JSON for this specific model, not just API
  reachability) and confirming whether the two upstream bug fixes /
  `--vram-headroom 6`/`--disable-smart-memory` flags from
  `comfyui-image-video-gen-findings.md` are needed on top of this image
  or already handled — left as a real-usage validation step, the same
  way LM Studio's final validation is a real VS Code Copilot session
  rather than a synthetic check.

**Phase 5 — GPU workload exclusivity — done, verified live 2026-07-20**,
via `ansible/00-initial-setup/framework-desktop-gpu-switch.yml`.

Not a memory-sizing problem, confirmed with the operator: running LLM
coding assistance and ComfyUI generation simultaneously is not a real
use case here, so there's no sum-of-two-ceilings to guess (the old
two-LXC design's actual failure mode) — the only real ceiling is
`ttm.pages_limit` (§8). What's needed is releasing the memory of
whichever workload you just finished with, not stopping its
service/container permanently.

**Both re-tests done empirically on this host, neither assumed from the
old finding** — real workflow submitted through ComfyUI's actual API
(the official Z-Image-Turbo example workflow, extracted from the
embedded PNG metadata at
`comfyanonymous.github.io/ComfyUI_examples/z_image/`), real GTT memory
measured before/after via `/sys/class/drm/card1/device/mem_info_gtt_used`,
not just log-watching:

- **LM Studio (`lms unload --all`): clean.** 65.1 GiB → 23.4 GiB, a
  41.7 GiB drop — matching the model (18.56GB) plus its 256K-context KV
  cache almost exactly. No restart needed.
- **ComfyUI (`POST /free`): also clean — this corrects the old
  finding, not just repeats it.** Ran the actual Z-Image-Turbo workflow
  end-to-end (real generation succeeded, `ComfyUI_00001_.png` produced;
  first-run took ~8 minutes, dominated by model/text-encoder load and
  first-time kernel compilation for `gfx1151`, not the 9 sampler steps
  themselves). Post-generation GTT was 81.1 GiB; `/free` dropped it to
  61.7 GiB (19.4 GiB freed) — and that new baseline is even slightly
  *below* the pre-generation baseline (69.9 GiB from the LM Studio test
  minutes earlier), strongly indicating no residue at all. A second
  `/free` call returned the identical GTT figure (no further reduction,
  no growing residue either) and the container's own memory/CPU dropped
  to an idle baseline. The old `comfyui-image-video-gen-findings.md`
  §6c finding (partial-unload residue, restart required) was real *for
  that setup* — different ComfyUI version, different image, LXC not
  Docker — but doesn't hold here. Recorded as a correction, not a
  contradiction.
- **Mechanism built and tested**: `switch-to-comfyui` (runs `lms unload
  --all`) and `switch-to-llm` (calls ComfyUI's `/free`) installed to
  `/usr/local/bin`, both confirmed working end-to-end. No `systemd
  Conflicts=` rule or `dual-workload-gateway-design.md`'s full gateway
  needed — both services already have a clean native unload path.
- **Scope**: this covers the actual real use-case pair (LM Studio for
  coding vs. ComfyUI for generation) only. Native llama.cpp and Ollama
  are lighter, occasional-use dev backends outside this mechanism —
  Ollama already self-unloads on its own keep-alive TTL; llama-router
  can be managed manually if that's ever actually needed.

**Phase 6 — `ai-services-stack` bring-up**

Not started as of 2026-07-21. **Decided (2026-07-21): the old `ai-stack`
LXC on `pve` (VMID 116 — n8n/SearXNG/Postgres/LiteLLM/Redis/Flowise/
Qdrant/AnythingLLM, no OpenWebUI despite the name) is out of scope here
— it's old enough the operator wants to rebuild it from scratch, as a
separate future task, not extend/reuse.** This phase is specifically
about porting `ai-services-stack` (OpenWebUI + SearXNG only, per
`decisions.md` Decision 9) onto `framework.gibbsgreatly.xyz`, the same
way `llm-gpu-stack`/`comfyui-stack` already landed there.

Live state confirmed 2026-07-21, so this plan is grounded in what
actually exists, not assumption:
- `framework.gibbsgreatly.xyz` currently runs only `comfyui`, `ollama`,
  `llamacpp-router` (`docker ps -a`) — no OpenWebUI/SearXNG anywhere yet.
- `https://openwebui.lab.gibbsgreatly.xyz` returns **502** — DNS
  (`dig` → `192.168.30.10`, Traefik itself, matching every other
  stack's pattern) and a Traefik router already exist from an earlier
  partial setup, but the backend (`http://192.168.50.12:8080`, the old
  `ai_seg` IP) is dead — confirmed via the locally generated
  `terraform/lxc/environments/pve/.generated/traefik/ai-services-stack.yml`,
  which still has the stale `192.168.50.12:8080` target. This is exactly
  the "not done yet" gap Phase 7 already flagged (§9 above:
  "`ai-services-stack/edge.yaml`/`LAB_IP_AI_SERVICES` — deferred, Phase
  6 not done yet").
- Root (`/`) has 31G free of 94G post-LV-migration; `/mnt/container-storage`
  (the dedicated `containers` LV from Phase 3/6 of the earlier LV work)
  has 240G free of 295G — the natural home for OpenWebUI/SearXNG's data
  volumes, consistent with why that LV was created in the first place
  (keep container-adjacent data off the small root partition).
- `LLM_GPU_STACK_API_KEY`, `OPENWEBUI_OIDC_CLIENT_SECRET`,
  `SEARXNG_SECRET_KEY` already exist in `terraform/secrets.common.enc.yaml`
  (confirmed via `./with-secrets env | grep ...`) — no new secrets
  needed.
- **Caveat worth carrying forward, not fixing here**: neither LM Studio
  (`framework-desktop-lmstudio.yml`) nor native llama.cpp
  (`framework-desktop-llamacpp.yml`, see its own `# nosonar` comment —
  "no api key set, `llm_gpu_stack_api_key` empty") actually check an API
  key today, despite `LLM_GPU_STACK_API_KEY` existing in secrets and
  `llm.${LAB_DOMAIN}`'s `edge.yaml` being `auth.mode: none` on the
  assumption the app layer covers it (Decision 8). It doesn't yet — the
  route is currently open to anyone who can reach it, key or no key.
  Pre-existing gap, unrelated to standing up OpenWebUI; flag to the
  operator, don't silently fix as a side effect of this phase.

**Precedent to follow, not the Terraform-era one**: `llm-gpu-stack` and
`comfyui-stack` did **not** reuse their old Terraform-provisioned-LXC
Ansible roles (`terraform/lxc/ansible/roles/{llm_gpu_stack,comfyui_stack}`)
on bare metal — those stay untouched, unused, and get deleted wholesale
in Phase 8. Instead, each got a fresh, self-contained playbook under
`ansible/00-initial-setup/framework-desktop-*.yml`, plain `docker compose`
(no `community.docker` collection, no `lxc_base` role — that role's DNS-
resolver-overwrite and OpenIPMI tasks are actively wrong for a real host
with real DNS), Harbor-proxied images
(`harbor.lab.gibbsgreatly.xyz/dockerhub/<image>`). `framework-desktop-comfyui.yml`
is the clearest template to copy the shape of. `ai-services-stack`
should get the same treatment: a new
`ansible/00-initial-setup/framework-desktop-openwebui.yml`, not a reuse
of `terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml` (which
assumes `lxc_base`/`docker_base`/Portainer-agent registration — all
LXC-provisioning concerns that don't apply here). That old playbook and
`terraform/lxc/stacks/ai-services-stack/stack.yaml` are left alone until
Phase 8, same as the other two stacks' Terraform artifacts.

**One open decision for whoever picks this up** — where OpenWebUI's
`OPENAI_API_BASE_URL` should point, now that it's co-located with LM
Studio instead of being a separate LXC on another VLAN:
- **Local** (`http://127.0.0.1:8090/v1`): skips DNS → Traefik → back-to-
  the-same-box round trip entirely; there's no auth on that route
  anyway (`mode: none`, see caveat above) so nothing is lost by
  bypassing it. Simpler, faster, matches this migration's general
  "remove unnecessary layers" theme.
- **Public** (`https://llm.${LAB_DOMAIN}/v1`, the existing playbook
  default): exercises the full validated path end-to-end on every
  request, and matches what a non-co-located OpenWebUI instance would
  need — but is pure overhead here with no real benefit given the
  current no-auth reality.
Recommendation: local (`127.0.0.1:8090`), but this is a real decision,
not a mechanical port — confirm before writing the compose file rather
than assuming.

Step-by-step:

1. **Write the new playbook**:
   `ansible/00-initial-setup/framework-desktop-openwebui.yml`, `hosts:
   framework`, modeled on `framework-desktop-comfyui.yml`'s shape:
   - Ensure `docker.io`/`docker-compose-v2` present (already true from
     the earlier Docker work on this host — task stays for idempotency/
     rebuild-from-scratch, matches the existing pattern).
   - Create `/opt/openwebui-docker` plus data dirs on the `containers`
     LV: `/mnt/container-storage/openwebui-data`,
     `/mnt/container-storage/searxng-data` (owned by whichever UID the
     containers run as — check the images' documented non-root UID if
     any, or accept root-owned bind mounts as the other three stacks
     already do).
   - Render the compose file — same two services
     (`ghcr.io/open-webui/open-webui:main`,
     `docker.io/searxng/searxng:latest`, pulled straight from upstream
     since neither is currently proxied through Harbor's `dockerhub/`
     mirror — decide whether to add that prefix for consistency with
     `comfyui`'s pattern, or pull directly since these aren't ROCm-
     specific images) as
     `terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml`
     already defines, adjusted for: bare-metal paths (per above), the
     `OPENAI_API_BASE_URL` decision above, and reading
     `OPENWEBUI_OIDC_CLIENT_SECRET`/`SEARXNG_SECRET_KEY`/
     `LLM_GPU_STACK_API_KEY` the same `lookup('env', ...) |
     mandatory(...)` way the existing playbook does (values already
     resolve via `./with-secrets`, nothing new to add to
     `secrets.common.enc.yaml`).
   - Seed `searxng`'s `settings.yml` with `formats: [html, json]`, same
     as the existing playbook (`json` is required for OpenWebUI's RAG
     web-search integration to parse SearXNG's response).
   - `docker compose up -d`, same `changed_when` pattern as the ComfyUI
     playbook.
2. **Syntax-check before running** (CLAUDE.md requirement for any
   Ansible edit, no matter how small): `ansible-playbook -i
   ansible/inventory/ ansible/00-initial-setup/framework-desktop-openwebui.yml
   --syntax-check`.
3. **Run it**: `ansible-playbook -i ansible/inventory/
   ansible/00-initial-setup/framework-desktop-openwebui.yml`.
4. **Verify locally first**, before touching any shared platform state:
   `curl http://127.0.0.1:8080` on the framework host should return
   OpenWebUI's own page (not yet reachable via the public hostname at
   this point — that's step 6). Confirm SearXNG answers internally via
   `docker exec openwebui curl -s http://searxng:8080/search?q=test&format=json`
   (or equivalent) rather than assuming the compose network wiring is
   correct.
5. **Update addressing** — same mechanical change already made for the
   other two stacks in Phase 7 (§9 above): `.env` and `.env.template`,
   `LAB_IP_AI_SERVICES` from `192.168.50.12` → `192.168.1.8`. No change
   needed to `terraform/lxc/stacks/ai-services-stack/edge.yaml` itself —
   it already parameterizes on `${LAB_IP_AI_SERVICES}`.
6. **Production reconcile against `pve`** — this is a real production
   mutation (Traefik + Authentik + Technitium on `pve`, a declared
   production node per `CLAUDE.md`), same category of action as the
   llm-gpu-stack/comfyui-stack cutover already done and documented above
   in this same §9 Phase 7 entry. Follow the identical approval flow
   used there, not a shortcut:
   - **Preflight to the operator**: target = `pve` (Traefik/Authentik/
     DNS containers), mutating, scope = the single
     `ai-services-stack/edge.yaml` manifest only.
   - **Scope the reconcile explicitly** — pass the manifest as a
     positional arg rather than `provision.sh`'s default full
     `--stacks-dir` discovery, exactly like the earlier cutover did,
     because a dry run last time surfaced unrelated pending drift in
     other stacks (harbor, monitoring, portainer, technitium, a shared
     Authentik outpost) that scoping avoided touching:
     ```
     ./with-secrets python3 terraform/lxc/reconcile-edge.py \
       terraform/lxc/stacks/ai-services-stack/edge.yaml \
       --authentik-url "https://authentik-int.${LAB_DOMAIN}:9443" \
       --no-verify-tls --json
     ```
     as a dry run first; add `--apply` only after operator approval and
     with `TASK_APPROVAL` set per `CLAUDE.md`'s flow, using
     `./with-secrets-prod` (target node `pve`) rather than plain
     `./with-secrets` for the actual apply.
   - Applying will (a) reconcile the Authentik OIDC Provider/Application
     for `edge-ai-services-stack-openwebui` (client ID/secret must match
     what the compose file's `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET`
     already read from the same secrets), and (b) re-render Traefik's
     dynamic config — but the *push* to the live `proxy-stack` container
     still needs the explicit `ansible-playbook ... deploy-proxy-stack.yml`
     step `reconcile_all_edge()` does internally (see `scripts/provision.sh`
     around line 173-191) — don't assume the Python script alone updates
     the live container; verify the live Traefik container's own config
     file afterward the same way the earlier cutover caught a real miss
     (§9 Phase 7, "real mistake made and caught by verification" note
     above) rather than trusting a clean exit code.
   - Technitium: no change expected — the ai-services-stack A record
     already exists pointing at `${LAB_IP_PROXY}` (confirmed via `dig`
     above), and that value doesn't change with this migration (still
     Traefik's own IP, not the backend's).
7. **Verify end-to-end**: `https://openwebui.lab.gibbsgreatly.xyz` should
   now return a real response (redirect to Authentik login, matching
   `comfyui`'s `forwardAuth` pattern verification done earlier — except
   `openwebui`'s route is `auth.mode: oidc`, a different mechanism:
   OpenWebUI itself redirects to Authentik via its own OIDC client, not
   a Traefik middleware — so expect OpenWebUI's login page with an
   "Authentik" SSO button, not an immediate redirect). Log in, confirm a
   chat against the local LLM backend actually works, confirm a RAG web
   search actually returns SearXNG results.
8. **Not part of this phase, explicitly deferred to Phase 7's own
   still-open item**: Portainer registration for `ai-services-stack`
   (flip `portainer_agent: false` → `true` in `stack.yaml`, add to
   `register_portainer_environments`'s list in `provision.sh`) — this
   assumes the old Terraform/LXC-Portainer-agent model, which may not
   even be the right mechanism for a bare-metal Docker host; worth
   re-examining rather than mechanically porting once this phase is
   otherwise working.

**Phase 7 — Ansible role adaptation and platform integration cutover**
- New bare-host inventory group — **done** (§5).
- Strip passthrough-check tasks from `llm_gpu_stack` — **done** (§5);
  `comfyui_stack` role is moot, ComfyUI runs via Docker instead (§5
  decision reversal).
- **Idempotent re-run confirmed, 2026-07-20**: all six
  `framework-desktop-*.yml` playbooks re-run back to back — five showed
  `changed=0` immediately; the bootstrap playbook showed one transient
  `changed=1` on its first re-run (plausibly the `user` module's
  `groups`/`append` handling recalculating on that pass) and `changed=0`
  on a second re-run immediately after. Confirmed stable, not a real
  drift.
- **`edge.yaml`/`.env` addressing scheme applied, 2026-07-20** — done for
  the two stacks actually live on the new host:
  - `.env`/`.env.template`: `LAB_IP_LLM_GPU`/`LAB_IP_COMFYUI` updated to
    `192.168.1.8` (confirmed via `with-secrets`'s own sourcing order that
    `.env.pve` doesn't override these, so the base `.env` file is exactly
    what a real `pve` run reads).
  - `terraform/lxc/stacks/llm-gpu-stack/edge.yaml`: backend port changed
    from `8080` to `8090` — **a real decision, not a copied-over
    default**: port 8080 was native llama-router (the abandoned HIP
    approach per `findings-plan.md`); the platform's public
    `llm.${LAB_DOMAIN}` route should point at LM Studio (8090), the
    actual validated production endpoint.
  - `comfyui-stack/edge.yaml` needed no port change (8188 already
    matches the Docker container's exposed port).
  - `ai-services-stack/edge.yaml`/`LAB_IP_AI_SERVICES` — deferred,
    Phase 6 not done yet.
- **Production cutover against `pve` — done and verified end-to-end,
  2026-07-20.** This reached real production systems (Traefik, Authentik,
  Technitium) — the one part of this whole migration outside this
  session's broad `framework.gibbsgreatly.xyz` authorization, done with
  explicit per-step operator approval.

  **Correction to an earlier claim in this doc**: the DNS A record's
  target was never the backend IP — checked `render-edge-technitium.py`
  directly, it always publishes `${LAB_IP_PROXY}` (`192.168.30.10`,
  Traefik itself), regardless of the backend. The "stale record" framed
  earlier as "pointing at the old backend IP" was imprecise; the actual
  effect of deleting it was simply removing the record entirely (nothing
  auto-republished it), not fixing a wrong value.

  1. **Traefik + Authentik reconcile**: scoped `reconcile-edge.py --apply`
     to just the two live manifests (passing them as explicit positional
     args rather than the default full `--stacks-dir` discovery) — a dry
     run first showed several *unrelated* stacks (harbor, monitoring,
     portainer, technitium, a shared Authentik outpost) also had pending
     drift; scoping to just our two files avoided touching any of that.
     Authentik actions were all `noop` for both stacks, confirming it
     never stored the backend address to begin with.
  2. **Pushing the rendered config to the live Traefik container**: hit a
     real, separate infrastructure issue — `node_exporter`'s apt-cache
     update failed identically on both `proxy-stack` and
     `technitium-stack` (Ansible's `apt` module rejected a corrupted/
     GPG-unverifiable `deb.debian.org` `trixie` `InRelease` fetch that
     plain `apt-get` merely warned about and continued past). Clearing
     the LXC's own apt lists didn't fix it — pointing at apt-cacher-ng
     itself serving a bad cached copy, a platform issue outside this
     task's scope. Worked around narrowly via `-e monitoring_enabled=false`
     (the existing guard on `node_exporter`'s role include in
     `lxc_base`), not a permanent change to any shared role.
  3. **Real mistake made and caught by verification, not assumed fixed**:
     the *first* `proxy-stack` run (operator-run) hit this same
     `node_exporter` failure early in the play — I initially told the
     operator it "likely succeeded before the unrelated failure," based
     on task-order guesswork I hadn't actually verified. **That was
     wrong.** Checking the *live* Traefik container's own config file
     directly afterward showed it still had the old `192.168.50.10:8080`
     value — the actual publish step had never run. Corrected by
     re-running `deploy-proxy-stack.yml` directly with the same
     `monitoring_enabled=false` workaround, which completed cleanly
     (`failed=0`) and did reach "Publish rendered Traefik files."
  4. **Technitium**: same `node_exporter` workaround, then
     `provision.sh --stack technitium-stack` (later replicated directly
     for the `monitoring_enabled=false` override) republished all 22
     records from current `EdgeManifest`s — 3 were actually missing
     (added), the rest already matched and were correctly skipped.
  5. **Verified end-to-end, not just "task succeeded"**: live Traefik
     container's own config file checked directly (shows
     `http://192.168.1.8:8090`); `dig` confirms both DNS names resolve to
     `192.168.30.10`; real HTTPS requests through the full DNS → Traefik
     → backend chain both succeed —
     `https://llm.lab.gibbsgreatly.xyz/v1/models` → `200`,
     `https://comfyui.lab.gibbsgreatly.xyz/` → `302` (correctly redirects
     to Authentik login, that route's `forwardAuth` middleware intercepts
     before ever reaching the backend, so a raw connectivity test doesn't
     apply the same way there).

  **Still open**: Portainer registration for `ai-services-stack` (blocked
  on Phase 6 existing first). The `node_exporter`/apt-cacher-ng issue
  itself is unresolved — real, recurring, but a separate platform problem
  from this migration; worth a follow-up outside this doc.

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
