# CyberSecEval Implementation — Current State

Entrypoint for this workspace, per `docs/workflow/documentation-workspaces.md`.
`plan/cyberseceval-implementation-plan.md` is the design (Meta's benchmark,
architecture, phases); this file tracks what has actually been built and
verified against it, and what's next. Update this file, not the plan doc's
prose, as work lands — the plan's §1a "Open decisions" list is still the
source of truth for unresolved judgment calls.

## Status (2026-09-18): cyber range built and verified; open decisions resolved; cse-controller LXC live on pve-tiny; Phase 1 acceptance requirement met

The plan splits into two independent tracks (§1a): `pve-test` (cyber range)
and `pve-tiny` (compute/orchestration). Only the first has started.

## Done and verified live

### `pve-test` — now the dedicated cyber-range host

- Cleaned up entirely: dead USB-backed ZFS pools and the 2 containers on
  them removed, then the 6 further vestigial pre-`pve-test-vm` containers
  also removed once flagged. Rebootstrapped: repo/Terraform-user baseline
  reaffirmed, SDN zones validated, Debian 13 LXC template rebuilt (base
  image bumped 13.1-2→13.6-1, the old version had fallen out of Proxmox's
  catalog). Own per-node SOPS secrets file created
  (`terraform/secrets.pve-test.enc.yaml`) after `pve-test`'s Terraform
  token was found dead.
- `pentest_seg` (VLAN 70) extended from `pve`/`pve-test-vm` to `pve-test`.
  No new VLAN needed — MikroTik trunk tagging for VLAN 70 on `pve-test`'s
  port was already prepped; only the Proxmox SDN zone/vnet definition was
  missing. Existing containment (default-deny + narrow allow) applies by
  subnet, so it covers new tenants automatically.
- **`cse-kali`** (LXC, `192.168.70.210`, VMID `70010`): live. Stock
  `kalilinux/kali-rolling` (pinned by digest — no versioned tags exist),
  pentest toolset (nmap, sqlmap, nikto, hydra, etc.) installed at deploy
  time. No sshd in the container — reached via SSH to the LXC host, then
  `docker exec`. Verified: `docker ps`, `nmap --version` both confirmed
  directly, not just trusted from the Ansible run.
- **`metasploitable3-win2k8`** (VM, `192.168.70.211`, VMID `70011`): live.
  First VM-provisioning Terraform code in this repo
  (`terraform/vm/metasploitable3-win2k8/`, `bpg/proxmox`'s
  `proxmox_virtual_environment_vm` — every other stack here is an LXC).
  Disk imported from the pre-built `rapid7/metasploitable3-win2k8` Vagrant
  box. Two real boot bugs found and fixed: `scsi0` (virtio-scsi) put
  Windows into a Startup Repair loop with no virtio drivers in this old
  box — moved to `ide0`; still looped until `ostype = w2k8` was set, which
  makes Proxmox auto-pin a Windows-compatible machine type. `pentest_seg`
  has no DHCP, so its static IP was set by hand via the console
  (`netsh`) — a genuinely operator-only step, not Terraform-managed.
  Verified: boots to the real Windows login screen (confirmed via
  screenshot, not assumed), reachable and scannable from `cse-kali`
  (FTP/SSH/HTTP/SMB/MySQL/RDP all open, matching Metasploitable3's known
  service set). `tofu plan` shows zero drift after reconciling state.

### `pve-tiny`

- 2TB NVMe provisioned as `nvme-lvm` (LVM-thin, deliberately not ZFS —
  ARC would pressure this node's 32GB RAM), wired into
  `terraform/lxc/storage/pve-tiny.yaml` (`durable-nvme` extra-mount
  profile).
- **`cse-controller`** (LXC, `192.168.40.70`, VMID `40070`): live.
  Joins the existing `infra_seg` zone (VLAN 40) — the operator's explicit
  choice over a new dedicated zone or `mgmt_seg`, since it at least
  shares this stack's real Harbor dependency. `docker-compose.yml` runs a
  stock `python:3.10-slim` container (`sleep infinity`, Phase 1
  placeholder — no CyberSecEval code cloned yet), with `curl`/`git`
  installed at deploy time. `/srv/cyberseceval` is a dedicated Proxmox
  mount point on the new `nvme-lvm` pool (`durable-nvme` profile, 100G) —
  the **first non-ZFS-backed extra mount in this repo**; its
  `resize_control_plane` had to be set to `provider`, not the
  `operational` value every other (ZFS-backed) stack uses — `main.tf`'s
  own check block only allows `operational` for a zfs-backed backend.
  Verified live: container running, mount present (93G avail),
  `python3 --version`/`curl --version` both confirmed by direct `docker
  exec`, not just trusted from the Ansible run.

### Framework — Nathanw-fork `llama-server` already live (discovered, not built)

Went looking to build this (plan §1a decision #4) and found it already
running: container `qwen38-flash-next-q4`,
`ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan`, port 8080, serving
`Qwen3.8-Flash-Next-UD-Q4_K_XL` (176.9B params, sharded UD-Q4_K_XL quant,
262144 ctx). Deployed by the operator directly — not through this repo's
Ansible. It supersedes the old upstream `llama-router`/`llamacpp-router`
(`ggml-org/llama.cpp`) this repo's `framework-desktop-llamacpp.yml`
deploys: confirmed `systemctl is-active llama-router` → `inactive`, no
`llamacpp-router` container running.

**Phase 1's acceptance requirement (plan §29) is met**: a real test call
from `cse-controller` reached `http://framework.gibbsgreatly.xyz:8080/health`
directly (HTTP 200, `{"status":"ok"}`) — `infra_seg` already egresses to
Framework's LAN address, no new MikroTik rule was needed. The exact
model/server config (image, command, model path, `n_ctx`, param count)
is recorded at `/srv/cyberseceval/manifests/phase1-llama-server-test.json`
on `cse-controller`'s durable mount, confirmed readable from inside the
container.

A speculative build-from-source playbook
(`ansible/00-initial-setup/framework-desktop-llamacpp-nathanw.yml`) was
written before this was discovered — kept in the repo only as an unused
reference (operator's choice) for a from-source rebuild scenario; it is
explicitly marked "NOT WIRED UP" at the top and must not be run as-is,
since it would duplicate/collide with the live container's port 8080.

## Not yet started

- `cse-code-eval`, `cse-autopatch` on `pve-tiny` — no CyberSecEval code,
  benchmark orchestration, Harbor project, or Framework integration
  exists yet. `cse-controller`'s container is an empty Python shell with
  no repo checkout.
- Cross-host MikroTik rule: `cse-controller` (once it exists on
  `pve-tiny`) → `cse-kali` (on `pve-test`). Flagged in the plan (§12) but
  deliberately deferred — the operator asked to focus on `pve-test`
  first.
- Any actual CyberSecEval benchmark run, or the CyberSecEval/PurpleLlama
  checkout itself.
- Windows Activation on `metasploitable3-win2k8` was deferred (deliberate
  — disposable pentest target, doesn't need it), and its network config
  isn't Terraform-managed (console-only, see above) — don't expect either
  to survive a VM recreate without redoing them.

## Open decisions (plan.md §1a) — all resolved 2026-09-18

3. **All three** CyberSecEval LXCs (`cse-controller`, `cse-code-eval`,
   `cse-autopatch`) live on `pve-tiny`.
4. `cse-controller` targets a **separate Nathanw Strix-Halo `llama.cpp`
   fork server** — not Framework's existing `llama-router`
   (`ggml-org/llama.cpp`), and not Ollama (that runtime decision was
   scoped to Laguna S 2.1's eval scores, doesn't bind this benchmark).
   Turned out to already exist, live — see above.
5. `cse-autopatch`'s Podman volume size: **deferred** — no pre-allocated
   number; size it from real `podman system df` output once Phase 8's
   PoC runs a shard.

## Next steps, in order

1. Harbor: create the `cyberseceval` project + scoped robot account (§18)
   — not done yet.
2. Clone PurpleLlama/CyberSecEval into `cse-controller`'s
   `/srv/cyberseceval/repo/`, pin to a commit, stand up the Python 3.10
   environment (§6, §8) — the container has Python 3.10 and `curl`/`git`
   ready, but nothing cloned yet. Phase 1 is otherwise complete.
3. Add the cross-host MikroTik rule (`cse-controller` → `cse-kali`) —
   still needed for the range side specifically (Kali is on a different
   SDN fabric on `pve-test`); Framework reachability needed no new rule.
4. Wire the controller to the range for the autonomous-offensive
   benchmark specifically — everything else in the plan's benchmark
   coverage table (§7) doesn't depend on the range at all and could be
   sequenced earlier if preferred.
