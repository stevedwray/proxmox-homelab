# Task 30d: Reconcile active MikroTik baseline and build-seg carriage assumptions

## Type

Development

## Objective

Reconcile the repo's stale MikroTik management-host assumptions with the active
`pve-test` router baseline, and clarify the real runtime input contract used by
`with-secrets`.

This task does not repair the `build_seg` data plane itself. It narrows the
remaining failure after Task 30c and updates the baseline assumptions that
future executor tasks must use.

## Files

- `.env.template`
- `ansible/00-initial-setup/mikrotik-dns-lab-zone-baseline.yml`
- `ansible/00-initial-setup/mikrotik-dns-lab-zone-delegate.yml`
- `terraform/lxc/network/pve-test.yaml`
- `docs/refactor-remove-portainer/reports/30d-reconcile-active-mikrotik-baseline-and-build-seg-carriage-report.md`

## Preconditions

- Task 30c is recorded and treated as the latest blocked network evidence.
- Scope is limited to baseline assumptions, runtime config-source clarity, and
  narrow syntax/runtime checks.

## Operations

1. Confirm the active MikroTik management endpoint in use for `pve-test`.
2. Compare the repo's current defaults/comments against that live baseline.
3. Update only the scoped fallback/default/comment paths needed so the package
   no longer points at the retired MikroTik host.
4. Record the sanctioned runtime input contract:
   - local `.env` or `.env.<env>` for non-secret coordinates
   - `terraform/secrets.enc.yaml` for secrets
   - `with-secrets` as the merge/runtime layer
5. Confirm the `build_seg` gateway path is still failing so the package does
   not misstate the remaining blocker.
6. Write the task report and stop.

## Postconditions

- Active MikroTik baseline assumptions are reconciled in the repo.
- The runtime-source contract is explicit.
- The remaining blocker is clearly isolated to the deeper VLAN/data-plane path.
