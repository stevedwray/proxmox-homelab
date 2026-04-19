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
| Stack | `netbox-stack` |

## Objective

LXC `netbox-stack` (VMID 143) is running at `10.57.3.12` in `infra_seg`. The NetBox
web interface is accessible and an initial superuser exists. All subsequent Phase 03b, 03c,
and Phase 04 deployments record their IP allocations in NetBox before deploying.

## Browser ingress and certificate policy

NetBox is a browser-facing operator UI and must have a Traefik ingress route with
Let's Encrypt certificates.

- Canonical browser URL: `https://netbox.gibbsgreatly.xyz`
- Resolver policy: `certResolver: letsencrypt`
- Auth policy: **Authentik forward-auth** — Traefik intercepts browser requests and requires an
  active Authentik session before proxying. NetBox native auth remains active for API token
  access; forward-auth gates the browser UI only.
- Direct IP access (`http://10.57.3.12`) is bootstrap/debug only and not the steady-state URL

Route wiring is implemented in task `04-core-services-06-browser-ingress-wiring`.

## Scope

- Run `terragrunt apply` for `terraform/lxc/stacks/netbox-stack/`
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

- `terraform/lxc/stacks/netbox-stack/stack.yaml`
- `terraform/lxc/stacks/netbox-stack/terragrunt.hcl`
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

## Acceptance Criteria

- [ ] VMID 143 running at `10.57.3.12`
- [ ] NetBox UI reachable at `http://10.57.3.12` (port 8080) for bootstrap validation
- [ ] `infra_seg` subnets and existing IP allocations recorded
- [ ] Browser ingress contract documented for `netbox.gibbsgreatly.xyz` with LE cert requirement
- [ ] Traefik route and browser cert for NetBox validated (task 04-core-services-06)

## Why this task belongs in Phase 03b

NetBox records what is allocated. Deploying it after Harbor and apt-cacher are already
running means retroactively entering those allocations — but that is acceptable. Deploying
it before Phase 04 means every new container from Authentik onward can be registered at
allocation time, which is the target practice.
