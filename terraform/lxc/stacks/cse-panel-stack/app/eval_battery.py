"""cse-panel's "Eval battery" JSON API: start, watch and control
eval-runner benchmark runs (GPQA, IFEval, BFCL, AgentBench, RepoBench) on
ai-services-stack, for the Dash panel's Eval battery tab
(app-ui/eval_tab.py). docs/eval-runner/panel-plan.md. Its old HTML page
was retired on 2026-10-08; /eval now redirects to the Dash panel.

Like the CyberSecEval pages, this only enqueues Celery tasks and reads
state from Redis. The work happens in eval-runner's worker on
ai-services-stack (terraform/lxc/ansible/files/eval-runner/eval_tasks.py),
which connects out to this stack's Redis:

  queue eval-runner      eval_tasks.run / eval_tasks.resume (one at a time)
  queue eval-runner-ctl  eval_tasks.cancel / publish / delete_run
  key eval:framework     Framework status, written by the worker every 30 s
  key eval:job:<id>      per-job state, log tail and results

The page can't reach Framework or ai-services-stack itself, and doesn't
need to.
"""

import json
import os
from datetime import datetime, timezone

from celery import Celery
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

celery_app = Celery("eval_panel", broker=os.environ.get("CELERY_BROKER_URL", "memory://"),
                    backend=os.environ.get("CELERY_RESULT_BACKEND", "cache+memory://"))
router = APIRouter(prefix="/eval")

RUN_QUEUE = "eval-runner"
CTL_QUEUE = "eval-runner-ctl"
RECENT_KEY = "eval:recent-jobs"
RECENT_MAX = 50
JOB_TTL = 30 * 24 * 3600
TASKS = {
    "gpqa": "GPQA diamond: 198 graduate-level science questions, chain of thought",
    "ifeval": "IFEval: 541 prompts with verifiable formatting instructions",
    "bfcl": "BFCL simple: 400 single function-call cases",
    "agentbench": "AgentBench os-std: 100 sandboxed shell episodes (seed 42)",
    "repobench": "RepoBench (rebuilt): next-line code completion, 1500 samples",
}
BUDGET_TASKS = ("gpqa", "ifeval")
NEXTCLOUD = "https://nextcloud.lab.gibbsgreatly.xyz"
# The eval-reports account's Reports/eval-runner folder, as it appears to
# the operator it's shared with: received shares land in the receiver's
# root under the folder's own name (this Nextcloud sets no share_folder).
SHARED_REPORTS_DIR = "/eval-runner"
LINKS = {
    "Results table (Nextcloud Tables)": f"{NEXTCLOUD}/apps/tables",
    "Reports folder": f"{NEXTCLOUD}/apps/files/?dir={SHARED_REPORTS_DIR}",
}
SAMPLES_TIMEOUT = 30
LIVE_STATES = ("queued", "waiting", "starting", "running", "publishing")


def _redis():
    return celery_app.backend.client


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(key):
    raw = _redis().get(key)
    return json.loads(raw) if raw else None


def _job(job_id):
    return _get(f"eval:job:{job_id}") or {}


def _put_job(job_id, **fields):
    job = _job(job_id)
    job.update(fields, id=job_id, updated=_now())
    _redis().set(f"eval:job:{job_id}", json.dumps(job), ex=JOB_TTL)
    return job


def _remember(job_id):
    client = _redis()
    client.lpush(RECENT_KEY, job_id)
    client.ltrim(RECENT_KEY, 0, RECENT_MAX - 1)


class RunRequest(BaseModel):
    tasks: list[str] = Field(min_length=1)
    mode: str = "full"  # full | pilot | limit
    limit: int | None = None
    note: str = ""
    budget_32k: bool = False


def validate(req: RunRequest):
    unknown = [t for t in req.tasks if t not in TASKS]
    if unknown:
        raise HTTPException(400, f"unknown benchmark(s): {', '.join(unknown)}")
    if req.mode not in ("full", "pilot", "limit"):
        raise HTTPException(400, "mode must be full, pilot or limit")
    if req.mode == "limit" and not (isinstance(req.limit, int) and 1 <= req.limit <= 10000):
        raise HTTPException(400, "limit must be 1-10000")
    if len(req.note) > 200 or "\n" in req.note:
        raise HTTPException(400, "note must be one line, at most 200 characters")
    if req.budget_32k and any(t not in BUDGET_TASKS for t in req.tasks):
        raise HTTPException(400, "the 32k budget applies to GPQA and IFEval only")


@router.get("/api/state")
def state():
    ids = [i.decode() if isinstance(i, bytes) else i for i in _redis().lrange(RECENT_KEY, 0, -1)]
    return {"framework": _get("eval:framework"), "jobs": [_job(i) | {"id": i} for i in ids], "links": LINKS}


@router.post("/api/jobs")
def submit(req: RunRequest, x_authentik_username: str | None = Header(default=None)):
    validate(req)
    who = x_authentik_username or "unknown"
    submitted = []
    for task in req.tasks:  # one job per benchmark; the worker runs them in this order
        kwargs = {"task": task, "mode": req.mode, "limit": req.limit if req.mode == "limit" else None,
                  "note": req.note, "budget_32k": req.budget_32k, "submitted_by": who}
        result = celery_app.send_task("eval_tasks.run", kwargs=kwargs, queue=RUN_QUEUE)
        _put_job(result.id, state="queued", submitted=_now(), **kwargs)
        _remember(result.id)
        submitted.append(result.id)
    return {"submitted": submitted}


@router.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    job = _job(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    if job.get("state") in ("done", "failed", "cancelled"):
        raise HTTPException(409, f"job already {job['state']}")
    if job.get("state") == "queued":  # not picked up yet: drop it from the queue
        celery_app.control.revoke(job_id)
        _put_job(job_id, state="cancelled", cancel_requested=True)
    else:  # waiting or running: the worker stops it
        _put_job(job_id, cancel_requested=True)
        celery_app.send_task("eval_tasks.cancel", args=[job_id], queue=CTL_QUEUE)
    return _job(job_id)


@router.post("/api/jobs/{job_id}/resume")
def resume(job_id: str, x_authentik_username: str | None = Header(default=None)):
    job = _job(job_id)
    if not job.get("run") or job.get("state") not in ("failed", "cancelled"):
        raise HTTPException(409, "only a failed or cancelled job with a run can be resumed")
    kwargs = {"run_name": job["run"], "submitted_by": x_authentik_username or "unknown"}
    result = celery_app.send_task("eval_tasks.resume", kwargs=kwargs, queue=RUN_QUEUE)
    _put_job(result.id, state="queued", submitted=_now(), task="resume", run=job["run"],
             note=f"resume of {job.get('task', '')} {job['run']}", submitted_by=kwargs["submitted_by"])
    _remember(result.id)
    return {"submitted": [result.id]}


@router.delete("/api/jobs/{job_id}")
def delete(job_id: str):
    """Delete a run for good: every panel entry for its run (the original
    job and any resumes of it), and, through the worker (eval_tasks.delete_run),
    its results, its Nextcloud folder and its table rows. A job that never
    got a run (e.g. cancelled while queued) only leaves the list."""
    client = _redis()
    ids = [i.decode() if isinstance(i, bytes) else i for i in client.lrange(RECENT_KEY, 0, -1)]
    job = _job(job_id)
    if not job and job_id not in ids:
        raise HTTPException(404, "no such job")
    run = job.get("run")
    related = [i for i in ids if i == job_id or (run and _job(i).get("run") == run)]
    live = [i for i in related if _job(i).get("state") in LIVE_STATES]
    if live:
        raise HTTPException(409, "this run is still going; cancel it first")
    if run:
        celery_app.send_task("eval_tasks.delete_run", args=[run], queue=CTL_QUEUE)
    for i in related:
        client.delete(f"eval:job:{i}")
        client.lrem(RECENT_KEY, 0, i)
    return {"deleted": related, "run": run}


@router.get("/api/jobs/{job_id}/samples")
def samples(job_id: str, offset: int = 0, limit: int = 10):
    """One page of the run's prompts and responses, read on demand by the
    eval worker (eval_tasks.samples) from the run's own files."""
    job = _job(job_id)
    if not job.get("run"):
        raise HTTPException(409, "this job has no run yet")
    result = celery_app.send_task("eval_tasks.samples", args=[job["run"], max(0, offset), max(1, min(25, limit))],
                                  queue=CTL_QUEUE)
    try:
        return result.get(timeout=SAMPLES_TIMEOUT)
    except Exception as err:  # worker down or slow: say so rather than hang the page
        raise HTTPException(504, f"the eval worker didn't answer: {type(err).__name__}")


@router.post("/api/publish")
def publish():
    result = celery_app.send_task("eval_tasks.publish", queue=CTL_QUEUE)
    return {"submitted": result.id}


@router.get("")
@router.get("/")
def page():
    """The old HTML page, retired 2026-10-08: the Eval battery is a tab in
    the Dash panel now (app-ui/eval_tab.py). Old bookmarks land there; the
    JSON API above stays, because that tab uses it."""
    domain = os.environ.get("LAB_DOMAIN", "")
    return RedirectResponse(f"https://cse-panel.{domain}/" if domain else "/", status_code=307)
