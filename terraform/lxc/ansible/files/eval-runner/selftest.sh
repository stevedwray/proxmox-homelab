#!/bin/sh
# eval-runner self-test, run inside the eval-runner image by
# `eval-run selftest` (and by the deploy, as a gate). Uses the same
# runmeta.py start/exec/check path as a real run, against mock_openai.py
# instead of Framework -- no GPU. Proves, in order:
#   1. a run (both tasks, --limit 2) completes: gated GPQA download
#      (HF_TOKEN), IFEval nltk data, scoring, result files
#   2. every request carried max_tokens 8192, temperature 0, seed 1234 and
#      the served model id; empty-response flags count correctly
#   3. resume: re-running the same run sends zero new requests (cache)
#   4. `runmeta check` passes against the same server and exits 3 against
#      a server that reports a different model_path
#   5. publish (the real HTTP client) to mock_nextcloud.py twice: report
#      files, one table with all columns and views, rows upserted without
#      duplicates, the share, and no samples files uploaded
# Scores are meaningless (canned replies).
set -eu

d=/opt/eval-runner
root=/results/_selftest
log=/tmp/selftest-requests.jsonl
pids=""
cleanup() {
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

start_mock() {
  MOCK_PORT="$1" MOCK_MODEL_PATH="$2" MOCK_REQUEST_LOG="$log" MOCK_EMPTY_EVERY=2 \
    python "$d/mock_openai.py" &
  pids="$pids $!"
  i=0
  until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$1/v1/models', timeout=1)" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 50 ]; then
      echo "selftest FAILED: mock server on :$1 did not start" >&2
      exit 1
    fi
    sleep 0.2
  done
}

# Keep only the 5 most recent selftest runs (~140 KB each; one per deploy).
# Names end in a UTC stamp, so a reverse name sort is newest-first.
mkdir -p "$root"
find "$root" -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +5 | while read -r old; do
  rm -rf "$old"
done

rm -f "$log"
export OPENAI_API_KEY=selftest
start_mock 18080 /models/selftest-mock.gguf

echo "== 1. run both tasks at --limit 2 against the mock"
run=$(python "$d/runmeta.py" start --base-url http://127.0.0.1:18080 --task both --limit 2 \
  --results-root "$root" --stamp "${SELFTEST_RUN:?SELFTEST_RUN must be set}" --note selftest)
dir="$root/$run"
python "$d/runmeta.py" exec "$dir"

echo "== 2. request settings and response flags"
python "$d/selftest_checks.py" --requests "$log" --expect-requests 4 --model selftest-mock \
  --run-dir "$dir" --expect-empty 2
python "$d/summarize.py" --check "$dir"

echo "== 3. resume replays from cache (no new requests)"
python "$d/runmeta.py" check "$dir"
python "$d/runmeta.py" exec "$dir"
python "$d/selftest_checks.py" --requests "$log" --expect-requests 4 --model selftest-mock

echo "== 4. a changed server is detected"
start_mock 18081 /models/some-other-model.gguf
set +e
python "$d/runmeta.py" check "$dir" --base-url http://127.0.0.1:18081
rc=$?
set -e
if [ "$rc" -ne 3 ]; then
  echo "selftest FAILED: runmeta check returned $rc for a changed server, want 3" >&2
  exit 1
fi

echo "== 5. publish to a stand-in Nextcloud, twice (no duplicates)"
MOCK_NC_PORT=18090 python "$d/mock_nextcloud.py" &
pids="$pids $!"
i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18090/_mock/state', timeout=1)" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 50 ]; then
    echo "selftest FAILED: mock Nextcloud did not start" >&2
    exit 1
  fi
  sleep 0.2
done
pubroot=$(mktemp -d)
cp -r "$dir" "$pubroot/"
for _ in 1 2; do
  NEXTCLOUD_EVAL_REPORTS_URL=http://127.0.0.1:18090 NEXTCLOUD_EVAL_REPORTS_USER=eval-reports \
    NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD=selftest NEXTCLOUD_EVAL_TABLE_SHARE_WITH=steve \
    python "$d/publish.py" --results-root "$pubroot"
done
python "$d/selftest_checks.py" --nextcloud-state http://127.0.0.1:18090/_mock/state \
  --expect-rows 2 --published-run "$run"
rm -rf "$pubroot"

echo "selftest OK"
