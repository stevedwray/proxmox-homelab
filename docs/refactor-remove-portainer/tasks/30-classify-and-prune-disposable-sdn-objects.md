# Task 30: Classify and prune disposable SDN objects after strip-down

## Type

Development

## Objective

Determine whether any current SDN objects on `pve-test` are disposable leftovers
after Task 29 and remove only those objects that are proven unused by the
remaining retained baseline.

This task may legitimately complete as a no-op if all current SDN objects are
still required.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/30-classify-and-prune-disposable-sdn-objects.md`
- `docs/refactor-remove-portainer/prompts/30-classify-and-prune-disposable-sdn-objects.yaml`

## Preconditions

- Task 29a is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/29a-manual-orphaned-container-cleanup-report.md`
  - that report must explicitly show `Status: complete`
- Treat the current live SDN snapshot as authoritative input for this task.
- Do not change Terraform or Ansible source files in this task.
- Do not run Sonar or Snyk in this task. This is an exploratory cleanup step,
  not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current `origin/dev/pve-test`
   baseline.
2. Capture the current SDN zones and VNets from `pve-test`.
3. Compare the live SDN objects with:
   - the currently retained running containers on `pve-test`
   - active stack metadata in `terraform/lxc/stacks/*/stack.yaml`
4. Remove only zones/VNets/subnets that are clearly disposable and unused.
5. If every live SDN object is still required by the retained baseline, record
   the task as an explicit no-op with evidence.
6. Write the task report to:
   - `docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md`
7. Stop after reporting. Do not start Task 31 automatically.

## Postconditions

- Disposable SDN leftovers are removed if and only if their unused status is
  proven.
- If no object can be safely removed, the report records a validated no-op.
- No Terraform/Ansible code changes are mixed into this task.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/29a-manual-orphaned-container-cleanup-report.md && echo present
rg -n "^Status: complete$" docs/refactor-remove-portainer/reports/29a-manual-orphaned-container-cleanup-report.md
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pvesh get /cluster/sdn/zones --output-format json'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pvesh get /cluster/sdn/vnets --output-format json'
rg -n "zone:|attachment_type:|network:" terraform/lxc/stacks
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 29a evidence is present on disk and explicitly marked complete
- the report clearly classifies each live SDN object as retained or disposable
- only proven-unused disposable objects are removed
- or the task closes as an explicit no-op with evidence if nothing is safely
  removable

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 29a evidence is missing from disk or does not show `Status: complete`.
- Dependency analysis cannot prove whether a live SDN object is safe to remove.
- Any attempted SDN object removal fails.
- Unexpected tracked changes appear outside the scoped report artifact.
