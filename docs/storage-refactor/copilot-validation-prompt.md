# Copilot Storage Refactor Validation Prompt

Continue the storage refactor from the current branch state in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/copilot-init-prompt.md`
- `docs/storage-refactor/copilot-followup-prompt.md`

Then inspect the branch changes and validate the highest completed phase plus
the phase currently in progress.

Your job for this pass:

1. Reconstruct the validation scope from `plan.md`.
   - Determine which phase tests should pass right now.
   - Do not invent a broader gate than the phase model requires.

Working rules:

- do not create sibling worktrees under `..`
- work in the current checkout unless a clean worktree is strictly required for
  a gate or proof flow
- if a clean worktree is strictly required, place it under
  `/tmp/proxmox-homelab-worktrees/` and remove it when finished
- do not create tracked temporary documents, evidence files, handoff notes, or
  handback notes unless they are durable artifacts that truly need to survive
  across branches or sessions
- prefer inline validation hand-back in the response and ignored/temp
  locations for transient notes or evidence

2. Re-run the intended non-destructive validation flow.
   - source-only checks
   - live read-only checks where the phase requires them
   - targeted Terraform formatting or validation steps that are safe
   - validator and unit tests added by the storage refactor

3. Re-run targeted storage mutation tests if the phase touched:
   - the `test-storage` validation stack shape or placement
   - Docker mount growth
   - existing extra-mount growth
   - additive extra-mount attachment
   - blocking or surfacing a second-extra-mount request
   - backup flag or backup-policy behavior
   - mutation classification or plan-safety behavior

4. Re-run required repo scans if the branch changed Terraform, Python, shell,
   or YAML in a merge-relevant way:
   - `/home/steve/.local/bin/snyk iac test terraform/`
   - `./with-secrets /home/steve/.local/bin/sonar-scanner`

5. Fix validation failures caused by the storage refactor.
   - avoid unrelated churn
   - call out environmental or pre-existing failures explicitly
   - preserve the distinction between disposable `pve-test` validation now and
     future `pve` rollout later

Definition of done for this pass:

- the intended phase validations were rerun and summarized, or
- the exact blocker preventing validation is proven and documented

End the pass with a structured hand-back that includes:

- phase validated
- validation status: passed, partial, or blocked
- files changed, if any
- validations and tests run
- validations not run, if any
- blockers, deviations, environmental failures, or assumptions
- the exact recommended next pass:
  - follow-up
  - gate
  - promotion

The hand-back must be review-ready in the response itself, not only written to
files.
