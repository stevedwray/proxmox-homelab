# 03b-harbor-01 — Deploy Harbor LXC to pve-test

## Status

PENDING

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## Prerequisites

- Phase 00b complete: standalone Portainer running at `192.168.1.20:9000`
- Phase 01 complete: ci-runner-01 online
- `terraform/lxc/stacks/harbor-stack/stack.yaml` and `terragrunt.hcl` exist in the repo
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml` exists
- `.env` has `HARBOR_ADMIN_PASSWORD` set
- `192.168.1.10` is unallocated (verify in NetBox)

## Objective

Harbor CE is running at `http://192.168.1.10` on pve-test (VMID 121), accessible via browser, and `curl -k https://192.168.1.10/api/v2.0/ping` returns `"Pong"`.

## Scope

- `terragrunt apply` in `terraform/lxc/stacks/harbor-stack/`
- Run `deploy-harbor-stack.yml` playbook against VMID 121
- Verify Harbor UI accessible and admin login works

## Out of Scope

- Harbor project creation (task 03b-03)
- Robot account and GC configuration (task 03b-04)
- Image pre-pull (task 03b-05)
- `harbor_postconfigure` is included in the playbook — if it ran cleanly, that's covered here; otherwise task 03b-02 handles re-running it

## Inputs

- `terraform/lxc/stacks/harbor-stack/stack.yaml`
- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl`
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- `.env` with `HARBOR_ADMIN_PASSWORD`, Proxmox API credentials
- `.env.pve-test` (sets pve-test target)

## Expected Outputs

- VMID 121 (`harbor-stack`) running on pve-test at `192.168.1.10`
- Harbor UI accessible at `http://192.168.1.10`

## Constraints and Conventions

- Source `.env` then `.env.pve-test` last
- Verify `TF_VAR_proxmox_node=pve-test` before apply
- Harbor's initial startup can take 2–3 minutes — wait before running health checks
- If deploy-harbor-stack.yml includes a `harbor_postconfigure` role, it will run as part of this task
- **LAN ingress**: Harbor (VMID 110, `192.168.1.10`) is on `mgmt_seg` and is directly LAN-reachable. Validate that ports 80 and 443 are accessible from your workstation after deploy — Harbor is unusable as an image cache if the LAN can't reach the registry API.

## Acceptance Criteria

- [ ] Safety check: `TF_VAR_proxmox_node=pve-test`
- [ ] `terragrunt apply` exits 0, VMID 121 created
- [ ] `curl -k https://192.168.1.10/api/v2.0/ping` returns `"Pong"`
- [ ] Admin login at `http://192.168.1.10` with `HARBOR_ADMIN_PASSWORD` succeeds

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy the Harbor LXC to pve-test via Terragrunt and Ansible. This is an
infrastructure-apply task — no code changes needed unless files are missing.

BEFORE STARTING, CHECK THESE FILES EXIST:
  terraform/lxc/stacks/harbor-stack/stack.yaml
  terraform/lxc/stacks/harbor-stack/terragrunt.hcl
  terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 1 — Source environment:
  cd /home/steve/git/proxmox-homelab
  source .env
  source .env.pve-test

STEP 2 — Safety check:
  echo "Node target  : $TF_VAR_proxmox_node"   # must print: pve-test
  echo "TF workspace : $TF_WORKSPACE"           # must print: pve-test

STEP 3 — Verify IP 192.168.1.10 is free:
  curl -s -H "Authorization: Token ${NETBOX_SUPERUSER_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.10" | jq .count
  # Expected: 0

STEP 4 — Provision Harbor LXC:
  cd terraform/lxc/stacks/harbor-stack
  terragrunt apply
  # Confirm plan: 1 LXC to create, VMID 121, IP 192.168.1.10, memory ~8192

STEP 5 — Run the playbook (check inventory path in the stack directory):
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i terraform/lxc/stacks/harbor-stack/inventory.yml \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 6 — Wait 2–3 minutes for Harbor to initialise, then verify:
  curl -k https://192.168.1.10/api/v2.0/ping
  # Expected: "Pong"

  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/systeminfo" | jq .harbor_version
  # Expected: version string

DONE WHEN: Harbor UI accessible and ping returns "Pong". Then proceed to task
03b-harbor-02-postconfigure.md to verify robot accounts and proxy caches.
```
