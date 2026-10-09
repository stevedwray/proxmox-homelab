# 06 — Run the CI gates on PRs into `stable`

**When:** this week · **Effort:** 30 min · **Value:** Med-High
**Production access:** none
**Depends on:** plan 02 (so the PR that carries this change goes to a clean
`stable`)

## Problem (verified 2026-09-28)

`validate.yml` (terraform fmt/validate, shellcheck, Harbor image policy,
ansible-lint, ruff/bandit, sops-freeze) and `security-scan.yml` (SonarCloud,
Trivy, Snyk IaC, the image build and signature gates) only trigger
`pull_request` for base branches `main` and `baseline/teardown-validated`.
Every day-to-day PR targets `stable`, so none of them ran. PR #432
(`task/retire-sops` → `stable`) shows only Snyk and Semgrep, the two external
GitHub apps. PR #434 (`stable` → `main`) shows all of them, four failing,
after 404 commits of silent drift.

## Consequence to plan for

Once this lands, every PR into `stable` runs these gates. They'll show the
existing failures (ansible-lint, Harbor image policy, ruff, SonarCloud) until
plan 10 fixes them, and a red check on an unrelated PR is noise. **Schedule
plan 10 right after this one.** No branch protection requires these checks
today, so red checks don't block merges.

## Step

### catchup-06-workflow-triggers

```yaml
id: catchup-06-workflow-triggers
title: Add stable to the pull_request branches of validate.yml and security-scan.yml
depends_on: []

change: |
  In .github/workflows/validate.yml, in the top-level `on:` block, the
  `pull_request:` key currently reads exactly:

    pull_request:
      branches:
        - main
        - 'baseline/teardown-validated'

  Replace it with this LITERAL text (same 2-space indentation as the
  original):

    pull_request:
      branches:
        - main
        - stable
        - 'baseline/teardown-validated'

  Make the identical edit to the `pull_request:` key in the top-level `on:`
  block of .github/workflows/security-scan.yml (it has the same two
  branches today). Do not change the `push:` keys, the
  `workflow_dispatch:` inputs, or anything under `jobs:` in either file.

scope:
  allowed_paths:
    - .github/workflows/validate.yml
    - .github/workflows/security-scan.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any change to jobs:, push: or workflow_dispatch:"
    - "Any gh command"

gates:
  - id: triggers
    cmd: |
      python3 - <<'PY'
      import yaml
      for f in ['.github/workflows/validate.yml', '.github/workflows/security-scan.yml']:
          d = yaml.safe_load(open(f))
          on = d.get('on', d.get(True))  # PyYAML parses the bare key `on` as True
          assert on['pull_request']['branches'] == ['main', 'stable', 'baseline/teardown-validated'], f
      print('ok')
      PY
    expect: "prints ok"
    critical: true
  - id: diff-size
    cmd: "git diff --numstat -- .github/workflows/validate.yml .github/workflows/security-scan.yml"
    expect: "exactly two lines, each '1\t0\t<file>' (one line added per file, none removed)"
    critical: true
```

## Operator: confirm it works

Open the PR for this branch against `stable` (it's the first PR to exercise
the change):

```bash
gh pr create --base stable --fill
gh pr checks --watch
```

Expect the check list to include "Ansible lint", "Python lint + security",
"Enforce Harbor-only image references", "SonarCloud analysis" and "Terraform
validate". Failures in the first three and SonarCloud are the known ones plan
10 fixes. Record the check names in the hand-back.

## Done when

- The gates run on PRs into `stable` (seen on the PR above).
- Plan 10 is scheduled next.
