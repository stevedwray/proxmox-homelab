# Current State — Framework Desktop (`fe-pve`)

Facts gathered live via `ssh root@192.168.1.121` on 2026-07-17, plus the
research already recorded under `docs/framework/`. This doc is the
as-found baseline the integration plan works from.

## Identity

| | |
|---|---|
| Hostname | `fe-pve` |
| Management IP | `192.168.1.121/24` (flat LAN, static, gateway `192.168.1.1`) |
| Hardware | Framework Desktop, AMD Ryzen AI Max+ 395 (Strix Halo), 16c/32t |
| GPU | Radeon 8060S (integrated, gfx1151), unified memory — no discrete VRAM pool |
| RAM | 125 GiB total |
| Disk | 1×58GB (`sda`, unused/blank), 1×1.8TB NVMe (`nvme0n1`) |
| OS | Proxmox VE 9.2.2 / Debian 13 (trixie), kernel `7.0.2-6-pve` |

Not yet in DNS, NetBox, or any repo inventory — it's known only by IP today.

## Storage

Single NVMe, LVM-thin only:

```
pve-root   96G   (Debian/Proxmox OS)
pve-data   1.7T  (lvmthin pool "data", thin-provisioned)
```

`/etc/pve/storage.cfg` only defines `local` (dir) and `local-lvm` (lvmthin).
**No ZFS pool exists.** This differs from `pve-test-vm`'s storage profile
set (`terraform/lxc/storage/pve-test-vm.yaml`), which assumes a ZFS backend
(`infrastructure-containers`) for `platform-zfs`/`durable-zfs` profiles. It
matches the legacy `pve-test.yaml` shape instead (`platform-default` →
`local-lvm`). See [decisions.md](./decisions.md) Decision 3.

The 58GB `sda` disk is unused — not part of any pool, no mountpoint.

## Network

As found 2026-07-17 (original recon): `vmbr0` was a plain (non-VLAN-aware)
bridge on `nic0`, static IP on the flat `192.168.1.0/24` LAN, no SDN zones,
no VLAN tags, no trunk.

**Updated 2026-07-17 (same day, Phase 0/1 work — see plan.md for the full
narrative):**

- `vmbr0` is now VLAN-aware (`bridge-vlan-aware yes`, `bridge-vids
  2-4094`), applied via `ansible/00-initial-setup/proxmox-vlan-aware-bridge.yml`.
- `ai_seg` (VLAN 50, `192.168.50.0/24`, gateway `192.168.50.1`) is live and
  verified end-to-end: MikroTik VLAN interface + gateway, bridge-VLAN
  tagging on both physical trunk ports (`ether1` — the port `fe-pve`'s
  traffic actually arrives on — and `ether5`), the physical switch
  carrying VLAN 50 to `fe-pve`'s port, and a router input-firewall rule
  permitting ICMP/DNS to the gateway. `ping 192.168.50.1` from `fe-pve`
  itself: 0% packet loss, confirmed via packet capture, not just a config
  check. See `plan.md` Phase 1 step 1 for the three distinct bugs hit and
  fixed getting here (safe-mode rollback, missing `ether1` tagging,
  missing firewall rule).
- `nic1` exists but is unconfigured (`iface nic1 inet manual`, no bridge
  membership).
- `wlp192s0` (wifi) present but down — not in use.
- `/etc/resolv.conf` points at the MikroTik (`192.168.1.1`), not at
  Technitium — consistent with the box not yet being onboarded into the
  `lab.gibbsgreatly.xyz` internal DNS model. Not yet revisited.
- Not part of any Proxmox cluster; it is a fully standalone node, same as
  `pve` and `pve-test-vm` are to each other.

## Existing guest state (pre-dates this integration effort)

Two LXCs from the `docs/framework/` AI-OS bake-off project, both created by
hand (`pct`/manual config edits), not by Terraform:

| VMID | Name | Status | Purpose |
|---|---|---|---|
| 9000 | `llamacpp-gpu` | stopped | Docker-based GPU passthrough variant |
| 9001 | `llamacpp-gpu-native` | running | Native (no-Docker) HIP build, current live target |

Container 9001's actual config (`/etc/pve/lxc/9001.conf`):

```
arch: amd64
cores: 8
memory: 8192
net0: name=eth0,bridge=vmbr0,hwaddr=...,ip=dhcp,type=veth
ostype: ubuntu
rootfs: local-lvm:vm-9001-disk-0,size=132G
lxc.cgroup2.devices.allow: c 226:* rwm
lxc.cgroup2.devices.allow: c 511:* rwm
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
lxc.mount.entry: /dev/kfd dev/kfd none bind,optional,create=file
```

Privileged, flat-LAN, DHCP-addressed, GPU passthrough applied by hand per
`docs/framework/proxmox-strix-halo-setup-notes.md`. `/data/ai` and
`/srv/ai-stack` exist on the host per that doc's planned layout.

As found 2026-07-17 (original recon): host boot config already carried the
unified-memory GTT fix from that doc, applied by hand —
`GRUB_CMDLINE_LINUX_DEFAULT="quiet ttm.pages_limit=25165824 ttm.page_pool_size=25165824"`
(a flat 96GB ceiling picked by hand). Apt repos were already fixed to
`pve-no-subscription` by hand too.

**Updated 2026-07-17 (same day):** both are now real Ansible, not hand
work:

- `ansible/00-initial-setup/proxmox-initial-setup.yml` ran successfully
  against `fe-pve` (repo fix, subscription-nag removal, `automation@pve` +
  Terraform token — live-verified against the real Proxmox API before
  trusting it).
- `ansible/00-initial-setup/proxmox-gpu-unified-memory-tuning.yml` +
  matching `tasks/` file replaced the hand-picked flat value with one
  computed from this host's actual reported RAM
  (`ansible_memtotal_mb`) minus an operator-set reserved margin
  (32GB, matching the original manual choice) — now
  `ttm.pages_limit=24401920 ttm.page_pool_size=24401920` (95320 MB
  ceiling, slightly more accurate than the old round-number 96GB since
  it's derived from what Linux actually reports as usable RAM rather
  than the nominal 128GB spec). `quiet` preserved. Applied for real;
  `update-grub` run. **A reboot is still required for this to take
  effect** — deliberately withheld since it would interrupt the running
  `9001` LXC; needs its own separate approval.

## What `docs/framework/` establishes (research, not yet productized)

Summarized from the four existing docs there — see each for full detail:

- **`project-brief.md`** — original OS bake-off scope: compare Ubuntu/Proxmox/Gentoo
  for a local LLM stack (`llama.cpp`, OpenWebUI, n8n, SearXNG, Postgres,
  Redis, Qdrant/Chroma, optionally Caddy/Traefik, Tailscale/WireGuard).
  Proxmox won.
- **`proxmox-strix-halo-setup-notes.md`** — the GPU-passthrough-into-LXC
  recipe (kfd/dri passthrough, AppArmor+cap-drop for nested Docker,
  ttm.pages_limit, Vulkan batch-size crash workaround). This is the
  hardware-enablement knowledge the new stack must reuse; none of it is in
  Ansible/Terraform yet.
- **`runtime-matrix-checkpoint-2026-07-16.md`** — llama.cpp/Ollama ×
  Vulkan/ROCm × bare/Docker/Incus all verified working; HIP native ≈ Docker
  perf; Vulkan ~15-20% faster on Proxmox LXC than Incus.
- **`llamacpp-router-mode-deployment.md`** — the deployment pattern this
  plan adopts: one GPU-passthrough container running `llama-server` in
  router mode (`--models-dir`, one endpoint, model picked per-request),
  not one container per model. Includes sizing guidance and an
  as-yet-unbuilt embedding-model plan.
- **`model-quality-and-vuln-bench-2026-07-17.md`** — model selection
  evidence: Qwen2.5-Coder-32B is the recommended default generation model
  (same correctness ceiling as Llama-3.3-70B, ~2.2x faster, half the disk).

None of this research is wired into `terraform/lxc` or `ansible/` yet. The
box is not reproducible from code today — a re-install would require
manually replaying every step in `proxmox-strix-halo-setup-notes.md`.

## Gaps versus the platform contract

Things the rest of the fleet has that this box currently lacks:

1. ~~No Terraform/Ansible bootstrap has been run~~ — **closed 2026-07-17**:
   `ansible/00-initial-setup/proxmox-initial-setup.yml` (repo fix,
   subscription-nag removal, `automation@pve` + Terraform token, live-
   verified against the real API), plus
   `proxmox-gpu-unified-memory-tuning.yml` and
   `proxmox-vlan-aware-bridge.yml` all ran successfully. Only remaining
   sub-item: the GTT tuning needs a reboot to actually take effect (staged,
   not yet applied — see plan.md Phase 0).
2. ~~No SDN VLAN zones — flat LAN only, no trunk to the MikroTik.~~ —
   **closed 2026-07-17**: `vmbr0` is VLAN-aware and `ai_seg` (VLAN 50) is
   live end-to-end, verified with real ping/packet-capture, not just
   config presence. See plan.md Phase 1 step 1 for the three bugs found
   and fixed along the way.
3. ~~No entry in `terraform/lxc/network/*.yaml`, `storage/*.yaml`, or
   `environments/*/`~~ — **mostly closed 2026-07-17**:
   `terraform/lxc/network/pve-framework.yaml` and
   `terraform/lxc/storage/pve-framework.yaml` added, and the Proxmox SDN
   zone/VNet/subnet (`tvai`, VLAN 50) applied live via `pvesh` — confirmed
   present, existing LXCs unaffected. Still missing:
   `terraform/lxc/environments/pve-framework/` (per-stack Terragrunt
   scaffolding, needed before any actual stack deploys in Phase 3).
4. No DNS record anywhere (MikroTik static, Technitium, or otherwise) —
   still open, Phase 2.
5. No NetBox entry (device or IPs) — still open, Phase 2.
6. GPU passthrough (`/dev/kfd`, `/dev/dri`, AppArmor/cap-drop) has no
   Terraform/Ansible module — `terraform/lxc/modules/lxc-docker-host` has
   no GPU-passthrough support today (confirmed by grep — no `kfd`/`hostpci`
   references anywhere in `terraform/lxc/modules` or `main.tf`).
7. Existing guests (9000/9001) are unmanaged, privileged, flat-LAN,
   DHCP-addressed — none of that matches how any other stack in the repo
   is deployed.
8. ~~No secrets/credential path~~ — **closed 2026-07-17**: secrets/env
   handling generalized (`terraform/PRODUCTION_NODES`,
   `scripts/with-secrets-prod-lib.sh`), `with-secrets-prod-framework` is
   live with a real Terraform token in `terraform/secrets.pve-framework.enc.yaml`.
   Still missing from that file: a dedicated `PROXMOX_READONLY_TOKEN_ID/SECRET`
   (this node currently only has the full-privilege Terraform token) and
   `TF_VAR_lxc_password` — needed before Phase 3.
