# Post-Reinstall Bootstrap Plan — `pve-framework`

Status: **in progress — reinstall, Phase 0 host bootstrap, and Phase 1
network onboarding all done. Next: Phase 3 prerequisites (container
templates, then `llm-gpu-stack`/`comfyui-stack`).**
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

## What's still open before this is genuinely reinstall-ready

- **No real `terragrunt apply` yet.** Everything above is `plan`-clean but
  untested end to end — the actual container creation, the HIP/ROCm build
  running for real, the GPU actually initializing under
  `unprivileged: true` + `device_passthrough`, and the `torchvision::nms`
  patch actually matching are all still unverified. This is the next step
  against the current disposable box, under the normal production
  approval flow (`pve-framework` is a listed production node — see
  CLAUDE.md), before it can be trusted as reinstall automation rather than
  untested code.
- Whether `unprivileged: true` + `device_passthrough` actually grants
  working GPU access on this hardware at all — the original manual
  bring-up of both 9001 and 9002 used the legacy privileged
  `lxc.cgroup2.devices.allow` pattern, never this mechanism. Documented
  fallback if it doesn't work: `unprivileged: false`.

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
4. **`llm-gpu-stack`, `comfyui-stack`** (not started): re-stage both
   container templates first (the gap found in step 1 — custom Debian
   Docker template via `build-debian-13-template.yml`, plain Ubuntu 26.04
   via `pveam download`), then `terragrunt apply` both environments,
   then the `deploy-llm-gpu-stack`/`deploy-comfyui-stack` playbooks
   (`llm_gpu_stack`/`comfyui_stack` Ansible roles). This should be close to
   a non-event if the pre-reinstall build-and-test work above was actually
   finished (including a real, not just planned, apply) before the
   reinstall happened — it wasn't (see "What's still open" above), so
   treat this as the first real test of that code, not a rerun of
   something already proven.
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
