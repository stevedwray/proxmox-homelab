"""RepoBench (rebuilt) for eval-runner: next-line code completion.

The historical RepoBench numbers came from custom scripts that are lost
(they lived only on the deleted ai-stack LXC), so this is a rebuild from
upstream RepoBench's own code (Leolty/repobench @ e0cfd34: run.py,
data/utils.py, eval.py, evaluation/metrics.py) on the same data, and its
results are a new series -- not comparable with the historical numbers.

What it does, following upstream:
  - data: tianyang/repobench_python_v1.1, settings cross_file_first,
    cross_file_random and in_file, levels 2k/4k/8k/12k/16k (upstream's
    default levels);
  - prompt: upstream construct_prompt() -- "# Repo Name", the cross-file
    snippets with "# Path" headers, then the in-file code -- with the
    cross-file part cut back line by line until the whole prompt fits in
    15800 tokens, counted by the served model's own tokenizer (llama-server
    /tokenize);
  - generation: raw text completion (/v1/completions, no chat template),
    128 new tokens, then upstream's get_first_line_not_comment();
  - metrics: exact match (whitespace-split equality) and edit similarity
    (fuzz.ratio, 0-100), per setting, then the average weighted by sample
    count (upstream eval.py). CodeBLEU is not computed (upstream's needs
    tree-sitter grammars; EM/ES are the headline numbers).

Deviations from upstream, both to make runs reproducible and comparable
between models: greedy decoding (temperature 0, upstream samples at 0.2),
and a seeded sample of 100 examples per setting and level (upstream runs
everything in a one-month date window; the historical runs also sampled
100 per level). No date filter.

Usage (inside the eval-runner image, via `runmeta.py exec`):
  repobench_run.py <run_dir>

Output, under <run_dir>/repobench/: predictions_<setting>.jsonl (one line
per answered example; a resume skips those) and results_<stamp>.json.
"""

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wrapper_common as wc  # noqa: E402

TASK = "repobench_python"
DATASET = "tianyang/repobench_python_v1.1"
SETTINGS = ("cross_file_first", "cross_file_random", "in_file")
LEVELS = ("2k", "4k", "8k", "12k", "16k")
PER_LEVEL = 100
SEED = 42
MAX_PROMPT_TOKENS = 15800
MAX_NEW_TOKENS = 128
VERSION = "upstream e0cfd34 (rebuilt)"
SERIES = "rebuilt"
RETRIES = 3


# --------------------------------------------------------------- upstream

def get_first_line_not_comment(code, language="python"):
    """Upstream run.py's helper (Python branch), unchanged in behaviour."""
    code = code.lstrip("\n")
    lines = code.split("\n")
    in_multiline_comment = False
    for line in lines:
        if not line.strip():
            continue
        if not in_multiline_comment and (line.strip().startswith('"""') or line.strip().startswith("'''")):
            in_multiline_comment = True
            continue
        if in_multiline_comment and (line.strip().endswith('"""') or line.strip().endswith("'''")):
            in_multiline_comment = False
            continue
        if in_multiline_comment:
            continue
        if line.strip().startswith("#"):
            continue
        return line
    return lines[0]


def prompt_parts(data):
    """Upstream construct_prompt()'s cross-file and in-file parts (Python)."""
    cross = f"# Repo Name: {data['repo_name']}\n"
    for snippet in data["context"]:
        cross += f"# Path: {snippet['path']}\n{snippet['snippet']}" + "\n\n"
    in_file = f"# Path: {data['file_path']}\n{data['import_statement']}\n{data['cropped_code'].rstrip()}\n"
    return cross, in_file


def construct_prompt(data, count_tokens, max_tokens=MAX_PROMPT_TOKENS):
    """Upstream construct_prompt(). Upstream drops cross-file lines from the
    end, subtracting each line's token count, until the excess is gone;
    here the longest prefix of cross-file lines that fits is found by
    binary search over whole-prefix token counts (a handful of /tokenize
    calls instead of one per line -- the same cut up to token-boundary
    effects at line joins)."""
    cross, in_file = prompt_parts(data)
    in_tokens = count_tokens(in_file)
    if count_tokens(cross) + in_tokens > max_tokens:
        lines = cross.split("\n")
        lo, hi = 0, len(lines)  # invariant: lines[:lo] fits
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count_tokens("\n".join(lines[:mid]) + "\n\n") + in_tokens <= max_tokens:
                lo = mid
            else:
                hi = mid - 1
        cross = "\n".join(lines[:lo]) + "\n\n"
    return re.sub(r"\n{4,}", "\n\n", cross + in_file)


def exact_match(pred, gt):
    return pred.split() == gt.split()


def edit_similarity(pred, gt):
    """fuzzywuzzy's fuzz.ratio (with python-Levenshtein): the normalised
    Indel similarity x 100, rounded -- rapidfuzz computes the same ratio."""
    from rapidfuzz import fuzz
    return int(round(fuzz.ratio(pred, gt)))


def score(predictions):
    """{setting: (n, EM %, ES)} plus the sample-weighted averages, as upstream
    eval.py (per-setting EM rounded to 2 dp before weighting)."""
    per_setting = {}
    total = em_sum = es_sum = 0
    for setting in SETTINGS:
        rows = predictions.get(setting) or []
        if not rows:
            continue
        n = len(rows)
        em = round(100 * sum(exact_match(r["pred"], r["gt"]) for r in rows) / n, 2)
        es = round(sum(edit_similarity(r["pred"], r["gt"]) for r in rows) / n, 2)
        per_setting[setting] = (n, em, es)
        total += n
        em_sum += em * n
        es_sum += es * n
    if not total:
        return per_setting, None, None, 0
    return per_setting, round(em_sum / total, 2), round(es_sum / total, 2), total


# ------------------------------------------------------------------ data

def sample(rows_by_level, per_level, seed=SEED):
    """Seeded sample of up to per_level dataset indices per level, in index order."""
    rng = random.Random(seed)
    chosen = []
    for level in LEVELS:
        indices = rows_by_level.get(level, [])
        chosen += sorted(rng.sample(indices, min(per_level, len(indices))))
    return chosen


def load_samples(per_level):
    """{setting: [(dataset index, row)]} for the seeded sample."""
    from datasets import load_dataset
    out = {}
    for setting in SETTINGS:
        data = load_dataset(DATASET, split=setting)
        by_level = {}
        for i, level in enumerate(data["level"]):
            by_level.setdefault(level, []).append(i)
        out[setting] = [(i, data[i]) for i in sample(by_level, per_level)]
    return out


# ---------------------------------------------------------------- server

class Server:
    def __init__(self, base_url, model_id, api_key):
        self.v1 = base_url  # .../v1
        self.root = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
        self.model = model_id
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self.tokenize_ok = True

    def _post(self, url, body, timeout):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=self.headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)

    def count_tokens(self, text):
        """llama-server /tokenize; ~4 characters per token if unavailable."""
        if self.tokenize_ok:
            try:
                return len(self._post(f"{self.root}/tokenize", {"content": text}, 300)["tokens"])
            except (urllib.error.URLError, OSError, KeyError, ValueError):
                self.tokenize_ok = False
                print("repobench_run: /tokenize unavailable, estimating 4 characters per token")
        return len(text) // 4

    def complete(self, prompt):
        body = {"model": self.model, "prompt": prompt, "max_tokens": MAX_NEW_TOKENS, "temperature": 0}
        return self._post(f"{self.v1}/completions", body, 3600)["choices"][0].get("text") or ""


def read_done(path):
    done = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    done[row["idx"]] = row
    return done


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: repobench_run.py <run_dir>", file=sys.stderr)
        return 2
    run_dir = argv[0]
    record = wc.load_record(run_dir)
    base_url, model_id, api_key = wc.server(record)
    limit = record.get("limit")
    per_level = limit or PER_LEVEL
    out_dir = os.path.join(run_dir, "repobench")
    os.makedirs(out_dir, exist_ok=True)
    server = Server(base_url, model_id, api_key)

    predictions, errors = {}, 0
    for setting, rows in load_samples(per_level).items():
        path = os.path.join(out_dir, f"predictions_{setting}.jsonl")
        done = read_done(path)
        with open(path, "a") as fh:
            for idx, data in rows:
                if idx in done:
                    continue
                prompt = construct_prompt(data, server.count_tokens)
                for attempt in range(RETRIES):
                    try:
                        raw = server.complete(prompt)
                        break
                    except (urllib.error.URLError, OSError, KeyError, ValueError) as err:
                        print(f"repobench_run: {setting} {idx} attempt {attempt + 1}: {err}")
                        time.sleep(5 * (attempt + 1))
                else:
                    errors += 1  # not recorded, so a resume retries it
                    continue
                row = {"idx": idx, "level": data["level"], "pred": get_first_line_not_comment(raw),
                       "gt": data["next_line"], "empty": not raw.strip()}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                done[idx] = row
        predictions[setting] = [done[idx] for idx, _ in rows if idx in done]

    per_setting, em, es, total = score(predictions)
    metrics = {"exact_match,weighted": em / 100 if em is not None else None,
               "edit_similarity,weighted": es / 100 if es is not None else None,
               "empty,none": sum(r.get("empty", False) for rows in predictions.values() for r in rows),
               "errors,none": errors}
    for setting, (n, s_em, s_es) in per_setting.items():
        metrics[f"exact_match,{setting}"] = s_em / 100
        metrics[f"edit_similarity,{setting}"] = s_es / 100
        metrics[f"n,{setting}"] = n
    path = wc.write_results(
        out_dir, TASK, metrics, total, len(SETTINGS) * len(LEVELS) * PER_LEVEL, limit=limit, model=model_id,
        base_url=base_url, harness="repobench", version=VERSION, series=SERIES, max_gen_toks=MAX_NEW_TOKENS,
        runtime=wc.runtime(record),
    )
    print(f"repobench_run: EM {em} / ES {es} on {total} examples (errors {errors}) -> {path}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
