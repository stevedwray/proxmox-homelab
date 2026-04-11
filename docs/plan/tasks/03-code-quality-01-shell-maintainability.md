# 03-code-quality-01 — Shell script maintainability fixes (issues #23, #26, #31)

## Status

PENDING

## Phase

Phase 03 — Code Quality and Bug Fixes

## Prerequisites

- Phase 00 (housekeeping) complete — branch is clean
- `shellcheck` available locally (recommended but not required)
- `ansible-lint` passing at 0 violations before starting

## Objective

`scripts/check-proxmox-status.sh`, `scripts/setup-dev-env.sh`, and `sync-secrets.sh` all pass shellcheck, have explicit `return 0` in every function, use named local variables instead of `$1`/`$2`, and extract repeated SSH option strings to variables. Issues #23, #26, and #31 are closed.

## Scope

- `scripts/check-proxmox-status.sh`
- `scripts/setup-dev-env.sh`
- `sync-secrets.sh` (repo root)
- Branch: `fix/shell-maintainability` off `dev/pve-test`

## Out of Scope

- Python files (batches 2–5 in phase-03)
- Ansible or Terraform files
- Adding new functionality to shell scripts

## Inputs

- `scripts/check-proxmox-status.sh` — read before editing
- `scripts/setup-dev-env.sh` — read before editing
- `sync-secrets.sh` — read before editing
- `docs/plan/phase-03-code-quality.md` — Batch 1 for exact line references and rules

## Expected Outputs

- `scripts/check-proxmox-status.sh` — modified
- `scripts/setup-dev-env.sh` — modified
- `sync-secrets.sh` — modified

## Constraints and Conventions

- Issue #23 (SonarCloud `shelldre:S7682`): Add `return 0` at the end of every function body where there is no existing return statement. Do NOT add `return 0` after a command whose exit code should propagate.
- Issue #26 (SonarCloud `shelldre:S7679`): At the top of each function that uses `$1`, `$2` etc., assign each to a named local: `local message="$1"`. Then replace all uses of the positional in the function body with the named variable.
- Issue #31 (SonarCloud `shelldre:S1192`): In `check-proxmox-status.sh`, extract the repeated SSH options string and separator string to script-level variables `SSH_OPTS` and `SEPARATOR`. Replace all literal occurrences.
- Do not change function logic, only the style issues listed
- Keep changes minimal — only touch lines identified as issues

## Acceptance Criteria

- [ ] `shellcheck scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh` passes (or no new failures compared to baseline)
- [ ] Every function in all three files ends with `return 0` (or a non-zero propagation)
- [ ] No bare `$1`, `$2` etc. used inside function bodies (all assigned to named locals)
- [ ] `SSH_OPTS` and `SEPARATOR` variables defined at script scope in `check-proxmox-status.sh`
- [ ] No regressions: scripts still execute without errors
- [ ] Issues #23, #26, #31 closed on GitHub with commit references

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Apply three SonarCloud shell script maintainability fixes across three shell scripts.
This is a code-quality task — no logic changes, only style improvements.

BEFORE EDITING, READ THESE FILES IN FULL:
  scripts/check-proxmox-status.sh
  scripts/setup-dev-env.sh
  sync-secrets.sh
  docs/plan/phase-03-code-quality.md   (Batch 1 — exact rules and line references)

CREATE A BRANCH:
  git checkout -b fix/shell-maintainability dev/pve-test

THREE CHANGES TO MAKE:

1. ISSUE #23 — Add explicit return 0 to shell functions (SonarCloud: shelldre:S7682)
   In each of the three files, find every function definition. At the end of the function
   body (before the closing }), add `return 0` if there is no existing return statement.
   Do NOT add return 0 after a command that should propagate a non-zero exit code.

2. ISSUE #26 — Assign positional parameters to named local variables (shelldre:S7679)
   In each function that uses $1, $2, etc., add at the TOP of the function body:
     local message="$1"   (use an appropriate name for each parameter)
   Then replace all occurrences of $1, $2, etc. in that function body with the named variable.

3. ISSUE #31 — Extract repeated SSH options string (shelldre:S1192)
   Only in scripts/check-proxmox-status.sh:
   After the shebang and initial variable declarations, add:
     SSH_OPTS="-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no"
     SEPARATOR="=============================================="
   Then replace every literal occurrence of those strings in the file with $SSH_OPTS and
   $SEPARATOR respectively.

VERIFY:
  shellcheck scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh

COMMIT AND CLOSE:
  git add scripts/check-proxmox-status.sh scripts/setup-dev-env.sh sync-secrets.sh
  git commit -m "refactor(scripts): shell maintainability fixes

- Add explicit return 0 to shell functions (shelldre:S7682) (Closes #23)
- Assign positional params to local variables (shelldre:S7679) (Closes #26)
- Extract repeated SSH opts and separator to variables (shelldre:S1192) (Closes #31)"

  git push origin fix/shell-maintainability
  git checkout dev/pve-test && git merge fix/shell-maintainability
  git push origin dev/pve-test

  gh issue close 23 --comment "Fixed in fix/shell-maintainability — explicit return 0 added."
  gh issue close 26 --comment "Fixed in fix/shell-maintainability — positional params → local vars."
  gh issue close 31 --comment "Fixed in fix/shell-maintainability — SSH_OPTS and SEPARATOR extracted."

DONE WHEN: All three issues closed and shellcheck passes without new failures.
```
