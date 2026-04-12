# Phase 04 — Core Shared Services

## Goal

Deploy the foundational shared services that must exist before any application stacks are migrated:

1. **Authentik** — identity provider, SSO, MFA
2. **Headscale** — self-hosted Tailscale control server (admin VPN)
3. **step-ca** — internal certificate authority
4. **Reverse proxy** (Traefik or Caddy) — dedicated ingress edge
5. **Monitoring stack** — VictoriaMetrics + Grafana + Loki

Deploy in this order. Each depends on the previous: Authentik before the proxy (auth middleware), the proxy before monitoring dashboards are exposed, monitoring last (most resource-heavy).

## Prerequisites

- Phase 01 (CI runner) complete — self-hosted runner is online
- **Phase 02 (memory upgrade) complete** — pve-test must be at 32 GB before starting this phase
- **Phase 03b complete** — Harbor has Trivy scanner enabled, proxy cache projects configured, and Phase 04 images already pulled and scanned
- **Phase 03c complete** — apt-cacher-ng running at `192.168.1.35`; all LXC stacks deployed in this phase will route apt through the proxy automatically
- Harbor is running at `192.168.1.10` (deployed earlier)
- NetBox is running at `192.168.1.30` (deployed earlier)
- The stack deployment pattern is understood — see `terraform/lxc/stacks/harbor-stack/` and `terraform/lxc/stacks/netbox-stack/` as reference implementations
- `.env` is sourced with Proxmox API credentials

## Image reference convention

All compose files in this phase use Harbor proxy cache image references — **never direct Docker Hub or GHCR pulls at runtime**. Phase 03b pre-pulled and scanned all images listed below. The pattern is:

| Upstream | Via Harbor |
|---|---|
| `docker.io/library/postgres:16-alpine` | `192.168.1.10/dockerhub/library/postgres:16-alpine` |
| `ghcr.io/goauthentik/server:<ver>` | `192.168.1.10/ghcr/goauthentik/server:<ver>` |
| `docker.io/grafana/grafana-oss:<ver>` | `192.168.1.10/dockerhub/grafana/grafana-oss:<ver>` |
| `docker.io/library/traefik:<ver>` | `192.168.1.10/dockerhub/library/traefik:<ver>` |
| `docker.io/victoriametrics/victoria-metrics:<ver>` | `192.168.1.10/dockerhub/victoriametrics/victoria-metrics:<ver>` |
| `docker.io/grafana/loki:<ver>` | `192.168.1.10/dockerhub/grafana/loki:<ver>` |

Always use the Harbor proxy address in compose files. If an image is not yet in Harbor, pull it through the proxy first (see Phase 03b Part E).

## Networking / IP allocation

All new stacks go on VLAN/zone `mgmt_seg` (management plane). Use the next available IPs in the `192.168.1.x/24` range (check NetBox for current allocations before assigning):

| Service | Suggested IP | VMID | Notes |
|---|---|---|---|
| Authentik | `192.168.1.46` | 150 | |
| Headscale | `192.168.1.41` | 151 | |
| step-ca | `192.168.1.42` | 152 | |
| Reverse proxy | `192.168.1.43` | 153 | Edge — also needs a public IP or port-forward |
| Monitoring | `192.168.1.44` | 154 | |

**Verify these IPs are unallocated in NetBox before using them.**

```bash
curl -s -H "Authorization: Token <NETBOX_TOKEN>" \
  "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.46" | jq .count
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
ip_address: "192.168.1.46/24"
gateway: "192.168.1.1"
vmid: 150
cores: 2
memory: 3072
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
    image: 192.168.1.10/dockerhub/library/postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: "${AUTHENTIK_POSTGRES_PASSWORD}"
      POSTGRES_USER: authentik
      POSTGRES_DB: authentik
    volumes:
      - database:/var/lib/postgresql/data

  redis:
    image: 192.168.1.10/dockerhub/library/redis:alpine
    command: --save 60 1 --loglevel warning

  server:
    image: 192.168.1.10/ghcr/goauthentik/server:2024.12.3   # pin to specific version
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
    image: 192.168.1.10/ghcr/goauthentik/server:2024.12.3   # same version as server
    command: worker
    environment: *server-env  # reference server env block
    depends_on:
      - postgresql
      - redis
```

### Initial configuration

After deployment, access `http://192.168.1.46:9000/if/flow/initial-setup/` to set the initial admin password. Then:

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
  -i "192.168.1.46," \
  terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
  --extra-vars "authentik_secret_key=${AUTHENTIK_SECRET_KEY} authentik_postgres_password=${AUTHENTIK_POSTGRES_PASSWORD}"
```

### Validation

```bash
curl -s http://192.168.1.46:9000/-/health/live/
# Expected: HTTP 204 (no body)

curl -s http://192.168.1.46:9000/-/health/ready/
# Expected: HTTP 204 (means DB and Redis connections healthy)
```

---

## Service 2 — Headscale (admin VPN)

### Overview

Headscale is a self-hosted implementation of the Tailscale control plane. It provides WireGuard-based VPN access for admin endpoints into the management network without exposing any service ports publicly.

Reference: [Headscale docs](https://headscale.net)

### Stack file

Create `terraform/lxc/stacks/headscale-stack/stack.yaml`:

```yaml
# Headscale self-hosted Tailnet control server — management zone
hostname: headscale-stack
ip_address: "192.168.1.41/24"
gateway: "192.168.1.1"
vmid: 151
cores: 1
memory: 512
swap: 256
rootfs_size: 8
rootfs_storage: infrastructure-containers
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - headscale
  - vpn
  - infrastructure

ansible_playbook: "deploy-headscale"
```

### Secrets required

```bash
HEADSCALE_NOISE_PRIVATE_KEY=  # auto-generated by Headscale on first run
```

No pre-generated secrets needed — Headscale generates its own keys. The LXC itself needs no Docker; Headscale can be installed as a native binary.

### Configuration

Key `config.yaml` settings:
- `server_url`: the publicly reachable URL for the Headscale server (or Tailscale client DNS name). For homelab use, this can be the LAN IP initially: `http://192.168.1.41:8080`
- `listen_addr`: `0.0.0.0:8080`
- `metrics_listen_addr`: `0.0.0.0:9090`
- `db_type`: `sqlite3`
- `db_path`: `/var/lib/headscale/db.sqlite`

### Ansible playbook

Create `terraform/lxc/ansible/playbooks/deploy-headscale.yml`.

Install Headscale as a systemd service (native binary, not Docker):
1. Download the Headscale binary from GitHub releases (pin version)
2. Create `/etc/headscale/config.yaml` from a template
3. Create a systemd unit at `/etc/systemd/system/headscale.service`
4. Enable and start the service

### Initial setup

After deployment:

```bash
# SSH into the LXC:
ssh root@192.168.1.41

# Create a namespace (user):
headscale namespaces create homelab

# Generate a pre-auth key for your workstation:
headscale preauthkeys create --namespace homelab --expiration 1h
```

On your workstation, install the Tailscale client and log in:
```bash
tailscale up --login-server http://192.168.1.41:8080 --authkey <preauth-key>
```

### Validation

```bash
# Check Headscale service:
systemctl status headscale

# List registered machines:
headscale nodes list

# From workstation (after joining):
tailscale status
```

---

## Service 3 — step-ca (internal PKI)

### Overview

step-ca is an automated Certificate Authority for X.509 and SSH certificates. Deploying it eliminates the need for self-signed certs and `validate_certs: false` in Ansible playbooks for internal services over time.

Reference: [step-ca docs](https://smallstep.com/docs/step-ca)

### Stack file

Create `terraform/lxc/stacks/step-ca-stack/stack.yaml`:

```yaml
# step-ca internal certificate authority — management zone
hostname: step-ca
ip_address: "192.168.1.42/24"
gateway: "192.168.1.1"
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
     --dns "step-ca,192.168.1.42" \
     --address ":443" \
     --provisioner "acme" \
     --password-file /etc/step-ca/password.txt
   ```
4. Install as a systemd service

### CA trust distribution

After step-ca is running, distribute the root CA cert to all LXCs and workstations:

```bash
# Get the root cert:
step ca root root.crt --ca-url https://192.168.1.42

# On each Debian LXC:
cp root.crt /usr/local/share/ca-certificates/homelab-root.crt
update-ca-certificates
```

Add a task to the base LXC Ansible role to trust the homelab CA root cert.

---

## Service 4 — Reverse proxy (Traefik)

### Overview

A dedicated reverse proxy LXC is the only ingress point from external networks into internal apps. Traefik is recommended for its dynamic container-discovery, built-in Let's Encrypt/ACME support, and Authentik forward-auth middleware.

### Stack file

Create `terraform/lxc/stacks/proxy-stack/stack.yaml`:

```yaml
# Traefik reverse proxy — edge / ingress
hostname: proxy-stack
ip_address: "192.168.1.43/24"
gateway: "192.168.1.1"
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

### Traefik configuration

Key settings in `traefik.yml` (static config):

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
  step-ca:
    acme:
      caServer: "https://192.168.1.42/acme/acme/directory"
      email: "admin@gibbsgreatly.xyz"
      storage: "/letsencrypt/acme.json"
      tlsChallenge: {}

providers:
  docker:
    exposedByDefault: false
  file:
    directory: "/etc/traefik/dynamic/"
    watch: true
```

### Authentik forward-auth middleware

Add to `traefik/dynamic/authentik.yml`:

```yaml
http:
  middlewares:
    authentik:
      forwardAuth:
        address: "http://192.168.1.46:9000/outpost.goauthentik.io/auth/traefik"
        trustForwardHeader: true
        authResponseHeaders:
          - X-authentik-username
          - X-authentik-groups
          - X-authentik-email
```

Apply this middleware to any internal dashboard or sensitive service.

### What to expose (initial scope)

Only expose:
- Traefik dashboard (via HTTPS + Authentik SSO)
- Nothing else in Phase 04 — application stacks are migrated in Phase 06

---

## Service 5 — Monitoring (VictoriaMetrics + Grafana + Loki)

Deploy last — highest resource usage of the Phase 04 services.

### Stack file

Create `terraform/lxc/stacks/monitoring-stack/stack.yaml`:

```yaml
# Monitoring: VictoriaMetrics + Grafana + Loki — management zone
hostname: monitoring-stack
ip_address: "192.168.1.44/24"
gateway: "192.168.1.1"
vmid: 154
cores: 2
memory: 3072
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
    image: victoriametrics/victoria-metrics:<version>
    ports:
      - "8428:8428"
    volumes:
      - vm-data:/storage
    command:
      - "--storageDataPath=/storage"
      - "--retentionPeriod=90d"

  grafana:
    image: grafana/grafana-oss:<version>
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GRAFANA_ADMIN_PASSWORD}"
      GF_AUTH_GENERIC_OAUTH_ENABLED: "true"  # Authentik OIDC integration
      # ... Authentik OIDC vars (configure after Authentik is up)

  loki:
    image: grafana/loki:<version>
    ports:
      - "3100:3100"
    volumes:
      - loki-data:/loki

  promtail:
    image: grafana/promtail:<version>
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

Create a short-lived branch for each service (`feat/authentik-stack`, `feat/headscale`, etc.), merge to `dev/pve-test` after each service passes its health checks.

After all five services are deployed and healthy:

```bash
git push origin dev/pve-test
```

Update NetBox to record all new services, IPs, and their relationships.

---

## Acceptance criteria

### Authentik
- [ ] LXC `authentik-stack` (VMID 150) running at `192.168.1.46`
- [ ] `curl http://192.168.1.46:9000/-/health/ready/` returns HTTP 204
- [ ] Admin UI accessible at `http://192.168.1.46:9000`
- [ ] Initial admin user created

### Headscale
- [ ] LXC `headscale-stack` (VMID 151) running at `192.168.1.41`
- [ ] `systemctl status headscale` is active
- [ ] Workstation can join the tailnet and `tailscale ping 192.168.1.46` succeeds

### step-ca
- [ ] LXC `step-ca` (VMID 152) running at `192.168.1.42`
- [ ] `step ca health --ca-url https://192.168.1.42` returns OK
- [ ] Root CA cert distributed to at least pve-test host
- [ ] At least one internal service issued a cert from step-ca

### Reverse proxy
- [ ] LXC `proxy-stack` (VMID 153) running at `192.168.1.43`
- [ ] Traefik dashboard accessible via HTTPS with Authentik SSO gate
- [ ] HTTP → HTTPS redirect working
- [ ] Authentik forward-auth middleware configured

### Monitoring
- [ ] LXC `monitoring-stack` (VMID 154) running at `192.168.1.44`
- [ ] Grafana accessible at `http://192.168.1.44:3000` (and via proxy)
- [ ] VictoriaMetrics scraping at least pve-test node_exporter
- [ ] Loki receiving logs from at least one LXC
- [ ] Grafana datasources for VictoriaMetrics and Loki configured

### Overall
- [ ] All five stacks registered in NetBox (IPs, services, relationships)
- [ ] Grafana admin login works via Authentik OIDC
- [ ] `dmesg | grep -i oom` on pve-test host shows no new OOM events
- [ ] All stacks survive a `pct restart <vmid>` and come back healthy
