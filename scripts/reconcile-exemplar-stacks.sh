#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROVISION_SCRIPT="${REPO_ROOT}/scripts/provision.sh"

usage() {
  cat <<'EOF'
Usage: scripts/reconcile-exemplar-stacks.sh [--stack <apt-cacher-stack|harbor-stack>]... [--check] [--post-infra] [--approval-text <text>]

Runs day-2 reconcile for the Stage 4 exemplar pair only.

Options:
  --stack <name>   Limit reconcile to an exemplar stack (repeatable).
  --check          Run ansible-playbook in check mode.
  --post-infra     Enable approval-gated post-infra reconcile mode.
  --approval-text  Required with --post-infra; must include approval intent.
  -h, --help       Show this help text.

Notes:
  - This script intentionally scopes to apt-cacher-stack and harbor-stack.
  - Invoke through with-secrets for secret-bearing workflows:
      ./with-secrets ./scripts/reconcile-exemplar-stacks.sh --post-infra --approval-text "I approve day-2 reconcile for exemplars"
EOF
}

log() {
  printf '[reconcile-exemplar] %s\n' "$*"
}

fail() {
  printf '[reconcile-exemplar] ERROR: %s\n' "$*" >&2
  exit 1
}

is_allowed_stack() {
  case "$1" in
    apt-cacher-stack|harbor-stack)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

approval_text_satisfies_post_infra_gate() {
  local text_lc="$1"
  [[ "${text_lc}" == *"approve"* ]] || return 1
  [[ "${text_lc}" == *"day-2"* ]] || return 1
  [[ "${text_lc}" == *"reconcile"* ]] || return 1
  return 0
}

declare -a requested_stacks=()
check_mode=false
post_infra=false
approval_text=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack)
      [[ $# -ge 2 ]] || fail "--stack requires a value"
      requested_stacks+=("$2")
      shift 2
      ;;
    --check)
      check_mode=true
      shift
      ;;
    --post-infra)
      post_infra=true
      shift
      ;;
    --approval-text)
      [[ $# -ge 2 ]] || fail "--approval-text requires a value"
      approval_text="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -x "${PROVISION_SCRIPT}" ]] || fail "missing provision entrypoint: ${PROVISION_SCRIPT}"

if (( ${#requested_stacks[@]} == 0 )); then
  requested_stacks=("apt-cacher-stack" "harbor-stack")
fi

for stack in "${requested_stacks[@]}"; do
  is_allowed_stack "$stack" || fail "unsupported stack '${stack}' (allowed: apt-cacher-stack, harbor-stack)"
done

if [[ "${post_infra}" == "true" ]]; then
  [[ -n "${approval_text}" ]] || fail "--post-infra requires --approval-text"
  if ! approval_text_satisfies_post_infra_gate "${approval_text,,}"; then
    fail "--approval-text must include approval intent for day-2 reconcile"
  fi
  log "Post-infra approval accepted for exemplar day-2 reconcile"
else
  if [[ -n "${approval_text}" ]]; then
    fail "--approval-text is only valid with --post-infra"
  fi
fi

for stack in "${requested_stacks[@]}"; do
  cmd=("${PROVISION_SCRIPT}" --stack "$stack")
  if [[ "${check_mode}" == "true" ]]; then
    cmd+=(--check)
  fi
  log "RUN ${stack}: ${cmd[*]}"
  "${cmd[@]}"
done

log "Completed exemplar day-2 reconcile"
