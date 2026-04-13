# 03c-artifact-proxy-01 — Deploy apt-cacher-ng stack on infra_seg

## Status

PENDING

## Phase

Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform mirror)

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task assumes a fresh pve-test laptop build where Portainer and Harbor have already
been brought up, but apt-cacher-ng has not.

## Prerequisites

- Phase 00b complete — Portainer running at `10.57.1.20`
- Harbor deployment task complete — Harbor healthy at `10.57.3.10`
- Storage pool `infrastructure-containers` exists
- Template `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz` exists
- `infra_seg` SDN zone/VNet is already applied manually on `pve-test`

## Network placement

| Field | Value |
|---|---|
| Zone | `infra_seg` |
| VLAN | 40 |
| VNet | `tvinfra` |
| IP | `10.57.3.11` |
| Gateway | `10.57.3.1` |
| VMID | 142 |

## Objective

LXC `apt-cacher-stack` (VMID 142) is running at `10.57.3.11`, serves the apt-cacher-ng
status page on port 3142, and becomes the apt proxy used by later LXCs in the greenfield
bring-up path.

## Scope

- Create or verify `terraform/lxc/stacks/apt-cacher-stack/stack.yaml`
- Create or verify `terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl`
- Create or verify `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml`
- Add or verify the base-LXC apt proxy task that writes `/etc/apt/apt.conf.d/01proxy`
- Apply the apt-cacher LXC and run the stack playbook

## Out of Scope

- Terraform provider mirror setup
- Re-pointing every previously deployed LXC to the proxy
- NetBox registration work

## Inputs

- [docs/plan/phase-03c-artifact-proxy.md](/home/steve/git/proxmox-homelab/docs/plan/phase-03c-artifact-proxy.md:1)
- `terraform/lxc/stacks/apt-cacher-stack/`
- `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml`

## Expected Outputs

- VMID 142 running at `10.57.3.11`
- apt-cacher-ng reachable at `http://10.57.3.11:3142/acng-report.html`
- Active LXC bootstrap path includes `Acquire::http::Proxy "http://10.57.3.11:3142";`

## Constraints and Conventions

- apt-cacher-ng is an infra-segment dependency for later tasks, but Harbor remains the image source
- Do not require NetBox for the initial greenfield deployment
- Later tasks should assume apt proxying is available after this task completes
- The apt proxy configuration must be added to the shared LXC/base role so future LXCs inherit it automatically

## Acceptance Criteria

- [ ] apt-cacher stack files exist and target VMID 142 / `10.57.3.11`
- [ ] Base LXC/shared role writes `/etc/apt/apt.conf.d/01proxy` pointing to `10.57.3.11:3142`
- [ ] `terragrunt apply` for `apt-cacher-stack` exits 0
- [ ] `ansible-playbook deploy-apt-cacher-stack.yml` exits 0
- [ ] `curl http://10.57.3.11:3142/acng-report.html` returns HTTP 200
- [ ] `apt-cacher-ng` systemd service is active inside the LXC

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy apt-cacher-ng on the greenfield pve-test laptop after Portainer and Harbor are
already online.

STEP 0 — Verify bootstrap dependencies:
  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test
  echo "$TF_VAR_proxmox_node"   # must print pve-test
  echo "$TF_WORKSPACE"          # must print pve-test
  curl -s http://10.57.1.20:9000/api/system/status
  curl -s http://10.57.3.10/api/v2.0/ping

STEP 0b — Confirm template and infra SDN prerequisites:
  ssh root@pve-test.gibbsgreatly.xyz "pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz"
  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /nodes/pve-test/sdn/zones"

STEP 1 — Verify IP availability:
  ping -c 3 10.57.3.11
  # Expect no reply

STEP 2 — Ensure these files exist and match the active plan:
  - terraform/lxc/stacks/apt-cacher-stack/stack.yaml
  - terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl
  - terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 2b — Ensure the shared LXC/base role includes:
  /etc/apt/apt.conf.d/01proxy
  with:
    Acquire::http::Proxy "http://10.57.3.11:3142";

STEP 3 — Apply apt-cacher:
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/apt-cacher-stack
  terragrunt apply

STEP 4 — Run the playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.3.11," \
    terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 5 — Verify service:
  curl http://10.57.3.11:3142/acng-report.html
  # Expect: status page

DONE WHEN: apt-cacher-ng is healthy at 10.57.3.11:3142 and is ready to support later stack
deployments, and future LXCs inherit the apt proxy config automatically.
```
