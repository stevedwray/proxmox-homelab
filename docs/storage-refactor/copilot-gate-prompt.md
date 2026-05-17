# Copilot Gate Prompt

Continue the storage refactor from the current branch state in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/copilot-init-prompt.md`
- `docs/storage-refactor/copilot-followup-prompt.md`
- `docs/storage-refactor/copilot-validation-prompt.md`

Then inspect the current branch and latest refactor commit:

- branch: `work/storage-refactor-plan`
- latest commit: `951dd3e` (`Refactor storage intent validation and preflight boundaries`)

Current state

- The storage refactor has been implemented with manifest-driven resolution.
- Source-only vs live validation boundaries were restored.
- Non-destructive validation and required scans were reported as passing in the
  intended operator environment.
- The next real milestone is the infrastructure promotion gate:
  full teardown + redeploy validation with evidence.

Your job for this pass

1. Prepare the branch for the destructive rebuild gate.
   - Confirm the target guard is still `pve-test`.
   - Confirm the expected storage manifest and template assumptions still match
     the intended environment.
   - Review the current working tree and avoid touching unrelated local edits
     such as `next-session.md` or untracked prompt files unless needed.

2. Run the full teardown + redeploy validation flow for this branch using the
   repo’s documented harness.
   - Follow the repo instructions for approval-preflight and destructive
     execution.
   - Use the correct evidence/approval-packet flow for this environment.
   - Keep the validation sequence aligned with the repo workflow rather than
     inventing a custom path.

3. Fix any genuine storage-refactor regressions exposed by the full cycle.
   - Prioritize issues in:
     - storage manifest resolution
     - template resolution
     - rootfs/docker/extra-mount backend selection
     - host bootstrap or validation assumptions that still encode the old
       storage model
   - Avoid unrelated churn.
   - If the cycle fails for an environmental or pre-existing reason, identify it
     clearly with exact evidence.

4. Re-run required validations after any fixes.
   - Re-run the relevant non-destructive checks.
   - Re-run required scans if code changed again.
   - Re-run the full gate if the branch needed fixes.

5. Prepare merge/handoff readiness.
   - Summarize whether the full teardown + redeploy gate passed.
   - Summarize what evidence was captured.
   - If the gate passed cleanly, prepare the branch for merge back to
     `baseline/teardown-validated`.
   - If it did not pass, leave a small, exact blocker list with file references,
     failing command(s), and what still needs operator input.

Working rules

- Do not redesign the storage refactor.
- Preserve the manifest-driven intent model.
- Follow the repo branching and gate policy exactly.
- Treat this as infrastructure work: evidence and gate outcome matter more than
  theoretical cleanliness.
- Make reasonable implementation decisions without micromanagement.
- Do not touch unrelated local edits unless absolutely necessary.

Definition of done for this pass

- The full teardown + redeploy gate has been attempted on this branch using the
  repo-approved flow.
- Any storage-refactor-caused failures found in the gate have been fixed or
  precisely documented.
- Evidence and outcome are summarized clearly enough to decide whether the
  branch can promote to `baseline/teardown-validated`.
