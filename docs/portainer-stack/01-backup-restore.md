# Sprint 01 — Portainer Backup and Restore

Prove that infrastructure Portainer state can be backed up to the NAS and
fully restored after a destroy. This must be validated before migrating any
application stacks — there is no point migrating stacks into a Portainer that
cannot survive a rebuild.

---

## Goal

After this sprint:
- A daily backup of Portainer state runs automatically and lands on the NAS
- A destroy + rebuild of the Portainer LXC followed by a restore from backup
  returns Portainer to its pre-destroy state (stacks, endpoints, env vars)
- The restore path is documented and tested, not theoretical

---

## What the Backup Covers

Portainer's `POST /api/backup` produces a binary dump of its BoltDB database.
This includes:

- Stack definitions (compose files)
- Stack environment variables (including secrets stored in Portainer)
- Endpoint registrations
- User accounts and API tokens
- Registry configuration
- OAuth and settings

It does **not** include Docker volume data (application data itself — media files,
config dirs, etc. live on NFS mounts and are unaffected by Portainer state).

---

## NAS Path

NAS NFS is already mounted on pve at `/mnt/nas-backup` (192.168.1.3:/volume1/ProxmoxBackup).

Portainer backups: `/volume1/ProxmoxBackup/portainer-backup/` on the NAS,
accessible from pve at `/mnt/nas-backup/portainer-backup/`.

---

## Tasks

### 1. Confirm Portainer LXC privilege level

The Portainer LXC runs Docker, which typically requires a privileged LXC.
Confirm: `pct config 20020 | grep unprivileged`

Result determines how the NFS bind mount is configured (UID mapping).
A privileged LXC simplifies this considerably.

### 2. Create NAS directory

On the NAS (ADM or SSH): create `/volume1/ProxmoxBackup/portainer-backup/`
with appropriate permissions for the LXC to write.

### 3. Configure NFS bind mount into Portainer LXC

Add to the Portainer LXC's Terraform config (or pct config directly to test):

```
mp0: /mnt/nas-backup/portainer-backup,mp=/var/backups/portainer
```

The pve NFS mount at `/mnt/nas-backup` must be mounted before the LXC starts.
The existing `_netdev` and `x-systemd.requires=network-online.target` fstab
flags already handle this for the pve host mount.

If the LXC is unprivileged, a bindfs re-mount (same pattern as CT105/PBS) will
be needed to map UIDs. Assess after step 1.

### 4. Write backup systemd service and timer

Service: calls `POST /api/backup` against `http://localhost:9000/api/backup`,
writes the response binary to `/var/backups/portainer/portainer-YYYYMMDD.tar.gz`.
Retains last 7 backups (prune older files).

Timer: daily, `Persistent=true`, `RandomizedDelaySec=1800`.

Pattern is identical to `netbox-populate.timer` — use it as the template.

Credentials: authenticates with admin password via `POST /api/auth` to get JWT,
then calls backup endpoint with `Authorization: Bearer <jwt>`.
Admin password sourced from a credentials env file (analogous to
`/etc/netbox-populate/env`).

### 5. Provision via Ansible

Add backup timer tasks to `deploy-portainer-stack.yml`:
- Write credentials env file (`/etc/portainer-backup/env`, mode 0600)
- Write backup script to `/opt/portainer-backup/backup.sh`
- Write systemd service and timer units
- Enable and start timer

### 6. Test backup

Trigger manually: `systemctl start portainer-backup.service`
Verify: file appears at `/var/backups/portainer/` and on NAS path.
Check file is a valid tar.gz: `tar tzf <file> | head`.

### 7. Test restore

Full destroy + restore cycle:
1. Note current stack count and endpoint list in Portainer UI
2. Destroy Portainer LXC: `pct destroy 20020 --destroy-unreferenced-disks`
3. Reprovision: `PVE_ENV=pve ./with-secrets-prod scripts/provision.sh --stack portainer-stack`
4. Restore: `POST /api/restore` with the backup file
5. Verify: stacks, endpoints, env vars match pre-destroy state
6. Verify: portainer-agents on app hosts reconnect (check Environments — should go green)

### 8. Document restore procedure

Write a runbook section below with the exact restore commands, so future-you
doesn't have to figure it out under pressure.

### 9. Commit and merge

Validation gate: successful destroy + restore cycle with application stacks intact.

---

## Restore Runbook

_To be filled in after task 7 is completed and the exact commands are confirmed._

```
# 1. Provision fresh Portainer
PVE_ENV=pve ./with-secrets-prod scripts/provision.sh --stack portainer-stack

# 2. Get admin JWT
TOKEN=$(curl -s -X POST http://<portainer-ip>:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"<password>"}' | jq -r .jwt)

# 3. Restore from backup
curl -X POST http://<portainer-ip>:9000/api/restore \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/var/backups/portainer/<backup-file>.tar.gz"

# 4. Restart Portainer to apply restored state
docker restart portainer
```

---

## Pre-conditions

- [ ] Infrastructure Portainer deployed and stable on pve
- [ ] NAS reachable from pve (`/mnt/nas-backup` mounted and healthy)
- [ ] No application stacks migrated yet (nothing to lose during test restore)
