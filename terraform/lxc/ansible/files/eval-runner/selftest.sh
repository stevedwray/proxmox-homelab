#!/bin/sh
# eval-runner self-test, run inside the eval-runner image by
# `eval-run selftest`. Starts mock_openai.py on 127.0.0.1:18080 and runs
# both tasks at --limit 2 against it, with the same lm_eval flags as a
# real run. That checks the gated GPQA download (HF_TOKEN), IFEval's nltk
# data, request/response handling, scoring and result files -- without
# Framework or its GPU. Scores are meaningless (canned replies); only
# completion and file shape are checked, by summarize.py --check.
set -eu

out="/results/_selftest/${SELFTEST_RUN:?SELFTEST_RUN must be set}"

python /opt/eval-runner/mock_openai.py &
mock_pid=$!
trap 'kill "$mock_pid" 2>/dev/null || true' EXIT

i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18080/v1/models', timeout=1)" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 50 ]; then
    echo "selftest FAILED: mock server did not start" >&2
    exit 1
  fi
  sleep 0.2
done

OPENAI_API_KEY=selftest lm_eval run \
  --model local-chat-completions \
  --model_args "base_url=http://127.0.0.1:18080/v1/chat/completions,model=selftest-mock,num_concurrent=1,tokenized_requests=False,timeout=60" \
  --tasks gpqa_diamond_cot_zeroshot,ifeval --apply_chat_template --log_samples \
  --gen_kwargs max_gen_toks=8192 --limit 2 \
  --output_path "$out"

python /opt/eval-runner/summarize.py --check "$out"
