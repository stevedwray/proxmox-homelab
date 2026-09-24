"""Celery worker for cse-controller -- runs on cse-controller itself (see
docker-compose.yml's `worker` service), consuming jobs submitted by
cse-panel-stack's panel-web across the cse_seg -> mgmt_seg:6379 firewall
rule. One task, run_benchmark, covers every benchmark proven in the
2026-09-19 small-batch run (see
docs/cyberseceval-implementation/current-state.md) -- the same CLI shapes
as ansible/00-initial-setup/cse-small-batch-run.yml's run-batch.sh,
parameterized instead of hardcoded per-benchmark.

Backend selection (2026-09-19): the model-under-test endpoint is no
longer a fixed constant -- the caller can point this at any
OpenAI-compatible server (Ollama's /v1, llama.cpp server's /v1, or
anything else) by passing backend_base_url/backend_model. Assumes the
engine already has a model loaded; this does not manage model loading.
Framework's llama-server remains the default when nothing is specified,
matching every benchmark run proven so far.
"""
import json
import os
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from celery import Celery

BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

app = Celery("cse_tasks", broker=BROKER_URL, backend=RESULT_BACKEND)
# Default acks-on-dispatch would silently drop whatever job was actually
# executing if the worker is killed/restarted mid-run (confirmed live
# 2026-09-19 -- two jobs stuck behind a hung Framework llama-server request
# vanished with no error when the worker was restarted to clear the hang).
# acks_late + prefetch=1 makes a killed/restarted worker redeliver the
# in-flight job instead of losing it.
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1

REPO_DIR = Path("/srv/cyberseceval/repo/PurpleLlama")
VENV_PY = Path("/srv/cyberseceval/.venv/bin/python3")
RUNS_DIR = Path("/srv/cyberseceval/runs")

# Framework's llama-server -- the default when no backend override is
# given, matching the exact spec proven in Phase 2
# (docs/cyberseceval-implementation/current-state.md).
DEFAULT_BACKEND_BASE_URL = "http://framework.gibbsgreatly.xyz:8080/v1"
DEFAULT_BACKEND_MODEL = (
    "/models/qwen3.8-flash-next-q4/UD-Q4_K_XL/"
    "Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf"
)


def _build_mut_spec(
    backend_base_url: str | None, backend_model: str | None, backend_api_key: str | None
) -> str:
    """Builds the OPENAI::<model>::<key>::<base_url> spec run.py expects.
    Ollama and llama.cpp server both expose an OpenAI-compatible /v1 API,
    so the same OPENAI provider works for any of them -- only the model
    name and base_url actually change."""
    base_url = backend_base_url or DEFAULT_BACKEND_BASE_URL
    model = backend_model or DEFAULT_BACKEND_MODEL
    key = backend_api_key or "not-needed"
    return f"OPENAI::{model}::{key}::{base_url}"


def _judge_spec() -> str:
    # Cloud judge (gpt-4o-mini), independent of the model-under-test
    # backend -- operator's explicit choice for Phase 2, unrelated to
    # backend selection above.
    key = os.environ["OPENAI_API_KEY"]
    return f"OPENAI::gpt-4o-mini::{key}"


# Default dataset path for each benchmark, relative to REPO_DIR -- the
# full, unfiltered test-case pool. Used both as the default --prompt-path
# and, when random sampling is requested, as the source _sample_prompts
# reads from before writing a per-job subset.
_DATASET_PATHS = {
    "mitre": "CybersecurityBenchmarks/datasets/mitre/mitre_benchmark_100_per_category_with_augmentation.json",
    "mitre-frr": "CybersecurityBenchmarks/datasets/mitre_frr/mitre_frr.json",
    "prompt-injection": "CybersecurityBenchmarks/datasets/prompt_injection/prompt_injection.json",
    "interpreter": "CybersecurityBenchmarks/datasets/interpreter/interpreter.json",
    "instruct": "CybersecurityBenchmarks/datasets/instruct/instruct-v2.json",
    "autocomplete": "CybersecurityBenchmarks/datasets/autocomplete/autocomplete.json",
    "malware_analysis": "CybersecurityBenchmarks/datasets/crwd_meta/malware_analysis/questions.json",
    "threat_intel_reasoning": "CybersecurityBenchmarks/datasets/crwd_meta/threat_intel_reasoning/report_questions.json",
    "multiturn-phishing": "CybersecurityBenchmarks/datasets/spear_phishing/multiturn_phishing_challenges.json",
}

# Each entry: the exact argv (minus python3/module prefix) run.py needs,
# using {run_dir} as the per-job output directory placeholder, {mut_spec}
# as the selected backend's LLM spec, and {prompt_path} as either the
# default dataset above or a per-job random-sampled subset of it.
_BENCHMARK_COMMANDS = {
    "mitre": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=mitre",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}", f"--expansion-llm={_judge_spec()}",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "mitre-frr": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=mitre-frr",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "prompt-injection": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=prompt-injection",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "interpreter": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=interpreter",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--judge-llm={_judge_spec()}",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "instruct": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=instruct",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "autocomplete": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=autocomplete",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "malware_analysis": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=malware_analysis",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "threat_intel_reasoning": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=threat_intel_reasoning",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        "--input-modality=text",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
    "multiturn-phishing": lambda run_dir, n, mut_spec, prompt_path: [
        "-m", "CybersecurityBenchmarks.benchmark.run", "--benchmark=multiturn-phishing",
        f"--prompt-path={prompt_path}",
        f"--response-path={run_dir}/responses.json",
        f"--judge-response-path={run_dir}/judge_responses.json",
        f"--stat-path={run_dir}/stats.json",
        f"--judge-llm={mut_spec}",
        f"--llm-under-test={mut_spec}", f"--num-test-cases={n}",
    ],
}


def _sample_prompts(benchmark: str, run_dir: Path, n: int) -> str:
    """Writes a random subset of n test cases from the benchmark's full
    dataset into the job's own run_dir and returns that path. Without
    this, --num-test-cases picks a fixed, evenly-strided slice of the
    dataset every time (see PurpleLlama's query_llm.py) -- same benchmark
    plus same count always ran the identical prompts, run after run.
    Dataset is read relative to REPO_DIR since --prompt-path is resolved
    against the benchmark CLI's own cwd."""
    dataset_path = REPO_DIR / _DATASET_PATHS[benchmark]
    dataset = json.loads(dataset_path.read_text())
    sample_size = min(n, len(dataset)) if n > 0 else len(dataset)
    sampled = random.sample(dataset, sample_size)  # nosonar: benchmark selection, not security-sensitive
    sample_path = run_dir / "sampled_prompts.json"
    sample_path.write_text(json.dumps(sampled))
    return str(sample_path)


def _humanize_key(k: str) -> str:
    return k.replace("_", " ").replace(".", " / ").strip().title()


def _format_scalar(key: str, value) -> object:
    """0-1 floats in a field that's clearly a rate/percentage read as a
    bare fraction (e.g. "0.4123") -- render as a real percentage instead."""
    if isinstance(value, float):
        lower = key.lower()
        if "rate" in lower or "percentage" in lower:
            pct = value * 100 if value <= 1 else value
            return f"{pct:.1f}%"
        return round(value, 4)
    return value


def _flatten_stats(stats, limit: int = 20) -> list[list]:
    """Same logic as cse-panel-stack's app.py _flatten_stats (kept in
    sync manually -- different container/codebase, no shared package)
    -- the actual pass/fail/refusal numbers people care about, in plain
    language, not the full nested stat.json/stats.json blob. See that
    function's own docstring for the two real shapes this was tuned
    against (mitre, mitre-frr) and the caveat that other benchmarks may
    need their own tuning once seen."""
    out: list[list] = []

    def render_count_cluster(node: dict, prefix: str) -> bool:
        total = node.get("total_count")
        count_keys = [k for k in node if k.endswith("_count") and k != "total_count"]
        if not isinstance(total, (int, float)) or not count_keys:
            return False
        for k in count_keys:
            v = node[k]
            label = _humanize_key(k[: -len("_count")])
            key = f"{prefix}.{label}" if prefix else label
            pct = f"{(v / total * 100):.0f}%" if total else "n/a"
            out.append([key, f"{v}/{total} ({pct})"])
        return True

    def walk(node, prefix: str, depth: int) -> None:
        if len(out) >= limit or depth > 5 or not isinstance(node, dict):
            return
        items = list(node.items())
        if len(items) == 1 and isinstance(items[0][1], dict):
            walk(items[0][1], prefix, depth)
            return
        if render_count_cluster(node, prefix):
            return
        for k, v in items:
            if len(out) >= limit:
                break
            key = f"{prefix}.{_humanize_key(k)}" if prefix else _humanize_key(k)
            if isinstance(v, bool) or isinstance(v, (int, str, float)):
                out.append([key, _format_scalar(k, v)])
            elif isinstance(v, dict):
                walk(v, key, depth + 1)

    walk(stats, "", 0)
    return out[:limit]


def _write_report(
    run_dir: Path,
    benchmark: str,
    result: dict,
    started_at: str,
    submitted_by: str,
    num_test_cases: int,
    random_sample: bool,
) -> None:
    """Writes report.md + manifest.json per
    docs/reporting-platform/CONVENTION.md -- the actual Phase 2 fix
    (docs/reporting-platform/plan.md): this is durable disk storage on
    cse-controller itself, independent of Celery/Redis's own
    result_expires TTL and independent of cse-panel-stack's separate
    24h job_meta TTL (see that stack's app.py JOB_META_TTL). The raw
    responses.json/judge_responses.json/run.log this function's caller
    already writes were never actually lost to Redis -- only the
    panel's ability to *discover* a run again once Redis forgets it,
    since nothing else indexed these directories. report.md/
    manifest.json existing here means a run survives that regardless.
    """
    finished_at = datetime.now(timezone.utc).isoformat()
    stats = result.get("stats")
    stats_error = result.get("stats_error")
    flattened = _flatten_stats(stats) if stats is not None else []

    if stats_error:
        summary = f"{benchmark}: failed -- {stats_error}"
    elif flattened:
        summary = f"{benchmark}: " + ", ".join(f"{k}={v}" for k, v in flattened[:3])
    else:
        summary = f"{benchmark}: completed, {num_test_cases} test case(s)"
    summary = summary[:300]

    lines = [
        f"# CyberSecEval: {benchmark}",
        "",
        f"**Submitted by:** {submitted_by}  ",
        f"**Started:** {started_at}  ",
        f"**Finished:** {finished_at}  ",
        f"**Summary:** {summary}  ",
        f"**Backend:** {result.get('backend_model')} @ {result.get('backend_base_url')}  ",
        f"**Test cases:** {num_test_cases} (random sample: {random_sample})",
        "",
        "## Result",
        "",
    ]
    if stats is not None:
        if flattened:
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for label, value in flattened:
                lines.append(f"| {label} | {value} |")
        else:
            lines.append("```json")
            lines.append(json.dumps(stats, indent=2))
            lines.append("```")
    elif stats_error:
        lines.append(f"**No stats produced:** {stats_error}")
    else:
        lines.append("No stats and no error captured -- see `run.log`.")

    lines += [
        "",
        "## Artifacts",
        "",
        "- `run.log` -- full stdout/stderr",
        "- `responses.json` / `judge_responses.json` -- raw per-test-case transcripts",
        "- `stat.json` / `stats.json` -- raw benchmark output this report summarizes",
    ]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")

    (run_dir / "manifest.json").write_text(json.dumps({
        "project": "cyberseceval",
        "run_id": run_dir.name,
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": summary,
    }, indent=2))

    _push_report_to_nextcloud(run_dir, benchmark)


def _push_report_to_nextcloud(run_dir: Path, benchmark: str) -> None:
    """Best-effort WebDAV push of this run's report.md into Nextcloud,
    per docs/reporting-platform/plan.md Sec5a (2026-09-25). Never raises
    -- report.md is already durable on cse-controller's own disk
    (docs/reporting-platform/CONVENTION.md); Nextcloud being briefly
    unreachable or a rotated credential must never fail a benchmark
    run that has already completed."""
    webdav_url = os.environ.get("NEXTCLOUD_REPORTS_WEBDAV_URL", "")
    user = os.environ.get("NEXTCLOUD_REPORTS_USER", "")
    password = os.environ.get("NEXTCLOUD_REPORTS_APP_PASSWORD", "")
    if not (webdav_url and user and password):
        return

    import base64
    import urllib.error
    import urllib.request

    auth_header = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    base = webdav_url.rstrip("/")
    for collection_url in (f"{base}/cyberseceval", f"{base}/cyberseceval/{run_dir.name}"):
        request = urllib.request.Request(collection_url, method="MKCOL")
        request.add_header("Authorization", auth_header)
        try:
            urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 301):
                return
        except urllib.error.URLError:
            return

    put_url = f"{base}/cyberseceval/{run_dir.name}/report.md"
    request = urllib.request.Request(
        put_url, data=(run_dir / "report.md").read_bytes(), method="PUT"
    )
    request.add_header("Authorization", auth_header)
    request.add_header("Content-Type", "text/markdown")
    try:
        urllib.request.urlopen(request, timeout=15)
    except urllib.error.URLError:
        pass


def _extract_failure_reason(log_text: str, max_chars: int = 300) -> str:
    """The last non-empty line of a run's combined stdout/stderr -- for a
    Python traceback that's the actual exception message (e.g. "ValueError:
    Response cannot be empty.", "statistics.StatisticsError: variance
    requires at least two data points"), and for a plain warning line
    (e.g. autonomous-uplift's "Grading is not implemented yet.") it's that
    line verbatim. Cheap and generic -- no benchmark-specific parsing --
    but covers every real failure seen so far. Confirmed live 2026-09-19:
    the panel's generic "may have failed" message wasn't informative
    enough to tell three genuinely different failure causes apart."""
    lines = [line for line in log_text.strip().splitlines() if line.strip()]
    return lines[-1][:max_chars] if lines else ""


def _run_autonomous_uplift(run_dir: Path, shots: int, mut_spec: str) -> dict:
    gen_cmd = [
        str(VENV_PY), "-m", "CybersecurityBenchmarks.datasets.autonomous_uplift.test_case_generator",
        "--ssh-key-file=/srv/cyberseceval/config/cse-kali-agent-key",
        "--ssh-username=kali",
        "--cyber-range-file=/srv/cyberseceval/config/cyber_range_pairs.json",
        "--system-prompt-file=CybersecurityBenchmarks/datasets/autonomous_uplift/in/system_prompt.txt",
        f"--out-file={run_dir}/prompts.json",
        f"--shots-per-run={shots}", "--runs-per-range=1",
    ]
    gen = subprocess.run(gen_cmd, cwd=REPO_DIR, capture_output=True, text=True)
    if gen.returncode != 0:
        return {"rc": gen.returncode, "stage": "generate", "log": gen.stdout + gen.stderr}
    attack_cmd = [
        str(VENV_PY), "-m", "CybersecurityBenchmarks.benchmark.run",
        "--benchmark=autonomous-uplift",
        f"--prompt-path={run_dir}/prompts.json",
        f"--response-path={run_dir}/responses.json",
        f"--stat-path={run_dir}/stat.json",
        f"--llm-under-test={mut_spec}",
    ]
    attack = subprocess.run(attack_cmd, cwd=REPO_DIR, capture_output=True, text=True)
    return {"rc": attack.returncode, "stage": "attack", "log": attack.stdout + attack.stderr}


@app.task(name="cse_tasks.run_benchmark")
def run_benchmark(
    benchmark: str,
    num_test_cases: int = 2,
    submitted_by: str = "unknown",
    backend_base_url: str | None = None,
    backend_model: str | None = None,
    backend_api_key: str | None = None,
    random_sample: bool = False,
) -> dict:
    job_id = run_benchmark.request.id
    run_dir = RUNS_DIR / f"panel-{job_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    mut_spec = _build_mut_spec(backend_base_url, backend_model, backend_api_key)
    started_at = datetime.now(timezone.utc).isoformat()
    (run_dir / "meta.json").write_text(json.dumps({
        "benchmark": benchmark,
        "num_test_cases": num_test_cases,
        "submitted_by": submitted_by,
        "backend_base_url": backend_base_url or DEFAULT_BACKEND_BASE_URL,
        "backend_model": backend_model or DEFAULT_BACKEND_MODEL,
        "random_sample": random_sample,
        "started_at": started_at,
    }))

    if benchmark == "autonomous-uplift":
        # No static dataset to sample from -- each run already generates
        # fresh attack shots live against the cyber range, so random_sample
        # doesn't apply here.
        result = _run_autonomous_uplift(run_dir, shots=num_test_cases, mut_spec=mut_spec)
        log_text = result.get("log", "")
    else:
        if benchmark not in _BENCHMARK_COMMANDS:
            result = {"rc": 1, "error": f"unknown benchmark '{benchmark}'", "stats_error": f"unknown benchmark '{benchmark}'"}
            _write_report(run_dir, benchmark, result, started_at, submitted_by, num_test_cases, random_sample)
            return result
        prompt_path = (
            _sample_prompts(benchmark, run_dir, num_test_cases)
            if random_sample
            else _DATASET_PATHS[benchmark]
        )
        argv = [str(VENV_PY)] + _BENCHMARK_COMMANDS[benchmark](str(run_dir), num_test_cases, mut_spec, prompt_path)
        proc = subprocess.run(argv, cwd=REPO_DIR, capture_output=True, text=True)
        log_text = proc.stdout + proc.stderr
        (run_dir / "run.log").write_text(log_text)
        result = {"rc": proc.returncode, "log_path": str(run_dir / "run.log")}

    result["run_dir"] = str(run_dir)
    result["backend_base_url"] = backend_base_url or DEFAULT_BACKEND_BASE_URL
    result["backend_model"] = backend_model or DEFAULT_BACKEND_MODEL

    # The actual substantive result -- refusal/malicious/vulnerable
    # percentages, per-category breakdowns, etc. -- lives in whichever
    # stat file the benchmark wrote (most use stat.json; malware_analysis/
    # threat_intel_reasoning/multiturn-phishing use stats.json). Without
    # this, the Celery result was just a return code and a log path on a
    # filesystem the caller can't reach -- not the thing anyone actually
    # wants to see after running a benchmark.
    for stat_name in ("stat.json", "stats.json"):
        stat_path = run_dir / stat_name
        if stat_path.exists():
            try:
                result["stats"] = json.loads(stat_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                result["stats_error"] = f"failed to read {stat_name}: {e}"
            break
    else:
        reason = _extract_failure_reason(log_text)
        result["stats_error"] = (
            f"no stat.json/stats.json found -- {reason}" if reason
            else "no stat.json/stats.json found -- benchmark may have failed before producing one"
        )

    # Per-test-case transcripts (the actual prompt text, the model's real
    # response, and the judgment) -- genuinely useful for research, not
    # just the aggregate stats above. judge_responses.json (when a judge
    # was used) is a superset of responses.json with the verdict added,
    # so prefer it; fall back to responses.json for benchmarks with no
    # judge (e.g. mitre-frr, which self-classifies via its own
    # judge_response field already inline).
    for transcript_name in ("judge_responses.json", "responses.json"):
        transcript_path = run_dir / transcript_name
        if transcript_path.exists():
            try:
                result["transcript"] = json.loads(transcript_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                result["transcript_error"] = f"failed to read {transcript_name}: {e}"
            break
    else:
        result["transcript_error"] = "no responses.json/judge_responses.json found"

    _write_report(run_dir, benchmark, result, started_at, submitted_by, num_test_cases, random_sample)
    return result
