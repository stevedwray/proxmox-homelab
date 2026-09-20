#!/bin/bash
# Prepares (but does not execute) a live CyberSecEval autonomous-uplift
# benchmark run against the cyber range (plan §7/§11/§13). Generates a
# fresh prompt dataset from cyber_range_pairs.json and prints the exact
# benchmark.run command that would trigger the live run -- deliberately
# stops short of running it, since that step makes real SSH connections
# and drives an actual attack against the range for up to 100 shots.
#
# Extra args are passed through to test_case_generator, e.g.:
#   ./run-autonomous-uplift.sh --runs-per-range=2 --shots-per-run=20
set -euo pipefail

REPO=/srv/cyberseceval/repo/PurpleLlama
VENV=/srv/cyberseceval/.venv
CONFIG=/srv/cyberseceval/config
RUN_DIR="/srv/cyberseceval/runs/autonomous-uplift-$(date +%Y%m%d-%H%M%S)"
mkdir -p "${RUN_DIR}"

cd "${REPO}"

"${VENV}/bin/python3" -m CybersecurityBenchmarks.datasets.autonomous_uplift.test_case_generator \
  --ssh-key-file="${CONFIG}/cse-kali-agent-key" \
  --ssh-username=kali \
  --cyber-range-file="${CONFIG}/cyber_range_pairs.json" \
  --system-prompt-file="${REPO}/CybersecurityBenchmarks/datasets/autonomous_uplift/in/system_prompt.txt" \
  --out-file="${RUN_DIR}/autonomous_prompts.json" \
  "$@"

echo ""
echo "Prompts written to ${RUN_DIR}/autonomous_prompts.json"
echo ""
echo "This does NOT run the live benchmark. To actually run it (real SSH"
echo "connections and a real attack against the range, up to N shots):"
echo ""
echo "  ${VENV}/bin/python3 -m CybersecurityBenchmarks.benchmark.run \\"
echo "    --benchmark=autonomous-uplift \\"
echo "    --prompt-path=${RUN_DIR}/autonomous_prompts.json \\"
echo "    --response-path=${RUN_DIR}/autonomous_responses.json \\"
echo "    --llm-under-test=<SPECIFICATION> \\"
echo "    --only-generate-llm-responses"
