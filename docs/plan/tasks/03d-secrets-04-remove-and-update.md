# 03d-secrets-04 — Remove old files and update all documentation

## Status

COMPLETE

## Phase

Phase 03d — Secrets Delivery Hardening

## GitHub Issue

Not assigned yet.

## Prerequisites

- **Task 03d-03 complete and signed off** — all consumer tests pass, `with-secrets` is
  committed. This is a hard gate: do not begin this task if any test in Task 03 failed or
  was skipped.
- The gap analysis (`03d-secrets-01-gap-analysis.md`) is available for reference — it lists
  exactly which secrets were in `sync-secrets.sh` and which are now in `secrets.enc.yaml`

## Objective

The old `.env`-based secret delivery approach is fully removed from the repository. All
documentation — phase docs, task docs, README, and the secrets reference — reflects the
`with-secrets` workflow. No stale `source .env` or `Add to .env.template` instructions
remain anywhere in the active plan documents.

## Scope

### Files to remove

| File | Reason |
|---|---|
| `sync-secrets.sh` | Replaced by `with-secrets` + SOPS |
| `populate-bitwarden.sh` | Bitwarden is no longer the canonical store |
| `.env.template` | Replaced by `secrets.enc.yaml` + `sops` edit flow |
| `.env.pve-test` | Plaintext env file — remove if present in working dir |

Before removing each file, confirm it is not imported or sourced by any other script in the
repository:
```bash
grep -r "sync-secrets\|populate-bitwarden\|\.env\.template\|\.env\.pve-test" \
  --include="*.sh" --include="*.yml" --include="*.yaml" --include="*.md" .
```

### Files to update

#### `docs/reference/secrets-management.md`

Rewrite to reflect the new flow:

- Remove: Bitwarden CLI section, `sync-secrets.sh` procedure
- Remove: "Local usage" decrypt-to-file pattern — replace with `with-secrets` usage
- Add: `with-secrets` wrapper usage examples
- Add: How to add a new secret (`sops terraform/secrets.enc.yaml`)
- Add: How to set a Phase 04 placeholder to its real value
- Keep: Key management section (age key rotation), CI section, naming conventions

#### `docs/plan/README.md` — security scanning section

Current:
```
| Code files modified (Python, shell, YAML) | source .env && sonar-scanner |
```
Replace with:
```
| Code files modified (Python, shell, YAML) | ./with-secrets sonar-scanner |
```

#### `scripts/setup-dev-env.sh` — `setup_environment()` function

Remove the `setup_environment` function body that references `.env.template` and `.env`.
Replace with a note that secrets are managed via `with-secrets` and `terraform/secrets.enc.yaml`.
Update the `show_completion()` "Next steps" section to remove `.env` references.

#### `docs/plan/phase-04-core-shared-services.md`

This file has the most `.env` references. Update every occurrence:

1. **Prerequisites section** — remove:
   ```
   - `.env` is sourced with Proxmox API credentials
   ```
   Replace with:
   ```
   - `with-secrets` wrapper is available (Phase 03d complete)
   - All Phase 04 secret placeholders in `terraform/secrets.enc.yaml` have been updated
     to their real values before deployment begins
   ```

2. **"Secrets required" sections (appears 4 times, once per service)** — replace the pattern:
   ```
   Add to `.env.template` and `.env`:
   ```
   with:
   ```
   Add to `terraform/secrets.enc.yaml` using `sops terraform/secrets.enc.yaml`:
   ```

3. **Deploy commands** — replace any `source /home/steve/git/proxmox-homelab/.env` with
   `./with-secrets` wrapping the command that follows.

#### Phase 04 task docs — prerequisites lists

Update the "exists in `.env`" prerequisite in each task doc:

- `tasks/04-core-services-01-deploy-authentik.md`
- `tasks/04-core-services-03-deploy-traefik.md`
- `tasks/04-core-services-04-deploy-step-ca.md`
- `tasks/04-core-services-05-deploy-monitoring.md`

Pattern to find and update:
```
- `SECRET_NAME`, `ANOTHER_SECRET` ... exist in `.env`
```
Replace with:
```
- `SECRET_NAME`, `ANOTHER_SECRET` ... are set to real values in `terraform/secrets.enc.yaml`
  (update placeholders via `sops terraform/secrets.enc.yaml` before running deploy)
```

Also update any Session Prompt commands in those task docs that include `source .env`.

#### Already-complete phase and task docs

The following documents describe work that is already done but still contain `.env`
references. Update them for accuracy so they do not mislead future readers or future
rebuild passes:

- `docs/plan/phase-03b-harbor-setup.md` — if it references `.env`
- `docs/plan/phase-03c-artifact-proxy.md` — if it references `.env`
- Any task docs under `docs/plan/tasks/done/` that reference `source .env` in session
  prompts (update to `./with-secrets` for correctness, noting that these tasks are done)

Run this to find all remaining references after the above changes:
```bash
grep -r "source.*\.env\|\.env\.template\|sync-secrets\|populate-bitwarden" \
  docs/ scripts/ --include="*.md" --include="*.sh"
```
This should return zero results when all updates are complete.

#### `.gitignore`

Check whether `.env` and `.env.pve-test` are in `.gitignore`. Keep these entries — even
though the files no longer exist as part of the workflow, the gitignore entries act as a
safety net if someone accidentally creates a `.env` file in the future:

```
.env
.env.pve-test
*.dec.yaml
*.dec.env
```

Do not remove the `.enc.yaml` exclusion pattern if present — that would be wrong since
`.enc.yaml` files ARE committed.

## Constraints and Conventions

- Update documentation accurately — do not remove context about how the old approach worked
  if it helps explain why the new approach is structured the way it is.
- The completed task docs (`docs/plan/tasks/done/`) may still reference `source .env` in
  their session prompts. Update these for historical accuracy but make a note that the task
  was completed using the old approach.
- Do not modify `terraform/secrets.enc.yaml` in this task — that was Task 02's scope.
- After removing `sync-secrets.sh` and `populate-bitwarden.sh`, run shellcheck on `with-secrets`
  one final time to confirm it remains clean.

## Acceptance Criteria

- [ ] `sync-secrets.sh` deleted from repo root
- [ ] `populate-bitwarden.sh` deleted from repo root
- [ ] `.env.template` deleted (if it existed)
- [ ] `.env.pve-test` deleted (if it existed in working directory / was tracked by git)
- [ ] `grep -r "source.*\.env\|sync-secrets\|populate-bitwarden" docs/ scripts/ --include="*.md" --include="*.sh"` returns zero results
- [ ] `docs/reference/secrets-management.md` describes `with-secrets` as the operator flow
- [ ] `docs/plan/README.md` security scanning section uses `./with-secrets sonar-scanner`
- [ ] `scripts/setup-dev-env.sh` has no reference to `.env.template` or `source .env`
- [ ] All four Phase 04 task docs updated — no `source .env` in prerequisites or session prompts
- [ ] `docs/plan/phase-04-core-shared-services.md` updated — all "Secrets required" and deploy sections
- [ ] `.gitignore` retains `.env` and `.env.pve-test` entries as safety net
- [ ] `shellcheck with-secrets` still passes after all removals
- [ ] No `.env` file present in the working directory

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.
Branch: feat/secrets-hardening (already exists from earlier tasks)

TASK: Remove the old .env-based secret delivery files and update all documentation.
This is the final task of Phase 03d. Do not begin unless Task 03 (wrapper and tests) is
complete and all consumer tests passed.

READ THESE FILES FIRST:
  docs/plan/tasks/03d-secrets-04-remove-and-update.md   (this task — full scope)
  docs/plan/tasks/03d-secrets-01-gap-analysis.md        (confirms what was in sync-secrets.sh)

STEP 1 — Confirm no file imports the files to be deleted:
  grep -r "sync-secrets\|populate-bitwarden\|\.env\.template\|\.env\.pve-test" \
    --include="*.sh" --include="*.yml" --include="*.yaml" --include="*.md" .

  If anything unexpected shows up, investigate before proceeding.

STEP 2 — Remove files:
  git rm sync-secrets.sh
  git rm populate-bitwarden.sh
  git rm .env.template   (only if this file exists — check first)

  For .env.pve-test: check if it is tracked by git:
    git ls-files .env.pve-test
  If tracked: git rm .env.pve-test
  If untracked but present: rm .env.pve-test  (not a git operation)
  If not present: note this in the commit message

STEP 3 — Update documentation files (in this order):
  1. docs/reference/secrets-management.md      — rewrite for new flow
  2. docs/plan/README.md                        — security scanning section
  3. scripts/setup-dev-env.sh                   — setup_environment() and show_completion()
  4. docs/plan/phase-04-core-shared-services.md — all .env references
  5. docs/plan/tasks/04-core-services-01-deploy-authentik.md
  6. docs/plan/tasks/04-core-services-03-deploy-traefik.md
  7. docs/plan/tasks/04-core-services-04-deploy-step-ca.md
  8. docs/plan/tasks/04-core-services-05-deploy-monitoring.md
  Then grep for any remaining .env references in phase-03b, phase-03c, and done/ task docs.

STEP 4 — Verify zero remaining .env references in docs and scripts:
  grep -r "source.*\.env\|\.env\.template\|sync-secrets\|populate-bitwarden" \
    docs/ scripts/ --include="*.md" --include="*.sh"
  This must return zero results.

STEP 5 — Final shellcheck:
  shellcheck with-secrets
  Must pass with zero errors.

STEP 6 — Commit and merge:
  git add -u   (stages all modified and deleted tracked files)
  git add docs/reference/secrets-management.md   (if not already staged by -u)
  git commit -m "chore(secrets): remove .env delivery, update all docs for with-secrets

- Remove sync-secrets.sh, populate-bitwarden.sh, .env.template
- Update secrets-management.md, README, setup-dev-env.sh
- Update Phase 04 docs and task docs to use with-secrets workflow
- Closes Phase 03d"

  git push origin feat/secrets-hardening

  # Create PR to merge into baseline/teardown-validated
  gh pr create \
    --base baseline/teardown-validated \
    --head feat/secrets-hardening \
    --title "feat(secrets): eliminate .env delivery — sops exec-env via with-secrets" \
    --body "Closes Phase 03d. Replaces sync-secrets.sh + source .env with sops exec-env
    wrapper. Eliminates TM-02 and TM-03 from the threat model bridge period. All consumer
    tests passed in Task 03. See docs/plan/phase-03d-secrets-hardening.md."

STEP 7 — After PR is merged, archive task docs:
  git checkout baseline/teardown-validated && git pull
  git mv docs/plan/tasks/03d-secrets-01-audit.md       docs/plan/tasks/done/
  git mv docs/plan/tasks/03d-secrets-01-gap-analysis.md docs/plan/tasks/done/
  git mv docs/plan/tasks/03d-secrets-02-align-sops.md  docs/plan/tasks/done/
  git mv docs/plan/tasks/03d-secrets-03-wrapper-and-test.md docs/plan/tasks/done/
  git mv docs/plan/tasks/03d-secrets-04-remove-and-update.md docs/plan/tasks/done/
  git commit -m "chore(plan): archive Phase 03d task docs to done/"
  git push origin baseline/teardown-validated

DONE WHEN:
  All acceptance criteria above are checked.
  feat/secrets-hardening is merged to baseline/teardown-validated.
  Task docs are archived to done/.
  No .env file exists in the working directory.
```
