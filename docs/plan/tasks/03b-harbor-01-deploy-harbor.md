# 03b-harbor-01 — Deploy Harbor registry stack on infra_seg

## Status

COMPLETE

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task assumes the laptop is being built from scratch. The only platform dependency that
must already exist is the Phase 00b bootstrap path on `pve-test`, including the Debian
Docker template and Portainer.

## Prerequisites

- Phase 00a complete — host bootstrap path available
- Phase 00b complete — Portainer running at `10.57.1.20`
- Storage pool `infrastructure-containers` exists
- Template `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz` exists
- MikroTik VLANs and routes for `infra_seg` are configured
- `vmbr0` is VLAN-aware on `pve-test`
- Proxmox SDN VLAN zones have been applied manually on `pve-test`
- `HARBOR_ADMIN_PASSWORD` exists in `.env`

## Network placement

| Field | Value |
|---|---|
| Zone | `infra_seg` |
| VLAN | 40 |
| VNet | `tvinfra` |
| IP | `10.57.3.10` |
| Gateway | `10.57.3.1` |
| VMID | 121 |

## Objective

LXC `harbor-stack` (VMID 121) is running at `10.57.3.10` in `infra_seg` and responds to
the Harbor API. This is the first registry in the greenfield build and becomes the image
source for all later Phase 03c/04/05 tasks.

## Scope

- Verify SDN prerequisites for `infra_seg`
- Create or verify `terraform/lxc/stacks/harbor-stack/stack.yaml`
- Create or verify `terraform/lxc/stacks/harbor-stack/terragrunt.hcl`
- Create or verify `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- Apply the Harbor LXC and run the stack playbook

## Out of Scope

- Harbor postconfigure work (proxy caches, robot account, GC, project setup)
- Pre-pulling Phase 04 images
- NetBox deployment

## Inputs

- [docs/plan/phase-03b-harbor-setup.md](/home/steve/git/proxmox-homelab/docs/plan/phase-03b-harbor-setup.md:1)
- `terraform/lxc/stacks/harbor-stack/`
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- `.env`
- `.env.pve-test`

## Expected Outputs

- VMID 121 running at `10.57.3.10`
- Harbor UI/API reachable on the infra segment

## Constraints and Conventions

- Harbor is the second and final allowed direct-upstream bootstrap pull
- On the first pass, Harbor may pull its own images directly from Docker Hub
- All later platform containers must pull through Harbor
- Do not require NetBox for this task; use ping and Proxmox verification if NetBox is not yet deployed
- SDN VLAN zone creation is still manual until Terraform VLAN support is completed

## Acceptance Criteria

- [ ] `tvinfra` exists on `pve-test`
- [ ] Harbor stack files exist and target VMID 121 / `10.57.3.10`
- [ ] `terragrunt apply` for `harbor-stack` exits 0
- [ ] `ansible-playbook deploy-harbor-stack.yml` exits 0
- [ ] `curl -s http://10.57.3.10/api/v2.0/ping` returns `Pong`
- [ ] Harbor UI login works with `admin` / `HARBOR_ADMIN_PASSWORD`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy the Harbor registry stack for a true-greenfield pve-test laptop rebuild.
Do not assume Harbor, apt-cacher, NetBox, or any SDN automation already exists.

STEP 0 — Verify host target and bootstrap dependencies:
  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test
  echo "$TF_VAR_proxmox_node"   # must print pve-test
  echo "$TF_WORKSPACE"          # must print pve-test

STEP 0b — Confirm Portainer is already up:
  curl -s http://10.57.1.20:9000/api/system/status

STEP 0c — Confirm the Debian Docker template exists:
  ssh root@pve-test.gibbsgreatly.xyz "pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz"

STEP 0d — Confirm infra_seg SDN prerequisites:
  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /nodes/pve-test/sdn/zones"
  # Expect an infra zone/VNet for VLAN 40

STEP 1 — Verify IP availability:
  ping -c 3 10.57.3.10
  # Expect no reply

STEP 2 — Ensure these files exist and match the active plan:
  - terraform/lxc/stacks/harbor-stack/stack.yaml
  - terraform/lxc/stacks/harbor-stack/terragrunt.hcl
  - terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 3 — Apply Harbor:
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack
  terragrunt apply

STEP 4 — Run the Harbor playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.3.10," \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 5 — Verify Harbor:
  curl -s http://10.57.3.10/api/v2.0/ping
  # Expect: Pong

DONE WHEN: Harbor is healthy at 10.57.3.10 and can serve as the registry/cache source for
all later platform tasks.
```
