# 04-core-services-01 — Deploy Authentik identity provider on mgmt_seg

## Rebuild confidence

| Criterion | State |
| --- | --- |
| IaC reproducible | Partial |
| Secrets managed | No — credentials baked into compose file on disk |
| Integrations wired | Partial |
| Rebuild-safe | **No** |

See [development-status.md](../development-status.md) for the full gap analysis.

## Phase

Phase 04 — Core Shared Services

## GitHub Issue

Not assigned yet.

## Known gaps preventing rebuild-safety

1. **Secrets in plaintext.** `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_POSTGRES_PASSWORD`, and related
   credentials are written into the compose file on disk inside the LXC. The playbook must
   inject all secrets from SOPS via `./with-secrets` and write a SOPS-sourced `.env` file
   that Docker Compose reads via `env_file`. No secret value may appear in a committed or
   on-disk compose file.

2. **Initial setup is manual.** After a fresh deploy, an operator must:
   - Access the first-boot web UI at `http://10.57.1.10:9000/if/flow/initial-setup/`
   - Create the superuser account using `AUTHENTIK_SUPERUSER_PASSWORD` from SOPS
   - Generate an API token and add it to `terraform/secrets.enc.yaml` as `AUTHENTIK_SUPERUSER_API_TOKEN`
   - Create a Proxy Provider + outpost for Traefik forward-auth — configure the provider in
     **"Forward auth (domain level)"** mode with cookie domain `.gibbsgreatly.xyz`. This allows
     one outpost to protect all `*.gibbsgreatly.xyz` subdomains (Traefik dashboard, Portainer,
     NetBox). Single-application mode only covers one redirect URI and cannot scale across
     multiple services.
   - Create an OIDC provider for Grafana (produces `GRAFANA_OAUTH_CLIENT_ID` and
     `GRAFANA_OAUTH_CLIENT_SECRET`, which must also be added to SOPS)

   This sequence cannot be skipped — Traefik auth and Grafana OIDC both fail without it.

3. **Automation path (target state).** The `terraform-provider-authentik` Terraform provider
   can manage providers, outposts, and OIDC clients using `AUTHENTIK_SUPERUSER_API_TOKEN`.
   Once implemented, only the initial superuser creation remains manual. All subsequent
   configuration becomes IaC. This is the primary work needed to make Authentik rebuild-safe.

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
- `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_POSTGRES_PASSWORD`, `AUTHENTIK_SUPERUSER_PASSWORD` are set
  to real values in `terraform/secrets.enc.yaml`

## Network placement

| Field | Value |
| --- | --- |
| Zone | `mgmt_seg` |
| VLAN | 20 |
| VNet | `tvmgmt` |
| IP | `10.57.1.10` |
| Gateway | `10.57.1.1` |
| VMID | 150 |

## Objective

LXC `authentik-stack` (VMID 150) is running at `10.57.1.10` in `mgmt_seg`, the Authentik
health endpoints return HTTP 200 or 204, and all secrets are injected from SOPS at deploy time —
no credentials in any on-disk file. After deploy, the manual first-boot steps are completed
and `AUTHENTIK_SUPERUSER_API_TOKEN` is recorded in `terraform/secrets.enc.yaml` for use by
future `terraform-provider-authentik` automation.

## Browser ingress and certificate policy

Authentik is a browser-facing service and must be accessed through Traefik with a Let's
Encrypt certificate. Internal step-ca certificates are not valid for browser-facing routes.

- Canonical browser URL: `https://authentik.gibbsgreatly.xyz`
- Resolver policy: `certResolver: letsencrypt`
- Auth policy: **no Traefik middleware** — Authentik is the identity provider; it cannot use
  its own forward-auth (circular dependency)
- Temporary bootstrap URL by IP (`http://10.57.1.10:9000`) is allowed only for first-boot
  setup and health checks

Route wiring is implemented in task `04-core-services-06-browser-ingress-wiring`.

## Scope

- Create or verify `terraform/lxc/stacks/authentik-stack/stack.yaml`
- Create or verify `terraform/lxc/stacks/authentik-stack/terragrunt.hcl`
- Create or verify `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` — must inject
  secrets from SOPS via `./with-secrets`; compose file must reference env vars only, no literal
  credentials
- Ensure the required Authentik secret keys exist in `terraform/secrets.enc.yaml`
- Apply the Authentik LXC and run the stack playbook
- Complete first-boot admin initialization and record `AUTHENTIK_SUPERUSER_API_TOKEN` in
  `terraform/secrets.enc.yaml` via SOPS

## Out of Scope for this task (known gaps — see above)

- `terraform-provider-authentik` implementation — listed as the automation path, not yet built

## In Scope Manual Runtime Gates

- Traefik forward-auth Proxy Provider and outpost creation are required in this task's
  manual first-boot sequence
- Grafana OIDC provider creation is required in this task's manual first-boot sequence
- `GRAFANA_OAUTH_CLIENT_ID` and `GRAFANA_OAUTH_CLIENT_SECRET` must be recorded in
  `terraform/secrets.enc.yaml` before marking this task complete

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 1 section
- `terraform/lxc/stacks/authentik-stack/`
- `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`
- `terraform/secrets.enc.yaml` — secrets injected via `./with-secrets`

## Expected Outputs

- VMID 150 running at `10.57.1.10`
- Authentik health endpoints healthy
- Compose file on disk contains only env var references — no literal credentials
- `AUTHENTIK_SUPERUSER_API_TOKEN` recorded in `terraform/secrets.enc.yaml` after first boot
- Traefik forward-auth Proxy Provider outpost created in Authentik
- Grafana OIDC provider created and its client credentials recorded in
  `terraform/secrets.enc.yaml`

## Constraints and Conventions

- All container images must be pulled via Harbor at `10.57.3.10`
- apt inside the LXC routes via apt-cacher at `10.57.3.11`
- Do not require NetBox for the initial deployment pass
- This is the first management-segment service and unblocks Traefik, step-ca, and monitoring
- Secrets injection: `./with-secrets` wraps all `terragrunt` and `ansible-playbook` calls;
  the playbook writes a SOPS-sourced `.env` file that Docker Compose reads via `env_file`
- No `--extra-vars` for secrets — all secret values flow from `terraform/secrets.enc.yaml`
  via `./with-secrets` as environment variables

## Acceptance Criteria

- [ ] Authentik stack files exist and target VMID 150 / `10.57.1.10`
- [ ] `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` exists
- [ ] `terraform/secrets.enc.yaml` contains real values (not `CHANGEME_`) for all Authentik keys
- [ ] `./with-secrets terragrunt apply` for `authentik-stack` exits 0
- [ ] `./with-secrets ansible-playbook deploy-authentik-stack.yml` exits 0
- [ ] On-disk compose file at `/opt/authentik-stack/docker-compose.yml` contains no literal credentials
- [ ] `curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/live/` returns 200 or 204
- [ ] `curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/` returns 200 or 204
- [ ] Initial admin setup completed via web UI
- [ ] `AUTHENTIK_SUPERUSER_API_TOKEN` recorded in `terraform/secrets.enc.yaml` (not in `.env`)
- [ ] Traefik forward-auth Proxy Provider created in domain-level mode with cookie domain `.gibbsgreatly.xyz`
- [ ] Outpost created and assigned the traefik-forwardauth provider
- [ ] Browser ingress contract documented for `authentik.gibbsgreatly.xyz` (no Traefik middleware)
- [ ] Traefik route and browser cert for Authentik validated (task 04-core-services-06)
- [ ] `GRAFANA_OAUTH_CLIENT_ID` and `GRAFANA_OAUTH_CLIENT_SECRET` recorded in
  `terraform/secrets.enc.yaml` (not in `.env`)

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Authentik as the first management-segment service on a true-greenfield
bare-metal pve-test laptop rebuild.

IMPORTANT: All secret values are in terraform/secrets.enc.yaml and must be injected via
./with-secrets. Never pass secrets as --extra-vars. Never store secrets in .env.
The Ansible playbook must write a .env file (read by Docker Compose via env_file) that
contains only env var references — never literal credential values.

STEP 0 — Verify bootstrap and infra dependencies:
  ./with-secrets bash -c 'echo "Node: $TF_VAR_proxmox_node; Workspace: $TF_WORKSPACE"'
  # Must print: Node: pve-test; Workspace: pve-test
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
  (AUTHENTIK_SUPERUSER_API_TOKEN populated in Step 7 after first-boot)

  To edit: SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml

STEP 4 — Apply Authentik LXC:
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/authentik-stack
  ../../../../with-secrets terragrunt apply

STEP 5 — Run the playbook:
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml

STEP 6 — Verify health:
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/live/
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Expect: 200 or 204 for both

STEP 7 — Complete first-boot setup (manual — this remains a rebuild gap until
         terraform-provider-authentik is implemented):
  Open http://10.57.1.10:9000/if/flow/initial-setup/
  Use AUTHENTIK_SUPERUSER_PASSWORD from terraform/secrets.enc.yaml.
  After the admin account is created, generate an API token in the Authentik admin UI.
  Record the token in terraform/secrets.enc.yaml (NOT in .env):
    SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
    # Set AUTHENTIK_SUPERUSER_API_TOKEN to the real token value

  Also create (manually for now — terraform-provider-authentik will automate these):
  - A Proxy Provider + outpost for Traefik forward-auth (unblocks task 04-03)
  - An OIDC provider for Grafana — record resulting client ID and secret in SOPS as
    GRAFANA_OAUTH_CLIENT_ID and GRAFANA_OAUTH_CLIENT_SECRET (unblocks task 04-05)

DONE WHEN: Authentik is healthy at 10.57.1.10, compose file has no literal credentials,
AUTHENTIK_SUPERUSER_API_TOKEN is in SOPS, the Proxy Provider outpost is created, and
Grafana OIDC client credentials are stored in SOPS.
```
