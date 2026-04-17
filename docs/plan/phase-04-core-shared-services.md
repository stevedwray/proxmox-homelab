# Phase 04 — Core Shared Services

## Goal

Deploy the foundational shared services that must exist before any application stacks are migrated:

1. **Authentik** — identity provider, SSO, MFA
2. **Reverse proxy** (Traefik) — dedicated ingress edge with dual certificate strategy
3. **step-ca** — internal certificate authority for service-to-service and management plane TLS
4. **Monitoring stack** — VictoriaMetrics + Grafana + Loki

Deploy in this order. Authentik must be running before Traefik (auth middleware depends on it). Traefik must be running before step-ca (step-ca resolver is activated in Traefik as part of the step-ca task). Monitoring deploys last as the most resource-heavy service.

## Live task docs

- [04-core-services-01 — Deploy Authentik identity provider on mgmt_seg](tasks/04-core-services-01-deploy-authentik.md)
- [04-core-services-03 — Deploy Traefik reverse proxy](tasks/04-core-services-03-deploy-traefik.md)
- [04-core-services-04 — Deploy step-ca internal certificate authority](tasks/04-core-services-04-deploy-step-ca.md)
- [04-core-services-05 — Deploy monitoring stack (VictoriaMetrics + Grafana + Loki)](tasks/04-core-services-05-deploy-monitoring.md)

## Current implementation status (2026-04-17)

- Authentik stack intent exists in `terraform/lxc/stacks/authentik-stack/stack.yaml` and corresponding playbook `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`.
- Traefik stack artifacts now exist at `terraform/lxc/stacks/proxy-stack/` with playbook `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`.
- step-ca stack/playbook wiring is present (`terraform/lxc/stacks/step-ca-stack/stack.yaml` -> `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`) and CA trust distribution playbook exists at `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml`.
- Monitoring stack artifacts now exist at `terraform/lxc/stacks/monitoring-stack/` with playbook `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`.
- Validate and execute task acceptance checks per service docs before marking Phase 04 complete.

## Certificate strategy

This phase uses a **dual certificate resolver** model in Traefik:

| Resolver | CA | Challenge | Used for |
|---|---|---|---|
| `letsencrypt` | Let's Encrypt | DNS-01 via Cloudflare | All browser-facing routes — wildcard `*.gibbsgreatly.xyz` |
| `step-ca` | Homelab internal CA | ACME via step-ca | Internal management plane, Proxmox API, Ansible `validate_certs: true` |

**Browser connections always use Let's Encrypt certs.** The homelab root CA is never distributed to browsers or end-user devices. It is distributed only to managed services that need to validate internal TLS: the Traefik container itself, the Ansible control machine, Proxmox hosts, and any service that calls another internal service directly.

This approach preserves the existing Cloudflare DNS + Let's Encrypt wildcard workflow while eliminating `validate_certs: false` and self-signed certs from internal management tooling over time.

step-ca is **not a prerequisite for Traefik**. Traefik is deployed first using only the `letsencrypt` resolver. The `step-ca` resolver block is pre-written into `traefik.yml` at deploy time but references a CA that does not yet exist — this is safe because Traefik only contacts a resolver when a route explicitly requests it. The step-ca task (04-04) then bootstraps the CA and activates the resolver.

---

## Prerequisites

- Phase 01 (CI runner) complete — self-hosted runner is online
- **Phase 02 (memory upgrade) complete** — pve-test must be at 32 GB before starting this phase
- **Phase 03b complete** — Harbor has Trivy scanner enabled, proxy cache projects configured, and Phase 04 images already pulled and scanned
- **Phase 03c complete** — apt-cacher-ng running at `10.57.3.11` in `infra_seg`; all LXC stacks deployed in this phase will route apt through the proxy automatically
- Harbor is running at `10.57.3.10` in `infra_seg` (deployed earlier)
- NetBox is running at `10.57.3.12` in `infra_seg` (deployed earlier)
- Cloudflare API token with `Zone:DNS:Edit` scope for `gibbsgreatly.xyz` available — add as `CF_DNS_API_TOKEN` in `.env`
- The stack deployment pattern is understood — see `terraform/lxc/stacks/harbor-stack/` and `terraform/lxc/stacks/netbox-stack/` as reference implementations
- `.env` is sourced with Proxmox API credentials
- **SDN zones applied to pve-test** — `mgmt_seg`, `edge_seg`, and `build_seg` must exist before any Phase 04 container is deployed (see SDN setup below)

### SDN zone setup (do this before deploying any Phase 04 stack)

pve-test uses Proxmox SDN **VLAN zones**. The MikroTik is the L3 gateway for all zones — no routing or NAT is performed on the Proxmox host.

**MikroTik one-time setup** — run once per pve-test rebuild (see full commands in `pve-test.yaml`):

```text
# Create VLAN interfaces on the trunk port facing pve-test
/interface vlan add interface=<trunk-iface> name=vlan10-build vlan-id=10
/interface vlan add interface=<trunk-iface> name=vlan20-mgmt  vlan-id=20
/interface vlan add interface=<trunk-iface> name=vlan30-edge  vlan-id=30
/interface vlan add interface=<trunk-iface> name=vlan40-infra vlan-id=40
/ip address add address=10.57.0.1/24 interface=vlan10-build
/ip address add address=10.57.1.1/24 interface=vlan20-mgmt
/ip address add address=10.57.2.1/24 interface=vlan30-edge
/ip address add address=10.57.3.1/24 interface=vlan40-infra
```

**Proxmox one-time setup** — enable VLAN awareness on vmbr0:

```bash
# In Proxmox UI: Network → vmbr0 → Edit → check "VLAN aware" → Apply
ifreload -a
```

**Apply SDN zones** (run `ansible/00-initial-setup/proxmox-sdn-setup.yml` until Terraform VLAN zone support is implemented):

```bash
# Create each zone and VNet — see pve-test.yaml for the full sequence
pvesh create /cluster/sdn/zones --type vlan --zone tvinfra --bridge vmbr0 --nodes pve-test
pvesh create /cluster/sdn/zones --type vlan --zone tvmgmt  --bridge vmbr0 --nodes pve-test
pvesh create /cluster/sdn/zones --type vlan --zone tvedge  --bridge vmbr0 --nodes pve-test
pvesh create /cluster/sdn/zones --type vlan --zone tvsegc  --bridge vmbr0 --nodes pve-test
# ... create VNets with tags and subnets, then:
pvesh set /cluster/sdn

pvesh get /nodes/pve-test/sdn/zones
# Expected output includes: tvinfra, tvmgmt, tvedge, tvsegc
```

---

## Image reference convention

All compose files in this phase use Harbor proxy cache image references — **never direct Docker Hub or GHCR pulls at runtime**. Phase 03b pre-pulled and scanned all images listed below. The pattern is:

| Upstream | Via Harbor |
|---|---|
| `docker.io/library/postgres:16-alpine` | `10.57.3.10/dockerhub/library/postgres:16-alpine` |
| `ghcr.io/goauthentik/server:<ver>` | `10.57.3.10/ghcr/goauthentik/server:<ver>` |
| `docker.io/grafana/grafana-oss:<ver>` | `10.57.3.10/dockerhub/grafana/grafana-oss:<ver>` |
| `docker.io/library/traefik:<ver>` | `10.57.3.10/dockerhub/library/traefik:<ver>` |
| `docker.io/victoriametrics/victoria-metrics:<ver>` | `10.57.3.10/dockerhub/victoriametrics/victoria-metrics:<ver>` |
| `docker.io/grafana/loki:<ver>` | `10.57.3.10/dockerhub/grafana/loki:<ver>` |

Always use the Harbor proxy address in compose files. If an image is not yet in Harbor, pull it through the proxy first (see Phase 03b Part E).

---

## Networking / IP allocation

Phase 04 containers are placed in named SDN zones — not on the flat LAN bridge. SDN zones must be applied to pve-test before deploying any stack (see Prerequisites above).

| Service | Zone | IP | VMID | Notes |
|---|---|---|---|---|
| Authentik | `mgmt_seg` | `10.57.1.10` | 150 | Identity provider — reachable from edge_seg (Traefik forward-auth) |
| Traefik | `edge_seg` | `10.57.2.10` | 153 | Ports 80 and 443 reachable from LAN via MikroTik route |
| step-ca | `mgmt_seg` | `10.57.1.11` | 152 | Internal only — ACME directory at `https://10.57.1.11/acme/acme/directory` |
| Monitoring | `mgmt_seg` | `10.57.1.12` | 154 | Grafana/VictoriaMetrics/Loki — accessed via Traefik proxy |

**Verify each IP is unallocated before deploying:**

```bash
# Ping check — must timeout (no response means address is free)
ping -c 3 10.57.1.10

# NetBox check (NetBox runs locally on pve-test at 10.57.3.12)
curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
  "http://10.57.3.12/api/ipam/ip-addresses/?address=10.57.1.10" | jq .count
# Should be 0 for each IP
```

---

## Service 1 — Authentik (identity provider)

### Overview

Authentik manages user identity, SSO (SAML/OIDC/LDAP), MFA, and reverse-proxy auth flows. It is composed of four services: `server`, `worker`, PostgreSQL, and Redis.

Reference: [authentik docs](https://docs.goauthentik.io)

### Stack file

Create `terraform/lxc/stacks/authentik-stack/stack.yaml`:

```yaml
# Authentik identity provider — management zone
hostname: authentik-stack
ip_address: "10.57.1.10/24"
gateway: "10.57.1.1"
vmid: 150
cores: 2
memory: 2048
swap: 1024
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "20G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - authentik
  - identity
  - infrastructure
  - docker

ansible_playbook: "deploy-authentik-stack"
portainer_agent: true
```

Copy `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` to `authentik-stack/terragrunt.hcl` with no changes needed.

### Secrets required

Add to `.env.template` and `.env`:

```bash
AUTHENTIK_SECRET_KEY=          # 50+ char random string: openssl rand -hex 32
AUTHENTIK_POSTGRES_PASSWORD=   # strong password
AUTHENTIK_SUPERUSER_PASSWORD=  # initial admin password
AUTHENTIK_SUPERUSER_API_TOKEN= # created after first boot
```

These must be passed to the playbook via `--extra-vars` or stored in Ansible vault.

### Ansible playbook

Create `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`.

The compose stack should use the official `ghcr.io/goauthentik/server:<version>` image (pin a specific version tag, do not use `latest`).

Key compose services:
- `postgresql` — Postgres 16+, data volume persisted
- `redis` — Redis/Valkey for caching and task queue
- `server` — Authentik main server, exposes port 9000 (HTTP) and 9443 (HTTPS)
- `worker` — Authentik background worker (same image as server)

Minimal `docker-compose.yml` excerpt (all images via Harbor proxy cache — pre-scanned in Phase 03b):

```yaml
services:
  postgresql:
    image: 10.57.3.10/dockerhub/library/postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: "${AUTHENTIK_POSTGRES_PASSWORD}"
      POSTGRES_USER: authentik
      POSTGRES_DB: authentik
    volumes:
      - database:/var/lib/postgresql/data

  redis:
    image: 10.57.3.10/dockerhub/library/redis:alpine
    command: --save 60 1 --loglevel warning

  server:
    image: 10.57.3.10/ghcr/goauthentik/server:2024.12.3   # pin to specific version
    command: server
    environment:
      AUTHENTIK_REDIS__HOST: redis
      AUTHENTIK_POSTGRESQL__HOST: postgresql
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: "${AUTHENTIK_POSTGRES_PASSWORD}"
      AUTHENTIK_SECRET_KEY: "${AUTHENTIK_SECRET_KEY}"
    ports:
      - "9000:9000"
      - "9443:9443"
    depends_on:
      - postgresql
      - redis

  worker:
    image: 10.57.3.10/ghcr/goauthentik/server:2024.12.3   # same version as server
    command: worker
    environment: *server-env  # reference server env block
    depends_on:
      - postgresql
      - redis
```

### Initial configuration

After deployment, access `http://10.57.1.10:9000/if/flow/initial-setup/` to set the initial admin password. Then:

1. Create an admin user with the `AUTHENTIK_SUPERUSER_PASSWORD` value
2. Create an API token — record in `.env` as `AUTHENTIK_SUPERUSER_API_TOKEN`
3. Configure an OIDC provider for each internal application that will use SSO

### Deploy

```bash
cd terraform/lxc/stacks/authentik-stack
terragrunt apply

# Get the registration vars from .env:
source /home/steve/git/proxmox-homelab/.env

ansible-playbook \
  -i "10.57.1.10," \
  terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
  --extra-vars "authentik_secret_key=${AUTHENTIK_SECRET_KEY} authentik_postgres_password=${AUTHENTIK_POSTGRES_PASSWORD}"
```

### Validation

```bash
curl -s http://10.57.1.10:9000/-/health/live/
# Expected: HTTP 204 (no body)

curl -s http://10.57.1.10:9000/-/health/ready/
# Expected: HTTP 204 (means DB and Redis connections healthy)
```

---

## Service 2 — Reverse proxy (Traefik)

### Overview

A dedicated reverse proxy LXC is the only ingress point from external networks into internal apps. Traefik is used for its dynamic container-discovery, dual ACME resolver support, and Authentik forward-auth middleware.

Two certificate resolvers are configured at deploy time:

- **`letsencrypt`** — DNS-01 challenge via Cloudflare API. Issues `*.gibbsgreatly.xyz` wildcard. Used for all browser-facing routes. Active immediately on deploy.
- **`step-ca`** — ACME via internal step-ca at `10.57.1.11`. Used for internal management routes. Pre-configured in `traefik.yml` but not active until task 04-04 (step-ca) is complete.

### Stack file

Create `terraform/lxc/stacks/proxy-stack/stack.yaml`:

```yaml
# Traefik reverse proxy — edge / ingress
hostname: proxy-stack
ip_address: "10.57.2.10/24"
gateway: "10.57.2.1"
vmid: 153
cores: 1
memory: 512
swap: 256
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "5G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - traefik
  - proxy
  - edge
  - docker

ansible_playbook: "deploy-proxy-stack"
```

### Secrets required

Add to `.env.template` and `.env`:

```bash
CF_DNS_API_TOKEN=              # Cloudflare API token, Zone:DNS:Edit for gibbsgreatly.xyz
```

A dedicated scoped token is preferred over reusing the NPM token. Create at dash.cloudflare.com → My Profile → API Tokens → Create Token → Edit zone DNS (scope to gibbsgreatly.xyz only).

### Traefik static configuration

Key settings in `traefik.yml`:

```yaml
api:
  dashboard: true
  insecure: false  # dashboard only via HTTPS

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

certificatesResolvers:
  letsencrypt:
    acme:
      # Use LE staging CA for all pve-test dev passes to avoid rate limits.
      # Remove the caServer line (or switch to production URL) only when
      # promoting to the main branch or running a final validation pass.
      caServer: "https://acme-staging-v02.api.letsencrypt.org/directory"
      email: "admin@gibbsgreatly.xyz"
      storage: "/certs/letsencrypt/acme.json"
      dnsChallenge:
        provider: cloudflare
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"

  # step-ca resolver — pre-configured, inactive until task 04-04 (step-ca) completes.
  # Traefik will not contact this CA until a route explicitly requests it.
  step-ca:
    acme:
      caServer: "https://10.57.1.11/acme/acme/directory"
      email: "admin@gibbsgreatly.xyz"
      storage: "/certs/step-ca/acme.json"
      httpChallenge:
        entryPoint: web  # step-ca connects back to Traefik:80 to complete the challenge
        # Requires MikroTik policy: mgmt_seg → edge_seg tcp/80 (see pve-test.yaml)

providers:
  docker:
    exposedByDefault: false
  file:
    directory: "/etc/traefik/dynamic/"
    watch: true
```

Both ACME storage paths (`/certs/letsencrypt/acme.json` and `/certs/step-ca/acme.json`) must be created with mode `0600` before Traefik starts.

### Authentik forward-auth middleware

Add to `traefik/dynamic/authentik.yml`:

```yaml
http:
  middlewares:
    authentik:
      forwardAuth:
        address: "http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik"
        trustForwardHeader: true
        authResponseHeaders:
          - X-authentik-username
          - X-authentik-groups
          - X-authentik-email
```

Apply this middleware to any internal dashboard or sensitive service.

### Wildcard TLS configuration

Add to `traefik/dynamic/certs.yml` to request the wildcard cert from Let's Encrypt at startup:

```yaml
tls:
  stores:
    default:
      defaultGeneratedCert:
        resolver: letsencrypt
        domain:
          main: "gibbsgreatly.xyz"
          sans:
            - "*.gibbsgreatly.xyz"
```

### What to expose (initial scope)

Only expose:
- Traefik dashboard (via HTTPS + Authentik SSO), cert from `letsencrypt` resolver
- Nothing else in Phase 04 — application stacks are migrated in Phase 06

---

## Service 3 — step-ca (internal PKI)

### Overview

step-ca is an automated Certificate Authority for X.509 and SSH certificates. It is deployed **after Traefik** because Traefik is already running and functional on Let's Encrypt certs. step-ca adds the internal resolver as a second option for management-plane and service-to-service TLS.

Deploying step-ca after Traefik means:
- Traefik is never blocked on an internal CA being available
- The `step-ca` resolver in Traefik activates automatically once step-ca is online and the homelab root CA is distributed
- No browser ever receives a step-ca cert — only routes explicitly assigned `certresolver=step-ca` will use it

Reference: [step-ca docs](https://smallstep.com/docs/step-ca)

### Stack file

Create `terraform/lxc/stacks/step-ca-stack/stack.yaml`:

```yaml
# step-ca internal certificate authority — management zone
hostname: step-ca
ip_address: "10.57.1.11/24"
gateway: "10.57.1.1"
vmid: 152
cores: 1
memory: 512
swap: 256
rootfs_size: 8
rootfs_storage: infrastructure-containers
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - step-ca
  - pki
  - infrastructure

ansible_playbook: "deploy-step-ca"
```

### Secrets required

```bash
STEP_CA_PASSWORD=              # password protecting the root CA key
STEP_CA_PROVISIONER_PASSWORD=  # ACME/JWK provisioner password
```

Add both to `.env.template` and `.env`.

### Ansible playbook

Create `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`.

1. Install `step-ca` binary from Smallstep GitHub releases (pin version)
2. Install `step` CLI tool (same release)
3. Run `step ca init` to bootstrap the CA:
   ```bash
   step ca init \
     --name "Homelab CA" \
     --dns "step-ca,10.57.1.11" \
     --address ":443" \
     --provisioner "acme" \
     --password-file /etc/step-ca/password.txt
   ```
4. Install as a systemd service
5. Export the root CA cert to `certs/homelab-root.crt` in the repository

### CA trust distribution

The homelab root CA is distributed only to managed services — not to browsers or end-user devices. The trust scope is:

| Target | Why |
|---|---|
| Traefik container | Validates backend certs when proxying to step-ca-issued services |
| Ansible control machine | Enables `validate_certs: true` on Proxmox, Harbor, Authentik API calls |
| Proxmox hosts | Validates step-ca-issued certs on management endpoints |
| Each new LXC (via base role) | Service-to-service calls without cert warnings |

Distribution is handled by a single task added to the base LXC Ansible role:

```yaml
- name: Trust homelab root CA
  copy:
    src: certs/homelab-root.crt
    dest: /usr/local/share/ca-certificates/homelab-root.crt
  notify: update-ca-certificates
```

This propagates automatically to every container deployed from that point forward.

To distribute manually after step-ca is running:

```bash
# Fetch the root cert
step ca root certs/homelab-root.crt --ca-url https://10.57.1.11

# Push to Traefik container
ansible-playbook -i "10.57.2.10," \
  terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

# Push to Proxmox host
ansible-playbook -i "192.168.1.40," \
  terraform/lxc/ansible/playbooks/trust-homelab-ca.yml
```

### Activating the step-ca resolver in Traefik

The `step-ca` resolver block is already present in `traefik.yml` from task 04-03. No Traefik config change is needed. Once the homelab root CA is trusted by the Traefik container and step-ca is online, any route that specifies `certresolver=step-ca` will begin receiving certs from the internal CA.

Verify the resolver is reachable from the Traefik container:

```bash
pct exec 153 -- curl -s --cacert /usr/local/share/ca-certificates/homelab-root.crt \
  https://10.57.1.11/acme/acme/directory | jq .
# Expected: ACME directory JSON
```

---

## Service 4 — Monitoring (VictoriaMetrics + Grafana + Loki)

Deploy last — highest resource usage of the Phase 04 services.

### Stack file

Create `terraform/lxc/stacks/monitoring-stack/stack.yaml`:

```yaml
# Monitoring: VictoriaMetrics + Grafana + Loki — management zone
hostname: monitoring-stack
ip_address: "10.57.1.12/24"
gateway: "10.57.1.1"
vmid: 154
cores: 2
memory: 1536
swap: 1024
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "50G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - monitoring
  - grafana
  - loki
  - victoria-metrics
  - infrastructure
  - docker

ansible_playbook: "deploy-monitoring-stack"
portainer_agent: true
```

### Compose services

```yaml
services:
  victoriametrics:
    image: 10.57.3.10/dockerhub/victoriametrics/victoria-metrics:<version>
    ports:
      - "8428:8428"
    volumes:
      - vm-data:/storage
    command:
      - "--storageDataPath=/storage"
      - "--retentionPeriod=90d"

  grafana:
    image: 10.57.3.10/dockerhub/grafana/grafana-oss:<version>
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GRAFANA_ADMIN_PASSWORD}"
      GF_AUTH_GENERIC_OAUTH_ENABLED: "true"  # Authentik OIDC integration
      # ... Authentik OIDC vars (configure after Authentik is up)

  loki:
    image: 10.57.3.10/dockerhub/grafana/loki:<version>
    ports:
      - "3100:3100"
    volumes:
      - loki-data:/loki

  promtail:
    image: 10.57.3.10/dockerhub/grafana/promtail:<version>
    volumes:
      - /var/log:/var/log:ro
      - ./promtail-config.yml:/etc/promtail/config.yml
```

### Secrets required

```bash
GRAFANA_ADMIN_PASSWORD=        # initial admin password
GRAFANA_OAUTH_CLIENT_SECRET=   # from Authentik OIDC provider config
```

### Initial datasource setup

After deployment, configure datasources in Grafana:
1. VictoriaMetrics: `http://victoriametrics:8428`
2. Loki: `http://loki:3100`

Provision default dashboards for:
- Proxmox node metrics (via node_exporter on pve-test)
- Docker container metrics (via cAdvisor)
- Harbor metrics
- NetBox metrics

### Exporters

Deploy `node_exporter` on each LXC (or as a Docker container). Add a scrape config to VictoriaMetrics for each LXC IP.

---

## Commit strategy

Create a short-lived branch for each service (`feat/authentik-stack`, `feat/proxy-stack`, `feat/step-ca`, `feat/monitoring-stack`), merge to `dev/pve-test` after each service passes its health checks.

After all services are deployed and healthy:

```bash
git push origin dev/pve-test
```

Update NetBox to record all new services, IPs, and their relationships.

---

## Acceptance criteria

### Authentik
- [ ] LXC `authentik-stack` (VMID 150) running at `10.57.1.10`
- [ ] `curl http://10.57.1.10:9000/-/health/ready/` returns HTTP 204
- [ ] Admin UI accessible at `http://10.57.1.10:9000`
- [ ] Initial admin user created

### Reverse proxy
- [ ] LXC `proxy-stack` (VMID 153) running at `10.57.2.10`
- [ ] `curl -o /dev/null -w "%{http_code}" http://10.57.2.10` returns 301 or 302
- [ ] Traefik dashboard accessible via HTTPS with Authentik SSO gate
- [ ] TLS cert for dashboard issued by Let's Encrypt (valid in browser without CA trust)
- [ ] HTTP → HTTPS redirect working
- [ ] Authentik forward-auth middleware configured in `dynamic/authentik.yml`
- [ ] `step-ca` resolver block present in `traefik.yml` (inactive until task 04-04)

### step-ca
- [ ] LXC `step-ca` (VMID 152) running at `10.57.1.11`
- [ ] `step ca health --ca-url https://10.57.1.11` returns OK
- [ ] Root CA cert saved to `certs/homelab-root.crt` in repository
- [ ] Homelab root CA distributed to Traefik container and Proxmox host
- [ ] Traefik `step-ca` resolver can reach ACME directory: `pct exec 153 -- curl -sk https://10.57.1.11/acme/acme/directory` returns JSON
- [ ] At least one internal management endpoint issued a cert from step-ca

### Monitoring
- [ ] LXC `monitoring-stack` (VMID 154) running at `10.57.1.12`
- [ ] Grafana accessible at `http://10.57.1.12:3000` (and via proxy)
- [ ] VictoriaMetrics scraping at least pve-test node_exporter
- [ ] Loki receiving logs from at least one LXC
- [ ] Grafana datasources for VictoriaMetrics and Loki configured

### Overall
- [ ] All stacks registered in NetBox (IPs, services, relationships)
- [ ] Grafana admin login works via Authentik OIDC
- [ ] `dmesg | grep -i oom` on pve-test host shows no new OOM events
- [ ] All stacks survive a `pct restart <vmid>` and come back healthy
- [ ] No browser receives a step-ca cert — all browser-facing routes verified against Let's Encrypt issuer
