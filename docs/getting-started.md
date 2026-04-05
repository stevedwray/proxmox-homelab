# Getting Started with Proxmox Homelab Automation

This guide walks you through setting up and validating the complete Proxmox homelab automation environment.

## Prerequisites

- Windows with WSL1 (for VMware compatibility)
- VMware Workstation with Proxmox VE 9.0+ running
- Git configured with SSH keys
- Basic understanding of infrastructure automation concepts

## Phase 1: Verify Your Foundation

Before starting automation setup, ensure your Proxmox VM is properly configured.

### Proxmox Server Requirements

- Static IP configuration
- FQDN resolution (for example, `pvetest.gibbsgreatly.xyz`)
- SSH access as `root` with key authentication
- Web interface accessible on port `8006`

### Validation

Your Proxmox server should be accessible:

```bash
ping pvetest.gibbsgreatly.xyz
ssh root@pvetest.gibbsgreatly.xyz "pveversion"
curl -k https://pvetest.gibbsgreatly.xyz:8006
```

## Phase 2: Development Environment Setup

### Quick Setup

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
terraform version
ansible --version
git --version
python3 -c "import proxmoxer; print('Proxmoxer available')"
```

## Phase 3: Proxmox Server Configuration

### Configure Your Environment

```bash
cp .env.template .env
nano .env
```

Add your Proxmox lab details, for example:

```bash
PROXMOX_HOST=192.168.1.100
PROXMOX_USER=root@pam
PROXMOX_PASSWORD=your-password
```

### Apply Baseline Setup

```bash
cd ansible
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
```

### Set API Access Password

The playbook creates the `automation@pve` user but does not set a password automatically.

```bash
ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"
```

Update `.env` with the password you chose:

```bash
PROXMOX_HOST=pvetest.gibbsgreatly.xyz
PROXMOX_USER=automation@pve
PROXMOX_PASSWORD=your-chosen-password
```

## Phase 4: Validation and Testing

### Complete System Validation

```bash
./scripts/check-proxmox-status.sh
```

Expected: all checks should pass with green checkmarks.

### Individual Component Testing

**SSH Connectivity**

```bash
ssh root@pvetest.gibbsgreatly.xyz "echo 'Root SSH works'"
ssh automation@pvetest.gibbsgreatly.xyz "sudo whoami"
```

**API Authentication**

```bash
source .env
curl -k -d "username=$PROXMOX_USER&password=$PROXMOX_PASSWORD" \
  https://$PROXMOX_HOST:8006/api2/json/access/ticket
```

**Terraform Integration**

```bash
cd terraform/environments/test-vm
terraform init
terraform validate
terraform plan
```

## Success Criteria

Your environment is ready when:

- [ ] All development tools are installed and working
- [ ] Proxmox server passes complete validation via `./scripts/check-proxmox-status.sh`
- [ ] SSH access works for both `root` and `automation` users
- [ ] API authentication is successful with `automation@pve`
- [ ] Terraform can connect to Proxmox and `terraform plan` succeeds
- [ ] VSCode workspace opens with recommended extensions
- [ ] Continue.dev AI assistant responds to custom commands

## Common Issues and Solutions

### WSL Version Conflicts

If VMware Workstation fails to start VMs:

```bash
wsl --set-version <distro-name> 1
```

### Missing SSH Keys

```bash
ssh-keygen -t rsa -b 4096 -C "your-email@example.com"
ssh-copy-id root@pvetest.gibbsgreatly.xyz
```

### Proxmox Configuration Issues

After VM resets, run the recovery procedure from `docs/troubleshooting/vm-reset-recovery.md`.

```bash
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
ssh root@pvetest.gibbsgreatly.xyz "pveum passwd automation@pve"
./scripts/check-proxmox-status.sh
```

### Package Installation Errors

```bash
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

- `docs/reference/proxmox-server-baseline.md`
- `docs/reference/proxmox-terraform-user.md`
- `docs/reference/dev-environment-setup.md`
- `docs/reference/stack-deployment-generalisation.md`
- `docs/troubleshooting/vm-reset-recovery.md`
- `docs/troubleshooting/ipv6-issues.md`

## Maintenance

### Regular Tasks

- Run validation weekly: `./scripts/check-proxmox-status.sh`
- Update packages monthly
- Test recovery procedures before major changes
- Keep documentation current with manual changes

### Backup Important Files

- `.env` file (secure storage)
- SSH private keys
- Terraform state files
- Custom configuration changes
