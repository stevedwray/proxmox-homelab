#!/usr/bin/env python3
"""panel-ui: Dash front end for cse-panel-stack, calling panel-web's
existing FastAPI JSON API. See docs/cse-panel-dash-migration/plan.md.

Since 2026-10-08 (docs/benchmark-panel/plan.md, phase 3) it is the one
benchmark panel: a shared header (who is logged in, what Framework is
doing) above one tab per benchmark family, each with its own Run /
Results switch. CyberSecEval lives here; the Eval battery is eval_tab.py.
"""
import os

import dash
import dash_bootstrap_components as dbc
import requests
from plotly.subplots import make_subplots
from dash import Input, Output, State, ctx, dash_table, dcc, html
from dash.exceptions import PreventUpdate
from flask import request

import compare_tab
import eval_tab

PANEL_API_BASE_URL = os.environ.get("PANEL_API_BASE_URL", "http://panel-web:8000")
LAB_DOMAIN = os.environ.get("LAB_DOMAIN", "")
LLM_CONTROL_URL = f"https://llm-control.{LAB_DOMAIN}" if LAB_DOMAIN else "#"

# Duplicated verbatim from app/app.py (panel-web's own FastAPI app) --
# panel-ui has no import path to that module, this is a deliberate
# duplication, not a shared import. Keep in sync by hand if panel-web's
# list changes. See docs/cse-panel-dash-migration/plan.md panel-dash-07.
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

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
server = app.server
app.title = "Benchmark Control Panel"

run_tab = dbc.Card(dbc.CardBody([
    html.H4("Submit a run", className="card-title mb-3"),
    dbc.Checklist(
        id="benchmarks",
        switch=True,
        inline=False,
        options=[
            {"label": f"{b} — {BENCHMARK_INFO[b]['description']}", "value": b}
            for b in KNOWN_BENCHMARKS
        ],
        value=[],
        className="mb-3",
    ),
    dbc.Label("Test cases"),
    dcc.Slider(
        id="num-test-cases",
        min=1, max=50, step=1, value=2,
        tooltip={"placement": "bottom", "always_visible": True},
    ),
    dbc.Button("Submit run(s)", id="submit-btn", color="primary", className="mt-3"),
    dbc.Alert(id="submit-result", is_open=False, className="mt-3"),
]))

results_tab = html.Div([
    dbc.Card(className="mt-3", children=dbc.CardBody([
        html.H4("Recent runs", className="card-title mb-3"),
        html.Div([
            html.Span("Click a run to see its results below. Tick runs to delete them.",
                      className="text-muted small me-auto"),
            dbc.Button("Select all finished", id="cse-select-all", color="secondary", size="sm", outline=True,
                       className="me-2"),
            dbc.Button("Clear", id="cse-select-none", color="secondary", size="sm", outline=True,
                       className="me-2"),
            dbc.Button("Delete selected", id="cse-delete-btn", color="danger", size="sm", disabled=True),
        ], className="d-flex align-items-center mb-2"),
        dcc.ConfirmDialog(id="cse-delete-confirm"),
        dash_table.DataTable(
            id="jobs-table",
            columns=[
                {"name": "Job ID", "id": "job_id"},
                {"name": "Benchmark", "id": "benchmark"},
                {"name": "Model", "id": "model"},
                {"name": "Backend", "id": "backend"},
                {"name": "Submitted by", "id": "submitted_by"},
                {"name": "Submitted at", "id": "submitted_at"},
                {"name": "State", "id": "state_label"},
                {"name": "Duration", "id": "duration"},
                {"name": "Tokens", "id": "tokens"},
                {"name": "Tokens/s", "id": "tokens_per_second"},
            ],
            data=[],
            row_selectable="multi",
            selected_rows=[],
            # Ten to a page, so the clicked run's results below stay in view.
            page_size=10,
            style_data_conditional=eval_tab.viewed_style(None),
            style_table={"width": "100%", "overflowX": "auto"},
            style_header={"backgroundColor": "#1a1a2e", "color": "white", "fontWeight": "bold"},
            style_cell={"backgroundColor": "#16162a", "color": "white", "border": "1px solid #333",
                        "padding": "8px", "textAlign": "left", "whiteSpace": "normal"},
            style_as_list_view=True,
        ),
        dcc.Interval(id="poll-interval", interval=4000, n_intervals=0),
        dcc.Store(id="cse-selected"),  # the run whose results are shown
        dcc.Store(id="cse-checked"),   # the ticked runs
        dbc.Alert(id="delete-result", is_open=False, className="mt-3"),
    ])),
    dbc.Card(className="mt-3", children=dbc.CardBody(id="run-detail", children=[
        html.P("Click a run above to see its results.", className="text-muted"),
    ])),

    dbc.Card(className="mt-3", children=dbc.CardBody([
        html.H4("Results by benchmark", className="card-title mb-1"),
        html.P("Each run's headline number, one panel per benchmark. Hover a bar for its sample size. "
               "Runs from before 2026-10-08 have no headline recorded.", className="text-muted small"),
        dcc.Graph(id="results-chart", config={"displaylogo": False}),
    ])),
    dbc.Card(className="mt-3", children=dbc.CardBody([
        html.H4("Speed and duration", className="card-title mb-3"),
        dcc.Graph(id="speed-chart", config={"displaylogo": False}),
    ])),
])



def section_switch(switch_id):
    """The Run / Results switch inside a benchmark family's tab: a
    Bootstrap button group (dbc's RadioItems-as-buttons pattern)."""
    return html.Div(dbc.RadioItems(
        id=switch_id, value="run",
        options=[{"label": "Run", "value": "run"}, {"label": "Results", "value": "results"}],
        className="btn-group", inputClassName="btn-check",
        labelClassName="btn btn-outline-primary", labelCheckedClassName="active",
    ), className="radio-group my-3")


# Every section stays in the layout and is shown or hidden, so each one's
# polling keeps running and nothing re-mounts when you switch.
cse_family = html.Div([
    section_switch("cse-section"),
    html.Div(run_tab, id="cse-run-section"),
    html.Div(results_tab, id="cse-results-section"),
])
eval_family = html.Div([
    section_switch("eval-section"),
    eval_tab.layout(),
])

app.layout = dbc.Container(
    fluid=True,
    style={"padding": "32px", "maxWidth": "1000px"},
    children=[
        html.Div([
            html.H1("Benchmark Control Panel", className="mb-0 me-auto"),
            html.Div([html.Div(id="whoami"), html.Div(id="api-health", className="text-muted")],
                     className="small text-end"),
        ], className="d-flex align-items-end mb-3"),
        # Who holds Framework (the benchmark lock shared by both families)
        # and which model it serves; above the tabs so it shows on all.
        dbc.Alert(id="framework-status", color="secondary", className="py-2 mb-2"),
        html.P(["Models load from ", html.A("llm-control", href=LLM_CONTROL_URL, target="_blank",
                                            rel="noopener"), "."], className="text-muted small"),
        dcc.Interval(id="framework-interval", interval=10000, n_intervals=0),
        dcc.Store(id="jobs-store"),
        dbc.Tabs(id="family", active_tab="cse", className="mt-3", children=[
            dbc.Tab(cse_family, tab_id="cse", label="CyberSecEval",
                    label_style={"fontSize": "1.15rem"}),
            dbc.Tab(eval_family, tab_id="eval", label="Eval battery",
                    label_style={"fontSize": "1.15rem"}),
            dbc.Tab(compare_tab.layout(), tab_id="compare", label="Compare",
                    label_style={"fontSize": "1.15rem"}),
        ]),
    ],
)


def _shown(visible):
    return {} if visible else {"display": "none"}


@app.callback(
    Output("cse-run-section", "style"),
    Output("cse-results-section", "style"),
    Input("cse-section", "value"),
)
def switch_cse(section):
    return _shown(section == "run"), _shown(section == "results")


@app.callback(
    Output("eval-run-section", "style"),
    Output("eval-runs-section", "style"),
    Input("eval-section", "value"),
)
def switch_eval(section):
    return _shown(section == "run"), _shown(section == "results")


def framework_status_text(info: dict) -> str:
    model = info.get("model") or "no model loaded"
    lock = info.get("lock")
    if lock:
        who = f"{lock.get('suite') or '?'} {lock.get('benchmark') or ''}".strip()
        since = f" since {lock['started']}" if lock.get("started") else ""
        return f"Framework: {model} · busy with {who} (job {lock.get('job_id')}{since}); new benchmark runs wait"
    if info.get("error") and not info.get("model"):
        return f"Framework: unreachable ({info['error']})"
    return f"Framework: {model} · free"


def builds_text(builds: dict | None) -> str:
    """One line on Framework's llama.cpp builds (llama-builds status)."""
    if not builds or not builds.get("backends"):
        return "llama.cpp builds: no status yet (llama-builds publishes it daily)"
    parts = []
    for name, b in builds["backends"].items():
        cur = b.get("current") or {}
        if not cur.get("name"):
            parts.append(f"{name} not built")
            continue
        behind = cur.get("behind")
        lag = "up to date" if behind == 0 else (f"{behind} behind" if behind is not None else "? behind")
        cand = (b.get("candidate") or {}).get("name")
        extra = f", candidate {cand}" if cand and cand != cur.get("name") else ""
        parts.append(f"{name} {cur['name']} ({lag}{extra})")
    return f"llama.cpp builds: {' · '.join(parts)} · checked {(builds.get('checked') or '?')[:16].replace('T', ' ')}"


def framework_status_color(info: dict) -> str:
    if info.get("lock"):
        return "warning"
    if info.get("error") and not info.get("model"):
        return "danger"
    return "secondary"


@app.callback(
    Output("framework-status", "children"),
    Output("framework-status", "color"),
    Input("framework-interval", "n_intervals"),
)
def poll_framework(_n):
    try:
        info = requests.get(f"{PANEL_API_BASE_URL}/framework", timeout=5).json()
    except (requests.RequestException, ValueError):
        return "Framework: status unavailable (panel-web unreachable)", "danger"
    return [framework_status_text(info), html.Br(),
            html.Small(builds_text(info.get("builds")), className="text-muted")], framework_status_color(info)


@app.callback(
    Output("whoami", "children"),
    Output("api-health", "children"),
    Input("whoami", "id"),
)
def load_identity(_):
    username = request.headers.get("X-Authentik-Username", "(no X-Authentik-Username header seen)")
    try:
        resp = requests.get(f"{PANEL_API_BASE_URL}/healthz", timeout=5)
        health = f"panel-web /healthz: {resp.status_code} {resp.text}"
    except requests.RequestException as exc:
        health = f"panel-web /healthz: ERROR {exc}"
    return f"Logged in as: {username}", health


@app.callback(
    Output("submit-result", "children"),
    Output("submit-result", "color"),
    Output("submit-result", "is_open"),
    Input("submit-btn", "n_clicks"),
    State("benchmarks", "value"),
    State("num-test-cases", "value"),
    prevent_initial_call=True,
)
def submit_run(n_clicks, benchmarks, num_test_cases):
    if not benchmarks:
        raise PreventUpdate

    username = request.headers.get("X-Authentik-Username", "unknown")
    headers = {"X-Authentik-Username": username}

    try:
        if len(benchmarks) == 1:
            resp = requests.post(
                f"{PANEL_API_BASE_URL}/jobs",
                params={"benchmark": benchmarks[0], "num_test_cases": num_test_cases},
                headers=headers,
                timeout=10,
            )
        else:
            resp = requests.post(
                f"{PANEL_API_BASE_URL}/suites",
                json={"tests": [
                    {"benchmark": b, "num_test_cases": num_test_cases} for b in benchmarks
                ]},
                headers=headers,
                timeout=10,
            )
    except requests.RequestException as exc:
        return f"Submit failed: {exc}", "danger", True

    data = resp.json()
    if "error" in data:
        return f"Submit failed: {data['error']}", "danger", True
    if "suite_id" in data:
        return f"Suite submitted: {data['suite_id']} ({len(data['jobs'])} jobs)", "success", True
    return f"Job submitted: {data['job_id']} ({data['benchmark']})", "success", True


def _format_duration(seconds):
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _metric_columns(job):
    """Duration / Tokens / Tokens/s for the runs table, from the run_metrics
    cse_tasks.py records (model under test only; blank for older runs)."""
    metrics = job.get("run_metrics") or {}
    mut = metrics.get("model_under_test") or {}
    return {
        "duration": _format_duration(metrics.get("duration_seconds")),
        "tokens": f"{mut['completion_tokens']:,}" if "completion_tokens" in mut else "",
        "tokens_per_second": mut.get("generation_tokens_per_second", ""),
    }


# Same rows as cse_tasks.py's report.md "Run metrics" table.
_METRIC_ROWS = [
    ("Model calls", "calls", "{:,}"),
    ("Prompt tokens", "prompt_tokens", "{:,}"),
    ("Generated tokens (incl. reasoning)", "completion_tokens", "{:,}"),
    ("Longest single answer (tokens)", "max_completion_tokens", "{:,}"),
    ("Answers cut off at the token limit", "hit_token_limit", "{:,}"),
    ("Generation speed (tokens/s)", "generation_tokens_per_second", "{}"),
    ("Prompt processing (tokens/s)", "prompt_tokens_per_second", "{}"),
    ("Time in model calls", "request_seconds", None),
]


def _run_metrics_block(metrics):
    if not metrics:
        return [html.H5("Run metrics", className="mt-4"),
                html.P("Not recorded for this run.", className="text-muted")]
    block = [
        html.H5("Run metrics", className="mt-4"),
        html.P([html.Strong("Duration: "), _format_duration(metrics.get("duration_seconds")) or "–"]),
    ]
    groups = [(key, label) for key, label in (
        ("model_under_test", "Model under test"),
        ("judge", "Judge / expansion (cloud)"),
    ) if metrics.get(key)]
    if not groups:
        return block + [html.P("No model calls were recorded.", className="text-muted")]
    body = []
    for label, key, fmt in _METRIC_ROWS:
        cells = []
        for group_key, _ in groups:
            value = metrics[group_key].get(key)
            if value is None:
                cells.append("–")
            elif fmt is None:
                cells.append(_format_duration(value))
            else:
                cells.append(fmt.format(value))
        body.append(html.Tr([html.Td(label)] + [html.Td(c) for c in cells]))
    table = dbc.Table(
        [html.Thead(html.Tr([html.Th("")] + [html.Th(label) for _, label in groups])), html.Tbody(body)],
        bordered=True, hover=True, size="sm",
    )
    return block + [table]


MODEL_COLOURS = ["#6f42c1", "#20c997", "#fd7e14", "#0dcaf0", "#d63384", "#ffc107", "#198754", "#adb5bd"]
CHART_LAYOUT = {"template": "plotly_dark", "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"}


def _empty_chart_figure(message):
    return {
        "data": [],
        "layout": {
            **CHART_LAYOUT,
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "annotations": [{
                "text": message, "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5, "showarrow": False,
                "font": {"size": 16, "color": "#888"},
            }],
        },
    }


def _run_label(job):
    """model · MM-DD HH:MM, so runs read as who and when, not job ids."""
    when = (job.get("finished_at") or job.get("submitted_at") or "")[5:16].replace("T", " ")
    return f"{job.get('model') or '?'} · {when}"


def _colours(jobs):
    models = sorted({j.get("model") or "?" for j in jobs})
    return {m: MODEL_COLOURS[i % len(MODEL_COLOURS)] for i, m in enumerate(models)}


def _results_chart_figure(jobs):
    """One panel per benchmark: each finished run's headline, in its own
    units, oldest to newest."""
    scored = [j for j in jobs if j.get("state") == "SUCCESS" and (j.get("headline") or {}).get("value") is not None]
    if not scored:
        return _empty_chart_figure("No scored runs yet (runs record a headline from 2026-10-08).")
    benchmarks = sorted({j["benchmark"] for j in scored})
    titles = []
    for b in benchmarks:
        head = next(j["headline"] for j in scored if j["benchmark"] == b)
        titles.append(f"{b}: {head['metric']} ({head['better']} is better)")
    fig = make_subplots(rows=len(benchmarks), cols=1, subplot_titles=titles, vertical_spacing=0.32 / len(benchmarks))
    colours = _colours(scored)
    for row, b in enumerate(benchmarks, 1):
        runs = sorted((j for j in scored if j["benchmark"] == b), key=lambda j: j.get("finished_at") or "")
        fig.add_bar(
            row=row, col=1, x=[_run_label(j) for j in runs], y=[j["headline"]["value"] for j in runs],
            marker_color=[colours[j.get("model") or "?"] for j in runs], showlegend=False,
            text=[f"{j['headline']['value']:.1f}%" for j in runs], textposition="auto",
            customdata=[[j["headline"].get("n"), j["job_id"][:8]] for j in runs],
            hovertemplate="%{x}<br>%{y:.1f}% of %{customdata[0]} cases<br>job %{customdata[1]}<extra></extra>",
        )
        fig.update_yaxes(range=[0, 100], ticksuffix="%", row=row, col=1)
    fig.update_layout(**CHART_LAYOUT, height=max(260, 230 * len(benchmarks)), margin={"t": 40, "b": 20})
    return fig


def _speed_chart_figure(jobs):
    """Generation speed and duration per finished run."""
    runs = [j for j in jobs if j.get("state") == "SUCCESS" and (j.get("run_metrics") or {}).get("duration_seconds")]
    if not runs:
        return _empty_chart_figure("No run metrics yet.")
    runs = sorted(runs, key=lambda j: j.get("finished_at") or j.get("submitted_at") or "")
    labels = [f"{j['benchmark']} · {_run_label(j)}" for j in runs]
    colours = _colours(runs)
    fig = make_subplots(rows=1, cols=2, subplot_titles=["Generation speed (tokens/s)", "Duration (minutes)"])
    fig.add_bar(row=1, col=1, x=labels, showlegend=False, marker_color=[colours[j.get("model") or "?"] for j in runs],
                y=[((j["run_metrics"].get("model_under_test") or {}).get("generation_tokens_per_second")) for j in runs],
                hovertemplate="%{x}<br>%{y} tokens/s<extra></extra>")
    fig.add_bar(row=1, col=2, x=labels, showlegend=False, marker_color=[colours[j.get("model") or "?"] for j in runs],
                y=[round(j["run_metrics"]["duration_seconds"] / 60, 1) for j in runs],
                hovertemplate="%{x}<br>%{y} min<extra></extra>")
    fig.update_xaxes(showticklabels=False)
    fig.update_layout(**CHART_LAYOUT, height=300, margin={"t": 40, "b": 20})
    return fig


@app.callback(
    Output("jobs-table", "data"),
    Output("results-chart", "figure"),
    Output("speed-chart", "figure"),
    Output("jobs-table", "selected_rows"),
    Input("poll-interval", "n_intervals"),
    State("cse-checked", "data"),
)
def poll_jobs(_n, checked=None):
    try:
        resp = requests.get(f"{PANEL_API_BASE_URL}/jobs", timeout=10)
        jobs = resp.json().get("jobs", [])
    except requests.RequestException:
        raise PreventUpdate
    rows = [{**job, **_metric_columns(job), "id": job["job_id"]} for job in jobs]
    # New runs are added at the top, so keep the ticks on the same runs,
    # not the same row numbers.
    keep = eval_tab.selected_index(rows, checked)
    return rows, _results_chart_figure(rows), _speed_chart_figure(rows), keep


@app.callback(
    Output("cse-selected", "data"),
    Input("jobs-table", "active_cell"),
    prevent_initial_call=True,
)
def select_job(active_cell):
    """Clicking a run shows its results (ticking it doesn't)."""
    if not active_cell or not active_cell.get("row_id"):
        raise PreventUpdate
    return active_cell["row_id"]


@app.callback(
    Output("cse-checked", "data"),
    Output("cse-delete-btn", "children"),
    Output("cse-delete-btn", "disabled"),
    Input("jobs-table", "selected_rows"),
    State("jobs-table", "data"),
)
def tick_jobs(selected_rows, rows):
    ids = [rows[i]["job_id"] for i in selected_rows or [] if rows and i < len(rows)]
    return ids, f"Delete selected ({len(ids)})" if ids else "Delete selected", not ids


CSE_UNFINISHED = ("PENDING", "WAITING", "STARTED", "RETRY")


@app.callback(
    Output("jobs-table", "selected_rows", allow_duplicate=True),
    Input("cse-select-all", "n_clicks"),
    Input("cse-select-none", "n_clicks"),
    State("jobs-table", "data"),
    prevent_initial_call=True,
)
def tick_many_jobs(_all, _none, rows):
    if ctx.triggered_id == "cse-select-none":
        return []
    return [i for i, row in enumerate(rows or []) if row.get("state") not in CSE_UNFINISHED]


def cse_delete_message(jobs):
    names = [f"{j.get('benchmark', '?')} {j['job_id'][:8]} ({j.get('state_label') or j.get('state')})" for j in jobs]
    shown = "\n".join(f"  • {n}" for n in names[:12]) + (f"\n  … and {len(names) - 12} more" if len(names) > 12 else "")
    running = sum(j.get("state") in CSE_UNFINISHED for j in jobs)
    return (f"Delete {len(jobs)} run{'s' if len(jobs) != 1 else ''} for good?\n\n{shown}\n\n"
            + (f"{running} of them haven't finished: deleting cancels them first.\n\n" if running else "")
            + "For each run this removes its results on cse-controller, its report folder in Nextcloud and "
              "its row in Compare and the results table. This can't be undone.")


@app.callback(
    Output("cse-delete-confirm", "displayed"),
    Output("cse-delete-confirm", "message"),
    Input("cse-delete-btn", "n_clicks"),
    State("cse-checked", "data"),
    State("jobs-table", "data"),
    prevent_initial_call=True,
)
def confirm_cse_delete(clicks, checked, rows):
    jobs = [r for r in rows or [] if r.get("job_id") in set(checked or [])]
    if not clicks or not jobs:
        raise PreventUpdate
    return True, cse_delete_message(jobs)


def _delete_one(job_id):
    """DELETE a job, cancelling it first if it's unfinished (the dialog said so)."""
    d = requests.delete(f"{PANEL_API_BASE_URL}/jobs/{job_id}", timeout=10).json()
    if d.get("in_progress"):
        d = requests.delete(f"{PANEL_API_BASE_URL}/jobs/{job_id}", params={"force": "true"}, timeout=10).json()
    return d


@app.callback(
    Output("delete-result", "children"),
    Output("delete-result", "color"),
    Output("delete-result", "is_open"),
    Input("cse-delete-confirm", "submit_n_clicks"),
    State("cse-checked", "data"),
    prevent_initial_call=True,
)
def delete_cse_jobs(clicks, checked):
    if not clicks or not checked:
        raise PreventUpdate
    deleted, errors = 0, []
    for job_id in checked:
        try:
            d = _delete_one(job_id)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{job_id[:8]}: {exc}")
            continue
        if "deleted" in d:
            deleted += 1
        else:
            errors.append(f"{job_id[:8]}: {d.get('error', '?')}")
    text = f"Deleted {deleted} run{'s' if deleted != 1 else ''}. Nextcloud and Compare catch up in a minute or so."
    if errors:
        return f"{text} Failed: {'; '.join(errors)}", "danger", True
    return text, "success", True


@app.callback(
    Output("run-detail", "children"),
    Output("jobs-table", "style_data_conditional"),
    Input("cse-selected", "data"),
    Input("jobs-table", "data"),
)
def show_run_detail(job_id, data):
    job = next((r for r in data or [] if r.get("job_id") == job_id), None) if job_id else None
    if not job:
        return ([html.P("Click a run above to see its results.", className="text-muted")],
                eval_tab.viewed_style(None))
    return run_detail(job), eval_tab.viewed_style(job_id)


def run_detail(job):
    header = [
        html.H4(f"{job.get('benchmark', '?')} — {job.get('job_id', '?')}", className="card-title"),
        html.P([
            html.Strong("State: "), job.get("state_label", "?"), "  ·  ",
            html.Strong("Model: "), job.get("model") or "not recorded", "  ·  ",
            html.Strong("Backend: "), job.get("backend", "?"), "  ·  ",
            html.Strong("Submitted by: "), job.get("submitted_by", "?"),
            " at ", job.get("submitted_at", "?"),
        ], className="text-muted"),
    ]

    if job.get("state") == "FAILURE":
        return header + [dbc.Alert(str(job.get("error", "unknown error")), color="danger")]

    stats_summary = job.get("stats_summary") or []
    if not stats_summary:
        if job.get("state") == "SUCCESS":
            return header + [html.P("No benchmark scores.", className="text-muted")] + _run_metrics_block(job.get("run_metrics"))
        return header + [html.P("No results yet.", className="text-muted")]

    rows = [html.Tr([html.Td(k), html.Td(str(v))]) for k, v in stats_summary]
    table = dbc.Table(
        [html.Thead(html.Tr([html.Th("Metric"), html.Th("Value")])), html.Tbody(rows)],
        bordered=True, hover=True, size="sm", className="mt-3",
    )
    return header + [table] + _run_metrics_block(job.get("run_metrics"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
