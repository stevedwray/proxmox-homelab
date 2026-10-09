"""The Compare tab: models against every benchmark's headline score
(phase 4 of docs/benchmark-panel/plan.md, decision 1).

The rows are the ones in the Nextcloud Tables "Model evaluations" table:
eval-runner runs, imported historical runs, and one headline row per
CyberSecEval run. panel-web's GET /compare asks the eval battery's ctl
worker for them (eval_tasks.compare -> publish.compare_rows).
"""
import os
import statistics

import dash_bootstrap_components as dbc
import requests
from dash import Input, Output, callback, dash_table, dcc, html
from dash.exceptions import PreventUpdate

PANEL_API_BASE_URL = os.environ.get("PANEL_API_BASE_URL", "http://panel-web:8000")
# Eval battery columns first, in the leaderboard's order; CyberSecEval after.
EVAL_TASKS = ["GPQA diamond", "IFEval", "BFCL simple", "AgentBench os-std", "RepoBench (rebuilt)"]
CSE_PREFIX = "CyberSecEval "
# CyberSecEval headlines where a higher number is better; the rest are
# "lower is safer" (cse_tasks._headline).
CSE_HIGHER_IS_BETTER = ("malware_analysis", "threat_intel_reasoning")


def _is_cse(row):
    return (row.get("Task") or "").startswith(CSE_PREFIX)


def _rank(row):
    """Which result a cell shows: a comparable full run first, then the
    bigger sample, then the newer run."""
    return (row.get("Comparable") == "yes", row.get("Questions") or 0, row.get("Date") or "")


def best_cells(rows, full_only=True):
    """{(model, task): row} with one result per model and benchmark."""
    cells = {}
    for row in rows:
        if row.get("Score %") is None or not row.get("Model"):
            continue
        if full_only and not _is_cse(row) and row.get("Comparable") != "yes":
            continue
        key = (row["Model"], row["Task"])
        if key not in cells or _rank(row) > _rank(cells[key]):
            cells[key] = row
    return cells


def task_order(cells):
    tasks = {task for _, task in cells}
    return [t for t in EVAL_TASKS if t in tasks] + sorted(t for t in tasks if t.startswith(CSE_PREFIX)) + \
        sorted(t for t in tasks if t not in EVAL_TASKS and not t.startswith(CSE_PREFIX))


def column_name(task):
    if task.startswith(CSE_PREFIX):
        bench = task[len(CSE_PREFIX):]
        return f"{bench} {'↑' if bench in CSE_HIGHER_IS_BETTER else '↓'}"
    return f"{task} ↑"


def cell_text(row):
    text = f"{row['Score %']:.1f}%"
    if row.get("Questions"):
        text += f" · n={row['Questions']}"
    if not _is_cse(row) and row.get("Comparable") != "yes":
        text += " (not comparable)"
    return text


def cell_tooltip(row):
    parts = [row.get("Metrics") or "", f"{row.get('Date') or '?'} · run {row.get('Run') or '?'}"]
    if row.get("Model name") and row["Model name"] != row.get("Model"):
        parts.append(f"recorded as {row['Model name']}")
    if row.get("Tokens/s"):
        parts.append(f"{row['Tokens/s']} tokens/s")
    if row.get("Note"):
        parts.append(row["Note"])
    return "\n".join(p for p in parts if p)


def compare_table(rows, full_only=True):
    """(columns, data, tooltips) for the DataTable."""
    cells = best_cells(rows, full_only)
    tasks = task_order(cells)
    models = sorted({m for m, _ in cells}, key=str.lower)  # a model's variants sit together
    speeds = {}
    for row in rows:
        if row.get("Tokens/s") and row.get("Model"):
            speeds.setdefault(row["Model"], []).append(row["Tokens/s"])
    columns = [{"name": "Model", "id": "model"}, {"name": "Tokens/s (median)", "id": "speed"}] + \
        [{"name": column_name(t), "id": f"t{i}"} for i, t in enumerate(tasks)]
    data, tooltips = [], []
    for model in models:
        record = {"model": model, "speed": round(statistics.median(speeds[model]), 1) if model in speeds else ""}
        tips = {}
        for i, task in enumerate(tasks):
            row = cells.get((model, task))
            record[f"t{i}"] = cell_text(row) if row else ""
            if row:
                tips[f"t{i}"] = {"value": cell_tooltip(row), "type": "text"}
        data.append(record)
        tooltips.append(tips)
    return columns, data, tooltips


def layout():
    return html.Div(className="mt-3", children=[
        dbc.Card(dbc.CardBody([
            html.Div([
                html.H4("Compare models", className="card-title mb-0 me-auto"),
                dbc.Switch(id="compare-full-only", value=True, className="me-3 mb-0",
                           persistence=True, persistence_type="local",
                           label="Eval battery: comparable full runs only"),
                dbc.Button("Refresh", id="compare-refresh", color="secondary", size="sm", outline=True),
            ], className="d-flex align-items-center flex-wrap mb-2"),
            html.P(["Each cell is that model's best result: a comparable full run if there is one, otherwise "
                    "the biggest sample. ↑ higher is better, ↓ lower is safer. CyberSecEval runs are samples, "
                    "so check n before reading much into a difference. Hover a cell for its metric and run."],
                   className="text-muted small"),
            dcc.Loading(type="dot", children=[
                html.Div(id="compare-status", className="small text-muted mb-2"),
                dash_table.DataTable(
                    id="compare-table", columns=[], data=[], tooltip_data=[], tooltip_duration=None,
                    sort_action="native", fixed_columns={"headers": True, "data": 1},
                    style_table={"overflowX": "auto", "minWidth": "100%"},
                    style_header={"backgroundColor": "#1a1a2e", "color": "white", "fontWeight": "bold",
                                  "whiteSpace": "normal"},
                    style_cell={"backgroundColor": "#16162a", "color": "white", "border": "1px solid #333",
                                "padding": "8px", "textAlign": "left", "minWidth": "110px"},
                ),
            ]),
            dcc.Store(id="compare-rows"),
        ])),
    ])


@callback(
    Output("compare-rows", "data"),
    Output("compare-status", "children"),
    Input("compare-refresh", "n_clicks"),
    Input("family", "active_tab"),
)
def load_rows(_n, tab):
    if tab != "compare":
        raise PreventUpdate
    try:
        resp = requests.get(f"{PANEL_API_BASE_URL}/compare", timeout=70)
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return None, f"Couldn't load results: {exc}"
    if resp.status_code != 200:
        return None, f"Couldn't load results: {body.get('detail')}"
    rows = body.get("rows") or []
    return rows, f"{len(rows)} results, read {body.get('at', '')}"


@callback(
    Output("compare-table", "columns"),
    Output("compare-table", "data"),
    Output("compare-table", "tooltip_data"),
    Input("compare-rows", "data"),
    Input("compare-full-only", "value"),
)
def show_table(rows, full_only):
    return compare_table(rows or [], bool(full_only))
