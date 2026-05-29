# portainer-stack — Stack Contract

## Purpose

Container management UI and agent registration hub for the pve-test node.
Portainer CE runs as the central server; all other Docker-capable stacks register
a Portainer agent so that their containers are visible and manageable from one UI.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `mgmt_seg` (VLAN 20)     |
| IP           | `${lab_ip_portainer}/24`          |
| Gateway      | `${lab_gw_mgmt}`         |
| VMID         | 20020                    |

## Inputs

| Input                       | Source      | Notes |
|-----------------------------|-------------|-------|
| `PORTAINER_ADMIN_PASSWORD`  | env var     | Initial admin password |

No Harbor dependency: Portainer CE and its agent images must be pulled from Docker
Hub (or a pre-seeded Harbor cache) because Portainer is deployed before Harbor on a
fresh pass. Use explicit version-pinned tags, not `latest`.

## Provides

| Service               | Port | Protocol | Notes |
|-----------------------|------|----------|-------|
| Portainer UI          | 9000 | HTTP     | Web interface |
| Portainer UI (TLS)    | 9443 | HTTPS    | Web interface |
| Agent tunnel endpoint | 8000 | TCP      | Edge agent communication |

`stack.yaml` service identifiers: `portainer-http`, `portainer-https`,
`portainer-edge`.

Other stacks register their agents at port 9000 using `portainer_server_ip`.

## Dependencies

None. Portainer is a foundation service deployed before all other stacks. It does
not depend on Harbor (see Inputs above) or any other stack.

## Persistent State

| Path              | Storage               | Contents |
|-------------------|-----------------------|----------|
| Docker volume     | `docker_storage` (10 GiB) | Portainer DB, TLS certs, agent state |

## What May Depend on This Stack

All stacks with `portainer_agent: true` in their `stack.yaml` depend on this stack
being reachable at `${lab_ip_portainer}:9000` during their Ansible provisioning play. The
`portainer_api` role registers the agent endpoint; the `portainer_agent` role starts
the agent container.

## What Must Not Be Edited Casually

- Portainer agent and server **must run the same major/minor version**. Mismatched
  versions cause TLS handshake failures and cross-instance pairing locks.
  See Observations.md Phase 03b note 8 for the full failure mode.
- `portainer_agent: false` in this stack's `stack.yaml` is intentional — the server
  does not register itself as its own agent.

## Playbook

`deploy-portainer-stack` (roles: `lxc_base`, `docker_base`)
