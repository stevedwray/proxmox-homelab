# 00b-pve-test-01 — Deploy Portainer bootstrap stack on bare-metal pve-test

## Status

COMPLETE

## Phase

Phase 00b — pve-test Management Bootstrap

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task assumes a **true greenfield laptop rebuild**:

- `pve-test` is bare-metal Proxmox VE
- the host storage layout exists
- no LXC template is assumed to exist yet
- no Portainer, Harbor, apt-cacher, NetBox, or other platform service is assumed to exist yet

## Prerequisites

- Phase 00a-01 complete — Proxmox host baseline applied, Terraform API token provisioned
- Phase 00a-02 complete — `mgmt_seg` SDN VLAN zone active on pve-test (`tvmgmt`, VLAN 20, `10.57.1.0/24`)
- Phase 00a-03 complete — Debian Docker LXC template exists in `storage-template`
- MikroTik route for `10.57.1.0/24 → 192.168.1.40` is active
- Storage pool `infrastructure-containers` exists on `pve-test`
- `.env` and `.env.pve-test` exist and set `TF_VAR_proxmox_node=pve-test`
- `PORTAINER_ADMIN_PASSWORD` exists in `.env`

## Network placement

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| VLAN | 20 |
| VNet | `tvmgmt` |
| IP | `10.57.1.20` |
| Gateway | `10.57.1.1` |
| VMID | 120 |

## Objective

LXC `portainer-stack` (VMID 120) is running on `pve-test` at `10.57.1.20` on `mgmt_seg`.
Portainer is reachable from the management network and provides the standalone management
endpoint for all later `pve-test` stacks.

## Browser ingress and certificate policy

Portainer is a browser-facing operator UI and must have an explicit Traefik ingress plan with
Let's Encrypt certificates for normal operator access.

- Canonical browser URL: `https://portainer.gibbsgreatly.xyz`
- Resolver policy: `certResolver: letsencrypt`
- Auth policy decision required: either direct Portainer auth only, or Traefik forward-auth
  middleware in front of Portainer (must be decided and documented before Phase 04 closeout)
- Direct IP access (`http://10.57.1.20:9000`) is bootstrap/debug only and not the steady-state
  browser entrypoint

Because this task executes before Traefik exists, it defines the ingress contract and required
outcome. Route implementation and cert issuance are completed once the Traefik stack is online.

## Scope

- Verify or create the Debian Docker LXC template needed by `terraform/lxc`
- Create or verify `terraform/lxc/stacks/portainer-stack/stack.yaml`
- Create or verify `terraform/lxc/stacks/portainer-stack/terragrunt.hcl`
- Create or verify `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
- Ensure `.env.template` contains a `PORTAINER_ADMIN_PASSWORD` placeholder
- Apply the stack and initialize the Portainer admin account
- Hand off to the `.env.pve-test` override step so later stacks register against the local Portainer

## Out of Scope

- Harbor deployment
- SDN VLAN zones
- Portainer image migration to Harbor proxy cache
- Any production `pve` resources

## Inputs

- [docs/plan/phase-00b-pve-test-management.md](/home/steve/git/proxmox-homelab/docs/plan/phase-00b-pve-test-management.md:1)
- `terraform/lxc/stacks/portainer-stack/`
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
- `.env`
- `.env.pve-test`

## Expected Outputs

- VMID 120 running on `pve-test`
- Portainer reachable at `http://10.57.1.20:9000`
- `PORTAINER_ADMIN_PASSWORD` used to initialize the admin user
- `.env.template` contains `PORTAINER_ADMIN_PASSWORD`

## Constraints and Conventions

- This task is allowed to pull `portainer/portainer-ce` directly from Docker Hub on the first pass
- Do not assume NetBox exists yet for IP allocation checks
- Portainer should expose the local Docker environment as an endpoint after bootstrap
- Safety check before apply:
  - `TF_VAR_proxmox_node=pve-test`
  - `TF_WORKSPACE=pve-test`

## Acceptance Criteria

- [x] Debian Docker template exists at `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz`
- [x] `terraform/lxc/stacks/portainer-stack/stack.yaml` exists and targets VMID 120 / `10.57.1.20`
- [x] `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` exists
- [x] `.env.template` contains `PORTAINER_ADMIN_PASSWORD`
- [x] `terragrunt apply` ownership for `portainer-stack` is present and `terragrunt plan -detailed-exitcode` returns 0
- [x] `curl -s http://10.57.1.20:9000/api/system/status` returns HTTP 200
- [x] Portainer admin login works with `PORTAINER_ADMIN_PASSWORD`
- [x] Portainer shows the local Docker environment as an endpoint
- [x] Follow-on environment configuration sets `TF_VAR_portainer_server_ip=10.57.1.20` in `.env.pve-test`
- [ ] Browser ingress contract documented for `portainer.gibbsgreatly.xyz` with LE cert requirement
- [ ] Traefik route and browser cert for Portainer validated once Traefik is deployed

## Completion Notes

- Verified live on 2026-04-16 against `pve-test.gibbsgreatly.xyz`.
- VMID 120 (`portainer-stack`) is running on bridge `tvmgmt` with IP `10.57.1.20/24`.
- Portainer API status returns HTTP 200 and reports version `2.27.3`.
- Admin authentication succeeds with `PORTAINER_ADMIN_PASSWORD`, and the `local` Docker
  endpoint exists at `unix:///var/run/docker.sock`.
- `terragrunt state list` confirms the stack is state-managed, and
  `terragrunt plan -detailed-exitcode -lock=false -no-color` returns exit code `0`
  after correcting the pve-test Proxmox token source.
- The original greenfield preflight step expecting `10.57.1.20` to be free no longer
  applies to the current live host; use this task as the canonical verification target
  for future rebuilds.

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy the bootstrap Portainer stack to a true-greenfield bare-metal pve-test laptop.
Assume only the host storage layout exists. Do not assume any LXC template or prior platform
services exist.

STEP 0 — Verify host target:
  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test
  echo "$TF_VAR_proxmox_node"   # must print pve-test
  echo "$TF_WORKSPACE"          # must print pve-test

STEP 0b — Verify required storages exist on pve-test:
  ssh root@pve-test.gibbsgreatly.xyz "pvesm status | egrep 'infrastructure-containers|storage-template'"

STEP 0c — Verify the Debian Docker template exists:
  ssh root@pve-test.gibbsgreatly.xyz "pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz"

If the template does not exist, stop and complete the template build/import path first.
Do not continue with this task until the template exists.

STEP 1 — Verify the bootstrap IP is free:
  ping -c 3 10.57.1.20
  # Expect no reply

STEP 2 — Ensure these files exist and match the active plan:
  - terraform/lxc/stacks/portainer-stack/stack.yaml
  - terraform/lxc/stacks/portainer-stack/terragrunt.hcl
  - terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

STEP 2b — Ensure .env.template includes:
  PORTAINER_ADMIN_PASSWORD=   # __FROM_BITWARDEN__

STEP 3 — Apply the stack:
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack
  terragrunt apply

STEP 4 — Run the playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.1.20," \
    terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

STEP 5 — Verify Portainer:
  curl -s http://10.57.1.20:9000/api/system/status
  # Expect HTTP 200 / JSON payload

  Confirm the local Docker environment appears in Portainer as an endpoint.

STEP 6 — Hand off to environment configuration:
  Set TF_VAR_portainer_server_ip=10.57.1.20 in .env.pve-test before deploying any later stack.

DONE WHEN: Portainer is up at 10.57.1.20:9000 and serves as the standalone management
endpoint for all later pve-test work.
```
