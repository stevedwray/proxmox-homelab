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

Framework is shared with CyberSecEval's worker through framework_lock.py
(docs/benchmark-panel/plan.md, C): a run takes the lock before it starts
and gives it back when its container exits. While it holds the lock, the
run's tokens and tokens/s come from llama-server's /metrics counters
(read before and after), in the same run_metrics shape CyberSecEval uses.
They are written to the job record and to the run's run.json, which
publish.py reads.
"""

import datetime
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

from celery import Celery

import framework_lock
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
RESULTS_DIR = os.environ.get("EVAL_RESULTS_DIR", "/srv/eval-runner/results")
# llama-server's cumulative counters (reset when a model is (re)loaded).
COUNTERS = {
    "llamacpp:prompt_tokens_total": "prompt_tokens",
    "llamacpp:prompt_seconds_total": "prompt_seconds",
    "llamacpp:tokens_predicted_total": "completion_tokens",
    "llamacpp:tokens_predicted_seconds_total": "generation_seconds",
}


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


def _get_text(path, timeout=10):
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def framework_counters(get_text=None):
    """{prompt_tokens, prompt_seconds, completion_tokens, generation_seconds}
    from llama-server's /metrics, or {"error": ...}."""
    try:
        text = (get_text or _get_text)("/metrics")
    except Exception as err:
        return {"error": f"{type(err).__name__}: {err}"}
    counters = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in COUNTERS:
            try:
                counters[COUNTERS[parts[0]]] = float(parts[1])
            except ValueError:
                pass
    if len(counters) != len(COUNTERS):
        return {"error": "llama-server /metrics is missing counters (started without --metrics?)"}
    return counters


def _parse_time(stamp):
    return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def _with_rates(totals):
    if totals.get("generation_seconds"):
        totals["generation_tokens_per_second"] = round(totals["completion_tokens"] / totals["generation_seconds"], 1)
    if totals.get("prompt_seconds"):
        totals["prompt_tokens_per_second"] = round(totals["prompt_tokens"] / totals["prompt_seconds"], 1)
    return totals


def run_metrics(before, after, started, finished):
    """CyberSecEval's run_metrics shape: duration_seconds plus
    model_under_test {prompt/completion tokens, tokens/s}. "unavailable"
    says why the token figures are missing (a counter went down: the model
    was reloaded during the run)."""
    metrics = {"source": "llama-server /metrics", "segments": 1}
    try:
        metrics["duration_seconds"] = round((_parse_time(finished) - _parse_time(started)).total_seconds(), 1)
    except (TypeError, ValueError):
        pass
    if "error" in (before or {"error": "not read"}) or "error" in (after or {"error": "not read"}):
        metrics["unavailable"] = (before or {}).get("error") or (after or {}).get("error") or "not read"
        return metrics
    delta = {name: after[name] - before[name] for name in COUNTERS.values()}
    if any(value < 0 for value in delta.values()):
        metrics["unavailable"] = "llama-server's counters went down: the model was reloaded during the run"
        return metrics
    metrics["model_under_test"] = _with_rates({
        "prompt_tokens": int(delta["prompt_tokens"]),
        "completion_tokens": int(delta["completion_tokens"]),
        "prompt_seconds": round(delta["prompt_seconds"], 1),
        "generation_seconds": round(delta["generation_seconds"], 1),
    })
    return metrics


def merge_metrics(previous, current):
    """A resumed run's totals: this segment plus what run.json already had."""
    if not previous:
        return current
    merged = {"source": current.get("source"), "segments": (previous.get("segments") or 1) + 1}
    durations = [m["duration_seconds"] for m in (previous, current) if "duration_seconds" in m]
    if durations:
        merged["duration_seconds"] = round(sum(durations), 1)
    reasons = [m["unavailable"] for m in (previous, current) if m.get("unavailable")]
    if reasons:
        merged["unavailable"] = reasons[-1] + " (in at least one segment of this resumed run)"
        return merged
    a, b = previous["model_under_test"], current["model_under_test"]
    totals = {key: a.get(key, 0) + b.get(key, 0) for key in
              ("prompt_tokens", "completion_tokens", "prompt_seconds", "generation_seconds")}
    merged["model_under_test"] = _with_rates({k: round(v, 1) if isinstance(v, float) else v for k, v in totals.items()})
    return merged


def record_metrics(run, metrics, results_dir=None):
    """Add metrics to the run's run.json (merged with a resumed run's earlier
    segments). Written in place so the file keeps its owner (the image's
    uid 1000). Returns the run's total metrics."""
    path = os.path.join(results_dir or RESULTS_DIR, run, "run.json")
    try:
        with open(path) as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return metrics
    record["run_metrics"] = merge_metrics(record.get("run_metrics"), metrics)
    with open(path, "w") as fh:
        json.dump(record, fh, indent=2)
    return record["run_metrics"]


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


def _holder_text(holder):
    if not holder:
        return "Framework"
    return f"Framework (held by {holder.get('suite') or '?'} {holder.get('benchmark') or ''} job {holder.get('job_id') or '?'})"


def take_framework(job_id, client, benchmark):
    """Wait for the shared Framework lock. False if cancelled or timed out."""
    def on_wait(holder):
        update_job(job_id, client, state="waiting", waiting_for=_holder_text(holder))
    if framework_lock.acquire(client, job_id, "eval", benchmark, on_wait=on_wait,
                              cancelled=lambda: cancel_requested(job_id, client),
                              poll=FRAMEWORK_POLL, max_wait=FRAMEWORK_MAX_WAIT):
        return True
    if not cancel_requested(job_id, client):
        update_job(job_id, client, state="failed",
                   error=f"gave up waiting for {_holder_text(framework_lock.holder(client))}")
    return False


def _launch(job_id, argv, client):
    """Wait for no other eval run (e.g. one started over ssh), then start.
    The caller already holds the Framework lock."""
    if not wait_until(job_id, client, lambda: eval_container_running() is None, "another eval run",
                      FRAMEWORK_POLL, FRAMEWORK_MAX_WAIT):
        return None
    counters = framework_counters()
    out = run_cmd(argv)
    run = started_run(out.stdout)
    if run is None:
        update_job(job_id, client, state="failed", error=(out.stderr or out.stdout).strip()[-2000:])
        return None
    update_job(job_id, client, run=run, run_started=_now(), counters_before=counters)
    return run


def _measure(job_id, run, client):
    """The run's metrics from the counters read at launch, into the job and run.json."""
    job = get_job(job_id, client)
    metrics = run_metrics(job.get("counters_before"), framework_counters(), job.get("run_started"), _now())
    try:
        total = record_metrics(run, metrics)
    except OSError:
        total = metrics
    update_job(job_id, client, run_metrics=metrics, run_metrics_total=total)


def _run_job(job_id, argv, client, benchmark):
    if cancel_requested(job_id, client):
        return update_job(job_id, client, state="cancelled")
    # Redelivered after a worker restart (acks_late) while its run container
    # carried on: re-attach to that run instead of starting a second one.
    # The lock is still ours (same job id) unless its TTL ran out.
    previous = get_job(job_id, client)
    if previous.get("run") and previous.get("state") in ("running", "publishing"):
        status, code = container_state(previous["run"])
        if status is not None:
            if status != "exited":
                framework_lock.try_acquire(client, job_id, "eval", benchmark)
                with framework_lock.held(client, job_id):
                    code = follow(job_id, previous["run"], client)
                    _measure(job_id, previous["run"], client)
            return finish(job_id, previous["run"], code, client)
    update_job(job_id, client, state="starting", started=_now())
    if not take_framework(job_id, client, benchmark):
        job = get_job(job_id, client)
        return job if job.get("state") == "failed" else update_job(job_id, client, state="cancelled")
    with framework_lock.held(client, job_id):
        run = _launch(job_id, argv, client)
        if run is None:
            job = get_job(job_id, client)
            if job.get("state") not in ("failed",):
                job = update_job(job_id, client, state="cancelled")
            return job
        code = follow(job_id, run, client)
        _measure(job_id, run, client)
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
    return _run_job(self.request.id, argv, client, task)


@app.task(bind=True, name="eval_tasks.resume")
def resume(self, run_name, force=False, submitted_by=""):
    client = _redis()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_name or ""):
        return update_job(self.request.id, client, state="failed", error="bad run name")
    update_job(self.request.id, client, task="resume", run=run_name, submitted_by=submitted_by)
    argv = [EVAL_RUN, "resume", run_name] + (["--force"] if force else [])
    return _run_job(self.request.id, argv, client, f"resume {run_name}")


@app.task(name="eval_tasks.cancel")
def cancel(job_id):
    """Ask a waiting or running job to stop (the run task notices within
    FOLLOW_EVERY / FRAMEWORK_POLL seconds); stop its container right away."""
    client = _redis()
    job = update_job(job_id, client, cancel_requested=True)
    if job.get("run") and job.get("state") == "running":
        run_cmd(["docker", "stop", f"eval-{job['run']}"], 120)
    return job


# ---------------------------------------------------------------- samples
# The panel's "prompts and responses" view. lm_eval tasks (GPQA, IFEval)
# write samples_<task>_<stamp>.jsonl next to their results; the wrappers
# (BFCL, AgentBench, RepoBench) keep no per-item log the panel can read.
# Read on demand and returned through the result backend, never copied to
# Nextcloud (GPQA's licence forbids reposting its questions).
SAMPLE_TEXT_MAX = 12000
SAMPLES_PAGE_MAX = 25
# For tasks scored under several filters, the row the headline uses.
PRIMARY_FILTER = {"gpqa_diamond_cot_zeroshot": "flexible-extract"}


def _clip(text, limit=SAMPLE_TEXT_MAX):
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit:,} more characters)"


def _prompt_text(row):
    """The prompt as sent: lm_eval keeps it in arguments.gen_args_0.arg_0,
    for chat APIs a JSON list of messages."""
    args = (row.get("arguments") or {}).get("gen_args_0") or {}
    raw = args.get("arg_0") if isinstance(args, dict) else None
    if raw is None and isinstance(row.get("arguments"), list) and row["arguments"]:
        raw = row["arguments"][0][0] if isinstance(row["arguments"][0], list) else row["arguments"][0]
    # lm_eval 0.4.12 wraps the JSON messages string in a one-item list.
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], str):
        raw = raw[0]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return raw
    if isinstance(raw, list):
        return "\n\n".join(f"[{m.get('role', '?')}]\n{m.get('content', '')}" if isinstance(m, dict) else str(m)
                           for m in raw)
    return "" if raw is None else json.dumps(raw)


def _sample_item(row):
    resps = row.get("resps") or [[""]]
    response = resps[0][0] if resps and resps[0] else ""
    scores = {m: row.get(m) for m in (row.get("metrics") or []) if m in row}
    return {
        "doc_id": row.get("doc_id"),
        "prompt": _clip(_prompt_text(row)),
        "response": _clip(response),
        "extracted": _clip((row.get("filtered_resps") or [""])[0], 500),
        "target": _clip(row.get("target"), 500),
        "scores": scores,
    }


def read_samples(run_dir, offset=0, limit=10):
    """One page of a run's prompts and responses, per task."""
    files = sorted(glob.glob(os.path.join(run_dir, "**", "samples_*.jsonl"), recursive=True))
    if not files:
        return {"available": False,
                "reason": "No per-question log for this run: only GPQA and IFEval keep one "
                          "(BFCL, AgentBench and RepoBench record scores only)."}
    newest = {}
    for path in files:  # samples_<task>_<stamp>.jsonl; a resume's newer file wins
        task = os.path.basename(path)[len("samples_"):].rsplit("_", 1)[0]
        newest[task] = path
    tasks = []
    for task, path in sorted(newest.items()):
        rows = {}
        with open(path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                doc = row.get("doc_id")
                primary = PRIMARY_FILTER.get(task)
                if doc not in rows or (primary and row.get("filter") == primary):
                    rows[doc] = row
        ordered = [rows[d] for d in sorted(rows, key=lambda d: (d is None, d))]
        page = ordered[offset:offset + limit]
        tasks.append({"task": task, "total": len(ordered), "offset": offset,
                      "items": [_sample_item(r) for r in page]})
    return {"available": True, "tasks": tasks}


@app.task(name="eval_tasks.samples")
def samples(run_name, offset=0, limit=10):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_name or ""):
        return {"available": False, "reason": "bad run name"}
    offset = max(0, int(offset or 0))
    limit = max(1, min(SAMPLES_PAGE_MAX, int(limit or 10)))
    return read_samples(os.path.join(RESULTS_DIR, run_name), offset, limit)


# ------------------------------------------------- results across benchmarks
CSE_DIR = "_cse"
CSE_FIELDS = ("job_id", "benchmark", "model", "model_file", "build", "headline", "finished_at",
              "duration_seconds", "completion_tokens", "tokens_per_second", "report", "ok")


@app.task(name="eval_tasks.record_cse")
def record_cse(row):
    """Keep a CyberSecEval run's headline row (sent by cse-controller's
    cse_tasks) with the eval results, then publish so it reaches the
    Nextcloud Tables table. Re-sending the same job replaces its row."""
    if not isinstance(row, dict) or not re.fullmatch(r"[0-9a-f-]{8,64}", str(row.get("job_id", ""))):
        return {"ok": False, "error": "bad row"}
    record = {k: row.get(k) for k in CSE_FIELDS}
    folder = os.path.join(RESULTS_DIR, CSE_DIR)
    os.makedirs(folder, mode=0o755, exist_ok=True)
    with open(os.path.join(folder, f"{record['job_id']}.json"), "w") as fh:
        json.dump(record, fh, indent=1)
    out = run_cmd([EVAL_RUN, "publish"], 900)
    return {"ok": out.returncode == 0, "published": (out.stdout.strip().splitlines() or [""])[-1]}


@app.task(name="eval_tasks.compare")
def compare():
    """Every result row for the panel's Compare tab: the same rows the
    Tables table holds, read from the results here (publish.py, installed
    next to this module)."""
    # Celery only has the worker's directory on sys.path while it imports
    # the app, so a later import of a module next to this one needs it put
    # back (found live 2026-10-08: ModuleNotFoundError: publish).
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import publish  # noqa: PLC0415 -- only the ctl worker needs it
    return {"rows": publish.compare_rows(RESULTS_DIR), "at": _now()}


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
        status["lock"] = framework_lock.holder(client)
        client.set(FRAMEWORK_KEY, json.dumps(status), ex=STATUS_EVERY * 10)
        n += 1
        sleep(STATUS_EVERY)


@worker_ready.connect
def _start_status_loop(sender=None, **_):
    if str(getattr(sender, "hostname", "")).startswith("ctl@"):
        threading.Thread(target=status_loop, daemon=True, name="framework-status").start()
