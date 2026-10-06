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
from dash import Input, Output, html
from flask import request

PANEL_API_BASE_URL = os.environ.get("PANEL_API_BASE_URL", "http://panel-web:8000")

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
