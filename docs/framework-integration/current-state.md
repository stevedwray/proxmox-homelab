# Current State — `pve-framework`

Facts gathered live via `ssh root@192.168.1.8` on 2026-07-18, immediately
after the operator wiped and reinstalled the Framework Desktop under its
real name, per Decision 7 and
[post-reinstall-plan.md](./post-reinstall-plan.md). This doc is the
as-found baseline the rest of this workspace works from — it describes
**this fresh install**, not the prior exploration-phase `fe-pve` box (see
`plan.md`, now a historical record of that earlier phase, for what came
before).

## Identity

| | |
|---|---|
| Hostname | `pve-framework` (set correctly from install time — no post-hoc rename needed) |
| Management IP | `192.168.1.8/24` (flat LAN, static, gateway `192.168.1.1`) — a **new** address; the old exploration-phase box was `192.168.1.121` |
| DNS | `pve-framework.gibbsgreatly.xyz` already resolves to `192.168.1.8` |
| Hardware | Framework Desktop, AMD Ryzen AI Max+ 395 (Strix Halo), 16c/32t |
| GPU | Radeon 8060S (integrated, gfx1151), unified memory — no discrete VRAM pool |
| RAM | 128088 MiB (~125 GiB) total, as reported by `ansible_memtotal_mb` |
| Disk | 1×58GB (`sda`, unused/blank), 1×1.8TB NVMe (`nvme0n1`) |
| OS | Proxmox VE 9.2.2 / Debian 13 (trixie), kernel `7.0.14-5-pve` |

## Storage

Single NVMe, restructured live 2026-07-18 (see
`docs/framework-integration/decisions.md` Decision 3) so growable data
never shares space with the Proxmox root filesystem — done while
`pve-data` was at 0.00% usage (fresh install, nothing staged yet), so it
was a clean, safe restructure rather than a data migration:

```
pve-root     96G    (Debian/Proxmox OS, unchanged, nothing else lives here)
pve-swap     8G     (unchanged)
pve-storage  1000G  (plain ext4 LV, mounted /storage)
pve-data     700G   (lvmthin pool, same name as before -> local-lvm needed
                      no storage.cfg changes, just resized)
```

`/etc/pve/storage.cfg`: `local` (dir, `/var/lib/vz` on `pve-root` —
still registered but no longer used for anything new) and `local-lvm`
(lvmthin, container rootfs/volumes) as before, plus three new `dir`
storages on `/storage` — `storage-iso`, `storage-template`,
`storage-backup` — named to match `pve`'s own live convention. Plain
(non-Proxmox-storage) directories `/storage/models/{llm,comfyui}` and
`/storage/artifacts` exist for bind-mounting into containers (models/
artifacts aren't Proxmox storage content types). No ZFS pool. The 58GB
`sda` disk is unused — not part of any pool, no mountpoint.

**`pveam list local` is still empty — no container templates exist.**
The Ubuntu 26.04/custom Debian templates need re-staging against the
*new* `storage-template` volume (not `local`, which
`terraform/lxc/storage/pve-framework.yaml`'s `template_profiles` no
longer point at). Real, open prerequisite before any stack can deploy —
see "Gaps" below.

## Network

Phase 0/1 both done and live-verified against this fresh install
(2026-07-18):

- `vmbr0` is VLAN-aware (`bridge-vlan-aware yes`, `bridge-vids 2-4094`),
  confirmed via `vlan_filtering 1` on the live interface, not just the
  Ansible run completing.
- `ai_seg` (VLAN 50, `192.168.50.0/24`, gateway `192.168.50.1`) is live
  and verified end-to-end: SDN zone/VNet/subnet (`tvai`) recreated via
  `pvesh`, and reachability re-confirmed with a temporary IP + `ping` +
  concurrent `tcpdump` — 0% packet loss, real ICMP request/reply pairs
  captured on the wire. Unlike the original exploration-phase bring-up
  (three separate bugs: MikroTik safe-mode rollback, wrong trunk port,
  missing firewall rule), this rebuild's physical path worked cleanly on
  the first attempt — the MikroTik/switch config genuinely survived the
  reinstall unchanged, as `post-reinstall-plan.md` predicted.
- One behavior difference from the original bring-up worth noting: the
  `tvai` Linux bridge came up immediately at the OS level with zero
  containers attached, where the original notes say it stayed absent
  until first attachment — a PVE version/behavior difference, not a
  problem.
- `ttm.pages_limit=24401920 ttm.page_pool_size=24401920` (32GB reserved
  for the host out of 128GB total, ~95320MB GTT ceiling) confirmed live
  in `/proc/cmdline` and `/sys/module/ttm/parameters/*` post-reboot — not
  just staged in `/etc/default/grub`.
- Not part of any Proxmox cluster; fully standalone, same as `pve` and
  `pve-test-vm` are to each other.
- Not yet revisited: DNS resolver config (`/etc/resolv.conf` presumably
  still points at the MikroTik, not Technitium) — Phase 2 territory.

## Existing guest state

**None.** This is a fresh install — no containers exist yet. The prior
exploration-phase guests (9000/9001/9002, the hand-built GPU-passthrough
LXCs from the `docs/framework/` bake-offs) did not survive the reinstall
and were never expected to; their value was the *knowledge* captured in
`docs/framework/comfyui-image-video-gen-findings.md`,
`docs/framework/llamacpp-router-mode-deployment.md`, and
`docs/framework/proxmox-strix-halo-setup-notes.md`, now being wrapped
into real Terraform/Ansible (`llm-gpu-stack`, `comfyui-stack` —
written and `plan`-validated, not yet applied against this host).

## What `docs/framework/` establishes (research, still the source of truth)

Summarized from the docs there — see each for full detail:

- **`project-brief.md`** — original OS bake-off scope: compare
  Ubuntu/Proxmox/Gentoo for a local LLM stack (`llama.cpp`, OpenWebUI,
  n8n, SearXNG, Postgres, Redis, Qdrant/Chroma, optionally
  Caddy/Traefik, Tailscale/WireGuard). Proxmox won.
- **`proxmox-strix-halo-setup-notes.md`** — the GPU-passthrough-into-LXC
  recipe (kfd/dri passthrough, `ttm.pages_limit`, Vulkan batch-size crash
  workaround). Now codified via Terraform's native `device_passthrough`
  mechanism (see Decision in `terraform/lxc/modules/lxc-docker-host`)
  rather than hand-edited `lxc.cgroup2.devices.allow` lines.
- **`runtime-matrix-checkpoint-2026-07-16.md`** — llama.cpp/Ollama ×
  Vulkan/ROCm × bare/Docker/Incus all verified working; HIP native ≈
  Docker perf; Vulkan ~15-20% faster on Proxmox LXC than Incus.
- **`llamacpp-router-mode-deployment.md`** — the deployment pattern
  `llm_gpu_stack`'s Ansible role implements: one GPU-passthrough
  container running `llama-server` in router mode.
- **`model-quality-and-vuln-bench-2026-07-17.md`** — model selection
  evidence: Qwen2.5-Coder-32B is the recommended default generation
  model.
- **`comfyui-image-video-gen-findings.md`** — the completed ComfyUI
  bake-off: ROCm/PyTorch setup, two upstream bugs and their fixes, the
  host-wide OOM incident and its resolution. `comfyui_stack`'s Ansible
  role implements this recipe.

## Gaps versus the platform contract

1. **No container templates staged** — `pveam list` is empty everywhere.
   Blocks any `terragrunt apply` for `llm-gpu-stack`/`comfyui-stack`
   until the custom Debian Docker template
   (`ansible/00-initial-setup/build-debian-13-template.yml`) and the
   plain Ubuntu 26.04 template (`pveam download`) are staged — now
   against the new `storage-template` volume (`/storage/template`), not
   `local`/`/var/lib/vz`, per the storage restructure above. Next step.
2. **`llm-gpu-stack`/`comfyui-stack` untested against a real host.**
   Terraform (`stack.yaml` + Terragrunt scaffolding) and Ansible (roles +
   playbooks) are written and validated (`tofu validate`, `terragrunt
   plan` clean, `ansible-lint` production profile clean) but never
   `apply`'d — no container has actually been created, the HIP/ROCm
   builds have never run for real, and whether `unprivileged: true` +
   `device_passthrough` actually grants GPU access on this hardware is
   still unverified (the original bake-off used the legacy privileged
   passthrough pattern, never this mechanism).
3. **No DNS record anywhere** (MikroTik static, Technitium, or
   otherwise) beyond the bare `pve-framework.gibbsgreatly.xyz` A record
   already pointing at 192.168.1.8 — Phase 2.
4. **No NetBox entry** (device or IPs) — Phase 2. Note
   `terraform/lxc/network/pve-framework.yaml`'s `inventory.proxmox_nodes`
   entry now has the correct `host_ip: "192.168.1.8"` for when this
   happens.
5. **Secrets**: the Terraform automation token is live and
   live-verified (`terraform/secrets.pve-framework.enc.yaml`). Still
   missing: a dedicated `PROXMOX_READONLY_TOKEN_ID/SECRET` (this node
   only has the full-privilege token so far) and `TF_VAR_lxc_password` —
   needed before Phase 3 container creation.
6. **Authentik/Traefik/Harbor/step-ca integration** for the AI stack —
   not started. `pve-framework` has no local instances of these and
   reuses `pve`'s per Decision 2/8; the actual wiring (OIDC clients,
   Traefik routes) hasn't been done for any AI-stack service yet.
