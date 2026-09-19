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
from datetime import datetime, timezone

from celery import Celery, group
from celery.result import AsyncResult, GroupResult
from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

celery_app = Celery("cse_panel", broker=BROKER_URL, backend=RESULT_BACKEND)

# Must match the task name registered by cse_tasks.py's worker exactly --
# Celery routes by string name, not by import, since the worker and this
# submitter are different processes on different hosts.
TASK_NAME = "cse_tasks.run_benchmark"

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


@app.get("/", response_class=HTMLResponse)
def index():
    benchmark_checkboxes = "".join(
        f'<label class="chip"><input type="checkbox" name="benchmark" value="{b}">{b}</label>'
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
      .chip {{ display: inline-block; margin: 0.15rem 0.6rem 0.15rem 0; }}
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
      .toast {{ margin: 0.5rem 0; padding: 0.5rem 0.8rem; border-radius: 4px; background: #eef; display: none; }}
      details.advanced {{ margin-top: 2.5rem; color: #666; font-size: 0.85rem; }}
      #custom-backend-fields {{ display: none; }}
    </style>
    </head>
    <body>
      <h1>CyberSecEval Control Panel</h1>

      <h2>Run tests</h2>
      <form id="run-form">
        <div>{benchmark_checkboxes}</div>
        <label class="field">Test cases per benchmark:
          <input name="num_test_cases" type="number" value="2" min="1" max="50">
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
      <div class="toast" id="toast"></div>

      <h2>Status</h2>
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

      <script>
        const KNOWN_BACKENDS = {json.dumps([[name, b["base_url"], b["model"]] for name, b in KNOWN_BACKENDS.items()])};

        document.getElementById('backend-select').addEventListener('change', (e) => {{
          document.getElementById('custom-backend-fields').style.display =
            e.target.value === 'custom' ? 'block' : 'none';
        }});

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
            benchmark: b, num_test_cases: numTestCases,
            backend_base_url: baseUrl, backend_model: model, backend_api_key: apiKey,
          }}));
          const res = await fetch('/suites', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{tests}}),
          }});
          const body = await res.json();
          if (body.error) {{ showToast('Error: ' + body.error); }}
          else {{ showToast(`Submitted ${{tests.length}} test(s).`); refreshStatus(); }}
        }});

        function stateClass(label) {{ return 'state-' + label.replace(/[^A-Za-z]/g, ''); }}

        function renderStats(job) {{
          if (job.state_label === 'Failed') {{
            return `<span style="color:#c62828">${{(job.error || '').slice(0, 160)}}</span>`;
          }}
          if (job.stats_error) {{
            return `<span class="muted">${{job.stats_error}}</span>`;
          }}
          if (job.stats_summary && job.stats_summary.length) {{
            return '<ul class="stats-list">' +
              job.stats_summary.map(([k, v]) => `<li><b>${{k}}</b>: ${{v}}</li>`).join('') +
              '</ul>';
          }}
          return '<span class="muted">-</span>';
        }}

        function renderJobRow(job) {{
          const when = job.submitted_at ? new Date(job.submitted_at).toLocaleString() : '';
          return `<tr>
            <td>${{when}}</td>
            <td>${{job.benchmark}}</td>
            <td>${{job.backend}}</td>
            <td class="${{stateClass(job.state_label)}}">${{job.state_label}}</td>
            <td>${{renderStats(job)}}</td>
          </tr>`;
        }}

        async function refreshStatus() {{
          const [jobsRes, suitesRes] = await Promise.all([fetch('/jobs'), fetch('/suites')]);
          const jobsBody = await jobsRes.json();
          const suitesBody = await suitesRes.json();
          const shown = new Set();
          let rows = '';
          for (const suite of suitesBody.suites) {{
            for (const job of suite.jobs) {{ shown.add(job.job_id); }}
          }}
          for (const suite of suitesBody.suites.slice().reverse()) {{
            const when = suite.submitted_at ? new Date(suite.submitted_at).toLocaleString() : '';
            rows += `<tr style="background:#f7f7fb"><td colspan="5"><b>Suite ${{suite.suite_id.slice(0, 8)}}</b>
              <span class="muted">${{when}} &middot; ${{suite.done}}/${{suite.total}} done${{suite.failed ? ', ' + suite.failed + ' failed' : ''}}</span></td></tr>`;
            for (const job of suite.jobs) {{ rows += renderJobRow(job); }}
          }}
          for (const job of jobsBody.jobs.slice().reverse()) {{
            if (!shown.has(job.job_id)) {{ rows += renderJobRow(job); }}
          }}
          document.getElementById('status').innerHTML = rows
            ? `<table><thead><tr><th>When</th><th>Benchmark</th><th>Backend</th><th>State</th><th>Result</th></tr></thead><tbody>${{rows}}</tbody></table>`
            : '<p class="muted">No tests run yet.</p>';
        }}

        refreshStatus();
        setInterval(refreshStatus, 4000);
      </script>
    </body></html>
    """
