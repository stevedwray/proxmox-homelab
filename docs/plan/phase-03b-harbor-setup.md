# Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## Goal

Configure Harbor (deployed on pve-test at `10.57.3.10`) as the single internal image
registry before any new services are deployed. This phase:

1. Runs `harbor_postconfigure` to (re-)apply proxy caches, robot account, scan-on-push,
   and Trivy schedule (these were applied to the pve instance in PR #7 and must run again
   against the fresh pve-test Harbor)
2. Creates service-level project namespaces not handled by `harbor_postconfigure`
3. Configures the GC (garbage collection) schedule
4. Stores the robot account credentials in `.env.template`
5. Pre-pulls Phase 04 images so they are scanned before deployment

**From Phase 04 onwards, all compose files reference `10.57.3.10/...` — never upstream
registries directly.**

## Live task docs

- [03b-harbor-01 — Deploy Harbor registry stack on infra_seg](tasks/03b-harbor-01-deploy-harbor.md)
- [03b-netbox-01 — Deploy NetBox IPAM on infra_seg](tasks/03b-netbox-01-deploy-netbox.md)

The rest of this phase document covers Harbor post-deployment configuration work that
follows once the base Harbor stack is healthy.

## Prerequisites

- Phase 00b complete: Portainer running at `10.57.1.20` on `mgmt_seg`
- Phase 01 complete: ci-runner-01 running on pve-test
- **Harbor LXC deployed to pve-test** via:
  ```bash
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/harbor-stack
  terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i terraform/lxc/stacks/harbor-stack/inventory.yml \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
  ```
  Harbor should be healthy at `http://10.57.3.10` (port 80) before continuing.
  Login with `admin` / `HARBOR_ADMIN_PASSWORD` from `.env` to verify.
- `HARBOR_ADMIN_PASSWORD` is set in `.env`

> **Note on prior state**: When Harbor was originally deployed to `pve` (PR #7),
> `harbor_postconfigure` ran and configured proxy caches, a CI robot account, scan-on-push,
> and a nightly scan schedule. Those settings live in Harbor's database. After the pve-test
> wipe and fresh Harbor deploy, **none of those settings exist** in the new instance.
> Part A re-applies them idempotently.

## Related GreenField sections

- GreenField §5 (Harbor as single internal registry)
- GreenField §7 (Trivy IaC and image scanning)

---

## Part A — Run harbor_postconfigure

`harbor_postconfigure` is an idempotent Ansible role that configures:
- Docker Hub proxy endpoint and `dockerhub` proxy project
- Additional proxy endpoints and projects: `ghcr`, `quay`, `lscr`
- CI robot account `robot$ci-runner` (system-level, push/pull on all projects, never expires)
- Scan-on-push enabled globally
- Nightly full-scan schedule (`0 2 * * *`)

The `deploy-harbor-stack.yml` playbook already includes this role. If it ran cleanly during
the `terragrunt apply` + playbook step in Prerequisites, **this step is already done**.
Verify by checking Harbor UI: **Administration → Robot Accounts** should list `robot$ci-runner`.

If the play was skipped or failed, re-run just the postconfigure role:

```bash
source .env && source .env.pve-test
ansible-playbook \
  -i terraform/lxc/stacks/harbor-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml \
  --tags postconfigure
```

If the playbook does not have a `postconfigure` tag, run the full playbook — the role is
idempotent.

### Verify Trivy is the active scanner

Trivy is the only scanner bundled with Harbor; no action is needed to enable it. Confirm
it is healthy:

```bash
source .env
curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "http://10.57.3.10/api/v2.0/scanners" | jq '.[] | {name, is_default, health}'
# Expected: {"name":"Trivy", "is_default":true, "health":"healthy"}
```

If the vulnerability database is stale, trigger an update:

```bash
curl -sk -X POST \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "http://10.57.3.10/api/v2.0/system/scanAll/schedule" \
  -H "Content-Type: application/json" \
  -d '{"schedule":{"type":"Manual"}}'
```

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

### Create via API

```bash
source /home/steve/git/proxmox-homelab/.env

for PROJECT in infrastructure netbox harbor authentik monitoring apps; do
  curl -sk -X POST \
    -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    -H "Content-Type: application/json" \
    "http://10.57.3.10/api/v2.0/projects" \
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
curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "http://10.57.3.10/api/v2.0/projects" | \
  jq '.[].name'
```

---

## Part C — Update .env.template with robot credentials

When `harbor_postconfigure` creates the `robot$ci-runner` account for the first time, it
prints the generated secret to the console and attempts to save it to Bitwarden (if the
Bitwarden CLI is unlocked). The credentials must also be added to `.env.template`:

```bash
# Harbor registry — robot account for CI and internal pulls
HARBOR_ROBOT_USER=              # robot$ci-runner
HARBOR_ROBOT_PASSWORD=          # token generated by harbor_postconfigure — __FROM_BITWARDEN__

# Harbor admin (already exists — verify it's present)
HARBOR_ADMIN_PASSWORD=          # __FROM_BITWARDEN__
```

Add the same two variables as GitHub Actions repository secrets:
- `HARBOR_ROBOT_USER`
- `HARBOR_ROBOT_PASSWORD`

Verify the robot token is valid:

```bash
source /home/steve/git/proxmox-homelab/.env
echo "${HARBOR_ROBOT_PASSWORD}" | \
  docker login 10.57.3.10 -u "${HARBOR_ROBOT_USER}" --password-stdin
# Expected: Login Succeeded
```

### Image reference pattern (for Phase 04 onwards)

All compose files reference images via Harbor. This applies from Phase 04 onwards:

| Upstream image | Via Harbor proxy |
|---|---|
| `docker.io/library/postgres:16-alpine` | `10.57.3.10/dockerhub/library/postgres:16-alpine` |
| `ghcr.io/goauthentik/server:2024.12.3` | `10.57.3.10/ghcr/goauthentik/server:2024.12.3` |
| `docker.io/grafana/grafana-oss:11.x` | `10.57.3.10/dockerhub/grafana/grafana-oss:11.x` |

---

## Part D — Configure GC schedule

The nightly Trivy scan schedule is already set by `harbor_postconfigure`. The remaining
schedule to configure manually is the **Garbage Collection** (GC) sweep that removes
untagged artifacts and frees disk space on the 100 GB Harbor volume.

**Harbor UI → Administration → Garbage Collection → GC Schedule**

Set to weekly (e.g., `0 3 * * 0` — Sunday 3 AM).

Via API:

```bash
source /home/steve/git/proxmox-homelab/.env
curl -s -X PUT \
  -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  "http://10.57.3.10/api/v2.0/system/gc/schedule" \
  -d '{
    "schedule": {
      "type": "Custom",
      "cron": "0 3 * * 0"
    }
  }'
```

---

## Part E — Pre-pull Phase 04 images

Before deploying Phase 04 services, pull each image through the Harbor proxy so it is
scanned and cached. Phase 04 Ansible playbooks can then use `10.57.3.10/...` refs without
hitting upstream registries at deploy time.

Run from the workstation or ci-runner-01:

```bash
source /home/steve/git/proxmox-homelab/.env
echo "${HARBOR_ROBOT_PASSWORD}" | \
  docker login 10.57.3.10 -u "${HARBOR_ROBOT_USER}" --password-stdin

# Authentik — check https://github.com/goauthentik/authentik/releases for latest
AUTHENTIK_VERSION="2024.12.3"
docker pull 10.57.3.10/ghcr/goauthentik/server:${AUTHENTIK_VERSION}
docker pull 10.57.3.10/dockerhub/library/postgres:16-alpine
docker pull 10.57.3.10/dockerhub/library/redis:alpine

# step-ca — native binary install, no Docker image needed

# Traefik — check https://github.com/traefik/traefik/releases
TRAEFIK_VERSION="v3.3"
docker pull 10.57.3.10/dockerhub/library/traefik:${TRAEFIK_VERSION}

# Monitoring stack — check release pages for latest versions
GRAFANA_VERSION="11.5.2"
VM_VERSION="v1.101.0"
LOKI_VERSION="3.4.2"
PROMTAIL_VERSION="3.4.2"

docker pull 10.57.3.10/dockerhub/grafana/grafana-oss:${GRAFANA_VERSION}
docker pull 10.57.3.10/dockerhub/victoriametrics/victoria-metrics:${VM_VERSION}
docker pull 10.57.3.10/dockerhub/grafana/loki:${LOKI_VERSION}
docker pull 10.57.3.10/dockerhub/grafana/promtail:${PROMTAIL_VERSION}
```

Harbor scans each image automatically after pull. Wait a few minutes, then check for
CRITICAL findings before proceeding to Phase 04:

```bash
source /home/steve/git/proxmox-homelab/.env
# Example: check Authentik scan result
curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
  "http://10.57.3.10/api/v2.0/projects/ghcr/repositories/goauthentik%2Fserver/artifacts?with_scan_overview=true" | \
  jq '.[0].scan_overview'
```

Do not deploy a service with CRITICAL-severity findings. Check whether a newer patch version
is available first.

---

## Commit

```bash
cd /home/steve/git/proxmox-homelab
git checkout -b feat/harbor-config dev/pve-test

# Stage .env.template changes:
git add .env.template

git commit -m "chore(harbor): project namespaces, robot credentials, GC schedule, pre-pull images

- Project namespaces created: infrastructure, netbox, harbor, authentik, monitoring, apps
- HARBOR_ROBOT_USER and HARBOR_ROBOT_PASSWORD added to .env.template
- GC schedule configured (weekly, Sunday 3 AM)
- Phase 04 images pre-pulled and scanned via Harbor proxy"

git push origin feat/harbor-config
git checkout dev/pve-test
git merge feat/harbor-config
git push origin dev/pve-test
```

---

## Acceptance criteria

**Part A — harbor_postconfigure**
- [ ] `robot$ci-runner` visible in Harbor UI → Administration → Robot Accounts
- [ ] Proxy registry endpoints exist: `docker-hub`, `ghcr`, `quay`, `lscr`
- [ ] Proxy projects exist: `dockerhub`, `ghcr`, `quay`, `lscr`
- [ ] Scan-on-push enabled (Harbor UI → Administration → Configuration → Security)
- [ ] Trivy shows as **Healthy** and is the active scanner
- [ ] Vulnerability DB last updated within 24 hours

**Part B — Project namespaces**
- [ ] Projects exist: `infrastructure`, `netbox`, `harbor`, `authentik`, `monitoring`, `apps`
- [ ] All projects have `auto_scan: true` and `prevent_vul: true` (severity: critical)

**Part C — Robot credentials**
- [ ] `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` in `.env.template`
- [ ] `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` added as GitHub Actions secrets
- [ ] `docker login 10.57.3.10 -u robot$ci-runner` succeeds

**Part D — GC schedule**
- [ ] GC schedule configured: weekly, Sunday 3 AM (`0 3 * * 0`)

**Part E — Pre-pull images**
- [ ] All Phase 04 images pre-pulled and scan results visible in Harbor UI
- [ ] No CRITICAL-severity images in use — any findings investigated before Phase 04
