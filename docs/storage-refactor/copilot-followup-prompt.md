# Copilot Storage Refactor Follow-Up Prompt

Continue the storage refactor in `/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/copilot-init-prompt.md`

Then inspect the current branch state and determine which storage-refactor
phase is partially complete.

Your job for this pass:

1. Identify the current phase boundary.
   - Determine which phase in `plan.md` is fully complete.
   - Determine which phase is next and what its exit criteria require.

2. Finish the next unfinished phase rather than doing scattered cleanup.
   - Complete the implementation work for that phase.
   - Run the tests listed for that phase.
   - Update docs or validators that are part of that phase.

3. If the current branch has drifted from the plan:
   - bring the branch back to the phase model in `plan.md`
   - remove accidental scope growth
   - document any justified deviation clearly

4. If you hit a blocker:
   - stop at the phase boundary
   - summarize the exact blocker, affected files, commands run, and what design
     choice or capability is missing

Working rules:

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
