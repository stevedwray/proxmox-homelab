# Sprint 02 — Migration from Existing Portainer

Migrate application stacks from the existing Portainer server to the
infrastructure Portainer. After this sprint the existing Portainer server
is decommissioned.

**Pre-condition: Sprint 01 (backup/restore) must be complete and validated.**

---

## Goal

After this sprint:
- All application stacks (torrent, media, gaming, any others) are owned and
  managed by infrastructure Portainer
- Application host portainer-agents are registered as endpoints in infrastructure Portainer
- Existing Portainer server is shut down and decommissioned
- First backup of the migrated state has run and landed on NAS

---

## Tasks

### 1. Identify agent type on existing Portainer

In the existing Portainer UI: **Settings → Environments** — check the Type column.
- "Agent" → regular agent (port 9001, Portainer dials in)
- "Edge Agent" → edge agent (agent dials out, has join token)

This determines steps 4 and 5 below.

### 2. Inventory existing stacks

In the existing Portainer: list all stacks, note:
- Stack names
- Which endpoint each stack runs on
- Any non-obvious environment variables (secrets stored in Portainer)

Secrets in Portainer that are NOT in SOPS will need to be captured manually
before migration. These will not survive a backup/restore if they were never
in SOPS.

### 3. Export backup from existing Portainer

```bash
# Get JWT from existing Portainer
TOKEN=$(curl -s -X POST http://<existing-portainer-ip>:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"<password>"}' | jq -r .jwt)

# Download backup
curl -o portainer-migration-backup.tar.gz \
  -H "Authorization: Bearer $TOKEN" \
  http://<existing-portainer-ip>:9000/api/backup
```

Store backup on NAS at `/volume1/ProxmoxBackup/portainer-backup/portainer-migration-YYYYMMDD.tar.gz`.

### 4a. If regular agents — register endpoints in infrastructure Portainer

Regular agents just listen — no reconfiguration needed on the app hosts.
Add each application host as an endpoint in infrastructure Portainer via the UI
or portainer_api role:

- Endpoint name: matches existing (e.g., `torrent-stack`, `media-stack`)
- URL: `tcp://<app-lxc-ip>:9001`
- Verify endpoint goes green (agent is reachable)

MikroTik pre-condition: `mgmt_seg → <zone>:9001` rule must exist.
See application-migration/00-overview.md pre-conditions.

### 4b. If edge agents — update join tokens on app hosts

Generate new edge keys in infrastructure Portainer for each endpoint.
On each application host update the portainer-agent config with the new
join token and restart the service. The agent will re-register with
infrastructure Portainer.

### 5. Restore or re-create stacks in infrastructure Portainer

Two options depending on Portainer version compatibility:

**Option A — restore backup (preferred if versions are close)**

```bash
TOKEN=$(curl -s -X POST http://192.168.20.20:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"<password>"}' | jq -r .jwt)

curl -X POST http://192.168.20.20:9000/api/restore \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@portainer-migration-backup.tar.gz"
```

After restore: verify stacks are present and endpoints are assigned correctly.
Stack env vars should be intact.

**Option B — re-create stacks manually (if versions differ or restore fails)**

For each stack:
1. In infrastructure Portainer: Stacks → Add Stack
2. Paste compose file content
3. Add environment variables (from SOPS where available, from notes in step 2 for others)
4. Deploy on the correct endpoint

### 6. Verify stacks are running

For each migrated stack:
- Check stack status in Portainer (running)
- Spot-check the actual service (UI accessible, expected behaviour)
- Confirm Traefik has picked up the stack's labels (if applicable)

### 7. Trigger backup

Run `systemctl start portainer-backup.service` on the Portainer LXC to take
an immediate backup of the migrated state. Verify it lands on the NAS.
This is the recovery point from this moment forward.

### 8. Decommission existing Portainer

Once all stacks are verified in infrastructure Portainer:
- Stop the existing Portainer server (or its container)
- Confirm app stacks continue running (they're now managed by infrastructure Portainer)
- Decommission the old LXC/VM if it was dedicated to Portainer
- Remove the old portainer DNS record if applicable

### 9. Commit and merge

---

## Pre-conditions

- [ ] Sprint 01 complete: backup and restore validated
- [ ] Access to existing Portainer (credentials)
- [ ] Application host IPs known for endpoint registration
- [ ] MikroTik `mgmt_seg → <zone>:9001` rules in place for each app zone
- [ ] Inventory of stacks and any Portainer-only secrets (step 2) complete before proceeding
