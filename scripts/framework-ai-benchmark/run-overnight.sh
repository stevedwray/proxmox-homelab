#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${SCRIPT_DIR}/benchmark.py"
DEFAULT_RESULTS_ROOT="/storage/artifacts/framework-ai-benchmarks"
RESULTS_ROOT="${FRAMEWORK_BENCH_RESULTS_ROOT:-${DEFAULT_RESULTS_ROOT}}"

usage() {
  cat <<'EOF'
Usage: run-overnight.sh [launcher options] [benchmark options]

Launcher options:
  --foreground       Run in this terminal instead of a detached user service.
  --status           Show the newest run's progress and recent log output.
  --smoke            Run one repetition with shortened generation limits.
  -h, --help         Show this help and the benchmark options.

The default starts a detached systemd user service with lingering enabled, so
the test continues after SSH and VS Code close. Results are written below
/storage/artifacts/framework-ai-benchmarks unless FRAMEWORK_BENCH_RESULTS_ROOT
overrides it.
EOF
}

show_status() {
  local latest=""
  if [[ -d "${RESULTS_ROOT}" ]]; then
    latest="$(find "${RESULTS_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
  fi
  systemctl --user list-units 'framework-ai-benchmark-*' --all --no-pager || true
  if [[ -z "${latest}" ]]; then
    echo "No benchmark runs found below ${RESULTS_ROOT}."
    return
  fi
  echo "Latest run: ${latest}"
  if [[ -f "${latest}/progress.json" ]]; then
    python3 -m json.tool "${latest}/progress.json"
  fi
  if [[ -f "${latest}/run.log" ]]; then
    echo "Recent log:"
    tail -n 30 "${latest}/run.log"
  fi
}

foreground=false
smoke=false
declare -a harness_args=()
while (($#)); do
  case "$1" in
    --foreground)
      foreground=true
      ;;
    --status)
      show_status
      exit 0
      ;;
    --smoke)
      smoke=true
      ;;
    --results-root)
      (($# >= 2)) || { echo "--results-root requires a path" >&2; exit 2; }
      RESULTS_ROOT="$2"
      harness_args+=("$1" "$2")
      shift
      ;;
    -h|--help)
      usage
      echo
      python3 "${HARNESS}" --help
      exit 0
      ;;
    *)
      harness_args+=("$1")
      ;;
  esac
  shift
done

[[ -r "${HARNESS}" ]] || { echo "Harness not found: ${HARNESS}" >&2; exit 1; }
if ! mkdir -p "${RESULTS_ROOT}" 2>/dev/null; then
  if [[ "${RESULTS_ROOT}" == "${DEFAULT_RESULTS_ROOT}" ]]; then
    sudo -n install -d -m 0750 -o "$(id -un)" -g "$(id -gn)" "${RESULTS_ROOT}"
  else
    echo "Cannot create results directory: ${RESULTS_ROOT}" >&2
    exit 1
  fi
fi

if [[ "${smoke}" == true ]]; then
  harness_args+=(--repetitions 1 --smoke)
fi

if [[ "${foreground}" == true ]]; then
  exec python3 "${HARNESS}" --results-root "${RESULTS_ROOT}" "${harness_args[@]}"
fi

if [[ "$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null || true)" != "yes" ]]; then
  sudo -n loginctl enable-linger "${USER}" || {
    echo "Cannot enable systemd lingering non-interactively; rerun with --foreground or configure sudo." >&2
    exit 1
  }
fi

run_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
unit="framework-ai-benchmark-${run_stamp,,}"
systemd-run --user --unit "${unit}" --collect \
  --property=Nice=10 \
  --property=IOSchedulingClass=best-effort \
  --property=IOSchedulingPriority=6 \
  python3 "${HARNESS}" --results-root "${RESULTS_ROOT}" "${harness_args[@]}"

echo "Started ${unit}. You can close this terminal and VS Code."
echo "Check progress with: ${BASH_SOURCE[0]} --status"
echo "Follow service logs with: journalctl --user -fu ${unit}"
