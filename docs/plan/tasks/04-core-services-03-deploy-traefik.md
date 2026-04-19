# 04-core-services-03 — Deploy Traefik reverse proxy

## Rebuild confidence

| Criterion | State |
| --- | --- |
| IaC reproducible | Partial |
| Secrets managed | **No** — `CF_DNS_API_TOKEN` written in plaintext into compose file on disk |
| Integrations wired | Partial |
| Rebuild-safe | **No** |

See [development-status.md](../development-status.md) for the full gap analysis.

## GitHub Issue

[stevedwray/proxmox-homelab#106](https://github.com/stevedwray/proxmox-homelab/issues/106)

## Phase

Phase 04 — Core Shared Services

## Known gaps preventing rebuild-safety

1. **Secrets in plaintext.** `CF_DNS_API_TOKEN` is written into
   `/opt/proxy-stack/docker-compose.yml` in cleartext. The playbook must inject it from
   SOPS via `./with-secrets` and write a SOPS-sourced `.env` file that Docker Compose reads
   via `env_file`. No secret value may appear in a committed or on-disk compose file.

2. **LE cert not persisted.** The ACME cert storage (`certs/letsencrypt/acme.json`) lives
  inside the LXC filesystem at `/opt/proxy-stack/certs/`. Rebuilding the LXC destroys it,
  triggering a new LE cert request. On pve-test with the staging CA this is harmless; on
  production it consumes rate-limit quota. Fix: add platform-supported `extra_mount_*`
  fields in `stack.yaml` so `/opt/proxy-stack/certs` is backed by persistent storage.

   ```yaml
  extra_mount_path: "/opt/proxy-stack/certs"
  extra_mount_size: "5G"
  extra_mount_storage: infrastructure-containers
   ```

3. **Authentik outpost not automated.** The `authentik` forwardAuth middleware points at
   `http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik`. This URL only works if an
   Authentik Proxy Provider and outpost have been created. After an Authentik rebuild, these
   must be re-created manually (in task 04-01 Step 7) before any protected route works. The
   `terraform-provider-authentik` provider is the automation path — see the Authentik task.

4. **LE staging CA required on pve-test.** Dev passes must use
   `https://acme-staging-v02.api.letsencrypt.org/directory` in the `letsencrypt` resolver.
   The production CA must only be used when promoting to `pve`. Staging certs show
   `(STAGING) Let's Encrypt` in browsers — this is expected and correct.

## Prerequisites

- Task 04-01 complete — Authentik running at `10.57.1.10`, Proxy Provider outpost created
- Phase 02 complete — pve-test at 32 GB
- `10.57.2.10` available (ping-verify before deploying)
- `CF_DNS_API_TOKEN` set to its real value in `terraform/secrets.enc.yaml` — Cloudflare API
  token with `Zone:DNS:Edit` scope for `gibbsgreatly.xyz` only (SEC-07)
- MikroTik resolver conditionally forwards `lab.gibbsgreatly.xyz` to the internal authoritative
  DNS server
- SDN zones applied to pve-test and MikroTik VLAN interfaces active

Note: step-ca is **not** a prerequisite for this task. The `step-ca` resolver is written into
`traefik.yml` at deploy time but will not be used by any route until task 04-04 (step-ca) is
complete. Traefik will not attempt to contact `10.57.1.11` until a route explicitly requests it.

## Network placement

| Field | Value |
| --- | --- |
| SDN zone | `edge_seg` |
| Proxmox VNet | `tvedge` (VLAN 30, `10.57.2.0/24`, gw `10.57.2.1` on MikroTik) |
| Container IP | `10.57.2.10` |
| Cross-zone routing | Traefik → Authentik: `10.57.2.10` → `10.57.1.10:9000` for `forwardAuth` middleware |
| Firewall intent | Inbound: ports 80 and 443 from LAN and all zones. Outbound: port 9000 to Authentik; DNS on 53; HTTPS for LE DNS-01 via Cloudflare; Harbor and apt-cacher via MikroTik to infra_seg |

## Objective

LXC `proxy-stack` (VMID 153) is running at `10.57.2.10` in `edge_seg`. The Traefik dashboard
is accessible over HTTPS with a valid Let's Encrypt staging cert (dev passes), HTTP redirects
to HTTPS, and the Authentik forward-auth middleware is configured. Both certificate resolver
blocks (`letsencrypt` and `step-ca`) are present in `traefik.yml`. All secrets are injected
from SOPS at deploy time — no literal credentials on disk.

Ingress naming policy for this task:

- Traefik operator ingress is `traefik.lab.gibbsgreatly.xyz`.
- Internal service identities may continue to use `*.lab.gibbsgreatly.xyz` where applicable.

## Scope

- Create `terraform/lxc/stacks/proxy-stack/stack.yaml` — include `extra_mount_*` fields for
  `certs/` directory persistence (LE cert persistence)
- Copy `harbor-stack/terragrunt.hcl` to `proxy-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` — secrets injected from SOPS,
  compose file references env vars only
- Create ACME storage files with correct permissions (`0600`) before `docker compose up -d`
- Run `./with-secrets terragrunt apply` and the Ansible playbook

## Out of Scope

- Exposing any application-layer services (Phase 06)
- Activating the `step-ca` resolver — that is part of task 04-04
- Monitoring dashboard behind the proxy (task 04-05)
- Distributing the homelab root CA to the Traefik container — that is part of task 04-04
- `terraform-provider-authentik` implementation — tracked in the Authentik task

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 2 section
- Traefik image: `10.57.3.10/dockerhub/library/traefik:<pin>`
- Cloudflare DNS API token: `${CF_DNS_API_TOKEN}` from `terraform/secrets.enc.yaml` (via `./with-secrets`)
- Authentik forward-auth address: `http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik`
- step-ca ACME URL (pre-configure only, not yet live): `https://10.57.1.11/acme/acme/directory`

## Expected Outputs

- `terraform/lxc/stacks/proxy-stack/stack.yaml` with `extra_mount_*` cert persistence fields
- `terraform/lxc/stacks/proxy-stack/terragrunt.hcl`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` — secrets via env_file from SOPS
- LXC VMID 153 provisioned; Traefik running at `10.57.2.10`
- Let's Encrypt staging cert for `*.gibbsgreatly.xyz` issued and stored in the persisted
  certs directory (survives LXC rebuild)

## Constraints and Conventions

- Traefik image via Harbor proxy — never direct docker.io pull
- Stack field names must follow `terraform/lxc/PLATFORM_CONTRACT.md` (use only documented
  keys such as `extra_mount_path`, `extra_mount_size`, `extra_mount_storage`)
- Secrets: `./with-secrets` wraps all commands; playbook writes a SOPS-sourced `.env` file;
  Docker Compose reads it via `env_file`; no `--extra-vars` for secrets
- Static config (`traefik.yml`): dashboard only over HTTPS; HTTP → HTTPS redirect on web
  entrypoint; both resolver blocks present; Docker provider with `exposedByDefault: false`;
  file provider watching `/etc/traefik/dynamic/`
- **LE staging CA for all pve-test dev passes** — `caServer: https://acme-staging-v02.api.letsencrypt.org/directory`
- Both ACME storage files must be created with `mode: '0600'` before `docker compose up -d`
- The `step-ca` resolver block in `traefik.yml` references `10.57.1.11` — this host does not
  yet exist. This is intentional and safe. Traefik will not contact it unless a route uses
  `certresolver=step-ca`
- `stack.yaml` values: VMID 153, IP `10.57.2.10/24`, gateway `10.57.2.1`, `network: zone: edge_seg`,
  `cores: 1`, `memory: 512`, `docker_storage_size: "5G"`, plus
  `extra_mount_path: "/opt/proxy-stack/certs"`, `extra_mount_size: "5G"`,
  `extra_mount_storage: infrastructure-containers`
- **LAN ingress**: ports 80 and 443 at `10.57.2.10` must be reachable from `192.168.1.0/24`.
  Verify from workstation: HTTP port 80 redirects to HTTPS, port 443 serves a staging LE cert

## Acceptance Criteria

- [ ] LXC VMID 153 running at `10.57.2.10` in zone `edge_seg`
- [ ] `curl -o /dev/null -w "%{http_code}" http://10.57.2.10` returns 301 or 302
- [ ] `curl -sk https://10.57.2.10` does not error (TLS handshake succeeds)
- [ ] TLS cert shows issuer `(STAGING) Let's Encrypt` — must not show `Homelab CA` or production LE
- [ ] Traefik dashboard accessible at `https://traefik.lab.gibbsgreatly.xyz/dashboard/` (protected by Authentik SSO)
- [ ] `/opt/proxy-stack/docker-compose.yml` contains no literal credentials
- [ ] Authentik forward-auth middleware present in `dynamic/authentik.yml`
- [ ] `dynamic/certs.yml` requesting wildcard `*.gibbsgreatly.xyz` from `letsencrypt` resolver
- [ ] Both `certificatesResolvers.letsencrypt` and `certificatesResolvers.step-ca` blocks present
  in `traefik.yml`, using staging CA URL
- [ ] ACME storage files have mode `0600`
- [ ] Certs directory persisted using `extra_mount_*` storage fields (survives LXC rebuild)
- [ ] Branch `feat/proxy-stack` merged to `dev/pve-test`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Traefik as an edge reverse proxy inside a new LXC (VMID 153) at 10.57.2.10
in the edge_seg SDN zone.

IMPORTANT: All secret values are in terraform/secrets.enc.yaml and must be injected via
./with-secrets. Never pass secrets as --extra-vars. The playbook must write a .env file
(read by Docker Compose via env_file) sourced from SOPS. No literal credentials on disk.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 2 section)
- VMID 153, IP 10.57.2.10/24, gateway 10.57.2.1, network zone edge_seg, cores 1, memory 512,
  docker_storage_size 5G
- stack.yaml must include cert persistence via:
    extra_mount_path: "/opt/proxy-stack/certs"
    extra_mount_size: "5G"
    extra_mount_storage: infrastructure-containers
- stack.yaml keys must follow terraform/lxc/PLATFORM_CONTRACT.md
- Traefik image: 10.57.3.10/dockerhub/library/traefik:<version>
- Let's Encrypt: STAGING CA for all pve-test dev passes:
    caServer: https://acme-staging-v02.api.letsencrypt.org/directory
- Cloudflare DNS-01: CF_DNS_API_TOKEN flows via ./with-secrets — do not pass as extra-vars
- Authentik forward-auth: http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik
- step-ca ACME URL (pre-configure only, not yet live): https://10.57.1.11/acme/acme/directory
  step-ca does not exist yet — pre-configure the resolver block but do NOT assign any
  route to certresolver=step-ca in this task
- step-ca resolver uses httpChallenge (not tlsChallenge) — step-ca connects back to Traefik:80

PREREQUISITES BRING-UP (bring up dependencies first before creating new stack files):

STEP 0 — Verify VLAN zones and MikroTik setup:
  pvesh get /nodes/pve-test/sdn/zones
  # Expected: tvinfra, tvmgmt, tvedge, tvsegc all listed

STEP 0b — Bring up harbor-stack:
  cd terraform/lxc/stacks/harbor-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.3.10," terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
  curl -s http://10.57.3.10/api/v2.0/ping   # Expect: pong

STEP 0c — Bring up apt-cacher-stack:
  cd terraform/lxc/stacks/apt-cacher-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.3.11," terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 0d — Bring up authentik-stack and complete first-boot setup:
  cd terraform/lxc/stacks/authentik-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Must return 204.
  # Then complete first-boot: http://10.57.1.10:9000/if/flow/initial-setup/
  # Create Proxy Provider + outpost for Traefik forward-auth (see task 04-01 Step 7).
  # This manual step is a known rebuild gap — the outpost must exist before Traefik auth works.

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/proxy-stack

STEP 2 — Check IP availability:
  ping -c 3 10.57.2.10
  # Must timeout (no response)

STEP 3 — Create stack files:
  - terraform/lxc/stacks/proxy-stack/stack.yaml
    (VMID 153, ip_address 10.57.2.10/24, gateway 10.57.2.1, network: {zone: edge_seg},
     cores 1, memory 512, docker_storage_size 5G,
     plus extra mount:
       extra_mount_path /opt/proxy-stack/certs
       extra_mount_size 5G
       extra_mount_storage infrastructure-containers)
  - terraform/lxc/stacks/proxy-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml:
  The playbook must:
  a) Write /opt/proxy-stack/.env from SOPS-injected environment (no literal values):
       CF_DNS_API_TOKEN={{ lookup('env', 'CF_DNS_API_TOKEN') }}
  b) Write docker-compose.yml referencing env_file: .env (no literal CF_DNS_API_TOKEN value)
  c) Write traefik.yml static config:
       entryPoints web (80, redirect to websecure), websecure (443)
       certificatesResolvers.letsencrypt:
         acme.email admin@gibbsgreatly.xyz
         acme.storage /certs/letsencrypt/acme.json
         acme.caServer https://acme-staging-v02.api.letsencrypt.org/directory
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
  d) Write dynamic/authentik.yml (forwardAuth middleware for Authentik at 10.57.1.10)
  e) Write dynamic/certs.yml (wildcard *.gibbsgreatly.xyz from letsencrypt resolver)
  f) Create ACME storage files before starting Traefik:
       file: /opt/proxy-stack/certs/letsencrypt/acme.json  mode: '0600'
       file: /opt/proxy-stack/certs/step-ca/acme.json      mode: '0600'
  g) docker compose up -d

STEP 5 — Deploy:
  cd terraform/lxc/stacks/proxy-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml

STEP 6 — Validate TLS and redirect:
  curl -o /dev/null -w "%{http_code}" http://10.57.2.10
  # Expect 301 or 302

  curl -sv https://10.57.2.10/ 2>&1 | grep -i "issuer"
  # Expect: "(STAGING) Let's Encrypt" — NOT Homelab CA, NOT production LE

  curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:10.57.2.10 \
    https://traefik.lab.gibbsgreatly.xyz/dashboard/
  # Expect: 302 redirect to Authentik authorize flow

  # Verify no literal credentials in compose file:
  TRAEFIK_VMID=$(pct list | awk 'NR>1 && ($4=="proxy-stack" || $4=="traefik") {print $1; exit}')
  pct exec "$TRAEFIK_VMID" -- grep -i "CF_DNS_API_TOKEN" /opt/proxy-stack/docker-compose.yml
  # Must show only the env var reference, not a token value

STEP 7 — Verify Authentik forward-auth (requires outpost from task 04-01 Step 7):
  # The middleware is configured in dynamic/authentik.yml.
  # The Authentik Proxy Provider outpost must already exist — this is a manual rebuild step.
  # Accessing https://traefik.lab.gibbsgreatly.xyz/dashboard/ should redirect through Authentik login.
  # NOTE: This step remains manual until terraform-provider-authentik is implemented.

STEP 8 — Commit and merge:
  git add terraform/lxc/stacks/proxy-stack/ \
          terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
  git commit -m "feat(traefik): deploy reverse proxy in edge_seg with LE staging cert and Authentik forward-auth (VMID 153)"
  git checkout dev/pve-test && git merge feat/proxy-stack
  git push origin dev/pve-test

DONE WHEN: LE staging cert valid in browser, compose file has no literal credentials,
certs directory is persisted via extra mount, HTTP→HTTPS redirect working, step-ca resolver block present.
Task 04-04 (step-ca) is now unblocked.
```
