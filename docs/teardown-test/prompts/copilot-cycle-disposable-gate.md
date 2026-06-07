# Copilot Handoff: Artifacts Restructure + Disposable Teardown Cycle

Working directory: `/home/steve/git/proxmox-homelab`

## Read first

Read these files before doing anything else:

- `.github/copilot-instructions.md`
- `docs/teardown-test/README.md`
- `docs/teardown-test/repeatable-test.md`
- `docs/teardown-test/runbook.md`
- `docs/teardown-test/inventory.md`
- `docs/teardown-test/lessons-learned.md`
- `docs/teardown-test/.gitignore`
- `scripts/teardown-deploy-test.sh`

## Current state

You are on branch `baseline/teardown-validated`. This is a promotion-only branch — do not commit directly to it.

The working tree has staged and unstaged changes that Claude Code prepared:

- **Staged** (`git mv`): packets and reports moved into `docs/teardown-test/artifacts/`; `copilot-vmid-schema-cycle-prompt.md` moved to `prompts/`
- **Unstaged modified**: `scripts/teardown-deploy-test.sh` — a one-block change that makes `--disposable` satisfy the approval-text gate (an early return in `require_execute_approval()` when `DISPOSABLE == true`)
- **Unstaged modified**: `docs/teardown-test/.gitignore` — changed from `evidence/ results/` to `artifacts/`
- **Untracked**: `docs/teardown-test/artifacts/` directory (gitignored, exists on disk; contains `evidence/` with historical run stamps, plus `packets/` and `reports/` from the git mv)

## Your job

### 1. Update all path references

The evidence, packets, and reports directories have moved from under `docs/teardown-test/` directly into `docs/teardown-test/artifacts/`. Update every reference in:

- `docs/teardown-test/runbook.md`
- `docs/teardown-test/repeatable-test.md`
- `docs/teardown-test/variables.md`
- `docs/teardown-test/README.md`
- `docs/teardown-test/harness-roadmap.md`
- `docs/teardown-test/operations-plan.md`
- `docs/teardown-test/decisions.md`
- `scripts/teardown-deploy-test.sh`

The substitution pattern is:

| Old path fragment | New path fragment |
|---|---|
| `docs/teardown-test/evidence/` | `docs/teardown-test/artifacts/evidence/` |
| `docs/teardown-test/packets/` | `docs/teardown-test/artifacts/packets/` |
| `docs/teardown-test/reports/` | `docs/teardown-test/artifacts/reports/` |
| `teardown-test/evidence/` (relative, inside harness) | `teardown-test/artifacts/evidence/` |
| `teardown-test/packets/` (relative, inside harness) | `teardown-test/artifacts/packets/` |

Do not touch anything else. Do not refactor, rename, or clean up unrelated content.

After editing, verify harness syntax:

```bash
bash -n scripts/teardown-deploy-test.sh
```

### 2. Cut the work branch and commit

```bash
git checkout -b work/disposable-gate-fix
git add scripts/teardown-deploy-test.sh docs/teardown-test/.gitignore
git add -u docs/teardown-test/
git status --short
```

Review the staged set — it should include:
- The harness `require_execute_approval()` change
- The `.gitignore` update
- All the git mv renames (packets, reports, copilot prompt)
- All the doc/harness path reference updates you made in step 1

Then commit:

```bash
git commit -m "teardown-test: artifacts restructure + disposable approval-text gate

- evidence/, packets/, reports/ moved to artifacts/ (gitignored)
- --disposable now satisfies the approval-text gate in require_execute_approval()
- all documentation and harness path references updated
- copilot-vmid-schema-cycle-prompt.md moved to prompts/"
```

Verify syntax once more after the commit:

```bash
bash -n scripts/teardown-deploy-test.sh
```

### 3. Confirm target guard

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Must return exactly `pve-test`. Stop if it does not.

### 4. Run non-destructive preflight

```bash
scripts/teardown-deploy-test.sh source-preflight
scripts/teardown-deploy-test.sh platform-status
```

If `platform-status` shows SSH access is blocked (cannot reach `pve-test`), record that as a blocker in the handback document and stop — do not proceed to the destructive cycle.

If `source-preflight` finds a source error, fix it and re-run before continuing. Do not proceed with a failing preflight.

### 5. Run the full teardown cycle

The `--disposable` flag is the only approval required. No approval packet needed.

```bash
scripts/teardown-deploy-test.sh cycle --execute --disposable
```

Do not stop between phases unless the harness itself stops. Let the harness drive destroy, foundation redeploy, edge redeploy, edge activation, platform redeploy, and final validation.

If the cycle fails at a phase:

1. Read the failing log path from the harness output.
2. Diagnose from the exact error output.
3. If the failure is a fixable source bug: fix it, re-run `source-preflight`, then resume the cycle from the failed phase using `--stamp <stamp>`.
4. If the failure is environmental (SSH unreachable, target guard returned wrong node, resource contention): record the exact blocker and stop — do not attempt to work around it.
5. Do not broaden into unrelated changes.

### 6. If the cycle passes: promote

```bash
git checkout baseline/teardown-validated
git merge --ff-only work/disposable-gate-fix
git branch -d work/disposable-gate-fix
```

### 7. Generate the handback document

Write `docs/teardown-test/artifacts/handback-001.md` (create the file). Structure it as:

```
# Handback 001

Date: <UTC timestamp>
Branch tested: work/disposable-gate-fix
Commit: <HEAD SHA after commit>
Promoted to baseline/teardown-validated: yes/no

## Outcome

PASSED / FAILED / BLOCKED

## Evidence stamp

<stamp used for the cycle run>
Evidence directory: docs/teardown-test/artifacts/evidence/<stamp>/

## Changes made

1. <each change made, numbered>

## Issues encountered

<list any failures, workarounds, or blockers; "none" if clean>

## Recommended next action for Claude Code

<one sentence: what should happen next — e.g., "Promote to dev/pve-test and validate application stacks" or "Investigate failure at phase X; log at ...">
```

## Working rules

- Follow the target-guard rules: stop if `TF_VAR_proxmox_node` is not `pve-test`.
- Keep all secret-bearing commands behind `./with-secrets`.
- Use the harness; do not run manual terragrunt destroy/apply commands.
- Do not stop for routine success confirmations.
- Stop only for: validation failure, environmental blocker, or unrelated dirty-tree risk.
- Do not commit on `baseline/teardown-validated` — the work branch is the vehicle.

## Definition of done

- All path references updated and syntax verified.
- The commit is on `work/disposable-gate-fix`.
- The teardown cycle completed (pass or proven blocker with evidence).
- If passed: `work/disposable-gate-fix` is merged to `baseline/teardown-validated` and deleted.
- `docs/teardown-test/artifacts/handback-001.md` exists and is complete.
