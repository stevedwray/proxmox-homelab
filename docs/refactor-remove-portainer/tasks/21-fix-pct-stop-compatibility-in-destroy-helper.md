# Task 21: Fix `pct stop` compatibility in the rebuild-gate destroy helper

## Type

Development

## Objective

Fix the stop-first rebuild-gate destroy helper so its live stop command is
compatible with the actual `pct` CLI on `pve-test`, while keeping scope limited
to the helper destroy path.

This is a narrow rebuild-unblocker implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/21-fix-pct-stop-compatibility-in-destroy-helper.md`
- `docs/refactor-remove-portainer/prompts/21-fix-pct-stop-compatibility-in-destroy-helper.yaml`
- `scripts/rebuild-gate-destroy.sh`

## Preconditions

- Task 20a is blocked and recorded in:
  - `docs/refactor-remove-portainer/reports/20a-rebuild-gate-with-corrected-evidence-handling-report.md`
- Treat the Task 20a stop condition as authoritative:
  - `./scripts/rebuild-gate-destroy.sh --execute` failed at
    `authentik-stack` (`vmid=150`) because the remote host rejected:
    - `pct stop '<vmid>' --timeout 120`
    - error text included: `Unknown option: timeout`
      and `400 unable to parse option`
- Scope is limited to the destroy helper compatibility fix. Do not widen into:
  - Terraform module refactors
  - LXC runtime changes inside guests
  - full rebuild-gate retry
  - provision/smoke/idempotency validation
- Preserve the local workspace hazards:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`

## Background

Task 19 introduced the stop-first helper. Task 20a then reached the first live
destroy step and showed the helper's stop invocation is not compatible with the
target Proxmox CLI on `pve-test`.

The failure is narrow and concrete: the helper's `pct stop` command includes an
unsupported `--timeout` option. The next step is to correct that command path
and validate the helper again without widening into the full rebuild gate.

## Operations

1. Add Task 21 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the narrow helper-compatibility follow-up to Task 20a.
2. Inspect the actual supported `pct stop` syntax on `pve-test` using a
   non-destructive host query.
3. Update `scripts/rebuild-gate-destroy.sh` so the stop-first phase uses a
   host-compatible stop invocation.
4. Keep the helper behavior otherwise unchanged:
   - repo-root enforcement
   - `pve-test` preflight
   - target scope derived from `terraform/lxc/stacks/*/stack.yaml`
   - dry-run support
   - no-op handling for stopped/absent CTs
   - existing stack-only Terragrunt destroy command after the stop-first phase
5. Validate the helper with:
   - source-only checks (`shellcheck`, dry-run)
   - a narrow live stop-path validation on `pve-test` that proves the revised
     stop invocation no longer fails on option parsing
6. Do not rerun the full rebuild gate in this task.
7. Write the implementation report to:
   - `docs/refactor-remove-portainer/reports/21-pct-stop-compatibility-fix-report.md`

## Postconditions

- The helper's stop-first phase is compatible with the actual `pct` CLI on
  `pve-test`.
- The option-parsing failure from Task 20a is resolved.
- The rebuild gate can be retried in a later task without this known helper
  defect.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/20a-rebuild-gate-with-corrected-evidence-handling-report.md && echo present
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct help stop | sed -n "1,120p"'
shellcheck scripts/rebuild-gate-destroy.sh
./scripts/rebuild-gate-destroy.sh --dry-run
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 150'
git status --short --branch
./with-secrets /home/steve/.local/bin/sonar-scanner
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms Task 20a evidence is present on disk
- host inspection confirms the supported `pct stop` syntax on `pve-test`
- `shellcheck` passes for the updated helper
- dry-run mode still prints the expected target scope and destroy command
- narrow live validation no longer fails on `Unknown option: timeout`
- Sonar reports no new issues

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 20a evidence is missing from disk.
- Host inspection reveals the fix would require a wider redesign of the helper
  or destroy path.
- Validation reveals a different live stop-path failure beyond the option
  parsing defect.
- Sonar reports new issues.
- Unexpected tracked changes appear outside scoped files.
