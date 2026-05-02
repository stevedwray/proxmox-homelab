# Portainer Removal Refactor

This directory is the source of truth for the refactor that removes Portainer
from the Tier 1 platform deployment path and separates Terraform provisioning
from Ansible configuration.

If any older Portainer-removal note conflicts with this directory, this
directory wins.

## Method

This package now follows the same operating method used successfully in
`docs/provisioning-refactor/`:

- decision-first: binding rules are written down in `decisions.md` before task
  execution
- one task per branch/session: each task is intentionally atomic
- task-sequenced: executor sessions follow `task-sequence.md`, not ad hoc work
- validation-driven: every implementation task has explicit validation and stop
  conditions
- rollback-aware: shared validation and rebuild vocabulary lives in
  `runbook.md`
- architecture-session controlled: executor sessions do not widen scope on
  their own
- hygiene-enforced: architect and executor sessions keep branch/worktree state
  tidy enough that `git status` continues to reflect only the active task

## Target Model

The target state is:

- Portainer remains in the homelab, but only as a management UI for Tier 2 app
  stacks.
- Platform stacks deploy directly by Ansible on-host using existing compose or
  stack-specific playbook logic.
- Terraform provisions infrastructure and generates inventories.
- Ansible configuration runs as a separate operator action via
  `scripts/provision.sh`.
- Terraform must not perform a hidden second pass for LXC configuration.

## Scope Boundaries

- Scope is `pve-test` only.
- Production `pve` is out of scope until the `pve-test` model is proven.
- This package describes documentation, implementation, and validation work for
  the refactor, but each execution task remains a single branch/session unit.
- Do not combine tasks unless the architecture session explicitly says to do so.

## Current Recovery Mode

After the post-reboot recovery evidence and the later disposable-network
investigation reports, the refactor is no longer using a broad rebuild-first
recovery path.

The current architecture-approved recovery mode is:

- cleanup-first on `pve-test`
- remove disposable validation containers before more SDN experimentation
- prune only disposable network state that is proven unused
- validate one infrastructure/build path at a time with a minimal harness
- defer another broad rebuild-gate retry until the minimal harness and SDN
  idempotency path are proven

## Background Documents

These files remain useful, but they are not the operational source of truth:

- [01-revised-architecture.md](01-revised-architecture.md) — background
  architecture context
- [02-terraform-ansible-separation.md](02-terraform-ansible-separation.md) —
  background separation model
- [03-refactor-plan.md](03-refactor-plan.md) — legacy draft plan; reference
  only when it does not conflict with this package

When there is any conflict:

1. `decisions.md`
2. `task-sequence.md`
3. task documents and prompts
4. `runbook.md`
5. background documents

## Files

- [decisions.md](decisions.md) — binding technical and process decisions
- [task-sequence.md](task-sequence.md) — ordered atomic execution plan
- [runbook.md](runbook.md) — shared validation, rebuild, and rollback contract
- [tasks/](tasks/) — one detailed task document per executor session
- [prompts/](prompts/) — matching executor prompts
- [prompts/index.yaml](prompts/index.yaml) — ordered prompt registry

## How To Use This Package

1. Read this file and [decisions.md](decisions.md).
2. Select exactly one task from [task-sequence.md](task-sequence.md).
3. Use the matching prompt from [prompts/index.yaml](prompts/index.yaml).
4. Keep changes inside the task's declared scope.
5. Run the task's required validation.
6. Stop and report back if validation reveals a new issue outside task scope.

## Workspace Hygiene

- Cut each task branch from a current `origin/dev/pve-test` baseline, not from a
  stale local branch snapshot.
- Keep package files that belong to the task tracked on the task branch. Do not
  rely on untracked prompts, task docs, or helper scripts as hidden session
  state.
- Keep scratch work, spare worktrees, and evidence directories out of normal
  repo status noise. If local scaffolding must exist, ignore it locally.
- Before reporting task-complete or asking the architect to evaluate a report,
  ensure `git status --short` reflects only the active task's scoped changes.

## Session Roles

Architecture session:

- owns this package
- updates decisions, sequencing, and prompts
- resolves stop conditions
- does not widen an executor task after the fact without updating docs
- enforces branch/worktree hygiene before issuing or accepting task work

Executor session:

- executes exactly one task
- reads this README, `decisions.md`, the task doc, and the matching prompt
- reports validation output, stop conditions, and unexpected findings
- does not silently fix unrelated issues
- keeps the branch/worktree tidy enough that required task artifacts are
  tracked and unrelated local noise is removed or ignored before handoff
