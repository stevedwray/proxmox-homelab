"""The Eval battery tab (GPQA, IFEval, BFCL, AgentBench, RepoBench):
phase 3 of docs/benchmark-panel/plan.md. Replaces panel-web's HTML page
(app/eval_battery.py) and uses that page's JSON API unchanged:

  GET  /eval/api/state             Framework status, recent jobs, links
  POST /eval/api/jobs              start runs (one job per benchmark)
  POST /eval/api/jobs/<id>/cancel  cancel a queued, waiting or running job
  POST /eval/api/jobs/<id>/resume  resume a failed or cancelled run
  POST /eval/api/publish           republish reports to Nextcloud

The work happens in eval-runner's worker on ai-services-stack
(eval_tasks.py); this tab only talks to panel-web.
"""
import os

import dash_bootstrap_components as dbc
import requests
from dash import ALL, MATCH, Input, Output, State, callback, ctx, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate
from flask import request

PANEL_API_BASE_URL = os.environ.get("PANEL_API_BASE_URL", "http://panel-web:8000")
# The reports folder as the operator sees it (shared from the eval-reports
# account into their root; see app/eval_battery.py SHARED_REPORTS_DIR).
NEXTCLOUD_URL = "https://nextcloud.lab.gibbsgreatly.xyz"
SHARED_REPORTS_DIR = "/eval-runner"
SAMPLES_PAGE = 10
MIN_PROMPT_SECONDS = 5

# Duplicated from app/eval_battery.py (panel-web), which validates again.
TASKS = {
    "gpqa": "GPQA diamond: 198 graduate-level science questions, chain of thought",
    "ifeval": "IFEval: 541 prompts with verifiable formatting instructions",
    "bfcl": "BFCL simple: 400 single function-call cases",
    "agentbench": "AgentBench os-std: 100 sandboxed shell episodes (seed 42)",
    "repobench": "RepoBench (rebuilt): next-line code completion, 1500 samples",
}
BUDGET_TASKS = ("gpqa", "ifeval")
# What "how many" means for each benchmark, from eval-runner's runmeta.py
# and wrappers (bfcl_run.py, agentbench_run.py, repobench_run.py): the
# maximum, the pilot size, the unit and which items a smaller run takes.
# RepoBench's count is per context length (5) and setting (3), so a run
# of N asks 15 x N of its 1500 samples.
SIZES = {
    "gpqa": {"name": "GPQA diamond", "max": 198, "pilot": 40, "unit": "questions", "which": "the first {n}"},
    "ifeval": {"name": "IFEval", "max": 541, "pilot": 40, "unit": "prompts", "which": "the first {n}"},
    "bfcl": {"name": "BFCL simple", "max": 400, "pilot": 40, "unit": "cases", "which": "spread evenly over all 400"},
    "agentbench": {"name": "AgentBench os-std", "max": 100, "pilot": 10, "unit": "episodes",
                   "which": "the first {n} of the seed-42 set"},
    "repobench": {"name": "RepoBench (rebuilt)", "max": 100, "pilot": 5, "unit": "samples",
                  "which": "the first {n} at each of 5 context lengths x 3 settings", "per_level": 15},
}
LIVE_STATES = ("queued", "waiting", "starting", "running", "publishing")
TABLE_STYLE = dict(
    style_table={"width": "100%", "overflowX": "auto"},
    style_header={"backgroundColor": "#1a1a2e", "color": "white", "fontWeight": "bold"},
    style_cell={"backgroundColor": "#16162a", "color": "white", "border": "1px solid #333",
                "padding": "8px", "textAlign": "left", "whiteSpace": "normal"},
    style_as_list_view=True,
)


def _format_duration(seconds):
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes}m {secs}s" if hours else (f"{minutes}m {secs}s" if minutes else f"{secs}s")


def job_metrics(job):
    """The run's totals (all segments of a resumed run) or this job's own."""
    return job.get("run_metrics_total") or job.get("run_metrics") or {}


def job_row(job):
    """One row of the runs table."""
    metrics = job_metrics(job)
    mut = metrics.get("model_under_test") or {}
    if job.get("task") == "resume":
        what = "resume"
    else:
        what = job.get("mode") or ""
        if what == "limit":
            what = f"limit {job.get('limit')}"
        if job.get("budget_32k"):
            what += " · 32k"
    state = job.get("state") or "?"
    if state == "waiting" and job.get("waiting_for"):
        state = f"waiting for {job['waiting_for']}"
    return {
        "id": job.get("id"),
        "submitted": (job.get("submitted") or "").replace("T", " ").replace("Z", ""),
        "task": job.get("task") or "",
        "mode": what,
        "state": state,
        "run": job.get("run") or "",
        "duration": _format_duration(metrics.get("duration_seconds")),
        "tokens": f"{mut['completion_tokens']:,}" if "completion_tokens" in mut else "",
        "tokens_per_second": mut.get("generation_tokens_per_second", ""),
    }


def metrics_block(metrics):
    if not metrics:
        return [html.P("Run metrics: not recorded (runs before 2026-10-08, or not finished yet).",
                       className="text-muted small")]
    lines = [html.Strong("Duration: "), _format_duration(metrics.get("duration_seconds")) or "–"]
    if (metrics.get("segments") or 1) > 1:
        lines.append(f" over {metrics['segments']} segments (resumed)")
    block = [html.H5("Run metrics", className="mt-3"), html.P(lines)]
    if metrics.get("unavailable"):
        return block + [html.P(f"Tokens unavailable: {metrics['unavailable']}", className="text-warning")]
    mut = metrics.get("model_under_test") or {}
    # Under MIN_PROMPT_SECONDS of prompt work (e.g. a cached prompt) the
    # speed is noise; publish.py applies the same rule.
    prompt_speed = (mut.get("prompt_tokens_per_second", "–") if (mut.get("prompt_seconds") or 0) >= MIN_PROMPT_SECONDS
                    else "– (too little prompt work to measure)")
    rows = [
        ("Generated tokens (incl. reasoning)", f"{mut['completion_tokens']:,}" if "completion_tokens" in mut else "–"),
        ("Prompt tokens processed (cached text excluded)", f"{mut['prompt_tokens']:,}" if "prompt_tokens" in mut else "–"),
        ("Generation speed (tokens/s)", mut.get("generation_tokens_per_second", "–")),
        ("Prompt processing (tokens/s)", prompt_speed),
    ]
    table = dbc.Table([html.Tbody([html.Tr([html.Td(k), html.Td(str(v))]) for k, v in rows])],
                      bordered=True, hover=True, size="sm")
    return block + [table, html.P("From llama-server's /metrics counters, read before and after the run. "
                                  "Prompt text the server still had cached from an earlier request isn't counted.",
                                  className="text-muted small")]


def job_detail(job):
    if not job:
        return [html.P("Select a run above to see its log, results and metrics.", className="text-muted")]
    row = job_row(job)
    title = f"{row['task']} · {row['mode']}" if row["task"] != "resume" else f"resume {row['run']}"
    meta = [html.Strong("State: "), row["state"]]
    for label, key in (("Run", "run"), ("Note", "note"), ("By", "submitted_by"),
                       ("Submitted", "submitted"), ("Finished", "finished")):
        if job.get(key):
            meta += ["  ·  ", html.Strong(f"{label}: "), str(job[key])]
    children = [html.H4(title, className="card-title"), html.P(meta, className="text-muted")]
    if job.get("run") and job.get("state") in ("done", "failed", "cancelled"):
        children.append(html.P(html.A(
            "This run's report in Nextcloud →",
            href=f"{NEXTCLOUD_URL}/apps/files/?dir={SHARED_REPORTS_DIR}/runs/{job['run']}",
            target="_blank", rel="noopener")))
    if job.get("error"):
        children.append(dbc.Alert(html.Pre(job["error"], className="mb-0"), color="danger"))
    if job.get("results"):
        children += [html.H5("Results"), html.Pre(job["results"])]
    elif job.get("log_tail"):
        children += [html.H5("Log (last lines)"), html.Pre(job["log_tail"])]
    if job.get("publish_error"):
        children.append(dbc.Alert(f"Publish failed: {job['publish_error']}", color="warning"))
    elif job.get("published"):
        children.append(html.P(f"Published: {job['published']}", className="text-muted small"))
    return children + metrics_block(job_metrics(job))


def _verdict(scores):
    values = [v for v in (scores or {}).values() if isinstance(v, (int, float, bool))]
    if not values:
        return ""
    return "✓ correct" if all(float(v) >= 1 for v in values) else "✗ wrong"


def samples_view(page, offset):
    """One page of prompts and responses, per task, as accordions."""
    if not page:
        return [html.P("Press Show to load this run's prompts and responses.", className="text-muted small")]
    if page.get("error"):
        return [dbc.Alert(page["error"], color="warning")]
    if not page.get("available"):
        return [html.P(page.get("reason") or "Not available for this run.", className="text-muted")]
    out = []
    pre = {"whiteSpace": "pre-wrap", "maxHeight": "420px", "overflowY": "auto"}
    for task in page.get("tasks") or []:
        items = task.get("items") or []
        first, last = offset + 1, offset + len(items)
        out.append(html.H6(f"{task['task']} · {first}–{last} of {task['total']}" if items
                           else f"{task['task']} · nothing at {first} (of {task['total']})", className="mt-3"))
        accordion = []
        for item in items:
            title = " · ".join(p for p in (
                f"#{item.get('doc_id')}", _verdict(item.get("scores")),
                f"answer {item['extracted']}" if item.get("extracted") else "",
                f"expected {item['target']}" if item.get("target") else "") if p)
            body = [html.Strong("Prompt"), html.Pre(item.get("prompt") or "(not recorded)", style=pre),
                    html.Strong("Response"), html.Pre(item.get("response") or "(empty)", style=pre)]
            if item.get("scores"):
                body.append(html.P("Scores: " + ", ".join(f"{k} {v}" for k, v in item["scores"].items()),
                                   className="text-muted small mb-0"))
            accordion.append(dbc.AccordionItem(body, title=title))
        if accordion:
            out.append(dbc.Accordion(accordion, start_collapsed=True, always_open=True))
    out.append(html.P("Read live from the run's files on ai-services-stack; not copied to Nextcloud.",
                      className="text-muted small mt-2 mb-0"))
    return out


def can_cancel(job):
    return bool(job) and job.get("state") in LIVE_STATES and job.get("state") != "publishing"


def can_resume(job):
    return bool(job) and job.get("state") in ("failed", "cancelled") and bool(job.get("run"))


def size_hint(task, size, count):
    """What the chosen size runs, e.g. "50 of 198 questions (the first 50)"."""
    spec = SIZES[task]
    n = {"pilot": spec["pilot"], "full": spec["max"]}.get(size, count)
    if not isinstance(n, int) or not 1 <= n <= spec["max"]:
        return f"Enter a number from 1 to {spec['max']}."
    per_level = spec.get("per_level", 1)
    total, asked = spec["max"] * per_level, n * per_level
    if asked >= total:
        return f"All {total:,} {spec['unit']}. Full runs are the ones ranked against other models."
    which = spec["which"].format(n=n)
    return f"{asked:,} of {total:,} {spec['unit']} ({which}). A smoke test: not ranked against full runs."


def request_for(task, size, count, note, budget):
    """The /eval/api/jobs body for one benchmark, or an error string."""
    spec = SIZES[task]
    if size == "count":
        if not isinstance(count, int) or not 1 <= count <= spec["max"]:
            return f"{spec['name']}: enter a number from 1 to {spec['max']}"
        size = "full" if count == spec["max"] else "limit"
    return {"tasks": [task], "mode": size, "limit": count if size == "limit" else None,
            "note": (note or "").strip(), "budget_32k": bool(budget) and task in BUDGET_TASKS}


def benchmark_row(task):
    spec = SIZES[task]
    per_level = spec.get("per_level", 1)
    return dbc.Row(className="py-2 border-bottom border-secondary", children=[
        dbc.Col(dbc.Switch(id={"type": "eval-on", "task": task}, value=False,
                           label=html.Span([html.Strong(spec["name"]), html.Br(),
                                            html.Span(TASKS[task].split(": ", 1)[1], className="text-muted small")])),
                md=5),
        dbc.Col([
            html.Div([
                # Choose last, so its number box sits right after it.
                # Labels show what actually runs (RepoBench: all levels).
                dbc.RadioItems(
                    id={"type": "eval-size", "task": task}, value="pilot", inline=True,
                    options=[{"label": f"Pilot ({spec['pilot'] * per_level:,})", "value": "pilot"},
                             {"label": f"Full ({spec['max'] * per_level:,})", "value": "full"},
                             {"label": "Choose" + (" per level" if per_level > 1 else ""), "value": "count"}],
                    className="me-1",
                ),
                dbc.Input(id={"type": "eval-count", "task": task}, type="number", min=1, max=spec["max"], step=1,
                          value=min(50, spec["max"]), size="sm", style={"maxWidth": "90px"}),
            ], className="d-flex align-items-center flex-wrap"),
            html.Div(id={"type": "eval-hint", "task": task}, className="text-muted small mt-1"),
        ], md=7),
    ])


run_section = dbc.Card(dbc.CardBody([
    html.H4("Start a run", className="card-title mb-1"),
    html.P("Switch on each benchmark to run, and choose how much of it.", className="text-muted small"),
    html.Div([benchmark_row(task) for task in TASKS], className="mb-3"),
    dbc.Switch(id="eval-budget", label="32k token budget (applies to GPQA and IFEval)", value=False,
               className="mb-2"),
    dbc.Input(id="eval-note", placeholder="Note (one line, e.g. reasoning_effort=high)", maxLength=200,
              className="mb-3"),
    dbc.Button("Start run(s)", id="eval-submit-btn", color="primary"),
    dbc.Alert(id="eval-submit-result", is_open=False, className="mt-3"),
    html.P("Each benchmark is its own run. They go one at a time, in this order, and wait while a "
           "CyberSecEval run is using Framework.", className="text-muted small mt-3 mb-0"),
]))

runs_section = html.Div([
    dbc.Card(dbc.CardBody([
        html.Div([
            html.H4("Runs", className="card-title mb-0 me-auto"),
            dbc.Button("Publish to Nextcloud now", id="eval-publish-btn", color="secondary",
                       size="sm", outline=True),
        ], className="d-flex align-items-center mb-2"),
        html.Div(id="eval-links", className="small mb-3"),
        dash_table.DataTable(
            id="eval-jobs-table",
            columns=[
                {"name": "Submitted (UTC)", "id": "submitted"},
                {"name": "Benchmark", "id": "task"},
                {"name": "Size", "id": "mode"},
                {"name": "State", "id": "state"},
                {"name": "Duration", "id": "duration"},
                {"name": "Tokens", "id": "tokens"},
                {"name": "Tokens/s", "id": "tokens_per_second"},
            ],
            data=[], row_selectable="single", selected_rows=[], page_size=15,
            **TABLE_STYLE,
        ),
        dbc.Alert(id="eval-action-result", is_open=False, className="mt-3"),
    ])),
    dbc.Card(className="mt-3", children=dbc.CardBody([
        html.Div(id="eval-detail", children=job_detail(None)),
        # Always in the layout; the detail callback shows the ones that
        # apply to the selected run.
        html.Div([
            dbc.Button("Cancel run", id="eval-cancel-btn", color="danger", size="sm", className="me-2",
                       style={"display": "none"}),
            dbc.Button("Resume run", id="eval-resume-btn", color="secondary", size="sm",
                       style={"display": "none"}),
        ], className="mt-2"),
    ])),
    dbc.Card(id="eval-samples-card", className="mt-3", style={"display": "none"}, children=dbc.CardBody([
        html.Div([
            html.H5("Prompts and responses", className="mb-0 me-auto"),
            dbc.Button("Show", id="eval-samples-show", color="primary", size="sm", className="me-2"),
            dbc.Button("‹ Previous", id="eval-samples-prev", color="secondary", size="sm", outline=True,
                       className="me-2"),
            dbc.Button("Next ›", id="eval-samples-next", color="secondary", size="sm", outline=True),
        ], className="d-flex align-items-center"),
        dcc.Loading(html.Div(id="eval-samples", children=samples_view(None, 0)), type="dot"),
    ])),
    dcc.Store(id="eval-samples-offset", data=0),
])


def layout():
    return html.Div([
        dcc.Interval(id="eval-poll", interval=5000, n_intervals=0),
        dcc.Store(id="eval-jobs"),
        dcc.Store(id="eval-selected"),
        html.Div(run_section, id="eval-run-section"),
        html.Div(runs_section, id="eval-runs-section"),
    ])


def _post(path, json=None):
    headers = {"X-Authentik-Username": request.headers.get("X-Authentik-Username", "unknown")}
    resp = requests.post(f"{PANEL_API_BASE_URL}{path}", json=json, headers=headers, timeout=10)
    try:
        body = resp.json()
    except ValueError:
        body = {"detail": resp.text}
    return resp.status_code, body


@callback(
    Output({"type": "eval-hint", "task": MATCH}, "children"),
    Input({"type": "eval-size", "task": MATCH}, "value"),
    Input({"type": "eval-count", "task": MATCH}, "value"),
    State({"type": "eval-size", "task": MATCH}, "id"),
)
def update_size(size, count, size_id):
    return size_hint(size_id["task"], size, count)


@callback(
    Output({"type": "eval-size", "task": MATCH}, "value"),
    Input({"type": "eval-count", "task": MATCH}, "value"),
    prevent_initial_call=True,
)
def typing_a_number_picks_choose(_count):
    """The box sits right after Choose; typing in it selects Choose."""
    return "count"


@callback(
    Output("eval-submit-result", "children"),
    Output("eval-submit-result", "color"),
    Output("eval-submit-result", "is_open"),
    Input("eval-submit-btn", "n_clicks"),
    State({"type": "eval-on", "task": ALL}, "value"),
    State({"type": "eval-on", "task": ALL}, "id"),
    State({"type": "eval-size", "task": ALL}, "value"),
    State({"type": "eval-count", "task": ALL}, "value"),
    State("eval-budget", "value"),
    State("eval-note", "value"),
    prevent_initial_call=True,
)
def submit(_n, on, on_ids, sizes, counts, budget, note):
    chosen = [(i["task"], size, count) for i, enabled, size, count in zip(on_ids, on, sizes, counts) if enabled]
    if not chosen:
        return "Switch on at least one benchmark.", "warning", True
    bodies = [request_for(task, size, count, note, budget) for task, size, count in chosen]
    errors = [b for b in bodies if isinstance(b, str)]
    if errors:
        return "Nothing started. " + "; ".join(errors), "warning", True
    started, failed = [], []
    for body in bodies:  # in table order, so the worker runs them in that order
        name = SIZES[body["tasks"][0]]["name"]
        size = f"{body['limit']}" if body["mode"] == "limit" else body["mode"]
        try:
            status, data = _post("/eval/api/jobs", body)
        except requests.RequestException as exc:
            failed.append(f"{name}: {exc}")
            continue
        if status != 200:
            failed.append(f"{name}: {data.get('detail')}")
        else:
            started.append(f"{name} ({size})")
    if failed:
        return (f"Queued: {', '.join(started) or 'none'}. Not started: {'; '.join(failed)}"), "danger", True
    return f"Queued {', '.join(started)}. Watch them under Results.", "success", True


@callback(
    Output("eval-jobs", "data"),
    Output("eval-jobs-table", "data"),
    Output("eval-links", "children"),
    Input("eval-poll", "n_intervals"),
)
def poll(_n):
    try:
        state = requests.get(f"{PANEL_API_BASE_URL}/eval/api/state", timeout=10).json()
    except (requests.RequestException, ValueError):
        raise PreventUpdate
    jobs = state.get("jobs") or []
    links = []
    for label, url in (state.get("links") or {}).items():
        if links:
            links.append("  ·  ")
        links.append(html.A(label, href=url, target="_blank", rel="noopener"))
    return jobs, [job_row(j) for j in jobs], links


@callback(
    Output("eval-selected", "data"),
    Input("eval-jobs-table", "selected_rows"),
    State("eval-jobs-table", "data"),
)
def select(selected_rows, rows):
    if not selected_rows or not rows or selected_rows[0] >= len(rows):
        return None
    return rows[selected_rows[0]]["id"]


@callback(
    Output("eval-detail", "children"),
    Output("eval-cancel-btn", "style"),
    Output("eval-resume-btn", "style"),
    Output("eval-samples-card", "style"),
    Input("eval-selected", "data"),
    Input("eval-jobs", "data"),
)
def detail(job_id, jobs):
    job = next((j for j in jobs or [] if j.get("id") == job_id), None) if job_id else None
    hidden = {"display": "none"}
    return (job_detail(job), ({} if can_cancel(job) else hidden), ({} if can_resume(job) else hidden),
            ({} if job and job.get("run") else hidden))


def fetch_samples(job_id, offset):
    try:
        resp = requests.get(f"{PANEL_API_BASE_URL}/eval/api/jobs/{job_id}/samples",
                            params={"offset": offset, "limit": SAMPLES_PAGE}, timeout=40)
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return {"error": f"Couldn't load them: {exc}"}
    if resp.status_code != 200:
        return {"error": f"Couldn't load them: {body.get('detail')}"}
    return body


@callback(
    Output("eval-samples", "children"),
    Output("eval-samples-offset", "data"),
    Input("eval-samples-show", "n_clicks"),
    Input("eval-samples-prev", "n_clicks"),
    Input("eval-samples-next", "n_clicks"),
    Input("eval-selected", "data"),
    State("eval-samples-offset", "data"),
    prevent_initial_call=True,
)
def show_samples(_show, _prev, _next, job_id, offset):
    trigger = ctx.triggered_id
    if trigger == "eval-selected" or not job_id:  # a different run: start again
        return samples_view(None, 0), 0
    offset = {"eval-samples-show": 0, "eval-samples-prev": max(0, (offset or 0) - SAMPLES_PAGE),
              "eval-samples-next": (offset or 0) + SAMPLES_PAGE}[trigger]
    return samples_view(fetch_samples(job_id, offset), offset), offset


@callback(
    Output("eval-action-result", "children"),
    Output("eval-action-result", "color"),
    Output("eval-action-result", "is_open"),
    Input("eval-cancel-btn", "n_clicks"),
    Input("eval-resume-btn", "n_clicks"),
    Input("eval-publish-btn", "n_clicks"),
    State("eval-selected", "data"),
    prevent_initial_call=True,
)
def act(cancel_clicks, resume_clicks, publish_clicks, job_id):
    trigger = ctx.triggered_id
    clicks = {"eval-cancel-btn": cancel_clicks, "eval-resume-btn": resume_clicks,
              "eval-publish-btn": publish_clicks}.get(trigger)
    if not clicks:
        return no_update, no_update, no_update
    if trigger == "eval-publish-btn":
        path, done = "/eval/api/publish", "Publish requested; the reports update in a minute or so."
    elif not job_id:
        return "Select a run first.", "warning", True
    elif trigger == "eval-cancel-btn":
        path, done = f"/eval/api/jobs/{job_id}/cancel", "Cancel requested."
    else:
        path, done = f"/eval/api/jobs/{job_id}/resume", "Resume queued."
    try:
        status, data = _post(path)
    except requests.RequestException as exc:
        return f"Failed: {exc}", "danger", True
    if status != 200:
        return f"Failed: {data.get('detail')}", "danger", True
    return done, "success", True
