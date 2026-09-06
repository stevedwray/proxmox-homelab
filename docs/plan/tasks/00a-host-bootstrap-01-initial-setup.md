# 00a-host-bootstrap-01 — Run Proxmox host initial setup

> Historical task packet.
> This document reflects the earlier bare-metal `pve-test` workflow and a
> retired branch model.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

COMPLETE

## Phase

Phase 00a — Proxmox Host Bootstrap Alignment

## GitHub Issue

[#129](https://github.com/stevedwray/proxmox-homelab/issues/129)

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

- [x] `ansible-playbook` run exits 0 with no failed tasks
- [x] `pveum user list` shows the Terraform automation user
- [x] `curl -k -H "Authorization: PVEAPIToken=..." https://192.168.1.40:8006/api2/json/version` returns HTTP 200
- [x] Token stored in `terraform/secrets.enc.yaml` under the expected key

## Completion Notes

- Verified on 2026-04-16 against `pve-test.gibbsgreatly.xyz`
- Host baseline applied cleanly: no-subscription Proxmox and Ceph repos, enterprise repos removed, nftables firewall backend enabled, IPv6 sysctl baseline applied
- Current automation API identity is `automation@pve!terraform`; older `terraform@pve!terraform-token` wording in this task is historical
- Token source of truth updated in `terraform/secrets.enc.yaml` and validated with a successful Proxmox API version query
- Completed in commit `d58a8e0`; issue `#129` closed

## Session Prompt

```text
You are working in /home/steve/git/proxmox-homelab on branch baseline/teardown-validated.

Issue: #129 — feat(host-bootstrap): run Proxmox host initial setup on pve-test (Phase 00a, task 1)

Context:
- Boundary-strengthening Sessions 3, 4, and 5 are merged into baseline/teardown-validated.
- Active pve-test shared-service wiring and stack metadata validation are already in place.
- Do not reopen boundary-strengthening work unless this host-bootstrap task directly depends on it.

TASK: Run the Proxmox host initial setup playbook against pve-test.

Primary objective:
- Prepare the pve-test Proxmox host so later Terraform/Terragrunt and Phase 00a follow-on work can authenticate and run cleanly.

STEP 0 — Confirm SSH access:
  ssh root@pve-test.gibbsgreatly.xyz "hostname && pveversion"
  # Expect: pve-test and a Proxmox VE version string

STEP 1 — Review the playbook and group_vars for pve-test correctness:
  - ansible/00-initial-setup/proxmox-initial-setup.yml
  - ansible/00-initial-setup/tasks/proxmox-host-firewall-backend.yml
  - ansible/inventory/dev.yml
  - ansible/group_vars/proxmox.yml
  - ansible/group_vars/proxmox_production.yml

  Confirm:
  - inventory includes pve-test in the intended host group
  - group vars still match the pve-test host/IP/API user expectations
  - the playbook's secrets/token flow still matches the current repository reality

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
  Ensure the token is stored in the repo's current expected secrets location.
  If the current repo no longer uses terraform/secrets.enc.yaml for this value,
  document the real path/flow instead of forcing the old assumption.

STEP 6 — Validate any repo changes:
  Run the relevant validation for any files you touched.
  If Terraform files or Python/shell/YAML code changes were made, run the required scans before merging.

STEP 7 — Commit and close the issue when verified:
  git commit -m "feat(ansible): run pve-test Proxmox host initial setup (Closes #129)"
  gh issue close 129 --comment "Fixed in commit <sha>"

DONE WHEN: The Proxmox host has the correct package repos, the Terraform user and token
exist, a curl to the Proxmox API using the token returns HTTP 200, and any repo updates
have been validated and committed against issue #129.
```
