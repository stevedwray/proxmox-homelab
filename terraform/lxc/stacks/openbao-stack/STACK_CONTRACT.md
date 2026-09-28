# openbao-stack — Stack Contract

## Purpose

Authoritative secrets store for the homelab (OpenBao, the open-source Vault
fork). Replaces Git-tracked SOPS files as the source of secret values. See
`docs/secrets-refactor/secrets-design.md` for the design and
`docs/secrets-refactor/plan.md` for how it is built.

## Network

| Field   | Value                 |
|---------|-----------------------|
| Zone    | `mgmt_seg` (VLAN 20)  |
| IP      | `192.168.20.16/24`    |
| Gateway | `${lab_gw_mgmt}`      |
| VMID    | 20016                 |

## Inputs

| Input                          | Source              | Notes |
|--------------------------------|---------------------|-------|
| `LAB_IP_OPENBAO`               | `.env`              | API address used by every client |
| `LAB_FQDN_OPENBAO`             | `.env`              | UI hostname (through Traefik); also a cert SAN |
| `STEP_CA_PROVISIONER_PASSWORD` | secrets (deploy-time only) | Initial cert issuance; deleted from the host afterwards |
| Seal key                       | USB stick on `pve`, bind mount `/srv/openbao-seal` | 32-byte static seal key, read-only |
| apt-cacher                     | `apt_cacher_host:3142` | apt proxy during provisioning |

## Provides

| Service       | Port | Protocol | Notes |
|---------------|------|----------|-------|
| `openbao-api` | 8200 | HTTPS    | API + UI. Machines call it directly by IP; humans use `https://openbao.${LAB_DOMAIN}` via Traefik |

`stack.yaml` service identifier: `openbao-api`.

## Dependencies

| Stack            | Why |
|------------------|-----|
| apt-cacher-stack | apt proxy for base package installs |
| step-ca-stack    | Listener TLS certificate (issue at deploy, `step ca renew` daily) |

Not a dependency: Harbor (no Docker images), Portainer (no agent),
Authentik and Traefik (UI login only; the API path never touches them).

## Persistent State

| Path                    | Contents |
|-------------------------|----------|
| `/opt/openbao/data`     | Integrated Raft storage (encrypted by the seal key) |
| `/etc/openbao/tls/`     | step-ca listener cert and key |
| `/var/log/openbao/`     | Audit log (logrotate, 30 days) |
| `/etc/openbao-snapshot/`| Snapshot AppRole role-id/secret-id (root 0600, placed by the operator) |
| `/srv/openbao-seal`     | Bind mount, read-only: USB seal key. Never in backups |
| `/srv/openbao-snapshots`| Bind mount: NAS directory for Raft snapshots |

## What must not be edited casually

- `seal "static"` key id and path in `openbao.hcl`: changing the key without
  the `previous_key` rotation procedure makes the data unreadable.
- Nothing in this stack may depend on a secret stored in OpenBao itself
  (bootstrap kit, design doc 9.1).
