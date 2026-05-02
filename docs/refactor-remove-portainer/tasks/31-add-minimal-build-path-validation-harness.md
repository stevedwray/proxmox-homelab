# Task 31: Add a minimal build-path validation harness

## Type

Development

## Objective

Add a narrow validation harness for the first cleanup-first live path: one
build-path target with the minimum companion containers needed to validate
firewall and port behavior.

The initial harness should target:

- `net-build-01`
- `net-artifacts-01`
- `net-client-01`

This task is a tooling task. It does not run the live harness on `pve-test`.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/31-add-minimal-build-path-validation-harness.md`
- `docs/refactor-remove-portainer/prompts/31-add-minimal-build-path-validation-harness.yaml`
- `terraform/lxc/validate-build-path.sh`
- `terraform/lxc/ansible/playbooks/validate-build-path.yml`

## Preconditions

- Task 30e is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/30e-reconcile-build-seg-vlan-data-plane-report.md`
  - that report must explicitly show `Status: complete`
- The minimal harness should avoid the full nine-container matrix and should
  not include the known broad-matrix egress probe path.
- Do not run Sonar or Snyk in this task. This is an exploratory tooling step,
  not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current `origin/dev/pve-test`
   baseline.
2. Add a dedicated minimal harness script and playbook for the build path.
3. Keep the harness scoped to the three named stacks only.
4. Validate the harness source with the repo's normal local linting for shell
   and Ansible.
5. Write the task report to:
   - `docs/refactor-remove-portainer/reports/31-add-minimal-build-path-validation-harness-report.md`
6. Stop after reporting. Do not start Task 32 automatically.

## Postconditions

- A dedicated minimal validation harness exists for the build-path scenario.
- The harness can be run independently of the full matrix validator.
- No live `pve-test` mutation is performed in this task.

## Validation

```bash
test -f docs/refactor-remove-portainer/reports/30e-reconcile-build-seg-vlan-data-plane-report.md && echo present
rg -n "^Status: complete$" docs/refactor-remove-portainer/reports/30e-reconcile-build-seg-vlan-data-plane-report.md
shellcheck terraform/lxc/validate-build-path.sh
cd terraform/lxc/ansible && ansible-lint playbooks/validate-build-path.yml
git status --short --branch
```

Expected outcome:

- Task 30e evidence is present on disk and explicitly marked complete
- the new shell harness passes `shellcheck`
- the new playbook passes `ansible-lint`
- the diff remains limited to the new minimal harness files plus scoped package
  updates if needed

## Stop Conditions

- Task 30e evidence is missing from disk or does not show `Status: complete`.
- The harness cannot be kept scoped to the three named stacks.
- `shellcheck` or `ansible-lint` fails and the task cannot resolve it within
  scope.
- Unexpected tracked changes appear outside the scoped files.
