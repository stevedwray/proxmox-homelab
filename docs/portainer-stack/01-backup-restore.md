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
- A manual backup of Portainer state can be written to the NAS before destructive rebuild/restore work
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

### 4. Write backup systemd service

Service: authenticates via `POST /api/auth`, then calls `POST /api/backup`,
writes binary to `/var/backups/portainer/portainer-YYYYMMDD.tar.gz`.
Retains last 7 backups (rotation: `ls -t | tail -n +8 | xargs -r rm`).

Scheduled backups are not enabled during normal Portainer deployment. Backup
support is opt-in for destructive rebuild/restore workflows so a normal reboot
does not trigger an API backup.

Use the same credential env file pattern as other local systemd helpers:
- Credentials env file: `/etc/portainer-backup/env` (mode 0600, root only)
- Script: `/opt/portainer-backup/backup.sh`

### 5. Provision via Ansible

Create a `portainer_backup` Ansible role at
`terraform/lxc/ansible/roles/portainer_backup/` — follow the role-per-concern
pattern used by `portainer_api` and `portainer_agent`. Include the role in
`deploy-portainer-stack.yml` after the Portainer init play.

Role tasks:
- Default to `portainer_backup_enabled: false`, which removes the scheduled
  backup units when normal Portainer provisioning runs
- Write `/etc/portainer-backup/env` (mode 0600, templated from `PORTAINER_ADMIN_PASSWORD`)
- Write `/opt/portainer-backup/backup.sh`
- When explicitly enabled, write the manual systemd service unit to
  `/etc/systemd/system/`

After writing the role, run the Ansible validation tier:

```bash
# Syntax check first (always, even for comment-only changes)
ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

# Then provision
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod scripts/provision.sh --stack portainer-stack
```

### 6. Test backup

After running the backup-support path with `portainer_backup_enabled=true`, trigger
one backup explicitly:

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
git commit -m "feat(portainer): add NAS backup service and bind mount"
```

Merge into `baseline/teardown-validated` after a full teardown + redeploy cycle
confirms manual backup/restore survives rebuild:

```bash
./with-secrets-prod scripts/teardown-deploy-test.sh --stack all --disposable
```

Then open a PR: `task/portainer-backup-restore` → `baseline/teardown-validated`.

---

## Restore Runbook

`scripts/portainer-restore.sh` is the single entry point for all restore scenarios.
It probes the current Portainer state and automatically selects the correct path.

```bash
export TASK_APPROVAL="portainer-restore"
./with-secrets-prod scripts/portainer-restore.sh
```

### Path A — Normal restore (LXC rebuilt after teardown)

Used when: Portainer LXC was destroyed and recreated, or Portainer has never started.
The script detects this as HTTP ≠ 200 from `/api/system/status`.

Sequence:
1. Wipes `/var/lib/portainer` (stale DB can survive template recreation)
2. Runs `provision.sh --stack portainer-stack --tags pre_restore` (Docker base + Portainer CE, no init)
3. Waits for uninitialized Portainer API
4. POSTs the latest NAS backup to `/api/restore` directly from pve (no bind mount needed)
5. Restarts Portainer container to load restored DB
6. Verifies InstanceID changed (confirms restore applied)
7. Restarts portainer-agents on all 6 legacy hosts to re-pair with restored keypair
8. Runs `provision.sh --stack portainer-stack` (full — init gets 409 and skips; OAuth and backup support apply idempotently)

Trigger this path by running the full teardown + apply cycle first:

```bash
export TASK_APPROVAL="portainer-restore"
NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true \
  ./with-secrets-prod terragrunt destroy \
  --working-dir terraform/lxc/stacks/portainer-stack -auto-approve
NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true \
  ./with-secrets-prod terragrunt apply \
  --working-dir terraform/lxc/stacks/portainer-stack -auto-approve
./with-secrets-prod scripts/portainer-restore.sh
```

### Path B — Emergency restore (database wiped while container was live)

Used when: Portainer is running and responding (HTTP 200) but the database was wiped
or corrupted while the container was up. This is detected automatically by the script.

This can happen when:
- The LXC is reprovisioned without a full teardown and something clears `/var/lib/portainer`
- `deploy-portainer-stack.yml` runs against an LXC with a missing or empty DB (it calls
  `admin/init` immediately, permanently closing the `POST /api/restore` window)
- Manual intervention goes wrong

Because `POST /api/restore` requires an **uninitialized** instance (before `admin/init`),
this path uses tar extraction instead. The NAS bind mount inside the LXC
(`/var/backups/portainer/`) provides direct access to the backup files.

Sequence:
1. Stops the Portainer container
2. Moves the current `/var/lib/portainer` aside (timestamped, for recovery)
3. Finds the latest backup in `/var/backups/portainer/` inside the LXC
4. Extracts it via tar to `/var/lib/portainer`
5. Starts Portainer
6. Restarts portainer-agents on all 6 legacy hosts to re-pair with restored keypair
7. Runs `provision.sh --stack portainer-stack` (full — init gets 409 and skips)

Just run the script — it detects the initialized state and switches to this path automatically:

```bash
export TASK_APPROVAL="portainer-restore"
./with-secrets-prod scripts/portainer-restore.sh
```

**Verified 2026-06-29** — emergency tar path used to recover from database loss while
Portainer was running and admin-initialized. Stacks and environment registrations
fully restored from June 22 backup.

### Critical constraint: restore must happen before init (normal path only)

`POST /api/restore` only works on an **uninitialized** Portainer instance — before
`POST /api/users/admin/init` has been called. If you run `provision.sh --stack portainer-stack`
or `deploy-portainer-stack.yml` directly against a fresh-DB Portainer, admin/init fires
immediately and the restore window is permanently closed. **Always use `portainer-restore.sh`
rather than running the playbook directly when recovering from data loss.**

### Backup file location

The NAS backup bind mount (`/mnt/nas-backup/portainer-backup → /var/backups/portainer`
inside the LXC) is applied by the `portainer_backup` Ansible role via `pct set` on pve.

- Normal path: script accesses backups from pve directly (`/mnt/nas-backup/portainer-backup/`)
  so it works before `provision.sh` has run and the bind mount configured.
- Emergency path: script accesses backups from inside the LXC (`/var/backups/portainer/`)
  via the existing bind mount (present because Portainer is still running on the same LXC).

Backups: `portainer-YYYYMMDD.tar.gz`, 30-day retention. The script picks the latest
file with `ls -t | head -1`.

---

## Pre-conditions

- [x] Infrastructure Portainer deployed and stable on pve
- [x] NAS reachable from pve (`/mnt/nas-backup` mounted and healthy)
- [x] Normal restore path validated with no application stacks (2026-06-19)
- [x] Emergency restore path validated with live application stacks (2026-06-29)
