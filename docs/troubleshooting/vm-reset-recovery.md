# Proxmox Host Reset Recovery

This guide describes the current recovery path for `pve-test` after a fresh Proxmox
install, host reset, or any event that removes the automation baseline needed by this
repository.

The active recovery model is:

- host bootstrap with `ansible/00-initial-setup/proxmox-initial-setup.yml`
- Terraform token setup with `ansible/01-base-system/terraform-token-management.yml`
- token-based Proxmox API authentication via `automation@pve!terraform`

For the planned bootstrap sequence, see `docs/plan/phase-00a-proxmox-host-bootstrap.md`.

## When to use this guide

- After reinstalling Proxmox VE on `pve-test`
- After restoring the host to a state that lost repository, token, or firewall settings
- When Terraform or Ansible automation can no longer authenticate to Proxmox
- Before starting a new development rebuild pass and you need to re-establish a known-good host baseline

## Quick recovery checklist

```bash
# 1. Confirm the host is reachable
ping -c 1 pve-test.gibbsgreatly.xyz
ssh root@pve-test.gibbsgreatly.xyz "pveversion"

# 2. Reapply the host bootstrap baseline
cd ansible
ansible-playbook -i inventory/dev.yml 00-initial-setup/proxmox-initial-setup.yml

# 3. Create or rotate the Terraform token
ansible-playbook -i inventory/dev.yml 01-base-system/terraform-token-management.yml

# 4. Update local env files if the token changed
#    .env and/or .env.pve-test

# 5. Verify API access with the token
curl -ks -H "Authorization: PVEAPIToken=automation@pve!terraform=<TOKEN_SECRET>" \
  "https://pve-test.gibbsgreatly.xyz:8006/api2/json/version"
```

## Recovery procedure

### 1. Confirm basic host access

Before changing anything, make sure the host is reachable and you still have root SSH:

```bash
ping -c 1 pve-test.gibbsgreatly.xyz
ssh root@pve-test.gibbsgreatly.xyz "hostname && pveversion"
```

If root SSH does not work, recover that first in Proxmox or on the console before using any repository automation.

### 2. Reapply the Proxmox baseline

Run the current bootstrap playbook:

```bash
cd ansible
ansible-playbook -i inventory/dev.yml 00-initial-setup/proxmox-initial-setup.yml
```

This restores the current baseline expectations, including:

- Proxmox no-subscription repository configuration
- package update/upgrade after repo normalization
- optional subscription nag suppression
- `automation@pve` creation
- Terraform token creation support
- optional host firewall backend enablement when configured

### 3. Recreate or rotate the Terraform token

Run:

```bash
cd ansible
ansible-playbook -i inventory/dev.yml 01-base-system/terraform-token-management.yml
```

The playbook prints the token values needed by Terraform:

- `TF_VAR_pm_api_token_id`
- `TF_VAR_pm_api_token_secret`

If the token was rotated, update your local `.env` and/or `.env.pve-test` files with the new secret before running Terraform again.

### 4. Verify token-based API access

Test Proxmox API access directly:

```bash
curl -ks -H "Authorization: PVEAPIToken=automation@pve!terraform=<TOKEN_SECRET>" \
  "https://pve-test.gibbsgreatly.xyz:8006/api2/json/version"
```

Expected result: JSON containing the Proxmox version.

### 5. Verify host prerequisites for the current network model

The active project uses Proxmox SDN VLAN zones on a VLAN-aware `vmbr0`, with the MikroTik as the L3 gateway.

Useful checks:

```bash
ssh root@pve-test.gibbsgreatly.xyz "bridge vlan show"
ssh root@pve-test.gibbsgreatly.xyz "pveum user list | grep automation@pve"
ssh root@pve-test.gibbsgreatly.xyz "pveum user token list automation@pve"
```

If the host firewall backend is expected for SDN/VNet firewall work, also check:

```bash
ssh root@pve-test.gibbsgreatly.xyz "grep -n 'nftables:' /etc/pve/nodes/pve-test/host.fw"
```

## Common failure cases

### Ansible cannot reach the host

Check:

- `pve-test.gibbsgreatly.xyz` resolves to the right host
- root SSH works with your configured key
- `ansible/inventory/dev.yml` still matches the current host IP and SSH key path

### Terraform cannot authenticate to Proxmox

Check:

- the token exists: `pveum user token list automation@pve`
- the token secret in `.env` or `.env.pve-test` is current
- Terraform is targeting the correct Proxmox hostname

If needed, rerun:

```bash
cd ansible
ansible-playbook -i inventory/dev.yml 01-base-system/terraform-token-management.yml
```

### Network/SDN issues after reinstall

Check:

- `vmbr0` is present and VLAN-aware
- MikroTik VLAN interfaces and gateways still exist
- SDN VLAN zones were re-applied if the rebuild wiped them

Useful references:

- `docs/reference/sdn-segment-routing.md`
- `terraform/lxc/network/pve-test.yaml`
- `docs/plan/phase-04-core-shared-services.md`

## Notes

- This guide intentionally reflects the current token-based bootstrap path, not the older password-based `automation@pve` workflow.
- `scripts/check-proxmox-status.sh` still reflects some older assumptions, so use direct host and API checks when recovering the current `pve-test` environment.
