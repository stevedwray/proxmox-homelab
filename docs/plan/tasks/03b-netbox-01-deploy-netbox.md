# 03b-netbox-01 — Deploy NetBox IPAM on infra_seg

## Status

PENDING

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task deploys NetBox alongside Harbor and apt-cacher as one of the first services
on a fresh pve-test pass. All Phase 04 and later tasks rely on NetBox being available
for IP allocation verification before deploying any new container.

## Prerequisites

- Phase 00b complete — Portainer running at `10.57.1.20`, `infra_seg` SDN zone applied
- Harbor task (03b-harbor-01) complete — Harbor healthy at `10.57.3.10`
- Template `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz` exists
- Storage pool `infrastructure-containers` exists
- `NETBOX_SECRET_KEY` and `NETBOX_DB_PASSWORD` set in `.env`

## Network placement

| Field | Value |
|---|---|
| Zone | `infra_seg` |
| VLAN | 40 |
| VNet | `tvinfra` |
| IP | `10.57.3.12` |
| Gateway | `10.57.3.1` |
| VMID | 143 |
| Stack | `netbox-stack-test` |

## Objective

LXC `netbox-stack-test` (VMID 143) is running at `10.57.3.12` in `infra_seg`. The NetBox
web interface is accessible and an initial superuser exists. All subsequent Phase 03b, 03c,
and Phase 04 deployments record their IP allocations in NetBox before deploying.

## Scope

- Run `terragrunt apply` for `terraform/lxc/stacks/netbox-stack-test/`
- Run `deploy-netbox-stack.yml` Ansible playbook against the new LXC
- Create the initial NetBox superuser
- Seed the prefix `10.57.3.0/24` (infra_seg) in NetBox with existing allocations:
  - `10.57.3.10` — Harbor (VMID 121)
  - `10.57.3.11` — apt-cacher (VMID 142)
  - `10.57.3.12` — NetBox itself (VMID 143)
- Verify the UI is reachable at `http://10.57.3.12`

## Out of Scope

- Terraform provider integration for automated IPAM sync (future improvement, see Observations.md)
- DNS record management
- NetBox configuration for production `pve` node

## Inputs

- `terraform/lxc/stacks/netbox-stack-test/stack.yaml`
- `terraform/lxc/stacks/netbox-stack-test/terragrunt.hcl`
- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- `.env` / `.env.pve-test`

## Expected Outputs

- VMID 143 running at `10.57.3.12`
- NetBox UI accessible on port 80
- `infra_seg` subnets and existing IP allocations recorded
- All subsequent new LXC deployments record their IP in NetBox before applying

## Constraints and Conventions

- Source `.env` and `.env.pve-test` before any `terragrunt` command
- Verify `10.57.3.12` is free with `ping -c 3 10.57.3.12` before deploying
- `keyctl: true` is set in `stack.yaml` — required by the netbox-docker compose stack
- After deployment, always check NetBox (not just IPAM assumption) before assigning an
  IP to any new container in any zone

## Why this task belongs in Phase 03b

NetBox records what is allocated. Deploying it after Harbor and apt-cacher are already
running means retroactively entering those allocations — but that is acceptable. Deploying
it before Phase 04 means every new container from Authentik onward can be registered at
allocation time, which is the target practice.
