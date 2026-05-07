#!/bin/bash
# File: scripts/check-proxmox-status.sh
# Proxmox Server Status Check Script
# Quick validation of Proxmox server configuration
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
    echo -e "${GREEN}[✓]${NC} $message"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    return 0
}

log_warning() {
    local message="$1"
    echo -e "${YELLOW}[⚠]${NC} $message"
    return 0
}

log_error() {
    local message="$1"
    echo -e "${RED}[✗]${NC} $message"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
    return 0
}

# Counters
CHECKS_TOTAL=0
CHECKS_PASSED=0
CHECKS_FAILED=0

# Load environment if available
if [[ -f .env ]]; then
    # shellcheck source=/dev/null
    source .env
else
    log_warning "No .env file found - using defaults"
fi

# Configuration
PROXMOX_HOST="${PROXMOX_HOST:?PROXMOX_HOST must be set in .env}"
PROXMOX_USER="${PROXMOX_USER:-root@pam}"
PROXMOX_PASSWORD="${PROXMOX_PASSWORD:-}"
SSH_USER="${SSH_USER:-root}"
AUTOMATION_USER="automation"
SSH_OPTS=(-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no)
SEPARATOR="=============================================="

# Test function wrapper
run_check() {
    local check_name="$1"
    local check_command="$2"
    local optional="${3:-false}"

    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    log_info "Checking: $check_name"

    if eval "$check_command" >/dev/null 2>&1; then
        log_success "$check_name"
        return 0
    else
        if [[ "$optional" == "true" ]]; then
            log_warning "$check_name (optional - may need setup)"
            CHECKS_TOTAL=$((CHECKS_TOTAL - 1)) # Don't count optional failures
        else
            log_error "$check_name"
        fi
        return 1
    fi
}

# Network connectivity tests
test_network_connectivity() {
    log_info "=== Network Connectivity ==="

    run_check "Proxmox host reachable" "ping -c 1 -W 5 $PROXMOX_HOST"
    run_check "SSH port accessible" "timeout 5 bash -c '</dev/tcp/$PROXMOX_HOST/22'"
    run_check "HTTPS port accessible" "timeout 5 bash -c '</dev/tcp/$PROXMOX_HOST/8006'"
    return 0
}

# SSH connectivity tests
test_ssh_connectivity() {
    log_info "=== SSH Connectivity ==="

    # Test root SSH access
    run_check "SSH access as root" "timeout 10 ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'echo ssh_test_root' 2>/dev/null"

    # Test automation user SSH access
    run_check "SSH access as automation user" "timeout 10 ssh ${SSH_OPTS[*]} $AUTOMATION_USER@$PROXMOX_HOST 'echo ssh_test_automation' 2>/dev/null" "true"
    return 0
}

# Proxmox API tests
test_api_connectivity() {
    log_info "=== Proxmox API Connectivity ==="

    if [[ -z "$PROXMOX_PASSWORD" ]]; then
        log_warning "No PROXMOX_PASSWORD set - skipping API tests"
        return 0
    fi

    # Test API authentication
    local api_cmd="curl -k -m 10 -s -d 'username=$PROXMOX_USER&password=$PROXMOX_PASSWORD' https://$PROXMOX_HOST:8006/api2/json/access/ticket"
    run_check "API authentication" "$api_cmd | jq -r '.data.ticket' | grep -v null"

    # Test API version endpoint (if auth works)
    if eval "$api_cmd | jq -r '.data.ticket' | grep -v null" >/dev/null 2>&1; then
        local ticket
        ticket=$(eval "$api_cmd | jq -r '.data.ticket'")
        local csrf
        csrf=$(eval "$api_cmd | jq -r '.data.CSRFPreventionToken'")

        run_check "API version info" "curl -k -s -H 'Cookie: PVEAuthCookie=$ticket' -H 'CSRFPreventionToken: $csrf' https://$PROXMOX_HOST:8006/api2/json/version | jq -r '.data.version' | grep -v null"
    fi
    return 0
}

# Check specific Proxmox configurations via SSH
test_proxmox_configuration() {
    log_info "=== Proxmox Configuration ==="

    # Test repository configuration
    run_check "Enterprise repo disabled" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'grep -q \"^#\" /etc/apt/sources.list.d/pve-enterprise.sources 2>/dev/null || echo missing'" "true"

    run_check "No-subscription repo enabled" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'grep -q \"^Types:\" /etc/apt/sources.list.d/pve-no-subscription.sources 2>/dev/null'" "true"

    # Test subscription nag removal
    run_check "Subscription nag removed" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'grep -q \"false\" /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js 2>/dev/null'" "true"

    # Test automation user exists
    run_check "Automation system user exists" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'getent passwd $AUTOMATION_USER >/dev/null'" "true"

    # Test PVE automation user exists
    run_check "Automation PVE user exists" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'pveum user list | grep -q \"automation@pve\"'" "true"

    # Test sudo access for automation user
    run_check "Automation user sudo access" "ssh ${SSH_OPTS[*]} $AUTOMATION_USER@$PROXMOX_HOST 'sudo -n whoami | grep root' 2>/dev/null" "true"
    return 0
}

# Check storage and network resources
test_resources() {
    log_info "=== Proxmox Resources ==="

    # Get storage information
    run_check "Storage pools available" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'pvesm status | wc -l | grep -v \"^1$\"'" "true"

    # Get network bridges
    run_check "Network bridges available" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'ip link show type bridge | grep -q vmbr'" "true"

    # Check for running VMs/containers (should be none in fresh test environment)
    run_check "No running containers blocking reset" "ssh ${SSH_OPTS[*]} root@$PROXMOX_HOST 'pct list | wc -l | grep -q \"^1$\"'" "true"
    return 0
}

# Get detailed system information
get_system_info() {
    log_info "=== System Information ==="

    if ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'echo test' >/dev/null 2>&1; then
        echo "Proxmox Server Details:"
        ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'cat /etc/os-release | grep PRETTY_NAME' 2>/dev/null | sed 's/PRETTY_NAME=//;s/"//g' | sed 's/^/  Version: /' || echo "  Version: Unknown"
        ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'hostname -f' 2>/dev/null | sed 's/^/  Hostname: /' || echo "  Hostname: Unknown"
        ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'date' 2>/dev/null | sed 's/^/  Date: /' || echo "  Date: Unknown"

        echo
        echo "Storage Pools:"
        ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'pvesm status 2>/dev/null' | awk 'NR>1 {print "  " $1 " (" $2 ")"}' || echo "  Unable to retrieve storage info"

        echo
        echo "Network Bridges:"
        ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'ip link show type bridge 2>/dev/null' | grep -o 'vmbr[0-9]*' | sed 's/^/  /' || echo "  Unable to retrieve bridge info"

        echo
        echo "Users:"
        if ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'getent passwd automation >/dev/null 2>&1'; then
            echo "  System user 'automation': ✓ Exists"
        else
            echo "  System user 'automation': ✗ Missing"
        fi

        if ssh "${SSH_OPTS[@]}" root@"$PROXMOX_HOST" 'pveum user list 2>/dev/null | grep -q automation@pve'; then
            echo "  PVE user 'automation@pve': ✓ Exists"
        else
            echo "  PVE user 'automation@pve': ✗ Missing"
        fi
    else
        log_error "Cannot retrieve system information - SSH access failed"
    fi
    return 0
}

# Generate remediation suggestions
generate_remediation() {
    echo
    log_info "=== Remediation Suggestions ==="

    if [[ $CHECKS_FAILED -gt 0 ]]; then
        echo "To fix the failed checks, run:"
        echo
        echo "1. Run the Proxmox setup playbook:"
        echo "   cd ansible"
        echo "   ansible-playbook -i inventory/test-lab.yml 01-base-system/proxmox-server-setup.yml"
        echo
        echo "2. If SSH keys are missing, copy your public key:"
        echo "   ssh-copy-id root@$PROXMOX_HOST"
        echo "   ssh-copy-id $AUTOMATION_USER@$PROXMOX_HOST"
        echo
        echo "3. Update your .env file with correct credentials"
        echo
        echo "4. Re-run this validation script to confirm fixes"
    else
        echo "All critical checks passed! Your Proxmox server appears ready for automation."
        echo
        echo "Next steps:"
        echo "1. Deploy test infrastructure: cd terraform/environments/test-vm && terraform apply"
        echo "2. Configure deployed containers with Ansible"
        echo "3. Set up monitoring and backups"
    fi
    return 0
}

# Generate summary report
generate_report() {
    echo
    echo "$SEPARATOR"
    echo "       PROXMOX SERVER STATUS REPORT"
    echo "$SEPARATOR"
    echo
    echo "Target Server: $PROXMOX_HOST"
    echo "Total Checks: $CHECKS_TOTAL"
    echo -e "Passed:       ${GREEN}$CHECKS_PASSED${NC}"
    echo -e "Failed:       ${RED}$CHECKS_FAILED${NC}"
    echo

    local pass_rate=$((CHECKS_PASSED * 100 / CHECKS_TOTAL))

    if [[ $pass_rate -eq 100 ]]; then
        echo -e "${GREEN}🎉 Proxmox server is fully configured and ready!${NC}"
    elif [[ $pass_rate -ge 80 ]]; then
        echo -e "${YELLOW}⚠️ Proxmox server mostly configured with minor issues${NC}"
    elif [[ $pass_rate -ge 60 ]]; then
        echo -e "${YELLOW}⚠️ Proxmox server partially configured - setup needed${NC}"
    else
        echo -e "${RED}❌ Proxmox server needs significant configuration${NC}"
        return 1
    fi

    echo "$SEPARATOR"
    return 0
}

# Main execution
main() {
    echo "$SEPARATOR"
    echo "      PROXMOX SERVER STATUS VALIDATION"
    echo "$SEPARATOR"
    echo
    echo "Checking Proxmox server: $PROXMOX_HOST"
    echo

    test_network_connectivity
    echo
    test_ssh_connectivity
    echo
    test_api_connectivity
    echo
    test_proxmox_configuration
    echo
    test_resources
    echo
    get_system_info
    echo
    generate_remediation
    generate_report
    return 0
}

# Handle script arguments
case "${1:-}" in
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo
        echo "Validates Proxmox server configuration and readiness for automation."
        echo
        echo "OPTIONS:"
        echo "  --help, -h     Show this help message"
        echo "  --quick, -q    Skip detailed system information"
        echo "  --no-api       Skip API connectivity tests"
        echo
        echo "Environment variables (or .env file):"
        echo "  PROXMOX_HOST     - Proxmox server IP/hostname (required from .env)"
        echo "  PROXMOX_USER     - Proxmox API username (default: root@pam)"
        echo "  PROXMOX_PASSWORD - Proxmox API password"
        echo "  SSH_USER         - SSH username (default: root)"
        echo
        exit 0
        ;;
    --quick|-q)
        # Override get_system_info to do nothing
        get_system_info() {
            return 0
        }
        ;;
    --no-api)
        # Override test_api_connectivity to do nothing
        test_api_connectivity() {
            return 0
        }
        ;;
    *)
        echo "Unknown option: ${1}" >&2
        echo "Run '$0 --help' for usage." >&2
        exit 1
        ;;
esac

# Run main function
main "$@"
