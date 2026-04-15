# netbox-stack-test — Stack Contract

## Purpose

IPAM and DCIM for the pve-test environment. Tracks IP allocations, prefixes,
VLAN assignments, and device records for all containers deployed on pve-test.
Deployed early in Phase 03b alongside Harbor so that Phase 04 and beyond can record
allocations at deployment time rather than retroactively.

Note: this is the **pve-test** instance. The production NetBox at `192.168.1.30` on
pve is a separate stack (`netbox-stack`).

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40)    |
| IP           | `10.57.3.12/24`          |
| Gateway      | `10.57.3.1` (MikroTik)  |
| VMID         | 143                      |

## Inputs

| Input                       | Source      | Notes |
|-----------------------------|-------------|-------|
| `NETBOX_SECRET_KEY`         | env var     | Django secret key |
| `NETBOX_SUPERUSER_PASSWORD` | env var     | Initial admin password |
| `NETBOX_DB_PASSWORD`        | env var     | PostgreSQL password |
| Harbor registry             | `registry_host` (`10.57.3.10`) | Image pulls via proxy cache |
| Portainer server            | `portainer_server_ip` (`10.57.1.20`) | Agent registration |

Special: requires `keyctl: true` in `stack.yaml` because netbox-community's
Docker image uses kernel keyring for secret storage.

## Provides

| Service      | Port | Protocol | Notes |
|--------------|------|----------|-------|
| NetBox UI    | 8080 | HTTP     | Web interface and REST API |
| NetBox API   | 8080 | HTTP     | `/api/` prefix |

## Dependencies

| Stack         | Why |
|---------------|-----|
| harbor-stack  | All container images pulled via `10.57.3.10` |
| portainer-stack | Registers Portainer agent |

## Persistent State

| Path              | Storage               | Contents |
|-------------------|-----------------------|----------|
| Docker volumes    | `docker_storage` (32 GiB) | PostgreSQL DB, media files |

## What May Depend on This Stack

- Operators and scripts that need to verify IP availability before allocation
- Future Terraform automation via `netbox-community/terraform-provider-netbox`
  (not yet implemented; see Observations.md Phase 03b note 1)

## What Must Not Be Edited Casually

- The database volume must not be deleted without a prior export/backup — all IPAM
  records are stored there.
- `keyctl: true` in `stack.yaml` is required; removing it will break the
  deployment.

## Playbook

`deploy-netbox-stack` (roles: `lxc_base`, `docker_base`, `portainer_agent`,
`portainer_api`, `app_stack`)
