"""cse-panel-stack's panel-web: submits CyberSecEval benchmark runs as
Celery tasks and reports their status. The actual benchmark execution
happens in the Celery worker on cse-controller (see
terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py) --
this app never runs benchmark code itself.
"""
import os
from celery import Celery
from celery.result import AsyncResult
from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse

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

RECENT_JOBS_KEY = "cse_panel:recent_job_ids"
RECENT_JOBS_MAX = 50

app = FastAPI(title="CyberSecEval Control Panel")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/benchmarks")
def list_benchmarks():
    return {"benchmarks": KNOWN_BENCHMARKS}


@app.post("/jobs")
def submit_job(
    benchmark: str,
    num_test_cases: int = 2,
    x_authentik_username: str | None = Header(default=None),
):
    if benchmark not in KNOWN_BENCHMARKS:
        return {"error": f"unknown benchmark '{benchmark}', must be one of {KNOWN_BENCHMARKS}"}
    result = celery_app.send_task(
        TASK_NAME,
        kwargs={
            "benchmark": benchmark,
            "num_test_cases": num_test_cases,
            "submitted_by": x_authentik_username or "unknown",
        },
    )
    celery_app.backend.client.lpush(RECENT_JOBS_KEY, result.id)
    celery_app.backend.client.ltrim(RECENT_JOBS_KEY, 0, RECENT_JOBS_MAX - 1)
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


@app.get("/", response_class=HTMLResponse)
def index():
    options = "".join(f'<option value="{b}">{b}</option>' for b in KNOWN_BENCHMARKS)
    lab_domain = os.environ.get("LAB_DOMAIN", "")
    flower_url = f"https://cse-panel-flower.{lab_domain}" if lab_domain else "#"
    return f"""
    <html><head><title>CyberSecEval Control Panel</title></head>
    <body>
      <h1>CyberSecEval Control Panel</h1>
      <form id="submit-form">
        <label>Benchmark: <select name="benchmark">{options}</select></label>
        <label>Num test cases: <input name="num_test_cases" type="number" value="2" min="1" max="10"></label>
        <button type="submit">Run</button>
      </form>
      <p><a href="/jobs">Recent jobs (JSON)</a> &middot;
         <a href="/docs">API docs</a> &middot;
         <a href="{flower_url}">Flower (live task detail)</a></p>
      <script>
        document.getElementById('submit-form').addEventListener('submit', async (e) => {{
          e.preventDefault();
          const form = new FormData(e.target);
          const params = new URLSearchParams(form);
          const res = await fetch('/jobs?' + params.toString(), {{method: 'POST'}});
          const body = await res.json();
          alert(JSON.stringify(body));
        }});
      </script>
    </body></html>
    """
