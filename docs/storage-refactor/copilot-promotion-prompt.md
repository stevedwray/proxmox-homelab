# Copilot Promotion Prompt

Continue from the current validated SSD cutover branch in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/teardown-test/reports/20260517-033905-storage-refactor-gate.md`
- the latest SSD cutover gate evidence under
  `docs/teardown-test/evidence/20260517-044924/`

Current state

- Branch: `work/storage-ssd-cutover`
- Latest validated commit: `bc6a9a3` (`config: cut pve-test storage policy over to SSD-backed pools`)
- The full teardown + redeploy cycle for the SSD cutover passed on stamp
  `20260517-044924`.
- The working tree should remain respectful of unrelated local edits such as
  `next-session.md`.

Your job for this pass

1. Capture promotion-ready closure.
   - Create or update a tracked closeout report for the SSD cutover gate.
   - Summarize:
     - branch and commit used for the gate
     - evidence stamp and path
     - the fact that platform stacks now validated on SSD-backed storage policy
     - any prerequisite discovered during the run, such as template placement on
       `local`
     - whether any regressions were found and fixed during the cycle

2. Prepare the branch for promotion.
   - Ensure the branch is clean except for intentionally excluded unrelated
     local edits.
   - Commit the cutover closeout documentation if needed.
   - Do not include `next-session.md` or ad hoc local scratch files unless they
     are explicitly part of the promotion artifact.

3. Promote to `baseline/teardown-validated`.
   - Follow the repo branching model exactly.
   - Merge the validated `work/storage-ssd-cutover` branch into
     `baseline/teardown-validated`.
   - Preserve the gate evidence and report references so future sessions can see
     why this promotion is valid.

4. Leave the repo in a clear post-promotion state.
   - Summarize what was merged.
   - Confirm the exact baseline branch commit after promotion.
   - Note any follow-up work that should happen on a fresh short-lived branch
     rather than on baseline.

Working rules

- Do not rerun the full destructive gate unless you find a concrete reason the
  completed result is invalid.
- Do not redesign the storage model.
- Do not touch unrelated local edits.
- Optimize for a clean, auditable promotion from validated work branch to
  `baseline/teardown-validated`.

Definition of done for this pass

- The SSD cutover gate result is captured in tracked documentation.
- The validated branch is merged to `baseline/teardown-validated`, or an exact
  blocker is documented.
- The resulting branch/commit state is summarized clearly for the next session.
