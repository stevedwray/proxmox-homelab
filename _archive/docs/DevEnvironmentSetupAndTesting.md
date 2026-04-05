# Phase 2: Development Environment Setup Guide (WSL1 Compatible)

## Important: WSL Version for VMware Compatibility

**Critical**: This setup is designed for WSL1 to ensure compatibility with VMware Workstation. WSL2 uses Hyper-V which conflicts with VMware's virtualization.

### Check and Convert WSL Version
```bash
# Check your current WSL version
wsl --list --verbose

# If you're running WSL2, convert to WSL1:
wsl --set-version <your-distro-name> 1

# Verify the change
wsl --list --verbose
```

## Quick Start Instructions

### 1. Create Repository Structure
```bash
# Download and run the structure creation script
curl -sSL https://raw.githubusercontent.com/your-repo/proxmox-homelab/main/scripts/create-repo-structure.sh | bash

# Or if you want to specify a custom directory:
curl -sSL [...]/create-repo-structure.sh | bash -s /path/to/your/directory
```

### 2. Run Development Environment Setup
```bash
# Navigate to your new repository
cd ~/proxmox-homelab

# Run the development environment setup
chmod +x scripts/setup-dev-env.sh
./scripts/setup-dev-env.sh
```

### 3. Configure Environment
```bash
# Copy and edit the environment template
cp .env.template .env
nano .env

# Add your Proxmox lab details:
PROXMOX_HOST=192.168.1.100
PROXMOX_USER=root@pam
PROXMOX_PASSWORD=your-password
ANTHROPIC_API_KEY=your-api-key-here
# ... etc
```

### 4. Validate Setup
```bash
# Run comprehensive validation
./scripts/validate-environment.sh

# Should show all green checkmarks for a successful setup
```

### 5. Open in VSCode
```bash
# Open the workspace in VSCode
code proxmox-homelab.code-workspace

# Install recommended extensions when prompted:
# - Remote - WSL
# - Continue.dev
# - HashiCorp Terraform
# - Ansible
```

## Detailed Setup Process
### WSL1 Environment Verification
```bash
# Check WSL version (should show version 1)
wsl --list --verbose

# Verify you're in WSL1 (should NOT show WSL2)
cat /proc/version

# Check available resources
free -h
df -h

# If you see WSL2, convert to WSL1:
# (Run this from Windows Command Prompt or PowerShell)
wsl --set-version <your-distro> 1
```

### Git Configuration
```bash
# Verify Git is configured
git config --global --list

# Test SSH connection to GitHub
ssh -T git@github.com

# Initialize your repository
cd ~/proxmox-homelab
git init
git remote add origin https://github.com/your-username/proxmox-homelab.git
```

### Python Environment Setup
```bash
# Activate the Ansible environment
source ~/.activate-ansible

# Verify installations
python --version
ansible --version
terraform --version

# Test Python packages
python -c "import proxmoxer; print('Proxmoxer OK')"
```

### Proxmox Connection Testing
```bash
# Test SSH connection to Proxmox
ssh root@your-proxmox-ip

# Test API connection
curl -k -d "username=root@pam&password=your-password" \
  https://your-proxmox-ip:8006/api2/json/access/ticket

# Test with Ansible
cd ansible
ansible -i inventory/test-lab.yml proxmox -m ping
```

## VSCode Integration Setup

### Workspace Configuration
1. Open VSCode in WSL2: `code ~/proxmox-homelab`
2. When prompted, install WSL2 extension
3. Install recommended extensions from `.vscode/extensions.json`
4. Open the workspace file: `proxmox-homelab.code-workspace`

### Continue.dev Setup
1. Install the Continue.dev extension
2. Add your Anthropic API key to `.env` file
3. Restart VSCode to load the configuration
4. Test with Ctrl+Shift+P → "Continue: Open Sidebar"

### Testing the AI Integration
```bash
# Test custom commands in Continue.dev:
# 1. Select some Terraform code
# 2. Use /terraform command to get assistance
# 3. Try /security-review on infrastructure code
# 4. Use /ansible for playbook help
```

## Repository Structure Setup

### Initialize Git Repository
```bash
cd ~/proxmox-homelab
git init
git add .
git commit -m "Initial repository structure"
git branch -M main
git remote add origin https://github.com/your-username/proxmox-homelab.git
git push -u origin main
```

### Set Up Pre-commit Hooks
```bash
# Install pre-commit hooks
pre-commit install

# Test the hooks
pre-commit run --all-files

# This will run:
# - YAML syntax checks
# - Terraform formatting and validation
# - Ansible linting
# - Security scans
# - Secret detection
```

## Testing Procedures

### 1. Environment Validation
```bash
# Run the validation script
scripts/validate-environment.sh

# Expected output:
# ✓ WSL2 environment detected
# ✓ All tools installed and accessible
# ✓ Python virtual environment configured
# ✓ SSH keys present and configured
# ✓ Git configured
# ✓ Proxmox connection successful
```

### 2. Terraform Testing
```bash
cd terraform/environments/test-vm

# Initialize Terraform
terraform init

# Validate configuration
terraform validate

# Plan deployment (should connect to Proxmox)
terraform plan

# Apply to create test resources
terraform apply
```

### 3. Ansible Testing
```bash
cd ansible

# Test connection to Proxmox host
ansible -i inventory/test-lab.yml proxmox -m ping

# Run base configuration playbook
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml --check

# Apply configuration (dry run first)
ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml --check
```

### 4. Security Pipeline Testing
```bash
# Run local security scans
pre-commit run --all-files

# Test individual tools
tfsec terraform/
ansible-lint ansible/
trivy fs .

# Commit changes to trigger GitHub Actions
git add .
git commit -m "Test security pipeline"
git push
```

### 5. Backup Procedures Testing
```bash
# Test backup script (dry run)
scripts/backup-procedures.sh --dry-run

# Create test data and backup
scripts/create-test-data.sh
scripts/backup-procedures.sh

# Test restore procedures
scripts/restore-procedures.sh --test
```

## Troubleshooting Guide

### Common Issues and Solutions

#### 1. WSL1 Network Issues
```bash
# WSL1 uses different networking than WSL2
# If Proxmox connection fails, check network connectivity
ping your-proxmox-ip

# WSL1 shares Windows network stack, so check Windows networking
ipconfig /all  # From Windows cmd

# Test from WSL1
curl -k https://your-proxmox-ip:8006
```

#### 2. Terraform Provider Issues
```bash
# If Proxmox provider fails to initialize
cd terraform/environments/test-vm
rm -rf .terraform .terraform.lock.hcl
terraform init

# Check provider version compatibility
terraform providers
```

#### 3. Ansible Connection Issues
```bash
# Test SSH connectivity
ssh -v root@your-proxmox-ip

# Check SSH key permissions
ls -la ~/.ssh/
chmod 600 ~/.ssh/id_rsa
chmod 644 ~/.ssh/id_rsa.pub

# Test Ansible connectivity with verbose output
ansible -i inventory/test-lab.yml proxmox -m ping -vvv
```

#### 4. Continue.dev API Issues
```bash
# Check API key is set
echo $ANTHROPIC_API_KEY

# Verify .env file is loaded
cat .env | grep ANTHROPIC

# Check VSCode settings
code ~/.vscode/settings.json
```

#### 5. Pre-commit Hook Failures
```bash
# Update pre-commit hooks
pre-commit autoupdate

# Skip hooks for emergency commits
git commit -m "Emergency fix" --no-verify

# Fix common issues
terraform fmt -recursive terraform/
ansible-lint --fix ansible/
```

## Next Steps After Setup

### 1. Create Your First Infrastructure
```bash
# Customize the test environment
cd terraform/environments/test-vm
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars

# Deploy test infrastructure
terraform plan
terraform apply
```

### 2. Set Up Monitoring
```bash
# Deploy monitoring stack
ansible-playbook -i inventory/test-lab.yml 02-infrastructure/monitoring.yml
```

### 3. Configure Backups
```bash
# Set up automated backups
ansible-playbook -i inventory/test-lab.yml 02-infrastructure/backup-setup.yml

# Test backup procedures
scripts/backup-procedures.sh
```

### 4. Security Hardening
```bash
# Run security hardening playbook
ansible-playbook -i inventory/test-lab.yml 01-base-system/security-hardening.yml

# Validate security configuration
scripts/security-audit.sh
```

## Success Metrics

Your Phase 2 setup is complete when you can:

- [ ] Successfully run all tools (Terraform, Ansible, etc.) in WSL2
- [ ] Connect to your Proxmox lab VM via SSH and API
- [ ] Create and destroy test infrastructure with Terraform
- [ ] Configure systems with Ansible playbooks
- [ ] Use Continue.dev for AI-assisted development
- [ ] Pass all pre-commit security checks
- [ ] Successfully backup and restore test data
- [ ] View and interact with your code in VSCode with all extensions working

## Performance Optimization

### WSL2 Resource Allocation
```bash
# Create or edit ~/.wslconfig on Windows side:
[wsl2]
memory=8GB
processors=4
swap=2GB
```

### Git Performance
```bash
# Enable Git credential caching
git config --global credential.helper cache
git config --global credential.helper 'cache --timeout=3600'

# Enable Git filesystem caching
git config --global core.preloadindex true
git config --global core.fscache true
git config --global gc.auto 256
```

### VSCode Performance
```bash
# Add to VSCode settings.json:
{
    "git.autofetch": true,
    "git.enableSmartCommit": true,
    "files.watcherExclude": {
        "**/.git/objects/**": true,
        "**/.git/subtree-cache/**": true,
        "**/node_modules/**": true,
        "**/.terraform/**": true
    }
}
```

This completes your Phase 2 development environment setup. You now have a fully integrated AI-enhanced development environment ready for infrastructure automation!
