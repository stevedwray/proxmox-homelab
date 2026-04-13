# Phase 00b — pve-test Management Bootstrap

## Goal

Make `pve-test` a fully standalone deployment target before any higher-phase stack work
begins.

This phase exists to remove the old dependency on production `pve` services during
development passes. After this phase:

- `pve-test` has its own Portainer server
- later stacks register against the local Portainer endpoint
- the greenfield laptop build can proceed without relying on production infrastructure

## Why this phase matters

Without this phase, pve-test deployments inherit the old Portainer default and are not
isolated from production. That breaks the greenfield model, where the laptop is rebuilt
from scratch and validated independently.

## Greenfield assumptions

- `pve-test` is a bare-metal Proxmox laptop
- host storage is present
- the Debian Docker LXC template may need to be built or imported first
- no application or platform containers are assumed to exist yet

## Dependencies

- Phase 00 complete
- Phase 00a host bootstrap path available
- `vmbr0` available for bootstrap LAN connectivity
- `storage-template` and `infrastructure-containers` storage available on `pve-test`

## Deliverables

- local Portainer stack on `192.168.1.20` / VMID 120
- `TF_VAR_portainer_server_ip=192.168.1.20` in `.env.pve-test`
- active pve-test deployments no longer depend on `192.168.1.4`

## Live task docs

- [00b-pve-test-01 — Deploy Portainer bootstrap stack on bare-metal pve-test](tasks/00b-pve-test-01-deploy-portainer.md)
- [00b-pve-test-02 — Update pve-test environment isolation after Portainer bootstrap](tasks/00b-pve-test-02-update-env-isolation.md)

## Out of Scope

- Harbor deployment
- ci-runner deployment
- SDN VLAN-zone service placement beyond the Portainer bootstrap exception

## Acceptance Criteria

- [ ] Portainer is running locally on `pve-test` at `192.168.1.20`
- [ ] Admin login works with `PORTAINER_ADMIN_PASSWORD`
- [ ] `.env.pve-test` exports `TF_VAR_portainer_server_ip=192.168.1.20`
- [ ] Subsequent pve-test stack deploys target the local Portainer server
- [ ] Production Portainer is not required for any later pve-test work

## Notes

- Portainer is the permanent bootstrap exception on flat LAN `vmbr0`
- All later stack work should follow the phase/task docs rather than the archived `done/`
  runbooks
