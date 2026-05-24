# Day-2 Credential Rotation

This note captures the current supported path for rotating deployment-managed
credentials after a stack is already live.

## Model

- SOPS remains the source of truth.
- Rotation updates `terraform/secrets.pve.enc.yaml` first.
- After the SOPS update, rerun the owning stack's Ansible day-2 reconcile so
  the live service converges to the new value.
- Only credentials with a proven reconcile path should be rotated this way.

## Current Script

Use:

- `scripts/rotate-stack-credentials.py`

The script is production-focused today and targets
`terraform/secrets.pve.enc.yaml`.

Default behavior is plan-only. Add `--execute` to actually rotate values.

## Supported Now

These credentials can be regenerated and converged with the current playbooks:

| Capability | SOPS key | Reconcile stack |
|---|---|---|
| `authentik-lab-admin-password` | `AUTHENTIK_STEVE_PASSWORD` | `authentik-stack` |
| `netbox-superuser-password` | `NETBOX_SUPERUSER_PASSWORD` | `netbox-stack` |
| `grafana-oauth-client-secret` | `GRAFANA_OAUTH_CLIENT_SECRET` | `monitoring-stack` |
| `harbor-oidc-client-secret` | `HARBOR_OIDC_CLIENT_SECRET` | `harbor-stack` |
| `portainer-oauth-client-secret` | `PORTAINER_OAUTH_CLIENT_SECRET` | `portainer-stack` |

## Not Supported Yet

These credentials still need extra day-2 work before they can be rotated
through one safe script:

- `HARBOR_ADMIN_PASSWORD`
- `TF_VAR_portainer_admin_password`
- `GRAFANA_ADMIN_PASSWORD`
- `BREAKGLASS_PASSWORD`
- `AUTHENTIK_SUPERUSER_PASSWORD`
- `AUTHENTIK_SUPERUSER_API_TOKEN`
- `NETBOX_SUPERUSER_API_TOKEN`
- `STEP_CA_PASSWORD`
- `STEP_CA_PROVISIONER_PASSWORD`

Current reasons include:

- the playbook authenticates with the same value you are trying to change
- the value is shared across multiple stacks but not all consumers can converge
  it yet
- the current playbook only bootstraps the value on first install

## Expected Usage

Plan only:

```bash
scripts/rotate-stack-credentials.py \
  --credential authentik-lab-admin-password
```

Execute and reconcile:

```bash
TASK_APPROVAL="prod-credential-rotation" \
scripts/rotate-stack-credentials.py \
  --credential authentik-lab-admin-password \
  --credential harbor-oidc-client-secret \
  --execute
```
