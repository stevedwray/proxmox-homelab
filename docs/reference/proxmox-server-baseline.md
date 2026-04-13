# Proxmox Server Baseline Configuration

This document defines the current baseline for a Proxmox VE host that is going to run the
active `pve-test` build path.

## Overview

The baseline exists to make a freshly installed Proxmox host automation-ready before
`terraform/lxc` stacks are applied. In the current project, this work is primarily done by:

- `ansible/00-initial-setup/proxmox-initial-setup.yml`
- `ansible/01-base-system/proxmox-terraform-setup.yml`
- `ansible/01-base-system/terraform-token-management.yml`

For planning context, see `docs/plan/phase-00a-proxmox-host-bootstrap.md`.

## Baseline Components

### Repository Configuration
- **Enterprise repository**: removed or disabled
- **No-subscription repositories**: enabled for Proxmox VE and optional Ceph packages
- **Package cache**: updated after repository changes
- **Dist upgrade**: applied after repo normalization

### System Users
- **root**: initial bootstrap entry point
- **automation@pve**: Proxmox VE user used by Terraform automation

### API Token
- **automation@pve!terraform**: Proxmox API token used by Terraform
- Token management is handled by the bootstrap playbooks, not manually tracked in this doc

### Security Configuration
- **Subscription nag**: optionally removed from the web interface
- **Host firewall backend**: nftables backend can be enabled for Proxmox firewall work
- **SSH**: root access is used for initial host bootstrap only
- **Token-based API auth**: preferred over password auth for Terraform

### Service Configuration
- **Single-node host**: `pve-test` is treated as a single-node development target
- **VLAN-aware bridge**: `vmbr0` must be configured as VLAN-aware for SDN VLAN zones
- **MikroTik gateway model**: routing and SNAT are handled by the MikroTik, not Proxmox

### Package Installation
Standard packages installed:
- repo and system tools required by the bootstrap playbooks
- Proxmox host packages updated through normal apt upgrade flow
- no special app-stack packages are assumed at the host level

## Validation Checklist

Use `scripts/check-proxmox-status.sh` to validate the baseline:

- [ ] Network connectivity (ping, SSH port 22, HTTPS port 8006)
- [ ] SSH access as root user for initial bootstrap
- [ ] API authentication works with the Terraform token
- [ ] API version information retrieval
- [ ] Enterprise repository disabled
- [ ] No-subscription repository enabled
- [ ] Subscription nag removed
- [ ] `automation@pve` user exists
- [ ] Terraform API token exists or can be rotated
- [ ] Storage pools available
- [ ] `vmbr0` exists and is VLAN-aware when SDN VLAN zones are in use

## Restoration Procedure

After a fresh Proxmox installation on `pve-test`:

1. **Apply baseline configuration**:
   ```bash
   cd ansible
   ansible-playbook 00-initial-setup/proxmox-initial-setup.yml
   ```

2. **Create or rotate the Terraform token if needed**:
   ```bash
   cd ansible
   ansible-playbook 01-base-system/terraform-token-management.yml
   ```

3. **Update local environment files** with the token values if they changed

4. **Validate configuration**:
   ```bash
   ./scripts/check-proxmox-status.sh
   ```

## Expected Results

After successful baseline application, the validation script should show:
- All critical checks passing (green checkmarks)
- Only optional warnings (yellow) acceptable
- API authentication working with the Terraform token

## Troubleshooting

### Common Issues
- **Repository drift**: rerun `proxmox-initial-setup.yml` to normalize sources
- **Missing Terraform token**: rerun `terraform-token-management.yml`
- **API authentication failure**: verify the token values in `.env` or `.env.pve-test`
- **SDN networking issues**: confirm `vmbr0` is VLAN-aware and the MikroTik VLANs exist

### Recovery Commands
If manual intervention is needed:
```bash
# Verify the Terraform user exists
ssh root@pve-test.gibbsgreatly.xyz "pveum user list | grep automation@pve"

# List Terraform tokens for that user
ssh root@pve-test.gibbsgreatly.xyz "pveum user token list automation@pve"

# Confirm vmbr0 is VLAN-aware
ssh root@pve-test.gibbsgreatly.xyz "bridge vlan show"
```

## Integration with Infrastructure Automation

The baseline configuration provides the foundation for:
- **Terraform**: uses `automation@pve!terraform` for Proxmox API access
- **Ansible bootstrap**: prepares the host and token before stack deployment
- **SDN VLAN zones**: depends on a VLAN-aware `vmbr0` and MikroTik-side VLAN setup
- **Stack deployment**: expects the host baseline to be stable before `terraform/lxc` runs

## Maintenance

The baseline should be:
- **Tested regularly**: run the validation script after rebuilds or host changes
- **Updated as needed**: modify the bootstrap playbooks for new requirements
- **Documented**: record any manual host step that should move into automation
- **Version controlled**: All changes committed to Git repository

This baseline configuration ensures reliable, repeatable infrastructure that supports the full automation workflow.
