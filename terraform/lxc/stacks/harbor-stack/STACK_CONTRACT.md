# harbor-stack — Stack Contract

## Purpose

Private container registry and proxy cache for all Docker image pulls across the
platform. All stacks on pve-test pull images through Harbor rather than directly from
Docker Hub or GHCR. Harbor also runs the embedded Trivy scanner for image vulnerability
reporting.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40)    |
| IP           | `10.57.3.10/24`          |
| Gateway      | `10.57.3.1` (MikroTik)  |
| VMID         | 121                      |

## Inputs

| Input                 | Source                              | Notes |
|-----------------------|-------------------------------------|-------|
| `HARBOR_HOSTNAME`     | env var (mandatory)                 | FQDN for TLS cert and API calls |
| `PORTAINER_ADMIN_PASSWORD` | env var (mandatory)           | For Portainer agent registration |
| Portainer server      | `portainer_server_ip` in inventory  | `10.57.1.20` on pve-test |

## Provides

| Service          | Port | Protocol | Notes |
|------------------|------|----------|-------|
| Registry API     | 80   | HTTP     | Image pulls (HTTP, not HTTPS) |
| Registry API     | 443  | HTTPS    | Image pulls (HTTPS) |
| Harbor UI        | 80   | HTTP     | Web interface |
| Portainer agent  | 9001 | TCP      | Portainer server connects here |

`stack.yaml` service identifiers: `registry-http`, `registry-https`.

## Dependencies

| Stack           | Why |
|-----------------|-----|
| portainer-stack | Registers Portainer agent on startup |

Bootstrap note: on the first pass of a fresh pve-test node, Harbor itself pulls from
Docker Hub directly (Harbor is not yet running). All subsequent stacks pull from
`10.57.3.10`. This is expected and not a misconfiguration.

## Persistent State

| Path                 | Storage               | Contents |
|----------------------|-----------------------|----------|
| `/var/lib/harbor`    | extra mount (100 GiB) | Registry blobs, PostgreSQL DB, Redis, Trivy cache |

## What May Depend on This Stack

Every stack that uses Docker images.

**Target state:** active pve-test `docker-compose.yml` files should reference
`${REGISTRY_HOST}`, which resolves to `10.57.3.10`.

**Current state:** `authentik-stack` and the active NetBox compose path already
reference `${REGISTRY_HOST}` through generated inventory variables. Remaining Harbor
cleanup is now mostly about runtime consumers, production-path stacks, and broader
repo consistency rather than the active pve-test provisioning path.

## What Must Not Be Edited Casually

- The registry hostname (`HARBOR_HOSTNAME`) must match the TLS certificate.
- The extra mount path `/var/lib/harbor` must not be remapped — Harbor's
  `harbor.yml` hardcodes blob and DB paths under it.
- Trivy DB lives in `/var/lib/harbor` and is large; don't delete the extra mount
  without accounting for re-download time.

## Playbook

`deploy-harbor-stack` (roles: `lxc_base`, `docker_base`, `portainer_agent`,
`portainer_api`, `harbor_installer`, `harbor_postconfigure`)
