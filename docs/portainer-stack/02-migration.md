# Sprint 02 — Migration from Existing Portainer

Migrate application stacks from the existing Portainer server to the
infrastructure Portainer. After this sprint the existing Portainer server
is decommissioned.

**Pre-condition: Sprint 01 (backup/restore) must be complete and validated.**

---

## Branch

Cut from `baseline/teardown-validated` (not from the sprint 01 branch):

```bash
git checkout baseline/teardown-validated && git pull
git checkout -b task/portainer-migration
```

Sprint 01 must be merged to `baseline/teardown-validated` before this branch
is cut — this sprint builds on the backup infrastructure being present and
provisioned.

All pve commands run through `./with-secrets-prod`. Mutating commands require
`TASK_APPROVAL`. See [00-overview.md — Working in This Repo](00-overview.md#working-in-this-repo).

---

## Existing Portainer

**Server:** `management-stack` LXC — `192.168.1.4`, on the LAN bridge.
**Portainer CE:** `2.33.6`, port 9000 (HTTP).
**Credentials:** not in SOPS — admin password must be retrieved from management-stack
before this sprint begins.

**Version incompatibility:** legacy is `2.33.6`, infra Portainer is `2.27.3`. A backup
from a newer version cannot restore into an older one. **Option A (backup/restore) is
not available for this migration.** All stacks must be migrated via Option B
(re-register agents, re-create stacks manually or via API).

Also running on management-stack: NPM, central Docker registry, registry-ui, Trivy.
This sprint covers the Portainer migration only. Full management-stack decommission
is a later step — see
[application-migration/05-management-decommission.md](../application-migration/05-management-decommission.md).

**Application hosts currently managed (on LAN bridge):**
- `torrent-stack` — `192.168.1.5`, endpoint `tcp://192.168.1.5:9001`
- `media-stack` — `192.168.1.6`, endpoint `tcp://192.168.1.6:9001`
- `gaming-stack` — `192.168.1.7`, endpoint `tcp://192.168.1.7:9001`

After this sprint, infra Portainer owns these endpoints at their **current LAN IPs**.
Endpoint URLs will be updated to VLAN IPs as each application-migration sprint runs.

---

## Relationship to Application-Migration Sprints

This sprint (portainer-stack/02) migrates ownership of the Portainer server — all
endpoints re-registered from the management-stack Portainer to infra Portainer.

The [application-migration sprints](../application-migration/00-overview.md) migrate
the application LXCs themselves into VLAN zones (dl_seg, media_seg, game_seg). Those
sprints run after this one, and each updates the portainer endpoint URL from the old
LAN IP to the new VLAN IP via the `portainer_api` role.

Sequencing:
```
portainer-stack/01  →  portainer-stack/02  →  app-migration/01  →  app-migration/02
(backup validated)     (ownership migrated)   (torrent → dl_seg) (media → media_seg)
                                                ↓ each sprint updates endpoint URL in infra Portainer
```

---

## Goal

After this sprint:
- All application stacks (torrent, media, gaming) are owned and managed by
  infrastructure Portainer
- Application host portainer-agents are registered as endpoints in infrastructure Portainer
  (initially at their LAN bridge IPs — updated to VLAN IPs by later app-migration sprints)
- Existing management-stack Portainer is stopped (management-stack LXC remains up;
  full decommission is sprint 05 of application-migration)
- First backup of the migrated state has run and landed on NAS

---

## Tasks

### 0. Check existing Portainer version

Before doing anything else, check the existing Portainer version to determine whether
Option A (backup/restore) will work cleanly.

In the existing Portainer UI: **Settings → About** — note the version number.
Or via API:

```bash
curl -s http://192.168.1.4:9000/api/system/status | jq .Version
```

Infrastructure Portainer runs **2.27.3**. Legacy is **2.33.6** — newer than infra.
Backup/restore across versions is incompatible. **Use Option B only** (task 5).

### 1. Identify agent type on existing Portainer

In the existing Portainer UI: **Settings → Environments** — check the Type column.
- "Agent" → regular agent (port 9001, Portainer dials in)
- "Edge Agent" → edge agent (agent dials out, has join token)

This determines steps 4 and 5 below. The existing agent type is expected to be
"Agent" (regular) based on the application-migration sprint docs.

### 2. Inventory existing stacks

In the existing Portainer at `http://192.168.1.4:9000`: list all stacks, note:
- Stack names
- Which endpoint each stack runs on
- Any non-obvious environment variables (secrets stored in Portainer)

Secrets in Portainer that are NOT in SOPS will need to be captured manually
before migration. These will not survive a backup/restore if they were never
in SOPS.

### 3. Export backup from existing Portainer

Retrieve the admin password from the existing Portainer host (check its stack env
file or the management LXC where it's deployed) and run:

```bash
EXISTING_PORTAINER_IP=192.168.1.4
TOKEN=$(curl -s -X POST http://$EXISTING_PORTAINER_IP:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"Username":"admin","Password":"<existing-password>"}' | jq -r .jwt)

curl -o /mnt/nas-backup/portainer-backup/portainer-migration-$(date +%Y%m%d).tar.gz \
  -H "Authorization: Bearer $TOKEN" \
  http://$EXISTING_PORTAINER_IP:9000/api/backup
```

Writing directly to `/mnt/nas-backup/portainer-backup/` keeps the backup off
local disk and immediately on the NAS.

### 4a. If regular agents — un-pair from legacy and register in infrastructure Portainer

**Agent pairing constraint (validated 2026-06-19):** A portainer-agent can only be paired
with ONE Portainer server at a time. Pairing state is stored in the agent container's
writable layer. `docker restart` does NOT clear it — the old state remains in the
container filesystem. Additionally, legacy Portainer's polling reconnects within seconds
of an agent restart, winning any race to re-pair.

**Required procedure per host:**

```bash
APP_HOST_IP=192.168.1.5   # change per host
APP_HOST_VMID=...          # Proxmox LXC VMID

# 1. Block legacy Portainer from reconnecting during the transition
ssh root@pve.gibbsgreatly.xyz "pct exec ${APP_HOST_VMID} -- \
  iptables -I INPUT -s 192.168.1.4 -p tcp --dport 9001 -j DROP"

# 2. Destroy and recreate the agent container (docker rm clears writable layer)
ssh root@pve.gibbsgreatly.xyz "pct exec ${APP_HOST_VMID} -- bash -c \
  'cd /opt/portainer && docker compose down && docker compose up -d portainer-agent'"

# 3. Immediately register with infra Portainer (while legacy is still blocked)
JWT=$(curl -sf http://192.168.20.20:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<PORTAINER_ADMIN_PASSWORD>"}' | jq -r '.jwt')

curl -s http://192.168.20.20:9000/api/endpoints \
  -H "Authorization: Bearer ${JWT}" \
  -F "Name=<endpoint-name>" \
  -F "EndpointCreationType=2" \
  -F "URL=tcp://${APP_HOST_IP}:9001" \
  -F "TLS=true" -F "TLSSkipVerify=true" -F "TLSSkipClientVerify=true"

# 4. Remove iptables block
ssh root@pve.gibbsgreatly.xyz "pct exec ${APP_HOST_VMID} -- \
  iptables -D INPUT -s 192.168.1.4 -p tcp --dport 9001 -j DROP"
```

Note: if legacy Portainer admin access is available, remove the endpoint from legacy first
(`DELETE /api/endpoints/<id>` via API). This is cleaner than the iptables block approach,
but the block works when legacy API access is unavailable.

After registering, verify each endpoint goes green. The `mgmt_seg → 192.168.1.0/24:9001`
routing was confirmed in place during testing — no MikroTik changes required.

Application hosts and LAN IPs:

| Endpoint name   | URL                      | VMID |
|---|---|---|
| `torrent-stack` | `tcp://192.168.1.5:9001` | TBD  |
| `media-stack`   | `tcp://192.168.1.6:9001` | TBD  |
| `gaming-stack`  | `tcp://192.168.1.7:9001` | TBD  |

These LAN bridge IPs are temporary — endpoint URLs will be updated to VLAN
addresses by the `portainer_api` role as each application-migration sprint runs.

### 4b. If edge agents — update join tokens on app hosts

Generate new edge keys in infrastructure Portainer for each endpoint.
On each application host update the portainer-agent config with the new
join token and restart the service. The agent will re-register with
infrastructure Portainer.

### 5. Re-create stacks in infrastructure Portainer

Option A (backup/restore) is not available — legacy is 2.33.6, infra is 2.27.3.
Restoring a newer-version backup into an older Portainer is incompatible.

**Option B — re-create stacks via API or UI**

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

### 8. Stop existing Portainer

Once all stacks are verified in infrastructure Portainer:
- Stop the Portainer container on management-stack: `docker stop portainer` (inside VMID 101)
- Confirm app stacks continue running (they're now managed by infrastructure Portainer,
  not by the management-stack Portainer)
- Leave the management-stack LXC (VMID 101) up — it still runs NPM and the central
  Docker registry, which are decommissioned in application-migration sprint 05
- Remove the old portainer DNS record if it points at 192.168.1.70 and there is
  no other service using that hostname

### 9. Commit, merge, and promote

There are no Terraform or Ansible code changes in this sprint (it is purely
an operational migration). Commit any runbook updates and close the branch:

```bash
git add docs/portainer-stack/
git commit -m "docs(portainer): complete migration runbook with verified commands"
```

Merge into `baseline/teardown-validated` after verifying all stacks are running
and the first post-migration backup has landed on the NAS.

No teardown cycle gate is required for a docs-only commit, but run one before
the next `baseline/teardown-validated` → `main` promotion to confirm the full
infrastructure still deploys cleanly with the migrated Portainer state.

---

## Pre-conditions

- [x] Sprint 01 complete: backup and restore validated (2026-06-19 — full destroy+apply+restore cycle confirmed)
- [ ] Existing Portainer admin password retrieved (not in SOPS — get from management-stack)
- [x] MikroTik rule: `mgmt_seg → 192.168.1.0/24:9001` in place (confirmed 2026-06-19 — no changes needed)
- [ ] Inventory of stacks and any Portainer-only secrets (step 2) complete before proceeding
- [x] Version compatibility confirmed: legacy 2.33.6 > infra 2.27.3, Option B (re-create stacks) only
