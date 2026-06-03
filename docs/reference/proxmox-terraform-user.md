# Terraform API User for Proxmox

This reference describes the current Terraform authentication pattern used by this
repository for the `pve-test` environment.

## Current model

The active automation path uses:

- Proxmox user: `automation@pve`
- Proxmox token: `automation@pve!terraform`
- Terraform stacks under `terraform/lxc/`
- Token values loaded from local environment files such as `.env` or `.env.pve-test`

Note: the `automation@pve!terraform` token shown above is the full-scope
Terraform provisioning token used during bootstrap and apply flows. For
day-2 discovery and monitoring/read-only automation (NetBox population,
topology discovery), prefer a dedicated read-only token such as
`automation@pve!terraform-readonly` exposed via `PROXMOX_READONLY_TOKEN_ID`.

In the current bootstrap flow, the user and token are normally created by:

- `ansible/00-initial-setup/proxmox-initial-setup.yml`
- `ansible/01-base-system/proxmox-terraform-setup.yml`
- `ansible/01-base-system/terraform-token-management.yml`

## How the token is created today

The current playbooks create the token with `privsep=0` and grant the user the
`Administrator` role at `/`.

That means the active implementation is not using the older “privsep token with direct
token ACLs” pattern. If you are following the repository’s normal bootstrap path, you do
not need to create custom Proxmox roles or assign token ACLs by hand.

The relevant Ansible behavior is:

```bash
pveum user add automation@pve --comment "Terraform automation account"
pveum aclmod / -user automation@pve -role Administrator
pveum user token add automation@pve terraform --privsep 0 --output-format json
```

## Rotating the token

To create or rotate the Terraform token:

```bash
cd ansible
ansible-playbook 01-base-system/terraform-token-management.yml
```

That playbook prints:

- `TF_VAR_pm_api_token_id`
- `TF_VAR_pm_api_token_secret`

For the active `pve-test` workflow, `terraform/secrets.enc.yaml` is the source of truth for
the token secret. Avoid keeping a second long-lived plaintext copy in `.env.pve-test` if the
SOPS file is available locally; otherwise you must resync `.env.pve-test` immediately after
rotation.

## Environment variables used by Terraform

Keep token secrets out of `terraform.tfvars`. Load them from the shell environment.

Example:

```bash
export TF_VAR_pm_api_token_id="automation@pve!terraform"
export TF_VAR_pm_api_token_secret="<TOKEN_SECRET>"
```

On the active development workstation, `.env.pve-test` may derive `PROXMOX_TOKEN_SECRET`
from `terraform/secrets.enc.yaml` at source time so the shell always follows the SOPS-backed
token source of truth.

Additional environment values are typically loaded from the project’s local env files
rather than copied into this document.

## Verification

List the token:

```bash
ssh root@pve-test.gibbsgreatly.xyz "pveum user token list automation@pve"
```

Check API access:

```bash
curl -ks -H "Authorization: PVEAPIToken=automation@pve!terraform=<TOKEN_SECRET>" \
  "https://pve-test.gibbsgreatly.xyz:8006/api2/json/version"
```

If Terraform authentication fails, first verify that:

- the token exists
- the token secret in `.env` or `.env.pve-test` is current
- the target hostname matches the active environment

## Notes and caveats

- The older `privsep=1` guidance is still generally true for restricted Proxmox tokens, but
  it is not the pattern this repository currently uses.
- The active implementation is optimized for a single-node development target, not for a
  tightly scoped least-privilege multi-node production role model.
- Stack-specific networking, storage, and SDN behavior is defined in `terraform/lxc/`,
  not in this reference document.
