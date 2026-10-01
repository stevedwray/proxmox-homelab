"""Assertions run by selftest.sh after lm_eval has talked to mock_openai.py.

  requests  Every chat-completion request lm_eval sent carries the settings
            the eval battery depends on: max_tokens 8192 (the Bug 6
            regression guard), temperature 0 (greedy, as every historical
            result used), seed 1234, the served model id, and a non-empty
            chat message list ending in a user turn. Also checks the count.
  flags     summarize.py's empty-response flags add up to what the mock was
            told to produce, and run.json carries a fingerprint and props.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runmeta  # noqa: E402
import summarize  # noqa: E402

EXPECTED_TEMPERATURE = 0
EXPECTED_SEED = 1234


def request_errors(path, expected_count, model):
    with open(path) as fh:
        requests = [json.loads(line) for line in fh if line.strip()]
    errors = []
    if len(requests) != expected_count:
        errors.append(f"expected {expected_count} requests, mock saw {len(requests)}")
    for i, req in enumerate(requests, 1):
        if req.get("max_tokens") != runmeta.MAX_GEN_TOKS:
            errors.append(f"request {i}: max_tokens {req.get('max_tokens')!r}, want {runmeta.MAX_GEN_TOKS}")
        if req.get("temperature") != EXPECTED_TEMPERATURE:
            errors.append(f"request {i}: temperature {req.get('temperature')!r}, want {EXPECTED_TEMPERATURE}")
        if req.get("seed") != EXPECTED_SEED:
            errors.append(f"request {i}: seed {req.get('seed')!r}, want {EXPECTED_SEED}")
        if req.get("model") != model:
            errors.append(f"request {i}: model {req.get('model')!r}, want {model!r}")
        messages = req.get("messages")
        if not isinstance(messages, list) or not messages or messages[-1].get("role") != "user":
            errors.append(f"request {i}: messages must be a non-empty list ending with a user turn")
    return errors


def flag_errors(run_dir, expected_empty):
    errors = []
    found = summarize.load(run_dir)
    total_empty = 0
    for task in summarize.HEADLINE:
        entry = found.get(task)
        if not entry or not entry["samples"]:
            errors.append(f"{task}: no results/samples file")
            continue
        total_empty += summarize.response_flags(entry["samples"], task)["empty"]
    if total_empty != expected_empty:
        errors.append(f"expected {expected_empty} empty responses across tasks, summarize counted {total_empty}")
    record = runmeta.load_record(run_dir)
    if not record.get("fingerprint") or not (record.get("server") or {}).get("props"):
        errors.append("run.json is missing the server fingerprint or props")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--expect-requests", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--expect-empty", type=int)
    args = parser.parse_args(argv)

    errors = request_errors(args.requests, args.expect_requests, args.model)
    if args.run_dir is not None:
        errors += flag_errors(args.run_dir, args.expect_empty)
    for line in errors:
        print(f"FAIL: {line}", file=sys.stderr)
    if errors:
        return 1
    print(f"checks OK ({args.expect_requests} requests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
