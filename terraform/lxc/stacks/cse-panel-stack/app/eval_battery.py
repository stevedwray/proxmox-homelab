"""cse-panel's "Eval battery" page: start, watch and control eval-runner
benchmark runs (GPQA, IFEval, BFCL, AgentBench, RepoBench) on
ai-services-stack. docs/eval-runner/panel-plan.md.

Like the CyberSecEval pages, this only enqueues Celery tasks and reads
state from Redis. The work happens in eval-runner's worker on
ai-services-stack (terraform/lxc/ansible/files/eval-runner/eval_tasks.py),
which connects out to this stack's Redis:

  queue eval-runner      eval_tasks.run / eval_tasks.resume (one at a time)
  queue eval-runner-ctl  eval_tasks.cancel / eval_tasks.publish
  key eval:framework     Framework status, written by the worker every 30 s
  key eval:job:<id>      per-job state, log tail and results

The page can't reach Framework or ai-services-stack itself, and doesn't
need to.
"""

import html
import json
import os
from datetime import datetime, timezone

from celery import Celery
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
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


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def page():
    boxes = "".join(
        f'<label class="row"><input type="checkbox" name="task" value="{t}">'
        f'<span class="name">{t}</span><span class="desc">{html.escape(d)}</span></label>'
        for t, d in TASKS.items())
    links = " · ".join(f'<a href="{u}" target="_blank" rel="noopener">{html.escape(n)}</a>' for n, u in LINKS.items())
    # The panel's own UI is the Dash app on cse-panel.<domain>; panel-web's
    # "/" no longer serves a page.
    domain = os.environ.get("LAB_DOMAIN", "")
    home = f"https://cse-panel.{domain}/" if domain else "/"
    return (PAGE.replace("{{BOXES}}", boxes).replace("{{LINKS}}", links)
            .replace("{{HOME}}", html.escape(home)))


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Eval battery</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; color: #1a1a1a; }
  h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }
  .list { border: 1px solid #eee; border-radius: 6px; }
  .row { display: flex; align-items: baseline; gap: .6rem; padding: .45rem .7rem; border-bottom: 1px solid #f2f2f2; cursor: pointer; }
  .row:last-child { border-bottom: none; } .row:hover { background: #f7f9fc; }
  .name { font-weight: 600; min-width: 7rem; } .desc, .muted { color: #666; font-size: .85rem; }
  .field { display: block; margin: .6rem 0; } button { padding: .4rem 1rem; cursor: pointer; }
  .status { padding: .6rem .9rem; border: 1px solid #eee; border-radius: 6px; background: #fafafa; }
  .job { border: 1px solid #ddd; border-radius: 6px; margin-bottom: .7rem; padding: .6rem .9rem; }
  .job pre { background: #f6f6f6; padding: .5rem; font-size: .78rem; overflow-x: auto; max-height: 14rem; margin: .5rem 0 0; }
  .s-queued, .s-waiting { color: #888; } .s-starting, .s-running, .s-publishing { color: #b8860b; font-weight: 600; }
  .s-done { color: #1a7f37; font-weight: 600; } .s-failed, .s-cancelled { color: #c62828; font-weight: 600; }
  .small { font-size: .8rem; padding: .15rem .6rem; margin-left: .4rem; }
  #toast { margin: .5rem 0; padding: .5rem .8rem; border-radius: 4px; background: #eef; display: none; }
</style></head>
<body>
<p class="muted"><a href="{{HOME}}">&larr; CyberSecEval</a></p>
<h1>Eval battery</h1>
<p class="muted">Runs on ai-services-stack against whatever Framework's llama-server is serving.
Results go to Nextcloud automatically: {{LINKS}}</p>
<div class="status" id="framework">Framework: checking…</div>
<div id="toast"></div>

<h2>Start runs</h2>
<form id="form">
  <div class="list">{{BOXES}}</div>
  <label class="field">Size:
    <select name="mode" id="mode">
      <option value="full">Full run (ranked)</option>
      <option value="pilot">Pilot (40 items; 10 episodes / 5 per level)</option>
      <option value="limit">Smoke test: first N items</option>
    </select>
    <input name="limit" id="limit" type="number" min="1" max="10000" value="5" style="width:5rem;display:none">
  </label>
  <label class="field">Note (e.g. reasoning_effort=high): <input name="note" maxlength="200" style="width:24rem"></label>
  <label class="field"><input type="checkbox" name="budget_32k"> 32k token budget (GPQA/IFEval only; a separate series)</label>
  <button type="submit">Queue selected</button>
  <span class="muted">Runs go one at a time, in order; each waits until Framework is idle.</span>
</form>

<h2>Runs <button class="small" onclick="publishNow()">Publish to Nextcloud now</button></h2>
<div id="jobs" class="muted">Loading…</div>

<script>
const $ = (s) => document.querySelector(s);
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.style.display = 'block'; setTimeout(() => t.style.display = 'none', 6000); }
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
$('#mode').onchange = () => { $('#limit').style.display = $('#mode').value === 'limit' ? 'inline' : 'none'; };

$('#form').onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { tasks: f.getAll('task'), mode: f.get('mode'), limit: parseInt(f.get('limit')) || null,
                 note: f.get('note') || '', budget_32k: f.get('budget_32k') === 'on' };
  if (!body.tasks.length) { toast('Pick at least one benchmark.'); return; }
  const res = await fetch('/eval/api/jobs', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  const data = await res.json();
  toast(res.ok ? `Queued ${data.submitted.length} run(s).` : `Not queued: ${data.detail}`);
  refresh();
};

async function act(path, msg) {
  const res = await fetch(path, { method: 'POST' });
  const data = await res.json();
  toast(res.ok ? msg : `Failed: ${data.detail}`);
  refresh();
}
function cancelJob(id) { if (confirm('Cancel this run?')) act(`/eval/api/jobs/${id}/cancel`, 'Cancel requested.'); }
function resumeJob(id) { act(`/eval/api/jobs/${id}/resume`, 'Resume queued.'); }
function publishNow() { act('/eval/api/publish', 'Publish requested; the reports update in a minute or so.'); }

function frameworkLine(fw) {
  if (!fw) return 'Framework: no status yet (is the eval-runner worker running?)';
  if (fw.error) return `Framework: <b>unreachable</b> (${esc(fw.error)}) · checked ${esc(fw.checked)}`;
  const busy = fw.busy ? `<b>${fw.busy} of ${fw.slots} slots busy</b>` : `idle (${fw.slots} slots)`;
  const ev = fw.eval_running ? ` · eval container: ${esc(fw.eval_running)}` : '';
  const lock = fw.lock ? ` · <b>busy with ${esc(fw.lock.suite)} ${esc(fw.lock.benchmark)}</b> (job ${esc(fw.lock.job_id)}); new benchmark runs wait` : '';
  return `Framework: serving <b>${esc(fw.model)}</b> · ${busy}${lock}${ev} · checked ${esc(fw.checked)}`;
}

function duration(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return h ? `${h}h ${m}m ${s}s` : (m ? `${m}m ${s}s` : `${s}s`);
}

// Duration, tokens and tokens/s (eval_tasks.py, from llama-server's /metrics).
function metricsLine(m) {
  if (!m) return '';
  const parts = [];
  if (m.duration_seconds != null) parts.push(`${duration(m.duration_seconds)}${m.segments > 1 ? ` over ${m.segments} segments` : ''}`);
  const mut = m.model_under_test;
  if (mut) {
    parts.push(`${mut.completion_tokens.toLocaleString()} tokens generated`);
    if (mut.generation_tokens_per_second != null) parts.push(`${mut.generation_tokens_per_second} tokens/s`);
    parts.push(`${mut.prompt_tokens.toLocaleString()} prompt tokens`);
  } else if (m.unavailable) {
    parts.push(`tokens unavailable: ${esc(m.unavailable)}`);
  }
  return parts.length ? `<div>Run: ${parts.join(' · ')}</div>` : '';
}

function jobCard(j) {
  const what = j.task === 'resume' ? `resume ${esc(j.run)}` :
    `${esc(j.task)} · ${esc(j.mode)}${j.mode === 'limit' ? ' ' + esc(j.limit) : ''}${j.budget_32k ? ' · 32k' : ''}`;
  const live = ['queued', 'waiting', 'starting', 'running'].includes(j.state);
  const buttons = (live ? `<button class="small" onclick="cancelJob('${j.id}')">Cancel</button>` : '') +
    (['failed', 'cancelled'].includes(j.state) && j.run ? `<button class="small" onclick="resumeJob('${j.id}')">Resume</button>` : '');
  const waiting = j.state === 'waiting' ? ` (for ${esc(j.waiting_for)})` : '';
  const body = j.results ? `<pre>${esc(j.results)}</pre>` : (j.log_tail ? `<pre>${esc(j.log_tail)}</pre>` : '');
  const err = j.error ? `<pre>${esc(j.error)}</pre>` : '';
  return `<div class="job"><b>${what}</b> <span class="s-${esc(j.state)}">${esc(j.state)}${waiting}</span>${buttons}
    <div class="muted">${j.run ? 'run ' + esc(j.run) + ' · ' : ''}${j.note ? 'note: ' + esc(j.note) + ' · ' : ''}by ${esc(j.submitted_by)} · submitted ${esc(j.submitted)}${j.finished ? ' · finished ' + esc(j.finished) : ''}</div>
    ${metricsLine(j.run_metrics_total || j.run_metrics)}${body}${err}</div>`;
}

async function refresh() {
  try {
    const s = await (await fetch('/eval/api/state')).json();
    $('#framework').innerHTML = frameworkLine(s.framework);
    $('#jobs').innerHTML = s.jobs.length ? s.jobs.map(jobCard).join('') : 'No runs yet.';
  } catch (e) { $('#framework').textContent = 'Could not load state: ' + e; }
}
refresh(); setInterval(refresh, 10000);
</script>
</body></html>
"""
