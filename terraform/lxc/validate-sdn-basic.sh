#!/usr/bin/env bash
# Basic SDN smoke harness: intentionally narrow scope.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WITH_SECRETS="${REPO_ROOT}/with-secrets"

STACKS=(
  "test-lxc"
  "net-build-01"
)

usage() {
  cat <<'EOF'
Usage: terraform/lxc/validate-sdn-basic.sh <apply|validate|destroy|cycle>

Scope:
  - test-lxc
  - net-build-01

Actions:
  apply     Apply both stacks in order
  validate  Run basic Ansible validation playbook
  destroy   Destroy both stacks in reverse order
  cycle     apply + validate + destroy
EOF
}

run_stack_apply() {
  local stack
  for stack in "${STACKS[@]}"; do
    echo "[basic-sdn] apply ${stack}"
    "${WITH_SECRETS}" terragrunt --working-dir "${SCRIPT_DIR}/stacks/${stack}" apply -auto-approve
  done
}

run_stack_destroy() {
  local i stack
  for ((i=${#STACKS[@]}-1; i>=0; i--)); do
    stack="${STACKS[i]}"
    echo "[basic-sdn] destroy ${stack}"
    "${WITH_SECRETS}" terragrunt --working-dir "${SCRIPT_DIR}/stacks/${stack}" destroy -auto-approve
  done
}

run_validate() {
  echo "[basic-sdn] validate playbook"
  "${WITH_SECRETS}" ansible-playbook \
    "${SCRIPT_DIR}/ansible/playbooks/validate-sdn-basic.yml"
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  case "$1" in
    apply)
      run_stack_apply
      ;;
    validate)
      run_validate
      ;;
    destroy)
      run_stack_destroy
      ;;
    cycle)
      run_stack_apply
      run_validate
      run_stack_destroy
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "Unknown action: $1" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
