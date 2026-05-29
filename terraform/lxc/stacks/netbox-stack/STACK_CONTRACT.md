# netbox-stack — Stack Contract

## Purpose

NetBox IPAM/DCIM application stack for the segmented lab environment.
This stack provides the inventory and source-of-truth UI/API for lab hosts,
services, IPs, and related infrastructure metadata.

## Network

| Field | Value |
|---|---|
| Zone | `infra_seg` |
| IP | `${lab_ip_netbox}/24` |
| Gateway | `${lab_gw_infra}` |
| VMID | 40012 |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `NETBOX_DB_PASSWORD` | env var | NetBox PostgreSQL password |
| `NETBOX_REDIS_PASSWORD` | env var | Redis password for queue broker |
| `NETBOX_REDIS_CACHE_PASSWORD` | env var | Redis password for cache layer |
| `NETBOX_SECRET_KEY` | env var | Django secret key |
| `NETBOX_API_TOKEN_PEPPER` | env var | Pepper for API token generation |
| `NETBOX_SUPERUSER_PASSWORD` | env var | Initial admin password |
| `NETBOX_SUPERUSER_API_TOKEN` | env var | Automation token created during bootstrap |
| `BREAKGLASS_PASSWORD` | env var | Optional local breakglass user password; defaults to superuser password if unset |
| `NETBOX_STEVE_USERNAME` | env var | Optional override for the managed local admin username |
| `NETBOX_STEVE_EMAIL` | env var | Optional override for the managed local admin email |
| `NETBOX_BREAKGLASS_USERNAME` | env var | Optional override for the local breakglass username |
| `NETBOX_BREAKGLASS_EMAIL` | env var | Optional override for the local breakglass email |
| `registry_host` | stack.yaml / env | Harbor registry host used by the compose stack |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through the stack metadata |
| `portainer_server_ip` | stack.yaml / env | Shared platform IP metadata |

No secret values are committed here. All sensitive values must come from the environment.

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| NetBox HTTP | 8080 | TCP / HTTP | Primary application endpoint |

`stack.yaml` service identifier: `netbox-http`.

## Dependencies

- `harbor-stack` must be available for image pulls and registry access.

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/srv/docker/netbox` | LXC host filesystem / Docker compose project | Compose file, `.env`, and runtime stack files |
| `/srv/docker/netbox/configuration` | LXC host filesystem | NetBox configuration overlays (`configuration.py`, `extra.py`, `plugins.py`, `logging.py`) |
| Docker volumes from compose | Docker storage | NetBox application data, database data, Redis state |

## Generated Artifacts

Terraform materializes the stack inventory and SDN handoff artifacts.

Expected generated files include:

- `terraform/lxc/stacks/netbox-stack/inventory.yml`
- `terraform/lxc/stacks/netbox-stack/network-sdn-vars.yml`

## What May Depend on This Stack

- Any operator workflow that needs the NetBox API for inventory, IPAM, or DCIM updates.
- Any future reconciliation or population jobs that read from the NetBox API using the automation token created during bootstrap.

## What Must Not Be Edited Casually

- The Docker registry trust setting in `deploy-netbox-stack.yml` is intentional. The stack is expected to trust the Harbor HTTP registry host used in this lab.
- The `direct_stack` deployment path is shared with the compose stack and should stay aligned with the compose layout under `/srv/docker/netbox`.
- The local superuser/API-token bootstrap is part of the contract for this stack and must remain idempotent or explicitly non-fatal when run repeatedly.
- `portainer_agent: false` in this stack is intentional; NetBox does not publish a Portainer agent.

## Playbook

`deploy-netbox-stack` (roles: `lxc_base`, `docker_base`, `direct_stack`)

## Notes

- This is a data-centric special-case stack and is treated as a bounded exception in the Stage 7 refactor model.
- The current operator flow is: Terraform provisions the container and inventory, then Ansible prepares the host, deploys compose, and bootstraps the NetBox admin/API state.
