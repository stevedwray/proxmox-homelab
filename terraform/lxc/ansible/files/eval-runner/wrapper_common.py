"""Shared by eval-runner's own benchmark wrappers (bfcl_run.py,
agentbench_run.py, repobench_run.py).

Each wrapper runs one benchmark against the server recorded in the run's
run.json, then writes <run>/<harness>/results_<stamp>.json in the same
shape as lm_eval's results files, so summarize.py, publish.py and the
Nextcloud table treat every benchmark alike:

  {"results": {task: {metric: value, ..., "empty,none": n, "errors,none": n}},
   "n-samples": {task: {"original": N, "effective": n}},
   "config": {"limit": ..., "model_args": {...}, "gen_kwargs": {...},
              "eval_runner": {"harness", "version", "series", "exclusion",
                              "runtime", "origin", "note"}},
   "date": <unix time>}

config.eval_runner decides comparability (summarize.exclusion_reason):
series is the task's STANDARD_SERIES name for a comparable result, and
exclusion explains why a full run is not comparable (None if it is).
"""

import datetime
import json
import os
import time


def load_record(run_dir):
    with open(os.path.join(run_dir, "run.json")) as fh:
        return json.load(fh)


def server(record):
    """(OpenAI-compatible /v1 base URL, served model id, API key)."""
    base = record["server"]["base_url"].rstrip("/")
    return f"{base}/v1", record["server"]["model_id"], os.environ.get("OPENAI_API_KEY", "")


def runtime(record):
    props = (record.get("server") or {}).get("props") or {}
    return f"llama.cpp {props.get('build_info') or ''}".strip() if props else "OpenAI-compatible server"


def now_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")


def write_results(out_dir, task, metrics, n_effective, n_original, *, limit, model, base_url,
                  harness, version, series, exclusion=None, max_gen_toks=None, runtime=None,
                  origin=None, note=None, date=None, stamp=None):
    """Write one lm_eval-shaped results file; return its path."""
    os.makedirs(out_dir, exist_ok=True)
    data = {
        "results": {task: metrics},
        "n-samples": {task: {"original": n_original, "effective": n_effective}},
        "config": {
            "limit": limit,
            "model_args": {"model": model, "base_url": base_url},
            "gen_kwargs": {"max_gen_toks": max_gen_toks} if max_gen_toks else {},
            "eval_runner": {"harness": harness, "version": version, "series": series,
                            "exclusion": exclusion, "runtime": runtime, "origin": origin, "note": note},
        },
        "date": date if date is not None else time.time(),
    }
    path = os.path.join(out_dir, f"results_{stamp or now_stamp()}.json")
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    return path
