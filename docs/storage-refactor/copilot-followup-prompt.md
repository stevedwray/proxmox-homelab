# Copilot Storage Refactor Follow-Up Prompt

Continue the storage refactor in `/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/phase-0-audit-notes.md`
- `docs/storage-refactor/copilot-init-prompt.md`

Then inspect the current branch state and determine which storage-refactor
phase is partially complete.

If the branch still matches the current audit note, treat it as
"Phase 0 audit note present, implementation still unfinished" unless the code
clearly proves a later completed phase.

Current review findings to correct first:

- treat the branch as a partial Phase 0 pass, not a completed Phase 0 and not a
  Phase 1 pass
- keep `test-storage` on a non-conflicting `build_seg` IP and preserve that
  property if the stack definition changes again
- tracked evidence must match current script behavior; stale or contradictory
  evidence must be reconciled or removed
- do not treat a hand-shaped fixture as sufficient Phase 0 proof where the plan
  requires targeted provider-backed `terragrunt plan` / `terraform show -json`
  evidence from the real `test-storage` stack
- the capability matrix and classifier must use only the four plan classes from
  `plan.md`: `safe-in-place`, `reboot-required`,
  `replacement-sensitive`, `blocked`
- do not leave speculative Phase 1 contract/schema work mixed into this pass if
  it is not required to complete Phase 0 cleanly
- remove obvious YAML ambiguity such as duplicate keys in `test-storage`
  before treating the stack definition as a trusted validation target

Your job for this pass:

1. Identify the current phase boundary.
   - Determine which phase in `plan.md` is fully complete.
   - Determine which phase is next and what its exit criteria require.

2. Finish the next unfinished phase rather than doing scattered cleanup.
   - Complete the implementation work for that phase.
   - Run the tests listed for that phase.
   - Update docs or validators that are part of that phase.
   - For this pass, prioritize correcting the reviewed Phase 0 issues before
     adding new scope.
   - If live/provider-backed proof cannot be produced in this pass, stop and
     hand back the exact blocker rather than substituting synthetic proof.

3. If the current branch has drifted from the plan:
   - bring the branch back to the phase model in `plan.md`
   - remove accidental scope growth
   - document any justified deviation clearly

4. If you hit a blocker:
   - stop at the phase boundary
   - summarize the exact blocker, affected files, commands run, and what design
     choice or capability is missing

Working rules:

- do not create sibling worktrees under `..`
- work in the current checkout unless a clean worktree is strictly required for
  a gate or proof flow
- if a clean worktree is strictly required, place it under
  `/tmp/proxmox-homelab-worktrees/` and remove it when finished
- do not create tracked temporary documents, evidence files, handoff notes, or
  handback notes unless they are durable artifacts that truly need to survive
  across branches or sessions
- if a tracked fixture is kept for repeatable tests, keep it clearly separated
  from transient evidence and explain why it needs to stay tracked
- do not store transient classifier output or one-off proof artifacts under
  tracked `docs/storage-refactor/evidence/` unless there is a specific durable
  review reason to keep that exact artifact in Git
- prefer inline hand-back in the response and ignored/temp locations for
  transient notes or evidence
- do not reintroduce PBS restore or restore-testing scope
- do not reintroduce storage-migration or dataset-redesign scope
- prioritize safe mutation, explicit mount identity, explicit backup intent,
  and plan safety
- keep the dedicated test LXC as the primary mutation-development target
- keep `test-storage` independent of platform-stack dependencies while still
  using a normal SDN/VLAN-backed zone
- keep unchanged real stacks on compatibility paths unless the current phase
  explicitly needs representative validation coverage
- keep Docker-managed volumes supported
- do not touch unrelated local edits
- do not stop after review, doc reading, or partial command output if the next
  required execution step is already clear from this prompt
- do not present a menu of options where the plan already implies a default
  next action
- if a validator or proof step fails because of an obvious repo-local fix that
  can be made safely from repo context, make that fix and rerun in the same
  pass
- this pass must produce material progress:
  at least one required validator/proof command run, one durable phase change,
  or one exact blocker after attempting the required execution path

Definition of done for this pass:

- one additional storage-refactor phase is completed, or
- the exact blocker preventing phase completion is documented clearly

End the pass with a structured hand-back that includes:

- current phase and whether it is complete, partial, or blocked
- files changed
- tests and validations run
- tests not run, if any
- blockers, deviations, or assumptions
- the exact recommended next pass:
  - follow-up
  - validation
  - gate
  - promotion

Also state explicitly:

- whether the branch remains in Phase 0 or has actually completed Phase 0
- which tracked artifacts were kept intentionally and why
- which temporary evidence artifacts were removed from tracked paths, if any
- whether the pass produced real provider-backed plan evidence or only source /
  fixture-level checks

The hand-back must be review-ready in the response itself, not only written to
files.
