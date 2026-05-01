# Task 36: Re-run basic SDN smoke idempotency and teardown

## Type

Development

## Objective

Validate repeatability of the basic SDN smoke harness, then return `pve-test`
to a clean baseline by tearing down the two harness stacks.

Scope:

- `test-lxc`
- `net-build-01`

## Files

- `docs/refactor-remove-portainer/tasks/36-rerun-basic-sdn-smoke-idempotency-and-teardown.md`
- `docs/refactor-remove-portainer/prompts/36-rerun-basic-sdn-smoke-idempotency-and-teardown.yaml`
- `terraform/lxc/validate-sdn-basic.sh`

## Preconditions

- Task 35 is complete and report is present:
  - `docs/refactor-remove-portainer/reports/35-run-basic-sdn-smoke-harness-report.md`
- Harness containers are still present from Task 35, or can be re-applied in scope.

## Operations

1. Re-run harness `apply` and `validate` to check idempotent behavior.
2. Run harness `destroy` to remove the two test stacks.
3. Confirm `pct list` is clean or only contains expected non-harness workloads.
4. Write task report:
   - `docs/refactor-remove-portainer/reports/36-rerun-basic-sdn-smoke-idempotency-and-teardown-report.md`

## Postconditions

- Basic SDN path has repeatability evidence.
- Test scope is torn down after validation.

## Validation

```bash
./with-secrets bash -lc 'cd terraform/lxc && ./validate-sdn-basic.sh apply'
./with-secrets bash -lc 'cd terraform/lxc && ./validate-sdn-basic.sh validate'
./with-secrets bash -lc 'cd terraform/lxc && ./validate-sdn-basic.sh destroy'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

## Stop Conditions

- Apply/validate does not reproduce expected behavior.
- Destroy fails for either stack.
- Unexpected tracked changes appear outside scoped report file.
