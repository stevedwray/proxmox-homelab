#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

STAMP="${TEARDOWN_EXECUTOR_STAMP:-$(date -u +%Y%m%d-%H%M%S)-retry-runner-op06}"
EVIDENCE_ROOT="${REPO_ROOT}/docs/teardown-test/evidence/${STAMP}"
LOG_DIR="${EVIDENCE_ROOT}/logs"
BACKUP_DIR="${EVIDENCE_ROOT}/backups"
TRANSCRIPT="${LOG_DIR}/action-transcript.log"

APPROVAL_PACKET="${REPO_ROOT}/docs/teardown-test/approval-packet-op06.md"
APPROVAL_TEXT="${TEARDOWN_DESTRUCTIVE_APPROVAL_TEXT:-}"
REVIEWED_DIFF="${TEARDOWN_REVIEWED_DIFF:-}"
EXPECTED_BRANCH="${TEARDOWN_EXPECTED_BRANCH:-}"
EXPECTED_HEAD="${TEARDOWN_EXPECTED_HEAD:-}"
PREFLIGHT_ONLY="false"

WITH_SECRETS="${REPO_ROOT}/with-secrets"
PVE_HOST="${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz}"
TARGET_NODE_EXPECTED="${RETRY_RUNNER_TARGET_NODE_EXPECTED:-${TF_VAR_proxmox_node:-pve-test}}"
APPROVAL_SCOPE_TARGET="${RETRY_RUNNER_APPROVAL_SCOPE_TARGET:-${TARGET_NODE_EXPECTED}}"
REVIEW_BASE_BRANCH="${RETRY_RUNNER_REVIEW_BASE_BRANCH:-dev/pve-test}"
MODE="${1:-self-check}"

PRE_EXEC_STATUS=""

REQUIRED_BACKUP_DIRS=(
  "portainer"
  "harbor"
  "authentik"
  "netbox"
  "monitoring"
  "traefik-certs"
  "step-ca"
  "ci-runner"
  "apt-cacher"
)

NON_LOSS_BACKUP_DIRS=(
  "step-ca"
  "authentik"
  "harbor"
  "netbox"
)

STACK_ORDER=(
  "netbox-stack:143"
  "monitoring-stack:154"
  "authentik-stack:150"
  "step-ca-stack:152"
  "proxy-stack:153"
  "dns-stack:151"
  "ci-runner-01:141"
  "harbor-stack:121"
  "apt-cacher-stack:142"
  "portainer-stack:120"
)

usage() {
  cat <<'EOF'
Usage: scripts/retry-runner-op06.sh [self-check|destroy] [options]

Modes:
  self-check  Non-destructive validation only (default).
  destroy     Executes approved destroy sequence. Destructive.

Options:
  --stamp <stamp>                 Evidence stamp override.
  --approval-text <text>          Required in destroy mode.
  --approval-packet <path>        Approval packet path (default OP-06 packet).
  --reviewed-diff <path>          Reviewed candidate diff file for drift checks.
  --expected-branch <branch>      Branch pin for reviewed-state checks in destroy mode.
  --expected-head <sha>           HEAD pin for reviewed-state checks in destroy mode.
  --preflight-only                Destroy mode only: run all pre-destroy gates, then exit cleanly.
  -h, --help                      Show help.
EOF
}

log_cmd() {
  printf '[%s] %s\n' "$(TZ=Pacific/Auckland date '+%Y-%m-%d %H:%M:%S NZST %z')" "$1" | tee -a "${TRANSCRIPT}" >/dev/null
}

close_guard_summary() {
  if "${WITH_SECRETS}" bash -c 'echo $TF_VAR_proxmox_node' >"${LOG_DIR}/guard-end.log" 2>&1; then
    :
  fi
  local end_guard=""
  end_guard="$(tail -n 1 "${LOG_DIR}/guard-end.log" 2>/dev/null | tr -d '\r' || true)"
  printf 'guard_value=%s\n' "${end_guard}" >"${LOG_DIR}/guard-end-summary.log"
}

fail_stop() {
  local phase="$1"
  local step="$2"
  local klass="$3"
  local detail="$4"

  log_cmd "STOP: phase=${phase} step=${step} class=${klass} detail=${detail}"
  close_guard_summary
  {
    echo "status=stopped"
    echo "mode=${MODE}"
    echo "phase=${phase}"
    echo "stop_condition=first_failure"
    echo "failing_step=${step}"
    echo "failure_class=${klass}"
    echo "failure_detail=${detail}"
    echo "close_guard=$(tail -n 1 "${LOG_DIR}/guard-end-summary.log" | cut -d= -f2-)"
    echo "destructive_actions_executed=false"
  } >"${LOG_DIR}/final-readiness-summary.log"
  exit 1
}

parse_args() {
  shift || true
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stamp)
        STAMP="$2"
        shift 2
        ;;
      --approval-text)
        APPROVAL_TEXT="$2"
        shift 2
        ;;
      --approval-packet)
        APPROVAL_PACKET="$2"
        shift 2
        ;;
      --reviewed-diff)
        REVIEWED_DIFF="$2"
        shift 2
        ;;
      --expected-branch)
        EXPECTED_BRANCH="$2"
        shift 2
        ;;
      --expected-head)
        EXPECTED_HEAD="$2"
        shift 2
        ;;
      --preflight-only)
        PREFLIGHT_ONLY="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "ERROR: unknown option '$1'" >&2
        usage
        exit 1
        ;;
    esac
  done
}

backup_dir_has_artifact() {
  local dir="$1"
  find "${dir}" -mindepth 1 -type f | grep -q .
}

validate_backup_gating() {
  local strict_mode="${1:-true}"
  local missing_dirs=()
  local missing_non_loss=()
  local optional_empty=()
  local d

  for d in "${REQUIRED_BACKUP_DIRS[@]}"; do
    if [[ ! -d "${BACKUP_DIR}/${d}" ]]; then
      missing_dirs+=("${BACKUP_DIR}/${d}")
    fi
  done

  for d in "${NON_LOSS_BACKUP_DIRS[@]}"; do
    if [[ -d "${BACKUP_DIR}/${d}" ]] && ! backup_dir_has_artifact "${BACKUP_DIR}/${d}"; then
      missing_non_loss+=("${BACKUP_DIR}/${d}")
    fi
  done

  for d in "${REQUIRED_BACKUP_DIRS[@]}"; do
    if [[ -d "${BACKUP_DIR}/${d}" ]] && ! backup_dir_has_artifact "${BACKUP_DIR}/${d}"; then
      optional_empty+=("${BACKUP_DIR}/${d}")
    fi
  done

  {
    echo "required_backup_root=${BACKUP_DIR}"
    echo "required_dir_count=${#REQUIRED_BACKUP_DIRS[@]}"
    echo "missing_dir_count=${#missing_dirs[@]}"
    echo "missing_non_loss_count=${#missing_non_loss[@]}"
    printf 'required_dirs=%s\n' "${REQUIRED_BACKUP_DIRS[*]}"
    if (( ${#missing_dirs[@]} > 0 )); then
      printf 'missing_dirs=%s\n' "${missing_dirs[*]}"
    fi
    if (( ${#missing_non_loss[@]} > 0 )); then
      printf 'missing_non_loss_artifacts=%s\n' "${missing_non_loss[*]}"
    fi
    if (( ${#optional_empty[@]} > 0 )); then
      printf 'empty_backup_dirs=%s\n' "${optional_empty[*]}"
    fi
  } >"${LOG_DIR}/backup-gating-summary.log"

  if (( ${#missing_dirs[@]} > 0 )) && [[ "${strict_mode}" == "true" ]]; then
    fail_stop phase2 backup-gating backup_dir_missing "required backup directories missing"
  fi
  if (( ${#missing_non_loss[@]} > 0 )) && [[ "${strict_mode}" == "true" ]]; then
    fail_stop phase2 backup-gating backup_artifact_missing "non-loss backup artifacts missing"
  fi

  if (( ${#missing_dirs[@]} > 0 || ${#missing_non_loss[@]} > 0 )); then
    return 1
  fi
  return 0
}

packet_has_required_scope() {
  local packet_path="$1"
  local -a required_patterns=(
    'Approval status:[[:space:]]*APPROVED'
    'Scope:[[:space:]]*Human go/no-go gate for destroy batch only'
    'OP-07[[:space:]]+through[[:space:]]+OP-16'
    'destroy[[:space:]]+only'
    'stop(ping)?[[:space:]]+on[[:space:]]+first[[:space:]]+failure'
    "${APPROVAL_SCOPE_TARGET}"
    'exclude(s|d)?[[:space:]]+rebuild[[:space:]]+apply'
    'exclude(s|d)?[[:space:]]+edge[[:space:]]+publish'
    'exclude(s|d)?.*OP-25'
    'exclude(s|d)?.*OP-28'
    'exclude(s|d)?.*OP-29'
    'exclude(s|d)?.*reconcile([[:space:]-]+--apply|[[:space:]-]+apply)'
  )
  local pat

  for pat in "${required_patterns[@]}"; do
    if ! grep -Eiq "${pat}" "${packet_path}"; then
      return 1
    fi
  done
  return 0
}

approval_text_has_required_scope() {
  local approval_lc="$1"
  local approval_scope_target_lc="${APPROVAL_SCOPE_TARGET,,}"
  [[ "${approval_lc}" == *"approve"* ]] || return 1
  [[ "${approval_lc}" == *"op-06"* ]] || return 1
  [[ "${approval_lc}" == *"op-07"* ]] || return 1
  [[ "${approval_lc}" == *"op-16"* ]] || return 1
  [[ "${approval_lc}" == *"destroy"* ]] || return 1
  [[ "${approval_lc}" == *"${approval_scope_target_lc}"* ]] || return 1
  [[ "${approval_lc}" == *"first failure"* ]] || return 1
  [[ "${approval_lc}" == *"does not authorize"* ]] || return 1
  [[ "${approval_lc}" == *"rebuild apply"* ]] || return 1
  [[ "${approval_lc}" == *"edge publish"* ]] || return 1
  [[ "${approval_lc}" == *"op-25"* ]] || return 1
  [[ "${approval_lc}" == *"op-28"* ]] || return 1
  [[ "${approval_lc}" == *"op-29"* ]] || return 1
  [[ "${approval_lc}" == *"reconcile"* && "${approval_lc}" == *"apply"* ]] || return 1
  return 0
}

validate_destructive_approval() {
  local approval_lc
  approval_lc="${APPROVAL_TEXT,,}"

  if [[ ! -f "${APPROVAL_PACKET}" ]]; then
    fail_stop phase2 approval-packet approval_packet_missing "approval packet path not found"
  fi

  if ! approval_text_has_required_scope "${approval_lc}"; then
    fail_stop phase2 approval-gate approval_text_scope_invalid "approval text must match OP-06 destroy-only scope and exclusions"
  fi

  if ! packet_has_required_scope "${APPROVAL_PACKET}"; then
    fail_stop phase2 approval-gate approval_packet_scope_invalid "approval packet missing required OP-06 scope markers"
  fi

  {
    echo "approval_packet=${APPROVAL_PACKET}"
    echo "approval_packet_scope=validated_op06_destroy_only"
    echo "approval_text_scope=validated_op06_destroy_only"
    echo "approval_text_redacted_length=${#APPROVAL_TEXT}"
  } >"${LOG_DIR}/approval-gating-summary.log"
}

require_guard() {
  local tag="$1"
  local phase="$2"

  log_cmd "CMD: ${WITH_SECRETS} bash -c guard-check (${tag})"
  "${WITH_SECRETS}" bash -c 'echo $TF_VAR_proxmox_node' >"${LOG_DIR}/guard-${tag}.log" || fail_stop "${phase}" "${tag}" "guard_command_error" "guard command failed"
  local gv=""
  gv="$(tail -n 1 "${LOG_DIR}/guard-${tag}.log" | tr -d '\r')"

  if [[ "${tag}" == "intake" ]]; then
    printf 'guard_value=%s\n' "${gv}" >"${LOG_DIR}/guard-summary.log"
  fi

  if [[ "${gv}" != "${TARGET_NODE_EXPECTED}" ]]; then
    fail_stop "${phase}" "${tag}" "guard_mismatch" "expected ${TARGET_NODE_EXPECTED} got ${gv}"
  fi
}

verify_reviewed_state() {
  local phase="$1"
  log_cmd "CMD: verify reviewed branch/head/diff"

  local branch=""
  local head=""
  local merge_base=""
  local branch_check="skipped"
  local head_check="skipped"
  local reviewed_diff_check="skipped"
  local reviewed_pinning_check="skipped"

  branch="$(git -C "${REPO_ROOT}" branch --show-current)"
  head="$(git -C "${REPO_ROOT}" rev-parse HEAD)"

  if [[ "${MODE}" == "destroy" ]]; then
    if [[ -z "${EXPECTED_BRANCH}" || -z "${EXPECTED_HEAD}" || -z "${REVIEWED_DIFF}" ]]; then
      fail_stop "${phase}" "reviewed-state" "reviewed_state_pinning_required" "destroy mode requires --expected-branch, --expected-head, and --reviewed-diff"
    fi
    reviewed_pinning_check="passed"
  else
    if [[ -z "${EXPECTED_BRANCH}" ]]; then
      EXPECTED_BRANCH="${branch}"
    fi
    if [[ -z "${EXPECTED_HEAD}" ]]; then
      EXPECTED_HEAD="${head}"
    fi
  fi

  {
    echo "expected_branch=${EXPECTED_BRANCH}"
    echo "actual_branch=${branch}"
    echo "expected_head=${EXPECTED_HEAD}"
    echo "actual_head=${head}"
    echo "reviewed_diff_reference=${REVIEWED_DIFF:-unset}"
    echo "reviewed_pinning_check=${reviewed_pinning_check}"
  } >"${LOG_DIR}/git-reviewed-state.log"

  if [[ "${branch}" != "${EXPECTED_BRANCH}" ]]; then
    fail_stop "${phase}" "reviewed-state" "branch_mismatch" "${branch}"
  fi
  branch_check="passed"

  if [[ "${head}" != "${EXPECTED_HEAD}" ]]; then
    fail_stop "${phase}" "reviewed-state" "head_mismatch" "${head}"
  fi
  head_check="passed"

  merge_base="$(git -C "${REPO_ROOT}" merge-base HEAD "${REVIEW_BASE_BRANCH}")"
  git -C "${REPO_ROOT}" diff --name-only "${merge_base}"..HEAD >"${LOG_DIR}/git-changed-files-candidate.log"

  if [[ -n "${REVIEWED_DIFF}" ]]; then
    if [[ ! -f "${REVIEWED_DIFF}" ]]; then
      fail_stop "${phase}" "reviewed-diff" "reviewed_diff_missing" "reviewed diff file not found"
    fi

    if ! diff -u "${REVIEWED_DIFF}" "${LOG_DIR}/git-changed-files-candidate.log" >"${LOG_DIR}/git-changed-files-reviewed-diff.log"; then
      echo "candidate_diff_match_reviewed=false" >"${LOG_DIR}/git-reviewed-diff-status.log"
      fail_stop "${phase}" "reviewed-diff" "candidate_diff_drift" "candidate diff changed from reviewed state"
    fi
    echo "candidate_diff_match_reviewed=true" >"${LOG_DIR}/git-reviewed-diff-status.log"
    reviewed_diff_check="passed"
  else
    : >"${LOG_DIR}/git-changed-files-reviewed-diff.log"
    echo "candidate_diff_match_reviewed=skipped" >"${LOG_DIR}/git-reviewed-diff-status.log"
    if [[ "${MODE}" == "destroy" ]]; then
      fail_stop "${phase}" "reviewed-diff" "reviewed_diff_required" "destroy mode requires --reviewed-diff"
    fi
    reviewed_diff_check="skipped"
  fi

  {
    echo "reviewed_pinning_check=${reviewed_pinning_check}"
    echo "branch_check=${branch_check}"
    echo "head_check=${head_check}"
    echo "reviewed_diff_check=${reviewed_diff_check}"
  } >"${LOG_DIR}/reviewed-state-summary.log"
}

validate_clean_tree_for_destroy() {
  {
    echo "mode=${MODE}"
    echo "gate=clean_working_tree_destroy"
    if [[ -z "${PRE_EXEC_STATUS}" ]]; then
      echo "clean_tree=true"
    else
      echo "clean_tree=false"
      printf '%s\n' "${PRE_EXEC_STATUS}"
    fi
  } >"${LOG_DIR}/clean-tree-gating-summary.log"

  if [[ -n "${PRE_EXEC_STATUS}" ]]; then
    fail_stop phase2 clean-tree-gating dirty_worktree "destructive mode requires a clean working tree before execution"
  fi
}

run_destroy_stack() {
  local spec="$1"
  local stack="${spec%%:*}"
  local vmid="${spec##*:}"

  require_guard "before-destroy-${stack}" phase3
  verify_reviewed_state phase3

  log_cmd "CMD: ${WITH_SECRETS} terragrunt destroy --working-dir ${REPO_ROOT}/terraform/lxc/stacks/${stack} -auto-approve"
  if ! "${WITH_SECRETS}" terragrunt destroy --working-dir "${REPO_ROOT}/terraform/lxc/stacks/${stack}" -auto-approve >"${LOG_DIR}/destroy-${stack}.log" 2>&1; then
    fail_stop phase3 "destroy-${stack}" terragrunt_failure "see destroy-${stack}.log"
  fi

  require_guard "verify-destroy-${stack}" phase3
  if ! "${WITH_SECRETS}" ssh -F /dev/null "root@${PVE_HOST}" "if pct status ${vmid} >/dev/null 2>&1; then echo 'FAIL vmid_${vmid}_still_present' >&2; exit 1; fi; echo 'PASS vmid_${vmid}_absent'" >"${LOG_DIR}/verify-destroy-${stack}.log" 2>&1; then
    fail_stop phase3 "verify-destroy-${stack}" verify_failure "vmid ${vmid} still present"
  fi
  printf 'stack=%s vmid=%s verify_result=pass\n' "${stack}" "${vmid}" >>"${LOG_DIR}/verify-destroy-summary.log"
}

main() {
  parse_args "$@"

  EVIDENCE_ROOT="${REPO_ROOT}/docs/teardown-test/evidence/${STAMP}"
  LOG_DIR="${EVIDENCE_ROOT}/logs"
  BACKUP_DIR="${EVIDENCE_ROOT}/backups"
  TRANSCRIPT="${LOG_DIR}/action-transcript.log"

  case "${MODE}" in
    self-check|destroy)
      ;;
    *)
      echo "ERROR: unknown mode '${MODE}'" >&2
      usage
      exit 1
      ;;
  esac

  if [[ "${PREFLIGHT_ONLY}" == "true" && "${MODE}" != "destroy" ]]; then
    echo "ERROR: --preflight-only is valid only with destroy mode" >&2
    exit 1
  fi

  PRE_EXEC_STATUS="$(git -C "${REPO_ROOT}" status --porcelain=v1 --untracked-files=all)"

  mkdir -p "${LOG_DIR}" "${BACKUP_DIR}"
  : >"${TRANSCRIPT}"

  printf '%s\n' "${PRE_EXEC_STATUS}" >"${LOG_DIR}/git-status-pre-execution.log"

  if [[ ! -x "${WITH_SECRETS}" ]]; then
    fail_stop phase1 with-secrets-path wrapper_missing "${WITH_SECRETS} not executable"
  fi

  log_cmd "CMD: capture session metadata"
  {
    echo "stamp=${STAMP}"
    echo "mode=${MODE}"
    echo "branch=$(git -C "${REPO_ROOT}" branch --show-current)"
    echo "head_full=$(git -C "${REPO_ROOT}" rev-parse HEAD)"
    echo "head_short=$(git -C "${REPO_ROOT}" rev-parse --short HEAD)"
    echo "timestamp_nzst=$(TZ=Pacific/Auckland date '+%Y-%m-%d %H:%M:%S NZST %z')"
    echo "repo_root=${REPO_ROOT}"
    echo "with_secrets=${WITH_SECRETS}"
    echo "approval_packet=${APPROVAL_PACKET}"
    echo "reviewed_diff=${REVIEWED_DIFF:-unset}"
    echo "evidence_root=${EVIDENCE_ROOT}"
    echo "logs_root=${LOG_DIR}"
    echo "backups_root=${BACKUP_DIR}"
    echo "runner_interface=retry-runner-op06"
    echo "preflight_only=${PREFLIGHT_ONLY}"
    echo "pre_execution_clean_tree=$([[ -z "${PRE_EXEC_STATUS}" ]] && echo true || echo false)"
  } >"${LOG_DIR}/session-metadata.log"

  require_guard intake phase1
  verify_reviewed_state phase1
  git -C "${REPO_ROOT}" status --short --branch >"${LOG_DIR}/git-status.log"

  if [[ "${MODE}" == "self-check" ]]; then
    if validate_backup_gating false >"${LOG_DIR}/backup-gating-self-check.log" 2>&1; then
      echo "backup_gating_self_check=pass" >>"${LOG_DIR}/backup-gating-summary.log"
    else
      echo "backup_gating_self_check=fail" >>"${LOG_DIR}/backup-gating-summary.log"
    fi

    {
      echo "status=completed"
      echo "mode=self-check"
      echo "runtime_changes=false"
      echo "destructive_actions_executed=false"
      echo "with_secrets_path_check=passed"
      echo "reviewed_state_check=passed"
      echo "backup_gating_check=executed_non_blocking"
      echo "approval_gating_check=skipped"
      echo "clean_tree_gating_check=skipped"
    } >"${LOG_DIR}/final-readiness-summary.log"

    printf 'READY: non-destructive self-check passed\n'
    exit 0
  fi

  validate_backup_gating true
  validate_destructive_approval
  verify_reviewed_state phase2
  validate_clean_tree_for_destroy

  if [[ "${PREFLIGHT_ONLY}" == "true" ]]; then
    require_guard end phase2
    {
      echo "status=completed"
      echo "mode=destroy"
      echo "preflight_only=true"
      echo "runtime_changes=false"
      echo "destructive_actions_executed=false"
      echo "stop_condition=pre_destroy_preflight_exit"
      echo "gates_passed=backup,approval,reviewed_state,clean_tree"
    } >"${LOG_DIR}/final-readiness-summary.log"
    printf 'READY: pre-destroy validation passed (non-destructive preflight-only exit)\n'
    exit 0
  fi

  for spec in "${STACK_ORDER[@]}"; do
    run_destroy_stack "${spec}"
  done

  require_guard end phase6
  printf 'guard_value=%s\n' "${TARGET_NODE_EXPECTED}" >"${LOG_DIR}/guard-end-summary.log"
  {
    echo "status=completed"
    echo "mode=destroy"
    echo "runtime_changes=true"
    echo "destructive_actions_executed=true"
    echo "stop_condition=none"
  } >"${LOG_DIR}/final-readiness-summary.log"
}

main "$@"
