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
task (visible in Flower on its own), not a single opaque long-running
job, since the worker's own concurrency is 1 anyway (one inference
backend can only do one thing at a time).
"""
import os
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

RECENT_JOBS_KEY = "cse_panel:recent_job_ids"
RECENT_SUITES_KEY = "cse_panel:recent_suite_ids"
RECENT_MAX = 50

app = FastAPI(title="CyberSecEval Control Panel")


class TestSpec(BaseModel):
    benchmark: str
    num_test_cases: int = 2
    backend_base_url: str | None = None
    backend_model: str | None = None
    backend_api_key: str | None = None


class SuiteRequest(BaseModel):
    tests: list[TestSpec]


def _job_kwargs(spec: TestSpec, submitted_by: str) -> dict:
    return {
        "benchmark": spec.benchmark,
        "num_test_cases": spec.num_test_cases,
        "submitted_by": submitted_by,
        "backend_base_url": spec.backend_base_url,
        "backend_model": spec.backend_model,
        "backend_api_key": spec.backend_api_key,
    }


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
    spec = TestSpec(
        benchmark=benchmark,
        num_test_cases=num_test_cases,
        backend_base_url=backend_base_url,
        backend_model=backend_model,
        backend_api_key=backend_api_key,
    )
    result = celery_app.send_task(
        TASK_NAME, kwargs=_job_kwargs(spec, x_authentik_username or "unknown")
    )
    celery_app.backend.client.lpush(RECENT_JOBS_KEY, result.id)
    celery_app.backend.client.ltrim(RECENT_JOBS_KEY, 0, RECENT_MAX - 1)
    return {"job_id": result.id, "benchmark": benchmark}


@app.get("/jobs")
def list_recent_jobs():
    ids = celery_app.backend.client.lrange(RECENT_JOBS_KEY, 0, -1)
    jobs = []
    for raw_id in ids:
        job_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        res = AsyncResult(job_id, app=celery_app)
        jobs.append({"job_id": job_id, "state": res.state})
    return {"jobs": jobs}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    res = AsyncResult(job_id, app=celery_app)
    body = {"job_id": job_id, "state": res.state}
    if res.state == "SUCCESS":
        body["result"] = res.result
    elif res.state == "FAILURE":
        body["error"] = str(res.result)
    return body


@app.post("/suites")
def submit_suite(
    body: SuiteRequest,
    x_authentik_username: str | None = Header(default=None),
):
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
    return {
        "suite_id": result.id,
        "jobs": [
            {"job_id": r.id, "benchmark": t.benchmark}
            for r, t in zip(result.results, body.tests)
        ],
    }


@app.get("/suites")
def list_recent_suites():
    ids = celery_app.backend.client.lrange(RECENT_SUITES_KEY, 0, -1)
    suites = []
    for raw_id in ids:
        suite_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        suites.append({"suite_id": suite_id})
    return {"suites": suites}


@app.get("/suites/{suite_id}")
def suite_status(suite_id: str):
    result = GroupResult.restore(suite_id, app=celery_app)
    if result is None:
        return {"error": f"suite '{suite_id}' not found"}
    jobs = [{"job_id": r.id, "state": r.state} for r in result.results]
    all_ready = all(r.ready() for r in result.results)
    return {
        "suite_id": suite_id,
        "jobs": jobs,
        "all_ready": all_ready,
        "all_successful": all(r.successful() for r in result.results) if all_ready else None,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    options = "".join(f'<option value="{b}">{b}</option>' for b in KNOWN_BENCHMARKS)
    lab_domain = os.environ.get("LAB_DOMAIN", "")
    flower_url = f"https://cse-panel-flower.{lab_domain}" if lab_domain else "#"
    return f"""
    <html><head><title>CyberSecEval Control Panel</title></head>
    <body>
      <h1>CyberSecEval Control Panel</h1>

      <h2>Single test</h2>
      <form id="submit-form">
        <label>Benchmark: <select name="benchmark">{options}</select></label>
        <label>Num test cases: <input name="num_test_cases" type="number" value="2" min="1" max="10"></label>
        <br>
        <label>Backend base URL (optional -- default: Framework llama-server):
          <input name="backend_base_url" type="text" placeholder="http://host:port/v1" size="40"></label>
        <label>Backend model (optional): <input name="backend_model" type="text" size="30"></label>
        <br>
        <button type="submit">Run</button>
      </form>

      <h2>Test suite (run several together)</h2>
      <p>Paste a JSON array of tests, e.g.
      <code>[{{"benchmark": "mitre-frr", "num_test_cases": 1}}, {{"benchmark": "instruct", "num_test_cases": 2}}]</code></p>
      <form id="suite-form">
        <textarea name="tests_json" rows="4" cols="60">[{{"benchmark": "mitre-frr", "num_test_cases": 1}}]</textarea>
        <br>
        <button type="submit">Run suite</button>
      </form>

      <p><a href="/jobs">Recent jobs (JSON)</a> &middot;
         <a href="/suites">Recent suites (JSON)</a> &middot;
         <a href="/backends">Known backends (JSON)</a> &middot;
         <a href="/docs">API docs</a> &middot;
         <a href="{flower_url}">Flower (live task detail)</a></p>
      <script>
        document.getElementById('submit-form').addEventListener('submit', async (e) => {{
          e.preventDefault();
          const form = new FormData(e.target);
          const params = new URLSearchParams();
          for (const [k, v] of form.entries()) {{ if (v) params.append(k, v); }}
          const res = await fetch('/jobs?' + params.toString(), {{method: 'POST'}});
          const body = await res.json();
          alert(JSON.stringify(body));
        }});
        document.getElementById('suite-form').addEventListener('submit', async (e) => {{
          e.preventDefault();
          const form = new FormData(e.target);
          let tests;
          try {{ tests = JSON.parse(form.get('tests_json')); }}
          catch (err) {{ alert('Invalid JSON: ' + err); return; }}
          const res = await fetch('/suites', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{tests}}),
          }});
          const body = await res.json();
          alert(JSON.stringify(body));
        }});
      </script>
    </body></html>
    """
