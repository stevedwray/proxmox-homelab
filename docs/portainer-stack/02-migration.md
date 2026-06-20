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

### 4a. If regular agents — migrate via Ansible playbook

**Agent pairing constraint (validated 2026-06-19):** A portainer-agent can only be paired
with ONE Portainer server at a time. Pairing state lives in the container's writable layer.
`docker restart` does NOT clear it. Legacy Portainer polls continuously and reconnects
within seconds of an agent restart, winning any naive race.

The migration playbook (`migrate-portainer-stack.yml`) handles this automatically:
it blocks legacy Portainer's IP while resetting the agent and registering with infra
Portainer, then unblocks.

**Per-host stack.yaml** must declare `portainer_stacks` (compose files to deploy) and
optionally `portainer_migration_legacy_ip` (default: `192.168.1.4`):

```yaml
# terraform/lxc/stacks/<name>/stack.yaml
ansible_playbook: "deploy-portainer-agent"
portainer_agent: true
portainer_stacks:
  - name: <stack-name>
    compose_file: docker-compose.yml   # relative to the stack directory
```

**Run migration:**

```bash
export TASK_APPROVAL="portainer-migration"
./with-secrets-prod scripts/provision.sh --stack <name> \
  --playbook terraform/lxc/ansible/playbooks/migrate-portainer-stack.yml
```

Or directly with ansible-playbook:

```bash
source .env
ansible-playbook \
  -i terraform/lxc/stacks/<name>/inventory.yml \
  terraform/lxc/ansible/playbooks/migrate-portainer-stack.yml \
  -e "@/tmp/<name>.ansible-extra-vars.yml"
```

If legacy Portainer admin access is available, remove the endpoint from legacy first
(`DELETE /api/endpoints/<id>`) — this stops legacy polling and makes the iptables block
unnecessary. The playbook works either way.

`mgmt_seg → 192.168.1.0/24:9001` routing confirmed in place — no MikroTik changes required.

Application hosts and LAN IPs:

| Stack yaml  | Endpoint name   | Agent URL                | VMID | Stacks |
|---|---|---|---|---|
| `torrent-stack` | `torrent-stack` | `tcp://192.168.1.5:9001` | 100 | torrent-stack (gluetun + qbittorrent + arr suite) |
| `media-stack`   | `media-stack`   | `tcp://192.168.1.6:9001` | 102 | jellyfin |
| `gaming-stack`  | `gaming-stack`  | `tcp://192.168.1.7:9001` | 103 | foreverworld, testworld, dayz, newworld |
| `analysis-stack` | `analysis-stack` | `tcp://192.168.1.16:9001` | 110 | (no stacks — agent only) |
| `security-stack` | `security-stack` | `tcp://192.168.1.11:9001` | 109 | (no stacks — agent only) |

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

**Option B — re-create stacks via IaC (automated)**

The `portainer_stack` Ansible role deploys stacks idempotently via the Portainer API
as part of the migration playbook (task 4a). Compose files must be committed to the
repo under each stack's directory before running the playbook.

For each application host before running the migration:
1. Commit the compose file to `terraform/lxc/stacks/<name>/docker-compose.yml`
2. Declare it in `stack.yaml` under `portainer_stacks`
3. Add any environment variables under `portainer_stacks[].env` (from SOPS where
   available, from manual notes in step 2 for Portainer-only secrets)

The playbook then deploys stacks automatically during endpoint registration. Stacks
already present on the endpoint are skipped (idempotent).

### 6. Verify stacks are running

Do one host at a time. Verify each host fully before migrating the next —
this limits any split state to a single host if something goes wrong.

**Per-host verification checklist:**

```bash
# 1. Confirm endpoint is online in infra Portainer
JWT=$(curl -sf http://192.168.20.20:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Calm4-Scrap-Seventy"}' | jq -r .jwt)

curl -sf http://192.168.20.20:9000/api/endpoints \
  -H "Authorization: Bearer $JWT" \
  | jq '[.[] | {Name, Status, URL}]'
# Status 1 = online

# 2. Confirm stack is running on the endpoint
curl -sf http://192.168.20.20:9000/api/stacks \
  -H "Authorization: Bearer $JWT" \
  | jq '[.[] | select(.Name=="<stack-name>") | {Name, Status, EndpointId}]'
# Status 1 = running

# 3. Confirm containers are up on the host itself
ssh root@pve.gibbsgreatly.xyz "pct exec <vmid> -- docker ps --format 'table {{.Names}}\t{{.Status}}'"

# 4. Check recent container logs for errors
ssh root@pve.gibbsgreatly.xyz "pct exec <vmid> -- docker compose -f /opt/<stack>/docker-compose.yml logs --tail=50"
```

**Per-stack spot-checks:**

| Stack | Check |
|---|---|
| torrent-stack | qBittorrent WebUI at `http://192.168.1.5:8080` — confirm gluetun VPN is up (check gluetun logs for `healthy`) |
| media-stack (jellyfin) | Jellyfin UI at `http://192.168.1.6:8096` — confirm library is intact |
| gaming-stack | Check each game server port is listening: `nc -zv 192.168.1.7 25566` (Minecraft), `25567` (testworld), `2302` (DayZ UDP) |
| analysis-stack | Confirm relevant containers are running via `docker ps` |
| security-stack | Confirm relevant containers are running via `docker ps` |

**Log check via Loki (if Promtail is running on the host):**

```bash
# Query recent logs for a host — look for errors or restarts
curl -G "http://192.168.20.12:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={host="<hostname>"} |= "error"' \
  --data-urlencode "start=$(date -d '5 minutes ago' +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000" \
  | jq '.data.result[].values[][1]'
```

**Confirm legacy Portainer no longer manages the endpoint:**

After successful migration, the endpoint should show as offline or absent in
legacy Portainer (`http://192.168.1.4:9000`). Verify with the API token:

```bash
./with-secrets bash -c '
curl -sf -H "X-API-Key: $PORTAINER_TOKEN" http://192.168.1.4:9000/api/endpoints \
  | jq "[.[] | select(.Name==\"<stack-name>\") | {Name, Status}]"'
# Status 2 = offline (agent no longer paired with legacy)
```

---

## Back-out Procedure

Application services are never stopped during migration — only the portainer-agent
container is reset. Back-out is therefore safe to run at any point without
disrupting running services.

### Per-host back-out

If a migration fails or a stack cannot be verified, back out the affected host:

```bash
# On the application host (via pct exec or SSH)
ssh root@pve.gibbsgreatly.xyz "pct exec <vmid> -- bash -c '
  # Remove iptables block if the playbook left it in place
  iptables -D INPUT -s 192.168.1.4 -p tcp --dport 9001 -j DROP 2>/dev/null || true

  # Reset agent — legacy Portainer reconnects within ~3 seconds
  cd /opt/portainer-agent && docker compose down && docker compose up -d
'"
```

Legacy Portainer polls continuously. Once the agent container is fresh,
legacy Portainer reclaims it automatically.

### After back-out

- Confirm the endpoint shows Status 1 in legacy Portainer
- Confirm the endpoint shows Status 2 (offline) in infra Portainer, then
  delete the stale endpoint from infra Portainer via the UI or:

```bash
curl -sf -X DELETE http://192.168.20.20:9000/api/endpoints/<endpoint-id> \
  -H "Authorization: Bearer $JWT"
```

- Diagnose the failure before retrying (missing env vars, compose issue,
  network reachability) — do not retry blind

### Failure modes and responses

| Failure | Response |
|---|---|
| Agent won't start after `docker compose up` | Check compose file and image availability on the host; back-out not needed since legacy will reconnect once agent is up |
| Infra Portainer can't reach agent (endpoint stays Status 2) | Check `mgmt_seg → 192.168.1.x:9001` routing; verify agent is listening on port 9001 |
| Stack fails to deploy (compose error) | Containers are still running; fix compose in infra Portainer and redeploy; no back-out needed |
| Stack deploys but service is unhealthy | Check container logs; app data is on host volumes and untouched; fix config and restart stack |
| Multiple hosts in bad state | Run per-host back-out on each; legacy Portainer resumes control |

---

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

- [x] Sprint 01 complete: backup and restore validated (2026-06-19 — full destroy+apply+restore cycle confirmed, re-validated 2026-06-20 with stacks and endpoints in backup)
- [x] Legacy Portainer API access confirmed: `PORTAINER_TOKEN` in SOPS is valid (verified 2026-06-20)
- [x] MikroTik rule: `mgmt_seg → 192.168.1.0/24:9001` in place (confirmed 2026-06-19 — no changes needed)
- [x] Stack inventory complete (2026-06-20): compose files retrieved, no Portainer-stored secrets on migration targets
- [x] Version compatibility confirmed: legacy 2.33.6 > infra 2.27.3, Option B (re-create stacks) only
- [ ] DayZ Steam credentials (`USERNAME`, `PASSWRD`) moved to SOPS before committing `gaming-stack/docker-compose.yml`
- [ ] Compose files committed to repo for each migration target
- [ ] VMIDs confirmed: torrent-stack=100, media-stack=102, gaming-stack=103, analysis-stack=110, security-stack=109
