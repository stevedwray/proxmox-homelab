# authentik-stack — Stack Contract

## Purpose

Identity provider (IdP) and SSO gateway for the platform. Authentik provides:
- Forward-auth for Traefik-protected routes (Traefik calls Authentik's outpost
  before allowing requests through)
- OAuth2/OIDC for applications that delegate authentication

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `mgmt_seg` (VLAN 20)     |
| IP           | `${lab_ip_authentik}/24` |
| Gateway      | `${lab_gw_mgmt}`         |
| VMID         | 20010                    |

## Inputs

| Input                         | Source                              | Notes |
|-------------------------------|-------------------------------------|-------|
| `AUTHENTIK_SECRET_KEY`        | env var (mandatory)                 | Django secret key |
| `AUTHENTIK_POSTGRES_PASSWORD` | env var (mandatory)                 | DB password |
| `AUTHENTIK_SUPERUSER_PASSWORD`| env var (optional)                  | Initial admin password |
| `AUTHENTIK_SUPERUSER_API_TOKEN`| env var (optional)                 | For API-driven setup |
| `registry_host`               | generated host var                  | Harbor registry host injected via inventory |

**Current implementation:** the platform exposes `registry_host` as a generated host
var, and the playbook writes `REGISTRY_HOST` into the stack `.env` file so the
compose file expands `${REGISTRY_HOST}` without hardcoding environment-specific
Harbor addresses.

## Provides

| Service            | Port | Protocol | Notes |
|--------------------|------|----------|-------|
| Authentik server   | 9000 | HTTP     | Forward-auth endpoint, UI |
| Authentik server   | 443  | HTTPS    | Standard direct TLS endpoint for OIDC consumers |
| Authentik server   | 9443 | HTTPS    | TLS endpoint |

`stack.yaml` service identifiers: `authentik-http`, `authentik-https`.

These ports must be reachable from `edge_seg` (Traefik forward-auth) and from the
LAN for admin access. See `pve-test.yaml` policies:
`edge_seg → mgmt_seg tcp/9000,9443`. Port `443` is additionally used for direct
OIDC clients such as Technitium on the management segment.

## Dependencies

| Stack           | Why |
|-----------------|-----|
| harbor-stack    | All images pulled via `${REGISTRY_HOST}` |

## Persistent State

| Path              | Storage               | Contents |
|-------------------|-----------------------|----------|
| Docker volumes    | `docker_storage` (20 GiB) | PostgreSQL DB, media, certs, custom templates |

## What May Depend on This Stack

- Traefik (Phase 04): uses Authentik as forward-auth provider
- Any application protected by Authentik SSO

## What Must Not Be Edited Casually

- `AUTHENTIK_SECRET_KEY` must never change once the stack is deployed — it is used
  to encrypt session data and tokens. Rotation requires a full re-setup.
- The forward-auth middleware in Traefik routes traffic to `${lab_ip_authentik}:9000`.
  Changing the IP or port requires updating Traefik's dynamic config (`dynamic/authentik.yml` in proxy-stack).

## Playbook

`deploy-authentik-stack` (roles: `lxc_base`, `docker_base`; direct tasks for portainer-agent mask, compose deploy, health probe, and superuser/OIDC bootstrap)

`portainer_agent: false` is intentional; the portainer-agent systemd unit is masked during provisioning.
