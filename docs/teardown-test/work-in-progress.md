# Teardown/Redeploy Work In Progress

Date: 2026-05-04
Branch: work/pve-test-teardown-redeploy-seq-01
HEAD: 2b1a67e

## Current State

- Full disposable teardown/redeploy cycle completed successfully.
- Containers are up on pve-test.
- Operator verified login to Authentik with user `akadmin`.

## Outstanding Functional Access Issues

The following applications are reachable, but the current authenticated user does not have admin permissions:

- Grafana: not admin
- NetBox: not admin
- Harbor: not admin

## Scope Decision

- Do not remediate RBAC/admin-role mapping in this session.
- Resume tomorrow in a new session.

## Suggested Next Session Start Plan

1. Re-validate target guard:
   - `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` (must be `pve-test`)
2. Confirm application reachability and current role claims for:
   - Grafana
   - NetBox
   - Harbor
3. Trace role/group mapping from Authentik to each app's admin role.
4. Apply minimal role-mapping fix and re-test with `akadmin`.
5. Capture evidence under a new timestamped directory in `docs/teardown-test/evidence/`.

## Relevant Evidence From Today

- Cycle run log: `/tmp/gate-cycle-run.log`
- Evidence directory:
  - `docs/teardown-test/evidence/teardown-redeploy-cycle-01/`

## Notes For Next Operator

- Infrastructure/container health is not the blocker now.
- Remaining work is identity/authorization alignment across Grafana, NetBox, and Harbor.
