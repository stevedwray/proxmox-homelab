# 00b-pve-test-03 — Deploy portainer-stack via Terragrunt and Ansible

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## Prerequisites

- Task 00b-01 complete: pve-test is wiped and empty
- Task 00b-02 complete: `portainer-stack/stack.yaml`, `portainer-stack/terragrunt.hcl`, and `deploy-portainer-stack.yml` all exist
- `.env` is sourced with `PM_API_TOKEN_ID`, `PM_API_TOKEN_SECRET`, `PM_API_URL`, `LXC_PASSWORD`, `PORTAINER_ADMIN_PASSWORD`
- `.env.pve-test` is sourced (sets `TF_VAR_proxmox_node=pve-test`, `TF_WORKSPACE=pve-test`)
- `192.168.1.20` is unallocated (verify in NetBox before applying; the NetBox API is on `http://192.168.1.30:8080`)
- Docker Hub is reachable from pve-test (required for the Portainer image pull)

## Objective

Portainer CE is deployed and running at `http://192.168.1.20:9000` on pve-test (VMID 120), with the admin account initialised, and the local Docker environment registered as an endpoint.

## Scope

- `terragrunt apply` in `terraform/lxc/stacks/portainer-stack/`
- `ansible-playbook deploy-portainer-stack.yml` against the new LXC IP
- Verify Portainer UI is accessible and admin login works

## Out of Scope

- Updating `.env.pve-test` with `TF_VAR_portainer_server_ip` (that is task 00b-04)
- Redeploying other stacks (ci-runner-01, Harbor, etc.)
- Phase 03b Harbor configuration

## Inputs

- `terraform/lxc/stacks/portainer-stack/stack.yaml` and `terragrunt.hcl`
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
- `.env` (Proxmox API credentials + `PORTAINER_ADMIN_PASSWORD`)
- `.env.pve-test` (pve-test overrides)

## Expected Outputs

- VMID 120 (`portainer-stack`) running on pve-test at `192.168.1.20`
- Portainer UI accessible at `http://192.168.1.20:9000`
- Admin account initialised

## Constraints and Conventions

- Source order: `.env` first, then `.env.pve-test` last (pve-test overrides win)
- Always verify `TF_VAR_proxmox_node=pve-test` before apply
- Terragrunt runs `tofu init -reconfigure` automatically — no manual init needed
- If the LXC exists but the playbook failed, re-run the playbook without re-applying Terraform

## Acceptance Criteria

- [ ] Safety check passes: `TF_VAR_proxmox_node=pve-test`, `TF_WORKSPACE=pve-test`
- [ ] `terragrunt apply` exits 0 and creates VMID 120
- [ ] LXC is reachable: `ping -c1 192.168.1.20` succeeds
- [ ] Ansible playbook exits 0
- [ ] `curl -s http://192.168.1.20:9000/api/system/status` returns HTTP 200
- [ ] Admin login via `http://192.168.1.20:9000` with `PORTAINER_ADMIN_PASSWORD` succeeds
- [ ] Portainer UI shows at least one endpoint (local Docker)
- [ ] **LAN reachability**: `curl -s http://192.168.1.20:9000` succeeds from a workstation on the LAN (not from pve-test itself) — confirms the UI is accessible for day-to-day management

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Apply Terraform and run the Ansible playbook to deploy the portainer-stack LXC on
pve-test. This is an infrastructure-apply task — no code changes are needed.

PREREQUISITES CHECK:
- Confirm these files exist before proceeding:
  terraform/lxc/stacks/portainer-stack/stack.yaml
  terraform/lxc/stacks/portainer-stack/terragrunt.hcl
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
  If any are missing, stop — run task 00b-02 first.

STEP 1 — Source environment (source order matters):
  cd /home/steve/git/proxmox-homelab
  source .env
  source .env.pve-test

STEP 2 — Safety check (stop if either is wrong):
  echo "Node target  : $TF_VAR_proxmox_node"   # must print: pve-test
  echo "TF workspace : $TF_WORKSPACE"           # must print: pve-test

STEP 3 — Verify IP is free:
  curl -s -H "Authorization: Token ${NETBOX_SUPERUSER_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.20" | jq .count
  # Expected: 0

STEP 4 — Provision the LXC:
  cd terraform/lxc/stacks/portainer-stack
  terragrunt apply

  Confirm the plan shows: 1 LXC to create, VMID 120, IP 192.168.1.20, memory 512.

STEP 5 — Wait for LXC to boot, then run the Ansible playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "192.168.1.20," \
    terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

  If the playbook has an inventory.yml in the stack directory, use that instead of the
  inline inventory.

STEP 6 — Verify (from within pve-test or the LXC):
  curl -s http://192.168.1.20:9000/api/system/status
  # Expected: HTTP 200 with JSON including version info

STEP 7 — Verify LAN reachability (run this from your workstation, not from pve-test):
  curl -s http://192.168.1.20:9000/api/system/status
  # Must also return HTTP 200 — confirms port 9000 is reachable from the LAN.
  # If it fails but step 6 passed, check for a host firewall on pve-test blocking the port.

  Open http://192.168.1.20:9000 in a browser and log in as admin with PORTAINER_ADMIN_PASSWORD.
  Confirm at least one endpoint (local Docker environment) appears in Environments.

TROUBLESHOOTING:
- If the Portainer image pull times out against Docker Hub, re-run `terragrunt apply`; the image pull is the only flaky part of the bootstrap and the LXC itself is safe to keep.
- If Terraform creates the LXC but Docker isn't starting, SSH in and check:
    ssh root@192.168.1.20 "systemctl status docker"
- If the Portainer UI is not reachable, check:
    ssh root@192.168.1.20 "docker ps"
- If the admin init POST returns 409, that means Portainer is already initialised — this
  is idempotent and should be treated as success.

DONE WHEN: Portainer UI is accessible and admin login works. No commit needed for this task
(infrastructure apply, no code changes).
```
