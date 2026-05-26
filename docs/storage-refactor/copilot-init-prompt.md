# Copilot Storage Refactor Kickoff Prompt

You are working in `/home/steve/git/proxmox-homelab` on the storage refactor
documented in:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/phase-0-audit-notes.md`

Start by reading those files and then inspect the current implementation in:

- `terraform/lxc/main.tf`
- `terraform/lxc/modules/lxc-docker-host/*`
- `terraform/lxc/storage/*`
- `terraform/lxc/stacks/*/stack.yaml`
- `terraform/lxc/stacks/*/STACK_CONTRACT.md`
- `terraform/lxc/README.md`
- `terraform/lxc/PLATFORM_CONTRACT.md`
- `scripts/teardown-deploy-test.sh`

Your job is to execute the storage refactor, starting from the earliest
unfinished phase in `docs/storage-refactor/plan.md`.

Current branch reality:

- planning docs have been rewritten around the phased storage-safety model
- `docs/storage-refactor/phase-0-audit-notes.md` records the lightweight source
  audit already completed on this branch
- `terraform/lxc/stacks/test-storage/` does not exist yet
- the current code still uses the pre-refactor storage shape

Use the audit note as established context. Do not restart with a broad
free-form rediscovery pass if the note already answers the question.

Primary objective:

- make Terraform-driven LXC storage layout changes for Docker-on-LXC explicit,
  low-risk, and provider-aware

Required end state:

- growing `/var/lib/docker` is a tested grow-only workflow
- growing an existing extra mount is a tested grow-only workflow
- attaching one additional persistent filesystem is a tested workflow
- that additive workflow is explicitly limited to stacks that do not already use
  the module's optional extra mount
- persistent mounts have explicit logical identity and backup intent
- unsafe `mount_point` mutations are classified before apply

Important constraints:

- treat `pve-test` as the disposable validation target
- do mutation development and testing on a dedicated test LXC, not on
  interconnected infrastructure stacks
- use the tracked stack `test-storage` for that purpose
- keep `test-storage` on a normal SDN/VLAN-backed zone, preferably `build_seg`,
  rather than the legacy `lan` bridge path
- keep that dedicated test LXC as a tracked normal stack shape, not a special
  one-off code path
- keep the contract environment-scoped so it can later be applied to `pve`
- stay on a short-lived `work/*` branch
- keep Docker-managed volumes supported
- do not add PBS restore testing
- do not turn this into a data-migration or dataset-redesign project
- do not assume a second optional extra mount is supported under the current
  module shape
- do not spend time removing an otherwise-unused `/var/lib/docker` mount from a
  non-Docker stack unless the current phase makes that necessary
- do not broaden scope beyond `README.md` and `plan.md` without explicit
  approval
- do not convert unchanged real stacks just for authoring cleanup when
  compatibility support is sufficient

Execution order:

1. Determine the highest completed storage-refactor phase from the current
   branch state.
2. If no implementation exists yet, continue with Phase 0:
   capability check and storage audit.
3. Treat the current branch as "Phase 0 audit note present, implementation not
   started" unless the code clearly proves otherwise.
4. Complete one full phase at a time, including its tests and exit criteria,
   before moving to the next phase.
5. Update docs and validation tooling as the contract changes.
6. Stop only for a real blocker, failed phase gate, or a decision with
   meaningful architectural consequences.

When reporting progress, focus on:

- which phase you are working on
- what changed
- what was tested
- what blocks the next phase, if anything

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
