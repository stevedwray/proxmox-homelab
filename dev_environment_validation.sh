#!/bin/bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; TESTS_PASSED=$((TESTS_PASSED + 1)); }
log_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; TESTS_FAILED=$((TESTS_FAILED + 1)); }

# Test wrapper function
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    log_info "Testing: $test_name"
    
    if eval "$test_command" >/dev/null 2>&1; then
        log_success "$test_name"
        return 0
    else
        log_error "$test_name"
        return 1
    fi
}

# Test WSL environment (1 or 2)
test_wsl() {
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
    log_info "Testing: WSL environment detection"
    
    if grep -qE "(microsoft|WSL)" /proc/version 2>/dev/null; then
        if grep -q "WSL2" /proc/version 2>/dev/null; then
            log_warning "WSL2 detected - may conflict with VMware Workstation"
            log_info "Consider: wsl --set-version <distro> 1"
        else
            log_success "WSL1 environment (VMware compatible)"
        fi
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        log_error "WSL environment not detected"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Test required tools
test_tools() {
    run_test "Terraform installation" 'terraform version'
    run_test "Ansible installation" 'source ~/.activate-ansible && ansible --version'
    run_test "Python environment" 'source ~/.activate-ansible && python -c "import proxmoxer"'
    run_test "Git configuration" 'git config --global user.name && git config --global user.email'
    run_test "SSH key presence" 'test -f ~/.ssh/id_rsa'
    run_test "Pre-commit installation" 'source ~/.activate-ansible && pre-commit --version'
    run_test "jq installation" 'jq --version'
}

# Test repository structure
test_repository_structure() {
    local required_dirs=(
        ".devcontainer"
        ".github/workflows"
        "terraform/environments/test-vm"
        "terraform/modules"
        "ansible/01-base-system"
        "ansible/02-infrastructure"
        "ansible/03-applications"
        "docs"
        "scripts"
    )
    
    local required_files=(
        ".env.template"
        ".gitignore"
        ".pre-commit-config.yaml"
        "requirements.txt"
        "ansible/requirements.yml"
        "ansible/ansible.cfg"
    )
    
    for dir in "${required_dirs[@]}"; do
        run_test "Directory exists: $dir" "test -d '$dir'"
    done
    
    for file in "${required_files[@]}"; do
        run_test "File exists: $file" "test -f '$file'"
    done
}

# Test environment configuration
test_environment() {
    run_test ".env.template exists" 'test -f .env.template'
    
    if [[ -f .env ]]; then
        log_success ".env file configured"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        log_warning ".env file not found - copy from .env.template and configure"
    fi
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
}

# Test Proxmox connectivity
test_proxmox_connection() {
    if [[ ! -f .env ]]; then
        log_warning "Skipping Proxmox tests - no .env file"
        return
    fi
    
    source .env
    
    if [[ -z "${PROXMOX_HOST:-}" ]]; then
        log_warning "Skipping Proxmox tests - PROXMOX_HOST not set"
        return
    fi
    
    run_test "Proxmox SSH connectivity" "timeout 10 ssh -o ConnectTimeout=5 -o BatchMode=yes ${SSH_USER:-root}@${PROXMOX_HOST} 'echo connection_test' 2>/dev/null"
    
    if [[ -n "${PROXMOX_PASSWORD:-}" ]]; then
        local api_test="curl -k -m 10 -s -d 'username=${PROXMOX_USER}&password=${PROXMOX_PASSWORD}' https://${PROXMOX_HOST}:8006/api2/json/access/ticket | jq -r '.data.ticket' | grep -v null"
        run_test "Proxmox API connectivity" "$api_test"
    else
        log_warning "Skipping API test - PROXMOX_PASSWORD not set"
    fi
}

# Test Terraform configuration
test_terraform() {
    local terraform_dir="terraform/environments/test-vm"
    
    if [[ ! -d "$terraform_dir" ]]; then
        log_error "Terraform test directory not found"
        return
    fi
    
    cd "$terraform_dir"
    run_test "Terraform initialization" "terraform init -backend=false"
    run_test "Terraform validation" "terraform validate"
    cd - >/dev/null
}

# Test Ansible configuration
test_ansible() {
    if [[ ! -f ansible/ansible.cfg ]]; then
        log_error "Ansible configuration not found"
        return
    fi
    
    source ~/.activate-ansible
    cd ansible
    
    run_test "Ansible configuration syntax" "ansible-config validate"
    run_test "Ansible inventory syntax" "ansible-inventory --list -i inventory/test-lab.yml"
    run_test "Ansible playbook syntax" "ansible-playbook --syntax-check 01-base-system/base-config.yml"
    
    cd - >/dev/null
}

# Test security tools
test_security_tools() {
    source ~/.activate-ansible
    
    run_test "Pre-commit hooks validation" "pre-commit validate-config"
    
    # Test individual security tools
    if command -v tfsec >/dev/null 2>&1; then
        run_test "tfsec execution" "tfsec --version"
    else
        log_warning "tfsec not installed - will be handled by pre-commit"
    fi
    
    run_test "ansible-lint execution" "ansible-lint --version"
}

# Test VSCode configuration
test_vscode_config() {
    run_test "VSCode settings file" "test -f .vscode/settings.json"
    run_test "VSCode extensions file" "test -f .vscode/extensions.json"
    run_test "VSCode tasks file" "test -f .vscode/tasks.json"
    run_test "VSCode workspace file" "test -f proxmox-homelab.code-workspace"
}

# Test Continue.dev configuration
test_continue_config() {
    run_test "Continue.dev config exists" "test -f .continue/config.json"
    run_test "Continue.dev prompts exist" "test -f .continue/prompts.md"
    
    if [[ -f .env ]] && grep -q "ANTHROPIC_API_KEY" .env; then
        log_success "Anthropic API key configured in .env"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        log_warning "Anthropic API key not found in .env - Continue.dev will not work"
    fi
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
}

# Test backup scripts
test_backup_scripts() {
    run_test "Backup script exists" "test -f scripts/backup-procedures.sh"
    run_test "Backup script is executable" "test -x scripts/backup-procedures.sh"
    
    # Test script syntax
    run_test "Backup script syntax" "bash -n scripts/backup-procedures.sh"
}

# Generate summary report
generate_report() {
    echo
    echo "=============================================="
    echo "       ENVIRONMENT VALIDATION REPORT"
    echo "=============================================="
    echo
    echo "Total Tests: $TESTS_TOTAL"
    echo -e "Passed:      ${GREEN}$TESTS_PASSED${NC}"
    echo -e "Failed:      ${RED}$TESTS_FAILED${NC}"
    echo
    
    local pass_rate=$((TESTS_PASSED * 100 / TESTS_TOTAL))
    
    if [[ $pass_rate -eq 100 ]]; then
        echo -e "${GREEN}🎉 All tests passed! Your environment is ready.${NC}"
        echo
        echo "Next steps:"
        echo "1. Configure your .env file with Proxmox credentials"
        echo "2. Test Proxmox connectivity"
        echo "3. Deploy your first test infrastructure"
        echo "4. Set up monitoring and backups"
    elif [[ $pass_rate -ge 80 ]]; then
        echo -e "${YELLOW}⚠️  Environment mostly ready with minor issues.${NC}"
        echo "Address the failed tests above before proceeding."
    else
        echo -e "${RED}❌ Environment setup incomplete.${NC}"
        echo "Please address the failed tests before proceeding."
        return 1
    fi
    
    echo
    echo "=============================================="
}

# Performance benchmark
run_performance_test() {
    log_info "Running performance benchmarks..."
    
    # Test Terraform performance
    local terraform_start=$(date +%s%N)
    (cd terraform/environments/test-vm && terraform validate >/dev/null 2>&1)
    local terraform_end=$(date +%s%N)
    local terraform_duration=$(((terraform_end - terraform_start) / 1000000))
    
    # Test Ansible performance
    source ~/.activate-ansible
    local ansible_start=$(date +%s%N)
    (cd ansible && ansible-playbook --syntax-check 01-base-system/base-config.yml >/dev/null 2>&1)
    local ansible_end=$(date +%s%N)
    local ansible_duration=$(((ansible_end - ansible_start) / 1000000))
    
    echo
    log_info "Performance Results:"
    echo "  Terraform validation: ${terraform_duration}ms"
    echo "  Ansible syntax check: ${ansible_duration}ms"
    
    if [[ $terraform_duration -lt 5000 && $ansible_duration -lt 3000 ]]; then
        log_success "Performance is optimal"
    elif [[ $terraform_duration -lt 10000 && $ansible_duration -lt 6000 ]]; then
        log_warning "Performance is acceptable"
    else
        log_warning "Consider optimizing WSL2 resources"
    fi
}

# Main execution
main() {
    echo "=============================================="
    echo "  PROXMOX HOMELAB ENVIRONMENT VALIDATION"
    echo "=============================================="
    echo
    
    log_info "Starting validation of development environment..."
    echo
    
    test_wsl
    test_tools
    test_repository_structure
    test_environment
    test_terraform
    test_ansible
    test_security_tools
    test_vscode_config
    test_continue_config
    test_backup_scripts
    
    # Only test Proxmox if configured
    if [[ -f .env ]]; then
        test_proxmox_connection
    fi
    
    run_performance_test
    generate_report
}

# Handle script arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo
        echo "OPTIONS:"
        echo "  --help, -h     Show this help message"
        echo "  --quick, -q    Skip performance tests"
        echo "  --no-proxmox   Skip Proxmox connectivity tests"
        echo
        exit 0
        ;;
    --quick|-q)
        # Override run_performance_test to do nothing
        run_performance_test() { :; }
        ;;
    --no-proxmox)
        # Override test_proxmox_connection to do nothing
        test_proxmox_connection() { :; }
        ;;
esac

# Run main function
main "$@"