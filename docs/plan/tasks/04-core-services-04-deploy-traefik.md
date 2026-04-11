# 04-core-services-04 — Deploy Traefik reverse proxy

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/106

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-01 complete — Authentik running at `192.168.1.40`
- Task 04-03 complete — step-ca running at `192.168.1.42`, ACME directory responding
- Phase 02 complete — pve-test at 32 GB
- `192.168.1.43` available (verify in NetBox before deploying)

## Objective

LXC `proxy-stack` (VMID 153) is running at `192.168.1.43`, the Traefik dashboard is accessible over HTTPS (certificate from step-ca), HTTP redirects to HTTPS, and the Authentik forward-auth middleware is configured.

## Scope

- Create `terraform/lxc/stacks/proxy-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `proxy-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` with:
  - `traefik.yml` static config (ACME via step-ca, Docker provider)
  - `dynamic/authentik.yml` (forwardAuth middleware)
  - Docker Compose with Traefik image via Harbor proxy
- Run `terragrunt apply` and the Ansible playbook

## Out of Scope

- Exposing any application-layer services (Phase 06)
- DNS or public certificate configuration — internal certs from step-ca only in this task
- Monitoring dashboard behind the proxy (task 04-05)

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 4 section
- Traefik image: `192.168.1.10/dockerhub/library/traefik:<pin>`
- step-ca ACME URL: `https://192.168.1.42/acme/acme/directory`
- Authentik forward-auth address: `http://192.168.1.40:9000/outpost.goauthentik.io/auth/traefik`

## Expected Outputs

- `terraform/lxc/stacks/proxy-stack/stack.yaml` (new)
- `terraform/lxc/stacks/proxy-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` (new)
- LXC VMID 153 provisioned; Traefik running at `192.168.1.43`

## Constraints and Conventions

- Traefik image via Harbor proxy — never direct docker.io pull
- Static config (`traefik.yml`): dashboard only over HTTPS; HTTP → HTTPS redirect on web entrypoint; ACME resolver points to step-ca; Docker provider with `exposedByDefault: false`
- `acme.json` must have `chmod 600` — add this as an Ansible file module task
- The Authentik outpost must be configured in Authentik before the middleware is active
- `stack.yaml` values: VMID 153, IP `192.168.1.43/24`, `cores: 1`, `memory: 512`, `docker_storage_size: "5G"`
- **LAN ingress**: Traefik is the edge proxy — ports 80 and 443 at `192.168.1.43` must be reachable from `192.168.1.0/24`. Verify from a workstation after deploy: a plain HTTP request to port 80 should redirect to HTTPS, and port 443 should serve a valid cert from step-ca.

## Acceptance Criteria

- [ ] LXC VMID 153 running at `192.168.1.43`
- [ ] `curl -sk https://192.168.1.43:443` does not error (TLS handshake succeeds)
- [ ] HTTP request to `http://192.168.1.43` redirects to HTTPS (HTTP 301/302)
- [ ] Traefik dashboard accessible at `https://192.168.1.43/dashboard/` (protected by Authentik)
- [ ] TLS cert issued by Homelab CA (from step-ca)
- [ ] Authentik forward-auth middleware configured in `dynamic/authentik.yml`
- [ ] Branch `feat/proxy-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Traefik as an edge reverse proxy inside a new LXC (VMID 153) at 192.168.1.43.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 4 section)
- VMID 153, IP 192.168.1.43, cores 1, memory 512, docker_storage_size 5G
- Traefik image: 192.168.1.10/dockerhub/library/traefik:<version>
  (check Harbor proxy cache for latest stable pin)
- ACME directory: https://192.168.1.42/acme/acme/directory (step-ca from task 04-03)
- Authentik forward-auth: http://192.168.1.40:9000/outpost.goauthentik.io/auth/traefik
- The root CA cert is at certs/homelab-root.crt (created in task 04-03)

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/proxy-stack

STEP 2 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.43" | jq .count
  # Must be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/proxy-stack/stack.yaml
  - terraform/lxc/stacks/proxy-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml:
  The playbook should:
  a) Create /opt/proxy-stack/ with:
     - docker-compose.yml (Traefik service via Harbor image)
     - traefik.yml (static config): 
         entryPoints web (80, redirect to websecure), websecure (443)
         certificatesResolvers.step-ca with caServer https://192.168.1.42/acme/acme/directory
         providers.docker (exposedByDefault: false), providers.file (dynamic/ dir)
         api.dashboard: true, api.insecure: false
     - dynamic/authentik.yml (forwardAuth middleware for Authentik)
  b) Create /opt/proxy-stack/letsencrypt/acme.json with mode 0600
  c) Install the homelab root CA cert in the LXC:
     copy certs/homelab-root.crt → /usr/local/share/ca-certificates/homelab-root.crt
     run: update-ca-certificates
  d) docker compose up -d

STEP 5 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/proxy-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "192.168.1.43," terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml

STEP 6 — Validate TLS and redirect:
  curl -o /dev/null -w "%{http_code}" http://192.168.1.43
  # Expect 301 or 302 (redirect to HTTPS)
  
  curl -sk --cacert certs/homelab-root.crt -o /dev/null -w "%{http_code}" \
    https://192.168.1.43/dashboard/
  # Expect 200 or Authentik redirect

STEP 7 — Configure Authentik outpost for forward-auth (in Authentik UI at 192.168.1.40:9000):
  - Create a "Proxy Provider" for the Traefik forward-auth URL
  - Create an outpost of type "Proxy" pointing at 192.168.1.43
  - The middleware is already configured in dynamic/authentik.yml

STEP 8 — Commit and merge:
  git add terraform/lxc/stacks/proxy-stack/ terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
  git commit -m "feat(traefik): deploy reverse proxy with step-ca ACME and Authentik forward-auth (VMID 153)"
  git checkout dev/pve-test && git merge feat/proxy-stack
  git push origin dev/pve-test

DONE WHEN: HTTPS cert from step-ca valid, dashboard accessible, HTTP→HTTPS redirect working.
Task 04-05 (Monitoring) is now unblocked.
```
