# 06-app-stacks-01 — Discover and document existing application workloads

> Historical task packet.
> This task still references the retired `baseline/teardown-validated`
> promotion path and an earlier NetBox / environment model.
> Keep it as migration-planning history rather than current workflow guidance.
> For current branch and environment rules, use
> [docs/workflow/branch-model.md](../../workflow/branch-model.md) and
> [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/113

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Validated stack-owned edge foundation is running
- Phase 05 complete — supply chain pipeline active
- NetBox running at `192.168.1.30`

## Objective

The migration table in `docs/plan/phase-06-app-stacks.md` is fully populated with each existing application's current VMID, IP, hostname, service list, and data paths, and the information is recorded in NetBox.

## Scope

- SSH into the relevant Proxmox hosts and run `pct list` / `qm list`
- For each workload: identify VMID, current IP, services running, config paths, data mount points
- Fill in the migration table in `docs/plan/phase-06-app-stacks.md`
- Create or update NetBox records to reflect current state

## Out of Scope

- Any migration, deployment, or destructive changes — this is read-only discovery
- Creating new LXC stack files (those happen in tasks 06-03 to 06-06)

## Inputs

- SSH access to current Proxmox host(s) and the containers/VMs running there
- `docs/plan/phase-06-app-stacks.md` — the migration table to fill in

## Expected Outputs

- Updated migration table in `docs/plan/phase-06-app-stacks.md`
- NetBox updated with current workload records
- Commit with the updated doc

## Constraints and Conventions

- Do not modify any running services — read-only discovery only
- Note any service that uses NFS/shared storage (NAS mounts) — these need special handling during migration
- Identify any containers with GPU/device passthrough — requires extra Terraform config in Phase 06
- Record exact image versions currently in use for Harbor mirroring before migration

## Acceptance Criteria

- [ ] `pct list` / `qm list` output captured
- [ ] Migration table in `docs/plan/phase-06-app-stacks.md` has VMID, IP, hostname, services, config paths, and NFS mounts for each workload
- [ ] GPU/device passthrough noted where applicable
- [ ] NetBox updated with current workloads
- [ ] Commit pushed to `baseline/teardown-validated`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Discover and document all existing application workloads before migrating them.
This is a read-only discovery task — do not change or restart any service.

STEP 1 — Enumerate all containers and VMs:
  # On the Proxmox host(s) — check which hosts are in your environment:
  ssh root@<proxmox-host> "pct list"
  ssh root@<proxmox-host> "qm list"

STEP 2 — For each application container/VM, note:
  - VMID and hostname
  - Current IP (pct config <vmid> | grep net0, or check /etc/network/interfaces inside)
  - Running services (docker ps, systemctl list-units --type=service --state=running)
  - Config directories (usually /config, /opt, or /etc/<service>)
  - Data mounts (pct config <vmid> | grep -E "mp[0-9]|rootfs")
  - Docker image versions: ssh root@<ip> "docker ps --format '{{.Image}}'"
  - NAS/NFS mounts: ssh root@<ip> "mount | grep nfs"

STEP 3 — Read the migration table in docs/plan/phase-06-app-stacks.md.
  Update the table with your findings. Expected services include:
  - arr stack (Radarr, Sonarr, Prowlarr, etc.)
  - Jellyfin
  - Pi-hole
  - Game services (Minecraft, etc.)
  - Any legacy proxy found during discovery should be recorded as retired cleanup only

STEP 4 — Update NetBox records:
  Access NetBox at http://192.168.1.30.
  For each discovered workload, create or update:
  - Virtual Machine or Container record
  - IP Address assignment
  - Services running on that IP

STEP 5 — Commit the updated discovery document:
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git checkout -b feat/workload-discovery
  git add docs/plan/phase-06-app-stacks.md
  git commit -m "docs(phase-06): document existing application workloads from discovery"
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git merge feat/workload-discovery
  git push origin baseline/teardown-validated

DONE WHEN: Migration table fully populated, NetBox updated, commit pushed.
```
