# step-ca-stack — Stack Contract

## Purpose

Internal certificate authority for the homelab PKI. Issues TLS certificates to
internal services via the ACME protocol (`httpChallenge`). Traefik uses this CA
as its ACME provider so that all internal services get trusted certs from the
homelab root CA rather than self-signed or public certificates.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `mgmt_seg` (VLAN 20)     |
| IP           | `${lab_ip_step_ca}/24`   |
| Gateway      | `${lab_gw_mgmt}`         |
| VMID         | 152                      |

## Inputs

| Input                           | Source                    | Notes |
|---------------------------------|---------------------------|-------|
| `STEP_CA_PASSWORD`              | env var (mandatory)       | Root CA key passphrase |
| `STEP_CA_PROVISIONER_PASSWORD`  | env var (mandatory)       | ACME provisioner passphrase |
| `PROXMOX_HOST`                  | env var (default: `pve-test.gibbsgreatly.xyz`) | Host to trust the root CA on |
| apt-cacher                      | `apt_cacher_host:3142`    | apt proxy during provisioning |

Note: step-ca installs binaries directly from GitHub releases (not Docker). It does
**not** pull from Harbor. The `lxc_base` role still needs apt-cacher for package
installs (`ca-certificates`, `curl`, `tar`).

## Provides

| Service            | Port | Protocol | Notes |
|--------------------|------|----------|-------|
| step-ca ACME       | 443  | HTTPS    | ACME challenge endpoint |
| step-ca health     | 443  | HTTPS    | `step ca health` check |

`stack.yaml` service identifier: `step-ca-acme`.

The ACME `httpChallenge` requires step-ca to reach Traefik on port 80 to verify
domain ownership. MikroTik policy required: `mgmt_seg → edge_seg tcp/80`.
See Observations.md Phase 04 note 5.

## Dependencies

| Stack         | Why |
|---------------|-----|
| apt-cacher-stack | apt proxy for base package installs |

step-ca has no dependency on Harbor (no Docker images) or Portainer (no agent).

## Persistent State

| Path              | Contents |
|-------------------|----------|
| `/etc/step-ca/`   | Root CA key, intermediate key, provisioner config, `ca.json` |
| `certs/homelab-root.crt` | Root cert fetched to `certs/` in this repo after init |

The root CA private key at `/etc/step-ca/secrets/` must never leave the LXC
container (except for backup purposes). The root cert (`root_ca.crt`) is safe to
distribute and is committed to the repo under `certs/`.

## What May Depend on This Stack

- Traefik (Phase 04): uses step-ca as ACME provider
- Any internal service that needs a TLS cert from the homelab CA

## What Must Not Be Edited Casually

- `ca.json` is generated once by `step ca init`. Do not overwrite it — regenerating
  it creates a new root CA and invalidates all issued certificates.
- The step-ca version must remain pinned. Updates require careful migration.
- Managed as a systemd service, not Docker. `portainer_agent: false` is explicitly set in
  `stack.yaml` — there are no containers to manage.

## Playbook

`deploy-step-ca` (roles: `lxc_base`; binary install via direct tasks)
