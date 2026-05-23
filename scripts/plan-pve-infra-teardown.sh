#!/usr/bin/env bash
# Read-only planner for infra-only teardown analysis on production pve.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WITH_SECRETS_PROD="${REPO_ROOT}/with-secrets-prod"
INVENTORY_FILE="${REPO_ROOT}/docs/productionize-refactor/pve-infra-teardown-inventory.md"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
EVIDENCE_ROOT="${REPO_ROOT}/docs/productionize-refactor/evidence"

STAMP="${PVE_INFRA_TEARDOWN_STAMP:-$(date -u +%Y%m%d-%H%M%S)}"
EVIDENCE_DIR="${EVIDENCE_ROOT}/pve-infra-teardown-plan-${STAMP}"
LOG_DIR="${EVIDENCE_DIR}/logs"
SUMMARY_FILE="${EVIDENCE_DIR}/summary.md"
PHASE=""

usage() {
  cat <<'EOF'
Usage:
  scripts/plan-pve-infra-teardown.sh <phase> [--stamp STAMP]

Phases:
  source-preflight  Validate the frozen inventory against current stack.yaml files.
  platform-status   Capture read-only current pve guest/storage status.
  plan              Run per-stack terragrunt destroy plans (read-only).
  summary           Build a human-readable summary from captured evidence.

Examples:
  scripts/plan-pve-infra-teardown.sh source-preflight
  scripts/plan-pve-infra-teardown.sh platform-status
  scripts/plan-pve-infra-teardown.sh plan --stamp 20260523-120000
  scripts/plan-pve-infra-teardown.sh summary --stamp 20260523-120000
EOF
}

log() {
  printf '[pve-infra-plan] %s\n' "$*"
}

fail() {
  printf '[pve-infra-plan] ERROR: %s\n' "$*" >&2
  exit 1
}

ensure_dirs() {
  mkdir -p "${EVIDENCE_DIR}" "${LOG_DIR}"
}

load_local_env() {
  if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${REPO_ROOT}/.env"
    set +a
  fi

  if [[ -f "${REPO_ROOT}/.env.pve" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "${REPO_ROOT}/.env.pve"
    set +a
  fi
}

sanitize_log_name() {
  local raw="$1"
  local cleaned

  cleaned="$(tr -cs '[:alnum:]._-' '-' <<<"${raw}")"
  cleaned="${cleaned#-}"
  cleaned="${cleaned%-}"

  if [[ -z "${cleaned}" ]]; then
    printf 'command\n'
  else
    printf '%s\n' "${cleaned}"
  fi
}

run_proxmox_read_only() {
  local command_name="$1"
  shift
  local suffix=""
  local log_name=""

  suffix="$(sanitize_log_name "$*")"
  log_name="$(sanitize_log_name "${command_name}-${suffix}")"

  if command -v "${command_name}" >/dev/null 2>&1; then
    run_logged "${log_name}" "${WITH_SECRETS_PROD}" "${command_name}" "$@"
    return 0
  fi

  local ssh_target="${PVE_INFRA_SSH_TARGET:-root@${PROXMOX_HOST:-pve.gibbsgreatly.xyz}}"
  local remote_cmd=""

  remote_cmd="$(printf '%q ' "${command_name}" "$@")"
  remote_cmd="${remote_cmd% }"

  run_logged \
    "${log_name}" \
    ssh -F /dev/null \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new \
    "${ssh_target}" "${remote_cmd}"
}

run_proxmox_read_only_capture_status() {
  local command_name="$1"
  shift
  local suffix=""
  local log_name=""

  suffix="$(sanitize_log_name "$*")"
  log_name="$(sanitize_log_name "${command_name}-${suffix}")"

  if command -v "${command_name}" >/dev/null 2>&1; then
    run_logged_capture_status "${log_name}" "${WITH_SECRETS_PROD}" "${command_name}" "$@"
    return 0
  fi

  local ssh_target="${PVE_INFRA_SSH_TARGET:-root@${PROXMOX_HOST:-pve.gibbsgreatly.xyz}}"
  local remote_cmd=""

  remote_cmd="$(printf '%q ' "${command_name}" "$@")"
  remote_cmd="${remote_cmd% }"

  run_logged_capture_status \
    "${log_name}" \
    ssh -F /dev/null \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new \
    "${ssh_target}" "${remote_cmd}"
}

target_guard_preflight() {
  local target_node="${TF_VAR_proxmox_node:-}"

  if [[ -n "${target_node}" && "${target_node}" != "pve" ]]; then
    fail "TF_VAR_proxmox_node must resolve to pve for this planner (got: ${target_node})"
  fi
}

resolve_inventory() {
  python3 - "${INVENTORY_FILE}" "${STACKS_DIR}" <<'PY'
import ipaddress
import os
import re
import sys
from pathlib import Path

import yaml

inventory_path = Path(sys.argv[1])
stacks_dir = Path(sys.argv[2])

if not inventory_path.is_file():
    raise SystemExit(f"inventory file not found: {inventory_path}")

text = inventory_path.read_text(encoding="utf-8")
rows = {}


def clean(value: str) -> str:
    return value.strip().strip("`").strip()


def normalize_ip(value: str) -> str:
    return str(ipaddress.ip_interface(clean(value)).ip)


def parse_table() -> None:
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
        if len(cells) < 8:
            continue

        stack = clean(cells[0])
        rows[stack] = {
            "stage": clean(cells[1]),
            "vmid": clean(cells[2]),
            "ip": normalize_ip(cells[3]),
            "zone": clean(cells[4]),
            "service_type": clean(cells[5]),
            "depends_on": clean(cells[6]),
            "playbook": clean(cells[7]),
        }


def parse_order(header: str) -> list[str]:
    pattern = re.compile(rf"^## {re.escape(header)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"missing inventory section: {header}")

    order = []
    for line in text[match.end():].splitlines():
        if line.startswith("## "):
            break
        item = re.match(r"\d+\.\s+`([^`]+)`", line)
        if item:
            order.append(item.group(1))
    return order


def stack_values(stack: str) -> tuple[str, str, bool]:
    stack_yaml = stacks_dir / stack / "stack.yaml"
    if not stack_yaml.is_file():
        raise SystemExit(f"missing stack.yaml for inventory stack {stack}: {stack_yaml}")

    text = os.path.expandvars(stack_yaml.read_text(encoding="utf-8"))
    data = yaml.safe_load(text) or {}
    vmid = str(data.get("vmid", "")).strip()
    ip_value = str(data.get("ip_address", "")).strip()
    enabled = bool(data.get("enabled", True))
    if not vmid or not ip_value:
        raise SystemExit(f"stack.yaml missing vmid or ip_address: {stack_yaml}")
    return vmid, normalize_ip(ip_value), enabled


parse_table()
destroy_order = parse_order("Candidate Destroy Order")

if not rows:
    raise SystemExit("no stack rows parsed from inventory")

for stack, metadata in rows.items():
    vmid, ip_value, enabled = stack_values(stack)
    if metadata["vmid"] != vmid or metadata["ip"] != ip_value:
        raise SystemExit(
            "inventory mismatch for "
            f"{stack}: inventory vmid/ip={metadata['vmid']}/{metadata['ip']}, "
            f"stack.yaml vmid/ip={vmid}/{ip_value}"
        )
    if not enabled:
        raise SystemExit(f"in-scope stack is disabled in stack.yaml: {stack}")

missing = [stack for stack in destroy_order if stack not in rows]
if missing:
    raise SystemExit("destroy order references stacks missing from inventory table: " + ", ".join(missing))

for stack in destroy_order:
    meta = rows[stack]
    print(
        "\t".join(
            [
                stack,
                meta["vmid"],
                meta["ip"],
                meta["stage"],
                meta["zone"],
                meta["service_type"],
                meta["depends_on"],
                meta["playbook"],
            ]
        )
    )
PY
}

map_inventory_rows() {
  local target_name="$1"
  local output

  output="$(resolve_inventory)" || return $?

  # shellcheck disable=SC2178
  local -n target="${target_name}"
  # shellcheck disable=SC2034
  mapfile -t target <<<"${output}"
}

run_logged() {
  local name="$1"
  shift
  local logfile="${LOG_DIR}/${name}.log"

  log "RUN ${name}: $*"
  "$@" >"${logfile}" 2>&1
  log "OK  ${name}: ${logfile}"
}

run_logged_capture_status() {
  local name="$1"
  shift
  local logfile="${LOG_DIR}/${name}.log"
  local statusfile="${LOG_DIR}/${name}.status"
  local exit_code=0

  log "RUN ${name}: $*"
  if "$@" >"${logfile}" 2>&1; then
    exit_code=0
  else
    exit_code=$?
  fi

  printf '%s\n' "${exit_code}" >"${statusfile}"
  if [[ "${exit_code}" -eq 0 ]]; then
    log "OK  ${name}: ${logfile}"
  else
    log "FAIL ${name}: ${logfile} (exit ${exit_code})"
  fi

  return 0
}

phase_source_preflight() {
  local rows=()
  map_inventory_rows rows
  log "validated inventory against current stack.yaml files"
  printf '%s\n' "${rows[@]}" | tee "${LOG_DIR}/source-preflight-stacks.log" >/dev/null
}

phase_platform_status() {
  local rows=()
  local row stack vmid ip stage zone service_type depends_on playbook
  local expected_file="${LOG_DIR}/platform-status-expected-vmids.log"
  local pct_status_file="${LOG_DIR}/pct-list.status"
  local qm_status_file="${LOG_DIR}/qm-list.status"
  local pvesm_status_file="${LOG_DIR}/pvesm-status.status"
  local pct_exit="1"
  local qm_exit="1"
  local pvesm_exit="1"

  map_inventory_rows rows

  {
    for row in "${rows[@]}"; do
      IFS=$'\t' read -r stack vmid ip stage zone service_type depends_on playbook <<<"${row}"
      printf '%s\t%s\n' "${stack}" "${vmid}"
    done
  } | sort -k2,2n >"${expected_file}"

  run_proxmox_read_only_capture_status pct list
  run_proxmox_read_only_capture_status qm list
  run_proxmox_read_only_capture_status pvesm status

  if [[ -f "${pct_status_file}" ]]; then
    pct_exit="$(<"${pct_status_file}")"
  fi
  if [[ -f "${qm_status_file}" ]]; then
    qm_exit="$(<"${qm_status_file}")"
  fi
  if [[ -f "${pvesm_status_file}" ]]; then
    pvesm_exit="$(<"${pvesm_status_file}")"
  fi

  python3 - "${expected_file}" "${LOG_DIR}/pct-list.log" "${LOG_DIR}/qm-list.log" "${LOG_DIR}" <<'PY'
import sys
from pathlib import Path

expected_path = Path(sys.argv[1])
pct_path = Path(sys.argv[2])
qm_path = Path(sys.argv[3])
log_dir = Path(sys.argv[4])


def parse_guest_log(path: Path, source: str):
    guests = []
    if not path.exists():
        return guests
    for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if line_no == 1:
            continue
        line = raw.strip()
        if not line:
            continue
        token = line.split()[0]
        if token.isdigit():
            guests.append((int(token), source, line))
    return guests


expected = {}
for raw in expected_path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not raw.strip():
        continue
    stack, vmid = raw.split("\t", 1)
    expected[int(vmid)] = stack

discovered = {}
for vmid, source, line in parse_guest_log(pct_path, "pct") + parse_guest_log(qm_path, "qm"):
    discovered[vmid] = (source, line)

present = sorted(vmid for vmid in expected if vmid in discovered)
missing = sorted(vmid for vmid in expected if vmid not in discovered)
out_of_scope = sorted(vmid for vmid in discovered if vmid not in expected)

(log_dir / "platform-status-in-scope-present.log").write_text(
    "\n".join(f"{vmid}\t{expected[vmid]}\t{discovered[vmid][0]}\t{discovered[vmid][1]}" for vmid in present) + ("\n" if present else ""),
    encoding="utf-8",
)

(log_dir / "platform-status-missing-in-scope.log").write_text(
    "\n".join(f"{vmid}\t{expected[vmid]}" for vmid in missing) + ("\n" if missing else ""),
    encoding="utf-8",
)

(log_dir / "platform-status-out-of-scope-guests.log").write_text(
    "\n".join(f"{vmid}\t{discovered[vmid][0]}\t{discovered[vmid][1]}" for vmid in out_of_scope) + ("\n" if out_of_scope else ""),
    encoding="utf-8",
)
PY

if [[ "${pct_exit}" != "0" || "${qm_exit}" != "0" || "${pvesm_exit}" != "0" ]]; then
  fail "platform-status collected evidence with one or more command failures; see ${LOG_DIR}/*.status"
fi
}

phase_plan() {
  local rows=()
  local stack vmid ip stage zone service_type depends_on playbook
  map_inventory_rows rows

  for row in "${rows[@]}"; do
    IFS=$'\t' read -r stack vmid ip stage zone service_type depends_on playbook <<<"${row}"
    run_logged_capture_status \
      "plan-destroy-${stack}" \
      "${WITH_SECRETS_PROD}" terragrunt plan -destroy \
      --working-dir "${STACKS_DIR}/${stack}" \
      -no-color
  done
}

phase_summary() {
  local rows=()
  local vmids=()
  local stack vmid ip stage zone service_type depends_on playbook
  map_inventory_rows rows

  for row in "${rows[@]}"; do
    IFS=$'\t' read -r stack vmid ip stage zone service_type depends_on playbook <<<"${row}"
    vmids+=("${vmid}")
  done

  {
    printf '# pve Infra-Only Teardown Plan Summary\n\n'
    printf '## Stamp\n\n'
    printf -- '- `%s`\n\n' "${STAMP}"

    printf '## Scope\n\n'
    printf '| Stack | VMID | IP | Stage | Zone | Service type |\n'
    printf '|---|---:|---|---|---|---|\n'
    for row in "${rows[@]}"; do
      IFS=$'\t' read -r stack vmid ip stage zone service_type depends_on playbook <<<"${row}"
      printf '| `%s` | %s | `%s` | %s | `%s` | %s |\n' \
        "${stack}" "${vmid}" "${ip}" "${stage}" "${zone}" "${service_type}"
    done
    printf '\n'

    printf '## Evidence Files\n\n'
    printf -- '- `logs/pct-list.log`\n'
    printf -- '- `logs/qm-list.log`\n'
    printf -- '- `logs/pvesm-status.log`\n'
    printf -- '- `logs/platform-status-in-scope-present.log`\n'
    printf -- '- `logs/platform-status-missing-in-scope.log`\n'
    printf -- '- `logs/platform-status-out-of-scope-guests.log`\n'
    for row in "${rows[@]}"; do
      IFS=$'\t' read -r stack vmid ip stage zone service_type depends_on playbook <<<"${row}"
      printf -- '- `logs/plan-destroy-%s.log`\n' "${stack}"
    done
    printf '\n'

    printf '## Live Platform Status\n\n'
    printf '| Check | Exit | Notes |\n'
    printf '|---|---:|---|\n'
    for check in pct-list qm-list pvesm-status; do
      local check_status_file="${LOG_DIR}/${check}.status"
      local check_exit="not-run"
      local check_notes="not collected"

      if [[ -f "${check_status_file}" ]]; then
        check_exit="$(<"${check_status_file}")"
        if [[ "${check_exit}" == "0" ]]; then
          check_notes="ok"
        else
          check_notes="BLOCKER: read-only command failed"
        fi
      fi

      printf '| `%s` | %s | %s |\n' "${check}" "${check_exit}" "${check_notes}"
    done
    printf '\n'

    if [[ -s "${LOG_DIR}/platform-status-missing-in-scope.log" ]]; then
      printf '### Missing In-Scope VMIDs\n\n'
      printf '| VMID | Stack |\n'
      printf '|---:|---|\n'
      while IFS=$'\t' read -r missing_vmid missing_stack; do
        printf '| %s | `%s` |\n' "${missing_vmid}" "${missing_stack}"
      done <"${LOG_DIR}/platform-status-missing-in-scope.log"
      printf '\n'
    fi

    if [[ -s "${LOG_DIR}/platform-status-out-of-scope-guests.log" ]]; then
      printf '### Out-Of-Scope Guests Observed On pve\n\n'
      printf '| VMID | Source | Guest line |\n'
      printf '|---:|---|---|\n'
      while IFS=$'\t' read -r out_vmid out_source out_line; do
        printf '| %s | `%s` | `%s` |\n' "${out_vmid}" "${out_source}" "${out_line}"
      done <"${LOG_DIR}/platform-status-out-of-scope-guests.log"
      printf '\n'
    fi

    printf '## Per-Stack Plan Status\n\n'
    printf '| Stack | Exit | Notes |\n'
    printf '|---|---:|---|\n'
    for row in "${rows[@]}"; do
      local status_file=""
      local plan_file=""
      local exit_code="not-run"
      local notes="plan not executed"
      local out_scope_vmid=""
      IFS=$'\t' read -r stack vmid ip stage zone service_type depends_on playbook <<<"${row}"

      status_file="${LOG_DIR}/plan-destroy-${stack}.status"
      plan_file="${LOG_DIR}/plan-destroy-${stack}.log"
      if [[ -f "${status_file}" ]]; then
        exit_code="$(<"${status_file}")"
        if [[ "${exit_code}" == "0" ]]; then
          if rg -n "pve-test" "${plan_file}" >/dev/null 2>&1; then
            notes="BLOCKER: plan mentions pve-test"
          elif out_scope_vmid="$(python3 - "${plan_file}" "${vmids[@]}" <<'PY'
import re
import sys
from pathlib import Path

plan_file = Path(sys.argv[1])
allowed_vmids = set(sys.argv[2:])

text = plan_file.read_text(encoding="utf-8", errors="replace")
found = sorted(set(re.findall(r"\bvmid\b\s*=\s*\"?(\d+)\"?", text)), key=int)
out_scope = [vmid for vmid in found if vmid not in allowed_vmids]
if out_scope:
    print(", ".join(out_scope))
PY
)" && [[ -n "${out_scope_vmid}" ]]; then
            notes="BLOCKER: out-of-scope VMID(s) in plan: ${out_scope_vmid}"
          elif rg -n "No changes\\." "${plan_file}" >/dev/null 2>&1; then
            notes="no infrastructure drift before destroy plan"
          else
            notes="review detailed destroy-plan log"
          fi
        else
          notes="BLOCKER: plan command failed"
        fi
      fi
      printf '| `%s` | %s | %s |\n' "${stack}" "${exit_code}" "${notes}"
    done
    printf '\n'

    printf '## Operator Review Checklist\n\n'
    printf '1. Confirm `pct list` and `qm list` include no unexpected in-scope/out-of-scope ambiguity.\n'
    printf '2. Confirm no per-stack destroy plan mentions `pve-test`.\n'
    printf '3. Confirm no per-stack destroy plan proposes VMIDs outside the in-scope inventory set.\n'
    printf '4. Confirm storage review from `pvesm status` matches the infra-only scope.\n'
    printf '5. Explicitly keep all out-of-scope guests on `pve` excluded from any future destructive packet.\n'
    printf '6. Treat this summary as read-only planning evidence only.\n'
  } >"${SUMMARY_FILE}"

  log "summary written to ${SUMMARY_FILE}"
}

parse_args() {
  if [[ $# -eq 0 ]]; then
    usage
    exit 1
  fi

  PHASE="$1"
  shift

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stamp)
        [[ $# -ge 2 ]] || fail "--stamp requires a value"
        STAMP="$2"
        EVIDENCE_DIR="${EVIDENCE_ROOT}/pve-infra-teardown-plan-${STAMP}"
        LOG_DIR="${EVIDENCE_DIR}/logs"
        SUMMARY_FILE="${EVIDENCE_DIR}/summary.md"
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
}

main() {
  parse_args "$@"
  ensure_dirs
  load_local_env
  target_guard_preflight

  case "${PHASE}" in
    source-preflight)
      phase_source_preflight
      ;;
    platform-status)
      phase_platform_status
      ;;
    plan)
      phase_plan
      ;;
    summary)
      phase_summary
      ;;
    *)
      fail "unknown phase: ${PHASE}"
      ;;
  esac
}

main "$@"
