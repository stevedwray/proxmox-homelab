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

**Confirmed:** LXC 20020 runs `unprivileged: 1` with `features: nesting=1`.
subuid mapping is `root:100000:65536`, so:
- UID 0 (root) inside LXC = UID **100000** on pve host
- Proxmox presents a directory owned by host UID 100000 as root-owned inside the LXC

No bindfs re-mount is needed — correct ownership on the NAS directory is sufficient.

### 2. Create NAS directory

On pve, via the NFS mount (NFS export uses no_root_squash — verified by `dump/`
being root-owned under the same mount):

```bash
mkdir /mnt/nas-backup/portainer-backup
chown 100000:100000 /mnt/nas-backup/portainer-backup
chmod 700 /mnt/nas-backup/portainer-backup
```

Inside the LXC, Proxmox's UID remapping presents this directory as root-owned 700.
The backup script running as root inside the LXC can read/write it, and no other
user or process can.

### 3. Configure NFS bind mount into Portainer LXC

The `lxc-docker-host` Terraform module (`terraform/lxc/modules/lxc-docker-host/main.tf`)
supports `mount_point` blocks for LVM volumes but does not yet have a host bind mount
input. Add one before this sprint begins — it unlocks a clean teardown-cycle-safe path.

**Extend the module** — add a `host_bind_mounts` variable and dynamic block:

```hcl
# In terraform/lxc/modules/lxc-docker-host/variables.tf
variable "host_bind_mounts" {
  type    = list(object({ host_path = string, lxc_path = string }))
  default = []
}

# In terraform/lxc/modules/lxc-docker-host/main.tf  (inside the container resource)
dynamic "mount_point" {
  for_each = var.host_bind_mounts
  content {
    volume = mount_point.value.host_path
    path   = mount_point.value.lxc_path
  }
}
```

**Declare the bind mount in `stack.yaml`:**

```yaml
host_bind_mounts:
  - host_path: /mnt/nas-backup/portainer-backup
    lxc_path: /var/backups/portainer
```

Wire the new variable through `terraform/lxc/main.tf` (pass
`local.stack.host_bind_mounts` to the module call).

This bind mount will be re-applied on every `terraform apply`, surviving teardown
cycles automatically.

**Test manually first** before wiring into Terraform (verify NFS permissions work):

```bash
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod pct set 20020 -mp0 /mnt/nas-backup/portainer-backup,mp=/var/backups/portainer
```

The pve NFS mount at `/mnt/nas-backup` is already in fstab with `_netdev` and
`x-systemd.requires=network-online.target` — it mounts before LXCs start.

### 4. Write backup systemd service and timer

Service: authenticates via `POST /api/auth`, then calls `POST /api/backup`,
writes binary to `/var/backups/portainer/portainer-YYYYMMDD.tar.gz`.
Retains last 7 backups (rotation: `ls -t | tail -n +8 | xargs -r rm`).

Timer: daily, `Persistent=true`, `RandomizedDelaySec=1800`.

Model on `netbox-populate.timer` (same credential env file pattern):
- Credentials env file: `/etc/portainer-backup/env` (mode 0600, root only)
- Script: `/opt/portainer-backup/backup.sh`

### 5. Provision via Ansible

Create a `portainer_backup` Ansible role at
`terraform/lxc/ansible/roles/portainer_backup/` — follow the role-per-concern
pattern used by `portainer_api` and `portainer_agent`. Include the role in
`deploy-portainer-stack.yml` after the Portainer init play.

Role tasks:
- Write `/etc/portainer-backup/env` (mode 0600, templated from `PORTAINER_ADMIN_PASSWORD`)
- Write `/opt/portainer-backup/backup.sh`
- Write systemd service and timer units to `/etc/systemd/system/`
- `systemctl daemon-reload && systemctl enable --now portainer-backup.timer`

After writing the role, run the Ansible validation tier:

```bash
# Syntax check first (always, even for comment-only changes)
ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

# Then provision
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod scripts/provision.sh --stack portainer-stack
```

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

### 9. Tidyup — add single-stack redeploy harness

During this sprint it became clear there is no top-level command to apply Terraform + Ansible
for a single named stack without running the full teardown cycle. The pattern is embedded inside
`teardown-deploy-test.sh`'s `stack_apply()` but not exposed externally.

Tracked in **issue #381**. After the restore gate is passed, cut a `task/single-stack-harness`
branch and add a `--stack NAME` flag (or a new `scripts/deploy-stack.sh`) that runs:
1. `terragrunt apply -auto-approve` from the stack directory
2. `provision.sh --stack NAME`

This is a separate task; do not block sprint 01 promotion on it.

### 10. Commit, merge, and promote

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

**Verified 2026-06-19.** Commands below are confirmed working.

### Critical constraint: restore must happen before `provision.sh`

`POST /api/restore` only works on an **uninitialized** Portainer instance. Once
`provision.sh` runs the init play (`POST /api/users/admin/init`), the instance is
initialized and the restore API returns 400. The correct order is:

1. `terragrunt apply` → LXC created, Portainer starts uninitialized
2. Restore from backup (no auth required on uninitialized instance)
3. `provision.sh` → init play gets 409 (already initialized from backup, skips);
   OAuth, timer, bind mount all apply idempotently

```bash
# 0. Verify NAS backup directory is accessible and has a backup file
ls /mnt/nas-backup/portainer-backup/

# 1. Deploy fresh LXC (Terraform only — do NOT run provision.sh yet)
export TASK_APPROVAL="portainer-restore"
NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true \
  ./with-secrets-prod terragrunt apply \
  --working-dir terraform/lxc/stacks/portainer-stack -auto-approve

# 2. Wait for Portainer API to come up (uninitialized — no auth needed yet)
until curl -sf http://192.168.20.20:9000/api/system/status > /dev/null; do sleep 3; done
echo "Portainer API ready — InstanceID before restore:"
curl -s http://192.168.20.20:9000/api/system/status | jq .InstanceID

# 3. Restore from NAS backup (no Bearer token — instance is not yet initialized)
#    The backup file is accessible inside the LXC at /var/backups/portainer/
#    (NAS bind mount is applied at container creation time)
ssh root@pve.gibbsgreatly.xyz "pct exec 20020 -- bash -c '
  BACKUP=\$(ls -t /var/backups/portainer/portainer-*.tar.gz | head -1)
  echo \"Restoring from: \${BACKUP}\"
  tar tzf \"\${BACKUP}\" | head -5
  curl -sf -X POST http://localhost:9000/api/restore \
    -F \"file=@\${BACKUP}\" \
    -w \"\nHTTP %{http_code}\n\"
'"

# 4. Restart Portainer to load restored state
ssh root@pve.gibbsgreatly.xyz "pct exec 20020 -- docker restart portainer-portainer-1"
sleep 10

# 5. Verify InstanceID matches the backed-up instance
curl -s http://192.168.20.20:9000/api/system/status | jq .InstanceID

# 6. Run provision.sh — init gets 409 (skipped), everything else applies
./with-secrets-prod scripts/provision.sh --stack portainer-stack

# 7. Verify Portainer is healthy and auth works
curl -s http://192.168.20.20:9000/api/system/status | jq .
```

### Bind mount note

`mp1` (`/mnt/nas-backup/portainer-backup → /var/backups/portainer`) is applied by the
`portainer_backup` Ansible role via `pct set` on the pve host. Because step 6 runs
`provision.sh` after the restore, the bind mount is guaranteed to be in place.

The backup file at `/var/backups/portainer/` is accessible from the LXC **as soon as
`provision.sh` has run at least once** (or if restored from a backup that included the
bind mount in the container config). On a brand-new LXC before provision, the NAS path
is not yet mounted — use the NAS path directly on pve for the initial restore instead:

```bash
# Alternative step 3 (if bind mount not yet applied — before first provision.sh):
ssh root@pve.gibbsgreatly.xyz "bash -c '
  BACKUP=\$(ls -t /mnt/nas-backup/portainer-backup/portainer-*.tar.gz | head -1)
  curl -sf -X POST http://192.168.20.20:9000/api/restore \
    -F \"file=@\${BACKUP}\" \
    -w \"\nHTTP %{http_code}\n\"
'"
```

After restore, Ansible can run again safely — the provisioner is idempotent and will
only update settings that differ from desired state (admin password and OAuth settings
will match SOPS, so no changes should apply).

---

## Pre-conditions

- [ ] Infrastructure Portainer deployed and stable on pve
- [ ] NAS reachable from pve (`/mnt/nas-backup` mounted and healthy)
- [ ] No application stacks migrated yet (nothing to lose during test restore)
