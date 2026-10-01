"""Print headline GPQA/IFEval numbers for eval-run result directories.

With no arguments, summarises every run directory under /results except
those starting with "_" (selftest output). With --check, exits non-zero
unless every given directory holds results for both tasks with numeric
headline metrics -- the selftest uses this as one of its checks.

Each task also gets response-quality flags read from its samples file,
counted per question:
  empty     the raw response was empty -- typically a reasoning model that
            used its whole token budget thinking, so the answer never came
  unparsed  (GPQA only) flexible-extract found no answer letter
Treat a score with many of either as an infrastructure/config problem to
inspect, not as the model's capability. (Deliberately no "accuracy on
answered questions" figure: the questions a model finishes inside the
token budget skew easy, and differ per model, so it isn't comparable.)

Historical results (the Ollama-era runs on framework, imported once into
/results/_historical/<source-dir>/) are listed in a second section. Only
results that are comparable with eval-runner's are shown: full runs
(no --limit) with max_gen_toks=8192. Everything else is listed as
excluded, with the reason (pilot, the Bug 6 missing token cap, or a
different token budget).

Token budget series: a full run at a larger max_gen_toks (eval-run
--max-gen-toks, e.g. 32768) is a separate series. (Smaller budgets are
treated like Bug 6: truncation, not a series.) It is ranked only
against other runs at the same budget, never against the 8192 series --
a bigger budget lets reasoning models finish answers they'd otherwise
lose, so the scores measure something different.
"""

import argparse
import glob
import json
import os
import sys

RESULTS_ROOT = "/results"
HISTORICAL_DIR = "_historical"
MAX_GEN_TOKS = 8192

HEADLINE = {
    "gpqa_diamond_cot_zeroshot": [
        ("GPQA flex", "exact_match,flexible-extract"),
        ("GPQA strict", "exact_match,strict-match"),
    ],
    "ifeval": [
        ("IFEval p-strict", "prompt_level_strict_acc,none"),
        ("IFEval p-loose", "prompt_level_loose_acc,none"),
    ],
}


def _results_stamp(path):
    """results_<stamp>.json -> <stamp>, shared with that run's samples files."""
    return os.path.basename(path)[len("results_"):-len(".json")]


def _max_gen_toks(gen_kwargs):
    """lm_eval records gen_kwargs as a dict or as a 'k=v,k=v' string."""
    if isinstance(gen_kwargs, dict):
        value = gen_kwargs.get("max_gen_toks")
    else:
        pairs = dict(part.split("=", 1) for part in str(gen_kwargs or "").split(",") if "=" in part)
        value = pairs.get("max_gen_toks")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def exclusion_reason(data):
    """None if a results file is comparable with eval-runner runs, else why not."""
    config = data.get("config", {})
    if config.get("limit") is not None:
        return f"pilot (limit {config['limit']:g})" if isinstance(config["limit"], (int, float)) else "pilot"
    budget = _max_gen_toks(config.get("gen_kwargs"))
    if budget is None or budget < MAX_GEN_TOKS:
        return f"no max_gen_toks={MAX_GEN_TOKS} (Bug 6 truncation risk)"
    if budget != MAX_GEN_TOKS:
        return f"token budget {budget} (separate {series_label(budget)} series)"
    return None


def series_label(budget):
    """8192 -> '8k', 32768 -> '32k', other values unchanged."""
    return f"{budget // 1024}k" if budget % 1024 == 0 else str(budget)


def series(data):
    """The token-budget series a results file is ranked in ('8k', '32k', ...),
    or None for pilots and runs without a token cap."""
    config = data.get("config", {})
    budget = _max_gen_toks(config.get("gen_kwargs"))
    if config.get("limit") is not None or budget is None or budget < MAX_GEN_TOKS:
        return None
    return series_label(budget)


def model_name(data):
    model_args = data.get("config", {}).get("model_args")
    if isinstance(model_args, dict):
        return model_args.get("model")
    pairs = dict(part.split("=", 1) for part in str(model_args or "").split(",") if "=" in part)
    return pairs.get("model")


def load(run_dir, comparable_only=False):
    """Map task -> {metrics, n, samples, model}, the newest results file winning.

    With comparable_only, results files failing exclusion_reason() are skipped.
    """
    found = {}
    pattern = os.path.join(run_dir, "**", "results_*.json")
    for path in sorted(glob.glob(pattern, recursive=True)):
        with open(path) as fh:
            data = json.load(fh)
        if comparable_only and exclusion_reason(data):
            continue
        stamp = _results_stamp(path)
        for task, metrics in data.get("results", {}).items():
            if task in HEADLINE:
                samples = os.path.join(os.path.dirname(path), f"samples_{task}_{stamp}.jsonl")
                found[task] = {
                    "metrics": metrics,
                    "n": data.get("n-samples", {}).get(task, {}).get("effective"),
                    "samples": samples if os.path.exists(samples) else None,
                    "model": model_name(data),
                }
    return found


def response_flags(samples_path, task):
    """Count empty (and, for GPQA, unparsed) responses per question."""
    empty_by_doc = {}
    unparsed = set()
    with open(samples_path) as fh:
        for line in fh:
            row = json.loads(line)
            doc = row["doc_id"]
            resps = row.get("resps") or [[""]]
            raw = resps[0][0] if resps[0] else ""
            empty_by_doc[doc] = not str(raw).strip()
            if (task.startswith("gpqa") and row.get("filter") == "flexible-extract"
                    and (row.get("filtered_resps") or [None])[0] == "[invalid]"):
                unparsed.add(doc)
    return {
        "questions": len(empty_by_doc),
        "empty": sum(empty_by_doc.values()),
        "unparsed": len(unparsed) if task.startswith("gpqa") else None,
    }


def _flag_text(task, entry):
    if not entry["samples"]:
        return "[no samples file]"
    flags = response_flags(entry["samples"], task)
    text = f"empty {flags['empty']}"
    if flags["unparsed"] is not None:
        text += f", unparsed {flags['unparsed']}"
    if flags["empty"] or flags["unparsed"]:
        text += " <- inspect samples"
    return f"[{text}]"


def task_parts(task, entry):
    """Formatted metrics + flags for one task; ok is False on a non-numeric metric."""
    parts = []
    ok = True
    for label, key in HEADLINE[task]:
        value = entry["metrics"].get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label} {value * 100:.2f}%")
        else:
            parts.append(f"{label} ?")
            ok = False
    parts.append(f"n={entry['n']}")
    parts.append(_flag_text(task, entry))
    return parts, ok


def describe(run_dir, check, comparable_only=False):
    """Return (line, ok) for one run directory."""
    name = os.path.basename(os.path.normpath(run_dir))
    found = load(run_dir, comparable_only=comparable_only)
    if not found:
        return f"{name}: no results yet (still running, or failed)", False
    ok = True
    parts = []
    for task in HEADLINE:
        if task not in found:
            ok = ok and not check
            continue
        task_text, task_ok = task_parts(task, found[task])
        parts += task_text
        ok = ok and task_ok
    return f"{name}: " + ", ".join(parts), ok


def historical_lines(root):
    """Comparable historical results first, then one line per excluded result."""
    hist_root = os.path.join(root, HISTORICAL_DIR)
    if not os.path.isdir(hist_root):
        return []
    lines = ["", f"historical (imported from framework; comparable = full run, max_gen_toks={MAX_GEN_TOKS}):"]
    excluded = []
    for source in sorted(d for d in glob.glob(os.path.join(hist_root, "*")) if os.path.isdir(d)):
        found = load(source, comparable_only=True)
        if found:
            line, _ = describe(source, check=False, comparable_only=True)
            model = next((e["model"] for e in found.values() if e["model"]), None)
            lines.append(f"  {line}" + (f"  ({model})" if model else ""))
        for path in sorted(glob.glob(os.path.join(source, "**", "results_*.json"), recursive=True)):
            with open(path) as fh:
                data = json.load(fh)
            reason = exclusion_reason(data)
            tasks = [t for t in data.get("results", {}) if t in HEADLINE]
            line = f"  {os.path.basename(source)} {','.join(tasks)}: {reason}"
            if reason and tasks and line not in excluded:
                excluded.append(line)
    if excluded:
        lines.append("excluded:")
        lines.extend(excluded)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("dirs", nargs="*")
    args = parser.parse_args(argv)

    if not args.dirs:
        dirs = sorted(
            d for d in glob.glob(os.path.join(RESULTS_ROOT, "*"))
            if os.path.isdir(d) and not os.path.basename(d).startswith("_")
        )
        if not dirs:
            print("no runs yet")
        for run_dir in dirs:
            print(describe(run_dir, check=False)[0])
        for line in historical_lines(RESULTS_ROOT):
            print(line)
        return 0
    dirs = args.dirs

    all_ok = True
    for run_dir in dirs:
        line, ok = describe(run_dir, args.check)
        print(line)
        all_ok = all_ok and ok

    if args.check:
        if not all_ok:
            print("check FAILED: missing task or non-numeric headline metric", file=sys.stderr)
            return 1
        print("check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
