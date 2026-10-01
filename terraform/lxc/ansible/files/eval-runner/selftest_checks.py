"""Assertions run by selftest.sh after lm_eval has talked to mock_openai.py.

  requests  Every chat-completion request lm_eval sent carries the settings
            the eval battery depends on: max_tokens 8192 (the Bug 6
            regression guard), temperature 0 (greedy, as every historical
            result used), seed 1234, the served model id, and a non-empty
            chat message list ending in a user turn. Also checks the count.
  flags     summarize.py's empty-response flags add up to what the mock was
            told to produce, and run.json carries a fingerprint and props.
  publish   After publishing twice to mock_nextcloud.py: one table with every
            column, the expected rows (no duplicates from the second
            publish), every view, one share, the report files including
            leaderboard.xlsx, and the stale leaderboard.csv deleted.
"""

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import publish  # noqa: E402
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


def publish_errors(state, expected_rows, run):
    errors = []
    if [t["title"] for t in state["tables"]] != [publish.TABLE_TITLE]:
        errors.append(f"expected exactly one '{publish.TABLE_TITLE}' table, got {state['tables']}")
    titles = [c["title"] for c in state["columns"]]
    if titles != [t for t, _ in publish.COLUMNS]:
        errors.append(f"columns {titles} don't match publish.COLUMNS")
    if len(state["rows"]) != expected_rows:
        errors.append(f"expected {expected_rows} rows, table has {len(state['rows'])}")
    if state["tables"] and len(state["tables"][0].get("columnSettings") or []) != len(publish.COLUMNS):
        errors.append("table column order (OCS v2 columnSettings) was not applied")
    if len(state["views"]) != len(publish.VIEWS) or len(state["shares"]) != 1:
        errors.append(f"expected {len(publish.VIEWS)} views and 1 share, got "
                      f"{len(state['views'])} and {len(state['shares'])}")
    for rel in ("leaderboard.md", "leaderboard.xlsx", "findings.md", f"runs/{run}/report.md",
                f"runs/{run}/manifest.json"):
        if f"{publish.FOLDER}/{rel}" not in state["files"]:
            errors.append(f"missing published file {rel}")
    xlsx = state["files"].get(f"{publish.FOLDER}/leaderboard.xlsx", "")
    if xlsx and not (xlsx.startswith("<binary") and xlsx.endswith(" zip>")):
        errors.append(f"leaderboard.xlsx is not a zip container: {xlsx[:60]!r}")
    for rel in publish.STALE_FILES:
        if f"{publish.FOLDER}/{rel}" not in state.get("deleted", []):
            errors.append(f"stale file {rel} was not deleted")
    if any("samples_" in name for name in state["files"]):
        errors.append("a samples file was published (GPQA questions must not leave the CT)")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests")
    parser.add_argument("--expect-requests", type=int)
    parser.add_argument("--model")
    parser.add_argument("--run-dir")
    parser.add_argument("--expect-empty", type=int)
    parser.add_argument("--nextcloud-state", help="mock_nextcloud.py /_mock/state URL")
    parser.add_argument("--expect-rows", type=int)
    parser.add_argument("--published-run")
    args = parser.parse_args(argv)

    errors = []
    if args.requests:
        errors += request_errors(args.requests, args.expect_requests, args.model)
    if args.run_dir is not None:
        errors += flag_errors(args.run_dir, args.expect_empty)
    if args.nextcloud_state:
        with urllib.request.urlopen(args.nextcloud_state, timeout=10) as resp:
            errors += publish_errors(json.load(resp), args.expect_rows, args.published_run)
    for line in errors:
        print(f"FAIL: {line}", file=sys.stderr)
    if errors:
        return 1
    print("checks OK" + (f" ({args.expect_requests} requests)" if args.requests else " (publish)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
