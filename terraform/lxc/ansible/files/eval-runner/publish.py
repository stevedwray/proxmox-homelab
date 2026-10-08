"""Publish eval results to Nextcloud.

What gets published (all under the service account, folder shared to the
operator by the deploy):

  Reports/eval-runner/
    leaderboard.xlsx    the spreadsheet: one ranked sheet per task and
                        token-budget series, plus every result on one
                        filterable sheet (opens in Nextcloud Office)
    leaderboard.md      the ranked lists as plain text
    findings.md         curated analysis (from the repo)
    runs/<run>/report.md, manifest.json            eval-runner runs
    historical/<source>/report.md, manifest.json   imported framework runs

and the Nextcloud Tables table "Model evaluations": one row per
(run, task, results file), upserted by its Key column, with saved views
for comparable GPQA / IFEval results. CyberSecEval runs add one headline
row each (Source "cyberseceval"): cse-controller sends it to the panel
worker (eval_tasks.record_cse), which keeps it in <results>/_cse/.

The report/manifest layout follows docs/reporting-platform/CONVENTION.md.
samples_*.jsonl files are never uploaded: they contain GPQA questions,
whose licence forbids reposting them.

Environment (from /etc/eval-runner/eval-runner.env):
  NEXTCLOUD_EVAL_REPORTS_URL           e.g. https://nextcloud.lab.gibbsgreatly.xyz
  NEXTCLOUD_EVAL_REPORTS_USER          service account
  NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD  its app password
  NEXTCLOUD_EVAL_TABLE_SHARE_WITH      user to share the table with (optional)

Only files whose content changed since the last publish are uploaded
(their hashes are kept in <results-root>/_publish-state.json), so in
Nextcloud only the folders of new or changed runs get a new timestamp.

Usage:
  publish.py                    publish what changed
  publish.py --all              upload every file again
  publish.py --dry-run DIR      render everything into DIR, no network
"""

import argparse
import base64
import datetime
import glob
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import summarize  # noqa: E402

try:  # only needed to render leaderboard.xlsx; in the image, see the Dockerfile
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover - unit tests skip the xlsx checks
    openpyxl = None

RESULTS_ROOT = "/results"
FINDINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "findings.md")
FOLDER = "Reports/eval-runner"
CSE_DIR = "_cse"
ALIASES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_aliases.json")
STATE_FILE = "_publish-state.json"
TABLE_TITLE = "Model evaluations"
TABLE_EMOJI = "📊"
TABLES_API = "/index.php/apps/tables/api/1"
TABLES_OCS_API = "/ocs/v2.php/apps/tables/api/2"
# Files earlier versions published that are now gone; deleted on publish.
STALE_FILES = ("leaderboard.csv",)

# task -> (label, primary metric name, alternative metric name or None).
# Order is the leaderboard's section and sheet order.
TASK_LABELS = {
    "gpqa_diamond_cot_zeroshot": ("GPQA diamond", "flexible-extract", "strict-match"),
    "ifeval": ("IFEval", "prompt-level strict", "prompt-level loose"),
    "bfcl_simple": ("BFCL simple", "accuracy", None),
    "agentbench_os_std": ("AgentBench os-std", "success rate", None),
    "repobench_python": ("RepoBench (rebuilt)", "exact match", "edit similarity"),
}
TASK_BY_LABEL = {label: task for task, (label, _, _) in TASK_LABELS.items()}

# (title, column spec). Order is the table's column order. "Key" is the
# upsert identity and must stay first and unchanged.
COLUMNS = [
    ("Key", {"type": "text", "subtype": "line"}),
    ("Model", {"type": "text", "subtype": "line"}),
    ("Task", {"type": "text", "subtype": "line"}),
    ("Score %", {"type": "number", "numberDecimals": 2, "numberSuffix": "%"}),
    ("Alt score %", {"type": "number", "numberDecimals": 2, "numberSuffix": "%"}),
    ("Metrics", {"type": "text", "subtype": "line"}),
    ("Questions", {"type": "number", "numberDecimals": 0}),
    ("Empty answers", {"type": "number", "numberDecimals": 0}),
    ("Empty %", {"type": "number", "numberDecimals": 1, "numberSuffix": "%"}),
    ("Unparsed", {"type": "number", "numberDecimals": 0}),
    ("Token budget", {"type": "number", "numberDecimals": 0}),
    # Per run, not per task (a run's tasks share them): from run.json's
    # run_metrics, which the panel worker writes (eval_tasks.py).
    ("Duration (min)", {"type": "number", "numberDecimals": 1}),
    ("Tokens generated", {"type": "number", "numberDecimals": 0}),
    ("Tokens/s", {"type": "number", "numberDecimals": 1}),
    ("Series", {"type": "text", "subtype": "line"}),
    ("Comparable", {"type": "text", "subtype": "line"}),
    ("Why not comparable", {"type": "text", "subtype": "line"}),
    ("Model file / tag", {"type": "text", "subtype": "line"}),
    ("Runtime", {"type": "text", "subtype": "line"}),
    ("Note", {"type": "text", "subtype": "line"}),
    ("Source", {"type": "text", "subtype": "line"}),
    ("Run", {"type": "text", "subtype": "line"}),
    ("Date", {"type": "text", "subtype": "line"}),
    ("Report", {"type": "text", "subtype": "line"}),
]

VIEWS = [
    # (title, emoji, task label or None for all, {column: required value}).
    # Per-benchmark views show every result for that benchmark (operator,
    # 2026-10-02: smoke runs must be visible there too); comparable full
    # runs sort first, by score, and the Comparable column says which.
    ("GPQA", "\U0001F9E0", "GPQA diamond", {}),
    ("IFEval", "\U0001F4CB", "IFEval", {}),
    ("BFCL", "\U0001F527", "BFCL simple", {}),
    ("AgentBench", "\U0001F916", "AgentBench os-std", {}),
    ("RepoBench (rebuilt)", "\U0001F4BB", "RepoBench (rebuilt)", {}),
    ("32k budget: GPQA", "\u23F3", "GPQA diamond", {"Series": "32k"}),
    ("32k budget: IFEval", "\u23F3", "IFEval", {"Series": "32k"}),
    # Every eval-runner run, newest first.
    ("Recent eval-runner runs", "\U0001F9EA", None, {"Source": "eval-runner"}),
    # Every CyberSecEval run's headline (cse-controller, via eval_tasks.record_cse).
    ("CyberSecEval", "\U0001F6E1", None, {"Source": "cyberseceval"}),
]
# Earlier view titles, renamed in place on publish (same view id, so
# shares and any manual tweaks survive).
RENAMED_VIEWS = {
    "Comparable: GPQA": "GPQA",
    "Comparable: IFEval": "IFEval",
    "Comparable: BFCL": "BFCL",
    "Comparable: AgentBench": "AgentBench",
}



# ---------------------------------------------------------------- collect

def _base_url(data):
    model_args = data.get("config", {}).get("model_args")
    if isinstance(model_args, dict):
        return model_args.get("base_url", "")
    pairs = dict(p.split("=", 1) for p in str(model_args or "").split(",") if "=" in p)
    return pairs.get("base_url", "")


def _date(data, fallback):
    stamp = data.get("date")
    if isinstance(stamp, (int, float)):
        return datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).strftime("%Y-%m-%d")
    return fallback


def _runtime(data, record):
    wrapper = data.get("config", {}).get("eval_runner") or {}
    if wrapper.get("runtime"):
        return wrapper["runtime"]
    if record and (record.get("server") or {}).get("props"):
        return f"llama.cpp {record['server']['props'].get('build_info') or ''}".strip()
    return "Ollama" if ":11434" in _base_url(data) else "OpenAI-compatible server"


def _model_file(model, record):
    props = (record or {}).get("server", {}).get("props") or {}
    if props.get("model_path"):
        return os.path.basename(props["model_path"])
    return model or ""


def _stamp_date(stamp):
    """20261001T030837Z -> 2026-10-01"""
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 and stamp[:8].isdigit() else ""


def _run_metric_cells(record):
    """(duration in minutes, tokens generated, tokens/s) from run.json."""
    metrics = (record or {}).get("run_metrics") or {}
    mut = metrics.get("model_under_test") or {}
    duration = metrics.get("duration_seconds")
    return (round(duration / 60, 1) if isinstance(duration, (int, float)) else None,
            mut.get("completion_tokens"), mut.get("generation_tokens_per_second"))


def _row(source, run, task, data, metrics, samples, record, stamp):
    label, primary_name, alt_name = TASK_LABELS[task]
    keys = [key for _, key in summarize.HEADLINE[task]]
    primary_key, alt_key = keys[0], (keys[1] if len(keys) > 1 else None)
    n = data.get("n-samples", {}).get(task, {}).get("effective")
    flags = summarize.task_flags(task, metrics, samples) or {"empty": None, "unparsed": None}
    wrapper = data.get("config", {}).get("eval_runner") or {}
    reason = summarize.exclusion_reason(data)
    model = (record or {}).get("server", {}).get("model_id") or summarize.model_name(data) or run

    def pct(value):
        return round(value * 100, 2) if isinstance(value, (int, float)) else None

    empty = flags["empty"]
    duration_min, tokens, tokens_per_s = _run_metric_cells(record)
    return {
        "Key": f"{source}/{run}/{task}" + (f"/{stamp}" if source == "historical" else ""),
        "Model": model,
        "Task": label,
        "Score %": pct(metrics.get(primary_key)),
        "Alt score %": pct(metrics.get(alt_key)),
        "Metrics": f"{primary_name} / {alt_name}" if alt_name else primary_name,
        "Questions": n,
        "Empty answers": empty,
        "Empty %": round(100 * empty / n, 1) if empty is not None and n else None,
        "Unparsed": flags["unparsed"],
        "Token budget": summarize._max_gen_toks(data.get("config", {}).get("gen_kwargs")),
        "Duration (min)": duration_min,
        "Tokens generated": tokens,
        "Tokens/s": tokens_per_s,
        "Series": summarize.series(data) or "",
        "Comparable": "no" if reason else "yes",
        "Why not comparable": reason or "",
        "Model file / tag": _model_file(model, record),
        "Runtime": _runtime(data, record),
        "Note": (record or {}).get("note") or wrapper.get("note") or "",
        "Source": "eval-runner" if source == "runs" else f"historical ({wrapper.get('origin') or 'framework'})",
        "Run": run,
        "Date": _date(data, _stamp_date((record or {}).get("created_utc", ""))),
        "Report": f"{FOLDER}/{source}/{run}/report.md",
    }


def _results_files(run_dir):
    return sorted(glob.glob(os.path.join(run_dir, "**", "results_*.json"), recursive=True))


def collect_run(run_dir, source):
    """Rows for one run directory. eval-runner runs: newest results file per
    task (a resume supersedes earlier files). Historical: every results file,
    so excluded pilots/Bug 6 runs stay visible with their reason."""
    run = os.path.basename(os.path.normpath(run_dir))
    record_path = os.path.join(run_dir, "run.json")
    record = None
    if os.path.exists(record_path):
        with open(record_path) as fh:
            record = json.load(fh)
    rows = {}
    for path in _results_files(run_dir):
        with open(path) as fh:
            data = json.load(fh)
        stamp = summarize._results_stamp(path)
        for task, metrics in data.get("results", {}).items():
            if task not in summarize.HEADLINE:
                continue
            samples = os.path.join(os.path.dirname(path), f"samples_{task}_{stamp}.jsonl")
            row = _row(source, run, task, data, metrics,
                       samples if os.path.exists(samples) else None, record, stamp)
            rows[row["Key"]] = row
    return record, list(rows.values())


def cse_row(record):
    """A Tables row from a CyberSecEval headline record (cse_tasks._compare_row)."""
    head = record.get("headline") or {}
    better = head.get("better")
    metrics = f"{head.get('metric', '')} ({better} is better)" if better else head.get("metric", "")
    if head.get("alt_metric"):
        metrics += f" / {head['alt_metric']}"
    duration = record.get("duration_seconds")
    return {
        "Key": f"cyberseceval/{record['job_id']}/{record['benchmark']}",
        "Model": record.get("model") or "",
        "Task": f"CyberSecEval {record['benchmark']}",
        "Score %": head.get("value"),
        "Alt score %": head.get("alt_value"),
        "Metrics": metrics,
        "Questions": head.get("n"),
        "Empty answers": None,
        "Empty %": None,
        "Unparsed": None,
        "Token budget": None,
        "Duration (min)": round(duration / 60, 1) if isinstance(duration, (int, float)) else None,
        "Tokens generated": record.get("completion_tokens"),
        "Tokens/s": record.get("tokens_per_second"),
        "Series": "",
        # CyberSecEval runs are samples of each benchmark's dataset; Compare
        # shows their size (Questions) instead of a comparable flag.
        "Comparable": "sample",
        "Why not comparable": "",
        "Model file / tag": record.get("model_file") or "",
        "Runtime": f"llama.cpp {record['build']}" if record.get("build") else "",
        "Note": "; ".join(n for n in (
            "" if record.get("model_verified", True) else
            "model not verified: recorded before 2026-10-08, from the request, not the server",
            "" if record.get("ok", True) else "run reported an error") if n),
        "Source": "cyberseceval",
        "Run": record["job_id"],
        "Date": (record.get("finished_at") or "")[:10],
        "Report": record.get("report") or "",
    }


def collect_cse(results_root):
    rows = []
    for path in sorted(glob.glob(os.path.join(results_root, CSE_DIR, "*.json"))):
        try:
            with open(path) as fh:
                record = json.load(fh)
            if record.get("headline"):
                rows.append(cse_row(record))
        except (OSError, ValueError, KeyError):
            continue
    return rows


def load_aliases(path=ALIASES_FILE):
    """{recorded model name: name Compare shows} from model_aliases.json."""
    try:
        with open(path) as fh:
            return json.load(fh).get("labels", {})
    except (OSError, ValueError):
        return {}


def compare_rows(results_root, aliases=None):
    """Every result row (eval-runner, historical and CyberSecEval), trimmed
    to what the panel's Compare tab needs, with each model shown by its
    model_aliases.json label ("Model name" keeps the recorded name)."""
    aliases = load_aliases() if aliases is None else aliases
    rows = [r for _, _, _, rs in collect(results_root) for r in rs] + collect_cse(results_root)
    keep = ("Model", "Task", "Score %", "Alt score %", "Metrics", "Questions", "Comparable", "Series",
            "Tokens/s", "Duration (min)", "Source", "Run", "Date", "Note")
    out = []
    for r in rows:
        trimmed = {k: r.get(k) for k in keep}
        trimmed["Model name"] = r.get("Model")
        trimmed["Model"] = aliases.get(r.get("Model"), r.get("Model"))
        out.append(trimmed)
    return out


def collect(results_root):
    """[(source, run_dir, record, rows)] for every eval-runner and historical run."""
    out = []
    for run_dir in sorted(glob.glob(os.path.join(results_root, "*"))):
        if os.path.isdir(run_dir) and not os.path.basename(run_dir).startswith("_"):
            record, rows = collect_run(run_dir, "runs")
            out.append(("runs", run_dir, record, rows))
    hist = os.path.join(results_root, summarize.HISTORICAL_DIR)
    for run_dir in sorted(glob.glob(os.path.join(hist, "*"))):
        if os.path.isdir(run_dir):
            record, rows = collect_run(run_dir, "historical")
            out.append(("historical", run_dir, record, rows))
    return out


# ----------------------------------------------------------------- render

def _fmt(value, suffix="", decimals=2):
    if value is None or value == "":
        return "–"
    if isinstance(value, float):
        return f"{value:.{decimals}f}{suffix}"
    return f"{value}{suffix}"


CAVEATS = """\
- **Greedy decoding.** Both task configs pin `temperature: 0`, as every
  historical result did.
- **Token budget.** `max_gen_toks` is 8192 unless the table says
  otherwise. An *empty answer* means the model produced no answer
  content, usually because its reasoning used up the budget. A score with
  many empty answers mostly measures finishing inside the budget. Read
  `findings.md` before comparing reasoning models.
- **Comparable** means a full run (no `--limit`) at the 8192 budget.
  Pilots and runs without the cap (the Bug 6 era) are listed but not
  ranked.
- **Series.** Full runs at a larger budget (e.g. 32k) are ranked in their
  own series, never against the 8k one: more budget lets reasoning models
  finish answers they would otherwise lose.
- **BFCL** is v3 "simple" (400 cases, bfcl-eval 2025.8.6.2) and
  **AgentBench** is os-std on a seed-42 sample of 100 episodes, both as
  every historical number. An AgentBench run over all 800 episodes is
  its own series.
- **RepoBench (rebuilt)** is a new series: the scripts behind the
  historical RepoBench numbers are lost, so those aren't ranked with it.
- Per-question samples stay on the eval-runner CT, not in Nextcloud:
  GPQA's licence forbids reposting its questions.
"""

TASK_ORDER = tuple(label for label, _, _ in TASK_LABELS.values())


def standard_series(label):
    return summarize.STANDARD_SERIES[TASK_BY_LABEL[label]]


def series_order(all_rows, label):
    """Series present for one task label: its standard series first (even
    with no rows yet), then the others by token budget."""
    standard = standard_series(label)
    found = {r["Series"]: r["Token budget"] or 0 for r in all_rows if r["Task"] == label and r["Series"]}
    found.setdefault(standard, 0)
    return sorted(found, key=lambda name: (name != standard, found[name], name))


def series_heading(label, series):
    standard = standard_series(label)
    if series == standard:
        return "comparable runs"
    kind = "token budget series" if TASK_BY_LABEL[label] in summarize.LM_EVAL_TASKS else "series"
    return f"{series} {kind}, not comparable with {standard}"


def ranked(all_rows, label, series):
    return sorted((r for r in all_rows if r["Task"] == label and r["Series"] == series),
                  key=lambda r: -(r["Score %"] or 0))


def metric_names(label):
    """(primary, alternative or None) metric names for a task label."""
    _, primary, alt = TASK_LABELS[TASK_BY_LABEL[label]]
    return primary, alt


def _num(value):
    """0.949999988079071 -> 0.95; None -> –."""
    if isinstance(value, float):
        return f"{value:.4g}"
    return "–" if value is None else str(value)


def _started(stamp):
    """20261001T204344Z -> 2026-10-01 20:43 UTC"""
    if len(stamp) >= 13 and stamp[8] == "T":
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]} UTC"
    return stamp or "–"


def _duration_text(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes}m {secs}s" if hours else (f"{minutes}m {secs}s" if minutes else f"{secs}s")


def _count(value):
    return f"{value:,}" if isinstance(value, int) else "–"


# Prompt speed from under this many seconds of prompt work is noise (e.g.
# a cached prompt: 4 tokens in 0.1 s).
MIN_PROMPT_SECONDS = 5


def _prompt_speed(mut):
    if (mut.get("prompt_seconds") or 0) < MIN_PROMPT_SECONDS:
        return "– (too little prompt work to measure)"
    return _num(mut.get("prompt_tokens_per_second"))


def render_metrics(record):
    """The report's Run metrics section (same figures as CyberSecEval's)."""
    metrics = (record or {}).get("run_metrics")
    if not metrics:
        return ["Not recorded for this run (runs started before 2026-10-08, or from the command line)."]
    lines = []
    if "duration_seconds" in metrics:
        segments = metrics.get("segments") or 1
        lines.append(f"- **Duration:** {_duration_text(metrics['duration_seconds'])}"
                     + (f" over {segments} segments (resumed)" if segments > 1 else ""))
    if metrics.get("unavailable"):
        return lines + [f"- **Tokens:** unavailable: {metrics['unavailable']}"]
    mut = metrics.get("model_under_test") or {}
    lines += [
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Generated tokens (incl. reasoning) | {_count(mut.get('completion_tokens'))} |",
        f"| Prompt tokens processed (cached text excluded) | {_count(mut.get('prompt_tokens'))} |",
        f"| Generation speed (tokens/s) | {_num(mut.get('generation_tokens_per_second'))} |",
        f"| Prompt processing (tokens/s) | {_prompt_speed(mut)} |",
        "",
        "From llama-server's /metrics counters, read before and after the run. Exact only if nothing "
        "else used Framework meanwhile: other benchmarks wait for the run, interactive chat does not. "
        "Prompt tokens count only what the server had to process: text it still had cached from an "
        "earlier request (a repeated question, a chat template, a multi-turn history) isn't counted.",
    ]
    return lines


def render_report(source, run_dir, record, rows):
    run = os.path.basename(os.path.normpath(run_dir))
    lines = [f"# {run}", ""]
    if rows:
        first = rows[0]
        lines += [
            f"- **Model:** {first['Model']} (`{first['Model file / tag']}`)",
            f"- **Runtime:** {first['Runtime']}",
            f"- **Source:** {first['Source']}",
        ]
    if record:
        props = (record.get("server") or {}).get("props") or {}
        params = props.get("params") or {}
        harness = record.get("harness") or "lm_eval"
        harness_text = (f"lm_eval {record.get('lm_eval_version') or ''}".strip() if harness == "lm_eval"
                        else f"{harness} (eval-runner wrapper)")
        lines += [
            f"- **Started:** {_started(record.get('created_utc', ''))}",
            f"- **Note:** {record.get('note') or '–'}",
            f"- **Server:** context {_num(props.get('n_ctx'))} tokens; server-default sampling "
            f"temperature {_num(params.get('temperature'))}, top_p {_num(params.get('top_p'))} "
            "(requests override temperature)",
            f"- **Harness:** {harness_text}; sample limit {record.get('limit') or 'none (full run)'}",
            f"- **Fingerprint:** `{record.get('fingerprint', '')[:16]}`",
        ]
    if source == "runs":
        lines += ["", "## Run metrics", ""] + render_metrics(record)
    # One narrow Metric | Value table per task: Nextcloud's markdown viewer
    # scrolls wide tables sideways (operator, 2026-10-02).
    lines += ["", "## Results", ""]
    for r in rows:
        primary, alt = metric_names(r["Task"])
        pairs = [(f"Score ({primary})", _fmt(r["Score %"], "%"))]
        if alt:
            pairs.append((alt.capitalize(), _fmt(r["Alt score %"], "%")))
        pairs += [("Questions", _fmt(r["Questions"])),
                  ("Empty answers", f"{_fmt(r['Empty answers'])} ({_fmt(r['Empty %'], '%', 1)})")]
        if r["Unparsed"] is not None:
            pairs.append(("Unparsed", _fmt(r["Unparsed"])))
        pairs += [("Token budget", _fmt(r["Token budget"]) if r["Token budget"] else "server default"),
                  ("Comparable", r["Comparable"] + (f": {r['Why not comparable']}" if r["Why not comparable"] else "")),
                  ("Date", r["Date"] or "–")]
        lines += [f"### {r['Task']}", "", "| Metric | Value |", "|---|---|"]
        lines += [f"| {name} | {value} |" for name, value in pairs]
        lines.append("")
    if not rows:
        lines += ["No results yet.", ""]
    lines += ["## Caveats", "", CAVEATS]
    return "\n".join(lines)


def render_manifest(source, run_dir, record, rows):
    run = os.path.basename(os.path.normpath(run_dir))
    dates = sorted(r["Date"] for r in rows if r["Date"])
    scores = ", ".join(f"{r['Task']} {_fmt(r['Score %'], '%')}" for r in rows) or "no results yet"
    return {
        "project": "eval-runner",
        "run_id": run,
        "started_at": (record or {}).get("created_utc") or (dates[0] if dates else ""),
        "finished_at": dates[-1] if dates else "",
        "summary": f"{rows[0]['Model'] if rows else run}: {scores}",
        "source": source,
        "rows": rows,
    }


RECENT_RUNS = 10


def render_leaderboard(all_rows, generated):
    lines = ["# Model evaluations: leaderboard", "",
             f"Generated {generated} by `eval-run publish`. The full detail is in "
             f"`leaderboard.xlsx` and the Nextcloud Tables table **{TABLE_TITLE}**. "
             "Analysis: `findings.md`.", ""]
    # Narrow tables only: Nextcloud's markdown viewer scrolls wide ones
    # sideways (operator, 2026-10-02). Alt scores, runtimes and dates are in
    # the xlsx and the Tables views.
    recent = sorted((r for r in all_rows if r["Source"] == "eval-runner"),
                    key=lambda r: (r["Date"], r["Run"]), reverse=True)[:RECENT_RUNS]
    if recent:
        lines += ["## Latest eval-runner runs", "", "Newest first, including smoke tests (not ranked).", "",
                  "| Date | Model | Task | Score |", "|---|---|---|---|"]
        lines += [f"| {r['Date']} | {r['Model']} | {r['Task']} | {_fmt(r['Score %'], '%')} |" for r in recent]
        lines.append("")
    for label in TASK_ORDER:
        for series in series_order(all_rows, label):
            rows = ranked(all_rows, label, series)
            main, alt = metric_names(label)
            lines += [f"## {label}: {series_heading(label, series)}", "", f"Ranked by {main}.", "",
                      "| # | Model | Score | Empty |", "|---|---|---|---|"]
            for i, r in enumerate(rows, 1):
                lines.append(f"| {i} | {r['Model']} | {_fmt(r['Score %'], '%')} | "
                             f"{_fmt(r['Empty answers'])}/{_fmt(r['Questions'])} |")
            if not rows:
                lines.append("| – | none yet | | |")
            lines.append("")
    excluded = [r for r in all_rows if not r["Series"]]
    if excluded:
        lines += ["## Not comparable (listed, not ranked)", ""]
        for r in sorted(excluded, key=lambda r: (r["Model"], r["Task"], r["Run"])):
            lines.append(f"- **{r['Model']}**, {r['Task']}: {_fmt(r['Score %'], '%')} "
                         f"({r['Why not comparable']})")
        lines.append("")
    lines += ["## Caveats", "", CAVEATS]
    return "\n".join(lines)


# Number formats for leaderboard.xlsx, by column title.
XLSX_FORMATS = {"Score %": '0.00"%"', "Alt score %": '0.00"%"', "Empty %": '0.0"%"'}
XLSX_HEADER_FILL = "DDE4EE"


def _xlsx_sheet(wb, title, headers, rows, freeze):
    """One sheet: bold shaded header, frozen panes, autofilter, number
    formats and column widths sized to the content."""
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=XLSX_HEADER_FILL)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    for idx, header in enumerate(headers, 1):
        letter = get_column_letter(idx)
        fmt = XLSX_FORMATS.get(header)
        if fmt:
            for cell in ws[letter][1:]:
                cell.number_format = fmt
        longest = max([len(header)] + [len(str(v)) for v in ws[letter][1:] for v in [v.value] if v is not None])
        ws.column_dimensions[letter].width = min(max(longest + 2, 8), 60)
    ws.freeze_panes = freeze
    ws.auto_filter.ref = ws.dimensions
    return ws


def render_xlsx(all_rows, generated):
    """leaderboard.xlsx: ranked sheets (task x series), All results, Notes."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    wb.properties.creator = "eval-runner"
    for label in TASK_ORDER:
        for series in series_order(all_rows, label):
            rows = ranked(all_rows, label, series)
            if not rows:
                continue
            main, alt = metric_names(label)
            headers = ["Rank", "Model", f"Score % ({main})", f"{alt or 'Alt score'} %", "Empty answers", "Questions",
                       "Empty %", "Unparsed", "Runtime", "Model file / tag", "Note", "Date", "Source", "Run"]
            body = [[i, r["Model"], r["Score %"], r["Alt score %"], r["Empty answers"], r["Questions"],
                     r["Empty %"], r["Unparsed"], r["Runtime"], r["Model file / tag"], r["Note"],
                     r["Date"], r["Source"], r["Run"]] for i, r in enumerate(rows, 1)]
            ws = _xlsx_sheet(wb, f"{label.split()[0]} ({series})", headers, body, "C2")
            for col in "CD":
                for cell in ws[col][1:]:
                    cell.number_format = XLSX_FORMATS["Score %"]
            for cell in ws["G"][1:]:
                cell.number_format = XLSX_FORMATS["Empty %"]
    titles = [t for t, _ in COLUMNS if t != "Key"]
    everything = sorted(all_rows, key=lambda r: (r["Task"], r["Series"] or "~", -(r["Score %"] or 0)))
    _xlsx_sheet(wb, "All results", titles, [[r.get(t) for t in titles] for r in everything], "C2")
    notes = wb.create_sheet("Notes")
    notes.append([f"Generated {generated} by eval-run publish. Same data as the Nextcloud Tables "
                  f"table '{TABLE_TITLE}'. Analysis: findings.md."])
    notes.append([])
    for para in CAVEATS.replace("\n  ", " ").splitlines():
        notes.append([para.replace("**", "").replace("`", "").lstrip("- ")])
    notes.column_dimensions["A"].width = 120
    for row in notes.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_files(collected, findings_text, generated):
    """{relative path under FOLDER: bytes}"""
    files = {}
    all_rows = []
    for source, run_dir, record, rows in collected:
        run = os.path.basename(os.path.normpath(run_dir))
        files[f"{source}/{run}/report.md"] = render_report(source, run_dir, record, rows).encode()
        files[f"{source}/{run}/manifest.json"] = (
            json.dumps(render_manifest(source, run_dir, record, rows), indent=2) + "\n").encode()
        all_rows += rows
    files["leaderboard.md"] = render_leaderboard(all_rows, generated).encode()
    if openpyxl is not None:  # always installed in the image; selftest checks the file is there
        files["leaderboard.xlsx"] = render_xlsx(all_rows, generated)
    if findings_text is not None:
        files["findings.md"] = findings_text.encode()
    return files, all_rows


# ------------------------------------------------------------------ client

class NextcloudError(RuntimeError):
    pass


class FileLocked(NextcloudError):
    """HTTP 423: someone has the file open in Nextcloud (the Text editor
    locks a file while it's open for editing)."""


class Nextcloud:
    def __init__(self, base_url, user, password, opener=None):
        self.base = base_url.rstrip("/")
        self.user = user
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.auth = f"Basic {token}"
        self.opener = opener or urllib.request.urlopen

    def request(self, method, path, body=None, raw=None, ok=(200, 201, 204)):
        headers = {"Authorization": self.auth, "OCS-APIRequest": "true", "Accept": "application/json"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener(req, timeout=60) as resp:
                payload = resp.read()
                status = resp.status
        except urllib.error.HTTPError as err:
            status, payload = err.code, err.read()
        except (urllib.error.URLError, OSError) as err:
            raise NextcloudError(f"{method} {path} -> {type(err).__name__}: {err}") from err
        if status not in ok:
            error = FileLocked if status == 423 else NextcloudError
            raise error(f"{method} {path} -> HTTP {status}: {payload[:300]!r}")
        if payload and payload.lstrip()[:1] in (b"{", b"["):
            return json.loads(payload)
        return None

    # WebDAV
    def _dav(self, rel):
        quoted = "/".join(urllib.parse.quote(part) for part in rel.split("/"))
        return f"/remote.php/dav/files/{urllib.parse.quote(self.user)}/{quoted}"

    def ensure_folder(self, rel):
        parts = rel.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            # 405 = already exists
            self.request("MKCOL", self._dav("/".join(parts[:i])), ok=(201, 405))

    def put_file(self, rel, content):
        self.request("PUT", self._dav(rel), raw=content, ok=(201, 204))

    def delete_file(self, rel):
        # 404 = already gone
        self.request("DELETE", self._dav(rel), ok=(204, 404))

    # Tables
    def tables(self, method, path, body=None):
        return self.request(method, TABLES_API + path, body=body)


def ensure_table(nc):
    for table in nc.tables("GET", "/tables") or []:
        if table.get("title") == TABLE_TITLE:
            return table["id"]
    return nc.tables("POST", "/tables", {"title": TABLE_TITLE, "emoji": TABLE_EMOJI})["id"]


def ensure_columns(nc, table_id):
    """{title: column id}, creating any missing columns in COLUMNS order."""
    existing = {c["title"]: c["id"] for c in nc.tables("GET", f"/tables/{table_id}/columns") or []}
    for title, spec in COLUMNS:
        if title not in existing:
            created = nc.tables("POST", f"/tables/{table_id}/columns",
                                {"title": title, "mandatory": False, **spec})
            existing[title] = created["id"]
    return existing


def _all_rows(nc, table_id, page=500):
    rows, offset = [], 0
    while True:
        batch = nc.tables("GET", f"/tables/{table_id}/rows?limit={page}&offset={offset}") or []
        rows += batch
        if len(batch) < page:
            return rows
        offset += page


def _row_payload(row, col_ids):
    return {str(col_ids[title]): row[title] for title, _ in COLUMNS if row.get(title) is not None}


def _same(a, b):
    """Remote numbers can come back as 198.0 for 198 -- compare numerically."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-9
    if isinstance(b, (int, float)) and isinstance(a, str):
        try:
            return abs(float(a) - b) < 1e-9
        except ValueError:
            return False
    return a == b


def upsert_rows(nc, table_id, col_ids, rows):
    """Create or update rows by Key. Returns (created, updated, unchanged)."""
    key_col = col_ids["Key"]
    existing = {}
    for remote in _all_rows(nc, table_id):
        values = {cell["columnId"]: cell["value"] for cell in remote.get("data", [])}
        if values.get(key_col) is not None:
            existing[values[key_col]] = (remote["id"], values)
    created = updated = unchanged = 0
    for row in rows:
        payload = _row_payload(row, col_ids)
        if row["Key"] not in existing:
            nc.tables("POST", f"/tables/{table_id}/rows", {"data": payload})
            created += 1
            continue
        row_id, values = existing[row["Key"]]
        if all(_same(values.get(int(cid)), value) for cid, value in payload.items()):
            unchanged += 1
            continue
        nc.tables("PUT", f"/rows/{row_id}", {"data": payload})
        updated += 1
    return created, updated, unchanged


# What a ranked view shows (operator, 2026-10-01: the full 20-column table
# with the internal Key first was unreadable). The rest stays in the base
# table.
VIEW_COLUMNS = ["Model", "Score %", "Alt score %", "Comparable", "Empty answers", "Questions", "Tokens/s",
                "Duration (min)", "Runtime", "Note", "Date"]
RUNS_VIEW_COLUMNS = ["Date", "Model", "Task", "Score %", "Alt score %", "Empty answers", "Questions",
                     "Duration (min)", "Tokens generated", "Tokens/s", "Comparable", "Why not comparable", "Note",
                     "Run"]
# The base table's column order: what a person reads first, the internal
# upsert Key last.
TABLE_ORDER = ["Model", "Task", "Score %", "Alt score %", "Empty answers", "Questions", "Duration (min)",
               "Tokens generated", "Tokens/s", "Series", "Comparable",
               "Why not comparable", "Runtime", "Model file / tag", "Note", "Date", "Source", "Run", "Metrics",
               "Empty %", "Unparsed", "Token budget", "Report", "Key"]


def view_settings(col_ids, task, required):
    """Body for PUT /views/{id}, in the shapes Tables 2.3's ViewUpdateInput
    accepts (read from its source): columnSettings [{columnId, order}],
    filter [[{columnId, operator, value}]] (groups OR-ed, entries AND-ed),
    sort [{columnId, mode: ASC|DESC}] -- real arrays, not JSON strings
    (the deprecated "columns" key breaks when given a string)."""
    filters = [{"columnId": col_ids["Task"], "operator": "is-equal", "value": task}] if task else []
    filters += [{"columnId": col_ids[column], "operator": "is-equal", "value": value}
                for column, value in required.items()]
    if task is None:  # the all-tasks runs view
        shown = RUNS_VIEW_COLUMNS
    else:
        has_alt = TASK_LABELS[TASK_BY_LABEL[task]][2] is not None
        shown = [title for title in VIEW_COLUMNS if has_alt or title != "Alt score %"]
    return {
        "columnSettings": [{"columnId": col_ids[title], "order": i} for i, title in enumerate(shown)],
        "filter": [filters],
        # No preset sort: Tables 2.3.1 hides the column header's sort buttons
        # on preset-sorted columns, and the operator wants to sort by clicking
        # any column (2026-10-02). Ranked lists live in leaderboard.md/.xlsx.
        "sort": [],
    }


def ensure_views(nc, table_id, col_ids):
    """Create missing views, and (re)apply every view's settings each time,
    so a view left half-configured by an earlier failure gets repaired."""
    existing = {v["title"]: v["id"] for v in nc.tables("GET", f"/tables/{table_id}/views") or []}
    for old, new in RENAMED_VIEWS.items():
        if old in existing and new not in existing:
            nc.tables("PUT", f"/views/{existing[old]}", {"data": {"title": new}})
            existing[new] = existing.pop(old)
    for title, emoji, task, required in VIEWS:
        view_id = existing.get(title)
        if view_id is None:
            view_id = nc.tables("POST", f"/tables/{table_id}/views", {"title": title, "emoji": emoji})["id"]
        nc.tables("PUT", f"/views/{view_id}", {"data": view_settings(col_ids, task, required)})


def table_layout(col_ids):
    """Body for the OCS v2 PUT /tables/{id}: the table's own column order
    (TABLE_ORDER, Key last) and no preset sort (see view_settings).
    The v1 API has no way to set these; without it the base table shows
    columns in an arbitrary order."""
    return {
        "columnSettings": [{"columnId": col_ids[title], "order": i} for i, title in enumerate(TABLE_ORDER)],
        "sort": [],
    }


def ensure_table_layout(nc, table_id, col_ids):
    nc.request("PUT", f"{TABLES_OCS_API}/tables/{table_id}", body=table_layout(col_ids))


def ensure_share(nc, table_id, user):
    """Share the table (read + manage) and every view (read) with user.

    Manage, because Tables 2.3.1 only sends a table's views along with the
    table to its owner or a manager. A read-only receiver gets them from a
    second request, and the web UI fires both in parallel and lets the
    table reply overwrite the view list -- so the views under the table
    vanish whenever that reply lands last (operator saw it, 2026-10-02).
    The view shares are kept as well, for other clients."""
    shares = nc.tables("GET", f"/tables/{table_id}/shares") or []
    mine = next((s for s in shares if s.get("receiver") == user), None)
    if mine is None:
        nc.tables("POST", f"/tables/{table_id}/shares", {
            "receiver": user, "receiverType": "user", "permissionRead": True,
            "permissionCreate": False, "permissionUpdate": False,
            "permissionDelete": False, "permissionManage": True,
        })
    elif not mine.get("permissionManage"):
        nc.tables("PUT", f"/shares/{mine['id']}", {"permissionType": "manage", "permissionValue": True})
    for view in nc.tables("GET", f"/tables/{table_id}/views") or []:
        if any(s.get("receiver") == user for s in nc.tables("GET", f"/views/{view['id']}/shares") or []):
            continue
        nc.tables("POST", "/shares", {
            "nodeId": view["id"], "nodeType": "view", "receiver": user, "receiverType": "user",
            "permissionRead": True, "permissionCreate": False, "permissionUpdate": False,
            "permissionDelete": False, "permissionManage": False,
        })


def file_hashes(files):
    return {rel: hashlib.sha256(content).hexdigest() for rel, content in files.items()}


def load_state(path):
    try:
        with open(path) as fh:
            return json.load(fh).get("files", {})
    except (OSError, ValueError):
        return {}


def save_state(path, hashes):
    with open(path, "w") as fh:
        json.dump({"files": hashes}, fh, indent=1, sort_keys=True)


def changed_files(files, previous):
    """Files that are new or differ from what the last publish uploaded."""
    hashes = file_hashes(files)
    return {rel for rel in files if previous.get(rel) != hashes[rel]}


def publish(nc, files, rows, share_with=None, only=None, locked=None):
    """Upload files (all, or just those in `only`), then sync the table.
    A file that is locked (open in Nextcloud) is skipped and added to
    `locked`, so one open report doesn't stop the whole publish."""
    nc.ensure_folder(FOLDER)
    made = set()
    for rel in sorted(files):
        if only is not None and rel not in only:
            continue
        parent = os.path.dirname(rel)
        if parent and parent not in made:
            nc.ensure_folder(f"{FOLDER}/{parent}")
            made.add(parent)
        try:
            nc.put_file(f"{FOLDER}/{rel}", files[rel])
        except FileLocked:
            if locked is None:
                raise
            locked.append(rel)
    for rel in STALE_FILES:
        if rel not in files:
            nc.delete_file(f"{FOLDER}/{rel}")
    table_id = ensure_table(nc)
    col_ids = ensure_columns(nc, table_id)
    counts = upsert_rows(nc, table_id, col_ids, rows)
    ensure_table_layout(nc, table_id, col_ids)
    ensure_views(nc, table_id, col_ids)
    if share_with:
        ensure_share(nc, table_id, share_with)
    return table_id, counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", metavar="DIR", help="render into DIR instead of publishing")
    parser.add_argument("--results-root", default=RESULTS_ROOT)
    parser.add_argument("--findings", default=FINDINGS_FILE)
    parser.add_argument("--all", action="store_true", help="upload every file, changed or not")
    args = parser.parse_args(argv)

    findings = None
    if os.path.exists(args.findings):
        with open(args.findings) as fh:
            findings = fh.read()
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    files, rows = build_files(collect(args.results_root), findings, generated)
    rows = rows + collect_cse(args.results_root)  # Tables only, not the leaderboard

    if args.dry_run:
        for rel, content in files.items():
            path = os.path.join(args.dry_run, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(content)
        print(f"dry run: {len(files)} files, {len(rows)} table rows -> {args.dry_run}")
        return 0

    env = os.environ
    missing = [k for k in ("NEXTCLOUD_EVAL_REPORTS_URL", "NEXTCLOUD_EVAL_REPORTS_USER",
                           "NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD") if not env.get(k)]
    if missing:
        print(f"publish: not configured, missing {', '.join(missing)}", file=sys.stderr)
        return 2
    nc = Nextcloud(env["NEXTCLOUD_EVAL_REPORTS_URL"], env["NEXTCLOUD_EVAL_REPORTS_USER"],
                   env["NEXTCLOUD_EVAL_REPORTS_APP_PASSWORD"])
    state_path = os.path.join(args.results_root, STATE_FILE)
    only = None if args.all else changed_files(files, load_state(state_path))
    locked = []
    try:
        table_id, (created, updated, unchanged) = publish(
            nc, files, rows, env.get("NEXTCLOUD_EVAL_TABLE_SHARE_WITH") or None, only=only, locked=locked)
    except NextcloudError as err:
        print(f"publish FAILED: {err}", file=sys.stderr)
        return 1
    # Locked files stay out of the record, so the next publish retries them.
    hashes = {rel: h for rel, h in file_hashes(files).items() if rel not in locked}
    try:
        save_state(state_path, hashes)
    except OSError as err:  # next publish just uploads everything again
        print(f"publish: could not save {state_path}: {err}", file=sys.stderr)
    sent = (len(files) if only is None else len(only)) - len(locked)
    skipped = (f"; {len(locked)} locked (open in Nextcloud?), retried next publish: {', '.join(locked)}"
               if locked else "")
    print(f"published {sent} changed of {len(files)} files to {FOLDER}/; table '{TABLE_TITLE}' (id {table_id}): "
          f"{created} rows created, {updated} updated, {unchanged} unchanged{skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
