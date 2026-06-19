# Portainer Stack — Overview

Infrastructure Portainer manages **application stacks only** (torrent, media, gaming).
Infrastructure stacks (Harbor, NetBox, Authentik, Monitoring, etc.) are deliberately
isolated from Portainer for security reasons — portainer-agent is masked on all
infrastructure LXCs.

---

## Location

| | |
|---|---|
| VMID | 20020 |
| Zone | mgmt_seg (192.168.20.20) |
| URL | https://management-stack.gibbsgreatly.xyz:9443 |
| Auth | Authentik OIDC + local admin breakglass |

---

## Security Boundary

Infrastructure stacks have `portainer-agent.service` masked at provision time.
They are not visible to Portainer and cannot be managed through it.

Application LXCs (dl_seg, media_seg, game_seg) run portainer-agent and register
as endpoints with the infrastructure Portainer. Portainer owns their stack lifecycle:
compose deployment, start/stop, image updates, environment config.

See [application-migration/00-overview.md](../application-migration/00-overview.md)
for the Portainer ownership model and per-sprint detail.

---

## Agent Model

Application hosts use **regular portainer-agent** (port 9001). Portainer connects
inbound to agents. This is implied by the pre-condition in application-migration:
`mgmt_seg → <zone>:9001` MikroTik rule.

Edge agent model (agent dials out to Portainer) is not in use. Verify on migration
by checking Environments tab in the existing Portainer — type column shows
"Agent" or "Edge Agent".

---

## Credentials

| Credential | Storage | Notes |
|---|---|---|
| Admin password | SOPS `secrets.pve.enc.yaml` | Re-applied on every provision |
| Portainer API token | Optional in SOPS | netbox-populate falls back to admin password auth if not set |
| Harbor registry config | Provisioned via portainer_api role | Auto-reprovisioned |
| Authentik OAuth | Provisioned | Auto-reprovisioned |

`PORTAINER_TOKEN` in SOPS is optional — `PortainerClient` falls back to
`PORTAINER_ADMIN_PASSWORD` if no API key is present. A Portainer rebuild does
not break netbox-populate discovery.

---

## Rebuild Behaviour

On full teardown + rebuild:
- Admin password, Harbor registry, Authentik OAuth — auto-reprovisioned by Ansible
- Application stack definitions — restored from NAS backup (see sprint 01)
- Application endpoints — portainer-agents keep running and reconnect automatically
  once Portainer is back at the same URL

---

## Sprint Plan

| Sprint | Goal | Status |
|---|---|---|
| [01](01-backup-restore.md) | Backup and restore from NAS — prove before migration | planned |
| [02](02-migration.md) | Migrate application stacks from existing Portainer | planned |

Sprint 01 must complete and be validated before sprint 02 begins.
