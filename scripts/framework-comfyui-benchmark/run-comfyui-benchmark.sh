#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${SCRIPT_DIR}/comfyui_benchmark.py"
DEFAULT_RESULTS_ROOT="/storage/artifacts/framework-ai-benchmarks/comfyui"
RESULTS_ROOT="${FRAMEWORK_COMFYUI_RESULTS_ROOT:-${DEFAULT_RESULTS_ROOT}}"

usage() {
  cat <<'EOF'
Usage: run-comfyui-benchmark.sh [options]

Modes:
  --smoke            One 512x512, four-step functional image test.
  --benchmark        Eight-image performance and use-case suite (default).

Launcher options:
  --foreground       Run in this terminal instead of a detached user service.
  --status           Show active units and the newest run's progress.
  --results-root P   Override the results directory.
  -h, --help         Show this help and harness options.

Detached runs use a systemd user service with lingering, so SSH and VS Code may
be closed. Powering the Framework off still stops the test.
EOF
}

show_status() {
  local latest=""
  systemctl --user list-units 'framework-comfyui-benchmark-*' --all --no-pager || true
  if [[ -d "${RESULTS_ROOT}" ]]; then
    latest="$(find "${RESULTS_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
  fi
  if [[ -z "${latest}" ]]; then
    echo "No ComfyUI benchmark runs found below ${RESULTS_ROOT}."
    return
  fi
  echo "Latest run: ${latest}"
  [[ ! -f "${latest}/progress.json" ]] || python3 -m json.tool "${latest}/progress.json"
  if [[ -f "${latest}/run.log" ]]; then
    echo "Recent log:"
    tail -n 30 "${latest}/run.log"
  fi
}

foreground=false
mode=benchmark
declare -a harness_args=()
while (($#)); do
  case "$1" in
    --foreground) foreground=true ;;
    --status) show_status; exit 0 ;;
    --smoke) mode=smoke ;;
    --benchmark) mode=benchmark ;;
    --results-root)
      (($# >= 2)) || { echo "--results-root requires a path" >&2; exit 2; }
      RESULTS_ROOT="$2"
      shift
      ;;
    -h|--help)
      usage
      echo
      python3 "${HARNESS}" --help
      exit 0
      ;;
    *) harness_args+=("$1") ;;
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

if [[ "${foreground}" == true ]]; then
  exec python3 "${HARNESS}" --mode "${mode}" --results-root "${RESULTS_ROOT}" "${harness_args[@]}"
fi

if [[ "$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null || true)" != "yes" ]]; then
  sudo -n loginctl enable-linger "${USER}" || {
    echo "Cannot enable systemd lingering; rerun with --foreground or configure sudo." >&2
    exit 1
  }
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
unit="framework-comfyui-benchmark-${mode}-${stamp,,}"
systemd-run --user --unit "${unit}" --collect \
  --property=Nice=10 \
  --property=IOSchedulingClass=best-effort \
  --property=IOSchedulingPriority=6 \
  python3 "${HARNESS}" --mode "${mode}" --results-root "${RESULTS_ROOT}" "${harness_args[@]}"

echo "Started ${unit}. You can close this terminal and VS Code."
echo "Check progress with: ${BASH_SOURCE[0]} --status"
