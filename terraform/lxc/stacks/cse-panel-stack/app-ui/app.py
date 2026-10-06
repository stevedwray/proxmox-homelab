#!/usr/bin/env python3
"""panel-ui: Dash front end for cse-panel-stack, calling panel-web's
existing FastAPI JSON API. Phase 0 scaffold -- proves the full
Traefik -> panel-ui -> panel-web auth-header path works before any
real UI is ported. See docs/cse-panel-dash-migration/plan.md.
"""
import os

import dash
import dash_bootstrap_components as dbc
import requests
from dash import Input, Output, State, dash_table, dcc, html
from dash.exceptions import PreventUpdate
from flask import request

PANEL_API_BASE_URL = os.environ.get("PANEL_API_BASE_URL", "http://panel-web:8000")

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
app.title = "CyberSecEval Control Panel"

app.layout = dbc.Container(
    fluid=True,
    style={"padding": "32px", "maxWidth": "700px"},
    children=[
        html.H1("CyberSecEval — panel-ui scaffold"),
        dbc.Card(dbc.CardBody([
            html.P(id="whoami"),
            html.P(id="api-health"),
        ])),

        dbc.Card(className="mt-4", children=dbc.CardBody([
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
        ])),

        dbc.Card(className="mt-4", children=dbc.CardBody([
            html.H4("Recent runs", className="card-title mb-3"),
            dash_table.DataTable(
                id="jobs-table",
                columns=[
                    {"name": "Job ID", "id": "job_id"},
                    {"name": "Benchmark", "id": "benchmark"},
                    {"name": "Backend", "id": "backend"},
                    {"name": "Submitted by", "id": "submitted_by"},
                    {"name": "Submitted at", "id": "submitted_at"},
                    {"name": "State", "id": "state_label"},
                    {"name": "Summary", "id": "summary"},
                ],
                data=[],
                style_table={"width": "100%", "overflowX": "auto"},
                style_header={"backgroundColor": "#1a1a2e", "color": "white", "fontWeight": "bold"},
                style_cell={"backgroundColor": "#16162a", "color": "white", "border": "1px solid #333",
                            "padding": "8px", "textAlign": "left", "whiteSpace": "normal"},
                style_as_list_view=True,
            ),
            dcc.Interval(id="poll-interval", interval=4000, n_intervals=0),
            dbc.Row(className="mt-3", children=[
                dbc.Col(dbc.Input(id="delete-job-id", placeholder="job_id to delete"), width=8),
                dbc.Col(dbc.Button("Delete job", id="delete-btn", color="danger", className="w-100"), width=4),
            ]),
            dbc.Alert(id="delete-result", is_open=False, className="mt-3"),
        ])),
    ],
)


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


def _job_row_summary(job):
    if job.get("state") == "FAILURE" and job.get("error"):
        return str(job["error"])
    stats_summary = job.get("stats_summary") or []
    return "; ".join(f"{k}: {v}" for k, v in stats_summary)


@app.callback(
    Output("jobs-table", "data"),
    Input("poll-interval", "n_intervals"),
)
def poll_jobs(_n):
    try:
        resp = requests.get(f"{PANEL_API_BASE_URL}/jobs", timeout=10)
        jobs = resp.json().get("jobs", [])
    except requests.RequestException:
        raise PreventUpdate

    rows = []
    for job in jobs:
        row = dict(job)
        row["summary"] = _job_row_summary(job)
        rows.append(row)
    return rows


@app.callback(
    Output("delete-result", "children"),
    Output("delete-result", "color"),
    Output("delete-result", "is_open"),
    Input("delete-btn", "n_clicks"),
    State("delete-job-id", "value"),
    prevent_initial_call=True,
)
def delete_job(n_clicks, job_id):
    if not job_id:
        raise PreventUpdate

    try:
        resp = requests.delete(f"{PANEL_API_BASE_URL}/jobs/{job_id}", timeout=10)
        data = resp.json()
        if data.get("in_progress"):
            resp = requests.delete(f"{PANEL_API_BASE_URL}/jobs/{job_id}", params={"force": "true"}, timeout=10)
            data = resp.json()
    except requests.RequestException as exc:
        return f"Delete failed: {exc}", "danger", True

    if "error" in data:
        return f"Delete failed: {data['error']}", "danger", True
    return f"Deleted: {data['deleted']}", "success", True


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
