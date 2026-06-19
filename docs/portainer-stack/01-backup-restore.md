# Sprint 01 — Portainer Backup and Restore

Prove that infrastructure Portainer state can be backed up to the NAS and
fully restored after a destroy. This must be validated before migrating any
application stacks — there is no point migrating stacks into a Portainer that
cannot survive a rebuild.

---

## Branch

Cut from `baseline/teardown-validated`:

```bash
git checkout baseline/teardown-validated && git pull
git checkout -b task/portainer-backup-restore
```

All pve commands run through `./with-secrets-prod`. Mutating commands require
`TASK_APPROVAL` to be set first. See [00-overview.md — Working in This Repo](00-overview.md#working-in-this-repo)
for the full working practices reference.

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

```bash
./with-secrets-prod pct config 20020 | grep unprivileged
```

The Portainer LXC runs Docker, which typically requires a privileged LXC.
A privileged LXC (no `unprivileged: 1` line) means UID 0 inside = UID 0 on
host, which simplifies NFS permissions. If unprivileged, a bindfs re-mount
will be needed (same pattern as CT105/PBS in the existing pve fstab).

### 2. Create NAS directory

On the NAS (ADM GUI or SSH): create `/volume1/ProxmoxBackup/portainer-backup/`
with write permissions for root (privileged LXC) or the mapped UID (unprivileged).

### 3. Configure NFS bind mount into Portainer LXC

Add to the Portainer LXC Terraform resource or apply directly to test:

```bash
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod pct set 20020 -mp0 /mnt/nas-backup/portainer-backup,mp=/var/backups/portainer
```

The pve NFS mount at `/mnt/nas-backup` is already in fstab with `_netdev` and
`x-systemd.requires=network-online.target` — it mounts before LXCs start.

Also add the bind mount to the Portainer LXC's Terraform config so it survives
a full teardown cycle.

### 4. Write backup systemd service and timer

Service: authenticates via `POST /api/auth`, then calls `POST /api/backup`,
writes binary to `/var/backups/portainer/portainer-YYYYMMDD.tar.gz`.
Retains last 7 backups.

Timer: daily, `Persistent=true`, `RandomizedDelaySec=1800`.

Model on `netbox-populate.timer` (same credential env file pattern):
- Credentials env file: `/etc/portainer-backup/env` (mode 0600, root only)
- Script: `/opt/portainer-backup/backup.sh`

### 5. Provision via Ansible

Add tasks to `deploy-portainer-stack.yml` (run after the Ansible validation
tier — syntax-check first, then provision to apply):

```bash
# Syntax check first (always, even for comment-only changes)
ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

# Then provision
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod scripts/provision.sh --stack portainer-stack
```

Tasks to add:
- Write `/etc/portainer-backup/env` (mode 0600, templated from `PORTAINER_ADMIN_PASSWORD`)
- Write `/opt/portainer-backup/backup.sh`
- Write systemd service and timer units to `/etc/systemd/system/`
- `systemctl daemon-reload && systemctl enable --now portainer-backup.timer`

### 6. Test backup

```bash
./with-secrets-prod pct exec 20020 -- systemctl start portainer-backup.service
./with-secrets-prod pct exec 20020 -- ls -lh /var/backups/portainer/
```

Verify file also appears on NAS at `/volume1/ProxmoxBackup/portainer-backup/`.
Sanity-check the file: `tar tzf <file> | head`.

### 7. Test restore

Full destroy + restore cycle — **this is the validation gate for this sprint**.
Do this while no application stacks are migrated yet so there is nothing to lose:

```bash
# Record pre-destroy state
./with-secrets-prod pct exec 20020 -- \
  curl -s http://localhost:9000/api/stacks | jq '[.[].Name]'

# Destroy LXC (mutating — TASK_APPROVAL required)
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod pct destroy 20020 --destroy-unreferenced-disks

# Reprovision
./with-secrets-prod scripts/provision.sh --stack portainer-stack

# Restore from backup (see Restore Runbook below)
```

After restore: verify stacks, endpoints, and env vars match pre-destroy state.

### 8. Document restore procedure

Fill in the Restore Runbook section below with exact commands confirmed in step 7.

### 9. Commit, merge, and promote

```bash
git add -p
git commit -m "feat(portainer): add NAS backup timer and bind mount"
```

Merge into `baseline/teardown-validated` after a full teardown + redeploy cycle
confirms backup timer survives rebuild:

```bash
./with-secrets-prod scripts/teardown-deploy-test.sh --stack all --disposable
```

Then open a PR: `task/portainer-backup-restore` → `baseline/teardown-validated`.

---

## Restore Runbook

_To be completed and verified during task 7. Commands below are a template — fill in
actual Portainer LXC IP and confirm the exact steps work before treating this as
authoritative._

```bash
# 1. Provision fresh Portainer LXC
export TASK_APPROVAL="portainer-restore"
./with-secrets-prod scripts/provision.sh --stack portainer-stack

# 2. Get admin JWT (from inside the LXC or from a host that can reach mgmt_seg)
#    Admin password is in terraform/secrets.pve.enc.yaml — use ./with-secrets-prod
#    to resolve it rather than typing it in plaintext
PORTAINER_IP=192.168.20.20
TOKEN=$(./with-secrets-prod bash -c '
  curl -s -X POST http://'"$PORTAINER_IP"':9000/api/auth \
    -H "Content-Type: application/json" \
    -d "{\"Username\":\"admin\",\"Password\":\"${PORTAINER_ADMIN_PASSWORD}\"}" \
  | jq -r .jwt
')

# 3. Restore from latest NAS backup
BACKUP=$(ls -t /mnt/nas-backup/portainer-backup/portainer-*.tar.gz | head -1)
curl -X POST http://$PORTAINER_IP:9000/api/restore \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$BACKUP"

# 4. Restart Portainer to apply restored state
./with-secrets-prod pct exec 20020 -- docker restart portainer
```

---

## Pre-conditions

- [ ] Infrastructure Portainer deployed and stable on pve
- [ ] NAS reachable from pve (`/mnt/nas-backup` mounted and healthy)
- [ ] No application stacks migrated yet (nothing to lose during test restore)
