# 03-code-quality-07 — Add ShellCheck to CI validate workflow

## Status

PENDING

## Phase

Phase 03 — Code Quality and Bug Fixes

## GitHub Issue

Not assigned yet.

## Prerequisites

- Task 03-06 complete — stale Harbor IP fixed (clean baseline in validate.yml)
- Shell scripts pass a local `shellcheck` run before adding CI enforcement
  (task 03-01 already fixed the known issues)

## Objective

All `.sh` files in the repository are linted by ShellCheck on every push and pull request
via the `validate.yml` workflow. This prevents shell script regressions from being merged
undetected.

## Scope

- `.github/workflows/validate.yml` — add a `shellcheck` job
- Branch: `feat/ci-shellcheck` off `baseline/teardown-validated`
- Scope of ShellCheck: all `.sh` files, excluding `_legacy/` and `.terragrunt-cache/`

## Out of Scope

- Fixing any new ShellCheck findings found during this task (those should be separate commits
  in their own branches; if findings exist, stop and raise them before merging the CI job)

## Inputs

- `.github/workflows/validate.yml`
- `scripts/check-proxmox-status.sh`
- `scripts/setup-dev-env.sh`

## Expected Outputs

- `shellcheck` job in `validate.yml` that runs on every push/PR

## Constraints and Conventions

- Action pins: use `actions/checkout` at the same SHA already used in other jobs
- ShellCheck is available via `apt-get` on `ubuntu-latest` runners; do not use a third-party
  action
- The job must use `ubuntu-latest` (not the self-hosted runner), since ShellCheck needs no
  Proxmox access

## Acceptance Criteria

- [ ] `shellcheck` job present in `validate.yml`
- [ ] Job runs `find . -name '*.sh' -not -path './.git/*' -not -path './_legacy/*' -not -path './.terragrunt-cache/*' | xargs shellcheck`
- [ ] Local `shellcheck scripts/*.sh` passes before the CI job is added
- [ ] CI passes on a test push to `baseline/teardown-validated` (or a short-lived branch)
- [ ] Commit merged to `baseline/teardown-validated`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Add a ShellCheck job to the validate.yml CI workflow.

STEP 1 — Create a short-lived branch:
  git checkout -b feat/ci-shellcheck baseline/teardown-validated

STEP 2 — Run ShellCheck locally first:
  shellcheck scripts/check-proxmox-status.sh scripts/setup-dev-env.sh
  # If findings exist, stop and fix them before continuing.

STEP 3 — Read validate.yml:
  Read .github/workflows/validate.yml

STEP 4 — Add the shellcheck job.
  Add it before the sops-decrypt-check job.
  Use this pattern:

  shellcheck:
    name: ShellCheck lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<same SHA as other jobs> # <same version comment>

      - name: Install ShellCheck
        run: sudo apt-get install -y shellcheck

      - name: Run ShellCheck
        run: find . -name '*.sh' -not -path './.git/*' -not -path './_legacy/*' -not -path './.terragrunt-cache/*' | xargs shellcheck

STEP 5 — Commit and merge:
  git add .github/workflows/validate.yml
  git commit -m "feat(ci): add ShellCheck lint job to validate workflow"
  git checkout baseline/teardown-validated && git merge feat/ci-shellcheck
  git push origin baseline/teardown-validated

DONE WHEN: The shellcheck job is present in validate.yml and a push to baseline/teardown-validated shows
it passing in GitHub Actions.
```
