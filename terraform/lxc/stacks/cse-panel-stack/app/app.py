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
import json
import os
import uuid
from datetime import datetime, timezone

from celery import Celery, group
from celery.result import AsyncResult, GroupResult
from fastapi import FastAPI, Header
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

# eval-runner's benchmark battery page (/eval), docs/eval-runner/panel-plan.md.
from eval_battery import router as eval_battery_router  # noqa: E402
app.include_router(eval_battery_router)


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


def _new_run_group_stamp() -> str:
    """One label shared by every job in a single submission (a whole
    suite, or a standalone job as a suite-of-one) -- becomes the
    top-level Nextcloud folder for that submission. Generated here, once,
    before dispatch, since jobs in a suite run sequentially (worker
    concurrency=1) and their own individual start times would otherwise
    drift apart by however long earlier benchmarks in the suite take,
    landing suite-mates in different folders instead of one shared one
    (operator request 2026-09-30: "top level folder for the run date and
    time, and that folder have subfolders for each benchmark type")."""
    now = datetime.now(timezone.utc)
    return f"{now.strftime('%Y-%m-%d_%H%M')}_{uuid.uuid4().hex[:8]}"


def _job_kwargs(spec: TestSpec, submitted_by: str, run_group_stamp: str) -> dict:
    return {
        "benchmark": spec.benchmark,
        "num_test_cases": spec.num_test_cases,
        "submitted_by": submitted_by,
        "backend_base_url": spec.backend_base_url,
        "backend_model": spec.backend_model,
        "backend_api_key": spec.backend_api_key,
        "random_sample": spec.random_sample,
        "run_group_stamp": run_group_stamp,
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
    result = celery_app.send_task(TASK_NAME, kwargs=_job_kwargs(spec, submitted_by, _new_run_group_stamp()))
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


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, force: bool = False):
    """Standalone jobs (submitted via POST /jobs, not part of a suite) --
    same force/cancel semantics as DELETE /suites/{id}, kept as a separate
    endpoint since a standalone job has no GroupResult to restore. This is
    also how the panel's own real jobs get cancelled/cleaned up: it's not
    just a raw-API convenience, the discontinued "Individual jobs" section
    at least had no delete control even when it existed, so a genuinely
    stuck standalone job had no way to be cleared at all until this."""
    res = AsyncResult(job_id, app=celery_app)
    if res.state in NON_TERMINAL_STATES and not force:
        return {
            "error": f"job is {res.state.lower()} -- retry with force=true to cancel and delete anyway",
            "in_progress": True,
        }
    cancelled = res.state in NON_TERMINAL_STATES
    if cancelled:
        res.revoke(terminate=True, signal="SIGTERM")

    client = celery_app.backend.client
    res.forget()
    client.delete(f"cse_panel:job_meta:{job_id}")
    client.lrem(RECENT_JOBS_KEY, 0, job_id)

    celery_app.send_task(DELETE_TASK_NAME, kwargs={"job_ids": [job_id]})
    return {"deleted": job_id, "cancelled": [job_id] if cancelled else []}


@app.post("/suites")
def submit_suite(body: SuiteRequest, x_authentik_username: str | None = Header(default=None)):
    unknown = [t.benchmark for t in body.tests if t.benchmark not in KNOWN_BENCHMARKS]
    if unknown:
        return {"error": f"unknown benchmark(s) {unknown}, must be one of {KNOWN_BENCHMARKS}"}
    if not body.tests:
        return {"error": "tests list is empty"}
    submitted_by = x_authentik_username or "unknown"
    run_group_stamp = _new_run_group_stamp()
    job_group = group(
        celery_app.signature(TASK_NAME, kwargs=_job_kwargs(t, submitted_by, run_group_stamp))
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
def delete_suite(suite_id: str, force: bool = False):
    result = GroupResult.restore(suite_id, app=celery_app)
    if result is None:
        return {"error": f"suite '{suite_id}' not found"}
    job_ids = [r.id for r in result.results]
    in_progress = [r for r in result.results if r.state in NON_TERMINAL_STATES]
    if in_progress and not force:
        return {
            "error": f"{len(in_progress)} job(s) still running/queued -- retry with force=true to cancel and delete anyway",
            "in_progress": True,
        }
    # terminate=True actually kills the worker process executing this task
    # (not just marking it revoked for a still-queued copy) -- needed for a
    # genuinely stuck job, e.g. one hung against a dead backend with no
    # effective timeout. Celery's prefork pool respawns the killed worker
    # process automatically, so this doesn't take the worker down.
    for r in in_progress:
        r.revoke(terminate=True, signal="SIGTERM")

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
    return {"deleted": suite_id, "jobs": job_ids, "cancelled": [r.id for r in in_progress]}
