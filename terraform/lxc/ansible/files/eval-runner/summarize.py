"""Print headline GPQA/IFEval numbers for eval-run result directories.

With no arguments, summarises every run directory under /results except
those starting with "_" (selftest output). With --check, exits non-zero
unless every given directory holds results for both tasks with numeric
headline metrics -- `eval-run selftest` uses this as its pass/fail.
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


def load(run_dir):
    """Map task -> (metrics, effective sample count), newest file wins."""
    found = {}
    pattern = os.path.join(run_dir, "**", "results_*.json")
    for path in sorted(glob.glob(pattern, recursive=True)):
        with open(path) as fh:
            data = json.load(fh)
        for task, metrics in data.get("results", {}).items():
            if task in HEADLINE:
                n = data.get("n-samples", {}).get(task, {}).get("effective")
                found[task] = (metrics, n)
    return found


def describe(run_dir, check):
    """Return (line, ok) for one run directory."""
    name = os.path.basename(os.path.normpath(run_dir))
    found = load(run_dir)
    if not found:
        return f"{name}: no results yet (still running, or failed)", False
    ok = True
    parts = []
    for task, columns in HEADLINE.items():
        if task not in found:
            ok = False if check else ok
            continue
        metrics, n = found[task]
        for label, key in columns:
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                parts.append(f"{label} {value * 100:.2f}%")
            else:
                parts.append(f"{label} ?")
                ok = False
        parts.append(f"n={n}")
    return f"{name}: " + ", ".join(parts), ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("dirs", nargs="*")
    args = parser.parse_args()

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
            print("selftest FAILED: missing task or non-numeric headline metric", file=sys.stderr)
            return 1
        print("selftest OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
