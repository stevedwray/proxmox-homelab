#!/usr/bin/env bash
# Destroy or stop a disposable pve-test stack counterpart before a pve cutover.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WITH_SECRETS="${REPO_ROOT}/with-secrets"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
TARGET_NODE_EXPECTED="${COUNTERPART_TARGET_NODE_EXPECTED:-pve-test}"
TARGET_HOST_FALLBACK="${COUNTERPART_TARGET_HOST:-pve-test.gibbsgreatly.xyz}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="${HOME}/.ssh/known_hosts")

STACK_NAME=""
STACK_DIR=""
STACK_YAML=""
STACK_VMID=""
STACK_IP=""
ACTION="destroy"
EXECUTE=false
TARGET_HOST=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/dispose-pve-test-counterpart.sh --stack <name> [--destroy|--stop-only] [--dry-run|--plan]
  ./scripts/dispose-pve-test-counterpart.sh --stack <name> [--destroy|--stop-only] --execute

Options:
  --stack <name>     Stack name under terraform/lxc/stacks/ (required)
  --destroy          Stop first if needed, then Terragrunt destroy the counterpart (default)
  --stop-only        Stop the counterpart but leave Terragrunt state/resources intact
  --dry-run, --plan  Show the detected counterpart state and planned action (default)
  --execute          Perform the selected action
  --help, -h         Show this help text
EOF
}

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

parse_args() {
  while (($# > 0)); do
    case "$1" in
      --stack)
        [[ $# -ge 2 ]] || fail "--stack requires a value"
        STACK_NAME="$2"
        shift
        ;;
      --destroy)
        ACTION="destroy"
        ;;
      --stop-only)
        ACTION="stop"
        ;;
      --dry-run|--plan)
        EXECUTE=false
        ;;
      --execute)
        EXECUTE=true
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "unknown argument: $1"
        ;;
    esac
    shift
  done

  [[ -n "${STACK_NAME}" ]] || fail "--stack is required"
}

require_repo_root() {
  local cwd
  cwd="$(pwd -P)"
  if [[ "${cwd}" != "${REPO_ROOT}" ]]; then
    fail "run this command from repo root: ${REPO_ROOT}"
  fi
}

require_stack() {
  STACK_DIR="${STACKS_DIR}/${STACK_NAME}"
  STACK_YAML="${STACK_DIR}/stack.yaml"

  [[ -d "${STACK_DIR}" ]] || fail "stack directory not found: ${STACK_DIR}"
  [[ -f "${STACK_YAML}" ]] || fail "stack.yaml not found: ${STACK_YAML}"
}

read_stack_value() {
  local key="$1"
  awk -F ':' -v wanted="${key}" '
    $1 ~ "^[[:space:]]*" wanted "[[:space:]]*$" {
      value=$2
      gsub(/#.*/, "", value)
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      print value
      exit 0
    }
  ' "${STACK_YAML}"
}

load_stack_metadata() {
  STACK_VMID="$(read_stack_value "vmid")"
  STACK_IP="$(read_stack_value "ip_address")"

  [[ "${STACK_VMID}" =~ ^[0-9]+$ ]] || fail "missing numeric vmid in ${STACK_YAML}"
}

require_pve_test_preflight() {
  local node
  node="$("${WITH_SECRETS}" bash -c "printf '%s' \"\${TF_VAR_proxmox_node:-}\"")"
  if [[ "${node}" != "${TARGET_NODE_EXPECTED}" ]]; then
    fail "preflight failed: expected TF_VAR_proxmox_node=${TARGET_NODE_EXPECTED}, got '${node}'"
  fi
  log "Preflight passed: TF_VAR_proxmox_node=${node}"
}

resolve_target_host() {
  TARGET_HOST="$("${WITH_SECRETS}" bash -c "printf '%s' \"\${PVE_TEST_FQDN:-\${PROXMOX_HOST:-${TARGET_HOST_FALLBACK}}}\"")"
  [[ -n "${TARGET_HOST}" ]] || fail "unable to resolve pve-test target host"
}

remote_pct_status() {
  local vmid="$1"
  "${WITH_SECRETS}" ssh -F /dev/null "${SSH_OPTS[@]}" "root@${TARGET_HOST}" "pct status '${vmid}'" 2>&1
}

classify_pct_status() {
  local status_output="$1"
  local status_line status_value

  if grep -qiE 'does not exist|not exist|configuration file .* does not exist|failed to open .*\.conf' <<<"${status_output}"; then
    printf 'absent\n'
    return 0
  fi

  status_line="$(awk -F ': ' '/^status:/ {print $2; exit}' <<<"${status_output}")"
  status_value="${status_line//[[:space:]]/}"

  if [[ -z "${status_value}" ]]; then
    printf 'unknown\n'
    return 0
  fi

  printf '%s\n' "${status_value}"
}

read_counterpart_status() {
  local status_output
  status_output="$(remote_pct_status "${STACK_VMID}" || true)"
  classify_pct_status "${status_output}"
}

stop_counterpart_if_running() {
  local status
  status="$(read_counterpart_status)"

  case "${status}" in
    running)
      log "Stopping ${STACK_NAME} (vmid=${STACK_VMID}) on ${TARGET_HOST}"
      "${WITH_SECRETS}" ssh -F /dev/null "${SSH_OPTS[@]}" "root@${TARGET_HOST}" "pct stop '${STACK_VMID}'"
      ;;
    stopped)
      log "No-op: ${STACK_NAME} (vmid=${STACK_VMID}) already stopped"
      ;;
    absent)
      log "No-op: ${STACK_NAME} (vmid=${STACK_VMID}) already absent"
      ;;
    *)
      fail "unexpected CT status '${status}' for ${STACK_NAME} (vmid=${STACK_VMID})"
      ;;
  esac
}

verify_absent() {
  local status
  status="$(read_counterpart_status)"
  [[ "${status}" == "absent" ]] || fail "expected ${STACK_NAME} (vmid=${STACK_VMID}) to be absent after destroy, got '${status}'"
}

run_destroy() {
  local destroy_cmd=(
    "${WITH_SECRETS}"
    terragrunt
    destroy
    --working-dir "${STACK_DIR}"
    -auto-approve
  )

  stop_counterpart_if_running
  log "Destroying ${STACK_NAME} Terragrunt state on ${TARGET_NODE_EXPECTED}"
  NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true \
  NETWORK_SDN_EXPECTED_TARGET="${TARGET_NODE_EXPECTED}" \
  NETWORK_SDN_EXPECTED_PVE_HOST="${TARGET_HOST}" \
  "${destroy_cmd[@]}"
  verify_absent
  log "Destroy complete: ${STACK_NAME} counterpart is absent on ${TARGET_HOST}"
}

print_plan() {
  local status
  status="$(read_counterpart_status)"

  log "Counterpart target:"
  log "  stack: ${STACK_NAME}"
  log "  vmid: ${STACK_VMID}"
  if [[ -n "${STACK_IP}" ]]; then
    log "  ip:   ${STACK_IP}"
  fi
  log "  host: ${TARGET_HOST}"
  log "  state: ${status}"
  log "Planned action: ${ACTION}"

  case "${ACTION}" in
    destroy)
      log "Would stop the counterpart if running, then Terragrunt destroy ${STACK_NAME} on ${TARGET_NODE_EXPECTED}."
      ;;
    stop)
      log "Would stop the counterpart if it is currently running."
      ;;
  esac
}

run_execute() {
  case "${ACTION}" in
    destroy)
      run_destroy
      ;;
    stop)
      stop_counterpart_if_running
      ;;
    *)
      fail "unsupported action: ${ACTION}"
      ;;
  esac
}

main() {
  parse_args "$@"
  require_repo_root
  require_stack
  load_stack_metadata
  require_pve_test_preflight
  resolve_target_host

  if [[ "${EXECUTE}" == true ]]; then
    run_execute
  else
    print_plan
  fi
}

main "$@"
