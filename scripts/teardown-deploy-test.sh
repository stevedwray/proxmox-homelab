#!/usr/bin/env bash
# Repeatable teardown/deploy harness with explicit target selection.
#
# Safe-by-default phases:
#   source-preflight   non-destructive source-only validation
#   live-preflight     non-destructive live read-only validation
#   approval-preflight clean-tree go/no-go preflight for destructive approval
#   preflight          backwards-compatible alias for source + live preflight
#   plan               show inventory-derived stack plans
#   platform-status    show read-only current stack/container state
#   status             summarize machine-readable checkpoint state for a stamp
#   final-validation   live read-only service and route checks
#
# Mutating phases require both --execute and --approval-text.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TERRAFORM_LXC="${REPO_ROOT}/terraform/lxc"
ANSIBLE_DIR="${TERRAFORM_LXC}/ansible"
EVIDENCE_ROOT="${REPO_ROOT}/docs/teardown-test/artifacts/evidence"
HOMELAB_ROOT_CA="${REPO_ROOT}/certs/homelab-root.crt"
INVENTORY_FILE="${TEARDOWN_INVENTORY_FILE:-${REPO_ROOT}/docs/teardown-test/inventory.md}"
TARGET_NODE_EXPECTED="${TEARDOWN_TARGET_NODE_EXPECTED:-${PVE_ENV:-${TF_VAR_proxmox_node:-pve-test}}}"
if [[ "${TARGET_NODE_EXPECTED}" == "pve" ]]; then
  DEFAULT_WITH_SECRETS_WRAPPER="with-secrets-prod"
  DEFAULT_TARGET_PVE_HOST="${PVE_PROD_FQDN:-pve.gibbsgreatly.xyz}"
  DEFAULT_ENV_HINT=".env.pve"
elif [[ "${TARGET_NODE_EXPECTED}" == "pve-test" ]]; then
  DEFAULT_WITH_SECRETS_WRAPPER="with-secrets"
  DEFAULT_TARGET_PVE_HOST="${PVE_TEST_FQDN:-pve-test.gibbsgreatly.xyz}"
  DEFAULT_ENV_HINT=".env.pve-test"
else
  DEFAULT_WITH_SECRETS_WRAPPER="with-secrets"
  DEFAULT_TARGET_PVE_HOST="${PVE_TEST_FQDN:-${TARGET_NODE_EXPECTED}.gibbsgreatly.xyz}"
  DEFAULT_ENV_HINT=".env.${TARGET_NODE_EXPECTED}"
fi
WITH_SECRETS="${TEARDOWN_WITH_SECRETS:-${REPO_ROOT}/${DEFAULT_WITH_SECRETS_WRAPPER}}"
TERRAGRUNT_WORKSPACE="${TEARDOWN_TERRAGRUNT_WORKSPACE:-${TARGET_NODE_EXPECTED}}"
TARGET_PVE_HOST="${TEARDOWN_PVE_HOST:-${DEFAULT_TARGET_PVE_HOST}}"
TARGET_ENV_FILE="${TEARDOWN_ENV_FILE:-${REPO_ROOT}/${DEFAULT_ENV_HINT}}"
REQUIRED_APPROVAL_PHRASE="${TEARDOWN_REQUIRED_APPROVAL_PHRASE:-approve}"
APPROVAL_TEXT=""
APPROVAL_PACKET=""
EXECUTE=false
DISPOSABLE=false
REQUIRE_CLEAN=false
PHASE=""
STAMP="${TEARDOWN_TEST_STAMP:-$(date -u +%Y%m%d-%H%M%S)}"
EVIDENCE_DIR="${EVIDENCE_ROOT}/${STAMP}"
LOG_DIR="${EVIDENCE_DIR}/logs"
RUN_LOG="${LOG_DIR}/teardown-deploy-test-${STAMP}.log"
STATE_FILE="${EVIDENCE_DIR}/state.json"
LOCK_FILE="${EVIDENCE_ROOT}/.harness.lock"
LOCK_HELD=false

TRACKED_PHASES=(
  "source-preflight"
  "live-preflight"
  "external-preflight"
  "approval-preflight"
  "preflight"
  "plan"
  "platform-status"
  "destroy"
  "deploy-foundation"
  "deploy-edge"
  "activate-edge"
  "deploy-platform"
  "final-validation"
  "cycle"
)

RESUME_PHASE_SEQUENCE=(
  "plan"
  "source-preflight"
  "live-preflight"
  "external-preflight"
  "approval-preflight"
  "destroy"
  "deploy-foundation"
  "deploy-edge"
  "activate-edge"
  "deploy-platform"
  "final-validation"
)

CURRENT_PHASE_NAME=""
CURRENT_PHASE_START_TIME=""
CURRENT_PHASE_END_TIME=""
CURRENT_PHASE_BRANCH=""
CURRENT_PHASE_COMMIT=""
CURRENT_PHASE_DIRTY="unknown"
CURRENT_PHASE_GIT_STATUS_LOG=""
CURRENT_PHASE_FAILURE_STEP=""
CURRENT_PHASE_FAILURE_COMMAND=""
CURRENT_PHASE_FAILURE_LOG=""
CURRENT_PHASE_FAILURE_MESSAGE=""
CURRENT_PHASE_STACK_SPECS=()

BROWSER_HOSTS=(
  "authentik"
  "harbor"
  "grafana"
  "portainer"
  "netbox"
  "traefik"
)

BREAKGLASS_DNS_HOSTS=(
  "authentik-bg"
  "harbor-bg"
  "monitoring-bg"
  "netbox-bg"
  "portainer-bg"
  "proxy-bg"
)

export LAB_IP_AUTHENTIK="${LAB_IP_AUTHENTIK:-}"
export LAB_IP_STEP_CA="${LAB_IP_STEP_CA:-}"
export LAB_IP_DNS="${LAB_IP_DNS:-}"
export LAB_IP_PORTAINER="${LAB_IP_PORTAINER:-}"
export LAB_IP_PROXY="${LAB_IP_PROXY:-}"
export LAB_GW_MGMT="${LAB_GW_MGMT:-}"
export LAB_DOMAIN="${LAB_DOMAIN:-lab.gibbsgreatly.xyz}"
export LAB_BASE_DOMAIN="${LAB_BASE_DOMAIN:-${LAB_DOMAIN}}"
export LAB_FQDN_TRAEFIK="${LAB_FQDN_TRAEFIK:-traefik.${LAB_DOMAIN}}"
export LAB_FQDN_GRAFANA="${LAB_FQDN_GRAFANA:-grafana.${LAB_DOMAIN}}"
export LAB_FQDN_NETBOX="${LAB_FQDN_NETBOX:-netbox.${LAB_DOMAIN}}"
export LAB_FQDN_HARBOR="${LAB_FQDN_HARBOR:-harbor.${LAB_DOMAIN}}"

# Runtime-generated deltas that can legitimately appear mid-cycle.
EXPECTED_RUNTIME_DIRTY_PATHS=(
  "certs/homelab-root.crt"
)

usage() {
  cat <<'EOF'
Usage:
  scripts/teardown-deploy-test.sh <phase> [options]

Phases:
  source-preflight    Run non-destructive source-only validation.
  live-preflight      Run non-destructive live read-only validation.
  external-preflight  Verify production SOPS secrets and external system connectivity (pve only).
  approval-preflight  Run clean-tree source + live preflight under one stamp.
  preflight           Backwards-compatible alias for source-preflight + live-preflight.
  plan                Show inventory-derived deploy/destroy stack plans.
  platform-status     Show read-only current stack/container state.
  status              Show checkpoint state and suggested next phase for a stamp.
  destroy             Destroy approved platform stacks in reverse order.
  deploy-foundation   Apply Stage 1/2 foundation stacks.
  deploy-edge         Apply Stage 3a edge foundation stacks.
  activate-edge       Reconcile Authentik and publish generated DNS/Traefik.
  deploy-platform     Apply remaining Stage 3b platform stacks.
  final-validation    Run live read-only end-to-end validation.
  cycle               Run destroy through final-validation in order.

Options:
  --execute
      Required for destroy, deploy-*, activate-edge, and cycle.
  --approval-text TEXT
      Required with --execute. Must contain: ${TEARDOWN_REQUIRED_APPROVAL_PHRASE:-approve}
  --approval-packet PATH
    Required for destroy and cycle unless --disposable is set.
    Must reference stamp/commit/backup approvals.
    --disposable
      Disposable environment mode for destroy/cycle.
      Skips approval-packet metadata validation, backup-artifact evidence checks,
      and the --approval-text gate. Use for pve-test dev iteration cycles.
  --stamp STAMP
      Use an existing/new evidence stamp instead of generating one.
  --require-clean
      Require a clean working tree for source/live preflight and final-validation.
  -h, --help
      Show this help.

Examples:
  scripts/teardown-deploy-test.sh source-preflight
  scripts/teardown-deploy-test.sh live-preflight
  scripts/teardown-deploy-test.sh approval-preflight
  scripts/teardown-deploy-test.sh preflight
  scripts/teardown-deploy-test.sh plan
  scripts/teardown-deploy-test.sh platform-status
  scripts/teardown-deploy-test.sh status --stamp 20260423-010203
  scripts/teardown-deploy-test.sh final-validation
  scripts/teardown-deploy-test.sh deploy-edge --execute \
    --approval-text "approve"
EOF
}

now_utc() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

git_current_branch() {
  git -C "${REPO_ROOT}" branch --show-current
}

git_current_commit() {
  git -C "${REPO_ROOT}" rev-parse HEAD
}

git_dirty_tree() {
  if [[ -n "$(git -C "${REPO_ROOT}" status --short)" ]]; then
    printf 'true\n'
  else
    printf 'false\n'
  fi
}

reset_phase_tracking_context() {
  CURRENT_PHASE_NAME=""
  CURRENT_PHASE_START_TIME=""
  CURRENT_PHASE_END_TIME=""
  CURRENT_PHASE_BRANCH=""
  CURRENT_PHASE_COMMIT=""
  CURRENT_PHASE_DIRTY="unknown"
  CURRENT_PHASE_GIT_STATUS_LOG=""
  CURRENT_PHASE_FAILURE_STEP=""
  CURRENT_PHASE_FAILURE_COMMAND=""
  CURRENT_PHASE_FAILURE_LOG=""
  CURRENT_PHASE_FAILURE_MESSAGE=""
  CURRENT_PHASE_STACK_SPECS=()
}

capture_phase_context_defaults() {
  CURRENT_PHASE_BRANCH="$(git_current_branch)"
  CURRENT_PHASE_COMMIT="$(git_current_commit)"
  CURRENT_PHASE_DIRTY="$(git_dirty_tree)"
}

set_phase_failure_context() {
  local step="$1"
  local command="$2"
  local log_path="$3"
  local message="$4"

  CURRENT_PHASE_FAILURE_STEP="${step}"
  CURRENT_PHASE_FAILURE_COMMAND="${command}"
  CURRENT_PHASE_FAILURE_LOG="${log_path}"
  CURRENT_PHASE_FAILURE_MESSAGE="${message}"
}

clear_phase_failure_context() {
  CURRENT_PHASE_FAILURE_STEP=""
  CURRENT_PHASE_FAILURE_COMMAND=""
  CURRENT_PHASE_FAILURE_LOG=""
  CURRENT_PHASE_FAILURE_MESSAGE=""
}

init_state_file() {
  local tracked_phases resume_sequence

  mkdir -p "${EVIDENCE_DIR}" "${LOG_DIR}"
  tracked_phases="$(printf '%s\n' "${TRACKED_PHASES[@]}")"
  resume_sequence="$(printf '%s\n' "${RESUME_PHASE_SEQUENCE[@]}")"

  STATE_TRACKED_PHASES="${tracked_phases}" \
  STATE_RESUME_SEQUENCE="${resume_sequence}" \
  STATE_FILE_PATH="${STATE_FILE}" \
  STATE_STAMP="${STAMP}" \
  STATE_EVIDENCE_DIR="${EVIDENCE_DIR}" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

state_path = Path(os.environ["STATE_FILE_PATH"])
tracked_phases = [line for line in os.environ.get("STATE_TRACKED_PHASES", "").splitlines() if line]
resume_sequence = [line for line in os.environ.get("STATE_RESUME_SEQUENCE", "").splitlines() if line]

if state_path.exists():
    data = json.loads(state_path.read_text(encoding="utf-8"))
else:
    data = {}

data["stamp"] = os.environ["STATE_STAMP"]
data["state_file"] = str(state_path)
data["evidence_dir"] = os.environ["STATE_EVIDENCE_DIR"]
data["phase_order"] = tracked_phases
data["resume_phase_sequence"] = resume_sequence
data["updated_at"] = None
phases = data.setdefault("phases", {})

for phase in tracked_phases:
    entry = phases.setdefault(phase, {})
    entry.setdefault("phase", phase)
    entry.setdefault("status", "pending")
    entry.setdefault("start_time", None)
    entry.setdefault("end_time", None)
    entry.setdefault("exit_status", None)
    entry.setdefault("evidence_dir", os.environ["STATE_EVIDENCE_DIR"])
    entry.setdefault("log_paths", [])
    entry.setdefault("stack_specs", [])
    entry.setdefault("branch", None)
    entry.setdefault("commit", None)
    entry.setdefault("dirty_tree", None)
    entry.setdefault("failure", None)

state_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_current_phase_state() {
  local status="$1"
  local exit_status="${2:-}"
  local stack_specs=""

  if [[ -n "${CURRENT_PHASE_NAME}" && ${#CURRENT_PHASE_STACK_SPECS[@]} -gt 0 ]]; then
    stack_specs="$(printf '%s\n' "${CURRENT_PHASE_STACK_SPECS[@]}")"
  fi

  STATE_FILE_PATH="${STATE_FILE}" \
  STATE_STAMP="${STAMP}" \
  STATE_PHASE="${CURRENT_PHASE_NAME}" \
  STATE_STATUS="${status}" \
  STATE_START_TIME="${CURRENT_PHASE_START_TIME}" \
  STATE_END_TIME="${CURRENT_PHASE_END_TIME}" \
  STATE_EXIT_STATUS="${exit_status}" \
  STATE_EVIDENCE_DIR="${EVIDENCE_DIR}" \
  STATE_LOG_DIR="${LOG_DIR}" \
  STATE_RUN_LOG="${RUN_LOG}" \
  STATE_BRANCH="${CURRENT_PHASE_BRANCH}" \
  STATE_COMMIT="${CURRENT_PHASE_COMMIT}" \
  STATE_DIRTY="${CURRENT_PHASE_DIRTY}" \
  STATE_GIT_STATUS_LOG="${CURRENT_PHASE_GIT_STATUS_LOG}" \
  STATE_STACK_SPECS="${stack_specs}" \
  STATE_FAILURE_STEP="${CURRENT_PHASE_FAILURE_STEP}" \
  STATE_FAILURE_COMMAND="${CURRENT_PHASE_FAILURE_COMMAND}" \
  STATE_FAILURE_LOG="${CURRENT_PHASE_FAILURE_LOG}" \
  STATE_FAILURE_MESSAGE="${CURRENT_PHASE_FAILURE_MESSAGE}" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

state_path = Path(os.environ["STATE_FILE_PATH"])
data = json.loads(state_path.read_text(encoding="utf-8"))
phase = os.environ["STATE_PHASE"]
status = os.environ["STATE_STATUS"]
log_dir = Path(os.environ["STATE_LOG_DIR"])
run_log = Path(os.environ["STATE_RUN_LOG"])

entry = data.setdefault("phases", {}).setdefault(phase, {"phase": phase})
log_paths = []
if log_dir.exists():
    log_paths.extend(str(path.resolve()) for path in sorted(log_dir.glob("*.log")))
if run_log.exists() and str(run_log.resolve()) not in log_paths:
    log_paths.append(str(run_log.resolve()))

dirty_value = os.environ.get("STATE_DIRTY", "unknown")
dirty_flag = None
dirty_status = "unknown"
if dirty_value == "true":
    dirty_flag = True
    dirty_status = "dirty"
elif dirty_value == "false":
    dirty_flag = False
    dirty_status = "clean"

failure = None
failure_step = os.environ.get("STATE_FAILURE_STEP", "")
failure_command = os.environ.get("STATE_FAILURE_COMMAND", "")
failure_log = os.environ.get("STATE_FAILURE_LOG", "")
failure_message = os.environ.get("STATE_FAILURE_MESSAGE", "")
if any([failure_step, failure_command, failure_log, failure_message]):
    failure = {
        "step": failure_step or None,
        "command": failure_command or None,
        "log_path": failure_log or None,
        "message": failure_message or None,
    }

stack_specs = [line for line in os.environ.get("STATE_STACK_SPECS", "").splitlines() if line]
exit_status_raw = os.environ.get("STATE_EXIT_STATUS", "")
entry.update(
    {
        "phase": phase,
        "status": status,
        "start_time": os.environ.get("STATE_START_TIME") or entry.get("start_time"),
        "end_time": os.environ.get("STATE_END_TIME") or None,
        "exit_status": int(exit_status_raw) if exit_status_raw else None,
        "evidence_dir": os.environ["STATE_EVIDENCE_DIR"],
        "log_paths": log_paths,
        "stack_specs": stack_specs,
        "branch": os.environ.get("STATE_BRANCH") or None,
        "commit": os.environ.get("STATE_COMMIT") or None,
        "dirty_tree": {
            "status": dirty_status,
            "dirty": dirty_flag,
            "status_log": os.environ.get("STATE_GIT_STATUS_LOG") or None,
        },
        "failure": failure,
    }
)

data["updated_at"] = os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip() or None
data["last_phase"] = phase
data["branch"] = entry["branch"]
data["commit"] = entry["commit"]
data["dirty_tree"] = entry["dirty_tree"]

state_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

refresh_current_phase_state() {
  if [[ -z "${CURRENT_PHASE_NAME}" ]]; then
    return
  fi

  write_current_phase_state "running"
}

set_current_phase_stack_specs() {
  CURRENT_PHASE_STACK_SPECS=("$@")
  refresh_current_phase_state
}

phase_error_trap() {
  local status="$1"

  CURRENT_PHASE_END_TIME="$(now_utc)"
  if [[ -z "${CURRENT_PHASE_FAILURE_STEP}" ]]; then
    set_phase_failure_context \
      "${CURRENT_PHASE_NAME}" \
      "scripts/teardown-deploy-test.sh ${CURRENT_PHASE_NAME}" \
      "${RUN_LOG}" \
      "Phase ${CURRENT_PHASE_NAME} failed"
  fi
  write_current_phase_state "failed" "${status}"
  write_phase_summary "${CURRENT_PHASE_NAME}" "failed"
  exit "${status}"
}

write_phase_summary() {
  local phase_name="${1:-${CURRENT_PHASE_NAME}}"
  local phase_status="${2:-unknown}"
  local summary_file="${EVIDENCE_DIR}/summary-${phase_name}.md"

  STATE_FILE_PATH="${STATE_FILE}" \
  SUMMARY_PHASE="${phase_name}" \
  SUMMARY_STATUS="${phase_status}" \
  SUMMARY_FILE="${summary_file}" \
  python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["STATE_FILE_PATH"])
phase = os.environ["SUMMARY_PHASE"]
summary_file = Path(os.environ["SUMMARY_FILE"])

if not state_path.exists():
    print(f"[write_phase_summary] state file not found: {state_path}", file=sys.stderr)
    sys.exit(0)

data = json.loads(state_path.read_text(encoding="utf-8"))
entry = data.get("phases", {}).get(phase, {})

status = entry.get("status", os.environ.get("SUMMARY_STATUS", "unknown"))
branch = entry.get("branch") or data.get("branch") or "unknown"
commit_full = entry.get("commit") or data.get("commit") or "unknown"
commit = commit_full[:12] if commit_full and commit_full != "unknown" else commit_full
start_time = entry.get("start_time") or "—"
end_time = entry.get("end_time") or "—"
stamp = data.get("stamp", "unknown")
log_paths = entry.get("log_paths", [])
failure = entry.get("failure") or {}
dirty_info = entry.get("dirty_tree") or {}
dirty_status = dirty_info.get("status", "unknown")

status_badge = {"passed": "PASSED", "failed": "FAILED"}.get(status, status.upper())

lines = [
    f"# Phase: {phase} — {status_badge}",
    "",
    f"**Stamp:** {stamp}  ",
    f"**Branch:** {branch}  ",
    f"**Commit:** {commit}  ",
    f"**Tree:** {dirty_status}  ",
    f"**Started:** {start_time}  ",
    f"**Ended:** {end_time}  ",
    "",
    f"## Result: {status_badge}",
    "",
]

if log_paths:
    lines.append("## Logs")
    for lp in log_paths:
        lines.append(f"- `{Path(lp).name}`")
    lines.append("")

if failure and any(failure.values()):
    lines.append("## Failure")
    if failure.get("step"):
        lines.append(f"**Step:** {failure['step']}  ")
    if failure.get("message"):
        lines.append(f"**Message:** {failure['message']}  ")
    if failure.get("log_path"):
        lines.append(f"**Log:** `{Path(failure['log_path']).name}`  ")
    lines.append("")
else:
    lines.append("## Deviations")
    lines.append("None.")
    lines.append("")

summary_file.parent.mkdir(parents=True, exist_ok=True)
summary_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"[summary] written: {summary_file}")
PY
}

run_phase_handler() {
  local phase_name="$1"
  local handler="$2"

  (
    set -Eeuo pipefail
    trap 'phase_error_trap "$?"' ERR

    reset_phase_tracking_context
    CURRENT_PHASE_NAME="${phase_name}"
    CURRENT_PHASE_START_TIME="$(now_utc)"
    capture_phase_context_defaults
    init_state_file
    write_current_phase_state "running"

    "${handler}"

    trap - ERR
    CURRENT_PHASE_END_TIME="$(now_utc)"
    clear_phase_failure_context
    write_current_phase_state "passed" "0"
    write_phase_summary "${phase_name}" "passed"
  )
}

log() {
  local message="$*"
  mkdir -p "${LOG_DIR}"
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${message}" | tee -a "${RUN_LOG}"
}

run_logged() {
  local name="$1"
  shift
  local logfile="${LOG_DIR}/${name}.log"
  local command_text

  mkdir -p "${LOG_DIR}"
  command_text="$*"
  log "START ${name}: ${command_text}"
  if "$@" >"${logfile}" 2>&1; then
    log "PASS ${name}: ${logfile}"
  else
    local status=$?
    log "FAIL ${name}: ${logfile}"
    set_phase_failure_context "${name}" "${command_text}" "${logfile}" "Command failed with exit status ${status}"
    return "${status}"
  fi
}

run_dns_answer_check() {
  local name="$1"
  local resolver="$2"
  local fqdn="$3"
  local expected_answer="$4"

  # shellcheck disable=SC2016
  run_logged "${name}" \
    bash -lc '
      set -euo pipefail

      resolver="$1"
      fqdn="$2"
      expected_answer="$3"

      mapfile -t answers < <(dig "@${resolver}" +short "${fqdn}" | sed "/^[[:space:]]*$/d")

      if (( ${#answers[@]} == 0 )); then
        observed="<empty>"
      else
        observed="$(printf "%s\n" "${answers[@]}" | paste -sd "," -)"
      fi

      printf "resolver=%s\n" "${resolver}"
      printf "fqdn=%s\n" "${fqdn}"
      printf "expected=%s\n" "${expected_answer}"
      printf "observed=%s\n" "${observed}"

      if (( ${#answers[@]} != 1 )) || [[ "${answers[0]}" != "${expected_answer}" ]]; then
        printf "DNS assertion failed for %s via %s: expected exactly %s, observed %s\n" \
          "${fqdn}" "${resolver}" "${expected_answer}" "${observed}" >&2
        exit 1
      fi

      printf "DNS assertion passed for %s via %s\n" "${fqdn}" "${resolver}"
    ' _ "${resolver}" "${fqdn}" "${expected_answer}"
}

run_dns_nonempty_check() {
  local name="$1"
  local resolver="$2"
  local fqdn="$3"

  # shellcheck disable=SC2016
  run_logged "${name}" \
    bash -lc '
      set -euo pipefail

      resolver="$1"
      fqdn="$2"

      mapfile -t answers < <(dig "@${resolver}" +short "${fqdn}" | sed "/^[[:space:]]*$/d")

      if (( ${#answers[@]} == 0 )); then
        printf "resolver=%s\n" "${resolver}"
        printf "fqdn=%s\n" "${fqdn}"
        printf "observed=<empty>\n"
        printf "DNS assertion failed for %s via %s: expected at least one answer\n" \
          "${fqdn}" "${resolver}" >&2
        exit 1
      fi

      printf "resolver=%s\n" "${resolver}"
      printf "fqdn=%s\n" "${fqdn}"
      printf "observed=%s\n" "$(printf "%s\n" "${answers[@]}" | paste -sd "," -)"
      printf "DNS assertion passed for %s via %s (non-empty)\n" "${fqdn}" "${resolver}"
    ' _ "${resolver}" "${fqdn}"
}

guard_target() {
  local output
  # shellcheck disable=SC2016
  output="$("${WITH_SECRETS}" printenv TF_VAR_proxmox_node)"
  if [[ "${output}" != "${TARGET_NODE_EXPECTED}" ]]; then
    log "ERROR target guard returned '${output}', expected ${TARGET_NODE_EXPECTED}"
    set_phase_failure_context \
      "target-guard" \
      "${WITH_SECRETS} printenv TF_VAR_proxmox_node" \
      "${RUN_LOG}" \
      "target guard returned '${output}', expected ${TARGET_NODE_EXPECTED}"
    return 1
  fi
  log "target guard passed: ${output}"
}

require_clean_tree() {
  local allowed_path
  local line path
  local path_allowed
  local -a status_lines=()
  local -a allowed_lines=()
  local -a disallowed_lines=()

  mapfile -t status_lines < <(git -C "${REPO_ROOT}" status --short)
  if [[ ${#status_lines[@]} -eq 0 ]]; then
    return 0
  fi

  for line in "${status_lines[@]}"; do
    path="${line:3}"
    if [[ "${path}" == *" -> "* ]]; then
      path="${path##* -> }"
    fi

    path_allowed=false
    if [[ "${PHASE}" == "cycle" || "${PHASE}" == "activate-edge" || "${PHASE}" == "deploy-platform" ]]; then
      for allowed_path in "${EXPECTED_RUNTIME_DIRTY_PATHS[@]}"; do
        if [[ "${path}" == "${allowed_path}" ]]; then
          path_allowed=true
          break
        fi
      done
    fi

    if [[ "${path_allowed}" == "true" ]]; then
      allowed_lines+=("${line}")
    else
      disallowed_lines+=("${line}")
    fi
  done

  if [[ ${#disallowed_lines[@]} -gt 0 ]]; then
    log "ERROR working tree is dirty"
    printf '%s\n' "${status_lines[@]}" | tee -a "${RUN_LOG}" >&2
    set_phase_failure_context \
      "require-clean-tree" \
      "git -C ${REPO_ROOT} status --short" \
      "${CURRENT_PHASE_GIT_STATUS_LOG:-${RUN_LOG}}" \
      "working tree is dirty"
    return 1
  fi

  {
    printf '[%s] WARNING allowing expected runtime-generated change(s) during %s:\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${PHASE}"
    printf '%s\n' "${allowed_lines[@]}"
  } | tee -a "${RUN_LOG}" >&2
}

record_working_tree_state() {
  git -C "${REPO_ROOT}" status --short >"${LOG_DIR}/git-status-short.log"
  CURRENT_PHASE_GIT_STATUS_LOG="${LOG_DIR}/git-status-short.log"
  if [[ -s "${LOG_DIR}/git-status-short.log" ]]; then
    CURRENT_PHASE_DIRTY="true"
    log "working tree has local changes; see ${LOG_DIR}/git-status-short.log"
    refresh_current_phase_state
    if [[ "${REQUIRE_CLEAN}" == "true" ]]; then
      log "ERROR --require-clean was set"
      set_phase_failure_context \
        "record-working-tree-state" \
        "git -C ${REPO_ROOT} status --short" \
        "${LOG_DIR}/git-status-short.log" \
        "--require-clean was set"
      return 1
    fi
  else
    CURRENT_PHASE_DIRTY="false"
    log "working tree clean"
    refresh_current_phase_state
  fi
}

record_branch_and_commit() {
  local branch commit

  branch="$(git -C "${REPO_ROOT}" branch --show-current)"
  commit="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
  CURRENT_PHASE_BRANCH="${branch}"
  CURRENT_PHASE_COMMIT="${commit}"

  printf '%s\n' "${branch}" >"${LOG_DIR}/branch.log"
  printf '%s\n' "${commit}" >"${LOG_DIR}/commit.log"

  log "branch=${branch}"
  log "commit=${commit}"
  refresh_current_phase_state
}

assert_traefik_render_output() {
  local logfile="$1"
  local status=0

  python3 - "${logfile}" <<'PY' || status=$?
import json
import os
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
payload = json.loads(log_path.read_text(encoding="utf-8"))
stack_count = int(payload.get("stack_count", 0))
files = payload.get("files", [])

if stack_count <= 0:
    raise SystemExit("Traefik render produced zero stack files")
if len(files) < stack_count:
    raise SystemExit(
        f"Traefik render reported {stack_count} stack files but listed {len(files)} output paths"
    )

missing = []
empty = []
for item in files:
    path = Path(item)
    if not path.is_file():
        missing.append(str(path))
    elif path.stat().st_size == 0:
        empty.append(str(path))

if missing:
    raise SystemExit("Missing rendered Traefik files: " + ", ".join(missing))
if empty:
    raise SystemExit("Empty rendered Traefik files: " + ", ".join(empty))
PY

  if [[ "${status}" -ne 0 ]]; then
    set_phase_failure_context \
      "assert-traefik-render-output" \
      "python3 <traefik-render-output-assertion> ${logfile}" \
      "${logfile}" \
      "Traefik render output assertion failed"
    return "${status}"
  fi
}

assert_coredns_render_output() {
  local logfile="$1"
  local status=0

  python3 - "${logfile}" <<'PY' || status=$?
import json
import os
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
payload = json.loads(log_path.read_text(encoding="utf-8"))
record_count = int(payload.get("generated_record_count", 0))
output_zone = Path(payload.get("output_zone", ""))

if record_count <= 0:
    raise SystemExit("CoreDNS render produced zero generated records")
if not output_zone.is_file():
    raise SystemExit(f"Rendered CoreDNS zone missing: {output_zone}")

rendered_zone = output_zone.read_text(encoding="utf-8")
if "Generated browser edge records" not in rendered_zone:
    raise SystemExit("Rendered CoreDNS zone is missing generated browser record section")
expected_target = os.environ.get("LAB_IP_PROXY", "")
if not expected_target:
    raise SystemExit("LAB_IP_PROXY is not set — source your environment file before running")
if expected_target not in rendered_zone:
    raise SystemExit(f"Rendered CoreDNS zone is missing the expected {expected_target} target")
PY

  if [[ "${status}" -ne 0 ]]; then
    set_phase_failure_context \
      "assert-coredns-render-output" \
      "python3 <coredns-render-output-assertion> ${logfile}" \
      "${logfile}" \
      "CoreDNS render output assertion failed"
    return "${status}"
  fi
}

resolve_stack_specs() {
  local group="$1"

  bash -lc "set -a && source '${REPO_ROOT}/.env' && source '${TARGET_ENV_FILE}' && python3 - '${group}' '${INVENTORY_FILE}' '${TERRAFORM_LXC}'" <<'PY'
import os
import re
import sys
from pathlib import Path

group = sys.argv[1]
inventory_path = Path(sys.argv[2])
terraform_lxc = Path(sys.argv[3])

if not inventory_path.is_file():
    raise SystemExit(f"inventory file not found: {inventory_path}")

inventory_text = inventory_path.read_text(encoding="utf-8")
stack_rows: dict[str, dict[str, str]] = {}
deploy_order: list[str] = []
destroy_order: list[str] = []


def clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def normalize_ip(value: str) -> str:
    return clean_cell(value).split("/", 1)[0]


PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_stack_placeholders(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        candidates = (name, name.upper(), f"TF_VAR_{name}")
        for candidate in candidates:
            value = os.environ.get(candidate)
            if value:
                return value
        return match.group(0)

    return PLACEHOLDER_PATTERN.sub(replace, text)


def parse_stack_table(text: str) -> None:
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Stack | Stage | VMID | IP |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            break

        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        stack = clean_cell(cells[0])
        stack_rows[stack] = {
            "stage": clean_cell(cells[1]),
            "vmid": clean_cell(cells[2]),
            "ip": normalize_ip(cells[3]),
        }


def parse_order_section(text: str, header: str) -> list[str]:
    pattern = re.compile(rf"^## {re.escape(header)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"missing inventory section: {header}")

    order: list[str] = []
    for line in text[match.end():].splitlines():
        if line.startswith("## "):
            break
        item = re.match(r"\d+\.\s+`([^`]+)`", line)
        if item:
            order.append(item.group(1))
    return order


def read_stack_yaml(stack: str) -> tuple[str, str]:
  stack_yaml = terraform_lxc / "stacks" / stack / "stack.yaml"
  if not stack_yaml.is_file():
    raise SystemExit(f"missing stack.yaml for inventory stack {stack}: {stack_yaml}")

  text = expand_stack_placeholders(stack_yaml.read_text(encoding="utf-8"))
  vmid_match = re.search(r"(?m)^vmid:\s*([0-9]+)\s*$", text)
  ip_match = re.search(r'(?m)^ip_address:\s*"?([^"\n]+)"?\s*$', text)
  if not vmid_match or not ip_match:
    raise SystemExit(f"stack.yaml missing vmid or ip_address: {stack_yaml}")
  return vmid_match.group(1), normalize_ip(ip_match.group(1))


parse_stack_table(inventory_text)
deploy_order = parse_order_section(inventory_text, "Approved Deploy Order")
destroy_order = parse_order_section(inventory_text, "Approved Destroy Order")

if not stack_rows:
    raise SystemExit("no stack rows parsed from inventory")

for stack, metadata in stack_rows.items():
    source_vmid, source_ip = read_stack_yaml(stack)
    if metadata["vmid"] != source_vmid or metadata["ip"] != source_ip:
        raise SystemExit(
            "inventory mismatch for "
            f"{stack}: inventory vmid/ip={metadata['vmid']}/{metadata['ip']}, "
            f"stack.yaml vmid/ip={source_vmid}/{source_ip}"
        )


def selected_order() -> list[str]:
    if group == "foundation":
        return [
            stack
            for stack in deploy_order
            if stack_rows.get(stack, {}).get("stage") == "Stage 1/2 foundation"
        ]
    if group == "edge":
        return [
            stack
            for stack in deploy_order
            if stack_rows.get(stack, {}).get("stage") == "Stage 3a edge foundation"
        ]
    if group == "platform":
        return [
            stack
            for stack in deploy_order
            if stack_rows.get(stack, {}).get("stage") == "Stage 3b platform"
        ]
    if group == "all":
        return deploy_order
    if group == "destroy":
        return destroy_order
    raise SystemExit(f"unknown stack group: {group}")


order = selected_order()
if not order:
    raise SystemExit(f"resolved empty stack order for group: {group}")

missing = [stack for stack in order if stack not in stack_rows]
if missing:
    raise SystemExit("order references stacks missing from inventory table: " + ", ".join(missing))

for stack in order:
    metadata = stack_rows[stack]
    print(f"{stack}:{metadata['vmid']}:{metadata['ip']}")
PY
}

log_stack_plan() {
  local group="$1"
  shift

  log "resolved ${group} stack order from ${INVENTORY_FILE}:"
  printf '%s\n' "$@" | tee -a "${RUN_LOG}"
}

stack_uses_explicit_storage_contract() {
  local stack="$1"
  local stack_yaml="${REPO_ROOT}/terraform/lxc/stacks/${stack}/stack.yaml"

  [[ -f "${stack_yaml}" ]] || return 1
  grep -Eq '^(docker_mount|extra_mount):' "${stack_yaml}"
}

review_storage_plan_safety() {
  local spec="$1"
  local stack planfile planjson classified

  stack="$(stack_name "${spec}")"
  if ! stack_uses_explicit_storage_contract "${stack}"; then
    log "skip storage-plan-review-${stack}: stack does not declare explicit storage contract"
    return 0
  fi

  planfile="${LOG_DIR}/${stack}-storage.tfplan"
  planjson="${LOG_DIR}/${stack}-storage.plan.json"
  classified="${LOG_DIR}/${stack}-storage.classified.json"

  run_logged "storage-plan-${stack}" \
    bash -lc "cd '${REPO_ROOT}/terraform/lxc/stacks/${stack}' && '${WITH_SECRETS}' env TF_WORKSPACE='${TERRAGRUNT_WORKSPACE}' terragrunt plan -target=module.lxc -out='${planfile}' -no-color"
  run_logged "storage-plan-json-${stack}" \
    bash -lc "cd '${REPO_ROOT}/terraform/lxc/stacks/${stack}' && '${WITH_SECRETS}' env TF_WORKSPACE='${TERRAGRUNT_WORKSPACE}' terragrunt show -json '${planfile}' >'${planjson}'"
  run_logged "storage-plan-classify-${stack}" \
    python3 "${TERRAFORM_LXC}/classify-storage-plan.py" --plan-json "${planjson}" --stack-name "${stack}" --out "${classified}"
  run_logged "storage-plan-safety-${stack}" \
    python3 "${TERRAFORM_LXC}/check-plan-safety.py" --plan-json "${planjson}"
}

run_storage_classifier_regression_checks() {
  local nonstorage_plan="${LOG_DIR}/storage-plan-nonstorage-fixture.json"
  local unsafe_log="${LOG_DIR}/storage-plan-known-unsafe.log"

  cat >"${nonstorage_plan}" <<'EOF'
{
  "resource_changes": [
    {
      "address": "module.lxc.proxmox_virtual_environment_container.docker_host",
      "change": {
        "actions": ["update"],
        "before": {"memory": {"dedicated": 1024}},
        "after": {"memory": {"dedicated": 2048}}
      }
    }
  ]
}
EOF

  run_logged "storage-plan-safety-nonstorage-fixture" \
    python3 "${TERRAFORM_LXC}/check-plan-safety.py" --plan-json "${nonstorage_plan}"
  run_logged "storage-plan-safety-known-unsafe" \
    bash -lc "if python3 '${TERRAFORM_LXC}/check-plan-safety.py' --plan-json '${REPO_ROOT}/docs/storage-refactor/fixtures/fixture-docker-grow-plan.json' >'${unsafe_log}' 2>&1; then echo 'expected unsafe storage fixture to fail' >&2; exit 1; else status=\$?; cat '${unsafe_log}'; [[ \"\${status}\" -eq 2 ]]; fi"
}

load_stack_specs() {
  local group="$1"
  local target_name="$2"
  local output

  if ! output="$(resolve_stack_specs "${group}")"; then
    local status=$?
    set_phase_failure_context \
      "resolve-${group}-stack-specs" \
      "resolve_stack_specs ${group}" \
      "${RUN_LOG}" \
      "Failed to resolve ${group} stack specs"
    return "${status}"
  fi

  if [[ -z "${output}" ]]; then
    log "ERROR resolved empty stack order for group: ${group}"
    set_phase_failure_context \
      "resolve-${group}-stack-specs" \
      "resolve_stack_specs ${group}" \
      "${RUN_LOG}" \
      "Resolved empty stack order for group: ${group}"
    return 1
  fi

  # shellcheck disable=SC2178
  local -n target="${target_name}"
  # shellcheck disable=SC2034
  mapfile -t target <<<"${output}"
}

get_authentik_url() {
  printf 'https://authentik-int.%s:9443\n' "${LAB_DOMAIN}"
  return 0
}

hydrate_live_env_contract() {
  local key value
  local vars=(
    LAB_IP_AUTHENTIK
    LAB_IP_STEP_CA
    LAB_IP_DNS
    LAB_IP_PORTAINER
    LAB_IP_PROXY
    LAB_GW_MGMT
  )

  for key in "${vars[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      continue
    fi

    value="$("${WITH_SECRETS}" printenv "${key}" || true)"
    if [[ -n "${value}" ]]; then
      printf -v "${key}" '%s' "${value}"
      export "${key}=${value}"
    fi
  done
}

require_live_env_contract() {
  local missing=()
  local vars=(
    LAB_IP_AUTHENTIK
    LAB_IP_STEP_CA
    LAB_IP_DNS
    LAB_IP_PORTAINER
    LAB_IP_PROXY
    LAB_GW_MGMT
  )

  hydrate_live_env_contract

  for key in "${vars[@]}"; do
    if [[ -z "${!key:-}" ]]; then
      missing+=("${key}")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi

  log "ERROR Missing required live-validation environment variable(s): $(IFS=,; echo "${missing[*]}"). Source your environment first (for example: source .env && source ${DEFAULT_ENV_HINT}). source-preflight is source-only and does not require these values."
  set_phase_failure_context \
    "live-env-contract" \
    "require_live_env_contract" \
    "${RUN_LOG}" \
    "Missing required live-validation environment variable(s): $(IFS=,; echo "${missing[*]}")"
  return 1
}

wait_for_authentik_api_ready() {
  local authentik_url="$1"
  local max_attempts="24"
  local delay_seconds="5"

  # shellcheck disable=SC2016
  run_logged "wait-authentik-api-ready" \
    "${WITH_SECRETS}" bash -lc '
      set -euo pipefail

      authentik_url="$1"
      max_attempts="$2"
      delay_seconds="$3"
      endpoint="${authentik_url%/}/api/v3/core/applications/?page_size=1"
      token="${AUTHENTIK_SUPERUSER_API_TOKEN:-}"

      if [[ -z "${token}" ]]; then
        echo "AUTHENTIK_SUPERUSER_API_TOKEN is not set" >&2
        exit 1
      fi

      for attempt in $(seq 1 "${max_attempts}"); do
        code="$(curl -sk -o /tmp/authentik-api-ready.json -w "%{http_code}" \
          -H "Authorization: Bearer ${token}" \
          -H "Accept: application/json" \
          "${endpoint}" || true)"
        echo "attempt=${attempt} http_code=${code} endpoint=${endpoint}"

        if [[ "${code}" == "200" ]]; then
          exit 0
        fi

        if [[ "${attempt}" -lt "${max_attempts}" ]]; then
          sleep "${delay_seconds}"
        fi
      done

      echo "Authentik API token-auth probe did not return 200 after ${max_attempts} attempts" >&2
      exit 1
    ' _ "${authentik_url}" "${max_attempts}" "${delay_seconds}"
}

acquire_harness_lock() {
  mkdir -p "${EVIDENCE_ROOT}"
  if [[ -f "${LOCK_FILE}" ]]; then
    local existing_pid existing_stamp
    existing_pid="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('pid',''))" "${LOCK_FILE}" 2>/dev/null || true)"
    existing_stamp="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('stamp',''))" "${LOCK_FILE}" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
      printf '[harness] ERROR: another harness run is active (PID %s, stamp %s)\n' \
        "${existing_pid}" "${existing_stamp}" >&2
      printf '[harness] Lock file: %s\n' "${LOCK_FILE}" >&2
      printf '[harness] If the other process is no longer running, remove the lock file and retry.\n' >&2
      return 1
    fi
    printf '[harness] WARNING: stale lock file (PID %s no longer running); removing.\n' "${existing_pid}" >&2
    rm -f "${LOCK_FILE}"
  fi
  python3 -c "
import json, os, sys
data = {
    'stamp': sys.argv[1],
    'pid': str(os.getppid()),
    'branch': sys.argv[2],
    'commit': sys.argv[3],
}
print(json.dumps(data))
" "${STAMP}" "$(git_current_branch)" "$(git_current_commit)" > "${LOCK_FILE}"
  LOCK_HELD=true
  printf '[harness] lock acquired: %s\n' "${LOCK_FILE}" >&2
}

release_harness_lock() {
  if [[ "${LOCK_HELD}" == "true" ]]; then
    rm -f "${LOCK_FILE}"
    LOCK_HELD=false
    printf '[harness] lock released\n' >&2
  fi
}

require_execute_approval() {
  local approval_lc
  approval_lc="${APPROVAL_TEXT,,}"

  if [[ "${EXECUTE}" != "true" ]]; then
    log "ERROR ${PHASE} requires --execute"
    set_phase_failure_context \
      "require-execute" \
      "scripts/teardown-deploy-test.sh ${PHASE} --execute" \
      "${RUN_LOG}" \
      "${PHASE} requires --execute"
    return 1
  fi

  if [[ "${DISPOSABLE}" == "true" ]]; then
    log "disposable mode enabled; approval-text gate satisfied by --disposable"
    return 0
  fi

  if [[ "${approval_lc}" != *"${REQUIRED_APPROVAL_PHRASE,,}"* ]]; then
    log "ERROR ${PHASE} requires --approval-text containing: ${REQUIRED_APPROVAL_PHRASE}"
    set_phase_failure_context \
      "require-approval-text" \
      "scripts/teardown-deploy-test.sh ${PHASE} --approval-text <text>" \
      "${RUN_LOG}" \
      "${PHASE} requires approval text containing: ${REQUIRED_APPROVAL_PHRASE}"
    return 1
  fi

}

approval_packet_field_value() {
  local packet_path="$1"
  local field_regex="$2"

  awk -v field_regex="${field_regex}" '
    BEGIN { IGNORECASE = 1 }
    $0 ~ "^[[:space:]]*" field_regex "[[:space:]]*:[[:space:]]*" {
      sub("^[[:space:]]*" field_regex "[[:space:]]*:[[:space:]]*", "", $0)
      print $0
      exit
    }
  ' "${packet_path}" || true
}

approval_packet_has_heading() {
  local packet_path="$1"
  local heading_regex="$2"

  grep -Eiq "^[[:space:]]*${heading_regex}[[:space:]]*:[[:space:]]*$" "${packet_path}"
}

approval_packet_has_backup_entry() {
  local packet_path="$1"
  local service_regex="$2"

  grep -Eiq "^[[:space:]]*-[[:space:]]*${service_regex}[[:space:]]+backup[[:space:]]+evidence[[:space:]]+path:[[:space:]]*[^[:space:]].*$" "${packet_path}"
}

approval_packet_has_data_loss_approval() {
  local packet_path="$1"

  grep -Eiq "^[[:space:]]*recreatable[[:space:]-]*services[[:space:]-]*approval[[:space:]]*:[[:space:]]*.+$" "${packet_path}" \
    && grep -Eiq "(data[[:space:]-]*loss|recreat|accept|acknowledg|allowed|approved)" "${packet_path}"
}

validate_approval_packet() {
  local packet_path
  local packet_hash_file
  local packet_sha
  local current_commit
  local packet_stamp
  local packet_target
  local packet_commit
  local outage_window
  local rollback_deadline
  local scope_approval
  local scope_exclusions
  local service
  local -a missing_items
  local -a non_loss_services=(
    "step-ca:step[- ]?ca"
    "authentik:authentik"
    "harbor:harbor"
    "netbox:netbox"
    "monitoring:monitoring"
    "portainer:portainer"
  )
  local -a recreatable_services=(
    "apt-cacher:apt[- ]?cacher"
    "ci-runner:ci[- ]?runner"
    "dns:dns"
    "proxy:proxy"
  )

  if [[ "${DISPOSABLE}" == "true" ]]; then
    log "disposable mode enabled; skipping approval packet validation"
    return 0
  fi

  if [[ -z "${APPROVAL_PACKET}" ]]; then
    log "ERROR ${PHASE} requires --approval-packet PATH"
    set_phase_failure_context \
      "require-approval-packet" \
      "scripts/teardown-deploy-test.sh ${PHASE} --approval-packet <path>" \
      "${RUN_LOG}" \
      "${PHASE} requires --approval-packet"
    return 1
  fi

  packet_path="$(realpath "${APPROVAL_PACKET}" 2>/dev/null || true)"
  if [[ -z "${packet_path}" || ! -f "${packet_path}" ]]; then
    log "ERROR approval packet not found: ${APPROVAL_PACKET}"
    set_phase_failure_context \
      "validate-approval-packet" \
      "test -f ${APPROVAL_PACKET}" \
      "${RUN_LOG}" \
      "approval packet not found"
    return 1
  fi

  current_commit="$(git_current_commit)"
  packet_stamp="$(approval_packet_field_value "${packet_path}" "stamp")"
  packet_target="$(approval_packet_field_value "${packet_path}" "target")"
  packet_commit="$(approval_packet_field_value "${packet_path}" "approved[[:space:]-]*commit([[:space:]_-]*sha)?")"
  outage_window="$(approval_packet_field_value "${packet_path}" "outage[[:space:]-]*window")"
  rollback_deadline="$(approval_packet_field_value "${packet_path}" "rollback[[:space:]-]*deadline")"
  scope_approval="$(approval_packet_field_value "${packet_path}" "scope[[:space:]-]*approval")"
  scope_exclusions="$(approval_packet_field_value "${packet_path}" "scope[[:space:]-]*exclusions")"

  if [[ -z "${packet_stamp}" ]]; then
    missing_items+=("stamp field (stamp: ${STAMP})")
  elif [[ "${packet_stamp}" != "${STAMP}" ]]; then
    missing_items+=("stamp field must match active --stamp (${STAMP})")
  fi

  if [[ -z "${packet_target}" ]]; then
    missing_items+=("target field (target: ${TARGET_NODE_EXPECTED})")
  elif [[ "${packet_target}" != "${TARGET_NODE_EXPECTED}" ]]; then
    missing_items+=("target field must equal ${TARGET_NODE_EXPECTED}")
  fi

  if [[ -z "${packet_commit}" ]]; then
    missing_items+=("approved commit SHA field")
  elif [[ ! "${packet_commit}" =~ ^[0-9a-f]{7,40}$ ]]; then
    missing_items+=("approved commit SHA must be 7-40 lowercase hex characters")
  elif [[ "${packet_commit}" != "${current_commit}" ]]; then
    missing_items+=("approved commit SHA must match current commit (${current_commit})")
  fi

  if [[ -z "${outage_window}" ]]; then
    missing_items+=("outage window field")
  fi

  if [[ -z "${rollback_deadline}" ]]; then
    missing_items+=("rollback deadline field")
  fi

  if [[ -z "${scope_approval}" ]]; then
    missing_items+=("scope approval field")
  fi

  if [[ -z "${scope_exclusions}" ]]; then
    missing_items+=("scope exclusions field")
  fi

  if ! approval_packet_has_heading "${packet_path}" "service[[:space:]-]*evidence"; then
    missing_items+=("service evidence heading")
  fi

  for service in "${non_loss_services[@]}"; do
    local service_name="${service%%:*}"
    local service_pattern="${service#*:}"
    if ! approval_packet_has_backup_entry "${packet_path}" "${service_pattern}"; then
      missing_items+=("backup evidence reference for ${service_name}")
    fi
  done

  if ! approval_packet_has_data_loss_approval "${packet_path}"; then
    if ! approval_packet_has_heading "${packet_path}" "recreatable[[:space:]-]*services[[:space:]-]*evidence"; then
      missing_items+=("recreatable services evidence heading or recreatable services approval field")
    fi
    for service in "${recreatable_services[@]}"; do
      local service_name="${service%%:*}"
      local service_pattern="${service#*:}"
      if ! approval_packet_has_backup_entry "${packet_path}" "${service_pattern}"; then
        missing_items+=("recreatable service evidence reference for ${service_name}")
      fi
    done
  fi

  set +u
  if [[ ${#missing_items[@]} -gt 0 ]]; then
    set -u
    {
      log "ERROR approval packet validation failed: ${packet_path}"
      printf '[%s] Missing approval packet items:\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${RUN_LOG}"
      printf -- '- %s\n' "${missing_items[@]}" | tee -a "${RUN_LOG}"
    } >/dev/null
    set_phase_failure_context \
      "validate-approval-packet" \
      "validate_approval_packet ${packet_path}" \
      "${RUN_LOG}" \
      "approval packet missing required metadata"
    return 1
  fi
  set -u

  packet_hash_file="${LOG_DIR}/approval-packet.sha256"
  packet_sha="$(sha256sum "${packet_path}" | awk '{print $1}')"
  printf '%s  %s\n' "${packet_sha}" "${packet_path}" >"${packet_hash_file}"
  log "approval packet accepted: ${packet_path}"
  log "approval packet sha256: ${packet_sha} (recorded in ${packet_hash_file})"
}

backup_dir_has_artifact() {
  local dir="$1"
  find "${dir}" -mindepth 1 -type f | grep -q .
}

validate_backup_artifacts_present() {
  local backup_root="${EVIDENCE_DIR}/backups"
  local d
  local -a missing_dirs=()
  local -a missing_non_loss=()
  local -a required_dirs=(
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
  local -a non_loss_dirs=(
    "step-ca"
    "authentik"
    "harbor"
    "netbox"
  )

  if [[ "${DISPOSABLE}" == "true" ]]; then
    log "disposable mode enabled; skipping backup artifact validation"
    return 0
  fi

  for d in "${required_dirs[@]}"; do
    if [[ ! -d "${backup_root}/${d}" ]]; then
      missing_dirs+=("${backup_root}/${d}")
    fi
  done

  for d in "${non_loss_dirs[@]}"; do
    if [[ -d "${backup_root}/${d}" ]] && ! backup_dir_has_artifact "${backup_root}/${d}"; then
      missing_non_loss+=("${backup_root}/${d}")
    fi
  done

  {
    echo "backup_root=${backup_root}"
    echo "required_dirs=${required_dirs[*]}"
    echo "missing_dir_count=${#missing_dirs[@]}"
    echo "missing_non_loss_count=${#missing_non_loss[@]}"
    if (( ${#missing_dirs[@]} > 0 )); then
      echo "missing_dirs=${missing_dirs[*]}"
    fi
    if (( ${#missing_non_loss[@]} > 0 )); then
      echo "missing_non_loss_artifacts=${missing_non_loss[*]}"
    fi
  } >"${LOG_DIR}/backup-gating.log"

  if (( ${#missing_dirs[@]} > 0 )); then
    log "WARNING backup evidence directories missing under ${backup_root} (advisory only)"
  fi

  if (( ${#missing_non_loss[@]} > 0 )); then
    log "WARNING backup evidence artifacts missing under ${backup_root} (advisory only)"
  fi

  log "backup evidence check complete"
}

stack_name() {
  printf '%s\n' "${1%%:*}"
}

stack_vmid() {
  local rest="${1#*:}"
  printf '%s\n' "${rest%%:*}"
}

stack_ip() {
  printf '%s\n' "${1##*:}"
}

ensure_workspace_dir() {
  local stack="$1"
  local workspace="${2:-${TERRAGRUNT_WORKSPACE}}"
  local dir="${REPO_ROOT}/terraform/lxc/stacks/${stack}/terraform.tfstate.d/${workspace}"
  if [[ ! -d "${dir}" ]]; then
    mkdir -p "${dir}"
    log "created workspace dir: ${dir}"
  fi
}

stack_apply() {
  local spec="$1"
  local stack
  stack="$(stack_name "${spec}")"

  ensure_workspace_dir "${stack}"
  guard_target
  run_logged "deploy-${stack}" \
    bash -lc "cd '${REPO_ROOT}/terraform/lxc/stacks/${stack}' && '${WITH_SECRETS}' env TF_WORKSPACE='${TERRAGRUNT_WORKSPACE}' terragrunt apply -auto-approve"
  guard_target
  run_logged "provision-${stack}" \
    "${WITH_SECRETS}" "${REPO_ROOT}/scripts/provision.sh" --stack "${stack}"
  validate_stack_smoke "${spec}"
}

stack_destroy() {
  local spec="$1"
  local stack vmid
  stack="$(stack_name "${spec}")"
  vmid="$(stack_vmid "${spec}")"

  ensure_workspace_dir "${stack}"

  if [[ "${stack}" == "portainer-stack" ]]; then
    run_logged "pre-destroy-backup-${stack}" \
      ssh -F /dev/null "root@${TARGET_PVE_HOST}" \
        "pct exec ${vmid} -- bash -c 'set -a; source /etc/portainer-backup/env; set +a; /opt/portainer-backup/backup.sh'"
  fi

  guard_target
  if [[ "${stack}" == "portainer-stack" || "${stack}" == "netbox-stack" || "${stack}" == "monitoring-stack" || "${stack}" == "harbor-stack" || "${stack}" == "authentik-stack" || "${stack}" == "step-ca-stack" || "${stack}" == "proxy-stack" || "${stack}" == "dns-stack" || "${stack}" == "ci-runner-01" || "${stack}" == "apt-cacher-stack" ]]; then
    run_logged "destroy-${stack}" \
      bash -lc "cd '${REPO_ROOT}' && REBUILD_GATE_WITH_SECRETS='${WITH_SECRETS}' REBUILD_GATE_TARGET_NODE_EXPECTED='${TARGET_NODE_EXPECTED}' REBUILD_GATE_TERRAGRUNT_WORKSPACE='${TERRAGRUNT_WORKSPACE}' REBUILD_GATE_TARGET_HOST='${TARGET_PVE_HOST}' '${REPO_ROOT}/scripts/rebuild-gate-destroy.sh' --execute --stack '${stack}'"
  else
    run_logged "destroy-${stack}" \
      bash -lc "cd '${REPO_ROOT}/terraform/lxc/stacks/${stack}' && '${WITH_SECRETS}' terragrunt destroy -auto-approve"
  fi
  run_logged "verify-destroy-${stack}" \
    ssh -F /dev/null "root@${TARGET_PVE_HOST}" "if pct status '${vmid}' >/dev/null 2>&1; then echo 'FAIL vmid_${vmid}_still_present' >&2; exit 1; fi; echo 'PASS vmid_${vmid}_absent'"
}

validate_stack_smoke() {
  local spec="$1"
  local stack vmid ip
  stack="$(stack_name "${spec}")"
  vmid="$(stack_vmid "${spec}")"
  ip="$(stack_ip "${spec}")"

  hydrate_live_env_contract

  run_logged "pct-status-${stack}" \
    ssh -F /dev/null "root@${TARGET_PVE_HOST}" "pct status '${vmid}' | grep -F 'status: running'"

  case "${stack}" in
    portainer-stack)
      run_logged "health-${stack}" curl -fsS "http://${ip}:9000/api/system/status"  # NOSONAR — unauthenticated health check on private SDN
      ;;
    apt-cacher-stack)
      run_logged "health-${stack}" \
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}:3142/'); printf 'http_status=%s\\n' \"\${code}\"; [[ \"\${code}\" == '200' || \"\${code}\" == '406' ]]"  # NOSONAR — unauthenticated health check on private SDN
      ;;
    harbor-stack)
      run_logged "health-${stack}" \
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}/v2/'); printf 'http_status=%s\\n' \"\${code}\"; [[ \"\${code}\" == '200' || \"\${code}\" == '301' || \"\${code}\" == '302' || \"\${code}\" == '401' ]]"  # NOSONAR — unauthenticated health check on private SDN
      ;;
    ci-runner-01)
      run_logged "health-${stack}" \
        ssh -F /dev/null "root@${TARGET_PVE_HOST}" "pct exec '${vmid}' -- sh -lc 'systemctl list-units --type=service --state=running --no-legend | grep -F actions.runner'"
      ;;
    dns-stack)
      run_logged "health-${stack}-authoritative" dig "@${ip}" +short "${LAB_FQDN_TRAEFIK}"
      run_logged "health-${stack}-delegated" dig "@${LAB_GW_MGMT}" +short "${LAB_FQDN_TRAEFIK}"
      ;;
    proxy-stack)
      run_logged "health-${stack}" curl -skI --resolve "${LAB_FQDN_TRAEFIK}:443:${LAB_IP_PROXY}" "https://${LAB_FQDN_TRAEFIK}/"
      ;;
    step-ca-stack)
      run_logged "health-${stack}" curl -sk "https://${ip}/acme/acme/directory"
      ;;
    authentik-stack)
      run_logged "health-${stack}" curl -fsS "http://${ip}:9000/-/health/live/"  # NOSONAR — unauthenticated health check on private SDN
      ;;
    monitoring-stack)
      run_logged "health-${stack}" curl -skI --resolve "${LAB_FQDN_GRAFANA}:443:${LAB_IP_PROXY}" "https://${LAB_FQDN_GRAFANA}/"
      ;;
    netbox-stack)
      run_logged "health-${stack}" curl -skI --resolve "${LAB_FQDN_NETBOX}:443:${LAB_IP_PROXY}" "https://${LAB_FQDN_NETBOX}/"
      ;;
  esac
}

run_status_capture() {
  local logfile="$1"
  shift
  local status=0

  mkdir -p "${LOG_DIR}"
  "$@" >"${logfile}" 2>&1
  status=$?
  if [[ "${status}" -eq 0 ]]; then
    return 0
  fi
  return "${status}"
}

classify_pct_capture_failure() {
  local pct_log="$1"

  PLATFORM_PCT_STATUS="missing"
  PLATFORM_PCT_DETAIL="pct status unavailable"

  if grep -Eq 'Could not resolve hostname|Temporary failure in name resolution|Name or service not known' "${pct_log}"; then
    PLATFORM_PCT_STATUS="blocked"
    PLATFORM_PCT_DETAIL="status collection blocked: operator host cannot resolve ${TARGET_PVE_HOST}"
    return 0
  fi

  if grep -Eq 'No route to host|Connection timed out|Connection refused|Host key verification failed|Permission denied' "${pct_log}"; then
    PLATFORM_PCT_STATUS="blocked"
    PLATFORM_PCT_DETAIL="status collection blocked: cannot reach Proxmox host via SSH"
    return 0
  fi
}

probe_stack_health() {
  local stack="$1"
  local vmid="$2"
  local ip="$3"

  PLATFORM_HEALTH_STATUS="skipped"
  PLATFORM_HEALTH_DETAIL="no stack-specific probe"
  PLATFORM_HEALTH_LOG=""

  case "${stack}" in
    portainer-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" curl -fsS "http://${ip}:9000/api/system/status"; then  # NOSONAR — unauthenticated health check on private SDN
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="portainer api ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="portainer api failed"
      fi
      ;;
    apt-cacher-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}:3142/'); printf 'http_status=%s\\n' \"\${code}\"; [[ \"\${code}\" == '200' || \"\${code}\" == '406' ]]"; then  # NOSONAR — unauthenticated health check on private SDN
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="apt-cacher http ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="apt-cacher http failed"
      fi
      ;;
    harbor-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}/v2/'); printf 'http_status=%s\n' \"\${code}\"; [[ \"\${code}\" == '401' ]]"; then  # NOSONAR — unauthenticated health check on private SDN
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="registry v2 challenge ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="registry v2 challenge failed"
      fi
      ;;
    ci-runner-01)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        ssh -F /dev/null "root@${TARGET_PVE_HOST}" "pct exec '${vmid}' -- sh -lc 'systemctl list-units --type=service --state=running --no-legend | grep -F actions.runner'"; then
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="github actions runner service running"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="github actions runner service not found running"
      fi
      ;;
    dns-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        bash -lc "dig '@${ip}' +short '${LAB_FQDN_TRAEFIK}' | grep -Fx '${LAB_IP_PROXY}'"; then
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="authoritative dns ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="authoritative dns failed"
      fi
      ;;
    proxy-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        bash -lc "curl -skI --resolve '${LAB_FQDN_TRAEFIK}:443:${LAB_IP_PROXY}' 'https://${LAB_FQDN_TRAEFIK}/' | grep -Eq '^HTTP/'"; then
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="traefik https responds"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="traefik https failed"
      fi
      ;;
    step-ca-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" curl -skf "https://${ip}/acme/acme/directory"; then
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="acme directory ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="acme directory failed"
      fi
      ;;
    authentik-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" curl -fsS "http://${ip}:9000/-/health/live/"; then  # NOSONAR — unauthenticated health check on private SDN
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="authentik health ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="authentik health failed"
      fi
      ;;
    monitoring-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        bash -lc "curl -fsS 'http://${ip}:3000/login' >/dev/null && curl -fsS 'http://${ip}:8428/-/ready'"; then  # NOSONAR — unauthenticated health check on private SDN
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="grafana and victoriametrics ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="grafana or victoriametrics failed"
      fi
      ;;
    netbox-stack)
      PLATFORM_HEALTH_LOG="${LOG_DIR}/platform-status-${stack}-health.log"
      if run_status_capture "${PLATFORM_HEALTH_LOG}" \
        bash -lc "code=\$(curl -sS -o /dev/null -w '%{http_code}' 'http://${ip}:8080/'); printf 'http_status=%s\n' \"\${code}\"; [[ \"\${code}\" =~ ^(200|301|302)$ ]]"; then  # NOSONAR — unauthenticated health check on private SDN
        PLATFORM_HEALTH_STATUS="ok"
        PLATFORM_HEALTH_DETAIL="netbox http ok"
      else
        PLATFORM_HEALTH_STATUS="failed"
        PLATFORM_HEALTH_DETAIL="netbox http failed"
      fi
      ;;
  esac
}

write_platform_status_json() {
  local tsv_path="$1"
  local json_path="$2"

  python3 - "${tsv_path}" "${json_path}" <<'PY'
import csv
import json
import sys
from pathlib import Path

tsv_path = Path(sys.argv[1])
json_path = Path(sys.argv[2])

rows = []
with tsv_path.open(encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle, delimiter="\t")
    for row in reader:
        rows.append(row)

summary = {
    "total": len(rows),
    "healthy": sum(1 for row in rows if row["overall"] == "healthy"),
    "running": sum(1 for row in rows if row["overall"] == "running"),
    "degraded": sum(1 for row in rows if row["overall"] == "degraded"),
    "blocked": sum(1 for row in rows if row["overall"] == "blocked"),
    "stopped": sum(1 for row in rows if row["overall"] == "stopped"),
    "missing": sum(1 for row in rows if row["overall"] == "missing"),
}

json_path.write_text(
    json.dumps({"summary": summary, "stacks": rows}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

generate_platform_status_report() {
  local spec stack vmid ip pct_log docker_log listeners_log pct_status health_status health_detail health_log overall
  local report_tsv="${LOG_DIR}/platform-status.tsv"
  local report_json="${LOG_DIR}/platform-status.json"
  local report_log="${LOG_DIR}/platform-status.log"
  local -a specs=("$@")

  printf 'stack\tvmid\tip\tpct_status\thealth\toverall\tdetail\tpct_log\tdocker_log\tlisteners_log\thealth_log\n' >"${report_tsv}"

  for spec in "${specs[@]}"; do
    stack="$(stack_name "${spec}")"
    vmid="$(stack_vmid "${spec}")"
    ip="$(stack_ip "${spec}")"
    pct_log="${LOG_DIR}/platform-status-${stack}-pct.log"
    docker_log="${LOG_DIR}/platform-status-${stack}-docker.log"
    listeners_log="${LOG_DIR}/platform-status-${stack}-listeners.log"

    if run_status_capture "${pct_log}" ssh -F /dev/null "root@${TARGET_PVE_HOST}" "pct status '${vmid}'"; then
      pct_status="$(awk -F': ' '/^status:/ {print $2; exit}' "${pct_log}")"
      if [[ -z "${pct_status}" ]]; then
        pct_status="unknown"
      fi
    else
      classify_pct_capture_failure "${pct_log}"
      pct_status="${PLATFORM_PCT_STATUS}"
    fi

    health_status="skipped"
    health_detail="container not running"
    health_log=""
    : >"${docker_log}"
    : >"${listeners_log}"

    if [[ "${pct_status}" == "running" ]]; then
      run_status_capture "${docker_log}" \
        ssh -F /dev/null "root@${TARGET_PVE_HOST}" \
          "pct exec '${vmid}' -- sh -lc 'if command -v docker >/dev/null 2>&1; then docker ps --format \"{{.Names}}|{{.Status}}|{{.Ports}}\"; else echo docker-unavailable; fi'" || true
      run_status_capture "${listeners_log}" \
        ssh -F /dev/null "root@${TARGET_PVE_HOST}" \
          "pct exec '${vmid}' -- sh -lc 'if command -v ss >/dev/null 2>&1; then ss -ltnp; else echo ss-unavailable; fi'" || true

      probe_stack_health "${stack}" "${vmid}" "${ip}"
      health_status="${PLATFORM_HEALTH_STATUS}"
      health_detail="${PLATFORM_HEALTH_DETAIL}"
      health_log="${PLATFORM_HEALTH_LOG}"
    fi

    if [[ "${pct_status}" == "blocked" ]]; then
      overall="blocked"
      health_detail="${PLATFORM_PCT_DETAIL}"
    elif [[ "${pct_status}" == "missing" ]]; then
      overall="missing"
    elif [[ "${pct_status}" != "running" ]]; then
      overall="stopped"
    elif [[ "${health_status}" == "ok" ]]; then
      overall="healthy"
    elif [[ "${health_status}" == "skipped" ]]; then
      overall="running"
    else
      overall="degraded"
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${stack}" \
      "${vmid}" \
      "${ip}" \
      "${pct_status}" \
      "${health_status}" \
      "${overall}" \
      "${health_detail}" \
      "${pct_log}" \
      "${docker_log}" \
      "${listeners_log}" \
      "${health_log}" >>"${report_tsv}"
  done

  write_platform_status_json "${report_tsv}" "${report_json}"

  {
    printf 'Platform status for %s\n' "${STAMP}"
    printf '\n'
    printf '%-20s %-5s %-12s %-10s %-8s %-9s %s\n' \
      "STACK" "VMID" "IP" "PCT" "HEALTH" "OVERALL" "DETAIL"
    tail -n +2 "${report_tsv}" | while IFS=$'\t' read -r stack vmid ip pct_status health_status overall health_detail _; do
      printf '%-20s %-5s %-12s %-10s %-8s %-9s %s\n' \
        "${stack}" "${vmid}" "${ip}" "${pct_status}" "${health_status}" "${overall}" "${health_detail}"
    done
    printf '\nTSV: %s\nJSON: %s\n' "${report_tsv}" "${report_json}"
  } | tee "${report_log}" | tee -a "${RUN_LOG}"
}

create_evidence_dirs() {
  mkdir -p \
    "${LOG_DIR}" \
    "${EVIDENCE_DIR}/backups/portainer" \
    "${EVIDENCE_DIR}/backups/harbor" \
    "${EVIDENCE_DIR}/backups/authentik" \
    "${EVIDENCE_DIR}/backups/netbox" \
    "${EVIDENCE_DIR}/backups/monitoring" \
    "${EVIDENCE_DIR}/backups/traefik-certs" \
    "${EVIDENCE_DIR}/backups/step-ca" \
    "${EVIDENCE_DIR}/backups/ci-runner" \
    "${EVIDENCE_DIR}/backups/apt-cacher"
}

run_source_preflight_checks() {
  run_logged "validate-storage-contract-offline" \
    python3 "${TERRAFORM_LXC}/validate-storage-contract.py" \
    --manifest "${TERRAFORM_LXC}/storage/${TARGET_NODE_EXPECTED}.yaml" \
    --stacks-dir "${TERRAFORM_LXC}/stacks" \
    --proxmox-node "${TARGET_NODE_EXPECTED}" \
    --offline
  run_storage_classifier_regression_checks
  run_logged "validate-edge-manifests" \
    python3 "${TERRAFORM_LXC}/validate-edge-manifests.py" "${TERRAFORM_LXC}"/stacks/*/edge.yaml
  run_logged "edge-unit-tests" \
    python3 -m unittest \
      terraform/lxc/test_edge_manifest.py \
      terraform/lxc/test_render_edge_traefik.py \
      terraform/lxc/test_render_edge_coredns.py \
      terraform/lxc/test_discover_authentik_edge.py \
      terraform/lxc/test_reconcile_authentik_edge.py \
      terraform/lxc/test_reconcile_edge.py \
      terraform/lxc/test_inventory_template.py \
      terraform/lxc/test_stack_classification.py
  run_logged "git-diff-check" git -C "${REPO_ROOT}" diff --check

  rm -rf "${TERRAFORM_LXC}/.generated/traefik" "${TERRAFORM_LXC}/.generated/coredns"
  run_logged "render-edge-traefik" python3 "${TERRAFORM_LXC}/render-edge-traefik.py" --json
  assert_traefik_render_output "${LOG_DIR}/render-edge-traefik.log"
  log "Traefik render output assertions passed"
  run_logged "render-edge-coredns" python3 "${TERRAFORM_LXC}/render-edge-coredns.py" --json
  assert_coredns_render_output "${LOG_DIR}/render-edge-coredns.log"
  log "CoreDNS render output assertions passed"
  run_logged "syntax-check-deploy-harbor-stack" \
    bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
      ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
      ansible-playbook --syntax-check \
        '${ANSIBLE_DIR}/playbooks/deploy-harbor-stack.yml'"
  run_logged "syntax-check-deploy-authentik-stack" \
    bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
      ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
      ansible-playbook --syntax-check \
        '${ANSIBLE_DIR}/playbooks/deploy-authentik-stack.yml'"
  run_logged "syntax-check-deploy-monitoring-stack" \
    bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
      ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
      ansible-playbook --syntax-check \
        '${ANSIBLE_DIR}/playbooks/deploy-monitoring-stack.yml'"
  run_logged "syntax-check-deploy-proxy-stack" \
    bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
      ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
      ansible-playbook --syntax-check \
        '${ANSIBLE_DIR}/playbooks/deploy-proxy-stack.yml'"
  run_logged "syntax-check-deploy-netbox-stack" \
    bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
      ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
      ansible-playbook --syntax-check \
        '${ANSIBLE_DIR}/playbooks/deploy-netbox-stack.yml'"
}

run_live_preflight_checks() {
  local authentik_url
  require_live_env_contract
  guard_target
  run_logged "validate-storage-contract-live" \
    "${WITH_SECRETS}" python3 "${TERRAFORM_LXC}/validate-storage-contract.py" \
    --manifest "${TERRAFORM_LXC}/storage/${TARGET_NODE_EXPECTED}.yaml" \
    --stacks-dir "${TERRAFORM_LXC}/stacks" \
    --proxmox-node "${TARGET_NODE_EXPECTED}"
  run_logged "dns-authoritative-traefik" \
    bash -lc "dig @${LAB_IP_DNS} +short '${LAB_FQDN_TRAEFIK}' | grep -Fx '${LAB_IP_PROXY}'"
  run_logged "dns-delegated-traefik" \
    bash -lc "dig @${LAB_GW_MGMT} +short '${LAB_FQDN_TRAEFIK}' | grep -Fx '${LAB_IP_PROXY}'"
  run_logged "https-route-traefik" \
    bash -lc "curl -skI --resolve '${LAB_FQDN_TRAEFIK}:443:${LAB_IP_PROXY}' 'https://${LAB_FQDN_TRAEFIK}/' | grep -Eq '^HTTP/'"
  run_logged "authentik-direct-health" \
    curl --cacert "${HOMELAB_ROOT_CA}" -fsS "https://authentik-int.${LAB_DOMAIN}:9443/-/health/live/"
  authentik_url="$(get_authentik_url)" || return 1
  run_logged "reconcile-edge-dry-run" \
    env "AUTHENTIK_EXTRA_CA=${HOMELAB_ROOT_CA}" \
    "${WITH_SECRETS}" python3 "${TERRAFORM_LXC}/reconcile-edge.py" \
      --authentik-url "${authentik_url}" --json
}

phase_source_preflight() {
  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  record_working_tree_state
  record_branch_and_commit
  run_source_preflight_checks
}

phase_live_preflight() {
  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  record_working_tree_state
  record_branch_and_commit
  run_live_preflight_checks
}

phase_external_preflight() {
  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  if [[ "${TARGET_NODE_EXPECTED}" != "pve" ]]; then
    log "external-preflight: skipped (TARGET_NODE_EXPECTED=${TARGET_NODE_EXPECTED}, only runs for pve)"
    return 0
  fi
  run_logged "external-preflight" \
    "${WITH_SECRETS}" python3 "${REPO_ROOT}/scripts/preflight-production-external.py" \
    --save-evidence "${EVIDENCE_DIR}"
}

phase_approval_preflight() {
  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  record_working_tree_state
  record_branch_and_commit
  require_clean_tree
  run_source_preflight_checks
  run_live_preflight_checks
}

phase_preflight() {
  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  record_working_tree_state
  record_branch_and_commit
  log "preflight is a backwards-compatible alias for source-preflight + live-preflight"
  run_source_preflight_checks
  run_live_preflight_checks
}

phase_plan() {
  local -a foundation_specs edge_specs platform_specs destroy_specs
  local -a state_specs
  local spec

  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  record_working_tree_state
  record_branch_and_commit
  load_stack_specs foundation foundation_specs
  load_stack_specs edge edge_specs
  load_stack_specs platform platform_specs
  load_stack_specs destroy destroy_specs

  for spec in "${foundation_specs[@]}"; do
    state_specs+=("foundation:${spec}")
  done
  for spec in "${edge_specs[@]}"; do
    state_specs+=("edge:${spec}")
  done
  for spec in "${platform_specs[@]}"; do
    state_specs+=("platform:${spec}")
  done
  for spec in "${destroy_specs[@]}"; do
    state_specs+=("destroy:${spec}")
  done
  set_current_phase_stack_specs "${state_specs[@]}"

  log_stack_plan "foundation" "${foundation_specs[@]}"
  log_stack_plan "edge" "${edge_specs[@]}"
  log_stack_plan "platform" "${platform_specs[@]}"
  log_stack_plan "destroy" "${destroy_specs[@]}"

  require_live_env_contract
  guard_target
  for spec in "${foundation_specs[@]}"; do
    review_storage_plan_safety "${spec}"
  done
  for spec in "${edge_specs[@]}"; do
    review_storage_plan_safety "${spec}"
  done
  for spec in "${platform_specs[@]}"; do
    review_storage_plan_safety "${spec}"
  done
}

phase_platform_status() {
  local -a specs

  create_evidence_dirs
  log "evidence_dir=${EVIDENCE_DIR}"
  record_working_tree_state
  record_branch_and_commit
  guard_target
  load_stack_specs all specs
  set_current_phase_stack_specs "${specs[@]}"
  generate_platform_status_report "${specs[@]}"
}

phase_destroy() {
  local spec
  local -a specs
  create_evidence_dirs
  require_execute_approval
  validate_approval_packet
  validate_backup_artifacts_present
  require_clean_tree
  load_stack_specs destroy specs
  set_current_phase_stack_specs "${specs[@]}"
  log_stack_plan "destroy" "${specs[@]}"
  for spec in "${specs[@]}"; do
    stack_destroy "${spec}"
  done
}

phase_deploy_foundation() {
  local spec
  local -a specs
  create_evidence_dirs
  require_execute_approval
  require_clean_tree
  load_stack_specs foundation specs
  set_current_phase_stack_specs "${specs[@]}"
  log_stack_plan "foundation" "${specs[@]}"
  for spec in "${specs[@]}"; do
    stack_apply "${spec}"
  done
}

phase_deploy_edge() {
  local spec
  local -a specs
  create_evidence_dirs
  require_execute_approval
  require_clean_tree
  rm -rf "${TERRAFORM_LXC}/.generated/traefik" "${TERRAFORM_LXC}/.generated/coredns"
  run_logged "render-edge-traefik-deploy" python3 "${TERRAFORM_LXC}/render-edge-traefik.py" --json
  run_logged "render-edge-coredns-deploy" python3 "${TERRAFORM_LXC}/render-edge-coredns.py" --json
  load_stack_specs edge specs
  set_current_phase_stack_specs "${specs[@]}"
  log_stack_plan "edge" "${specs[@]}"
  for spec in "${specs[@]}"; do
    stack_apply "${spec}"
  done
}

phase_activate_edge() {
  local authentik_url
  create_evidence_dirs
  require_execute_approval
  require_clean_tree
  guard_target
  authentik_url="$(get_authentik_url)" || return 1
  wait_for_authentik_api_ready "${authentik_url}"
  run_logged "render-edge-traefik-activate" python3 "${TERRAFORM_LXC}/render-edge-traefik.py" --json
  run_logged "render-edge-coredns-activate" python3 "${TERRAFORM_LXC}/render-edge-coredns.py" --json
  run_logged "reconcile-edge-apply" \
    env "AUTHENTIK_EXTRA_CA=${HOMELAB_ROOT_CA}" \
    "${WITH_SECRETS}" python3 "${TERRAFORM_LXC}/reconcile-edge.py" \
      --authentik-url "${authentik_url}" --apply --json

  guard_target
  run_logged "publish-coredns" \
    bash -lc "cd '${ANSIBLE_DIR}' && '${WITH_SECRETS}' ansible-playbook -i ../stacks/dns-stack/inventory.yml -u root playbooks/deploy-coredns.yml -e coredns_generated_zone_src='${TERRAFORM_LXC}/.generated/coredns/coredns-lab.zone'"

  guard_target
  run_logged "publish-traefik" \
    bash -lc "cd '${ANSIBLE_DIR}' && '${WITH_SECRETS}' ansible-playbook -i ../stacks/proxy-stack/inventory.yml -u root playbooks/deploy-proxy-stack.yml -e traefik_generated_source_dir='${TERRAFORM_LXC}/.generated/traefik'"

  run_logged "reconcile-edge-post-activate-dry-run" \
    env "AUTHENTIK_EXTRA_CA=${HOMELAB_ROOT_CA}" \
    "${WITH_SECRETS}" python3 "${TERRAFORM_LXC}/reconcile-edge.py" \
      --authentik-url "${authentik_url}" --json
}

phase_deploy_platform() {
  local spec
  local -a specs
  create_evidence_dirs
  require_execute_approval
  require_clean_tree
  load_stack_specs platform specs
  set_current_phase_stack_specs "${specs[@]}"
  log_stack_plan "platform" "${specs[@]}"
  for spec in "${specs[@]}"; do
    stack_apply "${spec}"
  done
}

phase_final_validation() {
  local host fqdn authentik_url bg_host bg_fqdn browser_dns_target_ip
  create_evidence_dirs
  record_working_tree_state
  require_live_env_contract
  guard_target
  authentik_url="$(get_authentik_url)" || return 1
  browser_dns_target_ip="${LAB_IP_PROXY:-}"

  if [[ -z "${browser_dns_target_ip}" ]]; then
    set_phase_failure_context \
      "resolve-browser-dns-target" \
      "LAB_IP_PROXY" \
      "${RUN_LOG}" \
      "LAB_IP_PROXY is required for final browser DNS validation"
    return 1
  fi

  for host in "${BROWSER_HOSTS[@]}"; do
    fqdn="${host}.${LAB_DOMAIN}"
    run_dns_answer_check "dns-authoritative-${host}" "${LAB_IP_DNS}" "${fqdn}" "${browser_dns_target_ip}"
    run_dns_answer_check "dns-delegated-${host}" "${LAB_GW_MGMT}" "${fqdn}" "${browser_dns_target_ip}"
    run_logged "https-route-${host}" curl -skI --resolve "${fqdn}:443:${LAB_IP_PROXY}" "https://${fqdn}/"
  done

  for bg_host in "${BREAKGLASS_DNS_HOSTS[@]}"; do
    bg_fqdn="${bg_host}.${LAB_DOMAIN}"
    run_dns_nonempty_check "dns-authoritative-${bg_host}" "${LAB_IP_DNS}" "${bg_fqdn}"
    run_dns_nonempty_check "dns-delegated-${bg_host}" "${LAB_GW_MGMT}" "${bg_fqdn}"
  done

  run_logged "harbor-registry-auth" curl -skI --resolve "${LAB_FQDN_HARBOR}:443:${LAB_IP_PROXY}" "https://${LAB_FQDN_HARBOR}/v2/"
  run_logged "portainer-direct-api" curl -fsS "http://${LAB_IP_PORTAINER}:9000/api/system/status"  # NOSONAR — unauthenticated health check on private SDN
  run_logged "authentik-direct-health" curl --cacert "${HOMELAB_ROOT_CA}" -fsS "https://authentik-int.${LAB_DOMAIN}:9443/-/health/live/"
  run_logged "final-reconcile-edge-dry-run" \
    env "AUTHENTIK_EXTRA_CA=${HOMELAB_ROOT_CA}" \
    "${WITH_SECRETS}" python3 "${TERRAFORM_LXC}/reconcile-edge.py" \
      --authentik-url "${authentik_url}" --json
}

phase_cycle() {
  require_execute_approval
  validate_approval_packet
  run_phase_handler "external-preflight" phase_external_preflight
  run_phase_handler "destroy" phase_destroy
  run_phase_handler "deploy-foundation" phase_deploy_foundation
  run_phase_handler "deploy-edge" phase_deploy_edge
  run_phase_handler "activate-edge" phase_activate_edge
  run_phase_handler "deploy-platform" phase_deploy_platform
  run_phase_handler "final-validation" phase_final_validation
}

phase_status() {
  if [[ ! -f "${STATE_FILE}" ]]; then
  printf 'Checkpoint state not found: %s\n' "${STATE_FILE}" >&2
  return 1
  fi

  python3 - "${STATE_FILE}" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
data = json.loads(state_path.read_text(encoding="utf-8"))
phases = data.get("phases", {})
phase_order = data.get("phase_order", [])
resume_order = data.get("resume_phase_sequence", [])


def phase_status(name: str) -> str:
  entry = phases.get(name, {})
  return entry.get("status", "pending")


def effectively_passed(name: str) -> bool:
  status = phase_status(name)
  if status == "passed":
    return True
  if name in {"source-preflight", "live-preflight"} and phase_status("preflight") == "passed":
    return True
  return False


def suggest_next_phase() -> str | None:
  for phase_name in resume_order:
    if phase_status(phase_name) == "failed":
      return phase_name
  for phase_name in resume_order:
    if effectively_passed(phase_name):
      continue
    if phase_status(phase_name) in {"pending", "skipped"}:
      return phase_name
    if phase_status(phase_name) == "running":
      return phase_name
  return None


print(f"Stamp: {data.get('stamp', '<unknown>')}")
print(f"State file: {state_path}")
print(f"Evidence dir: {data.get('evidence_dir', '<unknown>')}")
print(f"Branch: {data.get('branch') or '<unknown>'}")
print(f"Commit: {data.get('commit') or '<unknown>'}")

dirty_tree = data.get("dirty_tree") or {}
dirty_status = dirty_tree.get("status", "unknown")
dirty_log = dirty_tree.get("status_log")
if dirty_log:
  print(f"Dirty tree: {dirty_status} ({dirty_log})")
else:
  print(f"Dirty tree: {dirty_status}")

print("Phases:")
for phase_name in phase_order:
  entry = phases.get(phase_name, {})
  status = entry.get("status", "pending")
  suffix = ""
  if entry.get("exit_status") is not None:
    suffix = f" (exit={entry['exit_status']})"
  print(f"- {phase_name}: {status}{suffix}")

failed_entries = [phases[name] for name in phase_order if phases.get(name, {}).get("status") == "failed"]
if failed_entries:
  latest_failed = failed_entries[-1]
  failure = latest_failed.get("failure") or {}
  print("Failed phase detail:")
  print(f"- phase: {latest_failed.get('phase', '<unknown>')}")
  if failure.get("command"):
    print(f"- command: {failure['command']}")
  if failure.get("log_path"):
    print(f"- log: {failure['log_path']}")
  if failure.get("message"):
    print(f"- message: {failure['message']}")

next_phase = suggest_next_phase()
if next_phase is None:
  print("Suggested next phase: none")
else:
  print(f"Suggested next phase: {next_phase}")
PY
}

parse_args() {
  if [[ $# -eq 0 ]]; then
    usage
    exit 1
  fi

  if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    exit 0
  fi

  PHASE="$1"
  shift

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --execute)
        EXECUTE=true
        shift
        ;;
      --approval-text)
        if [[ $# -lt 2 ]]; then
          printf 'Missing value for --approval-text\n\n' >&2
          usage
          exit 1
        fi
        APPROVAL_TEXT="${2:-}"
        shift 2
        ;;
      --approval-packet)
        if [[ $# -lt 2 ]]; then
          printf 'Missing value for --approval-packet\n\n' >&2
          usage
          exit 1
        fi
        APPROVAL_PACKET="${2:-}"
        shift 2
        ;;
      --disposable)
        DISPOSABLE=true
        shift
        ;;
      --stamp)
        if [[ $# -lt 2 ]]; then
          printf 'Missing value for --stamp\n\n' >&2
          usage
          exit 1
        fi
        STAMP="${2:-}"
        EVIDENCE_DIR="${EVIDENCE_ROOT}/${STAMP}"
        LOG_DIR="${EVIDENCE_DIR}/logs"
        RUN_LOG="${LOG_DIR}/teardown-deploy-test-${STAMP}.log"
        STATE_FILE="${EVIDENCE_DIR}/state.json"
        shift 2
        ;;
      --require-clean)
        REQUIRE_CLEAN=true
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf 'Unknown argument: %s\n\n' "$1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

main() {
  parse_args "$@"
  cd "${REPO_ROOT}"

  case "${PHASE}" in
    source-preflight)
      run_phase_handler "source-preflight" phase_source_preflight
      ;;
    live-preflight)
      run_phase_handler "live-preflight" phase_live_preflight
      ;;
    external-preflight)
      run_phase_handler "external-preflight" phase_external_preflight
      ;;
    approval-preflight)
      run_phase_handler "approval-preflight" phase_approval_preflight
      ;;
    preflight)
      run_phase_handler "preflight" phase_preflight
      ;;
    plan)
      run_phase_handler "plan" phase_plan
      ;;
    platform-status)
      run_phase_handler "platform-status" phase_platform_status
      ;;
    status)
      phase_status
      ;;
    destroy|deploy-foundation|deploy-edge|activate-edge|deploy-platform|cycle)
      acquire_harness_lock
      trap 'release_harness_lock' EXIT
      case "${PHASE}" in
        destroy)          run_phase_handler "destroy"           phase_destroy ;;
        deploy-foundation) run_phase_handler "deploy-foundation" phase_deploy_foundation ;;
        deploy-edge)      run_phase_handler "deploy-edge"       phase_deploy_edge ;;
        activate-edge)    run_phase_handler "activate-edge"     phase_activate_edge ;;
        deploy-platform)  run_phase_handler "deploy-platform"   phase_deploy_platform ;;
        cycle)            run_phase_handler "cycle"             phase_cycle ;;
      esac
      release_harness_lock
      ;;
    final-validation)
      run_phase_handler "final-validation" phase_final_validation
      ;;
    *)
      printf 'Unknown phase: %s\n\n' "${PHASE}" >&2
      usage
      exit 1
      ;;
  esac

  log "DONE ${PHASE}; evidence_dir=${EVIDENCE_DIR}"
}

main "$@"
