# Task 20a: Retry the full `pve-test` rebuild gate with corrected evidence handling

## Type

Development

## Objective

Retry the documented rebuild gate after correcting the Task 20 evidence
contract so executor validation uses local report artifacts appropriately
without requiring them to exist on a refreshed clean `dev/pve-test` baseline.

This is an integration validation step, not a new implementation task.

## Files

- `docs/refactor-remove-portainer/runbook.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/20a-retry-rebuild-gate-with-corrected-evidence-handling.md`
- `docs/refactor-remove-portainer/prompts/20a-retry-rebuild-gate-with-corrected-evidence-handling.yaml`

## Preconditions

- Task 20 is blocked due to package/prompt defect and recorded in:
  - `docs/refactor-remove-portainer/reports/20-rebuild-gate-with-stop-first-helper-report.md`
- Treat the Task 20 stop condition as authoritative:
  - report-file existence was checked against a refreshed clean baseline where
    ignored local operational artifacts are not expected to exist
- Task 19 is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/19-stop-first-destroy-helper-report.md`
- Task 19a is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/19-destroy-helper-integration-report.md`
- Task 19b is complete and recorded in:
  - `docs/refactor-remove-portainer/reports/19a-status-update-integration-report.md`
- `origin/dev/pve-test` contains:
  - `18820711b8128c160807479e7a192a5258d88876`
  - `7032ed57758fb4413a5c6ba0305430314ed6b288`
- The rebuild gate must follow `runbook.md` exactly, using:
  - `./scripts/rebuild-gate-destroy.sh --execute`
- The current local workspace contains hazards that must be preserved:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
  - local uncommitted architect package updates under
    `docs/refactor-remove-portainer/`

## Background

Task 20 stopped before live mutation because its prompt incorrectly required
report files under `docs/refactor-remove-portainer/reports/` to exist on a
refreshed clean `origin/dev/pve-test` baseline. Those files are local
operational artifacts and are not integrated source-of-truth content.

The rebuild gate itself remains untested after Task 19/19a/19b. This task
retries the gate with corrected evidence handling: verify the required reports
exist in the executor's local operational workspace before creating or
switching into the clean execution branch/worktree, then proceed with the live
rebuild gate on the refreshed baseline.

## Operations

1. Verify the required local report artifacts exist on disk in the operator's
   current workspace before switching to a refreshed clean execution baseline.
2. Preserve the current workspace hazards and local architect package edits
   non-destructively. Use a separate temporary worktree or another isolation
   method if needed.
3. Refresh or otherwise verify the clean execution baseline so the working
   branch starts from the `dev/pve-test` state that already includes
   `7032ed57758fb4413a5c6ba0305430314ed6b288`.
4. Cut a clean short-lived branch from that refreshed `dev/pve-test` baseline.
5. Execute the rebuild gate exactly as documented in `runbook.md`:
   - `./scripts/rebuild-gate-destroy.sh --execute`
   - `./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- apply -auto-approve`
   - `./with-secrets ./scripts/provision.sh --tier platform`
   - Harbor, step-ca, and Traefik smoke checks
   - Portainer endpoint check
   - second `./with-secrets ./scripts/provision.sh --tier platform` no-op check
6. Stop immediately on the first failing command or any documented stop
   condition.
7. Write the rebuild-gate report to:
   - `docs/refactor-remove-portainer/reports/20a-rebuild-gate-with-corrected-evidence-handling-report.md`
8. Stop after reporting. Do not widen into fix work in this task.

## Postconditions

- If successful, the full rebuild gate has passed with the stop-first destroy
  helper in place.
- If unsuccessful, the report captures the exact failing step, stop condition,
  and observed behavior for a narrow architecture follow-up.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/19-stop-first-destroy-helper-report.md && echo present
test -f docs/refactor-remove-portainer/reports/19-destroy-helper-integration-report.md && echo present
test -f docs/refactor-remove-portainer/reports/19a-status-update-integration-report.md && echo present
git rev-parse origin/dev/pve-test
git merge-base --is-ancestor 7032ed57758fb4413a5c6ba0305430314ed6b288 origin/dev/pve-test && echo yes || echo no
./scripts/rebuild-gate-destroy.sh --execute
./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- apply -auto-approve
./with-secrets ./scripts/provision.sh --tier platform
curl -skf https://10.57.3.10/api/v2.0/ping
curl -skf https://10.57.1.11/health
curl -skf https://10.57.2.10/ping
./with-secrets bash -lc '
  token="$(
    curl -fsS http://10.57.1.20:9000/api/auth \
      -H "Content-Type: application/json" \
      -d "{\"Username\":\"admin\",\"Password\":\"${PORTAINER_ADMIN_PASSWORD}\"}" |
    python3 -c "import json,sys; print(json.load(sys.stdin)[\"jwt\"])"
  )"
  curl -fsS http://10.57.1.20:9000/api/endpoints \
    -H "Authorization: Bearer ${token}" |
  python3 -c "
import json, sys
platform = {
    'portainer-stack',
    'harbor-stack',
    'apt-cacher-stack',
    'ci-runner-01',
    'dns-stack',
    'step-ca-stack',
    'authentik-stack',
    'proxy-stack',
    'monitoring-stack',
    'netbox-stack',
}
names = {item.get('Name', '') for item in json.load(sys.stdin)}
unexpected = sorted(name for name in names if name in platform)
if unexpected:
    raise SystemExit('platform endpoints still registered: ' + ', '.join(unexpected))
print('no platform endpoints registered')
"
'
./with-secrets ./scripts/provision.sh --tier platform
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- source-only validation confirms required local report artifacts are present in
  the operator workspace and the integrated Task 19/19a/19b baseline is
  present on `origin/dev/pve-test`
- destroy/apply run non-interactively
- platform provisioning completes successfully
- Harbor, step-ca, and Traefik smoke tests pass
- Portainer contains no platform agent endpoints after platform provisioning
- the second `provision.sh --tier platform` run is effectively a no-op

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Required local report artifacts are missing from the operator workspace.
- The integrated baseline cannot be verified as containing `7032ed5`.
- Any rebuild-gate command fails.
- Any smoke test fails.
- Portainer still shows platform agent endpoints.
- The second platform provision run reports unresolved drift caused by the
  refactor.
- Unexpected tracked changes appear outside scoped package files.
