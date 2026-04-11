# 03b-harbor-04 — GC schedule, robot credentials in .env.template, GitHub secrets

## Status

PENDING

## Phase

Phase 03b — Harbor Configuration: Projects, Image Caching, and CI Robot

## Prerequisites

- Task 03b-02 complete: `robot$ci-runner` account exists in Harbor and its token is known
- Task 03b-03 complete: project namespaces created
- `HARBOR_ADMIN_PASSWORD` set in `.env`
- `HARBOR_ROBOT_PASSWORD` captured from `harbor_postconfigure` playbook run (or Bitwarden)

## Objective

The GC schedule is configured (weekly, Sunday 3 AM), `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` are in `.env.template`, both variables are added as GitHub Actions repository secrets, and `docker login 192.168.1.10 -u robot$ci-runner` succeeds.

## Scope

- Configure GC schedule via Harbor API
- Add `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` to `.env.template`
- Add both as GitHub Actions repository secrets via `gh secret set`
- Verify robot login works

## Out of Scope

- Pre-pulling Phase 04 images (task 03b-05)
- Changing Harbor project settings

## Inputs

- `HARBOR_ADMIN_PASSWORD` from `.env`
- `HARBOR_ROBOT_USER` = `robot$ci-runner`
- `HARBOR_ROBOT_PASSWORD` = token from `harbor_postconfigure` run
- `.env.template` — already in repo, add two lines
- `docs/plan/phase-03b-harbor-setup.md` — Parts C and D

## Expected Outputs

- `.env.template` — two new lines added
- No infrastructure changes
- GitHub Actions secrets set (not committed)

## Constraints and Conventions

- Robot credentials must be in `.env.template` as `__FROM_BITWARDEN__` placeholders — never hardcoded
- `HARBOR_ADMIN_PASSWORD` should already be in `.env.template`; do not add duplicates
- The robot token is sensitive — do not echo it to terminal; use `--stdin` with docker login
- Commit `.env.template` changes only; `.env` is never committed

## Acceptance Criteria

- [ ] GC schedule configured: `curl .../api/v2.0/system/gc/schedule` returns cron `0 3 * * 0`
- [ ] `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` present in `.env.template` as `__FROM_BITWARDEN__` placeholders
- [ ] `echo "${HARBOR_ROBOT_PASSWORD}" | docker login 192.168.1.10 -u "${HARBOR_ROBOT_USER}" --password-stdin` exits 0 with "Login Succeeded"
- [ ] GitHub Actions secrets `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` set in the repo
- [ ] Changes to `.env.template` committed and pushed

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Configure Harbor's GC schedule and store the robot account credentials in
.env.template and as GitHub Actions secrets.

BEFORE EDITING, READ:
  .env.template                                  (add placeholder lines — check for duplicates)
  docs/plan/phase-03b-harbor-setup.md            (Parts C and D)

STEP 1 — Source environment:
  source /home/steve/git/proxmox-homelab/.env

STEP 2 — Configure GC schedule (weekly, Sunday 3 AM):
  curl -sk -X PUT \
    -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    -H "Content-Type: application/json" \
    "http://192.168.1.10/api/v2.0/system/gc/schedule" \
    -d '{"schedule":{"type":"Custom","cron":"0 3 * * 0"}}'

  Verify: curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.1.10/api/v2.0/system/gc/schedule" | jq .schedule

STEP 3 — Verify robot credentials work:
  echo "${HARBOR_ROBOT_PASSWORD}" | \
    docker login 192.168.1.10 -u "${HARBOR_ROBOT_USER}" --password-stdin
  # Expected: Login Succeeded

  If HARBOR_ROBOT_USER or HARBOR_ROBOT_PASSWORD are not in .env, retrieve them from
  Bitwarden or re-run harbor_postconfigure to regenerate.

STEP 4 — Update .env.template (check file first for duplicates):
  Add if not already present:
    # Harbor robot account for CI pulls (set in .env, not committed)
    HARBOR_ROBOT_USER=              # robot$ci-runner
    HARBOR_ROBOT_PASSWORD=          # __FROM_BITWARDEN__

    # Harbor admin password (set in .env, not committed)
    HARBOR_ADMIN_PASSWORD=          # __FROM_BITWARDEN__

STEP 5 — Set GitHub Actions secrets:
  gh secret set HARBOR_ROBOT_USER --body "${HARBOR_ROBOT_USER}"
  gh secret set HARBOR_ROBOT_PASSWORD --body "${HARBOR_ROBOT_PASSWORD}"

  Verify:
  gh secret list | grep HARBOR
  # Expected: HARBOR_ROBOT_USER and HARBOR_ROBOT_PASSWORD listed

STEP 6 — Commit .env.template changes:
  git checkout -b feat/harbor-config dev/pve-test   # (or use existing feature branch)
  git add .env.template
  git commit -m "chore(harbor): add robot credentials and GC schedule to env template

- HARBOR_ROBOT_USER and HARBOR_ROBOT_PASSWORD placeholders added
- GC schedule configured: weekly Sunday 3 AM cron 0 3 * * 0
- GitHub Actions secrets set for CI harbor pulls"

  git push origin feat/harbor-config
  git checkout dev/pve-test && git merge feat/harbor-config
  git push origin dev/pve-test

DONE WHEN: GC schedule set, credentials in .env.template and GitHub, docker login succeeds.
Proceed to task 03b-harbor-05-pre-pull-images.md.
```
