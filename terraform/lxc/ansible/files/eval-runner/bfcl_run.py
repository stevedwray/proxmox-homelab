"""BFCL (Berkeley Function Calling Leaderboard) for eval-runner.

Runs BFCL v3's "simple" category (400 single-call Python cases) with
bfcl-eval 2025.8.6.2 against the server in <run>/run.json -- the same
category, package version, default temperature (0.001) and native
function-calling request shape as every historical BFCL number on
framework. There, each model had its own copy-pasted handler edited into
site-packages; here one generic handler ("eval-runner-FC") is registered
at start-up and pointed at whatever model the server is serving. Its
request is the historical handlers' (messages, model, temperature, tools;
no max_tokens, so the server's default length applies).

Usage (inside the eval-runner-bfcl image, via `runmeta.py exec`):
  bfcl_run.py <run_dir>

Output, all under <run_dir>/bfcl/:
  result/eval-runner-FC/BFCL_v3_simple_result.json   raw answers (BFCL's own)
  score/eval-runner-FC/BFCL_v3_simple_score.json     per-case verdicts
  results_<stamp>.json                               the eval-runner summary

Resuming re-runs only the cases with no answer yet, plus any that failed
with an inference error (a timeout, say). With a limit (--pilot), an evenly
spaced subset of the 400 cases is run and scored.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wrapper_common as wc  # noqa: E402

TASK = "bfcl_simple"
CATEGORY = "simple"
TOTAL_CASES = 400
MODEL_NAME = "eval-runner-FC"  # no "_": BFCL's checker maps "_" back to "/"
VERSION = "2025.8.6.2"
SERIES = "v3 simple"
TEMPERATURE = "0.001"  # `bfcl generate`'s default; no historical run changed it
RESULT_FILE = "BFCL_v3_simple_result.json"
ERROR_PREFIX = "Error during inference"


def pilot_ids(limit, total=TOTAL_CASES):
    """An evenly spaced subset of case ids (the earlier BFCL pilots used every 20th)."""
    stride = max(1, total // limit)
    return [f"{CATEGORY}_{i * stride}" for i in range(min(limit, total))]


def drop_errored(path):
    """Remove inference-error entries from a result file so a resume retries
    them (BFCL itself treats any existing entry as done). Returns how many."""
    if not os.path.exists(path):
        return 0
    with open(path) as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    keep = [e for e in entries if not str(e.get("result", "")).startswith(ERROR_PREFIX)]
    if len(keep) != len(entries):
        with open(path, "w") as fh:
            for entry in keep:
                fh.write(json.dumps(entry) + "\n")
    return len(entries) - len(keep)


def response_counts(entries):
    """(empty, errors): answers with neither a tool call nor text, and
    requests that failed outright."""
    empty = sum(1 for e in entries if e.get("result") in ("", [], None))
    errors = sum(1 for e in entries if str(e.get("result", "")).startswith(ERROR_PREFIX))
    return empty, errors


def register(base_url, model_id, api_key):
    """Add the generic eval-runner-FC model to BFCL's model table."""
    from bfcl_eval.constants import model_config as mc
    from bfcl_eval.model_handler.api_inference.openai_completion import OpenAICompletionsHandler
    from openai import OpenAI

    class EvalRunnerFCHandler(OpenAICompletionsHandler):
        def __init__(self, model_name, temperature):
            super().__init__(model_name, temperature)
            self.client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=3600)

        def _query_FC(self, inference_data):  # noqa: N802 (BFCL's name)
            message = inference_data["message"]
            tools = inference_data["tools"]
            inference_data["inference_input_log"] = {"message": repr(message), "tools": tools}
            kwargs = {"messages": message, "model": model_id, "temperature": self.temperature}
            if len(tools) > 0:
                kwargs["tools"] = tools
            return self.generate_with_backoff(**kwargs)

    mc.MODEL_CONFIG_MAPPING[MODEL_NAME] = mc.ModelConfig(
        model_name=MODEL_NAME, display_name=f"eval-runner: {model_id}", url="local", org="local",
        license="n/a", model_handler=EvalRunnerFCHandler, input_price=None, output_price=None,
        is_fc_model=True, underscore_to_dot=True,
    )


def generate(limit, project_root):
    import typer
    from bfcl_eval.__main__ import cli

    args = ["generate", "--model", MODEL_NAME, "--test-category", CATEGORY,
            "--temperature", TEMPERATURE, "--num-threads", "1"]
    if limit:
        with open(os.path.join(project_root, "test_case_ids_to_generate.json"), "w") as fh:
            json.dump({CATEGORY: pilot_ids(limit)}, fh)
        args.append("--run-ids")
    typer.main.get_command(cli)(args, standalone_mode=False)


def score():
    """Score whatever has been generated with BFCL's own AST checker (the
    path `bfcl evaluate` takes for "simple"), restricted to the generated
    cases so a pilot subset scores too. Returns (accuracy, total, entries)."""
    from bfcl_eval.constants.eval_config import POSSIBLE_ANSWER_PATH, PROMPT_PATH, RESULT_PATH, SCORE_PATH
    from bfcl_eval.eval_checker.eval_runner import ast_file_runner, get_handler
    from bfcl_eval.utils import find_file_with_suffix, load_file

    entries = load_file(RESULT_PATH / MODEL_NAME / RESULT_FILE, sort_by_id=True)
    ids = {e["id"] for e in entries}
    prompt = [p for p in load_file(find_file_with_suffix(PROMPT_PATH, CATEGORY), sort_by_id=True) if p["id"] in ids]
    answers = [a for a in load_file(find_file_with_suffix(POSSIBLE_ANSWER_PATH, CATEGORY), sort_by_id=True)
               if a["id"] in ids]
    accuracy, total = ast_file_runner(get_handler(MODEL_NAME), entries, prompt, answers, "Python",
                                      CATEGORY, MODEL_NAME, SCORE_PATH)
    return accuracy, total, entries


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: bfcl_run.py <run_dir>", file=sys.stderr)
        return 2
    run_dir = argv[0]
    record = wc.load_record(run_dir)
    project_root = os.path.join(run_dir, "bfcl")
    os.makedirs(project_root, exist_ok=True)
    # BFCL resolves its result/score paths from this at import time.
    os.environ["BFCL_PROJECT_ROOT"] = project_root

    base_url, model_id, api_key = wc.server(record)
    register(base_url, model_id, api_key)
    retried = drop_errored(os.path.join(project_root, "result", MODEL_NAME, RESULT_FILE))
    if retried:
        print(f"bfcl_run: retrying {retried} cases that failed with an inference error")
    limit = record.get("limit")
    generate(limit, project_root)
    accuracy, total, entries = score()
    empty, errors = response_counts(entries)
    path = wc.write_results(
        project_root, TASK,
        {"accuracy,none": accuracy, "correct,none": round(accuracy * total), "empty,none": empty,
         "errors,none": errors},
        total, TOTAL_CASES, limit=limit, model=model_id, base_url=base_url, harness="bfcl",
        version=VERSION, series=SERIES, runtime=wc.runtime(record),
    )
    print(f"bfcl_run: accuracy {accuracy:.4f} on {total} cases (empty {empty}, errors {errors}) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
