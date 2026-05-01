# Task 35: Run the basic SDN smoke harness on pve-test

## Type

Development

## Objective

Run the basic SDN smoke harness on `pve-test` to prove we can deploy and validate
one simple SDN use case with a reduced container set.

Harness scope:

- `test-lxc`
- `net-build-01`

## Files

- `docs/refactor-remove-portainer/tasks/35-run-basic-sdn-smoke-harness.md`
- `docs/refactor-remove-portainer/prompts/35-run-basic-sdn-smoke-harness.yaml`
- `terraform/lxc/validate-sdn-basic.sh`
- `terraform/lxc/ansible/playbooks/validate-sdn-basic.yml`

## Preconditions

- Task 34 is complete and report is present:
  - `docs/refactor-remove-portainer/reports/34-add-basic-sdn-smoke-harness-report.md`
- `TF_VAR_proxmox_node` resolves to `pve-test`.
- Do not widen scope beyond the two harness stacks.

## Operations

1. Apply the two harness stacks.
2. Run the harness validation phase.
3. Capture whether baseline check and SDN probe pass/fail.
4. Leave containers running for Task 36 idempotency check.
5. Write task report:
   - `docs/refactor-remove-portainer/reports/35-run-basic-sdn-smoke-harness-report.md`

## Postconditions

- Basic deploy/validate path is executed with concrete evidence.
- First blocker (if any) is isolated in a smaller scope.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
./with-secrets bash -lc 'cd terraform/lxc && ./validate-sdn-basic.sh apply'
./with-secrets bash -lc 'cd terraform/lxc && ./validate-sdn-basic.sh validate'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Any harness stack apply fails.
- Harness validation cannot complete.
- Unexpected tracked changes appear outside scoped report file.
