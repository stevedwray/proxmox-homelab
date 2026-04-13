# 03b-harbor-05 — Pre-pull Phase 04 images and verify scan results

> Historical archived task. Useful for implementation history only.
> Do not use this as the current deployment procedure.
> Active docs under `docs/design/` and `docs/plan/` take precedence.

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/99

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## Prerequisites

- Task 03b-04 complete: robot credentials valid, `docker login 192.168.1.10` succeeds
- Docker installed on workstation or ci-runner-01
- Internet access from the machine running `docker pull`

## Objective

All Phase 04 service images are cached in Harbor (pulled through the proxy cache), Trivy scan results are visible in Harbor UI, and no CRITICAL-severity findings block deployment.

## Scope

- Log in to Harbor with robot credentials
- Pull each Phase 04 image via the Harbor proxy cache URL (`192.168.1.10/...`)
- Wait for Trivy scans to complete
- Review scan results for CRITICAL findings

## Out of Scope

- Deploying Phase 04 stacks (that is Phase 04)
- Mitigating vulnerabilities found (document and carry forward)
- Images for Phase 05/06 -- only Phase 04 images are pre-pulled here

## Inputs

- `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` from `.env`
- `HARBOR_ADMIN_PASSWORD` from `.env` (for scan result queries)
- `docs/plan/phase-03b-harbor-setup.md` — Part E for image list and version pins

## Expected Outputs

- Images cached in Harbor
- Scan results visible
- No file changes

## Constraints and Conventions

- Image versions are pinned — do not use `latest`; check release pages for the most recent stable version at time of pull if the versions in the phase doc are outdated
- Check scan results before proceeding to Phase 04; do not deploy an image with CRITICAL findings without first checking for a newer patch version
- Pull from `192.168.1.10/<project>/...` — never `docker.io` or `ghcr.io` directly at runtime

## Acceptance Criteria

- [ ] All Phase 04 images successfully pulled via Harbor proxy cache
- [ ] Scan overview visible in Harbor UI for each image
- [ ] No CRITICAL-severity images in use (or CRITICAL findings investigated and accepted with justification)

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Pre-pull all Phase 04 images through the Harbor proxy cache so that Trivy can scan
them before deployment. Verify no CRITICAL findings block Phase 04.

STEP 1 — Source environment and log in to Harbor:
  source /home/steve/git/proxmox-homelab/.env

  echo "${HARBOR_ROBOT_PASSWORD}" | \
    docker login 192.168.1.10 -u "${HARBOR_ROBOT_USER}" --password-stdin
  # Expected: Login Succeeded

STEP 2 — Pull Phase 04 images (check release pages for more recent stable versions):
  # Authentik — https://github.com/goauthentik/authentik/releases
  AUTHENTIK_VERSION="2024.12.3"    # update if newer stable available
  docker pull 192.168.1.10/ghcr/goauthentik/server:${AUTHENTIK_VERSION}

  # Shared dependencies for Authentik:
  docker pull 192.168.1.10/dockerhub/library/postgres:16-alpine
  docker pull 192.168.1.10/dockerhub/library/redis:alpine

  # Traefik — https://github.com/traefik/traefik/releases
  TRAEFIK_VERSION="v3.3"           # update if newer stable available
  docker pull 192.168.1.10/dockerhub/library/traefik:${TRAEFIK_VERSION}

  # Monitoring stack — check release pages for latest
  GRAFANA_VERSION="11.5.2"
  VM_VERSION="v1.101.0"
  LOKI_VERSION="3.4.2"
  PROMTAIL_VERSION="3.4.2"

  docker pull 192.168.1.10/dockerhub/grafana/grafana-oss:${GRAFANA_VERSION}
  docker pull 192.168.1.10/dockerhub/victoriametrics/victoria-metrics:${VM_VERSION}
  docker pull 192.168.1.10/dockerhub/grafana/loki:${LOKI_VERSION}
  docker pull 192.168.1.10/dockerhub/grafana/promtail:${PROMTAIL_VERSION}

  # Headscale and step-ca are native binary installs — no Docker images needed

STEP 3 — Wait ~2–3 minutes for Trivy scans to run, then check results:
  # Example: check Authentik scan (adjust project/repository path as needed)
  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/projects/ghcr/repositories/goauthentik%2Fserver/artifacts?with_scan_overview=true" | \
    jq '.[0].scan_overview'

  Also check in Harbor UI: browse to each project and look at the vulnerability badge on
  each image tag. Red = CRITICAL found.

STEP 4 — If CRITICAL findings:
  - Check if a newer patch version is available for that image
  - If newer version available, pull it: docker pull 192.168.1.10/.../image:newer-version
  - If no fix available, document the finding; do not block Phase 04 deployment if the
    finding is in a package not used by the service's relevant code path (use judgement)

DONE WHEN: All images cached in Harbor and no unresolved CRITICAL findings.
No commit needed — this is an infrastructure-only task.
Phase 03b is now complete. Phase 04 deployment is unblocked.
```
