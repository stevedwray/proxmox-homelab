# apt-cacher-stack — Stack Contract

## Purpose

Transparent apt proxy for all LXC containers on pve-test. Every container's
`lxc_base` role configures `/etc/apt/apt.conf.d/01proxy` to point at this service
so that repeated `apt-get install` runs during development passes hit a local cache
rather than the upstream Debian mirrors.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40)    |
| IP           | `10.57.3.11/24`          |
| Gateway      | `10.57.3.1` (MikroTik)  |
| VMID         | 142                      |

## Inputs

None. apt-cacher-ng requires no secrets or upstream service references at startup.
The only runtime input is HTTP CONNECT requests from apt clients.

## Provides

| Service       | Port | Protocol | Notes |
|---------------|------|----------|-------|
| apt proxy     | 3142 | HTTP     | Debian/Ubuntu package cache |

`stack.yaml` service identifier: `apt-proxy`.

The `all_zones → infra_seg tcp/3142` firewall policy means every zone can reach
this service without additional MikroTik rules.

## Dependencies

None. apt-cacher-stack is a foundation service with no upstream service dependencies.
It must be deployed before any other stack that runs `apt-get` during provisioning.

## Persistent State

| Path              | Storage               | Contents |
|-------------------|-----------------------|----------|
| Docker volume     | `docker_storage` (20 GiB) | Cached `.deb` packages |

## What May Depend on This Stack

Every other stack (via `lxc_base` role apt proxy configuration).

## What Must Not Be Edited Casually

- The port (3142) is baked into every container's `/etc/apt/apt.conf.d/01proxy`.
  Changing it requires re-running `lxc_base` on all containers.
- The `apt_cacher_host` variable used by `lxc_base` must match this container's IP.
  On pve-test: `10.57.3.11`. On pve: `192.168.1.35`.

## Playbook

`deploy-apt-cacher-stack`

## Stage 4 Exemplar Scaffolding Hooks

### Day-1 To Day-2 Handoff

- identify generated handoff artifacts consumed by day-2 reconcile workflows
- keep ownership boundaries explicit between Terraform-managed and Ansible-managed state

### Reconcile Entry Expectations

- define approval-aware post-infra reconcile entrypoint expectations
- document minimal evidence to confirm hook wiring for Stage 5
