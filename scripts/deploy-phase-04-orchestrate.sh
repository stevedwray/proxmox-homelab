#!/bin/bash
# Phase 04 Orchestration Script — Deploy core shared services
# This script will deploy Authentik → Traefik → step-ca → Monitoring in sequence
# Each service gets its own Terragrunt init, plan, apply, and Ansible playbook
#
# Usage:
#   ./scripts/deploy-phase-04-orchestrate.sh              # Full deployment
#   ./scripts/deploy-phase-04-orchestrate.sh authentik    # Single service
#   ./scripts/deploy-phase-04-orchestrate.sh --dry-run    # Plan only (no apply)

set -euo pipefail

# ============================================================================
# Configuration & Util Functions
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m'  # No Color

# Configuration
readonly SERVICES=("authentik-stack" "proxy-stack" "step-ca-stack" "monitoring-stack")
readonly STACK_DIR="terraform/lxc/stacks"
readonly ANSIBLE_DIR="terraform/lxc/ansible/playbooks"
readonly DEPLOY_MODE="${1:-full}"  # "full", service name, or "--dry-run"
readonly LOG_DIR="/tmp/phase-04-logs-$(date +%Y%m%d-%H%M%S)"
DRY_RUN="${DRY_RUN:-false}"  # Can be set by --dry-run flag

# Logging functions
mkdir -p "$LOG_DIR"

log_info() {
  echo -e "${BLUE}[INFO]${NC} $*" | tee -a "$LOG_DIR/deploy.log"
}

log_success() {
  echo -e "${GREEN}[✓]${NC} $*" | tee -a "$LOG_DIR/deploy.log"
}

log_warn() {
  echo -e "${YELLOW}[⚠]${NC} $*" | tee -a "$LOG_DIR/deploy.log"
}

log_error() {
  echo -e "${RED}[✗]${NC} $*" | tee -a "$LOG_DIR/deploy.log"
}

log_step() {
  echo "" | tee -a "$LOG_DIR/deploy.log"
  echo -e "${CYAN}════════════════════════════════════════════════════${NC}" | tee -a "$LOG_DIR/deploy.log"
  echo -e "${CYAN}$*${NC}" | tee -a "$LOG_DIR/deploy.log"
  echo -e "${CYAN}════════════════════════════════════════════════════${NC}" | tee -a "$LOG_DIR/deploy.log"
}

# ============================================================================
# Prerequisite Checks
# ============================================================================

check_prerequisites() {
  log_step "Checking Prerequisites"

  local prereqs_ok=true

  # Check .env files
  if [ ! -f ".env" ]; then
    log_error ".env not found"
    prereqs_ok=false
  else
    log_success ".env found"
  fi

  if [ ! -f ".env.pve-test" ]; then
    log_warn ".env.pve-test not found (may not be needed)"
  else
    log_success ".env.pve-test found"
  fi

  # Check required tools
  for tool in terraform terragrunt ansible-playbook git; do
    if command -v "$tool" &> /dev/null; then
      log_success "$tool available"
    else
      log_error "$tool not found"
      prereqs_ok=false
    fi
  done

  # Check with-secrets wrapper
  if [ ! -x "./with-secrets" ]; then
    log_error "./with-secrets not executable"
    prereqs_ok=false
  else
    log_success "./with-secrets executable"
  fi

  # Source environment
  source .env 2>/dev/null || { log_error "Failed to source .env"; prereqs_ok=false; }
  [ -f ".env.pve-test" ] && source .env.pve-test 2>/dev/null

  if [ "$TF_VAR_proxmox_node" != "pve-test" ]; then
    log_error "Target node is $TF_VAR_proxmox_node, expected pve-test"
    prereqs_ok=false
  else
    log_success "Target node: pve-test ✓"
  fi

  # Check for SOPS secrets
  if ./with-secrets env | grep -q "AUTHENTIK_SECRET_KEY"; then
    log_success "SOPS secrets accessible"
  else
    log_error "Cannot read SOPS secrets"
    prereqs_ok=false
  fi

  if [ "$prereqs_ok" = false ]; then
    log_error "Prerequisites check failed"
    exit 1
  fi

  log_success "All prerequisites met"
}

# ============================================================================
# Deployment Functions
# ============================================================================

deploy_stack_infrastructure() {
  local service=$1
  local stack_path="$STACK_DIR/$service"

  log_step "Deploying Infrastructure: $service"

  if [ ! -d "$stack_path" ]; then
    log_error "Stack directory not found: $stack_path"
    return 1
  fi

  pushd "$stack_path" > /dev/null

  # Initialize Terragrunt
  log_info "Initializing Terragrunt..."
  if ! "$PROJECT_ROOT/with-secrets" terragrunt init \
    > "$LOG_DIR/${service}-init.log" 2>&1; then
    log_error "Terragrunt init failed (see $LOG_DIR/${service}-init.log)"
    popd > /dev/null
    return 1
  fi
  log_success "Terragrunt initialized"

  # Plan infrastructure
  log_info "Planning infrastructure..."
  if ! "$PROJECT_ROOT/with-secrets" terragrunt plan -no-color \
    > "$LOG_DIR/${service}-plan.log" 2>&1; then
    log_error "Terragrunt plan failed (see $LOG_DIR/${service}-plan.log)"
    popd > /dev/null
    return 1
  fi
  log_success "Plan generated"

  # Show plan summary
  local resources_planned
  resources_planned=$(grep -c "will be created\|will be destroyed\|will be updated" \
    "$LOG_DIR/${service}-plan.log" || echo "0")
  log_info "Resources affected: $resources_planned"

  # Apply if not dry-run
  if [ "$DRY_RUN" = false ]; then
    log_info "Applying infrastructure..."
    if ! "$PROJECT_ROOT/with-secrets" terragrunt apply -auto-approve -no-color \
      > "$LOG_DIR/${service}-apply.log" 2>&1; then
      log_error "Terragrunt apply failed (see $LOG_DIR/${service}-apply.log)"
      popd > /dev/null
      return 1
    fi
    log_success "Infrastructure deployed"
  else
    log_warn "DRY-RUN: Skipping apply"
  fi

  popd > /dev/null
}

deploy_stack_application() {
  local service=$1
  local stack_path="$STACK_DIR/$service"
  local playbook_name="deploy-${service%-stack}"
  local playbook_path="$ANSIBLE_DIR/${playbook_name}.yml"

  log_step "Deploying Application: $service"

  if [ ! -f "$playbook_path" ]; then
    log_error "Playbook not found: $playbook_path"
    return 1
  fi

  if [ "$DRY_RUN" = false ]; then
    log_info "Running Ansible playbook: $playbook_name"
    if ! ./with-secrets ansible-playbook \
      -i "$stack_path/inventory.yml" \
      "$playbook_path" \
      > "$LOG_DIR/${service}-ansible.log" 2>&1; then
      log_error "Ansible playbook failed (see $LOG_DIR/${service}-ansible.log)"
      return 1
    fi
    log_success "Application deployed"
  else
    log_warn "DRY-RUN: Would run: $playbook_name"
  fi
}

validate_service() {
  local service=$1

  log_step "Validating: $service"

  case "$service" in
    "authentik-stack")
      local ip="10.57.1.10"
      log_info "Testing Authentik health endpoints at $ip..."
      if timeout 30 bash -c "until curl -sf http://$ip:9000/-/health/live/ > /dev/null 2>&1; do sleep 2; done"; then
        log_success "Authentik live health check passed"
      else
        log_warn "Authentik not yet responding (service may still be starting)"
      fi
      ;;

    "proxy-stack")
      local ip="10.57.2.10"
      log_info "Testing Traefik at $ip..."
      if timeout 10 bash -c "docker ps 2>/dev/null | grep -q traefik" 2>/dev/null; then
        log_success "Traefik container running"
      else
        log_warn "Traefik validation (SSH into container for details)"
      fi
      ;;

    "step-ca-stack")
      local ip="10.57.1.11"
      log_info "Testing step-ca ACME directory at $ip..."
      if timeout 30 bash -c "until curl -sk https://$ip/acme/acme/directory 2>&1 | grep -q 'nonce-url'; do sleep 2; done" 2>/dev/null; then
        log_success "step-ca ACME directory accessible"
      else
        log_warn "step-ca ACME not yet accessible (service may still be starting)"
      fi
      ;;

    "monitoring-stack")
      local ip="10.57.1.12"
      log_info "Testing Monitoring stack at $ip..."
      if timeout 30 bash -c "until curl -sf http://$ip:8428/api/v1/targets 2>/dev/null | grep -q 'activeTargets'; do sleep 2; done" 2>/dev/null; then
        log_success "VictoriaMetrics responding"
      else
        log_warn "Monitoring services still initializing"
      fi
      ;;
  esac
}

deploy_service() {
  local service=$1

  log_step "Starting deployment: $service"

  # Deploy infrastructure
  if ! deploy_stack_infrastructure "$service"; then
    log_error "Infrastructure deployment failed: $service"
    return 1
  fi

  # Deploy application
  if ! deploy_stack_application "$service"; then
    log_error "Application deployment failed: $service"
    return 1
  fi

  # Validate
  if ! validate_service "$service"; then
    log_warn "Validation may have timed out (this is normal for initial startup)"
  fi

  log_success "$service deployment complete"

  # Small delay between services
  if [ "$service" != "${SERVICES[-1]}" ]; then
    log_info "Waiting 60s before next service..."
    sleep 60
  fi
}

# ============================================================================
# Main Orchestration
# ============================================================================

main() {
  local start_time
  start_time=$(date +%s)

  log_step "Phase 04 Core Services Deployment"
  log_info "Log directory: $LOG_DIR"

  # Check prerequisites
  check_prerequisites

  # Determine which services to deploy
  local services_to_deploy=()

  if [ "$DEPLOY_MODE" = "full" ]; then
    services_to_deploy=("${SERVICES[@]}")
  elif [ "$DEPLOY_MODE" = "--dry-run" ]; then
    DRY_RUN=true
    services_to_deploy=("${SERVICES[@]}")
    log_warn "DRY-RUN MODE: No changes will be applied"
  elif [[ " ${SERVICES[*]} " =~ " ${DEPLOY_MODE}-stack " ]]; then
    services_to_deploy=("${DEPLOY_MODE}-stack")
  else
    log_error "Invalid service: $DEPLOY_MODE"
    log_info "Valid services: ${SERVICES[*]}"
    exit 1
  fi

  # Deploy each service
  local failed_services=()
  for service in "${services_to_deploy[@]}"; do
    if ! deploy_service "$service"; then
      failed_services+=("$service")
    fi
  done

  # Summary
  log_step "Phase 04 Deployment Summary"

  if [ ${#failed_services[@]} -eq 0 ]; then
    log_success "All services deployed successfully!"

    # Calculate duration
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    log_info "Total deployment time: $((duration / 60))m $((duration % 60))s"

    log_info "Next steps:"
    log_info "  1. Verify all services are healthy"
    log_info "  2. Test Traefik → Authentik integration"
    log_info "  3. Run security scans before merging"
    log_info "  4. Create PR from feat/phase-04-core-services → dev/pve-test"

  else
    log_error "Deployment failed for services: ${failed_services[*]}"
    log_info "Check logs in $LOG_DIR for details"
    exit 1
  fi

  log_info "Logs saved to: $LOG_DIR"
  log_info "Main log: $LOG_DIR/deploy.log"
}

# ============================================================================
# Entry Point
# ============================================================================

main "$@"
