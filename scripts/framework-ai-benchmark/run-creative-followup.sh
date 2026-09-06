#!/usr/bin/env bash
set -euo pipefail

if (($# != 2)); then
  echo "Usage: $0 <benchmark-user-unit> <parent-run-directory>" >&2
  exit 2
fi

WAIT_UNIT="$1"
PARENT_RUN_DIR="$2"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="${SCRIPT_DIR}/benchmark.py"
RESULTS_ROOT="/storage/artifacts/framework-ai-benchmarks"
QUEUE_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
INDEX_FILE="${RESULTS_ROOT}/creative-followup-${QUEUE_STAMP}.tsv"

declare -a MODELS=(
  "L3.1-MOE-6X8B-Dark-RS-Dantes-Peak-HRR-R1-Uncen-36B-Q4_K_M-imat"
  "L3.2-8X4B-MOE-V2-Dark-Champion-Inst-21B-uncen-ablit-D_AU-Q4_k_m"
  "Command-R-35B-Dark-Horror-V2-D_AU-Q4_k_s"
)

echo "Waiting for ${WAIT_UNIT} to finish before creative-model follow-up."
while systemctl --user is-active --quiet "${WAIT_UNIT}"; do
  sleep 30
done

if [[ ! -f "${PARENT_RUN_DIR}/progress.json" ]] ||
   [[ "$(jq -r '.complete // false' "${PARENT_RUN_DIR}/progress.json")" != "true" ]]; then
  echo "Parent benchmark did not complete successfully; follow-up will not start." >&2
  exit 1
fi

printf 'model\trun_directory\tstatus\n' > "${INDEX_FILE}"
overall_status=0
for model in "${MODELS[@]}"; do
  run_name="$(date -u +%Y%m%dT%H%M%S)"
  run_dir="${RESULTS_ROOT}/${run_name}"
  echo "Starting creative story benchmark: ${model}"
  if env FRAMEWORK_BENCH_LLAMACPP_STORY_MODEL="${model}" \
      python3 "${HARNESS}" \
        --run-dir "${run_dir}" \
        --runtimes llamacpp \
        --suites story \
        --repetitions 3; then
    printf '%s\t%s\tcomplete\n' "${model}" "${run_dir}" >> "${INDEX_FILE}"
  else
    printf '%s\t%s\tfailed\n' "${model}" "${run_dir}" >> "${INDEX_FILE}"
    overall_status=1
  fi
done

echo "Creative follow-up index: ${INDEX_FILE}"
exit "${overall_status}"
