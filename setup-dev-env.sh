#!/bin/bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running in WSL (1 or 2)
check_wsl() {
    if ! grep -qE "(microsoft|WSL)" /proc/version 2>/dev/null; then
        log_error "This script is designed for WSL. Please run from WSL environment."
        exit 1
    fi
    
    # Check WSL version
    if grep -q "WSL2" /proc/version 2>/dev/null; then
        log_warning "WSL2 detected - this may conflict with VMware Workstation"
        log_info "Consider using WSL1 for VMware compatibility"
        log_info "Convert with: wsl --set-version <distro> 1"
    else
        log_success "Running in WSL1 environment (VMware compatible)"
    fi
}

# Update system packages
update_system() {
    log_info "Updating system packages..."
    sudo apt-get update && sudo apt-get upgrade -y
    sudo apt-get install -y curl wget unzip git python3 python3-pip python3-venv \
        software-properties-common apt-transport-https ca-certificates gnupg lsb-release
    log_success "System packages updated"
}

# Install Terraform
install_terraform() {
    log_info "Installing Terraform..."
    
    # Get latest Terraform version
    TERRAFORM_VERSION=$(curl -s https://api.github.com/repos/hashicorp/terraform/releases/latest | grep '"tag_name"' | cut -d'"' -f4 | sed 's/v//')
    
    # Download and install
    wget -q https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip
    unzip -q terraform_${TERRAFORM_VERSION}_linux_amd64.zip
    sudo mv terraform /usr/local/bin/
    rm terraform_${TERRAFORM_VERSION}_linux_amd64.zip
    
    # Verify installation
    if terraform version >/dev/null 2>&1; then
        log_success "Terraform $(terraform version -json | python3 -c "import sys, json; print(json.load(sys.stdin)['terraform_version'])") installed"
    else
        log_error "Terraform installation failed"
        exit 1
    fi
}

# Install Ansible
install_ansible() {
    log_info "Installing Ansible..."
    
    # Create Python virtual environment for Ansible
    python3 -m venv ~/.ansible-venv
    source ~/.ansible-venv/bin/activate
    
    # Install Ansible and required collections
    pip install --upgrade pip
    pip install ansible proxmoxer requests
    
    # Install community collections
    ansible-galaxy collection install community.general
    ansible-galaxy collection install community.crypto
    
    # Create activation script
    cat > ~/.activate-ansible << 'EOF'
#!/bin/bash
source ~/.ansible-venv/bin/activate
export PATH="$HOME/.ansible-venv/bin:$PATH"
EOF
    chmod +x ~/.activate-ansible
    
    # Add to bashrc
    if ! grep -q "source ~/.activate-ansible" ~/.bashrc; then
        echo "source ~/.activate-ansible" >> ~/.bashrc
    fi
    
    log_success "Ansible installed in virtual environment"
}

# Configure Git
configure_git() {
    log_info "Configuring Git..."
    
    # Check if git is already configured
    if git config --global user.name >/dev/null 2>&1 && git config --global user.email >/dev/null 2>&1; then
        log_info "Git already configured:"
        echo "  Name: $(git config --global user.name)"
        echo "  Email: $(git config --global user.email)"
        return
    fi
    
    # Prompt for Git configuration
    read -p "Enter your Git username: " git_username
    read -p "Enter your Git email: " git_email
    
    git config --global user.name "$git_username"
    git config --global user.email "$git_email"
    git config --global init.defaultBranch main
    git config --global pull.rebase false
    
    log_success "Git configured with username: $git_username"
}

# Generate SSH keys
setup_ssh_keys() {
    log_info "Setting up SSH keys..."
    
    if [[ -f ~/.ssh/id_rsa ]]; then
        log_warning "SSH key already exists. Skipping generation."
        return
    fi
    
    read -p "Enter your email for SSH key: " ssh_email
    ssh-keygen -t rsa -b 4096 -C "$ssh_email" -f ~/.ssh/id_rsa -N ""
    
    # Start ssh-agent and add key
    eval "$(ssh-agent -s)"
    ssh-add ~/.ssh/id_rsa
    
    log_success "SSH key generated. Public key:"
    cat ~/.ssh/id_rsa.pub
    log_info "Add this public key to your Proxmox server and GitHub account"
}

# Install additional tools
install_additional_tools() {
    log_info "Installing additional development tools..."
    
    # Install jq for JSON processing
    sudo apt-get install -y jq
    
    # Install pre-commit for Git hooks
    source ~/.activate-ansible
    pip install pre-commit
    
    log_success "Additional tools installed"
}

# Create workspace directory structure and files
create_workspace() {
    log_info "Creating workspace directory structure..."
    
    WORKSPACE_DIR="$HOME/proxmox-homelab"
    
    if [[ -d "$WORKSPACE_DIR" ]]; then
        log_warning "Workspace directory already exists: $WORKSPACE_DIR"
        read -p "Continue and merge with existing directory? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Exiting to avoid overwriting existing directory"
            exit 1
        fi
    fi
    
    cd "$HOME"
    mkdir -p proxmox-homelab
    cd proxmox-homelab
    
    # Create directory structure
    log_info "Creating directory structure..."
    mkdir -p .devcontainer
    mkdir -p .github/workflows
    mkdir -p .vscode
    mkdir -p .continue
    mkdir -p terraform/environments/test-vm
    mkdir -p terraform/environments/production
    mkdir -p terraform/modules
    mkdir -p ansible/01-base-system
    mkdir -p ansible/02-infrastructure
    mkdir -p ansible/03-applications
    mkdir -p ansible/inventory
    mkdir -p docs
    mkdir -p scripts
    mkdir -p backups
    
    # Initialize git repository first
    git init
    
    log_success "Directory structure created"
    
    # Now create all the configuration files
    create_configuration_files
    
    log_success "Workspace directory structure and files created at: $WORKSPACE_DIR"
}

# Create all configuration files
create_configuration_files() {
    log_info "Creating configuration files..."
    
    # DevContainer configuration
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

    # GitHub Actions workflow
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
EOF

    # Pre-commit configuration
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

  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.81.0
    hooks:
      - id: terraform_fmt
      - id: terraform_validate

  - repo: https://github.com/ansible/ansible-lint
    rev: v6.17.2
    hooks:
      - id: ansible-lint
        files: \.(yaml|yml)$
        exclude: .github/
EOF

    # Gitignore
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
*.tfvars
*.tfvars.json

# Ansible
*.retry
.vault_pass

# Python
__pycache__/
*.pyc
venv/
env/

# IDE
.vscode/settings.json
.vscode/launch.json
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

    # Python requirements
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

    # Ansible requirements
    cat > ansible/requirements.yml << 'EOF'
collections:
  - community.general
  - community.crypto
  - ansible.posix
EOF

    # Ansible configuration
    cat > ansible/ansible.cfg << 'EOF'
[defaults]
inventory = inventory/
host_key_checking = False
timeout = 30
gather_facts = True

[privilege_escalation]
become = True
become_method = sudo
become_user = root

[ssh_connection]
pipelining = True
retries = 3
EOF

    # VSCode settings
    cat > .vscode/settings.json << 'EOF'
{
    "files.associations": {
        "*.yml": "yaml",
        "*.yaml": "yaml",
        "*.tf": "terraform",
        "*.tfvars": "terraform"
    },
    "terraform.experimentalFeatures.validateOnSave": true,
    "ansible.python.interpreterPath": "~/.ansible-venv/bin/python",
    "python.defaultInterpreterPath": "~/.ansible-venv/bin/python",
    "files.exclude": {
        "**/.terraform": true,
        "**/*.tfstate": true,
        "**/.env": true
    }
}
EOF

    # VSCode extensions
    cat > .vscode/extensions.json << 'EOF'
{
    "recommendations": [
        "ms-vscode-remote.remote-wsl",
        "continue.continue",
        "hashicorp.terraform",
        "redhat.ansible",
        "ms-python.python",
        "timonwong.shellcheck"
    ]
}
EOF

    # VSCode tasks
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
            }
        },
        {
            "label": "Ansible Lint",
            "type": "shell",
            "command": "ansible-lint",
            "args": ["ansible/"],
            "group": "test"
        }
    ]
}
EOF

    # Continue.dev configuration
    cat > .continue/config.json << 'EOF'
{
    "models": [
        {
            "title": "Claude 3.5 Sonnet",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
            "apiKey": "${ANTHROPIC_API_KEY}",
            "contextLength": 200000
        }
    ],
    "customCommands": [
        {
            "name": "terraform",
            "prompt": "Help me write Terraform configuration for Proxmox. Focus on best practices and security. Context: {{{ input }}}"
        },
        {
            "name": "ansible",
            "prompt": "Help me create Ansible playbooks for infrastructure automation. Focus on idempotency and error handling. Context: {{{ input }}}"
        },
        {
            "name": "proxmox",
            "prompt": "Help me with Proxmox VE configuration and automation. Context: {{{ input }}}"
        }
    ]
}
EOF

    # Terraform main configuration
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

    # Terraform variables
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
  description = "Number of test containers"
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
  description = "Network bridge"
  type        = string
  default     = "vmbr0"
}
EOF

    # Terraform example vars
    cat > terraform/environments/test-vm/terraform.tfvars.example << 'EOF'
proxmox_api_url = "https://192.168.1.100:8006/api2/json"
proxmox_user    = "root@pam"
proxmox_node    = "pve"
lxc_password    = "your-secure-password"

test_container_count = 3
storage_pool         = "local-zfs"
network_bridge       = "vmbr0"
EOF

    # Ansible inventory
    cat > ansible/inventory/test-lab.yml << 'EOF'
all:
  children:
    proxmox:
      hosts:
        pve-lab:
          ansible_host: 192.168.1.100
          ansible_user: root
    
    test_containers:
      hosts:
        test-1:
          ansible_host: 192.168.1.101
          container_id: 101
        test-2:
          ansible_host: 192.168.1.102
          container_id: 102
      vars:
        ansible_user: root
        ansible_ssh_private_key_file: ~/.ssh/id_rsa
EOF

    # Ansible base playbook
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
  
  tasks:
    - name: Update package cache
      apt:
        update_cache: yes
        cache_valid_time: 3600
    
    - name: Install base packages
      apt:
        name: "{{ packages_to_install }}"
        state: present
EOF

    # VSCode workspace file
    cat > proxmox-homelab.code-workspace << 'EOF'
{
    "folders": [
        {
            "name": "Proxmox Homelab",
            "path": "."
        }
    ],
    "settings": {
        "terminal.integrated.defaultProfile.linux": "bash"
    },
    "extensions": {
        "recommendations": [
            "ms-vscode-remote.remote-wsl",
            "continue.continue",
            "hashicorp.terraform",
            "redhat.ansible"
        ]
    }
}
EOF

    # README
    cat > README.md << 'EOF'
# Proxmox Homelab Infrastructure

Infrastructure as Code for Proxmox-based homelab using Terraform and Ansible.

## Quick Start

1. Copy `.env.template` to `.env` and configure your settings
2. Run `scripts/validate-environment.sh` to check setup
3. Deploy test infrastructure with `terraform apply`

## Structure

- `terraform/` - Infrastructure definitions
- `ansible/` - Configuration management
- `scripts/` - Automation scripts
- `.github/` - CI/CD workflows

See `docs/` for detailed documentation.
EOF

    log_success "All configuration files created"
}

# Create environment template
create_env_template() {
    log_info "Creating environment template..."
    
    cat > "$HOME/proxmox-homelab/.env.template" << 'EOF'
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
TF_VAR_proxmox_host=${PROXMOX_HOST}
TF_VAR_proxmox_user=${PROXMOX_USER}
TF_VAR_proxmox_password=${PROXMOX_PASSWORD}

# Ansible Settings
ANSIBLE_HOST_KEY_CHECKING=False
ANSIBLE_PRIVATE_KEY_FILE=${SSH_PRIVATE_KEY_PATH}

# Backup Settings
BACKUP_NFS_SERVER=your-nfs-server
BACKUP_NFS_PATH=/mnt/backup
EOF
    
    log_success "Environment template created"
}

# Display completion message
show_completion() {
    log_success "Development environment setup completed!"
    echo
    log_info "Next steps:"
    echo "1. Copy and configure .env.template to .env"
    echo "2. Add your SSH public key to Proxmox and GitHub"
    echo "3. Test connection to your Proxmox lab VM"
    echo "4. Install VSCode extensions:"
    echo "   - Remote - WSL"
    echo "   - Continue.dev"
    echo "   - HashiCorp Terraform"
    echo "   - Ansible"
    echo "5. Clone/create your repository in ~/proxmox-homelab"
    echo
    log_info "To activate the Ansible environment in new shells, run:"
    echo "source ~/.activate-ansible"
}

# Main execution
main() {
    log_info "Starting Proxmox Homelab Development Environment Setup"
    
    check_wsl
    update_system
    install_terraform
    install_ansible
    configure_git
    setup_ssh_keys
    install_additional_tools
    create_workspace
    create_env_template
    show_completion
}

# Run main function
main "$@"