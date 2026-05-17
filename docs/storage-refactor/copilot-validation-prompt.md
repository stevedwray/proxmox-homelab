# Copilot Validation Prompt

Continue the storage refactor from the current branch state in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/copilot-init-prompt.md`
- `docs/storage-refactor/copilot-followup-prompt.md`

Then inspect the current branch changes and move the refactor through the next
practical stage: environment-backed validation and finish-line cleanup.

Current state

- The manifest-driven storage model is in place.
- The harness split between source-only and live validation has been restored.
- Transitional validator handling for extra mounts has been tightened.
- Some non-destructive checks were reported as passing, but local reproduction
  showed `source-preflight` can still fail early if required `.env` values such
  as `LAB_IP_AUTHENTIK` are missing in the execution environment.

Your job for this pass

1. Make the validation story reliable in the intended operator environment.
   - Inspect why `source-preflight` depends on `.env` values that may be absent.
   - Decide whether the right fix is:
     - documenting the required `.env` contract more clearly,
     - making the source-only path fail with a sharper preflight message, or
     - reducing unnecessary coupling in source-only checks if that is safe.
   - Prefer tightening the operator experience over broad redesign.

2. Re-run the intended validation sequence in the properly configured
   environment.
   - Python syntax validation for `terraform/lxc/validate-storage-contract.py`
   - targeted Terraform formatting/validation steps that are safe
   - `./scripts/teardown-deploy-test.sh source-preflight`
   - `./scripts/teardown-deploy-test.sh live-preflight`
   - required scans for this branch per repo policy:
     - `/home/steve/.local/bin/snyk iac test terraform/`
     - `./with-secrets /home/steve/.local/bin/sonar-scanner`

3. Fix any validation or scan failures that are genuinely caused by the storage
   refactor.
   - Do not churn unrelated areas.
   - If a failure is environmental or pre-existing, identify it clearly and
     avoid masking it.

4. Prepare the branch for handoff or commit.
   - Summarize what now passes.
   - Summarize what is still blocked, if anything.
   - If the branch is cleanly validated for this stage, prepare the changes for
     commit on the current `work/*` branch without touching unrelated local
     edits such as `next-session.md`.

Working rules

- Do not restart or redesign the storage refactor.
- Keep the manifest-driven storage contract and intent-based stack fields.
- Preserve the `source-preflight` vs `live-preflight` split unless you find a
  concrete reason it still does not hold.
- Prefer small corrective changes over broad refactors.
- Surface real blockers with exact commands and file references.

Definition of done for this pass

- The intended non-destructive validation flow has been rerun in the correct
  environment, or the exact blocker is proven and documented.
- Any storage-refactor-caused validation issues found in this pass are fixed.
- Required scans have been rerun, or the exact reason they could not be.
- The branch is either ready for commit/handoff or has a small, explicit list
  of remaining blockers.
