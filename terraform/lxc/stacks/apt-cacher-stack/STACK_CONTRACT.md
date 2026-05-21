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
| IP           | `${lab_ip_apt_cacher}/24`|
| Gateway      | `${lab_gw_infra}`        |
| VMID         | 40011                    |

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
  It should track `${lab_ip_apt_cacher}` for the active environment.

## Playbook

`deploy-apt-cacher-stack`

This stack is deployed as a direct systemd-managed host service (package install +
service unit), not a Docker Compose workload.
