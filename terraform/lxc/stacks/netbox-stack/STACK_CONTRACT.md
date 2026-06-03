# netbox-stack — Stack Contract

## Purpose

NetBox IPAM/DCIM application stack for the pve-test environment.
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
| `NETBOX_API_TOKEN` | env var | Preferred least-privilege automation token (non-superuser) |
| `NETBOX_SUPERUSER_PASSWORD` | env var | Initial admin password |
| `NETBOX_SUPERUSER_API_TOKEN` | env var | Legacy bootstrap superuser token (retained for bootstrap/backwards compatibility; avoid for day-2 automation) |
| `BREAKGLASS_PASSWORD` | env var | Optional local breakglass user password; defaults to superuser password if unset |
| `NETBOX_STEVE_USERNAME` | env var | Optional override for the managed local admin username |
| `NETBOX_STEVE_EMAIL` | env var | Optional override for the managed local admin email |
| `NETBOX_BREAKGLASS_USERNAME` | env var | Optional override for the local breakglass username |
| `NETBOX_BREAKGLASS_EMAIL` | env var | Optional override for the local breakglass email |
| `NETBOX_GUEST_SSH_USER` | env var | Non-root SSH user used by the external population container to inspect guests |
| `NETBOX_GUEST_SSH_IDENTITY_FILE` | env var | SSH private key path mounted into the external population container |
| `MIKROTIK_READONLY_USER` | env var | Read-only RouterOS API user for topology discovery |
| `MIKROTIK_READONLY_PASSWORD` | env var | Read-only RouterOS API password for topology discovery |
| `DOCKER_SOCKET_PROXY_URL_TEMPLATE` | env var | Preferred per-guest socket-proxy URL template. Use `{guest_ip}` as a placeholder for the discovered guest IP (e.g. http://{guest_ip}:2375). When set the collector resolves a proxy endpoint per Proxmox guest. |
| `DOCKER_SOCKET_PROXY_URL` | env var | Optional legacy single-endpoint base URL for a read-only docker-socket-proxy exposing the Docker API for runtime inspection (fallback only; e.g. http://10.57.3.12:2375) |
| `registry_host` | stack.yaml / env | Harbor registry host used by the compose stack |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through the stack metadata |
| `portainer_server_ip` | stack.yaml / env | Shared platform IP metadata |

No secret values are committed here. All sensitive values must come from the environment.

## DOCKER_SOCKET_PROXY Configuration Authority

For scheduled, production-style runs (the GitHub Actions scheduled job defined in `.github/workflows/netbox-populate.yml`), the `DOCKER_SOCKET_PROXY_URL_TEMPLATE` and `DOCKER_SOCKET_PROXY_URL` variables are expected to be supplied via GitHub Actions secrets (repository or organization level). The workflow explicitly maps these secrets into the job environment:

- `.github/workflows/netbox-populate.yml`: `DOCKER_SOCKET_PROXY_URL_TEMPLATE: ${{ secrets.DOCKER_SOCKET_PROXY_URL_TEMPLATE }}` and `DOCKER_SOCKET_PROXY_URL: ${{ secrets.DOCKER_SOCKET_PROXY_URL }}`

For operator-driven local or host-side execution (for example using `with-secrets-prod`), provide the same variables via the production SOPS overlay `terraform/secrets.pve.enc.yaml` (preferred for secret values) or as non-secret entries in `.env.pve`. `with-secrets-prod` injects the SOPS-backed production overlay into the command environment; it does not read GitHub Actions secrets. Do not commit `.env.pve` or plaintext secrets to the repository.

This ensures:

- CI/scheduled runs receive the proxy config from GitHub Actions secrets.
- Local/operator runs receive the proxy config from production SOPS or `.env.pve`.


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
 - Portainer is optional for operator convenience; base deployment and discovery are repo-driven under `/srv/docker/netbox` and do not require Portainer.
 - The recurring NetBox population job is external to the LXC and runs as a dedicated Docker container via `.github/workflows/netbox-populate.yml`.
 - Guest service inspection may currently use direct SSH to a non-root automation account as an interim fallback. The preferred long-term runtime discovery transport is read-only Docker API access via a `docker-socket-proxy` on Docker hosts/LXCs.

## Credential Expectations

**Proxmox**: Use a dedicated read-only API token scoped to discovery (node, guest list, config, storage, network) rather than full superuser credentials. Preferred environment variables for discovery are `PROXMOX_READONLY_TOKEN_ID` and `PROXMOX_READONLY_TOKEN_SECRET` (store the secret in `terraform/secrets.enc.yaml` or your secrets manager). For compatibility the discovery client will also accept `PROXMOX_TOKEN_ID` / `PROXMOX_TOKEN_SECRET` and `TF_VAR_pm_api_token_id` / `TF_VAR_pm_api_token_secret` as fallbacks if the preferred names are not present; operators should prefer the read-only names to make intent explicit.

**MikroTik**: Use a dedicated read-only RouterOS API user and password for topology discovery. Preferred environment variables are `MIKROTIK_READONLY_USER` and `MIKROTIK_READONLY_PASSWORD` (store the password in `terraform/secrets.enc.yaml` or your secrets manager). For compatibility the discovery client will also accept `MIKROTIK_USER` / `MIKROTIK_PASSWORD` as fallbacks if the preferred names are not present; operators should prefer the `MIKROTIK_READONLY_*` names to make intent explicit.

## Playbook

`deploy-netbox-stack` (roles: `lxc_base`, `docker_base`, `direct_stack`)

## Notes

- This is a data-centric special-case stack and is treated as a bounded exception in the Stage 7 refactor model.
- The current operator flow is: Terraform provisions the container and inventory, then Ansible prepares the host, deploys compose, and bootstraps the NetBox admin/API state.
