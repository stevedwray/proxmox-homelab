# Task 17: Retry the full `pve-test` rebuild gate after stale-lock cleanup

## Type

Development

## Objective

Run a fresh rebuild gate after Task 16 cleared the stale
`infrastructure-containers` storage lock, using the documented two-phase flow
from the runbook.

This is an integration validation step, not a new implementation task.

## Files

- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/17-retry-rebuild-gate-after-stale-lock-cleanup.md`
- `docs/refactor-remove-portainer/prompts/17-retry-rebuild-gate-after-stale-lock-cleanup.yaml`

## Preconditions

- Task 16 is complete and the scoped lock file is absent, or Task 16 reported a
  no-op because the lock was already absent.
- Task 15a is integrated on `dev/pve-test`.
- The runbook commands in `docs/refactor-remove-portainer/runbook.md` are the
  source of truth for the rebuild gate.
- The local workspace hazards must be preserved:
  - modified `terraform/secrets.enc.yaml`
  - untracked `docs/refactor-remove-portainer/prompts/00-architect-prompt.md`
  - untracked `docs/refactor-remove-portainer/prompts/00-operator-handoff.md`
- Scope is rebuild-gate execution only. Do not edit Terraform, Ansible,
  scripts, or runbook files in this task.

## Background

Earlier rebuild-gate attempts were blocked first by package/runbook command
issues and later by stale host lock state on:

- `/var/lock/pve-manager/pve-storage-infrastructure-containers`

Those package issues were corrected by earlier tasks, and Task 16 then removed
the stale/inactive lock file. The next step is therefore a fresh rebuild-gate
retry under the current runbook contract.

## Operations

1. Add Task 17 to package registries (`task-sequence.md`, `prompts/index.yaml`)
   as the explicit rebuild-gate retry step after Task 16.
2. Preserve local workspace hazards non-destructively.
3. Run preflight to confirm the target is still `pve-test`.
4. Confirm Task 16 evidence is present on disk and Task 15a remains integrated
   on `dev/pve-test`.
5. Execute the rebuild gate exactly as documented in the runbook:
   - destroy all LXCs from `terraform/lxc/stacks`
   - provision infrastructure from `terraform/lxc/stacks`
   - configure platform tier explicitly
   - run the three smoke tests
   - confirm Portainer has no platform agent endpoints
   - rerun platform provisioning as the no-op check
6. Stop immediately if any rebuild-gate command fails or a runbook stop
   condition is triggered.
7. Write the task report to:
   - `docs/refactor-remove-portainer/reports/17-rebuild-gate-after-lock-cleanup-report.md`
8. Stop after reporting. Do not widen into fix work inside this task.

## Postconditions

- If successful, the rebuild gate is complete and proves the refactor end to
  end.
- If unsuccessful, the report captures the exact failing step, command, and
  observed behavior for the next architecture iteration.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
git merge-base --is-ancestor de717554a3f91a9261bd6b40e7586d4405144d4e dev/pve-test && echo yes || echo no
test -f docs/refactor-remove-portainer/reports/16-stale-lock-cleanup-report.md && echo present
./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- destroy -auto-approve
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
- source-only validation confirms Task 15a is integrated and Task 16 evidence
  exists on disk
- destroy/apply run non-interactively from `terraform/lxc/stacks`
- platform provisioning completes successfully
- Harbor, step-ca, and Traefik smoke tests pass
- Portainer contains no platform agent endpoints after platform provisioning
- the second `provision.sh --tier platform` run is effectively a no-op

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 16 evidence is missing from disk.
- Any rebuild-gate command fails.
- Any smoke test fails.
- Portainer still shows platform agent endpoints.
- The second platform provision run reports unresolved drift caused by the
  refactor.
- Unexpected tracked changes appear outside scoped package files.
