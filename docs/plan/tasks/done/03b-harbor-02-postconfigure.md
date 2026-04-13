# 03b-harbor-02 — Run harbor_postconfigure (proxy caches, robot account, scanning)

> Historical archived task. Useful for implementation history only.
> Do not use this as the current deployment procedure.
> Active docs under `docs/design/` and `docs/plan/` take precedence.

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/96

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## Prerequisites

- Task 03b-01 complete: Harbor running at `http://192.168.1.10`, admin login works
- `HARBOR_ADMIN_PASSWORD` set in `.env`

## Objective

Harbor has proxy registry endpoints (`docker-hub`, `ghcr`, `quay`, `lscr`), a CI robot account (`robot$ci-runner`), scan-on-push enabled globally, and Trivy shows as healthy — all verified via the Harbor API.

## Scope

- Verify that `harbor_postconfigure` ran during task 03b-01 playbook execution
- If incomplete or skipped: re-run the playbook (full or with `--tags postconfigure`)
- Verify Trivy scanner health
- Trigger vulnerability DB update if stale

## Out of Scope

- Creating service-level project namespaces (task 03b-03)
- Robot credentials in `.env.template` (task 03b-04)
- GC schedule (task 03b-04)
- Image pre-pull (task 03b-05)

## Inputs

- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml` — check if `harbor_postconfigure` tag exists
- `HARBOR_ADMIN_PASSWORD` from `.env`
- `docs/plan/phase-03b-harbor-setup.md` — Part A for verification commands

## Expected Outputs

- No file changes
- Harbor configuration verified via API

## Constraints and Conventions

- `harbor_postconfigure` is idempotent — safe to re-run the full playbook
- The robot account token is only shown on first creation; if the playbook already ran and the token was not captured, a new robot account may need to be created manually (or the role re-run after deletion)
- Do not skip Trivy health verification — a stale vulnerability DB means scans are not meaningful

## Acceptance Criteria

- [ ] `robot$ci-runner` visible in Harbor UI → Administration → Robot Accounts
- [ ] Proxy endpoints exist: `docker-hub`, `ghcr`, `quay`, `lscr`
- [ ] Proxy projects exist: `dockerhub`, `ghcr`, `quay`, `lscr`
- [ ] Scan-on-push enabled (Harbor UI → Administration → Configuration → Security)
- [ ] Trivy shows as Healthy: `curl .../api/v2.0/scanners | jq '.[].health'` returns `"healthy"`
- [ ] Vulnerability DB last updated within 24 hours

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Verify that harbor_postconfigure ran correctly when Harbor was deployed. If any
configuration is missing, re-run the role to apply it.

STEP 1 — Source environment:
  source /home/steve/git/proxmox-homelab/.env

STEP 2 — Check robot account:
  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/robots" | jq '.[].name'
  # Expected: includes "robot$ci-runner"

STEP 3 — Check proxy registries/projects:
  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/registries" | jq '.[].name'
  # Expected: docker-hub, ghcr, quay, lscr (or similar names)

  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/projects" | jq '.[].name'
  # Expected: includes dockerhub, ghcr, quay, lscr

STEP 4 — Check Trivy:
  curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/scanners" | jq '.[] | {name, is_default, health}'
  # Expected: {"name":"Trivy","is_default":true,"health":"healthy"}

STEP 5 — If anything is missing, re-run harbor_postconfigure:
  cd /home/steve/git/proxmox-homelab
  source .env && source .env.pve-test
  # Try with postconfigure tag first:
  ansible-playbook \
    -i terraform/lxc/stacks/harbor-stack/inventory.yml \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml \
    --tags postconfigure
  # If no such tag exists, run the full playbook (it's idempotent):
  ansible-playbook \
    -i terraform/lxc/stacks/harbor-stack/inventory.yml \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 6 — If Trivy DB is stale, trigger an update:
  curl -sk -X POST \
    -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/system/scanAll/schedule" \
    -H "Content-Type: application/json" \
    -d '{"schedule":{"type":"Manual"}}'

DONE WHEN: robot$ci-runner exists, all 4 proxy registries/projects exist, and Trivy health
is "healthy". No commit needed — this is a verification task. Proceed to task 03b-03.
```
