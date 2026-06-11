# Harbor/Authentiк Parity Handback (Task 14)

Date: 2026-05-23
Branch: `work/productionize-06-canary-validation`

## Root Cause

Harbor OIDC activation was controlled by `harbor_postconfigure_oidc_enabled` (environment intent), not by Authentik reconcile outcome (runtime readiness).

In `deploy-harbor-stack.yml`, the playbook could:

1. mark Authentik unreachable and skip Harbor Authentik client reconcile, then
2. still invoke `harbor_postconfigure` with OIDC enabled, causing `Configure Harbor OIDC auth mode` to run anyway.

That sequencing allowed Harbor to enter `auth_mode=oidc_auth` even when the Harbor Authentik OIDC client reconcile was deferred.

## Files Changed

1. `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- Added `harbor_postconfigure_oidc_ready` computed gate.
- `harbor_postconfigure_oidc_ready=true` only when:
  - OIDC is requested,
  - Authentik health probe returned HTTP 200,
  - Harbor Authentik reconcile task executed (not skipped), and
  - reconcile exit code was successful.
- Added explicit defer message when OIDC is requested but not ready.
- Passed effective gate to role (`harbor_postconfigure_oidc_enabled` now uses readiness, not request intent).

2. `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml`
- Added read of Harbor current configuration and recorded `auth_mode`.
- Switched breakglass-create/skip logic to use Harbor current `auth_mode` instead of requested OIDC intent.
- This preserves idempotence when Harbor is already in `oidc_auth` from an earlier run and avoids trying to create a local user in a mode where Harbor forbids it.

3. `terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md`
- Documented new OIDC convergence behavior: OIDC apply is deferred unless Authentik client reconcile succeeds in the same run.

## Validation Run

Safe validation only (no production mutation):

1. Ansible syntax check from Ansible root:

```bash
cd terraform/lxc/ansible
HARBOR_HOSTNAME=harbor.lab.gibbsgreatly.xyz \
HARBOR_ADMIN_PASSWORD=dummy \
HARBOR_OIDC_CLIENT_SECRET=dummy \
HARBOR_OIDC_CLIENT_ID=harbor \
ansible-playbook -i ../stacks/harbor-stack/inventory.yml \
  playbooks/deploy-harbor-stack.yml --syntax-check
```

Result: pass (`playbook: playbooks/deploy-harbor-stack.yml`).

2. Targeted ansible-lint from Ansible root:

```bash
cd terraform/lxc/ansible
ansible-lint playbooks/deploy-harbor-stack.yml roles/harbor_postconfigure/tasks/main.yml
```

Result: no fatal errors in modified logic; only pre-existing warnings outside this fix scope.

## Execution Scope

Code-only fix. No live production apply/provision was executed in this session.

## TLS Verification Behavior

No TLS verification behavior changed.

- Authentik reachability probe in Harbor deploy playbook remains `validate_certs: true`.
- Harbor OIDC `oidc_verify_cert` handling was not altered.

## Remaining Risks / Operator Steps

1. Existing drifted Harbor instances already in `auth_mode=oidc_auth` are not forcibly rolled back by this change.
2. To converge a drifted host cleanly:
- ensure Authentik internal direct-TLS endpoint is healthy,
- rerun Harbor stack provisioning so Authentik reconcile succeeds,
- verify Harbor OIDC settings and login flow post-run.
3. If immediate rollback to local auth is required for an already drifted production Harbor, perform that as an explicit operator-directed remediation (not auto-enforced by this safety guard).
