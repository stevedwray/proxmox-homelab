# File: docs/getting-started-updated.md

# Getting Started with Proxmox Homelab Automation

This guide walks you through setting up and validating your complete Proxmox homelab automation environment.

## Prerequisites

- Windows with WSL1 (for VMware compatibility)
- VMware Workstation with Proxmox VE 9.0+ running
- Git configured with SSH keys
- Basic understanding of infrastructure automation concepts

## Phase 1: Verify Your Foundation

Before starting automation setup, ensure your Proxmox VM is properly configured:

### Proxmox Server Requirements
- Static IP configuration
- FQDN resolution (e.g., pvetest.gibbsgreatly.xyz)
- SSH access as root with key authentication
- Web interface accessible on port 8006

### Validation
Your Proxmox server should be accessible:
```bash
ping pvetest.gibbsgreatly.xyz
ssh root@pvetest.gibbsgreatly.xyz "pveversion"
curl -k https://pvetest.gibbsgreatly.xyz:8006
```

## Phase 2: Development Environment Setup

### Quick Setup
Run the automated setup script:
```bash
# Clone or create repository structure
git clone https://github.com/your-username/proxmox-homelab.git
cd proxmox-homelab

# Or create from scratch
curl -sSL https://raw.githubusercontent.com/your-repo/proxmox-homelab/main/scripts/repo-structure-creation.sh | bash
cd ~/proxmox-homelab

# Set up development tools
chmod +x scripts/setup-dev-env.sh
./scripts/setup-dev-env.sh
```

### Manual Verification
```bash
# Verify tool installations
terraform version
ansible --version
git --version

# Check Python packages
python3 -c "import proxmoxer; print('Proxmoxer available')"
```

## Phase 3: Proxmox Server Configuration

### Apply Baseline Configuration
```bash
# Configure environment
cp .env.template .env
nano .env  # Add your Proxmox details

# Apply baseline setup
cd ansible
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
```

### Set API Access Password
```bash
# Set automation@pve user password manually
ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"

# Update .env with the password you chose
nano .env  # Set PROXMOX_PASSWORD=your-chosen-password
```

## Phase 4: Validation and Testing

### Complete System Validation
```bash
# Comprehensive validation
./scripts/check-proxmox-status.sh

# Expected: All checks should pass with ✓ symbols
```

### Individual Component Testing

**SSH Connectivity:**
```bash
ssh root@pvetest.gibbsgreatly.xyz "echo 'Root SSH works'"
ssh automation@pvetest.gibbsgreatly.xyz "sudo whoami"
```

**API Authentication:**
```bash
source .env
curl -k -d "username=$PROXMOX_USER&password=$PROXMOX_PASSWORD" \
  https://$PROXMOX_HOST:8006/api2/json/access/ticket
```

**Terraform Integration:**
```bash
cd terraform/environments/test-vm
terraform init
terraform validate
terraform plan
```

## Success Criteria

Your environment is ready when:

- [ ] All development tools installed and working
- [ ] Proxmox server passes complete validation (check-proxmox-status.sh)
- [ ] SSH access working for both root and automation users
- [ ] API authentication successful with automation@pve user
- [ ] Terraform can connect to Proxmox (terraform plan succeeds)
- [ ] VSCode workspace opens with all recommended extensions
- [ ] Continue.dev AI assistant responds to commands

## Common Issues and Solutions

### WSL Version Conflicts
If VMware Workstation fails to start VMs:
```bash
# Convert WSL2 to WSL1
wsl --set-version <distro-name> 1
```

### Missing SSH Keys
```bash
# Generate SSH keys if missing
ssh-keygen -t rsa -b 4096 -C "your-email@example.com"
ssh-copy-id root@pvetest.gibbsgreatly.xyz
```

### Proxmox Configuration Issues
After VM resets, run the recovery procedure:
```bash
# See docs/troubleshooting/vm-reset-recovery.md
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"
./scripts/check-proxmox-status.sh
```

### Package Installation Errors
```bash
# Install missing packages system-wide if needed
pip install package-name --break-system-packages
sudo apt install missing-package
```

## Next Steps After Setup

### Infrastructure Deployment
1. Create test LXC containers with Terraform
2. Configure containers with Ansible playbooks
3. Set up monitoring and logging
4. Implement backup procedures

### Development Workflow
1. Make infrastructure changes in code
2. Test in VMware lab environment
3. Validate with security scans
4. Deploy to production when ready

### Advanced Features
- Explore LXC template automation
- Set up container orchestration
- Implement disaster recovery testing
- Integrate with external monitoring

## Support Resources

- **Project Documentation**: `docs/` directory
- **Troubleshooting Guide**: `docs/troubleshooting/`
- **API Reference**: `docs/reference/proxmox-api-authentication.md`
- **Recovery Procedures**: `docs/troubleshooting/vm-reset-recovery.md`

## Maintenance

### Regular Tasks
- Run validation weekly: `./scripts/check-proxmox-status.sh`
- Update packages monthly
- Test recovery procedures before major changes
- Keep documentation current with any manual changes

### Backup Important Files
- `.env` file (secure storage)
- SSH private keys
- Terraform state files
- Custom configuration changes

This environment provides a solid foundation for infrastructure automation development with reliable recovery procedures and comprehensive validation.
