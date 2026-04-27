# Task 34: Add a basic SDN smoke harness with simple container scope

## Type

Development

## Objective

Create a lower-blast-radius SDN harness that uses only:

- `test-lxc` (baseline non-SDN container)
- `net-build-01` (single SDN path)

This task is source-only. It adds the tooling but does not run live deploys.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/34-add-basic-sdn-smoke-harness.md`
- `docs/refactor-remove-portainer/prompts/34-add-basic-sdn-smoke-harness.yaml`
- `terraform/lxc/validate-sdn-basic.sh`
- `terraform/lxc/ansible/playbooks/validate-sdn-basic.yml`

## Preconditions

- Task 30g evidence is present and marked complete:
  - `docs/refactor-remove-portainer/reports/30g-validate-external-build-trunk-path-report.md`
- Scope must remain limited to basic harness code and package docs.
- Do not run Sonar or Snyk in this task (exploratory tooling step).

## Operations

1. Cut a clean short-lived branch from the current package baseline.
2. Add a shell harness that can `apply`, `validate`, `destroy`, and `cycle` the basic scope.
3. Add an Ansible validation playbook for one baseline check and one SDN-path probe.
4. Lint the harness source.
5. Write task report:
   - `docs/refactor-remove-portainer/reports/34-add-basic-sdn-smoke-harness-report.md`

## Postconditions

- A dedicated basic SDN harness exists and is runnable.
- Scope remains only `test-lxc` + `net-build-01`.
- No live mutation is required in this task.

## Validation

```bash
test -f docs/refactor-remove-portainer/reports/30g-validate-external-build-trunk-path-report.md && echo present
rg -n "^Status: complete$" docs/refactor-remove-portainer/reports/30g-validate-external-build-trunk-path-report.md
shellcheck terraform/lxc/validate-sdn-basic.sh
cd terraform/lxc/ansible && ansible-lint playbooks/validate-sdn-basic.yml
git status --short --branch
```

## Stop Conditions

- Task 30g report is missing or not marked complete.
- Harness scope expands beyond `test-lxc` + `net-build-01`.
- `shellcheck` or `ansible-lint` fails and cannot be fixed in-scope.
- Unexpected tracked changes appear outside scoped files.
