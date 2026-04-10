# Phase 03b — Harbor Configuration: Trivy Scanner, Projects, and Image Caching

## Goal

Configure Harbor (already running at `192.168.1.10`) as the single internal image registry before any new services are deployed. This means:

1. Enabling Trivy as the built-in vulnerability scanner with scan-on-push
2. Creating project namespaces for each service category
3. Creating a CI robot account
4. Setting up proxy cache projects for upstream registries (Docker Hub, GHCR, etc.)
5. Mirroring the base images needed by Phase 04 services so those images are scanned and cached before deployment

**Any image pulled into Harbor from this point forward is automatically scanned.** From Phase 04 onwards, all compose files reference `192.168.1.10/...` — never upstream registries directly.

## Prerequisites

- Harbor is running and healthy at `192.168.1.10` (deploy completed in earlier work)
- Harbor admin credentials: `admin` / value of `HARBOR_ADMIN_PASSWORD` in `.env`
- `HARBOR_ADMIN_PASSWORD` is set in `.env`

## Related GreenField sections

- GreenField §5 (Harbor as single internal registry)
- GreenField §7 (Trivy IaC and image scanning)

---

## Part A — Enable Trivy scanner in Harbor

Trivy is bundled with Harbor and just needs to be activated.

### Via Harbor UI

1. Log into Harbor at `https://192.168.1.10` (or `http://` if TLS not yet configured)
2. Navigate to: **Administration → Interrogation Services → Scanners**
3. If Trivy is not listed, click **+ New Scanner** — internal Trivy is pre-bundled; it should already appear as `Trivy` with endpoint `harbor-core:8080`
4. Click the three-dot menu → **Set as Default**

Verify the scanner is healthy:
- Scanner status should show **Healthy**
- Vulnerability DB should show a recent update time. If the DB is stale, trigger an update: **Administration → Interrogation Services → Vulnerability → Update Now**

### Via API (scripted option)

```bash
source /home/steve/git/proxmox-homelab/.env

# Check existing scanners:
curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "https://192.168.1.10/api/v2.0/scanners" | jq '.[] | {name, url, health}'

# Set the built-in Trivy scanner as default (use the UUID returned above):
SCANNER_UUID="<uuid-from-above>"
curl -sk -X PATCH \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  "https://192.168.1.10/api/v2.0/scanners/${SCANNER_UUID}" \
  -d '{"is_default": true}'
```

---

## Part B — Create Harbor projects

Create dedicated namespaces for each category of images. Projects isolate images, allow per-project vulnerability policies, and prevent images from different trust levels from sharing a namespace.

### Projects to create

| Project name | Public | Description |
|---|---|---|
| `infrastructure` | No | Base OS images, tool images used by CI and Ansible |
| `netbox` | No | NetBox and its dependencies (postgres, valkey) |
| `harbor` | No | Harbor's own component images (for self-update) |
| `authentik` | No | Authentik server, worker, postgres, redis |
| `monitoring` | No | Grafana, VictoriaMetrics, Loki, Promtail |
| `apps` | No | Media stack, Pi-hole, Jellyfin, game servers |
| `chainloop` | No | Chainloop server images |

### Create via API

```bash
source /home/steve/git/proxmox-homelab/.env

for PROJECT in infrastructure netbox harbor authentik monitoring apps chainloop; do
  curl -sk -X POST \
    -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    -H "Content-Type: application/json" \
    "https://192.168.1.10/api/v2.0/projects" \
    -d "{
      \"project_name\": \"${PROJECT}\",
      \"metadata\": {
        \"public\": \"false\",
        \"auto_scan\": \"true\",
        \"prevent_vul\": \"true\",
        \"severity\": \"critical\"
      }
    }"
  echo "Created: ${PROJECT}"
done
```

Key metadata settings:
- `auto_scan: true` — scan every image on push
- `prevent_vul: true` — block pull of images with vulnerabilities at or above severity threshold
- `severity: critical` — block pulls only for CRITICAL findings (adjust to `high` as posture matures)

### Verify projects exist

```bash
curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "https://192.168.1.10/api/v2.0/projects" | \
  jq '.[].name'
```

---

## Part C — Set up proxy cache registries

Harbor can act as a pull-through cache for upstream registries. When a proxy project is configured, `docker pull 192.168.1.10/dockerhub/<image>:<tag>` pulls from Docker Hub the first time and caches the result locally in Harbor — and immediately scans it.

This is how we ensure all images are scanned: nothing is pulled from the internet at runtime; everything goes through Harbor.

### Create upstream registry endpoints

```bash
source /home/steve/git/proxmox-homelab/.env

# Docker Hub
curl -sk -X POST \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  "https://192.168.1.10/api/v2.0/registries" \
  -d '{
    "name": "docker-hub",
    "type": "docker-hub",
    "url": "https://hub.docker.com",
    "description": "Docker Hub pull-through cache"
  }'

# GitHub Container Registry
curl -sk -X POST \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  "https://192.168.1.10/api/v2.0/registries" \
  -d '{
    "name": "ghcr",
    "type": "github",
    "url": "https://ghcr.io",
    "description": "GitHub Container Registry pull-through cache"
  }'
```

### Create proxy cache projects

```bash
# Get the registry IDs created above:
DOCKERHUB_ID=$(curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "https://192.168.1.10/api/v2.0/registries" | \
  jq '.[] | select(.name=="docker-hub") | .id')

GHCR_ID=$(curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "https://192.168.1.10/api/v2.0/registries" | \
  jq '.[] | select(.name=="ghcr") | .id')

# Create proxy project for Docker Hub:
curl -sk -X POST \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  "https://192.168.1.10/api/v2.0/projects" \
  -d "{
    \"project_name\": \"dockerhub\",
    \"registry_id\": ${DOCKERHUB_ID},
    \"metadata\": {
      \"public\": \"false\",
      \"auto_scan\": \"true\",
      \"prevent_vul\": \"true\",
      \"severity\": \"critical\"
    }
  }"

# Create proxy project for GHCR:
curl -sk -X POST \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  "https://192.168.1.10/api/v2.0/projects" \
  -d "{
    \"project_name\": \"ghcr\",
    \"registry_id\": ${GHCR_ID},
    \"metadata\": {
      \"public\": \"false\",
      \"auto_scan\": \"true\",
      \"prevent_vul\": \"true\",
      \"severity\": \"critical\"
    }
  }"
```

With proxy projects in place, the image reference pattern changes:

| Upstream image | Via Harbor proxy |
|---|---|
| `docker.io/library/postgres:16-alpine` | `192.168.1.10/dockerhub/library/postgres:16-alpine` |
| `ghcr.io/goauthentik/server:2024.12.3` | `192.168.1.10/ghcr/goauthentik/server:2024.12.3` |
| `docker.io/grafana/grafana-oss:11.x` | `192.168.1.10/dockerhub/grafana/grafana-oss:11.x` |

---

## Part D — Create robot account for CI

The CI runner needs push/pull access to Harbor for the supply chain pipeline in Phase 05.

### Via Harbor UI

1. **Administration → Robot Accounts → + New Robot Account**
2. Name: `ci-runner`
3. Expiry: set a long expiry (e.g., 365 days) or no expiry for homelab
4. Permissions: grant **Push** and **Pull** on projects: `infrastructure`, `authentik`, `monitoring`, `apps`, `chainloop`
5. Save — copy the generated token immediately (it is only shown once)

### Store the credentials

Add to `.env` and `.env.template`:

```bash
# .env.template
HARBOR_ROBOT_USER=              # robot account username (format: robot$ci-runner)
HARBOR_ROBOT_PASSWORD=          # robot account token (generated in Harbor UI)
```

Add as GitHub Actions repository secrets:
- `HARBOR_ROBOT_USER`
- `HARBOR_ROBOT_PASSWORD`

Verify login works from the workstation:

```bash
source /home/steve/git/proxmox-homelab/.env
echo "${HARBOR_ROBOT_PASSWORD}" | \
  docker login 192.168.1.10 -u "${HARBOR_ROBOT_USER}" --password-stdin
# Expected: Login Succeeded
```

---

## Part E — Mirror Phase 04 images into Harbor

Before deploying Phase 04 services, pull each image through the Harbor proxy so it gets scanned and cached. This means Phase 04 Ansible playbooks can use `192.168.1.10/...` image refs from day one.

### Images needed for Phase 04

Run these from the workstation or the ci-runner-01 LXC:

```bash
source /home/steve/git/proxmox-homelab/.env
docker login 192.168.1.10 -u "${HARBOR_ROBOT_USER}" --password-stdin <<< "${HARBOR_ROBOT_PASSWORD}"

# Authentik — check https://github.com/goauthentik/authentik/releases for current version
AUTHENTIK_VERSION="2024.12.3"
docker pull 192.168.1.10/ghcr/goauthentik/server:${AUTHENTIK_VERSION}
docker pull 192.168.1.10/dockerhub/library/postgres:16-alpine
docker pull 192.168.1.10/dockerhub/library/redis:alpine

# Headscale — native binary install, no Docker image needed

# step-ca — native binary install, no Docker image needed

# Traefik
TRAEFIK_VERSION="v3.3"  # check https://github.com/traefik/traefik/releases
docker pull 192.168.1.10/dockerhub/library/traefik:${TRAEFIK_VERSION}

# Monitoring stack
GRAFANA_VERSION="11.5.2"  # check https://github.com/grafana/grafana/releases
VM_VERSION="v1.101.0"    # check https://github.com/VictoriaMetrics/VictoriaMetrics/releases
LOKI_VERSION="3.4.2"     # check https://github.com/grafana/loki/releases
PROMTAIL_VERSION="3.4.2"

docker pull 192.168.1.10/dockerhub/grafana/grafana-oss:${GRAFANA_VERSION}
docker pull 192.168.1.10/dockerhub/victoriametrics/victoria-metrics:${VM_VERSION}
docker pull 192.168.1.10/dockerhub/grafana/loki:${LOKI_VERSION}
docker pull 192.168.1.10/dockerhub/grafana/promtail:${PROMTAIL_VERSION}
```

After each `docker pull`, Harbor automatically scans the image. Wait a few minutes, then verify scan results:

```bash
# Check scan results for a specific image (e.g., Authentik):
curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "https://192.168.1.10/api/v2.0/projects/ghcr/repositories/goauthentik%2Fserver/artifacts?with_scan_overview=true" | \
  jq '.[0].scan_overview'
```

If CRITICAL vulnerabilities are found in an image, investigate before deploying that service. Check whether a newer patch version exists. Do not deploy a CRITICAL-vulnerable image into the lab.

---

## Part F — Schedule regular vulnerability DB updates

The Trivy vulnerability database bundled with Harbor needs to refresh periodically. Configure a schedule:

**Harbor UI → Administration → Interrogation Services → Vulnerability → Schedule**

Set to run at least daily (e.g., `0 2 * * *` — 2 AM daily).

This ensures the DB stays current. Stale DB = missed vulnerabilities.

Also configure a **sweep/GC schedule** to remove untagged artifacts and free disk space:

**Harbor UI → Administration → Garbage Collection → GC Schedule**

Set to run weekly (e.g., Sunday at 3 AM).

---

## Part G — Update .env.template

Ensure these new variables are in `.env.template`:

```bash
# Harbor registry — robot account for CI and internal pulls
HARBOR_ROBOT_USER=              # robot$ci-runner
HARBOR_ROBOT_PASSWORD=          # token generated in Harbor UI — FROM_BITWARDEN

# Harbor admin (already exists, verify it's present)
HARBOR_ADMIN_PASSWORD=          # __FROM_BITWARDEN__
```

---

## Commit

```bash
cd /home/steve/git/proxmox-homelab
git checkout -b feat/harbor-config dev/pve-test

# Stage any .env.template changes:
git add .env.template

git commit -m "chore(harbor): configure Trivy scanner, projects, proxy cache, and robot account

- Trivy enabled as default scanner with scan-on-push
- Projects created: infrastructure, netbox, harbor, authentik, monitoring, apps, chainloop
- Proxy cache projects: dockerhub, ghcr
- Robot account: robot\$ci-runner with push/pull on relevant projects
- Phase 04 images pre-pulled and scanned via Harbor proxy"

git push origin feat/harbor-config
git checkout dev/pve-test
git merge feat/harbor-config
git push origin dev/pve-test
```

---

## Acceptance criteria

- [ ] Trivy scanner appears as **Healthy** in Harbor UI → Administration → Interrogation Services → Scanners
- [ ] Trivy is set as the **default** scanner
- [ ] Vulnerability DB last updated within 24 hours
- [ ] Daily DB update schedule configured
- [ ] Projects exist: `infrastructure`, `netbox`, `harbor`, `authentik`, `monitoring`, `apps`, `chainloop`
- [ ] All projects have `auto_scan: true` and `prevent_vul: true` (severity: critical)
- [ ] Proxy registry endpoints configured for Docker Hub and GHCR
- [ ] Proxy projects (`dockerhub`, `ghcr`) created with scan-on-push
- [ ] `docker login 192.168.1.10 -u robot$ci-runner` succeeds
- [ ] `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` added to `.env.template`
- [ ] `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` added as GitHub Actions secrets
- [ ] All Phase 04 images pre-pulled through Harbor proxy and scan results visible in Harbor UI
- [ ] No CRITICAL-severity images being used — investigate any findings before Phase 04 deployment
- [ ] GC schedule configured (weekly)
