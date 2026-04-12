# 02-memory-upgrade-02 — Resize pve-test VM to 32 GB on host Proxmox

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/88

## Phase

Phase 02 — pve-test Memory Upgrade (32 GB)

## Prerequisites

- Task 02-01 complete: baselines recorded, any right-sizing committed
- Access to the **host** Proxmox node (physical machine that runs pve-test as a QEMU VM)
- pve-test VMID on the host is known (find with `qm list | grep pve-test`)
- Scheduled maintenance window arranged (Harbor and NetBox will be offline during the resize)

## Objective

The pve-test QEMU VM is configured with 32768 MB RAM (`qm config <vmid> | grep memory` shows `memory: 32768`) and `free -h` inside pve-test shows ~30 GB total after restart.

## Scope

- Gracefully stop all LXCs inside pve-test
- Shut down the pve-test VM from the host
- Set VM memory to 32768 MB via `qm set` or Proxmox UI
- Start pve-test and restart LXCs
- Verify memory and service health

## Out of Scope

- Service health validation beyond boot (that is task 02-03)
- Any code or configuration changes

## Inputs

- Host Proxmox shell or web UI
- pve-test VMID on the host (discover with `qm list`)
- `docs/plan/phase-02-memory-upgrade.md` — Part B for exact procedure

## Expected Outputs

- No file changes
- pve-test VM memory: 32768 MB
- All LXCs restarted

## Constraints and Conventions

- **This is a destructive operation** — pve-test and all its LXCs will be offline during the resize window
- Always shut down LXCs gracefully before stopping the VM (`systemctl stop pve-guests.service` inside pve-test)
- Do not resize while LXCs are running (risk of corruption)
- If using `qm set`, the change takes effect only after VM restart

## Acceptance Criteria

- [ ] `systemctl stop pve-guests.service` or individual `pct stop` ran to shut LXCs down cleanly
- [ ] `qm shutdown <pvetest-vmid>` completed: `qm status <vmid>` shows `stopped`
- [ ] `qm set <pvetest-vmid> --memory 32768` succeeded
- [ ] `qm config <pvetest-vmid> | grep memory` shows `memory: 32768`
- [ ] `qm start <pvetest-vmid>` succeeded
- [ ] `free -h` inside pve-test shows ~30 GB total

## Session Prompt

```
You are performing a manual infrastructure operation on the host Proxmox node to resize
the pve-test nested VM from 16 GB to 32 GB RAM.

BEFORE STARTING, READ:
  docs/plan/phase-02-memory-upgrade.md   (Part B — authoritative procedure)

This task requires SSH access to the HOST Proxmox node (not pve-test itself).

STEP 1 — Find pve-test VMID on the host:
  # On the HOST Proxmox node:
  qm list | grep pve-test
  # Note the VMID — call it <pvetest-vmid>

STEP 2 — Gracefully stop all LXCs inside pve-test:
  # SSH into pve-test first:
  ssh root@pve-test.gibbsgreatly.xyz
  systemctl stop pve-guests.service
  exit

STEP 3 — Shut down pve-test VM from the host:
  # On the HOST Proxmox node:
  qm shutdown <pvetest-vmid>
  watch qm status <pvetest-vmid>
  # Wait until status: stopped

STEP 4 — Set memory to 32 GB:
  qm set <pvetest-vmid> --memory 32768
  qm config <pvetest-vmid> | grep memory
  # Expected: memory: 32768

STEP 5 — Start pve-test:
  qm start <pvetest-vmid>
  # Wait ~2 minutes for boot

STEP 6 — Verify memory inside pve-test:
  ssh root@pve-test.gibbsgreatly.xyz "free -h"
  # Expected: ~30 GB total

STEP 7 — Restart LXCs:
  ssh root@pve-test.gibbsgreatly.xyz "systemctl start pve-guests.service"
  # Or start individually in dependency order:
  # ssh root@pve-test.gibbsgreatly.xyz "pct start 119 && pct start 121 && pct start 141"

DONE WHEN: free -h shows ~30 GB and all LXCs have started. Then proceed to task
02-memory-upgrade-03-verify-services.md.
No code changes — no commit needed.
```
