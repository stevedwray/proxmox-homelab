# NetBox Day-2 Bootstrap Fix Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation
Task approval: netbox-day2-bootstrap-fix-20260524
Scope: Fix the source-controlled NetBox day-2/bootstrap path for production `pve` without rerunning the full teardown/rebuild packet and without broadening into Portainer recovery.

## Evidence Reviewed First

- `docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md`
- `docs/productionize-refactor/handoffs/25-netbox-pve-recovery-handback.md`
- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix.md`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/provision-netbox-stack.log`
- `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-232209/logs/netbox-direct-health-after-stop.log`

## Root Cause Confirmed

The remaining NetBox defect is in the day-2/bootstrap path, not the Terraform apply path.

Confirmed from bounded live reproductions on the existing production `netbox-stack`:

- the exact `createsuperuser` command shape timed out under an explicit wrapper and returned `124`
- a trivial `manage.py shell -c ...` probe also timed out under an explicit wrapper and returned `124`

Captured evidence:

- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/repro-createsuperuser-direct.log`
- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/repro-manage-shell-smoke.log`

Interpretation:

- the previous playbook used two overlapping bootstrap mechanisms
  - `createsuperuser`
  - a later ORM-based local-admin/token sync
- container health alone was not a sufficient gate for bootstrap safety
- when NetBox's Django shell path is slow or stalled, the old play could block indefinitely at bootstrap

The source-controlled fix therefore removes the overlapping bootstrap paths and adds explicit bounds around the only remaining bootstrap execution path.

## Files Changed

- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md`

## Code Change Summary

Updated `deploy-netbox-stack.yml` so the NetBox bootstrap path is single-path, bounded, and rerunnable:

1. Kept the existing container health wait.
2. Added a dedicated Django-shell readiness check using:
   - `docker exec ... manage.py shell -c "print('NETBOX_BOOTSTRAP_READY')"`
   - explicit timeout
   - bounded retries and delay
3. Removed the standalone `createsuperuser` task.
4. Removed the separate API-token shell task.
5. Replaced them with one bootstrap sync script that idempotently ensures:
   - the `admin` superuser and password
   - the `steve` local admin user
   - the `breakglass` local admin user and password
   - the automation API token when missing
6. Wrapped the unified bootstrap execution in `timeout` so future failures fail fast instead of hanging indefinitely.

Resulting intended behavior:

- one deterministic bootstrap path instead of multiple overlapping ones
- explicit timeout on both readiness detection and bootstrap execution
- idempotent rerun semantics for users and token creation

## Validation Run

### Syntax Validation

Passed:

- `ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook --syntax-check -i terraform/lxc/stacks/netbox-stack/inventory.yml terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- extracted/compiled the embedded `netbox-bootstrap-sync.py` block from `deploy-netbox-stack.yml` to verify the Python block scalar is syntactically valid

### Targeted Production Reproduction

Executed with explicit task approval:

- `TASK_APPROVAL=netbox-day2-bootstrap-fix-20260524 ./with-secrets-prod ./scripts/provision.sh --stack netbox-stack`

Captured logs:

- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/preflight-target.log`
- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/repro-createsuperuser-direct.log`
- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/repro-manage-shell-smoke.log`
- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/provision-netbox-stack-rerun.log`
- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/provision-netbox-stack-rerun-after-fix.log`

### Production Validation Result

Result: blocked at host reachability before the playbook could exercise the patched bootstrap tasks.

Both targeted reruns failed immediately at the first gather-facts step with:

- `Failed to connect to the host via ssh: Connection timed out during banner exchange`
- host: `192.168.40.12`

This means:

- the required production rerun was executed
- the final patched playbook was the target of the second rerun
- end-to-end bootstrap convergence remains unproven because the NetBox host became SSH-unreachable during validation

## Resulting State

NetBox container status on Proxmox after the failed rerun was captured from `pve`:

- `docs/productionize-refactor/evidence/netbox-day2-bootstrap-fix-20260524/logs/pve-netbox-status-current.log`

Observed state:

- CT `40012` `netbox-stack` is still `running`
- memory is effectively saturated: `mem = 985.88 MiB` of `maxmem = 1.00 GiB`
- pressure signals are very high:
  - `pressurecpusome = 99.26`
  - `pressurememoryfull = 97.00`
  - `pressurememorysome = 99.33`

Interpretation:

- the container is up from Proxmox's perspective
- validation was blocked by live host responsiveness, not by a new syntax or parsing error in the playbook
- the new bounded bootstrap logic is in source, but final production convergence still needs one more rerun after the host is reachable again

## Remaining Risks

1. Live production convergence of the new bootstrap path is not yet proven because `netbox-stack` stopped answering SSH during validation.
2. The container is under severe memory pressure. Even with the bootstrap path simplified and bounded, low-memory behavior may still delay or fail Django-shell readiness.
3. No full teardown/rebuild was rerun, per scope.
4. `portainer-stack` was not touched, per scope.

## Recommended Next Step

Once `netbox-stack` is SSH-reachable again, rerun exactly:

- `TASK_APPROVAL=netbox-day2-bootstrap-fix-20260524 ./with-secrets-prod ./scripts/provision.sh --stack netbox-stack`

and confirm the play reaches and completes the unified `Run NetBox bootstrap sync` task.
