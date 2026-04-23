# Task 10: Create shared validation runbook and sync documentation

## Type

Documentation

## Objective

Bring the Portainer-removal package up to the same documentation method used by
`docs/provisioning-refactor/`:

- clear source-of-truth ordering
- shared validation/runbook contract
- explicit task sequencing
- background-vs-operational document separation

Then update repo-level docs that still describe the old Portainer-everywhere or
Terraform-runs-Ansible model.

## Files

- `docs/refactor-remove-portainer/README.md`
- `docs/refactor-remove-portainer/decisions.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/runbook.md` (create if missing)
- `docs/refactor-remove-portainer/01-revised-architecture.md`
- `docs/refactor-remove-portainer/02-terraform-ansible-separation.md`
- `docs/refactor-remove-portainer/03-refactor-plan.md`
- `terraform/lxc/PLATFORM_CONTRACT.md`
- `docs/design/architecture.md`
- `terraform/lxc/README.md`
- `docs/plan/README.md` (if needed)

## Preconditions

- Task 06a complete.
- Task 07 complete.
- Task 08 complete.
- Task 09 complete.

## Operations

1. Read the package control docs and the repo-level docs in full before editing.
2. Ensure the package control docs clearly state:
   - this directory is the operational source of truth
   - one task equals one branch/session
   - `runbook.md` is the shared validation contract
   - `01`/`02` are background reference and `03` is legacy draft context
3. Ensure task sequencing covers all Tier 1 playbooks, including the
   service-mask-only group.
4. Update repo-level docs so they reflect the target model:
   - Tier 1 platform stacks do not use Portainer agents
   - Terraform and Ansible are separate phases for LXC configuration
   - `direct_stack`, `deployment_tier`, and the explicit orchestration path are
     documented where appropriate
5. Correct any stale path references to old plan docs when the current repo path
   is under `docs/plan/`.
6. Do not make code changes as part of this task.

## Postconditions

- The Portainer-removal package reads like an execution package, not a loose
  design note collection.
- `runbook.md` exists and defines shared validation/rebuild vocabulary.
- Background docs are clearly marked as background/legacy.
- Repo-level docs no longer describe the old Portainer-everywhere or
  Terraform-runs-Ansible model once the refactor is complete.

## Validation

```bash
rg -n "source of truth|runbook|one task|background|legacy draft" \
  docs/refactor-remove-portainer

rg -n "Terraform invokes Ansible|local-exec.*ansible|Portainer agents across all zones|observability-only" \
  terraform/lxc/PLATFORM_CONTRACT.md \
  docs/design/architecture.md \
  terraform/lxc/README.md \
  docs/plan/README.md
```

Expected outcome:

- the package control docs clearly describe the new method
- stale repo-level wording is removed or updated

## Stop Conditions

- Stop if a repo-level document still cannot be updated cleanly without making
  implementation decisions that belong in another task.
- Stop if a background document must remain contradictory for historical
  reasons; add a status note instead of silently rewriting history.
