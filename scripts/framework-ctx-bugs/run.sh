#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_ROOT="${FRAMEWORK_CTX_RESULTS_ROOT:-/storage/artifacts/framework-ctx-bugs}"
foreground=false
status=false
run_dir=""
declare -a harness_args=()

usage() {
  cat <<'EOF'
Usage: run.sh [--foreground | --status] [ctx_bugs.py options]

Default: a detached systemd user unit, with lingering enabled.
--foreground runs in this terminal; --status reads progress and recent logs.
--results-root PATH selects the output root (also used by --status).
--run-dir PATH resumes a run (or shows that run with --status).
Production runs require the production approval described in the repository
instructions. This launcher does not grant approval or deploy anything.
EOF
}

while (($#)); do
  case "$1" in
    --foreground) foreground=true ;;
    --status) status=true ;;
    --results-root|--run-dir)
      (($# >= 2)) || { echo "$1 requires a path" >&2; exit 2; }
      if [[ "$1" == --results-root ]]; then RESULTS_ROOT="$2"; else run_dir="$2"; fi
      harness_args+=("$1" "$2")
      shift
      ;;
    -h|--help)
      usage
      python3 "${SCRIPT_DIR}/ctx_bugs.py" --help
      exit 0
      ;;
    *) harness_args+=("$1") ;;
  esac
  shift
done

if [[ "${status}" == true ]]; then
  systemctl --user list-units 'framework-ctx-bugs-*' --all --no-pager || true
  latest="${run_dir}"
  if [[ -z "${latest}" && -d "${RESULTS_ROOT}" ]]; then
    latest="$(python3 - "${RESULTS_ROOT}" <<'PY'
import sys
from pathlib import Path
paths = [p for p in Path(sys.argv[1]).iterdir() if p.is_dir() and (p / 'run.json').is_file()]
print(max(paths, key=lambda p: (p / 'run.json').stat().st_mtime) if paths else '')
PY
)"
  fi
  if [[ -z "${latest}" ]]; then
    echo "No runs below ${RESULTS_ROOT}."
    exit 0
  fi
  echo "Run: ${latest}"
  [[ ! -f "${latest}/progress.json" ]] || python3 -m json.tool "${latest}/progress.json"
  [[ ! -f "${latest}/run.log" ]] || tail -n 30 "${latest}/run.log"
  exit 0
fi

mkdir -p "${RESULTS_ROOT}"
if [[ "${foreground}" == true ]]; then
  exec python3 "${SCRIPT_DIR}/ctx_bugs.py" --results-root "${RESULTS_ROOT}" "${harness_args[@]}"
fi

if [[ "$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null || true)" != yes ]]; then
  sudo -n loginctl enable-linger "${USER}" || {
    echo 'Configure user lingering or use --foreground.' >&2
    exit 1
  }
fi
run_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
unit="framework-ctx-bugs-${run_stamp,,}"
systemd-run --user --unit "${unit}" --collect \
  --property=Nice=10 \
  --property=IOSchedulingClass=best-effort \
  --property=IOSchedulingPriority=6 \
  python3 "${SCRIPT_DIR}/ctx_bugs.py" --results-root "${RESULTS_ROOT}" "${harness_args[@]}"
echo "Started ${unit}."
echo "Status: ${BASH_SOURCE[0]} --status --results-root ${RESULTS_ROOT}"
echo "Service log: journalctl --user -fu ${unit}"
