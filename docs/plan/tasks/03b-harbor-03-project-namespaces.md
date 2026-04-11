# 03b-harbor-03 — Create Harbor service project namespaces

## Status

PENDING

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## Prerequisites

- Task 03b-02 complete: Harbor postconfigure verified, Trivy healthy
- `HARBOR_ADMIN_PASSWORD` set in `.env`

## Objective

Seven service-level Harbor projects exist (`infrastructure`, `netbox`, `harbor`, `authentik`, `monitoring`, `apps`, `chainloop`), all configured with `auto_scan: true` and `prevent_vul: true` at CRITICAL severity.

## Scope

- Create 7 projects via Harbor API
- Verify all projects exist and have correct metadata

## Out of Scope

- Proxy cache projects (already created by `harbor_postconfigure` in task 03b-02)
- GC schedule (task 03b-04)
- Image pre-pull (task 03b-05)
- Harbor replication policies (future work)

## Inputs

- `HARBOR_ADMIN_PASSWORD` from `.env`
- `docs/plan/phase-03b-harbor-setup.md` — Part B for project list and API payload

## Expected Outputs

- 7 new projects created in Harbor (no file changes)

## Constraints and Conventions

- All projects must be private (`public: false`)
- `auto_scan: true` — scan every image on push
- `prevent_vul: true` with `severity: critical` — block pulls of CRITICAL-vulnerability images
- Creation is idempotent via API: a 409 (already exists) is not an error
- The Harbor API URL is `http://192.168.1.10` (not HTTPS — self-signed cert in homelab)

## Acceptance Criteria

- [ ] All 7 projects exist: `infrastructure`, `netbox`, `harbor`, `authentik`, `monitoring`, `apps`, `chainloop`
- [ ] Each project has `auto_scan: true` and `prevent_vul: true` (severity: critical)
- [ ] `curl .../api/v2.0/projects | jq '.[].name'` lists all 7 names

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Create 7 service-level project namespaces in Harbor via its REST API.

STEP 1 — Source environment:
  source /home/steve/git/proxmox-homelab/.env

STEP 2 — Create projects (loop):
  for PROJECT in infrastructure netbox harbor authentik monitoring apps chainloop; do
    curl -sk -X POST \
      -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      -H "Content-Type: application/json" \
      "http://192.168.1.10/api/v2.0/projects" \
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

  Note: A 409 response means the project already exists — that is idempotent and fine.

STEP 3 — Verify all 7 projects exist:
  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/projects" | jq '.[].name'
  # Expected: shows infrastructure, netbox, harbor, authentik, monitoring, apps, chainloop
  # (plus any pre-existing proxy cache projects like dockerhub, ghcr, quay, lscr)

STEP 4 — Spot-check metadata on one project:
  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/projects/authentik" | jq '.metadata'
  # Expected: {"auto_scan":"true","prevent_vul":"true","severity":"critical","public":"false"}

DONE WHEN: All 7 projects verified. No code changes — no commit needed.
Proceed to task 03b-harbor-04-gc-robot-credentials.md.
```
