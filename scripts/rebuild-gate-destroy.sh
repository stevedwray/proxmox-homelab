#!/usr/bin/env bash
# Stop-first destroy helper for the pve-test rebuild gate.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WITH_SECRETS="${REPO_ROOT}/with-secrets"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
INVENTORY_FILE="${REPO_ROOT}/docs/teardown-test/inventory.md"
TARGET_NODE_EXPECTED="${REBUILD_GATE_TARGET_NODE_EXPECTED:-${TF_VAR_proxmox_node:-pve-test}}"
TARGET_HOST=""
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="${HOME}/.ssh/known_hosts")
EXECUTE=false

usage() {
  cat <<'EOF'
Usage:
  ./scripts/rebuild-gate-destroy.sh [--dry-run|--plan] [--execute]

Options:
  --dry-run, --plan   Show target scope and actions without mutating state (default)
  --execute           Stop running target CTs, then run the stack-only Terragrunt destroy
  --help              Show this help text
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
}

require_repo_root() {
  local cwd
  cwd="$(pwd -P)"
  if [[ "${cwd}" != "${REPO_ROOT}" ]]; then
    fail "run this command from repo root: ${REPO_ROOT}"
  fi
}

require_pve_test_preflight() {
  local node
  node="$("${WITH_SECRETS}" bash -c "echo \$TF_VAR_proxmox_node" | tr -d '[:space:]')"
  if [[ "${node}" != "${TARGET_NODE_EXPECTED}" ]]; then
    fail "preflight failed: expected TF_VAR_proxmox_node=${TARGET_NODE_EXPECTED}, got '${node}'"
  fi
  TARGET_HOST="$("${WITH_SECRETS}" bash -c 'echo "${REBUILD_GATE_TARGET_HOST:-${PVE_TEST_FQDN:-${PROXMOX_HOST:-${TF_VAR_proxmox_node:-pve-test}.local}}}"' | tr -d '[:space:]')"
  if [[ -z "${TARGET_HOST}" ]]; then
    fail "preflight failed: unable to resolve target host from with-secrets environment"
  fi
  log "Preflight passed: TF_VAR_proxmox_node=${node}, target_host=${TARGET_HOST}"
}

read_vmid_from_stack_yaml() {
  local stack_yaml="$1"
  awk -F ':' '
    /^[[:space:]]*vmid:[[:space:]]*[0-9]+([[:space:]]*#.*)?$/ {
      value=$2
      gsub(/#.*/, "", value)
      gsub(/[[:space:]]/, "", value)
      print value
      exit 0
    }
  ' "${stack_yaml}"
}

approved_destroy_stacks() {
  awk '
    /^## Approved Destroy Order$/ {in_section=1; next}
    in_section && /^## / {exit}
    in_section {
      if (match($0, /^[0-9]+\.[[:space:]]+`([^`]+)`/, matches)) {
        print matches[1]
      }
    }
  ' "${INVENTORY_FILE}"
}

collect_stack_specs() {
  local stack_name stack_yaml vmid
  STACK_NAMES=()
  STACK_VMIDS=()

  while IFS= read -r stack_name; do
    [[ -n "${stack_name}" ]] || continue
    stack_yaml="${STACKS_DIR}/${stack_name}/stack.yaml"
    if [[ ! -f "${stack_yaml}" ]]; then
      fail "missing stack.yaml for approved destroy stack ${stack_name}: ${stack_yaml}"
    fi
    vmid="$(read_vmid_from_stack_yaml "${stack_yaml}")"
    if [[ -z "${vmid}" ]]; then
      fail "missing numeric vmid in ${stack_yaml}"
    fi
    STACK_NAMES+=("${stack_name}")
    STACK_VMIDS+=("${vmid}")
  done < <(approved_destroy_stacks)

  if [[ "${#STACK_NAMES[@]}" -eq 0 ]]; then
    fail "no approved destroy stacks found in ${INVENTORY_FILE}"
  fi
}

print_target_scope() {
  local i
  log "Target stack scope derived from docs/teardown-test/inventory.md Approved Destroy Order:"
  for i in "${!STACK_NAMES[@]}"; do
    printf '  - %s (vmid=%s)\n' "${STACK_NAMES[$i]}" "${STACK_VMIDS[$i]}"
  done
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

stop_running_targets() {
  local i stack vmid status_output status

  for i in "${!STACK_NAMES[@]}"; do
    stack="${STACK_NAMES[$i]}"
    vmid="${STACK_VMIDS[$i]}"

    if status_output="$(remote_pct_status "${vmid}")"; then
      status="$(classify_pct_status "${status_output}")"
    else
      status="$(classify_pct_status "${status_output}")"
      if [[ "${status}" == "unknown" ]]; then
        printf '%s\n' "${status_output}" >&2
        fail "unable to read CT status for ${stack} (vmid=${vmid})"
      fi
    fi

    case "${status}" in
      running)
        log "Stopping ${stack} (vmid=${vmid}) on ${TARGET_HOST}"
        "${WITH_SECRETS}" ssh -F /dev/null "${SSH_OPTS[@]}" "root@${TARGET_HOST}" "pct stop '${vmid}'"

        status_output="$(remote_pct_status "${vmid}" || true)"
        status="$(classify_pct_status "${status_output}")"
        if [[ "${status}" == "running" ]]; then
          fail "stop did not complete for ${stack} (vmid=${vmid})"
        fi
        log "Stop result for ${stack} (vmid=${vmid}): ${status}"
        ;;
      stopped)
        log "No-op: ${stack} (vmid=${vmid}) already stopped"
        ;;
      absent)
        log "No-op: ${stack} (vmid=${vmid}) already absent"
        ;;
      *)
        printf '%s\n' "${status_output}" >&2
        fail "unexpected CT status '${status}' for ${stack} (vmid=${vmid})"
        ;;
    esac
  done
}

print_dry_run_actions() {
  local i stack vmid status_output status

  log "Dry-run mode: no CT stop or destroy commands will be executed."
  log "Stop-first actions that would run:"

  for i in "${!STACK_NAMES[@]}"; do
    stack="${STACK_NAMES[$i]}"
    vmid="${STACK_VMIDS[$i]}"

    status_output="$(remote_pct_status "${vmid}" || true)"
    status="$(classify_pct_status "${status_output}")"

    case "${status}" in
      running)
        log "  - would stop ${stack} (vmid=${vmid})"
        ;;
      stopped)
        log "  - no-op ${stack} (vmid=${vmid}) already stopped"
        ;;
      absent)
        log "  - no-op ${stack} (vmid=${vmid}) already absent"
        ;;
      *)
        log "  - unable to classify status for ${stack} (vmid=${vmid}); would fail in --execute mode"
        ;;
    esac
  done

  log "Terragrunt destroy commands that would run:"
  for i in "${!STACK_NAMES[@]}"; do
    stack="${STACK_NAMES[$i]}"
    log "  - ${WITH_SECRETS} terragrunt destroy --working-dir terraform/lxc/stacks/${stack} -auto-approve"
  done
}

run_destroy() {
  local i stack

  if [[ "${EXECUTE}" == true ]]; then
    stop_running_targets
    for i in "${!STACK_NAMES[@]}"; do
      stack="${STACK_NAMES[$i]}"
      log "Terragrunt destroy command: ${WITH_SECRETS} terragrunt destroy --working-dir terraform/lxc/stacks/${stack} -auto-approve"
      "${WITH_SECRETS}" terragrunt destroy --working-dir "terraform/lxc/stacks/${stack}" -auto-approve
    done
  else
    print_dry_run_actions
  fi
}

main() {
  parse_args "$@"
  require_repo_root
  require_pve_test_preflight
  collect_stack_specs
  print_target_scope
  run_destroy
}

main "$@"
