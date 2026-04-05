#!/bin/bash
set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }

# Default workspace directory
WORKSPACE_DIR="${1:-$HOME/proxmox-homelab}"

create_directory_structure() {
    log_info "Creating directory structure in: $WORKSPACE_DIR"
    
    # Create main directories
    mkdir -p "$WORKSPACE_DIR"
    cd "$WORKSPACE_DIR"
    
    # Create all subdirectories
    local dirs=(
        ".devcontainer"
        ".github/workflows"
        ".vscode"
        ".continue"
        "terraform/environments/test-vm"
        "terraform/environments/production"
        "terraform/modules"
        "ansible/01-base-system"
        "ansible/02-infrastructure"  
        "ansible/03-applications"
        "ansible/inventory"
        "ansible/group_vars"
        "ansible/host_vars"
        "docs"
        "scripts"
        "backups"
    )
    
    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
        log_success "Created directory: $dir"
    done
}

create_devcontainer_files() {
    log_info "Creating DevContainer configuration..."
    
    cat > .devcontainer/devcontainer.json << 'EOF'
{
    "name": "Proxmox Homelab Development",
    "image": "mcr.microsoft.com/devcontainers/base:ubuntu-22.04",
    "features": {
        "ghcr.io/devcontainers/features/terraform:1": {},
        "ghcr.io/devcontainers/features/python:1": {
            "version": "3.11"
        },
        "ghcr.io/devcontainers/features/git:1": {}
    },
    "customizations": {
        "vscode": {
            "extensions": [
                "hashicorp.terraform",
                "redhat.ansible", 
                "ms-python.python",
                "continue.continue",
                "ms-vscode.vscode-json",
                "ms-vscode-remote.remote-wsl"
            ]
        }
    },
    "postCreateCommand": "pip install -r requirements.txt && ansible-galaxy install -r ansible/requirements.yml"
}
EOF
    log_success "Created .devcontainer/devcontainer.json"
}

create_github_workflows() {
    log_info "Creating GitHub Actions workflows..."
    
    cat > .github/workflows/security-scan.yml << 'EOF'
name: Security Scan

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  sast-scan:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - name: Run Trivy vulnerability scanner
      uses: aquasecurity/trivy-action@master
      with:
        scan-type: 'fs'
        scan-ref: '.'
        format: 'sarif'
        output: 'trivy-results.sarif'
    
    - name: Upload Trivy scan results
      uses: github/codeql-action/upload-sarif@v2
      with:
        sarif_file: 'trivy-results.sarif'

  terraform-security:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - name: Setup Terraform
      uses: hashicorp/setup-terraform@v2
    
    - name: Terraform Security Scan
      uses: triat/terraform-security-scan@v3.1.0
      with:
        tfsec_actions_comment: true
        tfsec_output_format: sarif
        tfsec_output_file: tfsec.sarif
    
    - name: Upload tfsec scan results
      uses: github/codeql-action/upload-sarif@v2
      with:
        sarif_file: tfsec.sarif
EOF
    log_success "Created .github/workflows/security-scan.yml"
}

create_vscode_config() {
    log_info "Creating VSCode configuration..."
    
    cat > .vscode/settings.json << 'EOF'
{
    "files.associations": {
        "*.yml": "yaml",
        "*.yaml": "yaml",
        "*.tf": "terraform",
        "*.tfvars": "terraform"
    },
    "terraform.experimentalFeatures.validateOnSave": true,
    "terraform.experimentalFeatures.prefillRequiredFields": true,
    "ansible.python.interpreterPath": "~/.ansible-venv/bin/python",
    "ansible.validation.enabled": true,
    "ansible.validation.lint.enabled": true,
    "python.defaultInterpreterPath": "~/.ansible-venv/bin/python",
    "files.exclude": {
        "**/.terraform": true,
        "**/*.tfstate": true,
        "**/*.tfstate.*": true,
        "**/.env": true
    },
    "continue.telemetryEnabled": false,
    "continue.enableTabAutocomplete": true
}
EOF

    cat > .vscode/extensions.json << 'EOF'
{
    "recommendations": [
        "ms-vscode-remote.remote-wsl",
        "continue.continue",
        "hashicorp.terraform",
        "redhat.ansible",
        "ms-python.python",
        "ms-vscode.vscode-json",
        "timonwong.shellcheck",
        "foxundermoon.shell-format"
    ]
}
EOF

    cat > .vscode/tasks.json << 'EOF'
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Terraform Init",
            "type": "shell",
            "command": "terraform",
            "args": ["init"],
            "group": "build",
            "options": {
                "cwd": "${workspaceFolder}/terraform/environments/test-vm"
            },
            "presentation": {
                "echo": true,
                "reveal": "always",
                "focus": false,
                "panel": "shared"
            }
        },
        {
            "label": "Terraform Plan",
            "type": "shell",
            "command": "terraform",
            "args": ["plan"],
            "group": "build",
            "options": {
                "cwd": "${workspaceFolder}/terraform/environments/test-vm"
            }
        },
        {
            "label": "Ansible Lint",
            "type": "shell",
            "command": "ansible-lint",
            "args": ["ansible/"],
            "group": "test"
        },
        {
            "label": "Run Security Scan",
            "type": "shell",
            "command": "pre-commit",
            "args": ["run", "--all-files"],
            "group": "test"
        },
        {
            "label": "Validate Environment",
            "type": "shell",
            "command": "${workspaceFolder}/scripts/validate-environment.sh",
            "group": "test",
            "presentation": {
                "echo": true,
                "reveal": "always",
                "focus": true,
                "panel": "new"
            }
        }
    ]
}
EOF
    log_success "Created VSCode configuration files"
}

create_continue_config() {
    log_info "Creating Continue.dev configuration..."
    
    cat > .continue/config.json << 'EOF'
{
    "models": [
        {
            "title": "Claude 3.5 Sonnet",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
            "apiKey": "${ANTHROPIC_API_KEY}",
            "contextLength": 200000,
            "completionOptions": {
                "temperature": 0.1,
                "topP": 1.0,
                "maxTokens": 4096
            }
        }
    ],
    "tabAutocompleteModel": {
        "title": "Claude 3.5 Sonnet",
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "apiKey": "${ANTHROPIC_API_KEY}"
    },
    "customCommands": [
        {
            "name": "terraform",
            "prompt": "Help me write Terraform configuration for Proxmox. Focus on:\n- Best practices for resource management\n- Proper variable usage and validation\n- Security considerations\n- Documentation\n\nContext: {{{ input }}}"
        },
        {
            "name": "ansible",
            "prompt": "Help me create Ansible playbooks for infrastructure automation. Focus on:\n- Idempotent tasks\n- Error handling and validation\n- Variable management\n- Role organization\n- Security best practices\n\nContext: {{{ input }}}"
        },
        {
            "name": "proxmox",
            "prompt": "Help me with Proxmox VE configuration and automation. Focus on:\n- LXC container management\n- ZFS storage configuration\n- Backup and restore procedures\n- API integration\n- Security hardening\n\nContext: {{{ input }}}"
        },
        {
            "name": "security-review",
            "prompt": "Review this infrastructure code for security issues. Check for:\n- Hardcoded secrets or sensitive data\n- Excessive permissions\n- Missing encryption\n- Network security concerns\n- Authentication/authorization issues\n- Compliance with security best practices\n\nCode to review:\n{{{ input }}}"
        }
    ],
    "contextProviders": [
        {
            "name": "diff",
            "params": {}
        },
        {
            "name": "folder",
            "params": {
                "folders": ["terraform", "ansible", "scripts", "docs"]
            }
        },
        {
            "name": "codebase",
            "params": {}
        }
    ]
}
EOF
    log_success "Created .continue/config.json"
}

create_terraform_files() {
    log_info "Creating Terraform configuration files..."
    
    # Main Terraform configuration
    cat > terraform/environments/test-vm/main.tf << 'EOF'
terraform {
  required_version = ">= 1.0"
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "~> 2.9"
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.proxmox_api_url
  pm_user         = var.proxmox_user
  pm_password     = var.proxmox_password
  pm_tls_insecure = var.proxmox_tls_insecure
}

# Test LXC containers
resource "proxmox_lxc" "test_containers" {
  count        = var.test_container_count
  target_node  = var.proxmox_node
  hostname     = "test-${count.index + 1}"
  ostemplate   = var.lxc_template
  password     = var.lxc_password
  unprivileged = true
  
  memory = 512
  cores  = 1
  
  rootfs {
    storage = var.storage_pool
    size    = "8G"
  }
  
  network {
    name   = "eth0"
    bridge = var.network_bridge
    ip     = "dhcp"
  }
  
  tags = "test,development"
}
EOF

    cat > terraform/environments/test-vm/variables.tf << 'EOF'
variable "proxmox_api_url" {
  description = "Proxmox API URL"
  type        = string
}

variable "proxmox_user" {
  description = "Proxmox username"
  type        = string
}

variable "proxmox_password" {
  description = "Proxmox password"
  type        = string
  sensitive   = true
}

variable "proxmox_tls_insecure" {
  description = "Skip TLS verification"
  type        = bool
  default     = true
}

variable "proxmox_node" {
  description = "Proxmox node name"
  type        = string
  default     = "pve"
}

variable "test_container_count" {
  description = "Number of test containers to create"
  type        = number
  default     = 2
}

variable "lxc_template" {
  description = "LXC template to use"
  type        = string
  default     = "local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst"
}

variable "lxc_password" {
  description = "Password for LXC containers"
  type        = string
  sensitive   = true
}

variable "storage_pool" {
  description = "Storage pool for containers"
  type        = string
  default     = "local-zfs"
}

variable "network_bridge" {
  description = "Network bridge for containers"
  type        = string
  default     = "vmbr0"
}
EOF

    cat > terraform/environments/test-vm/outputs.tf << 'EOF'
output "container_info" {
  description = "Information about created containers"
  value = {
    for container in proxmox_lxc.test_containers :
    container.hostname => {
      id       = container.vmid
      hostname = container.hostname
      node     = container.target_node
      memory   = container.memory
      cores    = container.cores
      tags     = container.tags
    }
  }
}
EOF

    cat > terraform/environments/test-vm/terraform.tfvars.example << 'EOF'
proxmox_api_url = "https://192.168.1.100:8006/api2/json"
proxmox_user    = "root@pam"
proxmox_node    = "pve"
lxc_password    = "your-secure-password"

test_container_count = 3
storage_pool         = "local-zfs"
network_bridge       = "vmbr0"
EOF

    log_success "Created Terraform configuration files"
}

create_ansible_files() {
    log_info "Creating Ansible configuration files..."
    
    cat > ansible/ansible.cfg << 'EOF'
[defaults]
inventory = inventory/
host_key_checking = False
timeout = 30
gather_facts = True
fact_caching = memory
fact_caching_timeout = 86400

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
retries = 3
EOF

    cat > ansible/requirements.yml << 'EOF'
collections:
  - community.general
  - community.crypto
  - ansible.posix
EOF

    cat > ansible/inventory/test-lab.yml << 'EOF'
all:
  children:
    proxmox:
      hosts:
        pve-lab:
          ansible_host: 192.168.1.100
          ansible_user: root
          ansible_ssh_private_key_file: ~/.ssh/id_rsa
    
    test_containers:
      hosts:
        test-1:
          ansible_host: "{{ hostvars['pve-lab']['container_ips']['test-1'] | default('192.168.1.101') }}"
          ansible_user: root
          container_id: 101
        test-2:
          ansible_host: "{{ hostvars['pve-lab']['container_ips']['test-2'] | default('192.168.1.102') }}"
          ansible_user: root
          container_id: 102
      vars:
        ansible_ssh_private_key_file: ~/.ssh/id_rsa
EOF

    cat > ansible/01-base-system/base-config.yml << 'EOF'
---
- name: Configure base system
  hosts: all
  become: yes
  vars:
    packages_to_install:
      - curl
      - wget
      - vim
      - htop
      - unzip
      - git
      - python3
      - python3-pip
  
  tasks:
    - name: Update package cache
      apt:
        update_cache: yes
        cache_valid_time: 3600
    
    - name: Install base packages
      apt:
        name: "{{ packages_to_install }}"
        state: present
    
    - name: Configure timezone
      timezone:
        name: "{{ timezone | default('UTC') }}"
    
    - name: Setup SSH keys
      authorized_key:
        user: "{{ ansible_user }}"
        key: "{{ lookup('file', ssh_public_key_path) }}"
        state: present
      when: ssh_public_key_path is defined
EOF

    # Create placeholder playbooks
    cat > ansible/02-infrastructure/monitoring.yml << 'EOF'
---
- name: Setup monitoring infrastructure
  hosts: all
  become: yes
  
  tasks:
    - name: Placeholder for monitoring setup
      debug:
        msg: "Monitoring configuration will be implemented here"
EOF

    cat > ansible/03-applications/docker-setup.yml << 'EOF'
---
- name: Setup Docker in LXC containers
  hosts: test_containers
  become: yes
  
  tasks:
    - name: Placeholder for Docker setup
      debug:
        msg: "Docker container setup will be implemented here"
EOF

    log_success "Created Ansible configuration files"
}

create_root_config_files() {
    log_info "Creating root configuration files..."
    
    cat > .gitignore << 'EOF'
# Environment files
.env
.env.local
*.env

# Terraform
*.tfstate
*.tfstate.*
.terraform/
.terraform.lock.hcl
crash.log
crash.*.log
*.tfvars
*.tfvars.json
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# Ansible
*.retry
.vault_pass
host_vars/
group_vars/

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# IDE
.vscode/settings.json
.vscode/launch.json
.vscode/extensions.json
.idea/

# OS
.DS_Store
Thumbs.db

# SSH Keys
id_rsa
id_rsa.pub
*.pem
*.key

# Logs
*.log
EOF

    cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: detect-private-key
      - id: check-merge-conflict

  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.81.0
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
      - id: terraform_docs

  - repo: https://github.com/ansible/ansible-lint
    rev: v6.17.2
    hooks:
      - id: ansible-lint
        files: \.(yaml|yml)$
        exclude: .github/
EOF

    cat > requirements.txt << 'EOF'
ansible>=7.0.0
proxmoxer>=2.0.0
requests>=2.28.0
python-dotenv>=1.0.0
paramiko>=3.0.0
jinja2>=3.1.0
pyyaml>=6.0
netaddr>=0.8.0
EOF

    cat > .env.template << 'EOF'
# Proxmox Connection Settings
PROXMOX_HOST=your-proxmox-ip
PROXMOX_USER=root@pam
PROXMOX_PASSWORD=your-password
PROXMOX_TOKEN_ID=your-token-id
PROXMOX_SECRET=your-secret

# SSH Configuration
SSH_USER=your-ssh-user
SSH_PRIVATE_KEY_PATH=~/.ssh/id_rsa

# Terraform Settings
TF_VAR_proxmox_api_url=https://${PROXMOX_HOST}:8006/api2/json
TF_VAR_proxmox_user=${PROXMOX_USER}
TF_VAR_proxmox_password=${PROXMOX_PASSWORD}

# Ansible Settings
ANSIBLE_HOST_KEY_CHECKING=False
ANSIBLE_PRIVATE_KEY_FILE=${SSH_PRIVATE_KEY_PATH}

# Continue.dev API Key
ANTHROPIC_API_KEY=your-anthropic-api-key

# Backup Settings
BACKUP_NFS_SERVER=your-nfs-server
BACKUP_NFS_PATH=/mnt/backup
EOF

    cat > proxmox-homelab.code-workspace << 'EOF'
{
    "folders": [
        {
            "name": "Proxmox Homelab",
            "path": "."
        }
    ],
    "settings": {
        "files.associations": {
            "*.yml": "yaml",
            "*.yaml": "yaml",
            "*.tf": "terraform",
            "*.tfvars": "terraform"
        },
        "terraform.experimentalFeatures.validateOnSave": true,
        "ansible.python.interpreterPath": "~/.ansible-venv/bin/python",
        "python.defaultInterpreterPath": "~/.ansible-venv/bin/python",
        "terminal.integrated.defaultProfile.linux": "bash",
        "terminal.integrated.env.linux": {
            "ANSIBLE_CONFIG": "${workspaceFolder}/ansible/ansible.cfg"
        }
    },
    "extensions": {
        "recommendations": [
            "ms-vscode-remote.remote-wsl",
            "continue.continue",
            "hashicorp.terraform",
            "redhat.ansible",
            "ms-python.python"
        ]
    }
}
EOF

    log_success "Created root configuration files"
}

create_documentation() {
    log_info "Creating documentation files..."
    
    cat > README.md << 'EOF'
# Proxmox Homelab Infrastructure

Infrastructure as Code for Proxmox-based homelab using Terraform and Ansible.

## Overview

This repository contains automation scripts and configurations for managing a Proxmox-based homelab environment with:
- Infrastructure provisioning via Terraform
- Configuration management via Ansible
- Security scanning and validation
- AI-assisted development with Continue.dev

## Quick Start

1. **Setup Environment**
   ```bash
   # Run the setup script (installs tools, creates structure)
   ./scripts/setup-dev-env.sh
   
   # Validate the setup
   ./scripts/validate-environment.sh
   ```

2. **Configure Settings**
   ```bash
   # Copy and edit environment settings
   cp .env.template .env
   nano .env  # Add your Proxmox details
   ```

3. **Deploy Test Infrastructure**
   ```bash
   cd terraform/environments/test-vm
   terraform init
   terraform plan
   terraform apply
   ```

4. **Configure Systems**
   ```bash
   cd ansible
   ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
   ```

## Repository Structure

```
proxmox-homelab/
├── .devcontainer/          # Development container config
├── .github/workflows/      # CI/CD pipelines
├── .vscode/               # VSCode settings and tasks
├── .continue/             # AI assistant configuration
├── terraform/
│   ├── environments/
│   │   ├── test-vm/       # VMware lab environment
│   │   └── production/    # Production hardware
│   └── modules/           # Reusable Terraform modules
├── ansible/
│   ├── 01-base-system/    # Base system configuration
│   ├── 02-infrastructure/ # Infrastructure services
│   ├── 03-applications/   # Application deployment
│   └── inventory/         # Host inventories
├── docs/                  # Documentation
├── scripts/               # Automation scripts
└── backups/              # Backup storage
```

## Key Features

- **Infrastructure as Code**: Complete automation of Proxmox infrastructure
- **Security First**: Automated security scanning and validation
- **AI-Enhanced**: Continue.dev integration for intelligent development
- **Testing**: Comprehensive validation and testing procedures
- **Documentation**: Well-documented procedures and troubleshooting

## Prerequisites

- WSL1 (for VMware Workstation compatibility)
- Proxmox VE lab environment
- Git, Terraform, Ansible (installed by setup script)

## Documentation

See the `docs/` directory for detailed documentation including:
- Setup and installation guides
- Configuration references
- Troubleshooting procedures
- Best practices

## Development Workflow

1. Make changes to infrastructure code
2. Run security scans with `pre-commit run --all-files`
3. Test changes in lab environment
4. Deploy to production when validated

## Support

For issues and questions, see the troubleshooting guide in `docs/troubleshooting.md`
EOF

    mkdir -p docs
    cat > docs/getting-started.md << 'EOF'
# Getting Started Guide

This guide will walk you through setting up your Proxmox homelab development environment.

## Prerequisites

- Windows with WSL1 installed
- VMware Workstation with Proxmox VM
- Git configured with SSH keys
- Basic familiarity with infrastructure concepts

## Step-by-Step Setup

### 1. Environment Setup
[Detailed setup instructions here]

### 2. Proxmox Configuration
[Proxmox-specific setup steps]

### 3. First Deployment
[Walk-through of first infrastructure deployment]

### 4. Validation and Testing
[How to validate your setup]

## Next Steps

After completing the setup, you can:
- Deploy your first test containers
- Set up monitoring and alerting
- Configure backup procedures
- Explore advanced features
EOF

    cat > docs/troubleshooting.md << 'EOF'
# Troubleshooting Guide

Common issues and their solutions.

## WSL Issues

### WSL1 vs WSL2
If you're having issues with VMware Workstation, ensure you're using WSL1:
```bash
wsl --set-version <distro> 1
```

## Terraform Issues

### Provider Initialization Failures
[Common Terraform provider issues and solutions]

## Ansible Issues

### SSH Connection Problems
[SSH and connectivity troubleshooting]

## Continue.dev Issues

### API Key Configuration
[How to properly configure API keys]
EOF

    log_success "Created documentation files"
}

create_script_stubs() {
    log_info "Creating script stubs..."
    
    # Create executable backup script stub
    cat > scripts/backup-procedures.sh << 'EOF'
#!/bin/bash
set -euo pipefail

# Backup procedures for Proxmox homelab
# This is a stub - implement actual backup logic

echo "Backup procedures script"
echo "Usage: $0 [--dry-run|--test]"

# Load environment if available
if [[ -f .env ]]; then
    source .env
fi

# Implement your backup logic here
echo "Backup functionality will be implemented here"
EOF
    chmod +x scripts/backup-procedures.sh

    # Create test data creation script
    cat > scripts/create-test-data.sh << 'EOF'
#!/bin/bash
set -euo pipefail

# Create test data for backup/restore testing

echo "Creating test data for backup validation..."
# Implement test data creation logic here
EOF
    chmod +x scripts/create-test-data.sh

    # Create security audit script
    cat > scripts/security-audit.sh << 'EOF'
#!/bin/bash
set -euo pipefail

# Security audit script for infrastructure

echo "Running security audit..."
# Implement security audit logic here
EOF
    chmod +x scripts/security-audit.sh

    log_success "Created script stubs"
}

initialize_git_repo() {
    log_info "Initializing Git repository..."
    
    if [[ -d .git ]]; then
        log_warning "Git repository already exists"
        return
    fi
    
    git init
    git add .
    git commit -m "Initial repository structure

- Created complete directory structure
- Added configuration files for all tools
- Set up VSCode and Continue.dev integration
- Added security scanning workflows
- Created documentation stubs"
    
    log_success "Git repository initialized with initial commit"
}

main() {
    echo "=============================================="
    echo "  PROXMOX HOMELAB STRUCTURE CREATION"
    echo "=============================================="
    echo
    
    log_info "Creating complete repository structure in: $WORKSPACE_DIR"
    
    create_directory_structure
    create_devcontainer_files
    create_github_workflows
    create_vscode_config
    create_continue_config
    create_terraform_files
    create_ansible_files
    create_root_config_files
    create_documentation
    create_script_stubs
    initialize_git_repo
    
    echo
    log_success "Repository structure creation completed!"
    echo
    log_info "Next steps:"
    echo "1. Copy .env.template to .env and configure your settings"
    echo "2. Run the development environment setup script"
    echo "3. Open in VSCode: code $WORKSPACE_DIR"
    echo "4. Install recommended extensions when prompted"
    echo "5. Test your setup with: ./scripts/validate-environment.sh"
    echo
    echo "Repository created at: $WORKSPACE_DIR"
}

# Handle command line arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [DIRECTORY]"
        echo
        echo "Creates the complete Proxmox homelab repository structure."
        echo
        echo "DIRECTORY    Target directory (default: ~/proxmox-homelab)"
        echo
        echo "Options:"
        echo "  --help, -h    Show this help message"
        exit 0
        ;;
esac

main "$@"