# Sprint 04: PBS → infra_seg

Move Proxmox Backup Server from LAN bridge into `infra_seg` (VLAN 40).

**Detail level:** Sketch — flesh out before starting this sprint.

---

## Current state

- PBS running on LAN (NetBox ID 20, VMID unknown)
- Currently backs up: Garuda workstation
- Will back up: other pve VMs/LXCs and future clients
- PBS datastore: backed by NAS iSCSI LUN mounted at pve host level
- Client port: `8007/tcp`

---

## Target

- PBS at `192.168.40.x` in `infra_seg`
- LAN clients (Garuda, future) → `infra_seg:8007`
- pve host backup jobs → `infra_seg:8007`
- PBS → NAS iSCSI stays on LAN bridge (no change — iSCSI is hypervisor-level, not PBS-level)

---

## Pre-conditions (to flesh out)

- [ ] PBS VMID confirmed: `./with-secrets-prod pvesh get /nodes/pve/qemu`
- [ ] PBS datastore type confirmed: iSCSI-backed, NFS-backed, or local disk
  - If iSCSI: pve host initiator connects to 192.168.1.3:3260 — unaffected by VM network change
  - If NFS: confirm mount origin before moving
- [ ] A PBS backup completes successfully immediately before migration
- [ ] MikroTik rules: `LAN → infra_seg:8007`, `infra_seg → 192.168.1.3` (storage protocol)
- [ ] `infra_seg` already exists (VLAN 40) — no new zone needed

---

## Key considerations

- **iSCSI is fragile**: do not change NAS addressing or disconnect the LUN while PBS is live.
  The iSCSI connection is pve host ↔ NAS, not PBS VM ↔ NAS. Moving the PBS VM's network
  interface to infra_seg does not affect iSCSI — the hypervisor handles it below the VM.
- **Client reconfiguration**: after PBS gets new IP, update:
  - Garuda workstation: `proxmox-backup-client` config pointing to old PBS IP
  - pve Datacenter → Storage → PBS server address
- **Snapshot before migration**: take a VM snapshot of PBS before moving its network interface
- **Run and verify backup after cutover** before removing old network config

---

## Steps (to be detailed)

1. Confirm PBS VMID and datastore type (prod access required)
2. Add MikroTik rules for infra_seg ↔ PBS
3. Take PBS VM snapshot
4. Move PBS VM network interface to infra_seg, assign 192.168.40.x
5. Confirm PBS web UI accessible at new IP
6. Update pve Datacenter storage config to new PBS IP
7. Update Garuda backup client config
8. Run a backup job and restore test
9. Remove temporary broad LAN allowances if any
