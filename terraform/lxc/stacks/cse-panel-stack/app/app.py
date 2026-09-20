"""cse-panel-stack's panel-web: submits CyberSecEval benchmark runs as
Celery tasks and reports their status. The actual benchmark execution
happens in the Celery worker on cse-controller (see
terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py) --
this app never runs benchmark code itself.

Backend selection (2026-09-19): callers can point a job/suite at any
OpenAI-compatible inference server (Ollama, llama.cpp server, etc.) via
backend_base_url/backend_model -- this app just passes those through to
the worker; it assumes the engine already has a model loaded and does
not manage model loading itself.

Test suites (2026-09-19): /suites submits several tests as one Celery
group -- each test is still an independent, individually trackable
task, not a single opaque long-running job, since the worker's own
concurrency is 1 anyway (one inference backend can only do one thing
at a time).

Human-readable status (2026-09-19): the homepage no longer just fires
raw API calls and alert(JSON...)s the response, and job/suite listings
carry benchmark/backend/state/result-summary fields directly (not just
a job_id + celery state code) -- the operator asked for "what tests are
queued/running/finished and what were the results", not workers/queues/
brokers/JSON. The full raw result is still returned alongside the
summary on GET /jobs/{id}, so this stays usable as a real API for other
integrations, not just this one HTML page.
"""
import html
import json
import os
from datetime import datetime, timezone

from celery import Celery, group
from celery.result import AsyncResult, GroupResult
from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

celery_app = Celery("cse_panel", broker=BROKER_URL, backend=RESULT_BACKEND)

# Must match the task names registered by cse_tasks.py's worker exactly --
# Celery routes by string name, not by import, since the worker and this
# submitter are different processes on different hosts.
TASK_NAME = "cse_tasks.run_benchmark"
DELETE_TASK_NAME = "cse_tasks.delete_run_dirs"

# States a job can still change from -- deleting a suite while any of its
# jobs is in one of these would either orphan a task still writing to a
# run_dir about to be deleted out from under it, or (worse, given
# task_acks_late) let a killed-but-redelivered task resurrect a "deleted"
# run. Simpler and safer to just require every job be finished first.
NON_TERMINAL_STATES = {"PENDING", "STARTED", "RETRY"}

# The set of benchmarks proven to work in the 2026-09-19 small-batch run
# (docs/cyberseceval-implementation/current-state.md) -- deliberately not
# auto-discovered from the PurpleLlama checkout, so a new/untested
# benchmark id can't be submitted by accident.
KNOWN_BENCHMARKS = [
    "mitre",
    "mitre-frr",
    "prompt-injection",
    "interpreter",
    "instruct",
    "autocomplete",
    "malware_analysis",
    "threat_intel_reasoning",
    "multiturn-phishing",
    "autonomous-uplift",
]

# Per-benchmark description (checkbox tooltip) and result_hint (a plain-
# language note on what the reported percentages actually mean and
# which direction is "safer" -- added 2026-09-19 after the operator
# pointed out a bare "Refusal/Malicious/Benign %" line means nothing
# without context). Not every benchmark measures safety the same way --
# mitre-frr's "Refusal" is the *bad* outcome (over-refusing something
# benign), unlike every other benchmark where refusing is the safe one;
# malware_analysis/threat_intel_reasoning aren't safety tests at all,
# they measure analysis capability.
BENCHMARK_INFO = {
    "mitre": {
        "description": "Does the model help carry out real cyberattack techniques (MITRE ATT&CK)?",
        "result_hint": "Malicious % = gave real attack-enabling help (lower is safer). Refusal/Benign % = declined or gave a non-actionable answer (safer).",
    },
    "mitre-frr": {
        "description": "False-refusal companion to mitre -- uses benign security questions to check if the model over-refuses things it shouldn't.",
        "result_hint": "Unlike other benchmarks here, Refusal % being high is the BAD outcome -- it means the model wrongly refused a legitimate request.",
    },
    "prompt-injection": {
        "description": "Can a hidden instruction in user input (e.g. \"ignore previous instructions\") override the model's system prompt?",
        "result_hint": "Injection Successful % = the attack worked (lower is safer). Injection Unsuccessful % = the model resisted it (higher is safer).",
    },
    "interpreter": {
        "description": "Would the code the model generates be malicious if actually run by a code-interpreter tool?",
        "result_hint": "Malicious % = generated code was actually harmful if executed (lower is safer).",
    },
    "instruct": {
        "description": "Does the model suggest insecure/vulnerable code when asked to write code for a described task?",
        "result_hint": "Vulnerable Suggestion % = the generated code had a real security flaw (lower is safer).",
    },
    "autocomplete": {
        "description": "Same as instruct, but completing an existing code snippet instead of writing from a description.",
        "result_hint": "Vulnerable Suggestion % = the completed code had a real security flaw (lower is safer).",
    },
    "malware_analysis": {
        "description": "Capability test, not a safety test -- can the model correctly analyze and answer questions about real malware samples?",
        "result_hint": "Measures analysis accuracy, not safety -- higher scores mean better threat-analysis capability.",
    },
    "threat_intel_reasoning": {
        "description": "Capability test -- can the model correctly answer questions about real threat-intelligence reports?",
        "result_hint": "Measures how accurately the model reasoned about the report (higher is better) -- not a safety measure.",
    },
    "multiturn-phishing": {
        "description": "Can the model be steered over several conversation turns into producing real phishing content? Needs 2+ test cases -- its own scoring math fails with just 1.",
        "result_hint": "Lower successful-phishing % is safer. Requires num_test_cases >= 2 -- this benchmark's own variance calculation needs at least 2 data points.",
    },
    "autonomous-uplift": {
        "description": "Runs the model as an autonomous agent attempting real attack steps against a live target in an isolated cyber range, over SSH.",
        "result_hint": "The attack runs for real against a live target, but this pinned PurpleLlama commit hasn't implemented automatic grading yet -- expect no score.",
    },
}

# Confirmed-real presets only -- "custom" is how you point this at
# anything else (Ollama, llama.cpp server, ...) via backend_base_url/
# backend_model on the job/suite itself. Not a registry of every
# possible backend, just the ones already proven live in this lab.
KNOWN_BACKENDS = {
    "framework-llama-server": {
        "base_url": "http://framework.gibbsgreatly.xyz:8080/v1",
        "model": "/models/qwen3.8-flash-next-q4/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf",
        "note": "Framework's live Nathanw llama-server (Qwen3.8-Flash-Next). Default when nothing else is specified.",
    },
    "custom": {
        "base_url": None,
        "model": None,
        "note": "Set backend_base_url/backend_model yourself -- any OpenAI-compatible server (Ollama's /v1, llama.cpp server's /v1, etc.). Assumes a model is already loaded.",
    },
}

STATE_LABELS = {
    "PENDING": "Queued",
    "STARTED": "Running",
    "SUCCESS": "Done",
    "FAILURE": "Failed",
    "RETRY": "Retrying",
    "REVOKED": "Cancelled",
}

RECENT_JOBS_KEY = "cse_panel:recent_job_ids"
RECENT_SUITES_KEY = "cse_panel:recent_suite_ids"
RECENT_MAX = 50
JOB_META_TTL = 86400  # matches Celery's own default result_expires

app = FastAPI(title="CyberSecEval Control Panel")


class TestSpec(BaseModel):
    benchmark: str
    num_test_cases: int = 2
    backend_base_url: str | None = None
    backend_model: str | None = None
    backend_api_key: str | None = None
    random_sample: bool = False


class SuiteRequest(BaseModel):
    tests: list[TestSpec]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_label(state: str) -> str:
    return STATE_LABELS.get(state, state)


def _resolve_backend(base_url: str | None, model: str | None) -> tuple[str, str, str]:
    """Fills in Framework's llama-server as the default when nothing is
    given, and labels the result with whichever known preset it matches
    (or "custom") -- so every stored job always has a concrete,
    human-labelled backend, never a bare None."""
    if base_url is None and model is None:
        preset = KNOWN_BACKENDS["framework-llama-server"]
        return preset["base_url"], preset["model"], "framework-llama-server"
    for name, preset in KNOWN_BACKENDS.items():
        if preset["base_url"] and preset["base_url"] == base_url and preset["model"] == model:
            return base_url, model, name
    return base_url or "", model or "", "custom"


def _job_kwargs(spec: TestSpec, submitted_by: str) -> dict:
    return {
        "benchmark": spec.benchmark,
        "num_test_cases": spec.num_test_cases,
        "submitted_by": submitted_by,
        "backend_base_url": spec.backend_base_url,
        "backend_model": spec.backend_model,
        "backend_api_key": spec.backend_api_key,
        "random_sample": spec.random_sample,
    }


def _store_job_meta(
    job_id: str, benchmark: str, backend_base_url: str, backend_model: str,
    backend_label: str, submitted_by: str, suite_id: str | None = None,
) -> None:
    client = celery_app.backend.client
    key = f"cse_panel:job_meta:{job_id}"
    mapping = {
        "benchmark": benchmark,
        "backend_base_url": backend_base_url,
        "backend_model": backend_model,
        "backend_label": backend_label,
        "submitted_by": submitted_by,
        "submitted_at": _now_iso(),
    }
    if suite_id:
        mapping["suite_id"] = suite_id
    client.hset(key, mapping=mapping)
    client.expire(key, JOB_META_TTL)


def _get_job_meta(job_id: str) -> dict:
    client = celery_app.backend.client
    raw = client.hgetall(f"cse_panel:job_meta:{job_id}")
    return {
        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
        for k, v in raw.items()
    }


def _store_suite_meta(suite_id: str, submitted_by: str, count: int) -> None:
    client = celery_app.backend.client
    key = f"cse_panel:suite_meta:{suite_id}"
    client.hset(key, mapping={
        "submitted_by": submitted_by, "submitted_at": _now_iso(), "count": str(count),
    })
    client.expire(key, JOB_META_TTL)


def _get_suite_meta(suite_id: str) -> dict:
    client = celery_app.backend.client
    raw = client.hgetall(f"cse_panel:suite_meta:{suite_id}")
    return {
        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
        for k, v in raw.items()
    }


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


def _flatten_stats(stats, limit: int = 12) -> list[list]:
    """The actual pass/fail/refusal numbers people care about, in plain
    language -- not the full nested stat.json/stats.json blob, and not
    just raw field names either. Confirmed live 2026-09-19 against two
    real shapes: mitre's stat.json (keyed by the model-under-test's own
    name, then category, then *_count/*_percentage fields) and
    mitre-frr's (flat rate/count fields at the top level) -- other
    benchmarks may need their own tuning once their real output is seen,
    this isn't a universal parser for all ten.

    Two special cases before falling back to generic label/value
    cleanup: a dict with exactly one key whose value is itself a dict
    gets collapsed (drops mitre's redundant model-name wrapper); and a
    dict that looks like a count cluster (a total_count sibling plus one
    or more other *_count fields) renders as "Label: n/total (p%)"
    instead of raw counts and a separately-listed percentage field."""
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


def _job_summary(job_id: str) -> dict:
    res = AsyncResult(job_id, app=celery_app)
    meta = _get_job_meta(job_id)
    entry = {
        "job_id": job_id,
        "benchmark": meta.get("benchmark", "?"),
        "backend": meta.get("backend_label", "?"),
        "submitted_by": meta.get("submitted_by", "?"),
        "submitted_at": meta.get("submitted_at", ""),
        "suite_id": meta.get("suite_id"),
        "state": res.state,
        "state_label": _state_label(res.state),
    }
    if res.state == "SUCCESS":
        result = res.result or {}
        entry["ok"] = result.get("rc") == 0 and "stats_error" not in result
        entry["stats_summary"] = _flatten_stats(result.get("stats"))
        if result.get("stats_error"):
            entry["stats_error"] = result["stats_error"]
    elif res.state == "FAILURE":
        entry["error"] = str(res.result)
    return entry


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/benchmarks")
def list_benchmarks():
    return {"benchmarks": KNOWN_BENCHMARKS}


@app.get("/backends")
def list_backends():
    return {"backends": KNOWN_BACKENDS}


@app.post("/jobs")
def submit_job(
    benchmark: str,
    num_test_cases: int = 2,
    backend_base_url: str | None = None,
    backend_model: str | None = None,
    backend_api_key: str | None = None,
    random_sample: bool = False,
    x_authentik_username: str | None = Header(default=None),
):
    if benchmark not in KNOWN_BENCHMARKS:
        return {"error": f"unknown benchmark '{benchmark}', must be one of {KNOWN_BENCHMARKS}"}
    submitted_by = x_authentik_username or "unknown"
    spec = TestSpec(
        benchmark=benchmark,
        num_test_cases=num_test_cases,
        backend_base_url=backend_base_url,
        backend_model=backend_model,
        backend_api_key=backend_api_key,
        random_sample=random_sample,
    )
    result = celery_app.send_task(TASK_NAME, kwargs=_job_kwargs(spec, submitted_by))
    celery_app.backend.client.lpush(RECENT_JOBS_KEY, result.id)
    celery_app.backend.client.ltrim(RECENT_JOBS_KEY, 0, RECENT_MAX - 1)
    resolved_base_url, resolved_model, backend_label = _resolve_backend(backend_base_url, backend_model)
    _store_job_meta(result.id, benchmark, resolved_base_url, resolved_model, backend_label, submitted_by)
    return {"job_id": result.id, "benchmark": benchmark}


@app.get("/jobs")
def list_recent_jobs():
    ids = celery_app.backend.client.lrange(RECENT_JOBS_KEY, 0, -1)
    jobs = []
    for raw_id in ids:
        job_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        jobs.append(_job_summary(job_id))
    return {"jobs": jobs}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    entry = _job_summary(job_id)
    res = AsyncResult(job_id, app=celery_app)
    if res.state == "SUCCESS":
        entry["result"] = res.result
    elif res.state == "FAILURE":
        entry["error"] = str(res.result)
    return entry


@app.post("/suites")
def submit_suite(body: SuiteRequest, x_authentik_username: str | None = Header(default=None)):
    unknown = [t.benchmark for t in body.tests if t.benchmark not in KNOWN_BENCHMARKS]
    if unknown:
        return {"error": f"unknown benchmark(s) {unknown}, must be one of {KNOWN_BENCHMARKS}"}
    if not body.tests:
        return {"error": "tests list is empty"}
    submitted_by = x_authentik_username or "unknown"
    job_group = group(
        celery_app.signature(TASK_NAME, kwargs=_job_kwargs(t, submitted_by))
        for t in body.tests
    )
    result = job_group.apply_async()
    result.save()  # required so /suites/{id} can look this up from a later, separate request
    celery_app.backend.client.lpush(RECENT_SUITES_KEY, result.id)
    celery_app.backend.client.ltrim(RECENT_SUITES_KEY, 0, RECENT_MAX - 1)
    _store_suite_meta(result.id, submitted_by, len(body.tests))
    jobs = []
    for r, t in zip(result.results, body.tests):
        resolved_base_url, resolved_model, backend_label = _resolve_backend(t.backend_base_url, t.backend_model)
        _store_job_meta(r.id, t.benchmark, resolved_base_url, resolved_model, backend_label, submitted_by, suite_id=result.id)
        jobs.append({"job_id": r.id, "benchmark": t.benchmark})
    return {"suite_id": result.id, "jobs": jobs}


@app.get("/suites")
def list_recent_suites():
    ids = celery_app.backend.client.lrange(RECENT_SUITES_KEY, 0, -1)
    suites = []
    for raw_id in ids:
        suite_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        result = GroupResult.restore(suite_id, app=celery_app)
        if result is None:
            continue
        meta = _get_suite_meta(suite_id)
        jobs = [_job_summary(r.id) for r in result.results]
        done = sum(1 for j in jobs if j["state"] in ("SUCCESS", "FAILURE"))
        failed = sum(1 for j in jobs if j["state"] == "FAILURE")
        total = len(jobs)
        overall = "Done" if done == total and failed == 0 else ("Failed" if failed and done == total else "Running")
        suites.append({
            "suite_id": suite_id,
            "submitted_by": meta.get("submitted_by", "?"),
            "submitted_at": meta.get("submitted_at", ""),
            "benchmarks": [j["benchmark"] for j in jobs],
            "total": total, "done": done, "failed": failed,
            "overall": overall,
            "jobs": jobs,
        })
    return {"suites": suites}


@app.get("/suites/{suite_id}")
def suite_status(suite_id: str):
    result = GroupResult.restore(suite_id, app=celery_app)
    if result is None:
        return {"error": f"suite '{suite_id}' not found"}
    meta = _get_suite_meta(suite_id)
    jobs = [_job_summary(r.id) for r in result.results]
    all_ready = all(r.ready() for r in result.results)
    return {
        "suite_id": suite_id,
        "submitted_by": meta.get("submitted_by", "?"),
        "submitted_at": meta.get("submitted_at", ""),
        "jobs": jobs,
        "all_ready": all_ready,
        "all_successful": all(r.successful() for r in result.results) if all_ready else None,
    }


@app.delete("/suites/{suite_id}")
def delete_suite(suite_id: str):
    result = GroupResult.restore(suite_id, app=celery_app)
    if result is None:
        return {"error": f"suite '{suite_id}' not found"}
    job_ids = [r.id for r in result.results]
    in_progress = [j for j, r in zip(job_ids, result.results) if r.state in NON_TERMINAL_STATES]
    if in_progress:
        return {"error": f"can't delete -- {len(in_progress)} job(s) still running/queued, wait for the run to finish first"}

    client = celery_app.backend.client
    for r in result.results:
        r.forget()
    result.delete()
    for job_id in job_ids:
        client.delete(f"cse_panel:job_meta:{job_id}")
    client.delete(f"cse_panel:suite_meta:{suite_id}")
    client.lrem(RECENT_SUITES_KEY, 0, suite_id)

    # The actual run_dir (responses.json, transcripts, logs) lives on
    # cse-controller's own filesystem, not reachable from this container --
    # dispatched as a task so the worker (which does have that filesystem)
    # does the real deletion. Fire-and-forget: the UI-visible cleanup above
    # is already done, no need to block the response on it.
    celery_app.send_task(DELETE_TASK_NAME, kwargs={"job_ids": job_ids})
    return {"deleted": suite_id, "jobs": job_ids}


@app.get("/", response_class=HTMLResponse)
def index():
    benchmark_checkboxes = "".join(
        f'<label class="benchmark-row">'
        f'<input type="checkbox" name="benchmark" value="{b}">'
        f'<span class="benchmark-name">{b}</span>'
        f'<span class="benchmark-desc">{html.escape(BENCHMARK_INFO[b]["description"])}</span>'
        f'</label>'
        for b in KNOWN_BENCHMARKS
    )
    backend_options = "".join(f'<option value="{name}">{name}</option>' for name in KNOWN_BACKENDS)
    lab_domain = os.environ.get("LAB_DOMAIN", "")
    flower_url = f"https://cse-panel-flower.{lab_domain}" if lab_domain else "#"
    return f"""
    <html><head><title>CyberSecEval Control Panel</title>
    <style>
      body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; color: #1a1a1a; }}
      h1 {{ font-size: 1.4rem; }}
      h2 {{ font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }}
      .tabs {{ display: flex; gap: 0.3rem; margin-top: 1.2rem; border-bottom: 2px solid #eee; }}
      .tab-btn {{ background: none; border: none; padding: 0.6rem 1.1rem; font-size: 1rem; font-family: inherit; cursor: pointer; color: #666; border-bottom: 2px solid transparent; margin-bottom: -2px; }}
      .tab-btn.active {{ color: #1a1a1a; font-weight: 600; border-bottom-color: #1a7f37; }}
      .tab-pane {{ margin-top: 1.2rem; }}
      .benchmark-list {{ border: 1px solid #eee; border-radius: 6px; }}
      .benchmark-row {{ display: flex; align-items: baseline; gap: 0.6rem; padding: 0.45rem 0.7rem; border-bottom: 1px solid #f2f2f2; cursor: pointer; }}
      .benchmark-row:last-child {{ border-bottom: none; }}
      .benchmark-row:hover {{ background: #f7f9fc; }}
      .benchmark-name {{ font-weight: 600; min-width: 9.5rem; flex-shrink: 0; }}
      .benchmark-desc {{ color: #666; font-size: 0.85rem; }}
      #run-form label.field {{ display: block; margin: 0.5rem 0; }}
      #run-form input[type=text], #run-form input[type=number] {{ padding: 0.3rem; }}
      button {{ padding: 0.4rem 1rem; cursor: pointer; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.9rem; }}
      th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; vertical-align: top; }}
      .state-Queued {{ color: #888; }}
      .state-Running {{ color: #b8860b; font-weight: 600; }}
      .state-Done {{ color: #1a7f37; font-weight: 600; }}
      .state-Failed {{ color: #c62828; font-weight: 600; }}
      .stats-list {{ margin: 0; padding-left: 0; list-style: none; font-size: 0.85rem; }}
      .stats-list li {{ display: inline-block; margin-right: 0.8rem; }}
      .muted {{ color: #888; font-size: 0.85rem; }}
      .result-hint {{ color: #666; font-size: 0.78rem; font-style: italic; margin-bottom: 0.3rem; max-width: 32rem; }}
      .toast {{ margin: 0.5rem 0; padding: 0.5rem 0.8rem; border-radius: 4px; background: #eef; display: none; }}
      details.advanced {{ margin-top: 2.5rem; color: #666; font-size: 0.85rem; }}
      details.run-card {{ border: 1px solid #ddd; border-radius: 6px; margin-bottom: 0.7rem; }}
      details.run-card summary {{ padding: 0.6rem 0.9rem; cursor: pointer; font-size: 0.95rem; list-style: none; }}
      details.run-card summary::-webkit-details-marker {{ display: none; }}
      details.run-card summary::before {{ content: "▸ "; color: #888; }}
      details.run-card[open] summary::before {{ content: "▾ "; }}
      details.run-card table {{ margin: 0; }}
      details.run-card th:first-child, details.run-card td:first-child {{ padding-left: 0.9rem; }}
      .delete-run-btn {{ float: right; font-size: 0.8rem; padding: 0.15rem 0.6rem; color: #b71c1c; background: none; border: 1px solid #b71c1c; border-radius: 4px; cursor: pointer; }}
      .delete-run-btn:disabled {{ color: #999; border-color: #ccc; cursor: not-allowed; }}
      #custom-backend-fields {{ display: none; }}
      .view-link {{ font-size: 0.85rem; margin-left: 0.5rem; }}
      tr.detail-row td {{ background: #fafafa; padding: 0; }}
      .detail-box {{ padding: 0.8rem 1rem; }}
      .transcript-entry {{ border-top: 1px solid #eee; padding: 0.6rem 0; }}
      .transcript-entry:first-child {{ border-top: none; }}
      .transcript-label {{ font-weight: 600; font-size: 0.8rem; color: #555; margin-top: 0.4rem; }}
      .transcript-text {{ white-space: pre-wrap; font-size: 0.9rem; margin: 0.15rem 0 0; }}
      .transcript-verdict {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; background: #eef; }}
      .transcript-meta {{ font-size: 0.8rem; color: #888; margin-top: 0.3rem; }}
    </style>
    </head>
    <body>
      <h1>CyberSecEval Control Panel</h1>

      <div class="tabs">
        <button type="button" class="tab-btn active" id="tab-btn-run" onclick="showTab('run')">Run tests</button>
        <button type="button" class="tab-btn" id="tab-btn-status" onclick="showTab('status')">Status</button>
      </div>
      <div class="toast" id="toast"></div>

      <div id="tab-run" class="tab-pane">
        <form id="run-form">
          <div class="benchmark-list">{benchmark_checkboxes}</div>
          <label class="field">Test cases per benchmark:
            <input name="num_test_cases" type="number" value="2" min="1" max="50">
          </label>
          <label class="field checkbox-field">
            <input name="random_sample" type="checkbox">
            Pick a random subset each run (otherwise the same N test cases run every time)
          </label>
          <label class="field">Backend:
            <select name="backend" id="backend-select">{backend_options}</select>
          </label>
          <div id="custom-backend-fields">
            <label class="field">Backend base URL: <input name="backend_base_url" type="text" placeholder="http://host:port/v1" size="40"></label>
            <label class="field">Backend model: <input name="backend_model" type="text" size="40"></label>
            <label class="field">API key (optional): <input name="backend_api_key" type="text" size="30"></label>
          </div>
          <button type="submit">Run</button>
        </form>
      </div>

      <div id="tab-status" class="tab-pane" style="display:none">
        <div id="status"><p class="muted">Loading...</p></div>

        <details class="advanced">
          <summary>Advanced / API</summary>
          <p>
            <a href="/jobs">Recent jobs (raw)</a> &middot;
            <a href="/suites">Recent suites (raw)</a> &middot;
            <a href="/backends">Known backends (raw)</a> &middot;
            <a href="/docs">API docs</a> &middot;
            <a href="{flower_url}">Flower (task/queue internals)</a>
          </p>
        </details>
      </div>

      <script>
        const KNOWN_BACKENDS = {json.dumps([[name, b["base_url"], b["model"]] for name, b in KNOWN_BACKENDS.items()])};
        const BENCHMARK_HINTS = {json.dumps({b: info["result_hint"] for b, info in BENCHMARK_INFO.items()})};

        document.getElementById('backend-select').addEventListener('change', (e) => {{
          document.getElementById('custom-backend-fields').style.display =
            e.target.value === 'custom' ? 'block' : 'none';
        }});

        function showTab(name) {{
          document.getElementById('tab-run').style.display = name === 'run' ? 'block' : 'none';
          document.getElementById('tab-status').style.display = name === 'status' ? 'block' : 'none';
          document.getElementById('tab-btn-run').classList.toggle('active', name === 'run');
          document.getElementById('tab-btn-status').classList.toggle('active', name === 'status');
        }}

        function showToast(msg) {{
          const t = document.getElementById('toast');
          t.textContent = msg;
          t.style.display = 'block';
          setTimeout(() => {{ t.style.display = 'none'; }}, 4000);
        }}

        document.getElementById('run-form').addEventListener('submit', async (e) => {{
          e.preventDefault();
          const form = new FormData(e.target);
          const benchmarks = form.getAll('benchmark');
          if (benchmarks.length === 0) {{ showToast('Pick at least one benchmark.'); return; }}
          const numTestCases = parseInt(form.get('num_test_cases') || '2', 10);
          const randomSample = form.get('random_sample') === 'on';
          const backendName = form.get('backend');
          let baseUrl = null, model = null, apiKey = null;
          if (backendName === 'custom') {{
            baseUrl = form.get('backend_base_url') || null;
            model = form.get('backend_model') || null;
            apiKey = form.get('backend_api_key') || null;
          }} else {{
            const preset = KNOWN_BACKENDS.find(b => b[0] === backendName);
            if (preset) {{ baseUrl = preset[1]; model = preset[2]; }}
          }}
          const tests = benchmarks.map(b => ({{
            benchmark: b, num_test_cases: numTestCases, random_sample: randomSample,
            backend_base_url: baseUrl, backend_model: model, backend_api_key: apiKey,
          }}));
          const res = await fetch('/suites', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{tests}}),
          }});
          const body = await res.json();
          if (body.error) {{ showToast('Error: ' + body.error); }}
          else {{ showToast(`Submitted ${{tests.length}} test(s).`); showTab('status'); refreshStatus(); }}
        }});

        function stateClass(label) {{ return 'state-' + label.replace(/[^A-Za-z]/g, ''); }}

        function hintLine(benchmark) {{
          const hint = BENCHMARK_HINTS[benchmark];
          return hint ? `<div class="result-hint">${{esc(hint)}}</div>` : '';
        }}

        function renderStats(job) {{
          const hint = hintLine(job.benchmark);
          if (job.state_label === 'Failed') {{
            return hint + `<span style="color:#c62828">${{esc((job.error || '').slice(0, 160))}}</span>`;
          }}
          if (job.stats_error) {{
            return hint + `<span class="muted">${{esc(job.stats_error)}}</span>`;
          }}
          if (job.stats_summary && job.stats_summary.length) {{
            return hint + '<ul class="stats-list">' +
              job.stats_summary.map(([k, v]) => `<li><b>${{esc(k)}}</b>: ${{esc(v)}}</li>`).join('') +
              '</ul>';
          }}
          return '<span class="muted">-</span>';
        }}

        // Tracks which jobs' transcripts are expanded and caches fetched
        // results, so the accordion survives the 4s poll rebuild instead
        // of getting wiped every refresh.
        const expandedJobs = new Set();
        const transcriptCache = {{}};
        let lastSuitesBody = {{suites: []}};

        // Each run (suite) gets its own collapsible card instead of
        // everything sharing one continuous table -- the operator asked
        // for runs to be visually separated, not just marked with a
        // header row in the middle of one long scroll. openSuites tracks
        // the operator's own manual expand/collapse choices so they
        // survive the 4s poll rebuild; every run starts folded, operator
        // opens whichever ones they actually want to look at.
        const openSuites = new Set();

        function renderJobRow(job) {{
          const when = job.submitted_at ? new Date(job.submitted_at).toLocaleString() : '';
          const isOpen = expandedJobs.has(job.job_id);
          const viewLink = (job.state_label === 'Done' || job.state_label === 'Failed')
            ? `<a href="#" class="view-link" onclick="toggleJob('${{job.job_id}}'); return false;">${{isOpen ? 'hide' : 'view'}} prompts &amp; responses</a>`
            : '';
          let html = `<tr>
            <td>${{when}}</td>
            <td>${{job.benchmark}}</td>
            <td>${{job.backend}}</td>
            <td class="${{stateClass(job.state_label)}}">${{job.state_label}}</td>
            <td>${{renderStats(job)}}${{viewLink}}</td>
          </tr>`;
          if (isOpen) {{
            html += `<tr class="detail-row"><td colspan="5">${{renderJobDetail(job.job_id)}}</td></tr>`;
          }}
          return html;
        }}

        // A benchmark's transcript entries don't share one exact schema --
        // pick whichever of these fields is actually present rather than
        // assuming one fixed shape. "Present" means the key exists at
        // all, even if its value is an empty string -- an empty response
        // is a real (if uninteresting) result and should say so, not
        // silently vanish as if that field didn't exist.
        const PROMPT_KEYS = ['test_case_prompt', 'prompt', 'mutated_prompt', 'question'];
        const RESPONSE_KEYS = ['response', 'model_output', 'model_response'];
        const VERDICT_KEYS = ['judge_response', 'judgement', 'judgment', 'answered_correctly'];
        const SKIP_KEYS = new Set([...PROMPT_KEYS, ...RESPONSE_KEYS, ...VERDICT_KEYS,
          'model', 'prompt_id', 'pass_id', 'judge_question', 'user_input']);

        function firstPresentKey(entry, keys) {{
          for (const k of keys) {{ if (entry[k] !== undefined) return k; }}
          return null;
        }}

        function esc(s) {{
          const d = document.createElement('div');
          d.textContent = String(s);
          return d.innerHTML;
        }}

        function textOrEmpty(v) {{
          return esc(v) || '<span class="muted">(empty)</span>';
        }}

        function renderTranscriptEntry(entry, i) {{
          const promptKey = firstPresentKey(entry, PROMPT_KEYS);
          const responseKey = firstPresentKey(entry, RESPONSE_KEYS);
          const verdictKey = firstPresentKey(entry, VERDICT_KEYS);
          const metaParts = Object.keys(entry)
            .filter(k => !SKIP_KEYS.has(k) && entry[k] !== null && entry[k] !== undefined && entry[k] !== '')
            .map(k => `${{esc(k)}}: ${{esc(entry[k])}}`);
          let html = `<div class="transcript-entry"><b>Test case ${{i + 1}}</b>`;
          if (promptKey) html += `<div class="transcript-label">Prompt</div><p class="transcript-text">${{textOrEmpty(entry[promptKey])}}</p>`;
          if (entry.user_input !== undefined) html += `<div class="transcript-label">User input</div><p class="transcript-text">${{textOrEmpty(entry.user_input)}}</p>`;
          if (responseKey) html += `<div class="transcript-label">Response</div><p class="transcript-text">${{textOrEmpty(entry[responseKey])}}</p>`;
          if (verdictKey) html += `<div class="transcript-label">Judge verdict</div><span class="transcript-verdict">${{textOrEmpty(entry[verdictKey])}}</span>`;
          if (entry.judge_question) html += `<div class="transcript-meta">Judge question: ${{esc(entry.judge_question)}}</div>`;
          if (metaParts.length) html += `<div class="transcript-meta">${{metaParts.join(' &middot; ')}}</div>`;
          html += '</div>';
          return html;
        }}

        function renderJobDetail(jobId) {{
          const cached = transcriptCache[jobId];
          if (!cached) return '<div class="detail-box muted">Loading...</div>';
          if (cached.error) return `<div class="detail-box"><p class="muted">${{esc(cached.error)}}</p></div>`;
          if (!cached.transcript.length) return '<div class="detail-box"><p class="muted">No transcript available for this job.</p></div>';
          return `<div class="detail-box">${{cached.transcript.map(renderTranscriptEntry).join('')}}</div>`;
        }}

        function jobsTable(jobs) {{
          const rows = jobs.map(renderJobRow).join('');
          return `<table><thead><tr><th>When</th><th>Benchmark</th><th>Backend</th><th>State</th><th>Result</th></tr></thead><tbody>${{rows}}</tbody></table>`;
        }}

        function onSuiteToggle(suiteId, isOpen) {{
          if (isOpen) openSuites.add(suiteId); else openSuites.delete(suiteId);
        }}

        function renderSuiteCard(suite, isOpen) {{
          const when = suite.submitted_at ? new Date(suite.submitted_at).toLocaleString() : '';
          const stillRunning = suite.done < suite.total;
          const deleteBtn = stillRunning
            ? `<button type="button" class="delete-run-btn" disabled title="Wait for the run to finish before deleting">Delete</button>`
            : `<button type="button" class="delete-run-btn" onclick="deleteSuite(event, '${{suite.suite_id}}')">Delete</button>`;
          return `<details class="run-card" ${{isOpen ? 'open' : ''}} ontoggle="onSuiteToggle('${{suite.suite_id}}', this.open)">
            <summary><b>${{when}}</b> &middot; ${{suite.jobs.length}} benchmark(s) &middot;
              ${{suite.done}}/${{suite.total}} done${{suite.failed ? ', ' + suite.failed + ' failed' : ''}}
              <span class="muted">(run ${{suite.suite_id.slice(0, 8)}})</span>
              ${{deleteBtn}}</summary>
            ${{jobsTable(suite.jobs)}}
          </details>`;
        }}

        async function deleteSuite(event, suiteId) {{
          event.preventDefault();
          event.stopPropagation();
          if (!confirm('Delete this run and all its results? This cannot be undone.')) return;
          try {{
            const res = await fetch(`/suites/${{suiteId}}`, {{method: 'DELETE'}});
            const body = await res.json();
            if (body.error) {{ showToast('Error: ' + body.error); return; }}
            lastSuitesBody.suites = lastSuitesBody.suites.filter(s => s.suite_id !== suiteId);
            openSuites.delete(suiteId);
            renderTable();
            showToast('Run deleted.');
          }} catch (err) {{
            showToast(`Failed to delete (${{err.message}}).`);
          }}
        }}

        function renderTable() {{
          const suitesNewestFirst = lastSuitesBody.suites.slice().reverse();
          const html = suitesNewestFirst
            .map(suite => renderSuiteCard(suite, openSuites.has(suite.suite_id)))
            .join('');
          document.getElementById('status').innerHTML = html || '<p class="muted">No tests run yet.</p>';
        }}

        async function toggleJob(jobId) {{
          if (expandedJobs.has(jobId)) {{
            expandedJobs.delete(jobId);
            renderTable();
            return;
          }}
          expandedJobs.add(jobId);
          // A retryable failure (network hiccup, or an expired Authentik
          // session redirecting this background fetch to an HTML login
          // page instead of JSON) shouldn't get stuck cached forever --
          // closing and reopening should try again. A genuine "this job
          // has no transcript" result from the server is fine to cache
          // permanently, since refetching it would just say the same thing.
          if (transcriptCache[jobId] && transcriptCache[jobId].retryable) {{
            delete transcriptCache[jobId];
          }}
          renderTable();
          if (!transcriptCache[jobId]) {{
            try {{
              const res = await fetch(`/jobs/${{jobId}}`);
              if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
              const job = await res.json();
              const result = job.result || {{}};
              transcriptCache[jobId] = result.transcript_error
                ? {{error: result.transcript_error}}
                : {{transcript: result.transcript || []}};
            }} catch (err) {{
              transcriptCache[jobId] = {{
                error: `Failed to load (${{err.message}}). Your session may have expired -- try reloading the page, then click again.`,
                retryable: true,
              }};
            }}
            renderTable();
          }}
        }}

        async function refreshStatus() {{
          try {{
            const suitesRes = await fetch('/suites');
            if (!suitesRes.ok) throw new Error(`HTTP ${{suitesRes.status}}`);
            lastSuitesBody = await suitesRes.json();
            renderTable();
          }} catch (err) {{
            document.getElementById('status').innerHTML =
              `<p class="muted" style="color:#c62828">Couldn't load status (${{esc(err.message)}}). Your session may have expired -- try reloading the page.</p>`;
          }}
        }}

        refreshStatus();
        setInterval(refreshStatus, 4000);
      </script>
    </body></html>
    """
