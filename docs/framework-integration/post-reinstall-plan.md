# Post-Reinstall Bootstrap Plan — `pve-framework`

Status: **`llm-gpu-stack`, `comfyui-stack`, and `ai-services-stack`
(OpenWebUI + SearXNG) are all live.** Chat/tool-calling bugs found and
triaged (one fixed, two left open — see below). Three more chat-oriented
models being staged. See `docs/workflow/session-handoff-2026-07-18.md`
for the earlier continuity checkpoint (superseded by this status block
for anything past "models staged"), `decisions.md` Decision 9 for the
ancillary-services split rationale, and Decisions 10–11 for the bugs and
gotcha below.

**Models staged (2026-07-18):**
- `llm-gpu-stack`: Qwen2.5-Coder-32B-Instruct-Q4_K_M (19.85GB, default),
  DeepSeek-R1-Distill-Qwen-32B-Q4_K_M (19.85GB, vuln-review specialist),
  Llama-3.3-70B-Instruct-Q4_K_M (42.5GB, available but not recommended
  over Qwen) — all in `/storage/models/llm/` on `pve-framework`,
  confirmed working via a real inference request through Qwen.
  `llm-gpu-stack`'s memory ceiling corrected from an initial wrong
  50G estimate down to 8G (real anon usage measured at ~1.6GB even under
  active GPU-offloaded inference — GPU-offloaded weights/KV-cache live in
  host-level GTT memory via `ttm.pages_limit`, not this container's own
  cgroup; don't conflate the two on this hardware).
- `comfyui-stack`: Z-Image Turbo (diffusion model + `qwen_3_4b` text
  encoder + VAE, ~20.6GB) staged in `/storage/models/comfyui/`. Not yet
  reload-tested against the running service.
- All three LLM `.gguf` files also backed up to an NFS NAS share
  (`nas.gibbsgreatly.xyz:/volume1/Models`, mounted at `/mnt/nas-models`
  on `pve-framework`) so a future rebuild doesn't need to re-download
  ~78GB from HuggingFace.

**`ai-services-stack` live (2026-07-18):** CT 50012, OpenWebUI + SearXNG,
`openwebui.lab.gibbsgreatly.xyz` verified working end-to-end — native
OIDC via Authentik (provider/application created through
`reconcile-authentik-edge.py`, required registering the new route in
`discover-authentik-edge.py`'s `OIDC_ROUTE_CLIENT_IDS` allowlist first —
a deliberate safety gate against auto-provisioning unregistered routes),
OpenWebUI's login page confirmed showing the Authentik option via its own
`/api/config` endpoint. Backend pre-configured with `llm-gpu-stack`'s API
+ key server-side. SearXNG never host-published, internal compose network
only.

**Bugs found and triaged (2026-07-18), see Decision 10:**
- **Fixed**: `llm-gpu-stack` (any model) could produce garbage/repeated-
  token output under concurrent requests — root-caused to `llama-server`'s
  default 4-slot concurrent decode corrupting shared GPU state on this
  HIP/ROCm build; OpenWebUI's real per-message pattern (main chat +
  background title-gen + tag-gen) reliably triggered it. Fixed by forcing
  `--parallel 1` (single-slot serialized decode). Verified via the same
  concurrent-request reproduction, now returns correct output.
- **Open, likely OpenWebUI-side, not our infra**: a background
  title-generation task's JSON response sometimes renders into the main
  chat bubble in OpenWebUI (Qwen). Could not reproduce via direct API
  testing in any combination (streaming/non-streaming, 2–3 concurrent
  requests, both `/completion` and `/v1/chat/completions`) — points at
  OpenWebUI's own task/websocket routing, not `llama-router`. OpenWebUI is
  pinned to `main`, which is confirmed identical to `latest` (this project
  doesn't ship a separately-tagged stable release on `ghcr.io`), so there's
  no simple "switch to stable" fix available either. Deprioritized — not
  the operator's actual use case (VSCode/MCP, not OpenWebUI chat).
- **Open, confirmed Qwen-specific**: Qwen2.5-Coder-32B doesn't populate
  `tool_calls` correctly when a real `tools` schema is sent — dumps raw,
  sometimes malformed JSON into `content` instead. Reproduced directly.
  Adding `--jinja` to the launch flags didn't fix it. Llama-3.3-70B-Instruct
  handles the identical request correctly. **Workaround: use
  Llama-3.3-70B-Instruct for agentic/tool-calling work (VSCode/MCP), not
  Qwen**, until Qwen's chat-template/tool-parser mismatch is actually
  root-caused.

**Chat-oriented models staged and confirmed live (2026-07-18):** three
DavidAU "uncensored"/creative-writing GGUFs requested for OpenWebUI chat
use (not coding) — `L3.1-MOE-6X8B-Dark-Reasoning-Dantes-Peak-HORROR-R1-
Uncensored-36B` (Q4_K_M, 20.48GB), `Command-R-01-Ultra-NEO-DARK-HORROR-
V1-V2-35B` (Q4_K_S, 18.98GB — no Q4_K_M available), `Llama-3.2-8X4B-MOE-V2-
Dark-Champion-Instruct-uncensored-abliterated-21B` (Q4_K_M, 11.97GB).
`llm-gpu-stack` now serves all six models total (the original three plus
these); confirmed via `GET /v1/models` showing all six IDs, and via
OpenWebUI's model picker after a page refresh. `/storage` has ample
headroom (1TB total, ~103GB used before these, still well under half full).

Two gotchas hit and fixed getting these staged:
- **`host_bind_mounts` ownership** — see Decision 11: unprivileged
  containers need the host-side bind-mount directory owned by the
  container's default subuid-mapped UID (100000), not real root; found via
  `Permission denied` writing into `/data/models` from inside
  `llm-gpu-stack` despite it looking like a normal `root:root 0755`
  directory from inside the container. Fixed with `chown -R
  100000:100000 /storage/models/llm` on the host.
- **Download tooling/memory** — plain anonymous `wget` slowed
  dramatically partway through a ~20GB download; switching to an
  authenticated HF token fixed the resolver-level behavior but not the
  actual throughput (root cause turned out to be normal network-path
  characteristics — the CDN resolved to AWS ap-southeast-1/Singapore
  edges, not a HuggingFace rate limit). Installing HF's accelerated `hf`
  CLI (`HF_XET_HIGH_PERFORMANCE=1`) directly inside `llm-gpu-stack` got
  real speed (114MB/s) but got OOM-killed at ~10GB — Xet's
  high-performance parallel-chunk transfer buffers substantially more
  client-side memory than a simple stream, and blew past the container's
  deliberately tight 8GB memory ceiling (sized for the inference workload,
  not a download client). Landed on downloading via `hf`/Xet on a separate
  personal workstation (ample RAM, no container ceiling to fight) and
  `rsync -avP --partial` transferring the finished file straight into
  `/storage/models/llm/` on the `pve-framework` host — sidesteps both the
  memory ceiling and avoids installing extra tooling on production infra
  entirely. Worth reusing this pattern for any future large model
  downloads rather than fighting the container's memory budget again.

Also confirmed (by design, not a bug): `llm-gpu-stack`'s router does
**not** auto-discover new files dropped into its models directory — it
needs an explicit `GET /v1/models?reload=1` (or a service restart) before
new models show up, including in OpenWebUI's picker (which just reflects
whatever the router currently reports).

`llm_gpu_stack_ctx_size` (8192, shared globally across whatever model the
router has loaded) is worth revisiting for these three — long-context
chat/roleplay use is exactly where 8K may feel cramped; not yet changed,
revisit if it becomes a problem in practice.

Next: `n8n-stack` (n8n + Postgres + Redis) and `rag-stack` (Qdrant/Chroma,
deferred until OpenWebUI's embedded default isn't enough) — see
Decision 9. NetBox registration explicitly deferred by the operator.
Also still open: Terraform state-drift `ignore_changes` fix for
`device_passthrough`/`host_bind_mounts` (identified, not applied —
operator said "stop" mid-edit, only resume if asked again), and an actual
end-to-end ComfyUI generation test (models confirmed staged/visible via
API, never actually run a generation).
This is the concrete, ordered runbook for what happens once the Framework
Desktop is wiped and reinstalled from scratch under its real name
(`pve-framework`, not the prior exploration-only `fe-pve`), per Decision 7.
Everything that was on the box before this (containers 9000/9001/9002, all
hand-built GPU passthrough and ComfyUI setup) is gone — the value already
extracted from it was the *knowledge*, captured in `docs/framework/`, not
the running state itself.

Read `plan.md` first for the phase-by-phase architecture reasoning; this
doc is the sequenced "what to actually run, in what order" companion,
informed by everything proven since `plan.md` was first written.

## What survives the reinstall vs. what doesn't

**Survives** (external to the Proxmox host itself):
- The MikroTik `ai_seg` (VLAN 50) configuration — VLAN interface, gateway
  IP, bridge-VLAN tagging on both `ether1`/`ether5`, and the router
  firewall rules. Confirmed live and working; nothing to redo here.
- The physical switch's VLAN 50 trunk/access-port config for this box's
  port.
- Every Ansible playbook/task file already committed to this repo
  (`ansible/00-initial-setup/proxmox-initial-setup.yml`,
  `proxmox-gpu-unified-memory-tuning.yml`, `proxmox-vlan-aware-bridge.yml`,
  `mikrotik-ai-seg-vlan50-reconcile.yml`) and the Terraform
  network/storage declarations (`terraform/lxc/network/pve-framework.yaml`,
  `terraform/lxc/storage/pve-framework.yaml`) — all reusable as-is.
- Everything in `docs/framework/` and `docs/framework-integration/` — the
  actual point of writing it down.

**Does not survive** (Proxmox-host-local state, wiped by a reinstall):
- The Proxmox SDN zone/VNet/subnet objects (`tvai`) — these are
  Proxmox-local config, not MikroTik-side; must be recreated via `pvesh`
  (same commands as before — see `plan.md` Phase 1 step 5).
- The `automation@pve` user and its Terraform API token — a fresh Proxmox
  install has no users at all yet. The current
  `terraform/secrets.pve-framework.enc.yaml` token **will stop working**
  the moment the host is reinstalled; expect to regenerate it the same way
  it was captured the first time (Phase 0 step 2's process, repeated).
- `ttm.pages_limit`/subscription-nag/repo fixes, `vmbr0` VLAN-awareness —
  all re-applied fresh by the same Ansible playbooks, not carried over as
  files (a fresh install has none of this).
- Containers 9000/9001/9002 and everything inside them — including
  downloaded model weights (ComfyUI's checkpoints total well over 50GB
  inside container 9002's own disk; `/data/ai` on the host itself is only
  ~2GB, so the bulk of what would need re-fetching is container-internal,
  not host-level). Nothing here is irreplaceable — every model is a public
  download, and `docs/framework/comfyui-image-video-gen-findings.md`
  already has the exact source/URL pattern for each — but re-downloading
  is real bandwidth/time. Worth deciding before wiping whether to stage
  copies of the specific checkpoints already proven working (Z-Image
  Turbo, Wan 2.2 TI2V-5B, Wan 2.2 I2V-14B + Lightning LoRA) somewhere that
  survives — the unused 58GB `sda` disk, or off-box — purely as a
  convenience, not a requirement.

## What needs to be *built* before this plan can actually be run

Everything in Phase 0/1 (host bootstrap, network onboarding) is already
real, tested Ansible/Terraform — ready to reuse today. Phase 3's AI stack
started the same way containers 9001/9002 did (hand-built, never wrapped)
but is now wrapped in real Terraform + Ansible, written and validated
against the current (disposable) box's `tofu validate`/`terragrunt plan`
and `ansible-lint`, though **not yet applied** — no container has actually
been created from this code:

1. ~~A shared GPU-passthrough Ansible role/task~~ — turned out not to be
   needed as an Ansible construct. Device passthrough itself
   (`/dev/kfd`+`/dev/dri`) moved to Terraform's native `device_passthrough`
   block (`bpg/proxmox` provider, PVE 8.1+) via `terraform/lxc/modules/lxc-docker-host`'s
   new `docker_enabled`/`device_passthrough` variables — no hand-edited
   `lxc.cgroup2.devices.allow` lines, no reading the KFD major number
   live, Proxmox handles it internally. Each stack has its own
   OS-package/toolchain Ansible role instead (items 2/3 below), since HIP
   vs. PyTorch/ROCm are different enough dependency stacks that a shared
   role added indirection without saving real duplication. This resolves
   the second "open question" that used to be listed below. Docker-nesting
   / AppArmor-unconfined / `cap.drop` turned out to be moot — neither
   stack runs Docker (`docker_enabled: false` on both), so none of that
   applies.
2. **`llm-gpu-stack`** — done: `terraform/lxc/stacks/llm-gpu-stack/stack.yaml`,
   Terragrunt env at `terraform/lxc/environments/pve-framework/llm-gpu-stack/`,
   Ansible role `terraform/lxc/ansible/roles/llm_gpu_stack/` +
   `terraform/lxc/ansible/playbooks/deploy-llm-gpu-stack.yml`. Implements
   llama.cpp's native HIP build
   (`docs/framework/proxmox-strix-halo-setup-notes.md`) and the
   router-mode systemd unit exactly as documented in
   `docs/framework/llamacpp-router-mode-deployment.md`, including
   `--api-key-file` support (key kept off the command line and out of the
   world-readable unit file, via a 0600 secret — not wired to a real key
   yet, no Traefik route exists).
3. **`comfyui-stack`** — done:
   `terraform/lxc/stacks/comfyui-stack/stack.yaml`, Terragrunt env at
   `terraform/lxc/environments/pve-framework/comfyui-stack/`, Ansible role
   `terraform/lxc/ansible/roles/comfyui_stack/` +
   `terraform/lxc/ansible/playbooks/deploy-comfyui-stack.yml`. Implements
   the full recipe from the findings doc:
   - ROCm 7.1.1 from Ubuntu's apt repos (`rocm-dev`, `rocm-smi`).
   - PyTorch/torchvision/torchaudio from AMD's `gfx1151`-specific pip
     index (findings doc §1) — not PyPI.
   - `comfyanonymous/ComfyUI` git clone, a generated `requirements-rocm.txt`
     with `torch`/`torchvision`/`torchaudio` lines stripped (kept separate
     from the tracked `requirements.txt` so `git update` never conflicts
     with a locally-edited file).
   - The `torchvision::nms` op-registration patch (findings doc §2.1) —
     implemented as an idempotent `ansible.builtin.replace` derived from
     the bug writeup, not a diff against the live source. **Not yet
     confirmed to actually match** the real installed
     `torchvision==0.26.0+rocm7.13.0` file — a no-match is silently
     harmless (module no-ops rather than failing), so the first real run
     needs to be checked for whether this task actually reports
     `changed`, not just whether the playbook completes.
   - `torchaudio` installed even though unused, to satisfy `comfy/sd.py`'s
     unconditional import (§2.2).
   - Launch flags `--vram-headroom 6 --disable-smart-memory`.
   - Memory ceiling: 40960MB, the empirically-validated figure for the
     640×640/49-frame Wan 2.2 14B I2V workload (findings doc §7). Still
     just copied forward from the ad hoc bake-off, not re-validated
     against this real container — re-check once the real target workload
     is known, per [[reference_unified_memory_oom_sizing]].
4. Both stacks have their `terraform/lxc/environments/pve-framework/<stack>/`
   Terragrunt scaffolding (per-environment layout, matching
   `docs/environment-isolation/current-state.md`). `terragrunt plan`
   against the live `pve-framework` node confirms 5 clean resource
   additions each, correct IP/vmid/memory/`device_passthrough` — verified
   read-only, nothing applied.

The dual-workload gateway (`docs/framework/dual-workload-gateway-design.md`)
still depends on both stacks existing as real systemd services first —
build it after, not as part of the initial reinstall pass.

## What's still open

Both open items below from the pre-apply version of this section are
now **closed (2026-07-18)** — see step 4 in the sequence below for the
full trail: `terragrunt apply` succeeded for both stacks (after removing
`device_passthrough`/bind-mount handling from Terraform's managed
resource, per the root@pam restriction found), and
`unprivileged: true` + out-of-band `device_passthrough` is confirmed
working — `/dev/kfd`+`/dev/dri/*` visible and functional inside both
containers, no need for the documented `unprivileged: false` fallback.

Genuinely still open:
- Phase 2 (DNS/NetBox/Authentik onboarding) for both new containers.
- The dual-workload gateway (depends on both stacks existing as real
  systemd services, which is now true).
- No model weights staged yet in `/storage/models/{llm,comfyui}` — both
  services are up but have nothing to actually serve/generate with yet.
- Final memory ceiling validation for `llm-gpu-stack` once a real target
  model/context-size is chosen (currently a conservative placeholder).

## Sequence, once the reinstall actually happens

1. **OS install — done (2026-07-18).** Debian 13 + Proxmox VE 9
   (`pve-manager/9.2.2`), hostname set to `pve-framework` from the start,
   at a new IP (192.168.1.8 — the box's old exploration-phase address,
   192.168.1.121, does not carry over). DNS (`pve-framework.gibbsgreatly.xyz`)
   already points at the new IP; SSH key access confirmed. Initial storage
   layout matched what `terraform/lxc/storage/pve-framework.yaml` already
   assumed (single 1.8TB NVMe, `local-lvm` LVM-thin + `local` dir) — since
   restructured live, see the new step 1a below. **`pveam list` is empty**
   — no container templates exist yet (neither the custom Docker-enhanced
   Debian template nor the plain Ubuntu 26.04 template survive a
   reinstall); staging both against the new `storage-template` volume is a
   real prerequisite for step 4 below, not yet its own numbered step here.
1a. **Storage restructure — done (2026-07-18).** Operator raised a real
   concern: `local` (Proxmox's default dir storage for ISOs/templates/
   backups) lived on `/var/lib/vz`, which is on the root filesystem
   (`pve-root`) — meaning growable content would compete with the OS for
   space. Fixed live and safely, since `pve-data` was confirmed at 0.00%
   usage (nothing staged yet — this window closes the moment anything
   real is stored). Used `pve`'s own live `storage.cfg` as the naming
   precedent. Result: `pve-root`/`pve-swap` untouched; new plain ext4 LV
   `storage` (1000G) mounted `/storage`, registered as `storage-iso`/
   `storage-template`/`storage-backup` (Proxmox dir storage) plus plain
   bind-mount directories `/storage/models/{llm,comfyui}`/`/storage/artifacts`;
   `local-lvm`'s thin pool recreated at the same name (`data`, 700G, was
   1.71TB) so its `storage.cfg` entry needed no changes. Full rationale
   in `decisions.md` Decision 3. `llm-gpu-stack`/`comfyui-stack`
   `stack.yaml`s and `terraform/lxc/storage/pve-framework.yaml` updated to
   match — `rootfs_size` shrunk (140G/250G → 30G each, models no longer
   live in-container), `host_bind_mounts` added, `template_profiles` now
   point at `storage-template` instead of `local`. `tofu validate` clean;
   not yet re-verified with a live `terragrunt plan` against the restructured
   host.
1b. **Container templates staged — done (2026-07-18).** Plain Ubuntu
   26.04 (`pveam download storage-template ...`) and the custom
   Docker-enhanced Debian template (`build-debian-13-template.yml`) both
   landed on `storage-template`. The Debian build surfaced and fixed a
   real bug in that playbook along the way: unprivileged-container
   `vzdump` failing with `tar: ...tmp: Cannot open: Permission denied`
   against a freshly-created directory — root-caused to the playbook's
   own "Ensure dump directory exists" task hardcoding `mode: "0700"`
   (`lxc-usernsexec`'s uid-remapped `tar` process can't write into a
   0700 root-owned directory it doesn't own). Confirmed via a direct
   `vzdump --storage <id>` test succeeding while `--dumpdir` against any
   fresh 0700 directory failed identically, isolating the cause to that
   one task rather than anything specific to the new `/storage` volume.
   Fixed to `0755`, matching Proxmox's own `/var/lib/vz/dump`. Never
   surfaced on `pve`/`pve-test-vm` before now — likely because their
   target directories had already been touched by something else prior
   to that task's assertion; `pve-framework`'s fresh install made this
   the first true exercise of that exact path. Full trail in
   `decisions.md` Decision 3's addendum.
2. **Host bootstrap — step 1 of 3 done (2026-07-18).**
   `proxmox-initial-setup.yml` run against `192.168.1.8` (33 ok / 11
   changed / 0 failed) — repo switch, subscription-nag removal, Terraform
   automation user + token created. Token captured the same careful way as
   before: redirected to a local log file (never printed to chat), id/
   secret extracted and shape-checked (length + regex, not the value
   itself), written straight into a fresh
   `terraform/secrets.pve-framework.enc.yaml` via `sops set`, live-verified
   against the real API (`GET /api2/json/version` → HTTP 200), then the
   plaintext log shredded. `./with-secrets-prod-framework terragrunt plan`
   confirmed working end-to-end against the fresh host immediately after;
   a `terragrunt apply` attempt through the same wrapper (deliberately, to
   confirm the mutating-command gate survived the token rotation) was
   blocked before even reaching the wrapper's own `TASK_APPROVAL` check —
   two independent layers both refuse it, as intended.
   Rest of Phase 0 — done (2026-07-18): `proxmox-gpu-unified-memory-tuning.yml`
   (`pmx_gpu_gtt_reserved_host_mb=32768`, matching the value already
   validated; dry-run via `--check --diff` first, matching the discipline
   that caught a real bug last time) → `proxmox-vlan-aware-bridge.yml` →
   reboot. Verified live post-reboot, not just trusted from the Ansible
   run completing: `/proc/cmdline` and `/sys/module/ttm/parameters/*`
   both show `ttm.pages_limit=24401920`/`ttm.page_pool_size=24401920`
   (32GB reserved out of 128GB total), and `ip -d link show vmbr0` shows
   `vlan_filtering 1`. Phase 0 is now fully complete.
3. **Network onboarding — done (2026-07-18).** Recreated via `pvesh`
   (`proxmox-sdn-setup.yml` is not a fit — it's built for `pve-test`'s
   4-zone shape and asserts on that; used the manual procedure from
   `NETWORK_CONTRACT.md` instead, matching what was actually done the
   first time): zone `tvai` (vlan, `vmbr0`, `pve-framework`), VNet `tvai`
   (tag 50, alias "pve-framework AI application segment"), subnet
   `192.168.50.0/24`/gateway `192.168.50.1`. All three verified via
   `pvesh get` to match the intent file exactly. One behavior difference
   from the original bring-up worth noting: the `tvai` Linux bridge came
   up immediately at the OS level with zero containers attached, where the
   original exploration-phase notes say it stayed absent until first
   attachment — a PVE version/behavior difference, not a problem.
   Re-verified reachability rather than assuming the physical wiring
   still works just because it did before: temporary IP on `tvai`
   (192.168.50.2/24, added and removed in the same step), `ping
   192.168.50.1` + concurrent `tcpdump` — 0% packet loss, real ICMP
   request/reply pairs captured on the wire. Unlike the original bring-up
   (three separate bugs found across MikroTik safe-mode rollback, wrong
   trunk port, and a missing firewall accept rule), this rebuild's
   physical path worked cleanly on the first attempt — the MikroTik/
   switch config genuinely survived the reinstall unchanged, as predicted.
4. **`llm-gpu-stack`, `comfyui-stack` — done (2026-07-18).** Both
   templates staged, `terragrunt apply` for both environments, then the
   `deploy-llm-gpu-stack`/`deploy-comfyui-stack` playbooks. Was not the
   non-event the earlier text hoped for — genuinely the first real test
   of this code, and it found three real bugs:
   - **`device_passthrough` and bind-type `mount_point` blocks are both
     hardcoded by Proxmox to `root@pam`-only authentication**, rejecting
     the `automation@pve` API token's create call with a 403 regardless
     of its Administrator RBAC role. Same restriction class the module
     already worked around for the `keyctl` feature flag
     (`configure-keyctl.yml`). Fixed the same way: removed both from the
     Terraform-managed resource, added
     `ansible/playbooks/configure-device-passthrough.yml` to apply them
     out-of-band via direct root SSH `pct set` (true `root@pam`, not
     subject to the restriction).
   - `comfyui_stack`'s `git clone` into `/opt/ComfyUI` failed because the
     bind-mounted `models`/`output` subdirectories had already created it
     as a non-empty directory (mount points materialize before the role
     runs). Fixed by cloning to a scratch path and merging via `rsync`.
   - That same fix had its own bug: an unanchored `--exclude=models`
     rsync pattern also matched ComfyUI's own internal
     `comfy/ldm/models/` package deep in the source tree, silently
     dropping it and breaking the service at runtime
     (`ModuleNotFoundError: No module named 'comfy.ldm.models'`) until
     anchored to `--exclude=/models`.

   **Result, fully verified**: CT 50010 (`llama-router`, port 8080) and
   CT 50011 (`comfyui`, port 8188) both confirmed serving real HTTP
   traffic, both with `/dev/kfd`+`/dev/dri/*` visible and functional
   inside an `unprivileged: true` container — this was flagged as
   genuinely untested since the original bake-off always used privileged
   containers; now proven, not assumed. The speculative `torchvision::nms`
   patch (previously unconfirmed whether it would match the real
   installed package) matched and applied correctly on the real run.
5. **Platform onboarding** (Phase 2, now under the real name): Technitium
   host record for `pve-framework` (not `fe-pve`), NetBox device
   registration, Authentik OIDC wiring per Decision 8 for whichever web
   UI stacks exist by this point.
6. **Dual-workload gateway**: build and deploy once both GPU stacks are
   real systemd services with static IPs (a stated prerequisite in its own
   design doc).
7. **Remaining Phase 3 stacks**: OpenWebUI, n8n, SearXNG, Postgres, Redis,
   Qdrant/Chroma — per `plan.md`'s existing table.

## This reinstall *is* the validation gate Phase 4 has been waiting for

`plan.md` Phase 4 and Decision 2 both note that `pve-framework` has no
separate test copy to rehearse against — "the teardown cycle is the
validation environment here." A clean reinstall driven entirely by the
Ansible/Terraform built above, reaching the same working state that's
been hand-validated piece by piece, **is** that teardown-cycle proof —
provided it's actually done through the codified automation rather than
turning into a second round of manual fixes. If it requires manual
intervention beyond what's already written down, that's a signal the
corresponding role/playbook is still incomplete, not a reason to patch it
by hand and move on.

## Open questions to resolve before or during the reinstall

- Whether to stage the already-proven model checkpoints somewhere durable
  first (bandwidth/time convenience only, not a hard requirement).
- Final memory ceilings for both GPU stacks once the dual-workload gateway
  exists and they're no longer implicitly time-sharing the host by manual
  discipline alone.
