# 03-code-quality-08 — Integrate SonarCloud into CI security scan workflow

> Historical task packet.
> This document reflects the earlier CI and branch workflow.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## Phase

Phase 03 — Code Quality and Bug Fixes

## GitHub Issue

Not assigned yet.

## Prerequisites

- Phase 00 complete — branch is clean
- SonarCloud project `stevedwray_proxmox-homelab` exists at sonarcloud.io
  (configured in `sonar-project.properties`)
- `SONAR_TOKEN` added as a GitHub Actions repository secret

## Objective

SonarCloud analysis runs automatically on every push and pull request via the
`security-scan.yml` workflow. Currently `sonar-scanner` is only a manual pre-merge step
(documented in `CLAUDE.md`) — this task makes it a CI enforcement gate.

## Scope

- `.github/workflows/security-scan.yml` — add a `sonarcloud` job
- `sonar-project.properties` — remove hardcoded `sonar.branch.name=main` (the action
  sets branch context from git automatically)
- GitHub repository settings — add `SONAR_TOKEN` secret (manual step, not in code)
- Branch: `feat/ci-sonarcloud` off `baseline/teardown-validated`

## Out of Scope

- Resolving existing SonarCloud findings (those are Phase 03 batches 1–5)
- Changing the quality gate threshold
- Integrating SonarCloud PR decoration beyond what the default action provides

## Inputs

- `.github/workflows/security-scan.yml`
- `sonar-project.properties`
- SonarCloud project: `stevedwray_proxmox-homelab` / org: `stevedwray`

## Expected Outputs

- `sonarcloud` job in `security-scan.yml`
- `sonar.branch.name` removed from `sonar-project.properties`
- CI analysis visible in the SonarCloud dashboard on push

## Constraints and Conventions

- Use `SonarSource/sonarcloud-github-action` — pin to the latest stable release SHA
- `fetch-depth: 0` is required for accurate blame/history analysis
- The job must use `ubuntu-latest` (not self-hosted runner)
- Action pins must follow the repo convention: `uses: owner/action@<full-sha> # vX.Y.Z`

## Acceptance Criteria

- [ ] `sonarcloud` job present in `security-scan.yml`
- [ ] `sonar.branch.name` removed from `sonar-project.properties`
- [ ] `SONAR_TOKEN` secret is set in GitHub repository settings (verify before merging)
- [ ] A push to `baseline/teardown-validated` triggers the sonarcloud job and it passes
- [ ] Analysis visible in the SonarCloud dashboard at sonarcloud.io
- [ ] Commit merged to `baseline/teardown-validated`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Add SonarCloud analysis to the security-scan.yml CI workflow.

STEP 1 — Confirm prerequisites:
  - SONAR_TOKEN is set in GitHub repo secrets:
    gh secret list | grep SONAR_TOKEN
  - If missing, ask the user to add it before continuing.

STEP 2 — Create a short-lived branch:
  git checkout -b feat/ci-sonarcloud baseline/teardown-validated

STEP 3 — Remove hardcoded branch from sonar-project.properties:
  Read sonar-project.properties, then remove the sonar.branch.name=main line.
  The SonarCloud action sets this from git context automatically.

STEP 4 — Read security-scan.yml:
  Read .github/workflows/security-scan.yml

STEP 5 — Find the current SonarSource/sonarcloud-github-action latest stable release:
  curl -s "https://api.github.com/repos/SonarSource/sonarcloud-github-action/releases/latest" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tag_name',''))"
  # Then get the SHA for that tag:
  curl -s "https://api.github.com/repos/SonarSource/sonarcloud-github-action/git/refs/tags/<tag>" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('object',{}).get('sha',''))"

STEP 6 — Add the sonarcloud job to security-scan.yml (before the trufflehog job):

  sonarcloud:
    name: SonarCloud analysis
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<same SHA as other jobs> # <same version comment>
        with:
          fetch-depth: 0

      - name: SonarCloud Scan
        uses: SonarSource/sonarcloud-github-action@<sha> # <tag>
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}

STEP 7 — Commit and merge:
  git add .github/workflows/security-scan.yml sonar-project.properties
  git commit -m "feat(ci): add SonarCloud analysis job to security-scan workflow"
  git checkout baseline/teardown-validated && git merge feat/ci-sonarcloud
  git push origin baseline/teardown-validated

DONE WHEN: The sonarcloud job appears in security-scan.yml, passes on a push to
baseline/teardown-validated, and the analysis is visible in the SonarCloud dashboard.
```
