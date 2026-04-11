# 04-core-services-01 — Deploy Authentik identity provider

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/103

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Phase 02 (memory upgrade) complete — pve-test at 32 GB RAM
- Phase 03b complete — Harbor running at `192.168.1.10`, Trivy enabled, proxy cache projects configured, Authentik images pre-pulled and scanned
- Phase 03c complete — apt-cacher-ng running at `192.168.1.35`
- Phase 01 complete — ci-runner-01 online
- `192.168.1.40` available (verify in NetBox before deploying)
- `.env` has Proxmox API credentials; `.env.pve-test` has `TF_VAR_proxmox_node=pve-test`

## Objective

LXC `authentik-stack` (VMID 150) is running at `192.168.1.40`, the Authentik health endpoints return HTTP 204, and an initial admin user has been created.

## Scope

- Create `terraform/lxc/stacks/authentik-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `authentik-stack/terragrunt.hcl` verbatim
- Create `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`
- Add `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_POSTGRES_PASSWORD`, `AUTHENTIK_SUPERUSER_PASSWORD`, `AUTHENTIK_SUPERUSER_API_TOKEN` to `.env.template`
- Run `terragrunt apply` and the Ansible playbook
- Complete the initial Authentik setup wizard

## Out of Scope

- OIDC provider configuration for downstream apps (Phase 06)
- Authentik forward-auth middleware for Traefik (task 04-04)
- Monitoring OIDC integration (task 04-05)

## Inputs

- `terraform/lxc/stacks/harbor-stack/stack.yaml` — reference for stack.yaml format
- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` — copy verbatim
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml` — reference for playbook structure
- `docs/plan/phase-04-core-shared-services.md` — Service 1 section for compose detail
- `.env` for `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_POSTGRES_PASSWORD`, `AUTHENTIK_SUPERUSER_PASSWORD`

## Expected Outputs

- `terraform/lxc/stacks/authentik-stack/stack.yaml` (new)
- `terraform/lxc/stacks/authentik-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` (new)
- `.env.template` updated with four Authentik variables
- LXC VMID 150 provisioned in pve-test
- Authentik stack healthy at `192.168.1.40`

## Constraints and Conventions

- All compose images must reference Harbor proxy cache (`192.168.1.10/...`), never direct docker.io/ghcr.io
- Images must be pinned to specific version tags (not `latest`)
- Compose: `postgres:16-alpine`, `redis:alpine`, `goauthentik/server:<pin>` (same version for server and worker)
- `stack.yaml` values: VMID 150, IP `192.168.1.40/24`, `cores: 2`, `memory: 3072`, `docker_storage_size: "20G"`
- Pass secrets to playbook via `--extra-vars` sourced from `.env`; never hardcode credentials in playbook files
- Branch convention: cut `feat/authentik-stack` from `dev/pve-test`, merge after health check passes
- **LAN ingress**: Authentik HTTP (port 9000) and HTTPS (port 9443) at `192.168.1.40` must be reachable from `192.168.1.0/24`. Browser-based OIDC flows require the client (workstation) to connect directly to Authentik — Traefik forwards the auth check but the browser redirect targets Authentik's own URL directly.

## Acceptance Criteria

- [ ] `curl http://192.168.1.40:9000/-/health/live/` returns HTTP 204
- [ ] `curl http://192.168.1.40:9000/-/health/ready/` returns HTTP 204
- [ ] Admin UI accessible at `http://192.168.1.40:9000/if/flow/initial-setup/`
- [ ] Initial admin user created
- [ ] `AUTHENTIK_SUPERUSER_API_TOKEN` populated in `.env`
- [ ] `.env.template` has all four Authentik variable placeholders
- [ ] Branch `feat/authentik-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Authentik identity provider as a new LXC (VMID 150) at 192.168.1.40 on pve-test.

CONTEXT:
- Read the existing stack pattern (stack.yaml + terragrunt.hcl) from:
    terraform/lxc/stacks/harbor-stack/
- Read the reference playbook at:
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
- The full spec is in docs/plan/phase-04-core-shared-services.md (Service 1 section)
- All compose images must go through Harbor proxy at 192.168.1.10 (NOT docker.io/ghcr.io directly)
- Authentik image: 192.168.1.10/ghcr/goauthentik/server:<version> — check Harbor for the pinned tag
- Postgres image: 192.168.1.10/dockerhub/library/postgres:16-alpine
- Redis image: 192.168.1.10/dockerhub/library/redis:alpine

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/authentik-stack

STEP 2 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.40" | jq .count
  # Must be 0 before proceeding

STEP 3 — Create stack files:
  - terraform/lxc/stacks/authentik-stack/stack.yaml (VMID 150, IP 192.168.1.40, cores 2, memory 3072, docker_storage_size 20G)
  - terraform/lxc/stacks/authentik-stack/terragrunt.hcl (copy from harbor-stack/terragrunt.hcl verbatim)

STEP 4 — Add secrets to .env.template:
  - AUTHENTIK_SECRET_KEY=          # 50+ char random: openssl rand -hex 32
  - AUTHENTIK_POSTGRES_PASSWORD=   # strong password
  - AUTHENTIK_SUPERUSER_PASSWORD=  # initial admin password
  - AUTHENTIK_SUPERUSER_API_TOKEN= # populated after first boot

STEP 5 — Add actual secret values to .env (not committed):
  source .env
  # Generate and add: AUTHENTIK_SECRET_KEY, AUTHENTIK_POSTGRES_PASSWORD, AUTHENTIK_SUPERUSER_PASSWORD

STEP 6 — Create Ansible playbook:
  terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
  Following the harbor playbook pattern: install Docker, deploy compose at /opt/authentik-stack/docker-compose.yml,
  inject secrets via environment or .env file.
  Compose services: postgresql, redis, server, worker (all via Harbor proxy images, pinned versions).

STEP 7 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/authentik-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "192.168.1.40," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
    --extra-vars "authentik_secret_key=${AUTHENTIK_SECRET_KEY} authentik_postgres_password=${AUTHENTIK_POSTGRES_PASSWORD}"

STEP 8 — Validate:
  curl -s -o /dev/null -w "%{http_code}" http://192.168.1.40:9000/-/health/live/
  # Expect: 204
  curl -s -o /dev/null -w "%{http_code}" http://192.168.1.40:9000/-/health/ready/
  # Expect: 204

STEP 9 — Complete initial setup wizard at http://192.168.1.40:9000/if/flow/initial-setup/
  Use AUTHENTIK_SUPERUSER_PASSWORD from .env. After creating admin, create an API token
  and store it in .env as AUTHENTIK_SUPERUSER_API_TOKEN.

STEP 10 — Commit and merge:
  git add terraform/lxc/stacks/authentik-stack/ terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml .env.template
  git commit -m "feat(authentik): deploy Authentik identity provider stack (VMID 150)"
  git push origin feat/authentik-stack

SECURITY SCAN (run before merging — stop and present options if new issues are found):
  /home/steve/.local/bin/snyk iac test terraform/
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

  git checkout dev/pve-test && git merge feat/authentik-stack
  git push origin dev/pve-test

DONE WHEN: Both health endpoints return 204, admin UI accessible, and security scan clean.
Task 04-02 (Headscale) is now unblocked.
```
