#!/bin/bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    local message="$1"
    echo -e "${BLUE}[INFO]${NC} $message"
    return 0
}

log_success() {
    local message="$1"
    echo -e "${GREEN}[SUCCESS]${NC} $message"
    return 0
}

log_warning() {
    local message="$1"
    echo -e "${YELLOW}[WARNING]${NC} $message"
    return 0
}

log_error() {
    local message="$1"
    echo -e "${RED}[ERROR]${NC} $message" >&2
    return 0
}

# Update system packages
update_system() {
    log_info "Updating system packages..."
    sudo apt-get update && sudo apt-get upgrade -y
    sudo apt-get install -y curl wget unzip git python3 python3-pip python3-venv \
        software-properties-common apt-transport-https ca-certificates gnupg lsb-release jq
    log_success "System packages updated"
    return 0
}

# Install Terraform
install_terraform() {
    log_info "Installing Terraform..."

    # Check if Terraform is already installed
    if command -v terraform >/dev/null 2>&1; then
        log_info "Terraform already installed: $(terraform version -json | python3 -c "import sys, json; print(json.load(sys.stdin)['terraform_version'])" 2>/dev/null || terraform version)"
        return 0
    fi

    # Get latest Terraform version
    TERRAFORM_VERSION=$(curl -s https://api.github.com/repos/hashicorp/terraform/releases/latest | grep '"tag_name"' | cut -d'"' -f4 | sed 's/v//')

    # Download and install
    wget -q https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip
    unzip -q terraform_${TERRAFORM_VERSION}_linux_amd64.zip
    sudo mv terraform /usr/local/bin/
    rm terraform_${TERRAFORM_VERSION}_linux_amd64.zip

    # Verify installation
    if terraform version >/dev/null 2>&1; then
        log_success "Terraform $(terraform version -json | python3 -c "import sys, json; print(json.load(sys.stdin)['terraform_version'])" 2>/dev/null || echo "installed") installed"
    else
        log_error "Terraform installation failed"
        exit 1
    fi
    return 0
}

# Install Ansible
install_ansible() {
    log_info "Installing Ansible..."

    # Create Python virtual environment for Ansible
    if [[ ! -d ~/.ansible-venv ]]; then
        python3 -m venv ~/.ansible-venv
    fi

    source ~/.ansible-venv/bin/activate

    # Install Ansible and required packages
    pip install --upgrade pip
    pip install ansible proxmoxer requests python-dotenv paramiko jinja2 pyyaml netaddr

    # Install community collections
    ansible-galaxy collection install community.general --force
    ansible-galaxy collection install community.crypto --force
    ansible-galaxy collection install ansible.posix --force

    # Create activation script
    cat > ~/.activate-ansible << 'EOF'
#!/bin/bash
source ~/.ansible-venv/bin/activate
export PATH="$HOME/.ansible-venv/bin:$PATH"
EOF
    chmod +x ~/.activate-ansible

    # Add to bashrc if not already there
    if ! grep -q "source ~/.activate-ansible" ~/.bashrc; then
        echo "source ~/.activate-ansible" >> ~/.bashrc
        log_info "Added Ansible activation to ~/.bashrc"
    fi

    log_success "Ansible installed in virtual environment"
    log_info "Note: Run 'source ~/.activate-ansible' or restart your shell to activate"
    return 0
}

# Configure Git
configure_git() {
    log_info "Configuring Git..."

    # Check if git is already configured
    if git config --global user.name >/dev/null 2>&1 && git config --global user.email >/dev/null 2>&1; then
        log_success "Git already configured:"
        echo "  Name: $(git config --global user.name)"
        echo "  Email: $(git config --global user.email)"
        return 0
    fi

    # Prompt for Git configuration
    echo "Git configuration needed:"
    read -p "Enter your Git username: " git_username
    read -p "Enter your Git email: " git_email

    git config --global user.name "$git_username"
    git config --global user.email "$git_email"
    git config --global init.defaultBranch main
    git config --global pull.rebase false

    log_success "Git configured with username: $git_username"
    return 0
}

# Generate SSH keys
setup_ssh_keys() {
    log_info "Setting up SSH keys..."

    if [[ -f ~/.ssh/id_rsa ]]; then
        log_success "SSH key already exists"
        echo "Public key:"
        cat ~/.ssh/id_rsa.pub
        return 0
    fi

    echo "SSH key generation:"
    read -p "Enter your email for SSH key: " ssh_email

    # Create .ssh directory if it doesn't exist
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh

    # Generate SSH key
    ssh-keygen -t rsa -b 4096 -C "$ssh_email" -f ~/.ssh/id_rsa -N ""

    # Set proper permissions
    chmod 600 ~/.ssh/id_rsa
    chmod 644 ~/.ssh/id_rsa.pub

    # Start ssh-agent and add key
    eval "$(ssh-agent -s)"
    ssh-add ~/.ssh/id_rsa

    log_success "SSH key generated. Public key:"
    cat ~/.ssh/id_rsa.pub
    echo
    log_info "Add this public key to:"
    echo "  - Your Proxmox server (for SSH access)"
    echo "  - Your GitHub account (for repository access)"
    return 0
}

# Install pre-commit
install_precommit() {
    log_info "Installing pre-commit hooks..."

    # Activate Ansible environment to get pip
    source ~/.ansible-venv/bin/activate

    # Install pre-commit
    pip install pre-commit

    # Install hooks if .pre-commit-config.yaml exists
    if [[ -f .pre-commit-config.yaml ]]; then
        pre-commit install
        log_success "Pre-commit hooks installed"
    else
        log_warning "No .pre-commit-config.yaml found - hooks not installed"
    fi
    return 0
}

# Create environment file if it doesn't exist
setup_environment() {
    log_info "Setting up environment configuration..."

    log_info "Secrets are managed via SOPS — no .env file required."
    log_info "All infrastructure credentials are stored in terraform/secrets.enc.yaml"
    echo "  Ensure the age private key is present at ~/.config/sops/age/keys.txt"
    echo "  Retrieve from Bitwarden: 'proxmox-homelab age private key'"
    echo "  Then: mkdir -p ~/.config/sops/age && install -m 600 /dev/stdin ~/.config/sops/age/keys.txt"
    echo "  Use ./with-secrets <command> to run any command with secrets injected."
    return 0
}

# Test installations
test_installations() {
    log_info "Testing installed tools..."

    # Test Terraform
    if terraform version >/dev/null 2>&1; then
        log_success "Terraform: $(terraform version | head -1)"
    else
        log_error "Terraform not working"
    fi

    # Test Ansible (need to activate environment first)
    source ~/.ansible-venv/bin/activate
    if ansible --version >/dev/null 2>&1; then
        log_success "Ansible: $(ansible --version | head -1)"
    else
        log_error "Ansible not working"
    fi

    # Test Python packages
    if python3 -c "import proxmoxer; print('Proxmoxer OK')" >/dev/null 2>&1; then
        log_success "Python packages: proxmoxer installed"
    else
        log_warning "Proxmoxer not available (may need to activate Ansible environment)"
    fi

    # Test Git
    if git --version >/dev/null 2>&1; then
        log_success "Git: $(git --version)"
    else
        log_error "Git not working"
    fi
    return 0
}

# Display completion message
show_completion() {
    log_success "Development environment setup completed!"
    echo
    log_info "Summary of what was installed:"
    echo "  ✓ System packages updated"
    echo "  ✓ Terraform (latest version)"
    echo "  ✓ Ansible (in Python virtual environment)"
    echo "  ✓ Python packages (proxmoxer, etc.)"
    echo "  ✓ Git configured"
    echo "  ✓ SSH keys generated"
    echo "  ✓ Pre-commit hooks (if config present)"
    echo
    log_info "Next steps:"
    echo "1. Ensure the age private key is present:"
    echo "   mkdir -p ~/.config/sops/age"
    echo "   install -m 600 /dev/stdin ~/.config/sops/age/keys.txt"
    echo "   (Retrieve key from Bitwarden: 'proxmox-homelab age private key')"
    echo
    echo "2. Verify secret access:"
    echo "   ./with-secrets env | grep TF_VAR_"
    echo
    echo "3. Deploy infrastructure with secrets:"
    echo "   cd terraform/lxc/stacks/<stack> && ../../../../with-secrets terragrunt apply"
    echo
    echo "4. Open in VSCode:"
    echo "   code proxmox-homelab.code-workspace"
    echo
    log_info "To activate Ansible environment in future sessions:"
    echo "   source ~/.activate-ansible"
    echo
    log_success "Happy automating! 🚀"
    return 0
}

# Main execution
main() {
    echo "=============================================="
    echo "  PROXMOX HOMELAB DEVELOPMENT SETUP"
    echo "=============================================="
    echo

    log_info "Starting development environment setup..."
    echo

    update_system
    install_terraform
    install_ansible
    configure_git
    setup_ssh_keys
    install_precommit
    setup_environment
    test_installations
    show_completion
    return 0
}

# Handle script arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo
        echo "Sets up complete development environment for Proxmox homelab automation."
        echo
        echo "OPTIONS:"
        echo "  --help, -h     Show this help message"
        echo "  --no-update    Skip system package updates"
        echo
        echo "This script installs:"
        echo "  - Terraform (latest)"
        echo "  - Ansible + Python packages"
        echo "  - Git configuration"
        echo "  - SSH keys"
        echo "  - Development tools"
        exit 0
        ;;
    --no-update)
        # Override update_system to do nothing
        update_system() { log_info "Skipping system updates"; }
        ;;
    *)
        echo "Unknown option: ${1}" >&2
        echo "Run '$0 --help' for usage." >&2
        exit 1
        ;;
esac

# Run main function
main "$@"
