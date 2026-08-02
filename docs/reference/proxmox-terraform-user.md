# Terraform API User for Proxmox

This reference describes the Terraform authentication pattern used by this
repository. The historical implementation started on `pve-test`, and the same
automation user/token model is now being prepared for production `pve`.

## Current model

The active automation path uses:

- Proxmox user: `automation@pve`
- Proxmox token: `automation@pve!terraform`
- Terraform stacks under `terraform/lxc/`
- Token values loaded from local environment files and SOPS-managed secret
  files

Note: the `automation@pve!terraform` token shown above is the full-scope
Terraform provisioning token used during bootstrap and apply flows. For
day-2 discovery and monitoring/read-only automation (NetBox population,
topology discovery), prefer a dedicated read-only token such as
`automation@pve!terraform-readonly` exposed via `PROXMOX_READONLY_TOKEN_ID`.

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

If the user already exists and you only want to rotate the token manually on the
Proxmox host, the minimal sequence is:

```bash
pveum user token list automation@pve --output-format json
pveum user token remove automation@pve terraform
pveum user token add automation@pve terraform --privsep 0 --output-format json
```

The token secret is shown only at creation time. Capture it immediately and
store it in the correct SOPS file for the target environment.

Terraform API tokens are per-node secrets, not common ones — they're
meaningless against any other node's API — so each node's own
`terraform/secrets.<node>.enc.yaml` is the source of truth for its token
secret, never `terraform/secrets.common.enc.yaml`. For the `pve-test-vm`
workflow that's `terraform/secrets.pve-test-vm.enc.yaml`; for production
`pve` it's `terraform/secrets.pve.enc.yaml`. Avoid keeping a second
long-lived plaintext copy in the corresponding `.env.<node>` if the SOPS
file is available locally; otherwise you must resync that file immediately
after rotation.

## Environment variables used by Terraform

Keep token secrets out of `terraform.tfvars`. Load them from the shell environment.

Example:

```bash
export TF_VAR_pm_api_token_id="automation@pve!terraform"
export TF_VAR_pm_api_token_secret="<TOKEN_SECRET>"
```

On the active development workstation, `.env.pve-test-vm` may derive `PROXMOX_TOKEN_SECRET`
from `terraform/secrets.pve-test-vm.enc.yaml` at source time so the shell always follows the
SOPS-backed token source of truth.

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
- the token secret in the correct SOPS-backed environment source is current
- the target hostname matches the active environment

## Production Validation Note

On May 22, 2026, the production token path for `automation@pve!terraform` was
validated successfully with a read-only `/version` API call to
`pve.gibbsgreatly.xyz`, returning HTTP 200.

## Notes and caveats

- The older `privsep=1` guidance is still generally true for restricted Proxmox tokens, but
  it is not the pattern this repository currently uses.
- The active implementation is optimized for a single-node development target, not for a
  tightly scoped least-privilege multi-node production role model.
- Stack-specific networking, storage, and SDN behavior is defined in `terraform/lxc/`,
  not in this reference document.
