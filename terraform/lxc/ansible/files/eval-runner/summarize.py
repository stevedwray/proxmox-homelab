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
inspect, not as the model's capability.
"""

import argparse
import glob
import json
import os
import sys

RESULTS_ROOT = "/results"

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


def load(run_dir):
    """Map task -> {metrics, n, samples}, the newest results file winning."""
    found = {}
    pattern = os.path.join(run_dir, "**", "results_*.json")
    for path in sorted(glob.glob(pattern, recursive=True)):
        with open(path) as fh:
            data = json.load(fh)
        stamp = _results_stamp(path)
        for task, metrics in data.get("results", {}).items():
            if task in HEADLINE:
                samples = os.path.join(os.path.dirname(path), f"samples_{task}_{stamp}.jsonl")
                found[task] = {
                    "metrics": metrics,
                    "n": data.get("n-samples", {}).get(task, {}).get("effective"),
                    "samples": samples if os.path.exists(samples) else None,
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


def _flag_text(samples, task):
    if not samples:
        return "[no samples file]"
    flags = response_flags(samples, task)
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
    parts.append(_flag_text(entry["samples"], task))
    return parts, ok


def describe(run_dir, check):
    """Return (line, ok) for one run directory."""
    name = os.path.basename(os.path.normpath(run_dir))
    found = load(run_dir)
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("dirs", nargs="*")
    args = parser.parse_args(argv)

    dirs = args.dirs or sorted(
        d for d in glob.glob(os.path.join(RESULTS_ROOT, "*"))
        if os.path.isdir(d) and not os.path.basename(d).startswith("_")
    )
    if not dirs:
        print("no runs yet")
        return 0

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
