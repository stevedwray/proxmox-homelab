# Task 30a: Validate retained container creation with `ci-runner-01`

## Type

Development

## Objective

Run the first proper retained-stack container creation test after the
cleanup-first reset by applying only `ci-runner-01` on `pve-test` and verifying
that the LXC is actually created as expected.

This is a live creation test. It is intentionally narrower than a broad rebuild
or multi-stack harness run.

## Files

- `docs/refactor-remove-portainer/decisions.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/30a-validate-ci-runner-container-creation.md`
- `docs/refactor-remove-portainer/prompts/30a-validate-ci-runner-container-creation.yaml`
- `docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md`
- `terraform/lxc/stacks/ci-runner-01/stack.yaml`

## Preconditions

- Task 30 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md`
  - that report must explicitly show `Status: complete`
- Treat the current live baseline as authoritative:
  - retained CTs `153` (`proxy-stack`) and `154` (`monitoring-stack`) remain
    present
  - `ci-runner-01` is the target stack for this test
- `ci-runner-01` stack metadata is expected to describe:
  - VMID `141`
  - hostname `ci-runner-01`
  - IP `10.57.0.63/24`
  - `network.zone: build_seg`
- Do not run Sonar or Snyk in this task. This is an exploratory live creation
  test, not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current architecture-approved
   package baseline.
2. Verify `pve-test` targeting and capture the current `pct list`.
3. Apply only `terraform/lxc/stacks/ci-runner-01`.
4. Verify that VMID `141` now exists on `pve-test` with the expected hostname.
5. Capture the post-apply `pct list`.
6. Write the task report to:
   - `docs/refactor-remove-portainer/reports/30a-validate-ci-runner-container-creation-report.md`
7. Stop after reporting. Do not start Task 31 automatically.

## Postconditions

- `ci-runner-01` is created on `pve-test`, or the exact first blocker is
  reported.
- Retained CTs outside this task scope are unchanged.
- No additional stacks are applied in this task.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md && echo present
rg -n "^Status: complete$" docs/refactor-remove-portainer/reports/30-classify-and-prune-disposable-sdn-objects-report.md
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets terragrunt --working-dir "terraform/lxc/stacks/ci-runner-01" apply -auto-approve
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct config 141 | sed -n "1,80p"'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 30 evidence is present on disk and explicitly marked complete
- `ci-runner-01` apply succeeds
- VMID `141` exists on the host after apply
- retained CTs `153` and `154` remain present
- no unrelated code or package files are edited beyond the required report

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 30 evidence is missing from disk or does not show `Status: complete`.
- `ci-runner-01` apply fails.
- VMID `141` is not created as expected after a successful apply.
- A retained non-target CT is unexpectedly affected.
- Unexpected tracked changes appear outside the scoped report artifact.
