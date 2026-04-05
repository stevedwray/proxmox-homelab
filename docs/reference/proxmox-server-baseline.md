# File: docs/phase4-testing-validation/proxmox-server-baseline.md

# Proxmox Server Baseline Configuration

This document defines the standard baseline configuration for Proxmox VE servers in the homelab automation environment.

## Overview

The baseline configuration ensures consistent, automated-ready Proxmox servers that can be reliably restored after VM resets or fresh installations. This configuration is applied via the `base-config.yml` Ansible playbook.

## Baseline Components

### Repository Configuration
- **Enterprise repository**: Disabled (all lines commented out)
- **No-subscription repository**: Enabled for updates
- **Package cache**: Updated and maintained

### System Users
- **automation user**: System user with sudo privileges, SSH key access
- **automation@pve**: Proxmox VE user with Administrator role for API access

### Security Configuration
- **Subscription nag**: Removed from web interface
- **SSH keys**: Deployed for passwordless authentication
- **Sudo access**: Configured for automation user with NOPASSWD

### Service Configuration
- **HA services**: Disabled for single-node setup (pve-ha-lrm, pve-ha-crm, corosync)
- **SSH**: Enabled and configured for key-based authentication

### Package Installation
Standard packages installed:
- curl, wget, vim, htop, unzip, git
- python3, python3-pip
- iftop, iotop, net-tools, smartmontools
- sudo, openssh-server

## Validation Checklist

Use `scripts/check-proxmox-status.sh` to validate the baseline:

- [ ] Network connectivity (ping, SSH port 22, HTTPS port 8006)
- [ ] SSH access as root user
- [ ] SSH access as automation user
- [ ] API authentication with automation@pve user
- [ ] API version information retrieval
- [ ] Enterprise repository disabled
- [ ] No-subscription repository enabled
- [ ] Subscription nag removed
- [ ] Automation system user exists
- [ ] Automation PVE user exists
- [ ] Automation user sudo access
- [ ] Storage pools available
- [ ] Network bridges available

## Restoration Procedure

After VM reset or fresh installation:

1. **Apply baseline configuration**:
   ```bash
   cd ansible
   ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
   ```

2. **Set automation@pve password manually**:
   ```bash
   ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"
   ```

3. **Update .env file** with the password you set

4. **Validate configuration**:
   ```bash
   ./scripts/check-proxmox-status.sh
   ```

## Expected Results

After successful baseline application, the validation script should show:
- All critical checks passing (green checkmarks)
- Only optional warnings (yellow) acceptable
- API authentication working with automation@pve user

## Troubleshooting

### Common Issues
- **Missing sudo package**: Baseline playbook installs this automatically
- **Broken automation user**: Playbook recreates user idempotently
- **API authentication failure**: Verify password in .env matches manually set password

### Recovery Commands
If manual intervention is needed:
```bash
# Recreate automation user
ssh root@proxmox "useradd -m -s /bin/bash -G sudo automation"

# Reset PVE user password
ssh root@proxmox "pveum passwd automation@pve"

# Verify sudo access
ssh automation@proxmox "sudo whoami"
```

## Integration with Infrastructure Automation

The baseline configuration provides the foundation for:
- **Terraform**: Uses automation@pve credentials for Proxmox provider
- **Ansible**: Uses automation user for SSH access and system configuration
- **Backup procedures**: Relies on consistent user and permission setup
- **Monitoring**: Expects standard directory structure and services

## Maintenance

The baseline should be:
- **Tested regularly**: Run validation script weekly
- **Updated as needed**: Modify base-config.yml for new requirements
- **Documented**: Record any manual changes that should be automated
- **Version controlled**: All changes committed to Git repository

This baseline configuration ensures reliable, repeatable infrastructure that supports the full automation workflow.
