# CyberSecEval Implementation — Current State

Entrypoint for this workspace, per `docs/workflow/documentation-workspaces.md`.
`plan/cyberseceval-implementation-plan.md` is the design (Meta's benchmark,
architecture, phases); this file tracks what has actually been built and
verified against it, and what's next. Update this file, not the plan doc's
prose, as work lands — the plan's §1a "Open decisions" list is still the
source of truth for unresolved judgment calls.

## Status (2026-09-18): cyber range built and verified; compute side not started

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
  profile). Nothing CyberSecEval-specific deployed here yet.

## Not yet started

- `cse-controller`, `cse-code-eval`, `cse-autopatch` on `pve-tiny` — no
  CyberSecEval code, benchmark orchestration, Harbor project, or Framework
  integration exists yet.
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

## Open decisions (plan.md §1a — still unresolved)

3. Does `pve-tiny` host all three CyberSecEval LXCs, or just
   `cse-controller`? (plan's proposed default: all three)
4. Framework inference layer: target the existing `llama-router`
   (upstream `ggml-org/llama.cpp` build, confirmed live) as-is, or is a
   separate Nathanw-fork server genuinely wanted?
5. `cse-autopatch`'s initial Podman working-volume size on `pve-tiny`'s
   `durable-nvme` pool (proposed: 150–250GB, measure-first per §17)

## Next steps, in order

1. Resolve open decisions #3–5 above.
2. Build `cse-controller` on `pve-tiny` (plan Phase 1): reach Framework's
   `llama-server`, record model/server config in a run manifest.
3. Harbor: create the `cyberseceval` project + scoped robot account (§18)
   — not done yet.
4. Clone PurpleLlama/CyberSecEval, pin to a commit, stand up the Python
   3.10 environment (§6, §8).
5. Add the cross-host MikroTik rule (`cse-controller` → `cse-kali`) once
   the controller exists.
6. Wire the controller to the range for the autonomous-offensive
   benchmark specifically — everything else in the plan's benchmark
   coverage table (§7) doesn't depend on the range at all and could be
   sequenced earlier if preferred.
