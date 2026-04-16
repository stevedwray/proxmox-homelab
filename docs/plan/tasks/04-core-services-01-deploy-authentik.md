# 04-core-services-01 — Deploy Authentik identity provider on mgmt_seg

## Status

PENDING

## Phase

Phase 04 — Core Shared Services

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task assumes a true greenfield pve-test rebuild where the laptop started with only host
storage and host bootstrap. By the time this task begins, the bootstrap and infra platform
services must already exist locally on `pve-test`.

## Prerequisites

- Phase 00b complete — Portainer running at `10.57.1.20`
- Harbor deployment task complete — Harbor healthy at `10.57.3.10`
- apt-cacher deployment task complete — apt-cacher healthy at `10.57.3.11`
- Storage pool `infrastructure-containers` exists
- Template `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz` exists
- `mgmt_seg` and `infra_seg` SDN VLAN zones are applied manually on `pve-test`
- `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_POSTGRES_PASSWORD`, `AUTHENTIK_SUPERUSER_PASSWORD`, and `AUTHENTIK_SUPERUSER_API_TOKEN` are set to real values in `terraform/secrets.enc.yaml`

## Network placement

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| VLAN | 20 |
| VNet | `tvmgmt` |
| IP | `10.57.1.10` |
| Gateway | `10.57.1.1` |
| VMID | 150 |

## Objective

LXC `authentik-stack` (VMID 150) is running at `10.57.1.10` in `mgmt_seg`, the Authentik
health endpoints return HTTP 204, and the service is ready for later Traefik forward-auth
integration.

## Scope

- Create or verify `terraform/lxc/stacks/authentik-stack/stack.yaml`
- Create or verify `terraform/lxc/stacks/authentik-stack/terragrunt.hcl`
- Create or verify `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`
- Ensure the required Authentik secret placeholders exist in `.env.template`
- Apply the Authentik LXC and run the stack playbook
- Complete first-boot admin initialization and record `AUTHENTIK_SUPERUSER_API_TOKEN` in `.env`

## Out of Scope

- Traefik forward-auth wiring
- Authentik outpost configuration for Traefik
- step-ca integration
- Monitoring OIDC configuration

## Inputs

- [docs/plan/phase-04-core-shared-services.md](/home/steve/git/proxmox-homelab/docs/plan/phase-04-core-shared-services.md:128)
- `terraform/lxc/stacks/authentik-stack/`
- `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`
- `.env`
- `.env.template`

## Expected Outputs

- VMID 150 running at `10.57.1.10`
- Authentik health endpoints healthy
- `.env.template` contains the required Authentik secret placeholders
- `AUTHENTIK_SUPERUSER_API_TOKEN` recorded after first boot

## Constraints and Conventions

- All container images must be pulled via Harbor at `10.57.3.10`
- apt inside the LXC should route via apt-cacher at `10.57.3.11`
- Do not require NetBox for the initial deployment pass
- This is the first management-segment service and unblocks Traefik, step-ca, and monitoring
- After health is confirmed, complete the initial setup flow and create an admin API token for later automation

## Acceptance Criteria

- [ ] Authentik stack files exist and target VMID 150 / `10.57.1.10`
- [ ] `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` exists
- [ ] `.env.template` contains the required Authentik placeholders
- [ ] `terragrunt apply` for `authentik-stack` exits 0
- [ ] `ansible-playbook deploy-authentik-stack.yml` exits 0
- [ ] `curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/live/` returns 204
- [ ] `curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/` returns 204
- [ ] Initial admin setup is complete
- [ ] `AUTHENTIK_SUPERUSER_API_TOKEN` is recorded in `.env`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Authentik as the first management-segment service on a true-greenfield
bare-metal pve-test laptop rebuild.

STEP 0 — Verify bootstrap and infra dependencies:
  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test
  echo "$TF_VAR_proxmox_node"   # must print pve-test
  echo "$TF_WORKSPACE"          # must print pve-test
  curl -s http://10.57.1.20:9000/api/system/status
  curl -s http://10.57.3.10/api/v2.0/ping
  curl -s http://10.57.3.11:3142/acng-report.html >/dev/null

STEP 0b — Confirm template and SDN prerequisites:
  ssh root@pve-test.gibbsgreatly.xyz "pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz"
  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /nodes/pve-test/sdn/zones"
  # Expect mgmt and infra zones/VNets to exist

STEP 1 — Verify IP availability:
  ping -c 3 10.57.1.10
  # Expect no reply

STEP 2 — Ensure these files exist and match the active plan:
  - terraform/lxc/stacks/authentik-stack/stack.yaml
  - terraform/lxc/stacks/authentik-stack/terragrunt.hcl
  - terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml

STEP 3 — Ensure Authentik secrets are set to real values in terraform/secrets.enc.yaml:
  AUTHENTIK_SECRET_KEY
  AUTHENTIK_POSTGRES_PASSWORD
  AUTHENTIK_SUPERUSER_PASSWORD
  (AUTHENTIK_SUPERUSER_API_TOKEN will be populated after first-boot init in Step 7)

  To edit: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml

STEP 4 — Apply Authentik:
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/authentik-stack
  ./../../../../with-secrets terragrunt apply

STEP 5 — Run the playbook:
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml

STEP 6 — Verify health:
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/live/
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Expect: 204 for both

STEP 7 — Complete first-boot setup:
  Open http://10.57.1.10:9000/if/flow/initial-setup/
  Use AUTHENTIK_SUPERUSER_PASSWORD (check terraform/secrets.enc.yaml).
  After the admin account is ready, create an API token and update it in secrets.enc.yaml:
    SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
    (Replace CHANGEME_AUTHENTIK_SUPERUSER_API_TOKEN with the real token)

DONE WHEN: Authentik is healthy at 10.57.1.10 and later Phase 04 tasks can depend on it.
```
