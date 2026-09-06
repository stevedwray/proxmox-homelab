# Copilot Storage Refactor Promotion Prompt

Continue from the current validated storage-refactor branch in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- the latest gate evidence and validation notes produced by this refactor

Use this prompt only after the branch has:

- passed the required final validations
- passed required scans or explicitly accepted findings
- passed the repo's infrastructure promotion gate

Your job for this pass:

1. Capture promotion-ready closure.
   - create or update a tracked closeout note if needed
   - summarize the branch, commit, evidence stamp, and scope of validated
     storage safety changes

Working rules:

- do not create sibling worktrees under `..`
- work in the current checkout unless a clean worktree is strictly required for
  a gate or proof flow
- if a clean worktree is strictly required, place it under
  `/tmp/proxmox-homelab-worktrees/` and remove it when finished
- do not create tracked temporary documents, evidence files, handoff notes, or
  handback notes unless they are durable artifacts that truly need to survive
  across branches or sessions
- prefer inline promotion hand-back in the response and ignored/temp
  locations for transient notes or evidence

2. Prepare the branch for promotion.
   - keep the working tree clean except for intentionally excluded unrelated
     local edits
   - ensure the promotion artifact does not include scratch files

3. Promote to `stable`.
   - follow the repo branch model exactly (see
     [docs/workflow/branch-model.md](../workflow/branch-model.md))
   - preserve evidence references so future sessions can see why the promotion
     is valid
   - note explicitly that this promotion proves the `pve-test-vm`-validated
     storage safety contract, while later `pve` rollout (promotion to `main`
     after incremental deploy) remains separate follow-on work

4. Leave the repo in a clear post-promotion state.
   - summarize what was merged
   - confirm the resulting baseline commit
   - note follow-up work that belongs on a fresh short-lived branch

Definition of done for this pass:

- the validated storage-refactor branch is merged to `stable`, or
- the exact promotion blocker is documented clearly

The hand-back must be review-ready in the response itself, not only written to
files.
