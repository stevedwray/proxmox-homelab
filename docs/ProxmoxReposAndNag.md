## Project Context for AI Assistant

**Current State:**
- Working Ansible playbook for Proxmox VE 9.0 base system configuration
- Test environment: VMware Workstation running nested Proxmox VE at `pvetest.gibbsgreatly.xyz`
- Ansible inventory configured in `ansible/inventory/test-lab.yml`
- Successfully automated repository fixes, package installation, and subscription nag removal

**Technical Environment:**
- Host: Windows with WSL2 environment at `/mnt/i/proxmox`
- Proxmox VE 9.0 (Debian Trixie base) with deb822 source format
- Ansible 2.18.8 installed with community.general collection
- SSH key authentication configured between WSL2 and Proxmox test server

**Working Ansible Playbook:**
Located at `01-base-system/base-config.yml` with validated tasks:
- Disables enterprise repositories by commenting entire deb822 stanzas
- Adds pve-no-subscription repository in correct deb822 format
- Performs full system upgrade and installs base packages
- Removes subscription nag via JavaScript modification: `sed -i 's/res.data.status.toLowerCase() !== '\''active'\''/false/'`
- Disables HA services for single-node setup

**Critical Implementation Details:**
- Proxmox VE 9 requires commenting all lines in `.sources` files, not just `Types:` line
- Original subscription check targets `'active'` string, not `'NoMoreNagging'`
- Repository order: disable enterprise → add no-subscription → update cache
- Use `failed_when: false` for missing files during cleanup
- Shell module more reliable than replace module for complex sed operations

**Project Structure:**
```
/mnt/i/proxmox/ansible/
├── inventory/test-lab.yml (configured for pvetest.gibbsgreatly.xyz)
├── 01-base-system/base-config.yml (working playbook)
├── 02-infrastructure/ (empty)
├── 03-applications/ (empty)
└── ansible.cfg (basic configuration)
```

**Next Phase Options:**
1. Container provisioning via Ansible proxmox module
2. Terraform integration for infrastructure-as-code
3. Application deployment automation
4. Backup/restore procedures

**Validation Requirements:**
Test all automation on fresh Proxmox installations via snapshot restore to catch environment-specific assumptions that work on modified systems but fail on clean deployments.
