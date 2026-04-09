#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.pve-test"
MATRIX_SCRIPT="${SCRIPT_DIR}/validate-network-matrix.sh"
PVE_TEST_HOST="pve-test.gibbsgreatly.xyz"

BRIDGE_STACKS=(
  "net-app-01"
  "net-svc-01"
  "net-isolated-01"
)

SDN_STACKS=(
  "net-client-01"
  "net-service-01"
  "net-client-02"
  "net-service-02"
)

ALL_STACKS=(
  "net-app-01"
  "net-svc-01"
  "net-isolated-01"
  "net-client-01"
  "net-service-01"
  "net-client-02"
  "net-service-02"
)

usage() {
  cat <<'EOF'
Usage:
  ./manage-validation-env.sh deploy
  ./manage-validation-env.sh validate
  ./manage-validation-env.sh destroy
  ./manage-validation-env.sh cycle
EOF
}

require_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    printf 'Missing environment file: %s\n' "${ENV_FILE}" >&2
    exit 1
  fi

  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  mkdir -p /tmp/.ansible/tmp /tmp/.ansible/cp
}

run_stack_cmd() {
  local stack="$1"
  local action="$2"

  (
    cd "${SCRIPT_DIR}/stacks/${stack}"
    unset TF_VAR_stack_hostname TF_VAR_stack_app_name TF_VAR_stack_ip_address
    terragrunt "${action}" -auto-approve
  )
}

deploy_env() {
  local stack

  require_env

  for stack in "${SDN_STACKS[@]}"; do
    printf 'Deploying %s\n' "${stack}"
    run_stack_cmd "${stack}" apply
  done

  for stack in "${BRIDGE_STACKS[@]}"; do
    printf 'Deploying %s\n' "${stack}"
    run_stack_cmd "${stack}" apply
  done
}

validate_env() {
  require_env
  "${MATRIX_SCRIPT}"
}

verify_destroy() {
  if ssh -F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@${PVE_TEST_HOST}" \
    "pct list | grep -E 'net-(app|svc|client|service|isolated)'" >/dev/null; then
    printf 'Validation LXCs still exist on %s\n' "${PVE_TEST_HOST}" >&2
    exit 1
  fi

  if ssh -F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@${PVE_TEST_HOST}" \
    "pvesh get /cluster/sdn/vnets --output-format json" \
    | python3 -c 'import json,sys; v=[item["vnet"] for item in json.load(sys.stdin) if item["vnet"] in ("tvn1","tvn2")]; raise SystemExit(0 if v else 1)'; then
    printf 'Validation VNets still exist on %s\n' "${PVE_TEST_HOST}" >&2
    exit 1
  fi

  if ssh -F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@${PVE_TEST_HOST}" \
    "pvesh get /cluster/sdn/zones --output-format json" \
    | python3 -c 'import json,sys; z=[item["zone"] for item in json.load(sys.stdin) if item["zone"] in ("tvz1","tvz2")]; raise SystemExit(0 if z else 1)'; then
    printf 'Validation zones still exist on %s\n' "${PVE_TEST_HOST}" >&2
    exit 1
  fi

  ssh -F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@${PVE_TEST_HOST}" \
    "/usr/libexec/proxmox/proxmox-firewall compile" >/dev/null
}

destroy_env() {
  local stack

  require_env

  for stack in "${BRIDGE_STACKS[@]}"; do
    printf 'Destroying %s\n' "${stack}"
    run_stack_cmd "${stack}" destroy
  done

  for stack in "${SDN_STACKS[@]}"; do
    printf 'Destroying %s\n' "${stack}"
    run_stack_cmd "${stack}" destroy
  done

  verify_destroy
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  case "$1" in
    deploy)
      deploy_env
      ;;
    validate)
      validate_env
      ;;
    destroy)
      destroy_env
      ;;
    cycle)
      deploy_env
      validate_env
      destroy_env
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
