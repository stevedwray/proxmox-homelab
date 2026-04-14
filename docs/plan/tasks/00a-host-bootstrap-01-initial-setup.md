# 00a-host-bootstrap-01 — Run Proxmox host initial setup

## Status

PENDING

## Phase

Phase 00a — Proxmox Host Bootstrap Alignment

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task assumes a fresh bare-metal Proxmox VE install on the pve-test laptop. No prior
automation has been run. Network connectivity and a root SSH session are the only
prerequisites.

## Prerequisites

- `pve-test` is reachable at `pve-test.gibbsgreatly.xyz` / `192.168.1.40` via SSH as root
- `ansible/inventory/dev.yml` lists `pve-test` under the correct host group
- `ansible/group_vars/proxmox.yml` and `ansible/group_vars/proxmox_production.yml` are
  populated with the correct values for pve-test
- No storage pools or LXC templates are assumed to exist yet

## Objective

The pve-test host has the correct Proxmox package repositories, post-install tuning
applied, and a Terraform API user + token provisioned so that later Terraform/Terragrunt
runs can authenticate to the Proxmox API.

## Scope

- Run `ansible/00-initial-setup/proxmox-initial-setup.yml` against pve-test
  - Applies Proxmox package repo baseline (no-subscription repo, removes enterprise repo)
  - Applies post-install host tuning (swappiness, kernel params)
  - Creates the Terraform automation API user and token
  - Optionally enables nftables firewall backend (via included task file)
- Verify the Terraform API token works against the Proxmox API
- Record the token in `.env` / SOPS secrets as required by `terraform/lxc`

## Out of Scope

- SDN zone creation (task 00a-02)
- Template build (task 00a-03)
- Storage pool setup (storage pools are created as part of the host build, not this task)

## Inputs

- `ansible/00-initial-setup/proxmox-initial-setup.yml`
- `ansible/00-initial-setup/tasks/proxmox-host-firewall-backend.yml`
- `ansible/inventory/dev.yml`
- `ansible/group_vars/proxmox.yml`

## Expected Outputs

- Proxmox host package repos set to no-subscription baseline
- Terraform automation user and API token exist on pve-test
- Token recorded in `terraform/secrets.enc.yaml` (SOPS-encrypted)
- `curl -k https://192.168.1.40:8006/api2/json/version` returns version JSON using the token

## Acceptance Criteria

- [ ] `ansible-playbook` run exits 0 with no failed tasks
- [ ] `pveum user list` shows the Terraform automation user
- [ ] `curl -k -H "Authorization: PVEAPIToken=..." https://192.168.1.40:8006/api2/json/version` returns HTTP 200
- [ ] Token stored in `terraform/secrets.enc.yaml` under the expected key

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Run the Proxmox host initial setup playbook against pve-test.

STEP 0 — Confirm SSH access:
  ssh root@pve-test.gibbsgreatly.xyz "hostname && pveversion"
  # Expect: pve-test and a Proxmox VE version string

STEP 1 — Review the playbook and group_vars for pve-test correctness:
  - ansible/00-initial-setup/proxmox-initial-setup.yml
  - ansible/group_vars/proxmox.yml

STEP 2 — Run the initial setup playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i ansible/inventory/dev.yml \
    ansible/00-initial-setup/proxmox-initial-setup.yml

STEP 3 — Confirm Terraform API token:
  ssh root@pve-test.gibbsgreatly.xyz "pveum user list && pveum token list terraform@pve"

STEP 4 — Verify API access with the token:
  # Token value from SOPS secrets or .env
  curl -k -H "Authorization: PVEAPIToken=terraform@pve!terraform-token=<token>" \
    https://192.168.1.40:8006/api2/json/version

STEP 5 — Encrypt and store the token:
  Ensure the token is stored in terraform/secrets.enc.yaml using SOPS.

DONE WHEN: The Proxmox host has the correct package repos, the Terraform user and token
exist, and a curl to the Proxmox API using the token returns HTTP 200.
```
