# Copilot Storage Refactor Gate Prompt

Continue the storage refactor from the current branch state in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- the current branch diff and latest refactor commits

Use this prompt only when the branch has completed:

- Phase 0 through Phase 4 in `plan.md`, and
- the branch is ready for final gate work

Your job for this pass:

1. Confirm gate readiness.
   - verify the current phase status against `plan.md`
   - confirm the live validation target is still `pve-test`
   - confirm the resulting contract remains applicable to future `pve`
   - confirm there are no unresolved storage safety blockers

2. Run the final validation sequence required by the plan.
   - re-run non-destructive validations
   - re-run targeted storage mutation validation on `test-storage`
   - re-run required scans if code changed since last validation

3. Run the repo-required promotion gate.
   - follow the documented harness and approval flow
   - treat this as infrastructure evidence work, not as an opportunity to
     redesign the refactor

4. Fix genuine storage-refactor regressions exposed by the gate.
   - prioritize resize behavior
   - prioritize existing extra-mount resize behavior
   - prioritize additive mount behavior
   - prioritize explicit handling of the second-extra-mount out-of-scope case
   - prioritize path masking prevention
   - prioritize explicit backup behavior
   - prioritize storage plan-safety checks
   - avoid unrelated churn

5. Summarize whether the branch is ready for promotion.

Definition of done for this pass:

- the final gate has been attempted and summarized clearly, or
- the exact blocker preventing promotion is documented with evidence
