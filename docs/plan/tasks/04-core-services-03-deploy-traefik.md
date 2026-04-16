# 04-core-services-03 — Deploy Traefik reverse proxy

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/106

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-01 complete — Authentik running at `10.57.1.10`
- Phase 02 complete — pve-test at 32 GB
- `10.57.2.10` available (ping-verify before deploying; also check NetBox)
- `CF_DNS_API_TOKEN` set in `.env` — Cloudflare API token with `Zone:DNS:Edit` scope for `gibbsgreatly.xyz`
- SDN zones applied to pve-test and MikroTik static routes added (see Step 0 below)

Note: step-ca is **not** a prerequisite for this task. The `step-ca` resolver is written into `traefik.yml` at deploy time but will not be used by any route until task 04-04 (step-ca) is complete. Traefik will not attempt to contact `10.57.1.11` until a route explicitly requests it.

## Network placement

| Field | Value |
|---|---|
| SDN zone | `edge_seg` |
| Proxmox VNet | `tvedge` (VLAN 30, `10.57.2.0/24`, gw `10.57.2.1` on MikroTik) |
| Container IP | `10.57.2.10` |
| IP selection | Next allocatable host in the `edge_seg` subnet after the gateway. Verified available with ping and NetBox check before deploying. |
| Cross-zone routing | Traefik → Authentik: `10.57.2.10` → `10.57.1.10:9000` for `forwardAuth` middleware. MikroTik routes between VLAN 30 (edge_seg) and VLAN 20 (mgmt_seg). |
| Firewall intent | Inbound: ports 80 and 443 from LAN and all zones via MikroTik routing. Outbound: port 9000 to Authentik (`10.57.1.10`); DNS on 53; HTTPS (443) for Let's Encrypt DNS-01 challenge via Cloudflare API; Harbor (`10.57.3.10`) and apt-cacher (`10.57.3.11`) via MikroTik routing to infra_seg. |

## Objective

LXC `proxy-stack` (VMID 153) is running at `10.57.2.10` in `edge_seg`. The Traefik dashboard is accessible over HTTPS with a valid Let's Encrypt wildcard cert, HTTP redirects to HTTPS, and the Authentik forward-auth middleware is configured. Both certificate resolver blocks (`letsencrypt` and `step-ca`) are present in `traefik.yml`. The `step-ca` resolver block is pre-configured and dormant, ready to activate when task 04-04 completes.

## Scope

- Create `terraform/lxc/stacks/proxy-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `proxy-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` with:
  - `traefik.yml` static config — dual resolvers (`letsencrypt` DNS-01 via Cloudflare, `step-ca` ACME pre-configured), Docker provider, file provider
  - `dynamic/authentik.yml` — forwardAuth middleware
  - `dynamic/certs.yml` — wildcard cert request for `*.gibbsgreatly.xyz`
  - Docker Compose with Traefik image via Harbor proxy, `CF_DNS_API_TOKEN` env var
- Create ACME storage files with correct permissions
- Run `terragrunt apply` and the Ansible playbook

## Out of Scope

- Exposing any application-layer services (Phase 06)
- Activating the `step-ca` resolver — that is part of task 04-04
- Monitoring dashboard behind the proxy (task 04-05)
- Distributing the homelab root CA to the Traefik container — that is part of task 04-04

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 2 section
- Traefik image: `10.57.3.10/dockerhub/library/traefik:<pin>`
- Cloudflare DNS API token: `${CF_DNS_API_TOKEN}` from `.env`
- Authentik forward-auth address: `http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik`
- step-ca ACME URL (pre-configure only, not yet live): `https://10.57.1.11/acme/acme/directory`

## Expected Outputs

- `terraform/lxc/stacks/proxy-stack/stack.yaml` (new)
- `terraform/lxc/stacks/proxy-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` (new)
- LXC VMID 153 provisioned; Traefik running at `10.57.2.10`
- Let's Encrypt wildcard cert for `*.gibbsgreatly.xyz` issued and stored in `/certs/letsencrypt/acme.json`

## Constraints and Conventions

- Traefik image via Harbor proxy — never direct docker.io pull
- `CF_DNS_API_TOKEN` passed as environment variable to the Traefik container — never hardcoded in config files
- Static config (`traefik.yml`): dashboard only over HTTPS; HTTP → HTTPS redirect on web entrypoint; both resolver blocks present; Docker provider with `exposedByDefault: false`; file provider watching `/etc/traefik/dynamic/`
- Both ACME storage files must be created with `mode: '0600'` as an explicit Ansible `file` module task before `docker compose up -d` — Traefik will refuse to start if permissions are wrong
- The `step-ca` resolver block in `traefik.yml` references `10.57.1.11` — this host does not yet exist. This is intentional and safe. Traefik will not contact it unless a route uses `certresolver=step-ca`
- The Authentik outpost must be configured in Authentik before the forwardAuth middleware is active
- `stack.yaml` values: VMID 153, IP `10.57.2.10/24`, gateway `10.57.2.1` (MikroTik VLAN 30 interface), `network: zone: edge_seg`, `cores: 1`, `memory: 512`, `docker_storage_size: "5G"`
- **LAN ingress**: ports 80 and 443 at `10.57.2.10` must be reachable from `192.168.1.0/24`. The MikroTik VLAN 30 interface (10.57.2.1) provides this routing — no static routes needed. Verify from a workstation: HTTP to port 80 redirects to HTTPS, port 443 serves a cert with issuer `(STAGING) Let's Encrypt` (dev passes use LE staging).

## Acceptance Criteria

- [ ] LXC VMID 153 running at `10.57.2.10` in zone `edge_seg`
- [ ] `curl -o /dev/null -w "%{http_code}" http://10.57.2.10` returns 301 or 302
- [ ] `curl -sk https://10.57.2.10` does not error (TLS handshake succeeds)
- [ ] TLS cert for dashboard is issued by Let's Encrypt — must not show `Homelab CA`
- [ ] Traefik dashboard accessible at `https://10.57.2.10/dashboard/` (protected by Authentik SSO)
- [ ] Authentik forward-auth middleware present in `dynamic/authentik.yml`
- [ ] `dynamic/certs.yml` requesting wildcard `*.gibbsgreatly.xyz` from `letsencrypt` resolver
- [ ] Both `certificatesResolvers.letsencrypt` and `certificatesResolvers.step-ca` blocks present in `traefik.yml`
- [ ] `/certs/letsencrypt/acme.json` and `/certs/step-ca/acme.json` both have mode `0600`
- [ ] Branch `feat/proxy-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Traefik as an edge reverse proxy inside a new LXC (VMID 153) at 10.57.2.10
in the edge_seg SDN zone.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 2 section)
- VMID 153, IP 10.57.2.10/24, gateway 10.57.2.1, network zone edge_seg, cores 1, memory 512, docker_storage_size 5G
- Traefik image: 10.57.3.10/dockerhub/library/traefik:<version>
  (check Harbor proxy cache for latest stable pin — Harbor is now in infra_seg)
- Let's Encrypt: use STAGING CA for all dev passes (caServer: https://acme-staging-v02.api.letsencrypt.org/directory)
- Cloudflare DNS-01: CF_DNS_API_TOKEN from .env
- Authentik forward-auth: http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik
- step-ca ACME URL (pre-configure only): https://10.57.1.11/acme/acme/directory
  step-ca does not exist yet — pre-configure the resolver block but do NOT assign any
  route to certresolver=step-ca in this task
- step-ca resolver uses httpChallenge (not tlsChallenge) — step-ca connects back to Traefik:80

PREREQUISITES BRING-UP (pve-test is wiped between passes — bring up dependencies first):

STEP 0 — Verify VLAN zones and MikroTik setup:
  # MikroTik VLAN interfaces (10.57.0.1, 10.57.1.1, 10.57.2.1, 10.57.3.1) must already
  # be configured and the trunk port to pve-test active. See pve-test.yaml for setup commands.
  # Proxmox vmbr0 must have VLAN awareness enabled.
  # Apply SDN VLAN zones with ansible/00-initial-setup/proxmox-sdn-setup.yml (Terraform VLAN support pending):
  pvesh get /nodes/pve-test/sdn/zones
  # Expected: tvinfra, tvmgmt, tvedge, tvsegc all listed

STEP 0b — Bring up harbor-stack (first pass pulls from Docker Hub; subsequent passes use cache):
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/harbor-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.3.10," terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
  curl -s http://10.57.3.10/api/v2.0/ping   # Expect: pong

STEP 0c — Bring up apt-cacher-stack:
  cd terraform/lxc/stacks/apt-cacher-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.3.11," terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 0d — Bring up authentik-stack:
  cd terraform/lxc/stacks/authentik-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
    --extra-vars "authentik_secret_key=${AUTHENTIK_SECRET_KEY} authentik_postgres_password=${AUTHENTIK_POSTGRES_PASSWORD}"
  # Verify Authentik health before proceeding:
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Must return 204 before continuing to Step 1

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/proxy-stack

STEP 2 — Check IP availability:
  ping -c 3 10.57.2.10
  # Must timeout (no response) — if ping succeeds, address is in use, choose another
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://10.57.3.12/api/ipam/ip-addresses/?address=10.57.2.10" | jq .count
  # Should be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/proxy-stack/stack.yaml
    (VMID 153, ip_address 10.57.2.10/24, gateway 10.57.2.1, network: {zone: edge_seg},
     cores 1, memory 512, docker_storage_size 5G)
  - terraform/lxc/stacks/proxy-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml:
  The playbook should:
  a) Create /opt/proxy-stack/ directory structure:
     - docker-compose.yml (Traefik service via Harbor image, CF_DNS_API_TOKEN env var)
     - traefik.yml (static config):
         entryPoints web (80, redirect to websecure), websecure (443)
         certificatesResolvers.letsencrypt:
           acme.email admin@gibbsgreatly.xyz
           acme.storage /certs/letsencrypt/acme.json
           acme.dnsChallenge.provider cloudflare
           acme.dnsChallenge.resolvers [1.1.1.1:53, 8.8.8.8:53]
         certificatesResolvers.step-ca:
           acme.caServer https://10.57.1.11/acme/acme/directory
           acme.email admin@gibbsgreatly.xyz
           acme.storage /certs/step-ca/acme.json
           acme.httpChallenge.entryPoint web
         providers.docker (exposedByDefault: false)
         providers.file (directory: /etc/traefik/dynamic/, watch: true)
         api.dashboard: true, api.insecure: false
     - dynamic/authentik.yml (forwardAuth middleware for Authentik at 10.57.1.10)
     - dynamic/certs.yml (wildcard *.gibbsgreatly.xyz from letsencrypt resolver)
  b) Create ACME storage files before starting Traefik:
       file: /certs/letsencrypt/acme.json  mode: '0600'
       file: /certs/step-ca/acme.json      mode: '0600'
  c) docker compose up -d

STEP 5 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/proxy-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml \
    --extra-vars "cf_dns_api_token=${CF_DNS_API_TOKEN}"

STEP 6 — Validate TLS and redirect:
  curl -o /dev/null -w "%{http_code}" http://10.57.2.10
  # Expect 301 or 302

  curl -sv https://10.57.2.10/dashboard/ 2>&1 | grep -i "issuer"
  # Expect: issuer must show Let's Encrypt, NOT Homelab CA

STEP 7 — Configure Authentik outpost for forward-auth (in Authentik UI at 10.57.1.10:9000):
  - Create a "Proxy Provider" for the Traefik forward-auth URL
  - Create an outpost of type "Proxy" pointing at 10.57.2.10
  - The middleware is already configured in dynamic/authentik.yml

STEP 8 — Commit and merge:
  git add terraform/lxc/stacks/proxy-stack/ \
          terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
  git commit -m "feat(traefik): deploy reverse proxy in edge_seg with Let's Encrypt wildcard and Authentik forward-auth (VMID 153)"
  git checkout dev/pve-test && git merge feat/proxy-stack
  git push origin dev/pve-test

DONE WHEN: Let's Encrypt wildcard cert valid in browser, dashboard accessible behind Authentik,
HTTP→HTTPS redirect working, step-ca resolver block present in traefik.yml.
Task 04-04 (step-ca) is now unblocked.
```
