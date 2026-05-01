# Task 29a: Manually remove orphaned disposable validation containers on `pve-test`

## Type

Development

## Objective

Remove the disposable validation containers directly on `pve-test` after Task 29
proved they are orphaned host objects rather than Terraform-managed stack
resources.

This is a narrow cleanup unblocker task. It removes orphaned disposable CTs
only. It does not remove SDN zones, VNets, or subnets.

## Files

- `docs/refactor-remove-portainer/decisions.md`
- `docs/refactor-remove-portainer/task-sequence.md`
- `docs/refactor-remove-portainer/prompts/index.yaml`
- `docs/refactor-remove-portainer/tasks/29a-manually-remove-orphaned-disposable-validation-containers.md`
- `docs/refactor-remove-portainer/prompts/29a-manually-remove-orphaned-disposable-validation-containers.yaml`
- `docs/refactor-remove-portainer/reports/29-strip-down-disposable-validation-containers-report.md`

## Preconditions

- Task 29 is blocked and recorded in:
  - `docs/refactor-remove-portainer/reports/29-strip-down-disposable-validation-containers-report.md`
  - that report must explicitly show `Status: blocked`
  - that report must explicitly identify orphaned disposable CTs with empty
    Terraform state
- Treat the current live baseline as authoritative:
  - orphaned disposable validation CTs `130` through `140` may still be
    present on `pve-test`
  - retained platform CTs `153` (`proxy-stack`) and `154`
    (`monitoring-stack`) are not in scope for removal
- Scope is limited to manual cleanup of the orphaned disposable CT fleet:
  - `130` `test-lxc`
  - `131` `test-docker`
  - `132` `net-client-01`
  - `133` `net-service-01`
  - `134` `net-app-01`
  - `135` `net-svc-01`
  - `136` `net-isolated-01`
  - `137` `net-client-02`
  - `138` `net-service-02`
  - `139` `net-build-01`
  - `140` `net-artifacts-01`
- Do not change Terraform or Ansible source files in this task.
- Do not remove or mutate SDN zones, VNets, or subnets in this task.
- Do not run Sonar or Snyk in this task. This is an exploratory cleanup
  unblocker, not a merge-candidate integration task.

## Operations

1. Cut a clean short-lived branch from the current architecture-approved
   package baseline.
2. Verify `pve-test` targeting and capture the current `pct list`.
3. For each orphaned disposable VMID in scope, confirm whether it still exists.
4. If it exists, stop it if needed and destroy it directly on the Proxmox host.
5. If a listed VMID is already absent, record that as an explicit no-op rather
   than treating it as a failure.
6. Re-check `pct list` after the cleanup pass.
7. Write the task report to:
   - `docs/refactor-remove-portainer/reports/29a-manual-orphaned-container-cleanup-report.md`
8. Stop after reporting. Do not start Task 30 automatically.

## Postconditions

- VMIDs `130` through `140` are absent from `pve-test`, or the exact first
  blocker is reported.
- Retained platform CTs outside this task scope are unchanged.
- No SDN zone/VNet/subnet pruning is attempted in this task.
- No Terraform/Ansible code changes are mixed into this task.

## Validation

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
test -f docs/refactor-remove-portainer/reports/29-strip-down-disposable-validation-containers-report.md && echo present
rg -n "^Status: blocked$|ORPHANED CONTAINERS|Terraform state is empty" docs/refactor-remove-portainer/reports/29-strip-down-disposable-validation-containers-report.md
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 130 >/dev/null 2>&1 && { pct stop 130 || true; pct destroy 130; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 131 >/dev/null 2>&1 && { pct stop 131 || true; pct destroy 131; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 132 >/dev/null 2>&1 && { pct stop 132 || true; pct destroy 132; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 133 >/dev/null 2>&1 && { pct stop 133 || true; pct destroy 133; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 134 >/dev/null 2>&1 && { pct stop 134 || true; pct destroy 134; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 135 >/dev/null 2>&1 && { pct stop 135 || true; pct destroy 135; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 136 >/dev/null 2>&1 && { pct stop 136 || true; pct destroy 136; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 137 >/dev/null 2>&1 && { pct stop 137 || true; pct destroy 137; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 138 >/dev/null 2>&1 && { pct stop 138 || true; pct destroy 138; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 139 >/dev/null 2>&1 && { pct stop 139 || true; pct destroy 139; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct status 140 >/dev/null 2>&1 && { pct stop 140 || true; pct destroy 140; } || true'
./with-secrets ssh -F /dev/null root@pve-test.gibbsgreatly.xyz 'pct list'
git status --short --branch
```

Expected outcome:

- preflight confirms `pve-test`
- Task 29 evidence is present on disk and explicitly shows the orphaned CT
  blocker
- each orphaned disposable VMID is either removed or already absent
- `pct list` no longer contains VMIDs `130` through `140`
- retained CTs outside this task scope remain present
- no code or package files are edited in this task beyond the required report

## Stop Conditions

- Preflight does not confirm `pve-test`.
- Task 29 evidence is missing from disk or does not show the orphaned CT
  blocker.
- Any in-scope orphaned CT stop or destroy command fails.
- A retained non-disposable CT is unexpectedly targeted or affected.
- Unexpected tracked changes appear outside the scoped report artifact.
