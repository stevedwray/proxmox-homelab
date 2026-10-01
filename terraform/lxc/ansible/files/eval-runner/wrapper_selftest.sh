#!/bin/sh
# Self-test for one of eval-runner's benchmark wrappers (bfcl, agentbench,
# repobench), run inside that wrapper's image by `eval-run selftest` (and
# by the deploy, as a gate). Same runmeta.py start/exec path as a real run,
# against mock_openai.py instead of Framework -- no GPU. Proves:
#   1. a --limit run completes and writes an eval-runner results file
#      that summarize.py accepts (numeric headline metric)
#   2. every request matched the historical request shape for this
#      benchmark (selftest_checks.py --harness), with the right count
#   3. resume: re-running the same run sends zero new requests
# Scores are meaningless (canned replies).
#
# Usage: wrapper_selftest.sh <harness> <limit> <expected requests>
set -eu

harness="$1"
limit="$2"
expect="$3"
d=/opt/eval-runner
root=/results/_selftest
log="/tmp/selftest-${harness}-requests.jsonl"
pids=""
cleanup() {
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

# AgentBench's agent parses "Act: answer(...)" -- answering at once makes
# every episode one request long.
case "$harness" in
  agentbench) reply="Think: done. Act: answer(0)" ;;
  repobench) reply="return value" ;;
  *) reply="ok" ;;
esac

rm -f "$log"
export OPENAI_API_KEY=selftest
MOCK_PORT=18082 MOCK_REQUEST_LOG="$log" MOCK_REPLY="$reply" python "$d/mock_openai.py" &
pids="$pids $!"
i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=1)" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 50 ]; then
    echo "selftest FAILED: mock server did not start" >&2
    exit 1
  fi
  sleep 0.2
done

mkdir -p "$root"
echo "== $harness 1. run at --limit $limit against the mock"
run=$(python "$d/runmeta.py" start --base-url http://127.0.0.1:18082 --task "$harness" --limit "$limit" \
  --results-root "$root" --stamp "${SELFTEST_RUN:?SELFTEST_RUN must be set}" --note selftest)
dir="$root/$run"
python "$d/runmeta.py" exec "$dir"
python "$d/summarize.py" --check "$dir"

echo "== $harness 2. request shape"
python "$d/selftest_checks.py" --harness "$harness" --requests "$log" --expect-requests "$expect" \
  --model selftest-mock

echo "== $harness 3. resume sends no new requests"
python "$d/runmeta.py" exec "$dir"
python "$d/selftest_checks.py" --harness "$harness" --requests "$log" --expect-requests "$expect" \
  --model selftest-mock

echo "$harness selftest OK"
