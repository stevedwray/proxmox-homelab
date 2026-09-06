# Production Secrets Template (pve node delta)

This file documents the expected key surface for `terraform/secrets.pve.enc.yaml`
— the **delta** file for the `pve` node, not the full secret set. As of
2026-07-17 (see `docs/framework-integration/decisions.md` Decision 6), most
secrets live in `terraform/secrets.common.enc.yaml` and are shared across
every environment; this file holds only the handful of keys genuinely tied
to `pve`'s own Proxmox node identity. The real file must be SOPS-encrypted.

Creation/update flow:
1. Edit `terraform/secrets.pve.enc.yaml` via SOPS:
   `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.pve.enc.yaml`
2. Keep this template in sync whenever required keys change.

## Required in `terraform/secrets.pve.enc.yaml` (this node's delta)

These are per-node by construction — a read-only/Terraform token for one
Proxmox API endpoint is meaningless against another, and `TF_VAR_lxc_password`
is kept per-node by operator choice. See
`docs/reference/secrets-management.md`'s "The common/per-node split" for the
rule on where a new secret belongs.

```
PROXMOX_READONLY_TOKEN_ID: <pve read-only Proxmox API token ID>
PROXMOX_READONLY_TOKEN_SECRET: <pve read-only Proxmox API token secret>
TF_VAR_pm_api_token_secret: <pve Terraform automation token secret>
TF_VAR_lxc_password: <pve-specific LXC root password override>
```

## Also required, but from `terraform/secrets.common.enc.yaml`

`with-secrets-prod` merges `secrets.common.enc.yaml` with this file
(this file wins on any key collision) — it does **not** load only this
file. Everything else a production Terragrunt plan or an Ansible stack
playbook needs (Authentik, step-ca, Grafana, Harbor, NetBox, MikroTik,
`CF_DNS_API_TOKEN`, `BREAKGLASS_PASSWORD`, `TF_VAR_portainer_admin_password`,
`PORTAINER_OAUTH_CLIENT_SECRET`, etc.) comes from the common file. See
`docs/reference/secrets-management.md`'s "Secret inventory" for the full
common-file key list — it is not duplicated here to avoid the two lists
drifting out of sync again.

## Notes

- `with-secrets-prod` loads `terraform/secrets.common.enc.yaml` merged with
  `terraform/secrets.pve.enc.yaml`, this file's values winning on conflict.
- Do not add a secret here that's actually meant to be shared — check
  `docs/reference/secrets-management.md` first; duplicating a common
  secret into this file is exactly the drift this restructuring removed.
- This template is plaintext documentation; never store real secret values here.
