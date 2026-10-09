"""The Eval battery tab (GPQA, IFEval, BFCL, AgentBench, RepoBench):
phase 3 of docs/benchmark-panel/plan.md. Replaces panel-web's HTML page
(app/eval_battery.py) and uses that page's JSON API unchanged:

  GET  /eval/api/state             Framework status, recent jobs, links
  POST /eval/api/jobs              start runs (one job per benchmark)
  POST /eval/api/jobs/<id>/cancel  cancel a queued, waiting or running job
  POST /eval/api/jobs/<id>/resume  resume a failed or cancelled run
  DELETE /eval/api/jobs/<id>       delete a finished run everywhere
  POST /eval/api/publish           republish reports to Nextcloud

The work happens in eval-runner's worker on ai-services-stack
(eval_tasks.py); this tab only talks to panel-web.
"""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
# Settings a person picks (run form, tabs, switches) are kept in this
# browser's localStorage, so a reload or a later visit starts from them.
# Dash keeps only what the person changed: a value a callback sets (typing
# a number selects Choose) isn't kept.
PERSIST = {"persistence": True, "persistence_type": "local"}
TABLE_STYLE = dict(
    style_table={"width": "100%", "overflowX": "auto"},
    style_header={"backgroundColor": "#1a1a2e", "color": "white", "fontWeight": "bold"},
    style_cell={"backgroundColor": "#16162a", "color": "white", "border": "1px solid #333",
                "padding": "8px", "textAlign": "left", "whiteSpace": "normal"},
    style_as_list_view=True,
)


def local_time(stamp, tz=None):
    """A UTC timestamp from the API (…Z or …+00:00) in the browser's time
    zone (tz: an IANA name such as "Pacific/Auckland", read in the browser
    by app.py), e.g. "2026-10-09 10:30". UTC when tz is unknown."""
    if not stamp:
        return ""
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(tz) if tz else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return when.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _seconds_since(stamp, now=None):
    try:
        start = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, ((now or datetime.now(timezone.utc)) - start).total_seconds())


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


def running_for(job, now=None):
    """How long a running job's run has been going ("12m 5s"), or ""."""
    if job.get("state") not in ("running", "publishing") or not (job.get("run_started") or job.get("started")):
        return ""
    return _format_duration(_seconds_since(job.get("run_started") or job.get("started"), now))


def job_row(job, tz=None, now=None):
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
        "submitted": local_time(job.get("submitted"), tz),
        "task": job.get("task") or "",
        "mode": what,
        "state": state,
        "run": job.get("run") or "",
        "duration": (f"{running_for(job, now)} so far" if running_for(job, now)
                     else _format_duration(metrics.get("duration_seconds"))),
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


def job_detail(job, tz=None):
    if not job:
        return [html.P("Click a run above to see its log, results and metrics.", className="text-muted")]
    row = job_row(job, tz)
    title = f"{row['task']} · {row['mode']}" if row["task"] != "resume" else f"resume {row['run']}"
    meta = [html.Strong("State: "), row["state"]]
    for label, key in (("Run", "run"), ("Note", "note"), ("By", "submitted_by"),
                       ("Submitted", "submitted"), ("Finished", "finished")):
        if job.get(key):
            value = local_time(job[key], tz) if key in ("submitted", "finished") else str(job[key])
            meta += ["  ·  ", html.Strong(f"{label}: "), value]
    children = [html.H4(title, className="card-title"), html.P(meta, className="text-muted")]
    if running_for(job):
        children.append(html.P([
            html.Strong(f"Running for {running_for(job)}"),
            f" (since {local_time(job.get('run_started') or job.get('started'), tz)}). ",
            html.Span("The log gets a line when an answer comes back, so with long answers it can sit still "
                      "for many minutes while the model is still working.", className="text-muted"),
        ], className="small"))
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


def can_delete(job):
    return bool(job) and job.get("state") not in LIVE_STATES


def delete_plan(jobs, ids):
    """The ticked jobs split into (to delete, still going so left alone)."""
    ticked = [j for j in jobs or [] if j.get("id") in set(ids or [])]
    return [j for j in ticked if can_delete(j)], [j for j in ticked if not can_delete(j)]


def delete_message(doomed, skipped):
    """The confirm dialog's text for deleting the ticked runs."""
    names = [j.get("run") or f"{j.get('task') or '?'} job (never started a run)" for j in doomed]
    shown = "\n".join(f"  • {n}" for n in names[:12]) + (f"\n  … and {len(names) - 12} more" if len(names) > 12 else "")
    text = f"Delete {len(doomed)} run{'s' if len(doomed) != 1 else ''} for good?\n\n{shown}\n\n"
    if skipped:
        text += f"{len(skipped)} ticked run{'s are' if len(skipped) != 1 else ' is'} still going and won't be deleted.\n\n"
    return text + ("For each run this removes its results on ai-services-stack, its report folder in Nextcloud, "
                   "its rows in the results table and Compare, and every entry for it here (resumes included). "
                   "The leaderboard is republished without them. This can't be undone.")


def selected_index(rows, job_ids):
    """The table rows to keep ticked after a refresh: new runs are added at
    the top, so the same row numbers would point at different runs."""
    wanted = set(job_ids or [])
    return [i for i, row in enumerate(rows) if row.get("id") in wanted]


def viewed_style(job_id):
    """Highlight the run whose results are shown below the list."""
    rules = [{"if": {"state": "active"}, "backgroundColor": "#2a2a4a", "border": "1px solid #333"}]
    if job_id:
        rules.append({"if": {"filter_query": f'{{id}} = "{job_id}"'}, "backgroundColor": "#2a2a4a"})
    return rules


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
        dbc.Col(dbc.Switch(id={"type": "eval-on", "task": task}, value=False, **PERSIST,
                           label=html.Span([html.Strong(spec["name"]), html.Br(),
                                            html.Span(TASKS[task].split(": ", 1)[1], className="text-muted small")])),
                md=5),
        dbc.Col([
            html.Div([
                # Choose last, so its number box sits right after it.
                # Labels show what actually runs (RepoBench: all levels).
                dbc.RadioItems(
                    id={"type": "eval-size", "task": task}, value="pilot", inline=True, **PERSIST,
                    options=[{"label": f"Pilot ({spec['pilot'] * per_level:,})", "value": "pilot"},
                             {"label": f"Full ({spec['max'] * per_level:,})", "value": "full"},
                             {"label": "Choose" + (" per level" if per_level > 1 else ""), "value": "count"}],
                    className="me-1",
                ),
                dbc.Input(id={"type": "eval-count", "task": task}, type="number", min=1, max=spec["max"], step=1,
                          **PERSIST,
                          value=min(50, spec["max"]), size="sm", style={"maxWidth": "90px"}),
            ], className="d-flex align-items-center flex-wrap"),
            html.Div(id={"type": "eval-hint", "task": task}, className="text-muted small mt-1"),
        ], md=7),
    ])


run_section = dbc.Card(dbc.CardBody([
    html.H4("Start a run", className="card-title mb-1"),
    html.P("Switch on each benchmark to run, and choose how much of it.", className="text-muted small"),
    html.Div([benchmark_row(task) for task in TASKS], className="mb-3"),
    dbc.Switch(id="eval-budget", label="32k token budget (applies to GPQA and IFEval)", value=False, **PERSIST,
               className="mb-2"),
    dbc.Input(id="eval-note", placeholder="Note (one line, e.g. reasoning_effort=high)", maxLength=200, **PERSIST,
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
        html.Div([
            html.Span("Click a run to see its results below. Tick runs to delete them.",
                      className="text-muted small me-auto"),
            dbc.Button("Select all finished", id="eval-select-all", color="secondary", size="sm", outline=True,
                       className="me-2"),
            dbc.Button("Clear", id="eval-select-none", color="secondary", size="sm", outline=True,
                       className="me-2"),
            dbc.Button("Delete selected", id="eval-delete-btn", color="danger", size="sm", disabled=True),
        ], className="d-flex align-items-center mb-2"),
        dcc.ConfirmDialog(id="eval-delete-confirm"),
        dash_table.DataTable(
            id="eval-jobs-table",
            columns=[
                {"name": "Submitted", "id": "submitted"},
                {"name": "Benchmark", "id": "task"},
                {"name": "Size", "id": "mode"},
                {"name": "State", "id": "state"},
                {"name": "Duration", "id": "duration"},
                {"name": "Tokens", "id": "tokens"},
                {"name": "Tokens/s", "id": "tokens_per_second"},
            ],
            # Ten to a page, so the clicked run's results below stay in view.
            data=[], row_selectable="multi", selected_rows=[], page_size=10,
            style_data_conditional=viewed_style(None),
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
        dcc.Store(id="eval-selected"),  # the run whose results are shown
        dcc.Store(id="eval-checked"),   # the ticked runs
        html.Div(run_section, id="eval-run-section"),
        html.Div(runs_section, id="eval-runs-section"),
    ])


def _post(path, json=None):
    return _request("POST", path, json)


def _request(method, path, json=None):
    headers = {"X-Authentik-Username": request.headers.get("X-Authentik-Username", "unknown")}
    resp = requests.request(method, f"{PANEL_API_BASE_URL}{path}", json=json, headers=headers, timeout=10)
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
    Output("eval-jobs-table", "selected_rows"),
    Input("eval-poll", "n_intervals"),
    State("eval-checked", "data"),
    State("browser-tz", "data"),
)
def poll(_n, checked=None, tz=None):
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
    rows = [job_row(j, tz) for j in jobs]
    return jobs, rows, links, selected_index(rows, checked)


@callback(
    Output("eval-selected", "data"),
    Input("eval-jobs-table", "active_cell"),
    prevent_initial_call=True,
)
def select(active_cell):
    """Clicking a run shows its results (ticking it doesn't)."""
    if not active_cell or not active_cell.get("row_id"):
        raise PreventUpdate
    return active_cell["row_id"]


@callback(
    Output("eval-checked", "data"),
    Output("eval-delete-btn", "children"),
    Output("eval-delete-btn", "disabled"),
    Input("eval-jobs-table", "selected_rows"),
    State("eval-jobs-table", "data"),
)
def tick(selected_rows, rows):
    ids = [rows[i]["id"] for i in selected_rows or [] if rows and i < len(rows)]
    return ids, f"Delete selected ({len(ids)})" if ids else "Delete selected", not ids


@callback(
    Output("eval-jobs-table", "selected_rows", allow_duplicate=True),
    Input("eval-select-all", "n_clicks"),
    Input("eval-select-none", "n_clicks"),
    State("eval-jobs", "data"),
    prevent_initial_call=True,
)
def tick_many(_all, _none, jobs):
    if ctx.triggered_id == "eval-select-none":
        return []
    return [i for i, job in enumerate(jobs or []) if can_delete(job)]


@callback(
    Output("eval-detail", "children"),
    Output("eval-cancel-btn", "style"),
    Output("eval-resume-btn", "style"),
    Output("eval-samples-card", "style"),
    Output("eval-jobs-table", "style_data_conditional"),
    Input("eval-selected", "data"),
    Input("eval-jobs", "data"),
    State("browser-tz", "data"),
)
def detail(job_id, jobs, tz=None):
    job = next((j for j in jobs or [] if j.get("id") == job_id), None) if job_id else None
    hidden = {"display": "none"}
    return (job_detail(job, tz), ({} if can_cancel(job) else hidden), ({} if can_resume(job) else hidden),
            ({} if job and job.get("run") else hidden), viewed_style(job and job_id))


@callback(
    Output("eval-delete-confirm", "displayed"),
    Output("eval-delete-confirm", "message"),
    Input("eval-delete-btn", "n_clicks"),
    State("eval-checked", "data"),
    State("eval-jobs", "data"),
    prevent_initial_call=True,
)
def confirm_delete(clicks, checked, jobs):
    doomed, skipped = delete_plan(jobs, checked)
    if not clicks or not doomed:
        raise PreventUpdate
    return True, delete_message(doomed, skipped)


def delete_jobs(job_ids):
    """DELETE each job; a 404 means an earlier delete already took it (a
    resume goes with its run). Returns (deleted runs, removed, errors)."""
    runs, removed, errors = [], 0, []
    for job_id in job_ids:
        try:
            status, data = _request("DELETE", f"/eval/api/jobs/{job_id}")
        except requests.RequestException as exc:
            errors.append(str(exc))
            continue
        if status == 404:
            continue
        if status != 200:
            errors.append(str(data.get("detail")))
        elif data.get("run"):
            runs.append(data["run"])
        else:
            removed += 1
    return runs, removed, errors


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
    Input("eval-delete-confirm", "submit_n_clicks"),
    State("eval-selected", "data"),
    State("eval-checked", "data"),
    State("eval-jobs", "data"),
    prevent_initial_call=True,
)
def act(cancel_clicks, resume_clicks, publish_clicks, delete_clicks, job_id, checked=None, jobs=None):
    trigger = ctx.triggered_id
    clicks = {"eval-cancel-btn": cancel_clicks, "eval-resume-btn": resume_clicks,
              "eval-publish-btn": publish_clicks, "eval-delete-confirm": delete_clicks}.get(trigger)
    if not clicks:
        return no_update, no_update, no_update
    if trigger == "eval-delete-confirm":
        doomed, _ = delete_plan(jobs, checked)
        runs, removed, errors = delete_jobs([j["id"] for j in doomed])
        done = []
        if runs:
            done.append(f"Deleted {len(runs)} run{'s' if len(runs) != 1 else ''}")
        if removed:
            done.append(f"removed {removed} job{'s' if removed != 1 else ''} that never ran")
        text = (", ".join(done) or "Nothing deleted") + "."
        if runs:
            text += " Nextcloud and the results table catch up in a minute or so."
        if errors:
            return f"{text} Failed: {'; '.join(errors)}", "danger", True
        return text, "success", True
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
