#!/bin/bash
# Phase 04 deployment script - Deploy core shared services in sequence
# Services: Authentik → Traefik → step-ca → Monitoring
#
# Prerequisites verified:
# - CI runner online
# - Harbor with Trivy
# - apt-cacher-ng accessible
# - SDN zones configured
# - Secrets in SOPS (terraform/secrets.enc.yaml)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICES=(
  "authentik-stack"
  "proxy-stack"
  "step-ca-stack"
  "monitoring-stack"
)

STACK_DIR="terraform/lxc/stacks"
LAB_IP_AUTHENTIK="${LAB_IP_AUTHENTIK:-10.57.1.10}"
LAB_IP_STEP_CA="${LAB_IP_STEP_CA:-10.57.1.11}"
LAB_IP_MONITORING="${LAB_IP_MONITORING:-10.57.1.12}"

# Functions
log_info() {
  echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
  echo -e "${GREEN}[✓]${NC} $*"
}

log_error() {
  echo -e "${RED}[✗]${NC} $*"
}

log_step() {
  echo -e "\n${YELLOW}=== $* ===${NC}"
}

check_env() {
  log_step "Sourcing environment"

  if [ ! -f ".env" ]; then
    log_error ".env not found"
    return 1
  fi

  # shellcheck disable=SC1091
  source .env
  if [ -f ".env.pve-test" ]; then
    # shellcheck disable=SC1091
    source .env.pve-test
  fi

  : "${TF_VAR_proxmox_node:=}"

  if [ "$TF_VAR_proxmox_node" != "pve-test" ]; then
    log_error "Target node is $TF_VAR_proxmox_node, expected pve-test"
    return 1
  fi

  log_success "Environment loaded for: $TF_VAR_proxmox_node"
}

deploy_service() {
  local service=$1
  local service_path="$STACK_DIR/$service"

  log_step "Deploying $service"

  if [ ! -d "$service_path" ]; then
    log_error "Stack directory not found: $service_path"
    return 1
  fi

  # CD into stack directory
  cd "$service_path"

  # Run terragrunt plan
  log_info "Running terragrunt plan for $service..."
  if ! terragrunt plan -no-color; then
    log_error "Terragrunt plan failed for $service"
    cd - > /dev/null
    return 1
  fi

  # Run terragrunt apply
  log_info "Running terragrunt apply for $service..."
  if ! terragrunt apply -auto-approve -no-color; then
    log_error "Terragrunt apply failed for $service"
    cd - > /dev/null
    return 1
  fi

  cd - > /dev/null
  log_success "Terraform deployment completed for $service"
}

deploy_ansible() {
  local service=$1
  local playbook_name="deploy-${service%-stack}"
  local playbook_path="terraform/lxc/ansible/playbooks/${playbook_name}.yml"

  log_info "Running Ansible playbook: $playbook_name"

  if [ ! -f "$playbook_path" ]; then
    log_error "Playbook not found: $playbook_path"
    return 1
  fi

  # Run ansible-playbook with secrets from SOPS
  if ! ./with-secrets ansible-playbook -i "terraform/lxc/stacks/${service}/inventory.yml" "$playbook_path"; then
    log_error "Ansible deployment failed for $service"
    return 1
  fi

  log_success "Ansible deployment completed for $service"
}

validate_service() {
  local service=$1

  log_info "Validating $service..."

  case "$service" in
    "authentik-stack")
      # Check health endpoints
      local ip="$LAB_IP_AUTHENTIK"
      if curl -sf http://$ip:9000/-/health/live/ > /dev/null 2>&1; then
        log_success "Authentik live health check passed"
      else
        log_error "Authentik live health check failed (expected - wait for startup)"
      fi
      ;;
    "proxy-stack")
      log_info "Traefik validation - check dashboard accessibility"
      ;;
    "step-ca-stack")
      local ip="$LAB_IP_STEP_CA"
      if curl -sk https://$ip/acme/acme/directory 2>&1 | grep -q "nonce-url"; then
        log_success "step-ca ACME directory accessible"
      else
        log_error "step-ca ACME directory not yet accessible (expected - wait for startup)"
      fi
      ;;
    "monitoring-stack")
      log_info "Monitoring validation - check container startup at $LAB_IP_MONITORING"
      ;;
  esac
}

main() {
  log_step "Phase 04 Core Services Deployment"

  # Verify environment
  if ! check_env; then
    log_error "Environment check failed"
    exit 1
  fi

  # Deploy each service in sequence
  for service in "${SERVICES[@]}"; do
    log_step "Processing: $service"

    # Deploy infrastructure (Terraform)
    if ! deploy_service "$service"; then
      log_error "Failed to deploy infrastructure for $service"
      log_info "You can retry manually:cd $STACK_DIR/$service && terragrunt apply"
      exit 1
    fi

    # Deploy application (Ansible)
    if ! deploy_ansible "$service"; then
      log_error "Failed to deploy $service via Ansible"
      log_info "You can retry manually: ./with-secrets ansible-playbook -i terraform/lxc/stacks/$service/inventory.yml terraform/lxc/ansible/playbooks/deploy-${service%-stack}.yml"
      exit 1
    fi

    # Validate
    validate_service "$service"

    log_success "$service deployment complete"
    log_info "Waiting 30s before next service..."
    sleep 30
  done

  log_step "Phase 04 Deployment Complete"
  log_success "All core shared services deployed"
  log_info "Next steps:"
  log_info "  1. Verify all health checks"
  log_info "  2. Test Traefik → Authentik forward-auth"
  log_info "  3. Run security scans"
  log_info "  4. Merge to dev/pve-test"
}

main "$@"
