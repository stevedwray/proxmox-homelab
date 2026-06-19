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
- Application stack definitions — restored from NAS backup via `scripts/portainer-restore.sh`
- Application endpoints — portainer-agents keep running on their hosts; however, after a
  Portainer rebuild the agents are paired with the old (destroyed) instance. The restore script
  restores the DB including endpoint registrations. Agents reconnect automatically once Portainer
  is back at the same URL and the restored DB contains their endpoint record.

The full restore sequence is automated: `./with-secrets-prod scripts/portainer-restore.sh`
runs Phase 1 (deploy Portainer CE without init), restores the DB, then Phase 2 (init skip +
OAuth + backup timer). See [sprint 01 restore runbook](01-backup-restore.md#restore-runbook).

---

## Working in This Repo

### Branching

Every sprint runs on a short-lived branch cut from `baseline/teardown-validated`:

```bash
git checkout baseline/teardown-validated
git pull
git checkout -b task/portainer-backup-restore   # or task/portainer-migration
```

Never develop directly in `baseline/teardown-validated`. Merge back only after
the sprint's validation gate is satisfied (see each sprint doc). The merge target
is always `baseline/teardown-validated`, not `main`.

Promotion from `baseline/teardown-validated` to `main` happens separately after
a full teardown + redeploy cycle confirms the combined state is stable.

### Running commands against pve (production)

All commands that touch pve run through `./with-secrets-prod`, which loads
`terraform/secrets.pve.enc.yaml` and enforces production controls:

```bash
# Read-only — allowed by default
./with-secrets-prod pct config 20020
./with-secrets-prod scripts/provision.sh --stack portainer-stack  # plan/validate only

# Mutating — requires TASK_APPROVAL to be set first
export TASK_APPROVAL="portainer-backup-restore"
./with-secrets-prod scripts/provision.sh --stack portainer-stack
```

For a full teardown + redeploy cycle, `--disposable` bypasses the approval chain:

```bash
./with-secrets-prod scripts/teardown-deploy-test.sh --stack all --disposable
```

See [docs/reference/production-credentials.md](../reference/production-credentials.md)
and [docs/reference/secrets-management.md](../reference/secrets-management.md)
for the full model. The credential controls are also specified in `CLAUDE.md`.

### Validation tiers

Match validation depth to the change being made:

| Change | Minimum validation |
|---|---|
| Ansible comment / nosonar edit | `ansible-playbook --syntax-check` on affected playbooks |
| Ansible task or role change | `./with-secrets-prod scripts/provision.sh --stack portainer-stack` |
| New systemd unit or script | Provision and trigger manually, verify output |
| Terraform / bind-mount / LXC config | Full teardown + redeploy cycle |

Sprint promotion to `baseline/teardown-validated` requires a full teardown cycle
showing the complete stack (including the new backup timer) survives a rebuild.

---

## Sprint Plan

| Sprint | Goal | Status |
|---|---|---|
| [01](01-backup-restore.md) | Backup and restore from NAS — prove before migration | **complete** — validated 2026-06-19 |
| [02](02-migration.md) | Migrate application stacks from existing Portainer | **IaC ready** — test harness validated 2026-06-19; real migration pending |

Sprint 01 is complete. Sprint 02 IaC is in place (`migrate-portainer-stack.yml`); the real migration
runs when the legacy Portainer admin password is retrieved and the production approval workflow is followed.
