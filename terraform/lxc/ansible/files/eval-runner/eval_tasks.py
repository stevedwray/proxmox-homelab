"""Celery worker for eval-runner's control panel page (cse-panel's "Eval
battery" page; docs/eval-runner/panel-plan.md).

Runs on ai-services-stack as two systemd units from this one module, both
connecting OUT to cse-panel's Redis (the panel never reaches ai_seg):

  eval-runner-worker-runs  queue eval-runner, concurrency 1: run, resume.
                           One benchmark run at a time, in submission order.
  eval-runner-worker-ctl   queue eval-runner-ctl: cancel, publish, and a
                           background loop that writes Framework's status.
                           Separate so a click isn't stuck behind a run
                           that takes hours.

Everything goes through /usr/local/bin/eval-run, so the panel and the
command line behave identically (eval-run's one-run-at-a-time guard
included). State the page shows is kept in Redis (the Celery result
backend's client):

  eval:framework      {model, slots, busy, checked, error}, every 30 s
  eval:job:<task id>  {state, task, run, log_tail, ...}, kept 30 days

Job states: queued, waiting (for Framework or another run), running,
publishing, done, failed, cancelled.
"""

import datetime
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

from celery import Celery
from celery.signals import worker_ready

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "memory://")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "cache+memory://")
app = Celery("eval_tasks", broker=BROKER_URL, backend=RESULT_BACKEND)
# A worker killed mid-run gets the task redelivered (acks_late); the
# visibility timeout must outlast the longest run (a full RepoBench on a
# slow model is about a day), or Redis redelivers a run that is still going
# (reference_celery_redis_visibility_timeout_redelivery).
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1
app.conf.broker_transport_options = {"visibility_timeout": 48 * 3600}

RUN_QUEUE = "eval-runner"
CTL_QUEUE = "eval-runner-ctl"
EVAL_RUN = os.environ.get("EVAL_RUN", "/usr/local/bin/eval-run")
TASKS = ("gpqa", "ifeval", "bfcl", "agentbench", "repobench")
BUDGET_TASKS = ("gpqa", "ifeval")
JOB_TTL = 30 * 24 * 3600
FRAMEWORK_KEY = "eval:framework"
STATUS_EVERY = 30
FOLLOW_EVERY = 10
FRAMEWORK_POLL = 60
FRAMEWORK_MAX_WAIT = 12 * 3600
LOG_TAIL = 20


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redis():
    return app.backend.client


def job_key(job_id):
    return f"eval:job:{job_id}"


def get_job(job_id, client=None):
    raw = (client or _redis()).get(job_key(job_id))
    return json.loads(raw) if raw else {}


def update_job(job_id, client=None, **fields):
    client = client or _redis()
    job = get_job(job_id, client)
    job.update(fields, updated=_now())
    client.set(job_key(job_id), json.dumps(job), ex=JOB_TTL)
    return job


def cancel_requested(job_id, client=None):
    return bool(get_job(job_id, client).get("cancel_requested"))


# ---------------------------------------------------------------- commands

def eval_run_args(task, mode, limit=None, note="", budget_32k=False):
    """argv for `eval-run` from the panel's form fields (validated again here:
    the worker, not the page, is the trust boundary for what it executes)."""
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}")
    argv = [EVAL_RUN, task]
    if mode == "pilot":
        argv.append("--pilot")
    elif mode == "limit":
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("limit must be an integer 1-10000")
        argv += ["--limit", str(limit)]
    elif mode != "full":
        raise ValueError(f"unknown mode {mode!r}")
    if budget_32k:
        if task not in BUDGET_TASKS:
            raise ValueError("the 32k budget applies to gpqa/ifeval only")
        argv += ["--max-gen-toks", "32768"]
    if note:
        if len(note) > 200 or "\n" in note:
            raise ValueError("note must be one line, at most 200 characters")
        argv += ["--note", note]
    return argv


def run_cmd(argv, timeout=600):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def started_run(output):
    """The run name from eval-run's "Started eval-<run>" line."""
    match = re.search(r"^Started eval-(\S+)$", output, re.M)
    return match.group(1) if match else None


def container_state(run):
    """(status, exit code) of the run's container, or (None, None) if absent."""
    out = run_cmd(["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", f"eval-{run}"], 30)
    if out.returncode != 0:
        return None, None
    status, code = out.stdout.split()
    return status, int(code)


def log_tail(run, lines=LOG_TAIL):
    out = run_cmd(["docker", "logs", "--tail", str(lines), f"eval-{run}"], 30)
    text = (out.stdout or "") + (out.stderr or "")
    # tqdm redraws with bare carriage returns; keep each line's last state
    # (str.splitlines would also split on \r, so split on \n only)
    return "\n".join(line.split("\r")[-1] for line in text.rstrip("\n").split("\n")[-lines:])


def eval_container_running():
    out = run_cmd(["docker", "ps", "--filter", "name=^eval-", "--format", "{{.Names}}"], 30)
    return out.stdout.strip() or None


# --------------------------------------------------------------- Framework

def framework_status(get_json=None):
    """What Framework's llama-server is serving and whether it is busy."""
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if get_json is None:
        def get_json(path):
            req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)
    status = {"checked": _now(), "model": None, "slots": None, "busy": None, "error": None}
    try:
        models = get_json("/v1/models")
        status["model"] = (models.get("data") or [{}])[0].get("id")
        slots = get_json("/slots")
        status["slots"] = len(slots)
        status["busy"] = sum(1 for s in slots if s.get("is_processing"))
    except Exception as err:  # unreachable, no model, /slots disabled
        status["error"] = f"{type(err).__name__}: {err}"
    return status


def wait_until(job_id, client, ready, waiting_for, poll, max_wait, sleep=None):
    """Poll ready() until true; the job shows `waiting_for` meanwhile.
    Returns False if cancelled or timed out."""
    sleep = sleep or time.sleep  # resolved at call time, so tests can patch it
    waited = 0
    while not ready():
        if cancel_requested(job_id, client):
            return False
        if waited >= max_wait:
            update_job(job_id, client, state="failed", error=f"gave up waiting for {waiting_for}")
            return False
        update_job(job_id, client, state="waiting", waiting_for=waiting_for)
        sleep(poll)
        waited += poll
    return True


def framework_idle():
    status = framework_status()
    return status["error"] is None and status["busy"] == 0


# ------------------------------------------------------------------- tasks

def follow(job_id, run, client, sleep=None):
    """Track the run's container until it exits; returns its exit code (or
    None if it vanished). Stops it if the panel asked to cancel."""
    sleep = sleep or time.sleep
    while True:
        status, code = container_state(run)
        tail = log_tail(run) if status else ""
        update_job(job_id, client, state="running", run=run, log_tail=tail)
        if status is None:
            return None
        if status == "exited":
            return code
        if cancel_requested(job_id, client):
            run_cmd(["docker", "stop", f"eval-{run}"], 120)
        sleep(FOLLOW_EVERY)


def finish(job_id, run, code, client):
    """Publish, record the result summary, remove the container."""
    cancelled = cancel_requested(job_id, client)
    update_job(job_id, client, state="publishing")
    publish = run_cmd([EVAL_RUN, "publish"], 900)
    results = run_cmd([EVAL_RUN, "results", run], 120) if run else None
    run_cmd(["docker", "rm", f"eval-{run}"], 60)
    state = "cancelled" if cancelled else ("done" if code == 0 else "failed")
    return update_job(job_id, client, state=state, exit_code=code, finished=_now(),
                      results=(results.stdout.strip() if results else ""),
                      published=(publish.stdout.strip().splitlines() or [""])[-1],
                      publish_error=publish.stderr.strip() if publish.returncode else "")


def _launch(job_id, argv, client):
    """Wait for a free slot (no other eval run, Framework idle), then start."""
    if not wait_until(job_id, client, lambda: eval_container_running() is None, "another eval run",
                      FRAMEWORK_POLL, FRAMEWORK_MAX_WAIT):
        return None
    if not wait_until(job_id, client, framework_idle, "Framework (busy slots)", FRAMEWORK_POLL, FRAMEWORK_MAX_WAIT):
        return None
    out = run_cmd(argv)
    run = started_run(out.stdout)
    if run is None:
        update_job(job_id, client, state="failed", error=(out.stderr or out.stdout).strip()[-2000:])
    return run


def _run_job(job_id, argv, client):
    if cancel_requested(job_id, client):
        return update_job(job_id, client, state="cancelled")
    # Redelivered after a worker restart (acks_late) while its run container
    # carried on: re-attach to that run instead of starting a second one.
    previous = get_job(job_id, client)
    if previous.get("run") and previous.get("state") in ("running", "publishing"):
        status, code = container_state(previous["run"])
        if status is not None:
            code = follow(job_id, previous["run"], client) if status != "exited" else code
            return finish(job_id, previous["run"], code, client)
    update_job(job_id, client, state="starting", started=_now())
    run = _launch(job_id, argv, client)
    if run is None:
        job = get_job(job_id, client)
        if job.get("state") not in ("failed",):
            job = update_job(job_id, client, state="cancelled")
        return job
    code = follow(job_id, run, client)
    return finish(job_id, run, code, client)


@app.task(bind=True, name="eval_tasks.run")
def run(self, task, mode="full", limit=None, note="", budget_32k=False, submitted_by=""):
    client = _redis()
    try:
        argv = eval_run_args(task, mode, limit, note, budget_32k)
    except ValueError as err:
        return update_job(self.request.id, client, state="failed", error=str(err))
    update_job(self.request.id, client, task=task, mode=mode, limit=limit, note=note,
               budget_32k=budget_32k, submitted_by=submitted_by)
    return _run_job(self.request.id, argv, client)


@app.task(bind=True, name="eval_tasks.resume")
def resume(self, run_name, force=False, submitted_by=""):
    client = _redis()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_name or ""):
        return update_job(self.request.id, client, state="failed", error="bad run name")
    update_job(self.request.id, client, task="resume", run=run_name, submitted_by=submitted_by)
    argv = [EVAL_RUN, "resume", run_name] + (["--force"] if force else [])
    return _run_job(self.request.id, argv, client)


@app.task(name="eval_tasks.cancel")
def cancel(job_id):
    """Ask a waiting or running job to stop (the run task notices within
    FOLLOW_EVERY / FRAMEWORK_POLL seconds); stop its container right away."""
    client = _redis()
    job = update_job(job_id, client, cancel_requested=True)
    if job.get("run") and job.get("state") == "running":
        run_cmd(["docker", "stop", f"eval-{job['run']}"], 120)
    return job


@app.task(name="eval_tasks.publish")
def publish():
    out = run_cmd([EVAL_RUN, "publish"], 900)
    return {"ok": out.returncode == 0, "output": (out.stdout + out.stderr).strip()[-2000:], "at": _now()}


def status_loop(client=None, sleep=None, rounds=None):
    """Write Framework's status for the page every STATUS_EVERY seconds."""
    client = client or _redis()
    sleep = sleep or time.sleep
    n = 0
    while rounds is None or n < rounds:
        status = framework_status()
        status["eval_running"] = eval_container_running()
        client.set(FRAMEWORK_KEY, json.dumps(status), ex=STATUS_EVERY * 10)
        n += 1
        sleep(STATUS_EVERY)


@worker_ready.connect
def _start_status_loop(sender=None, **_):
    if str(getattr(sender, "hostname", "")).startswith("ctl@"):
        threading.Thread(target=status_loop, daemon=True, name="framework-status").start()
