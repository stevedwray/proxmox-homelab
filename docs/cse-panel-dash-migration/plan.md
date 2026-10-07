# cse-panel-stack → Dash UI — research, architecture, and step packets

Written per `.github/prompts/plan-change.prompt.md`'s two-pass shape:
§1–4 are the research/architecture pass; §6's open decisions (all
resolved 2026-10-07) gate §5, the step packets themselves, per
`docs/agent-design/step-packet-schema.md`. §8 covers the parts that are
deliberately *not* step blocks (operator-run deploys, browser
verification) — this is a one-model-plans/one-model-executes process,
and anything a local model's execution loop can't actually do belongs
in prose, not a fenced YAML block it would misread as its own job.

---

## 1. Why — and what's actually being replaced

`cse-panel-stack` (`docs/cyberseceval-panel/`) is the browser control
panel for submitting CyberSecEval benchmark runs. Its current UI is a
~500-line block of hand-written HTML/CSS/vanilla-JS returned as a raw
f-string from `app.py`'s `index()` route (lines 565–1067) — functional,
but exactly the "bland and homegrown" UI the operator wants off this
repo's hands, and a dead end for the richer graphics/graphs OCCULT's
upcoming reporting work will need (`docs/mitre-occult/plan.md` §9-E
already names "reuse `cse-panel`" as the leading front-end option for
OCCULT once this exists).

A quick side-by-side spike (2026-10-06/07, throwaway LXC `90001` on
`pve`, plain-LAN/no-SSO, torn down after) compared **NiceGUI** and
**Dash**. Operator's call: **Dash**, once styled with
`dash-bootstrap-components` (bare Dash is no better-looking than the
current page) — its native Plotly charting is the real differentiator,
and `dbc.Checklist` solves the multi-benchmark-selection UX the old
page's checkboxes already got right (don't regress that with a
dropdown that collapses to "N selected").

**This is a presentation-layer swap, not a backend rewrite.** `app.py`
already cleanly separates its JSON API (`/jobs`, `/suites`,
`/benchmarks`, `/backends`, `/healthz` — lines 363–562) from the one
HTML route. The API is correct, tested-by-production-use, and the
code's own comment (line ~24) says it's deliberately kept "usable as a
real API for other integrations, not just this one HTML page" — that
intent stands; Dash becomes a new consumer of it, same as the current
JS frontend is, not a replacement for it.

---

## 2. What's actually in `cse-panel-stack` today (reuse inventory)

Confirmed by reading the real files, not assumed:

| Piece | What it is | Fate in this migration |
|---|---|---|
| `app/app.py`'s FastAPI app (`/jobs`, `/suites`, `/benchmarks`, `/backends`, `/healthz`) | The real backend: submits Celery tasks to `cse-controller`, tracks job/suite meta in Redis, returns status + `_flatten_stats`-summarized results | **Unchanged.** Dash calls it over HTTP exactly like a browser does today |
| `app.py`'s `index()` route (~500 lines, HTML/CSS/JS f-string, lines 565–1067) | The current bland UI | **Deleted** once Dash is live and verified (step `panel-dash-12`) |
| `docker-compose.yml` (3 services: `redis`, `flower`, `panel-web`) | One LXC, one-process-per-container precedent already established here | New Dash service follows the same shape — a 4th service, not a second process stuffed into `panel-web`'s container |
| `edge.yaml` (Traefik `EdgeManifest`, `forwardAuth` on both routes) | SSO/access gate, enforced at the edge regardless of backend framework | **Unchanged except one route's backend `url`** — once Dash is live, `cse-panel.${LAB_DOMAIN}` points at the new service's port instead of `panel-web`'s 8000 |
| `X-Authentik-Username` header handling | `submit_job`/`submit_suite` read `x_authentik_username` straight off the **inbound HTTP header** (FastAPI `Header()` param, not a body field) — see `app.py:386` | Dash must read the same header off *its own* inbound request (the browser → Traefik → Dash hop still carries it) and **explicitly forward it** as a header on Dash's outgoing call to FastAPI's `/jobs`/`/suites` — this is a server-to-server call now, the header does not forward itself |
| `stack.yaml` (`vmid: 20030`, `mgmt_seg`, 1 core / 1024MB / 512 swap) | LXC sizing for the 3 existing services | Likely needs a modest bump once Dash+gunicorn's footprint is measured (§6-B) — not guessed in advance; checked at `panel-dash-01` execution time |
| `STACK_CONTRACT.md` | "Image stays stock `python:3.10-slim`, code lives in bind-mounted `/srv/cse-panel/app`, never baked into the image" | New service follows the identical convention — own bind-mounted code dir, stock Python image |

Relevant real field names, confirmed from `app.py` for the step packets
below (not assumed):

- `POST /jobs` query params: `benchmark`, `num_test_cases` (default 2),
  `backend_base_url`, `backend_model`, `backend_api_key`,
  `random_sample` (bool). Reads `x_authentik_username` off the header.
- `POST /suites` body: `{"tests": [<same fields as a job, minus the
  header>, ...]}`. Same header read.
- `GET /jobs` → `{"jobs": [<job summary>, ...]}`; `GET /jobs/{id}` → one
  job summary, plus `result`/`error` once terminal.
- Job summary fields: `job_id`, `benchmark`, `backend`, `submitted_by`,
  `submitted_at`, `suite_id`, `state`, `state_label`, and once
  `SUCCESS`: `ok` (bool), `stats_summary` (list of `[key, value]`
  pairs), optionally `stats_error`.
- `GET /suites` → `{"suites": [...]}`, each with `suite_id`,
  `submitted_by`, `submitted_at`, `benchmarks` (list), `total`, `done`,
  `failed`, `overall` ("Done"/"Failed"/"Running"), `jobs` (list of job
  summaries).
- `DELETE /jobs/{id}?force=<bool>`, `DELETE /suites/{id}?force=<bool>` —
  both return `{"error": ..., "in_progress": true}` if still running
  and `force` wasn't set.
- `KNOWN_BENCHMARKS` (10 strings) and `BENCHMARK_INFO[b]["description"]`
  (`app.py:62-125`) — the exact list and descriptions the new
  `dbc.Checklist` must offer, verbatim, not reinvented.

---

## 3. Key architectural fact: Dash needs WSGI, this stack runs ASGI

`panel-web` currently runs `uvicorn app:app` (ASGI, for FastAPI). Dash
is built on Flask (WSGI) — its dev server is literally the Werkzeug dev
server (the "WARNING: this is a development server" banner seen live in
the spike). Trying to run Dash under uvicorn, or FastAPI under Dash's
server, doesn't work without extra adapter layers.

**Resolution: don't merge them.** Dash runs as its own service
(`panel-ui`), its own container, served by **gunicorn** (the standard
production WSGI server for a Flask-based app — Dash's own docs
recommend this over the dev server), talking to FastAPI's existing
`/jobs`/`/suites`/etc. over plain HTTP inside the same docker network
(`http://panel-web:8000/...`), exactly as a browser's `fetch()` calls do
today. This keeps the two frameworks' runtime models fully separate and
matches the one-process-per-container precedent already in this
stack's own `docker-compose.yml`.

---

## 4. Proposed architecture

```
  Browser → Traefik (forwardAuth) → panel-ui (NEW: Dash + gunicorn, port 8050)
                                          │ forwards X-Authentik-Username
                                          │ HTTP, same docker network
                                          ▼
                                    panel-web (UNCHANGED: FastAPI + uvicorn, port 8000)
                                          │
                                          ▼
                                   Celery → cse-controller (unchanged, cross-zone)
```

`redis` and `flower` are unaffected — `flower`'s own route in
`edge.yaml` stays pointed at `flower`'s own port, untouched by any of
this.

---

## 5. Step packets

Risk-ordered: prove the plumbing (Phase 0) before porting real UI
(Phases 1–2), add the actual payoff (Phase 3's charting) before cutting
over the production hostname (Phase 4). Every step below touches only
`terraform/lxc/stacks/cse-panel-stack/` and
`terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml` — nothing
in `cse-controller` or any other stack is touched by this plan.

### Phase 0 — scaffold `panel-ui`, prove the full auth path

#### panel-dash-01-compose-service

```yaml
id: panel-dash-01-compose-service
title: Add panel-ui service to cse-panel-stack's docker-compose.yml
depends_on: []

change: >
  Add a fourth service named `panel-ui` to
  terraform/lxc/stacks/cse-panel-stack/docker-compose.yml, directly
  below the existing `panel-web` service, with exactly this content:

    panel-ui:
      image: harbor.lab.gibbsgreatly.xyz/dockerhub/library/python:3.10-slim
      container_name: cse-panel-ui
      volumes:
        - /srv/cse-panel/panel-ui:/app
      working_dir: /app
      command: ["bash", "-c", "pip install --no-cache-dir -r requirements.txt && gunicorn -b 0.0.0.0:8050 --workers 2 app:server"]
      environment:
        - PANEL_API_BASE_URL=http://panel-web:8000
        - LAB_DOMAIN=${LAB_DOMAIN}
      ports:
        - "8050:8050"
      depends_on:
        - panel-web
      restart: unless-stopped

  Do not change any of the three existing services (`redis`, `flower`,
  `panel-web`).

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/docker-compose.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply / docker compose up run -- this step only edits the file"
    - "Any edit to the redis, flower, or panel-web service blocks"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/docker-compose.yml'))\""
    expect: "exit 0"
    critical: true
  - id: service-count
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/docker-compose.yml')); assert set(d['services']) == {'redis','flower','panel-web','panel-ui'}, d['services']\""
    expect: "exit 0"
    critical: true
```

#### panel-dash-02-app-requirements

```yaml
id: panel-dash-02-app-requirements
title: Create panel-ui's requirements.txt
depends_on: []

change: >
  Create terraform/lxc/stacks/cse-panel-stack/app-ui/requirements.txt.
  Two packages have versions already verified live in the 2026-10-06/07
  spike (use these exact pins): dash==4.4.1 and plotly==7.1.0. Two more
  were never pinned in the spike (dash-bootstrap-components, gunicorn)
  plus requests (new, for panel-ui's calls to panel-web) -- resolve
  each of these three to its current latest version by running
  `pip index versions <package>` (or `pip install <package>` in a throwaway
  venv and reading the installed version) and pin exactly what that
  resolves to. Do not write unpinned package names and do not guess a
  version number -- look each one up for real, the same way the
  media-stack-lab plan's Jellyfin step required looking up a real image
  tag instead of shipping a placeholder.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app-ui/requirements.txt
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any unpinned (bare, no ==version) package entry"

gates:
  - id: file-exists-and-pinned
    cmd: "grep -cE '^[a-zA-Z0-9_-]+==[0-9]' terraform/lxc/stacks/cse-panel-stack/app-ui/requirements.txt"
    expect: "5"
    critical: true
```

#### panel-dash-03-app-scaffold

```yaml
id: panel-dash-03-app-scaffold
title: Create panel-ui's app.py (auth-proving scaffold page)
depends_on: [panel-dash-02-app-requirements]

change: >
  Create terraform/lxc/stacks/cse-panel-stack/app-ui/app.py with exactly
  this content:

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

  Transcribe this exactly -- do not add extra routes, pages, or
  components; later steps add those. `server = app.server` must be
  present (gunicorn's `app:server` target in panel-dash-01's compose
  command depends on it).

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app-ui/app.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding components, routes, or pages beyond the literal content above"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: "exit 0"
    critical: true
  - id: has-server-export
    cmd: "grep -c '^server = app.server$' terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: "1"
    critical: true
```

#### panel-dash-04-playbook-panel-ui

```yaml
id: panel-dash-04-playbook-panel-ui
title: Extend deploy-cse-panel-stack.yml to deploy panel-ui's code and restart it
depends_on: [panel-dash-01-compose-service, panel-dash-03-app-scaffold]

change: >
  In terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml, add a
  `cse_panel_ui_app_dir: /srv/cse-panel/panel-ui` var next to the
  existing `cse_panel_app_dir` var. After the existing "Create panel-web
  app directory" / "Write panel-web's app.py" / "Write panel-web's
  requirements.txt" tasks, add four parallel tasks for panel-ui:
  (1) create directory `{{ cse_panel_ui_app_dir }}` mode 0755;
  (2) copy src `../../stacks/{{ cse_panel_stack_name }}/app-ui/app.py`
  to `{{ cse_panel_ui_app_dir }}/app.py` mode 0644;
  (3) copy src `../../stacks/{{ cse_panel_stack_name }}/app-ui/requirements.txt`
  to `{{ cse_panel_ui_app_dir }}/requirements.txt` mode 0644 -- same
  shape as the three existing panel-web tasks immediately above them,
  just a different source/dest pair.
  Then, immediately after the existing "Restart panel-web to pick up
  any app.py/requirements.txt changes" task (and its `docker compose
  restart panel-web` command), add a matching
  "Restart panel-ui to pick up any app.py/requirements.txt changes"
  task running `docker compose restart panel-ui` in the same
  `cse_panel_stack_dir`, same `when: not ansible_check_mode` guard.
  Finally, after the existing "Wait for panel-web to respond" task, add
  a "Wait for panel-ui to respond" task using the same
  `ansible.builtin.uri`/`until`/`retries: 10`/`delay: 3` shape, but
  `url: "http://localhost:8050/"` and `status_code: 200` (panel-ui has
  no `/healthz` yet -- its scaffold page itself is the check).

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any change to the existing panel-web/redis/flower tasks' own content"
    - "Running ansible-playbook or provision.sh -- this step only edits the file"

gates:
  - id: yaml-syntax
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml"
    expect: "exit 0"
    critical: true
  - id: mentions-panel-ui
    cmd: "grep -c 'panel-ui' terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml"
    expect: ">=4"
    critical: true
```

#### panel-dash-05-edge-dev-route

```yaml
id: panel-dash-05-edge-dev-route
title: Add a temporary panel-ui dev route to edge.yaml
depends_on: []

change: >
  In terraform/lxc/stacks/cse-panel-stack/edge.yaml, add a third route
  under `spec.routes`, after the existing `cse-panel-flower` route,
  with exactly this content:

    - name: cse-panel-ui-dev
      host: cse-panel-ui-dev.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_CSE_PANEL}:8050
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth

  This is a temporary route for Phases 0-3 verification only --
  panel-dash-11 (cutover) removes it once `cse-panel` itself points at
  panel-ui. Do not change the existing `cse-panel` or
  `cse-panel-flower` route entries.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit to the existing cse-panel or cse-panel-flower route entries"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: route-count
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml')); assert len(d['spec']['routes'])==3\""
    expect: "exit 0"
    critical: true
```

#### panel-dash-06-stack-contract

```yaml
id: panel-dash-06-stack-contract
title: Document panel-ui in STACK_CONTRACT.md
depends_on: [panel-dash-01-compose-service, panel-dash-05-edge-dev-route]

change: >
  In terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md: (1) in the
  "Provides" table, add a row `| panel-ui-http | 8050 | tcp |` below
  the existing `panel-web-http`/`flower-http` rows; (2) in "Persistent
  State", add a bullet after the existing `/srv/cse-panel/app` bullet:
  "- `/srv/cse-panel/panel-ui` -- `panel-ui`'s own application code
  (`app.py`/`requirements.txt`), same bind-mount-not-image convention as
  `panel-web`."; (3) in "Implementation Files", add a row
  `| terraform/lxc/stacks/cse-panel-stack/app-ui/app.py | panel-ui's
  Dash application |` below the existing `app/app.py` row.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit to existing rows/bullets beyond the three additions named above"

gates:
  - id: mentions-panel-ui
    cmd: "grep -c 'panel-ui' terraform/lxc/stacks/cse-panel-stack/STACK_CONTRACT.md"
    expect: ">=3"
    critical: true
```

### Phase 1 — port the run-submission form

#### panel-dash-07-submission-form

```yaml
id: panel-dash-07-submission-form
title: Add the benchmark-run submission form to panel-ui, wired to panel-web's existing POST /jobs and POST /suites
depends_on: [panel-dash-03-app-scaffold]

change: >
  Extend terraform/lxc/stacks/cse-panel-stack/app-ui/app.py (do not
  remove the Phase-0 whoami/api-health card -- add to the layout, don't
  replace it). Import the 10-entry `KNOWN_BENCHMARKS` list and
  `BENCHMARK_INFO` dict verbatim from
  terraform/lxc/stacks/cse-panel-stack/app/app.py lines 62-125 (copy
  the literal Python values into app-ui/app.py -- panel-ui has no
  import path to panel-web's module, this is a deliberate duplication,
  not a shared import). Add a new dbc.Card "Submit a run" containing: a
  dbc.Checklist (id="benchmarks", switch=True, inline=False -- one row
  per benchmark since there are 10, each row label including both the
  benchmark name and its BENCHMARK_INFO description, matching the old
  UI's benchmark_checkboxes content) over all KNOWN_BENCHMARKS; a
  dcc.Slider (id="num-test-cases", min=1, max=50, value=2,
  tooltip always_visible) for num_test_cases; a dbc.Button
  (id="submit-btn", "Submit run(s)"). Add a callback on submit-btn
  click, State on the Checklist value and the Slider value, that: reads
  `request.headers.get("X-Authentik-Username")`; if exactly one
  benchmark is checked, POSTs to
  f"{PANEL_API_BASE_URL}/jobs" with params
  {"benchmark": b, "num_test_cases": n} and header
  {"X-Authentik-Username": username} using `requests.post`; if more
  than one benchmark is checked, POSTs to
  f"{PANEL_API_BASE_URL}/suites" with json body
  {"tests": [{"benchmark": b, "num_test_cases": n} for b in checked]}
  and the same forwarded header. Add a dbc.Alert (id="submit-result",
  initially hidden) showing the response JSON's job_id/suite_id on
  success, or the "error" field if the API returned one. Raise
  dash.exceptions.PreventUpdate if no benchmark is checked when Submit
  is clicked.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app-ui/app.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing or altering the Phase-0 whoami/api-health card"
    - "Changing panel-web's app.py -- this step only adds a caller, never edits the API it calls"
    - "Hardcoding any benchmark name/description not sourced from app/app.py's KNOWN_BENCHMARKS/BENCHMARK_INFO"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: "exit 0"
    critical: true
  - id: benchmark-count
    cmd: "python3 -c \"import re; s=open('terraform/lxc/stacks/cse-panel-stack/app-ui/app.py').read(); assert len(re.findall(r'KNOWN_BENCHMARKS', s))>=1\""
    expect: "exit 0"
    critical: true
  - id: forwards-auth-header
    cmd: "grep -c 'X-Authentik-Username' terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: ">=1"
    critical: true
```

### Phase 2 — port the status/results view

#### panel-dash-08-status-table

```yaml
id: panel-dash-08-status-table
title: Add a live-polling recent jobs/suites table with delete controls to panel-ui
depends_on: [panel-dash-07-submission-form]

change: >
  Extend app-ui/app.py with a new dbc.Card "Recent runs" containing a
  dash_table.DataTable (id="jobs-table") with columns job_id,
  benchmark, backend, submitted_by, submitted_at, state_label (and a
  text summary column rendering stats_summary's [key, value] pairs
  joined as "key: value" strings, or the error field if state is
  FAILURE), plus a dcc.Interval (id="poll-interval", interval=4000,
  i.e. 4 seconds, matching the old UI's own 4000ms polling cadence) and
  a dbc.Button per row is not supported by DataTable directly -- instead
  add one dbc.Input (id="delete-job-id") + one dbc.Button
  (id="delete-btn", "Delete job") below the table for a job_id-driven
  delete action, calling `requests.delete(f"{PANEL_API_BASE_URL}/jobs/{job_id}")`
  (retry once with `?force=true` if the first call's JSON has
  `"in_progress": true`) on click. A callback on poll-interval's n_intervals
  calls `requests.get(f"{PANEL_API_BASE_URL}/jobs")`, flattens the
  returned jobs list's stats_summary/error into the display string
  described above, and sets jobs-table.data. Do not implement a
  suites-specific table in this step -- /suites support (a second table
  or a suite_id grouping column) is deliberately left for a later,
  separate step if wanted; this step only needs to prove the jobs table
  and delete path work against real data.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app-ui/app.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any change to panel-web's app.py"
    - "Removing the Phase-0/Phase-1 cards"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: "exit 0"
    critical: true
  - id: has-poll-interval
    cmd: "grep -c 'dcc.Interval' terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: ">=1"
    critical: true
```

### Phase 3 — charting (3a, real payoff) and OCCULT scaffold (3b, gated)

#### panel-dash-09-results-chart

```yaml
id: panel-dash-09-results-chart
title: Add a real per-benchmark results chart to panel-ui, reading real stats_summary data
depends_on: [panel-dash-08-status-table]

change: >
  Extend app-ui/app.py with a new dbc.Card "Results" containing a
  dcc.Graph (id="results-chart"). In the same callback that updates
  jobs-table.data (panel-dash-08), also compute and return a Plotly
  figure: for each job in the fetched /jobs list with state SUCCESS and
  a non-empty stats_summary, take the first numeric-valued entry in
  stats_summary (the primary headline metric most benchmarks surface
  first, e.g. mitre's malicious %) and plot one bar per job, x-axis
  = benchmark name, y-axis = that numeric value, using the same
  plotly_dark/transparent-background figure styling validated in the
  spike (template: "plotly_dark", paper_bgcolor/plot_bgcolor:
  "rgba(0,0,0,0)"). Do not fabricate or mock chart data -- if no job has
  a SUCCESS state with stats yet, render an empty figure with an
  annotation "No completed runs yet."

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app-ui/app.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Hardcoded/mock/placeholder numbers in the chart -- must read real /jobs data"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: "exit 0"
    critical: true
  - id: has-graph-component
    cmd: "grep -c 'dcc.Graph' terraform/lxc/stacks/cse-panel-stack/app-ui/app.py"
    expect: ">=1"
    critical: true
```

**panel-dash-10-occult-tab-scaffold is NOT written as a step block yet.**
Per §6-E, this sub-phase is gated on `docs/mitre-occult/plan.md`'s own
Phase 0–1 (Inspect harness + a working TACTL-equivalent scoring tier)
actually existing and writing results somewhere readable. Writing its
`change` field now would mean inventing a data shape to read from
before OCCULT has one — exactly the "guessing instead of resolving
judgment" failure mode this schema exists to prevent. **Do not execute
a `panel-dash-10` step until `docs/mitre-occult/plan.md`'s README
records its Phase 1 as complete; at that point, write this step fresh**
(scaffold a second `dbc.Tabs` entry reading whatever real path OCCULT's
plan ends up landing results in — `reports/occult/<run-id>/` or the
Nextcloud pipeline pattern from `fix/cse-report-transcript-content`,
whichever OCCULT's own plan resolves §9-A to) rather than trying to
pre-author it blind here.

### Phase 4 — cutover

#### panel-dash-11-cutover-edge

```yaml
id: panel-dash-11-cutover-edge
title: Repoint cse-panel's production route at panel-ui, add a dedicated API route, and remove the temporary dev route
depends_on: [panel-dash-09-results-chart]

change: >
  In terraform/lxc/stacks/cse-panel-stack/edge.yaml, make three changes.
  (1) Change the existing `cse-panel` route's `backend.url` from
  `http://${LAB_IP_CSE_PANEL}:8000` to
  `http://${LAB_IP_CSE_PANEL}:8050`. (2) Replace the `cse-panel-ui-dev`
  route entry added in panel-dash-05 with a new permanent route named
  `cse-panel-api`, giving FastAPI's JSON API its own standalone public
  address now that `cse-panel` itself points at panel-ui instead of it
  -- confirmed 2026-10-07 that no current consumer other than the
  browser page calls it, but the operator chose to add this anyway per
  the API's own "stays usable for other integrations" design intent
  (app.py's header comment). Exact content:

    - name: cse-panel-api
      host: cse-panel-api.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_CSE_PANEL}:8000
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth

  (3) Leave the `cse-panel-flower` route completely unchanged.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit to the cse-panel-flower route"
    - "Changing the cse-panel route's host, dns, tls, or auth fields -- only backend.url changes"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: route-count-still-three
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml')); assert len(d['spec']['routes'])==3\""
    expect: "exit 0"
    critical: true
  - id: cse-panel-points-at-8050
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml')); r=[x for x in d['spec']['routes'] if x['name']=='cse-panel'][0]; assert r['backend']['url'].endswith(':8050')\""
    expect: "exit 0"
    critical: true
  - id: cse-panel-api-points-at-8000
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml')); r=[x for x in d['spec']['routes'] if x['name']=='cse-panel-api'][0]; assert r['backend']['url'].endswith(':8000')\""
    expect: "exit 0"
    critical: true
  - id: dev-route-gone
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/cse-panel-stack/edge.yaml')); assert not any(r['name']=='cse-panel-ui-dev' for r in d['spec']['routes'])\""
    expect: "exit 0"
    critical: true
```

#### panel-dash-12-remove-old-ui

```yaml
id: panel-dash-12-remove-old-ui
title: Delete app.py's index() HTML route now that panel-ui is live
depends_on: [panel-dash-11-cutover-edge]

change: >
  In terraform/lxc/stacks/cse-panel-stack/app/app.py: delete the entire
  `@app.get("/", response_class=HTMLResponse)` / `def index():` route
  and everything after it through the literal end of the file (lines
  565-1067 as of this plan's writing -- re-confirm the exact range by
  searching for `def index():` since line numbers may have drifted).
  Also remove the two imports that become unused once this route is
  gone: `import html` (top-level, used only inside index()'s
  benchmark_checkboxes construction) and
  `from fastapi.responses import HTMLResponse` (used only in the
  deleted route's decorator). Do not touch any other route or helper
  function in this file -- every function above line 565 (including
  `_flatten_stats`, `_job_summary`, every `/jobs`/`/suites` endpoint) is
  the real, still-used API and must be left exactly as-is.

scope:
  allowed_paths:
    - terraform/lxc/stacks/cse-panel-stack/app/app.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit to code above the index() route (all API endpoints and helpers stay untouched)"
    - "Leaving html or HTMLResponse imported but unused"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-panel-stack/app/app.py"
    expect: "exit 0"
    critical: true
  - id: index-route-gone
    cmd: "grep -c 'def index' terraform/lxc/stacks/cse-panel-stack/app/app.py"
    expect: "0"
    critical: true
  - id: no-unused-html-import
    cmd: "grep -c '^import html$' terraform/lxc/stacks/cse-panel-stack/app/app.py"
    expect: "0"
    critical: true
  - id: api-routes-still-present
    cmd: "grep -cE '@app\\.(get|post|delete)' terraform/lxc/stacks/cse-panel-stack/app/app.py"
    expect: ">=9"
    critical: true
```

---

## 6. Decisions (resolved 2026-10-07)

**A. Service topology — 4th container. CONFIRMED.** Separate `panel-ui`
container, gunicorn, calls `panel-web` over HTTP inside the docker
network. Implemented in `panel-dash-01`.

**B. LXC resource bump — measure, don't guess. CONFIRMED.** Check
`pve-tiny`'s actual headroom when `panel-dash-01`–`06` are deployed
(see §8); bump `memory`/`swap`/`cores` in `stack.yaml` only if the real
footprint of gunicorn+Dash+Plotly+dash-bootstrap-components needs it.
This bump, if needed, is an "Ansible task or role change" — validates
directly on `pve-tiny` under the normal production approval flow (not
pve-test-vm), per CLAUDE.md's Validation Tiers. Not written as its own
step block since whether it's needed at all is only knowable after real
deployment, not something to resolve blind here.

**C. Styling — CYBORG theme. CONFIRMED.** Baked into `panel-dash-03`.

**D. Old `index()` route — delete outright. CONFIRMED.** `panel-dash-12`.

**E. OCCULT reporting integration — folded in now, but gated.** Phase
3a (`panel-dash-09`) proceeds unblocked. Phase 3b (the OCCULT tab) is
deliberately **not** written as a step block yet — see the note after
`panel-dash-09` above. This is the one place this plan intentionally
stops short of "every judgment resolved to literal content," because
the judgment genuinely depends on a different, not-yet-resolved plan;
writing it now would mean guessing, not resolving.

**F. Spike cleanup — destroyed.** Throwaway LXC `90001` on `pve` was
destroyed 2026-10-07 after the spike comparison concluded (see this
workspace's `README.md`).

---

## 7. Sources

- This repo: `terraform/lxc/stacks/cse-panel-stack/{app/app.py,
  docker-compose.yml, edge.yaml, stack.yaml, STACK_CONTRACT.md}`,
  `terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml` (all read
  in full for this plan, not assumed), `docs/cyberseceval-panel/README.md`,
  `docs/mitre-occult/plan.md` §9-E, `docs/agent-design/README.md`,
  `docs/agent-design/step-packet-schema.md`.
- The NiceGUI/Dash spike itself: `docs/mitre-occult/artifacts/
  {nicegui,dash}_demo.py`, built and run live on throwaway LXC `90001`
  on `pve`, 2026-10-06/07.

---

## 8. What is deliberately *not* a step block

Per `step-packet-schema.md`: anything a local model's execution loop
can't actually run, or that needs a human to verify, is plain prose
here, not a fenced YAML block.

- **Deploying any of the above.** Every step in §5 only edits files.
  Actually applying them — `scripts/provision.sh --stack
  cse-panel-stack` — is an Ansible task/role change (CLAUDE.md
  Validation Tiers), run directly against `pve-tiny` under the normal
  production approval flow (`./with-secrets-prod-tiny`, Preflight →
  Operator Approval → `TASK_APPROVAL` → execute). Run it after
  `panel-dash-01` through `06` land, to actually bring `panel-ui` up
  before continuing to Phase 1.
- **Phase 0's real acceptance check.** After deploying, visit
  `https://cse-panel-ui-dev.${LAB_DOMAIN}` in a browser while logged in
  via Authentik and confirm the page shows your real username (not the
  placeholder string) and a `200` from `panel-web`'s `/healthz`. This
  is the proof that the auth-header-forwarding plumbing (§2) actually
  works end-to-end — no script can verify "is this really my username"
  on your behalf.
- **Phase 1's real acceptance check.** Submit a real single-benchmark
  job and a real multi-benchmark suite through the new form; confirm
  both show up via `GET /jobs` / `GET /suites` exactly as a job
  submitted through the old UI would, and that a real Celery
  worker on `cse-controller` picks them up (check via Flower, same as
  always).
- **Phase 2/3's real acceptance check.** Watch a real job's state
  transition live in the new table without a page reload; confirm
  delete actually removes it; confirm the chart renders real numbers
  from a completed run.
- **Phase 4's real acceptance check.** After deploying `panel-dash-11`
  and `12`, visit `https://cse-panel.${LAB_DOMAIN}` and confirm it's
  now the Dash UI, `https://cse-panel-flower.${LAB_DOMAIN}` is
  unaffected, and `curl https://cse-panel-api.${LAB_DOMAIN}/healthz`
  returns 200 (resolved 2026-10-07: confirmed no existing consumer other
  than the browser page calls the JSON API directly, but the operator
  chose to give it its own standalone route anyway rather than let it
  become unreachable once `cse-panel` repoints to panel-ui — see
  `panel-dash-11`, which now creates this route).
