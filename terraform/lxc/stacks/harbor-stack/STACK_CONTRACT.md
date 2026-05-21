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
| IP           | `${lab_ip_harbor}/24`    |
| Gateway      | `${lab_gw_infra}`        |
| VMID         | 40010                    |

## Inputs

| Input                 | Source                              | Notes |
|-----------------------|-------------------------------------|-------|
| `HARBOR_HOSTNAME`     | env var (mandatory)                 | FQDN for TLS cert and API calls |

## Provides

| Service          | Port | Protocol | Notes |
|------------------|------|----------|-------|
| Registry API     | 80   | HTTP     | Image pulls (HTTP, not HTTPS) |
| Registry API     | 443  | HTTPS    | Image pulls (HTTPS) |
| Harbor UI        | 80   | HTTP     | Web interface |

`stack.yaml` service identifiers: `registry-http`, `registry-https`.

## Dependencies

Bootstrap note: on the first pass of a fresh pve-test node, Harbor itself pulls from
Docker Hub directly (Harbor is not yet running). All subsequent stacks pull from
`${REGISTRY_HOST}` (injected from `registry_host` host vars). This is expected and
not a misconfiguration.

## Persistent State

| Path                 | Storage               | Contents |
|----------------------|-----------------------|----------|
| `/var/lib/harbor`    | extra mount (100 GiB) | Registry blobs, PostgreSQL DB, Redis, Trivy cache |

## What May Depend on This Stack

Every stack that uses Docker images.

**Target state:** active pve-test `docker-compose.yml` files should reference
`${REGISTRY_HOST}` (the `registry_host` generated inventory variable).

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

`deploy-harbor-stack` (roles: `lxc_base`, `docker_base`, `harbor_installer`, `harbor_postconfigure`)

`portainer_agent: false` is intentional; the portainer-agent systemd unit is masked during provisioning.
