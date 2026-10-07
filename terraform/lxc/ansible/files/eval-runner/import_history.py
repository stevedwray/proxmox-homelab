"""One-off import of historical BFCL and AgentBench results into
eval-runner's results tree, as eval-runner results files (wrapper_common
format), so they appear in `eval-run results`, the leaderboard and the
Nextcloud table next to new runs -- as the GPQA/IFEval history already does.
Not part of any image; run by the operator (docs/eval-runner/plan.md).

  probe-bfcl <site-packages dir>
      Run with framework's BFCL venv python (~/bfcl-eval/venv/bin/python,
      dir ~/bfcl-eval/venv/lib/python3.14/site-packages):
      prints JSON describing every BFCL_v3_simple score in that venv --
      accuracy, counts, empty/error answers, date, and the Ollama tag /
      endpoint from each model's handler.
  bfcl <probe.json> <results_root>
      Write one results file per probed model under
      <results_root>/_historical/bfcl-<model>/bfcl/.
  agentbench <outputs_dir> <results_root>
      For each <outputs_dir>/<stamp>/<agent>/os-std/overall.json (garuda's
      ~/eval-harnesses/AgentBench/outputs), write a results file under
      <results_root>/_historical/agentbench-<agent>-<stamp>/agentbench/.
      100-episode runs are the comparable "100 seeded" series (the seed-42
      sample every later run used); a full 800-episode run is listed as its
      own series.
"""

import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wrapper_common as wc  # noqa: E402

BFCL_VERSION = "2025.8.6.2"


def probe_bfcl(root):
    import inspect
    os.environ.setdefault("BFCL_PROJECT_ROOT", "/tmp/bfcl-probe-root")
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING
    out = []
    for score in sorted(glob.glob(f"{root}/score/*/BFCL_v3_simple_score.json")):
        name = score.split("/")[-2]
        with open(score) as fh:
            head = json.loads(fh.readline())
        result = f"{root}/result/{name}/BFCL_v3_simple_result.json"
        empty = errors = 0
        if os.path.exists(result):
            with open(result) as fh:
                for line in fh:
                    value = json.loads(line).get("result")
                    empty += value in ("", [], None)
                    errors += str(value).startswith("Error during inference")
        cfg = MODEL_CONFIG_MAPPING.get(name)
        tag = base = None
        if cfg is not None:
            src = inspect.getsource(cfg.model_handler)
            tag = getattr(cfg.model_handler, "OLLAMA_MODEL_ID", None)
            base_match = re.search(r'getenv\("\w+",\s*"([^"]+)"\)', src)
            base = base_match.group(1) if base_match else None
        out.append({"name": name, "score": head, "mtime": os.path.getmtime(score), "empty": empty,
                    "errors": errors, "tag": tag, "base_url": base})
    return out


def bfcl_runtime(entry):
    base = entry.get("base_url") or ""
    if ":11434" in base or "-Ollama-" in entry["name"]:
        return "Ollama"
    if ":8080" in base:
        return "llama.cpp (router)"
    return "llama.cpp (router, by name)"


def bfcl_note(name):
    effort = re.search(r"-(High|Medium|Low|None)-Ollama", name)
    return f"reasoning effort {effort.group(1).lower()}" if effort else ""


def import_bfcl(probe, results_root):
    paths = []
    for entry in probe:
        score = entry["score"]
        model = entry["tag"] or re.sub(r"-FC$", "", entry["name"])
        full = score["total_count"] == 400
        stamp = datetime.datetime.fromtimestamp(entry["mtime"], datetime.timezone.utc)
        paths.append(wc.write_results(
            os.path.join(results_root, "_historical", f"bfcl-{entry['name']}", "bfcl"), "bfcl_simple",
            {"accuracy,none": score["accuracy"], "correct,none": score["correct_count"],
             "empty,none": entry["empty"], "errors,none": entry["errors"]},
            score["total_count"], 400, limit=None if full else score["total_count"], model=model,
            base_url=entry.get("base_url"), harness="bfcl", version=BFCL_VERSION,
            series="v3 simple" if full else None, runtime=bfcl_runtime(entry), origin="framework",
            note=bfcl_note(entry["name"]), date=entry["mtime"], stamp=stamp.strftime("%Y-%m-%dT%H-%M-%S.000000"),
        ))
    return paths


def import_agentbench(outputs_dir, results_root):
    import agentbench_run
    paths = []
    for overall_path in sorted(glob.glob(os.path.join(outputs_dir, "*", "*", "os-std", "overall.json"))):
        task_dir = os.path.dirname(overall_path)
        agent = os.path.basename(os.path.dirname(task_dir))
        run_stamp = os.path.basename(os.path.dirname(os.path.dirname(task_dir)))
        with open(overall_path) as fh:
            overall = json.load(fh)["custom"]["overall"]
        runs = os.path.join(task_dir, "runs.jsonl")
        _, empty, errors = agentbench_run.episode_counts(runs)
        sampled = overall["total"] == agentbench_run.SAMPLE_LIMIT
        series = agentbench_run.SERIES if sampled else f"{overall['total']} full"
        exclusion = None if sampled else (f"all {overall['total']} episodes (separate series; the ranked "
                                          f"series is the seed-42 sample of {agentbench_run.SAMPLE_LIMIT})")
        when = datetime.datetime.strptime(run_stamp, "%Y-%m-%d-%H-%M-%S")
        paths.append(wc.write_results(
            os.path.join(results_root, "_historical", f"agentbench-{agent}-{run_stamp}", "agentbench"),
            "agentbench_os_std",
            {"success_rate,none": overall["acc"], "passed,none": overall["pass"],
             "injection_success_rate,none": agentbench_run.injection_rate(runs) if os.path.exists(runs) else None,
             "empty,none": empty, "errors,none": errors},
            overall["total"], agentbench_run.TOTAL_EPISODES, limit=None, model=agent, base_url=None,
            harness="agentbench", version="0cfef97 (garuda)", series=series, exclusion=exclusion,
            max_gen_toks=agentbench_run.MAX_TOKENS, runtime="Ollama", origin="garuda",
            date=when.replace(tzinfo=datetime.timezone.utc).timestamp(),
            stamp=when.strftime("%Y-%m-%dT%H-%M-%S.000000"),
        ))
    return paths


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if argv[:1] == ["probe-bfcl"] and len(argv) == 2:
        print(json.dumps(probe_bfcl(argv[1])))
        return 0
    if argv[:1] == ["bfcl"] and len(argv) == 3:
        with open(argv[1]) as fh:
            paths = import_bfcl(json.load(fh), argv[2])
    elif argv[:1] == ["agentbench"] and len(argv) == 3:
        paths = import_agentbench(argv[1], argv[2])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
