# cse-panel-dash-migration (planning workspace)

Status: **Phases 0-1 live and verified end-to-end (real job ran on
Framework GPU through the new UI), 2026-10-07.** Entrypoint per
`docs/workflow/documentation-workspaces.md`. `plan.md` §5 holds 11
executable step blocks (`panel-dash-01` through `12`, minus the
deliberately-not-yet-written `panel-dash-10`) per
`docs/agent-design/step-packet-schema.md`; this file is the durable
status record and where step hand-backs get written as each one runs.

## What this is

A plan to replace `cse-panel-stack`'s homegrown, hand-rolled HTML/CSS/JS
front end (`app.py`'s ~500-line `index()` route) with a **Dash**
(Plotly) UI, following a quick side-by-side spike against NiceGUI run
2026-10-06/07 on a throwaway LXC (`90001` on `pve`, not yet torn down —
see plan.md §7 open items). Dash was chosen for its stronger native
charting (the real payoff for OCCULT's upcoming capability-vs-refusal
visualizations) and, once `dash-bootstrap-components` is added, a
genuinely polished look with minimal custom CSS.

The existing FastAPI JSON API (`/jobs`, `/suites`, `/benchmarks`,
`/backends`) is **not being replaced** — it's a clean, already-correct
backend contract the current `index()` page itself calls via fetch().
Dash becomes a new consumer of that same API, not a rewrite of it.

## Current state (2026-10-07)

- Research + architecture written to `plan.md`. Nothing built in
  `cse-panel-stack` itself.
- The UI-framework spike (`docs/mitre-occult/artifacts/{nicegui,dash}_demo.py`)
  is a separate, disposable proof of concept — not part of this
  migration's codebase, just the evidence that informed the Dash choice.
  Throwaway LXC `90001` on `pve` destroyed 2026-10-07 after the plan was
  written.
- All 6 open decisions in `plan.md` §6 resolved by the operator
  2026-10-07. Notably: **E (OCCULT integration) was folded in**, not
  deferred — Phase 3 now has a 3a/3b split with 3b explicitly gated on
  `docs/mitre-occult/plan.md`'s own Phase 0–1 existing first (see §6-E
  for the exact dependency).

## Hand-back: panel-dash-01 through 06 (2026-10-07)

All six Phase 0 steps executed, all gates passed:

| Step | Edit | Gates |
|---|---|---|
| `panel-dash-01-compose-service` | Added `panel-ui` service to `docker-compose.yml` (4th service, stock `python:3.10-slim`, gunicorn, port 8050) | yaml-syntax PASS, service-count PASS |
| `panel-dash-02-app-requirements` | Created `app-ui/requirements.txt`. `dash`/`plotly` pinned from the spike (4.4.1/7.1.0); `dash-bootstrap-components`/`gunicorn`/`requests` resolved live via a throwaway venv install (2.0.4 / 26.2.0 / 2.34.2) | file-exists-and-pinned PASS (5/5) |
| `panel-dash-03-app-scaffold` | Created `app-ui/app.py` — trivial Dash/CYBORG page showing `X-Authentik-Username` + a live call to `panel-web`'s `/healthz` | python-syntax PASS, has-server-export PASS |
| `panel-dash-04-playbook-panel-ui` | Extended `deploy-cse-panel-stack.yml`: panel-ui dir/copy tasks, restart task, wait-for-200-on-`:8050` task | yaml-syntax PASS (needed `ANSIBLE_ROLES_PATH`-correct cwd — ran from `terraform/lxc/ansible/`, not repo root), mentions-panel-ui PASS (7 ≥ 4) |
| `panel-dash-05-edge-dev-route` | Added `cse-panel-ui-dev` route to `edge.yaml` (temporary, removed at cutover) | yaml-syntax PASS, route-count PASS (3) |
| `panel-dash-06-stack-contract` | Updated `STACK_CONTRACT.md`: Provides row, Persistent State bullet, Implementation Files row | mentions-panel-ui PASS (3 ≥ 3) |

Nothing deployed yet — these are file edits only, per each step's own
`forbidden_actions`. No gate failures, no deviations from the plan's
literal content.

## Hand-back: Phase 0 deployed live (2026-10-07)

`scripts/provision.sh --stack cse-panel-stack` ran clean on `pve-tiny`
(`failed=0`, both `panel-web` and `panel-ui` passed their health waits).
Edge activation needed two more deploys, run by the operator directly
per the harness's own production-deploy classifier (blocks even
approved `provision.sh` calls against `pve`/`pve-tiny` from this
session's own tool calls):

- `proxy-stack` (`pve`) — publishes the Traefik dynamic route
- `technitium-stack` (`pve`) — publishes the live DNS record

**Two real bugs found and fixed along the way, not pre-planned:**

1. **`terraform/lxc/reconcile-edge.py`'s target-preflight check only
   knew about `pve`.** `_resolve_target_preflight_command` special-cased
   `target == "pve"` → `with-secrets-prod`, and silently fell back to
   the dev `with-secrets` wrapper for every other node — so running it
   against `pve-tiny` tripped `with-secrets`'s own production safety
   rail (`EGR200`). Fixed by adding `_production_wrapper_name()`,
   deriving the right `with-secrets-prod-<node>` wrapper from
   `terraform/PRODUCTION_NODES` generically instead of hardcoding one
   node. Confirmed the fix introduced no new test failures (7
   pre-existing, unrelated `test_reconcile_edge.py` failures exist on
   `main` with or without this change — not touched here, out of scope).
2. **Ran `reconcile-edge.py --apply` against the wrong node the first
   time.** Targeted `pve-tiny` (where `cse-panel-stack` itself lives)
   instead of `pve` (where `proxy-stack`/Traefik actually lives) — the
   generated Traefik configs landed in
   `terraform/lxc/environments/pve-tiny/.generated/traefik/`, but
   `proxy-stack`'s deploy playbook reads from its *own* node's
   `.generated/` tree (`.../pve/...`), which stayed stale. First
   `proxy-stack` redeploy reported `changed=4` but the live dynamic
   config file was untouched (confirmed by `pct exec`-ing into the
   `proxy-stack` LXC directly — not the PVE host, which was itself a
   first wrong-filesystem check). Re-ran the reconcile targeted at
   `pve`, redeployed `proxy-stack` again — fixed. **Lesson for any
   future edge change:** target `reconcile-edge.py --apply` at whichever
   node runs `proxy-stack`/Traefik, not the node the edited stack lives
   on — they're not always the same, and this repo has three production
   nodes now.

**Verified live:** `dig cse-panel-ui-dev.lab.gibbsgreatly.xyz` resolves;
`curl` returns `302` (forward-auth redirect) matching `grafana`/`netbox`
sanity checks exactly; live dynamic config on the `proxy-stack` LXC has
the correct 3-router/3-service block. `panel-ui` uses ~90MB RSS in the
LXC, 723Mi still available — **no `stack.yaml` resource bump needed**
(§6-B resolved: measure, don't guess — the real footprint was small).

**Phase 0 acceptance confirmed by operator 2026-10-07**, in browser:
page showed real username ("Logged in as: steve") and
`panel-web /healthz: 200 {"status":"ok"}` — the auth-header-forwarding
path works end-to-end.

## Hand-back: panel-dash-07-submission-form (2026-10-07)

Extended `app-ui/app.py`: duplicated `KNOWN_BENCHMARKS`/`BENCHMARK_INFO`
verbatim from `app/app.py` (per the step's instruction — no shared
import path between the two apps); added a "Submit a run" card with a
`dbc.Checklist` (10 benchmarks, switch style, each row showing the real
description text), a test-case-count `dcc.Slider`, and a submit button;
added a callback that reads `X-Authentik-Username` off the inbound
request, forwards it as a header, and POSTs to `panel-web`'s real
`/jobs` (single benchmark) or `/suites` (multiple) endpoints —
unchanged API, exactly as the plan specified.

Gates: python-syntax PASS, benchmark-count PASS, forwards-auth-header
PASS (3 occurrences ≥ 1). Deployed via
`./with-secrets-prod-tiny scripts/provision.sh --stack cse-panel-stack`
(`failed=0`); `docker logs cse-panel-ui` confirms clean gunicorn startup,
both workers booted, no import errors.

**Not yet verified — needs a human in a browser:** actually checking a
benchmark and clicking Submit, confirming a real job/suite appears
(e.g. via Flower or `GET /jobs`) — this is Phase 1's real acceptance
check per plan.md §8, and nothing above proves the click-through flow
itself works, only that the code is syntactically sound and the
container starts cleanly.

## Phase 1 acceptance confirmed live, plus a real pre-existing bug found along the way (2026-10-07)

Operator submitted a real `mitre` job through the new UI. First
submission got stuck `PENDING` with no GPU activity — traced to a
**genuine, pre-existing config drift in `cse-controller`, unrelated to
this migration**: the *live deployed* `docker-compose.yml` on the
`cse-controller` host still referenced `${CSE_PANEL_REDIS_PASSWORD}` in
its Celery broker URL, but the *repo's* `docker-compose.yml` for that
stack has never had a password in it (confirmed via `git log -p`), and
`cse-panel-redis` genuinely has no `requirepass` set (matches
`STACK_CONTRACT.md`'s documented "no secret inputs"). The host was
simply never redeployed since whenever that password was removed from
the repo — the worker had been failing to connect to its broker this
whole time, silently. Fixed by redeploying `cse-controller`
(`scripts/provision.sh --stack cse-controller` on `pve-tiny`); worker
reconnected cleanly (`Connected to redis://192.168.20.30:6379/0`).

The original stuck test job (`ebe57cd0-...`) landed in Redis's
`unacked` hash — a known behavior this project already has a memory
entry for (`task_acks_late=True` + a task delivered-then-disconnected
sits unacked until the 12h visibility timeout, not instantly
redelivered). Not chased further; operator resubmitted fresh through
the UI instead, which queued and ran immediately with **confirmed real
GPU activity on Framework** — full path verified end-to-end: Dash UI →
`panel-web` → Celery → `cse-controller` worker → Framework inference.

## Next step

Phase 2 (`panel-dash-08`, the status/results table with live polling
and delete controls). `panel-dash-10` (the OCCULT tab) stays unwritten
until `docs/mitre-occult/plan.md` Phase 1 is real — don't pre-author it.

## Hand-back: panel-dash-08-status-table (2026-10-07)

Extended `app-ui/app.py`: a "Recent runs" `dash_table.DataTable`
(job_id/benchmark/backend/submitted_by/submitted_at/state/summary
columns — summary flattens `stats_summary`'s `[key, value]` pairs or
shows the `error` field on `FAILURE`), a `dcc.Interval` polling
`GET /jobs` every 4s (matching the old UI's cadence), and a job-id
input + delete button calling `DELETE /jobs/{id}` with an automatic
`?force=true` retry if the first response has `"in_progress": true`.
No suites-specific table yet — deliberately deferred per the step's own
scope (jobs only, suites left for a later step if wanted).

Gates: python-syntax PASS, has-poll-interval PASS (1 ≥ 1). Deployed via
`./with-secrets-prod-tiny scripts/provision.sh --stack cse-panel-stack`
(`failed=0`); `docker logs cse-panel-ui` confirms clean gunicorn
startup, both workers booted, no import errors.

**Not yet verified — needs a human in a browser:** confirming the table
actually renders and updates live (e.g. watching the `f0bd378e-...`
mitre job's row, or a fresh submission, transition states without a
page reload), and that Delete actually removes a row. Nothing above
proves the click-through/live-update behavior, only that the code is
sound and the container starts cleanly.

## Hand-back: tabs/row-delete/detail-panel rework (2026-10-07)

Direct operator feedback on the deployed Phase 2 table: everything on
one scrolling page, no click-to-delete, results squashed into an
unreadable joined string. Iterated live against real job data (not a
written step block — direct UX feedback mid-session, same pattern as
the earlier Dash-vs-NiceGUI spike iteration):

- Split into `dbc.Tabs`: "Run" (identity check + submission form) vs.
  "Results" (jobs table + detail panel).
- `jobs-table` now uses `row_deletable=True` + `row_selectable="single"`
  — deletion diffs `data` vs `data_previous` (standard Dash pattern)
  instead of a separate job-id input box.
- New detail panel renders the selected row's full `stats_summary` as
  a real metric/value table, not a single joined string.

Verified live against real jobs (operator confirmed: multiple orphaned
test jobs deleted via the UI, a completed mitre run's full C2/Exfil
breakdown displayed correctly once selected). **This work was deployed
live but the commit was missed at the time** — caught and committed
2026-10-07 when returning to this workspace after an unrelated
tangent (VS Code Copilot model config, parked separately).

## Next step

Phase 3a (`panel-dash-09`, the results chart). `panel-dash-10` (OCCULT
tab) stays gated as noted above.

## Open item found while writing the step packets — resolved 2026-10-07

Writing `panel-dash-11`'s acceptance check surfaced a real gap: once
`cse-panel.${LAB_DOMAIN}` repoints from `panel-web` (8000) to
`panel-ui` (8050), FastAPI's JSON API loses its public address
entirely. Checked the repo for an actual consumer first — found none
(`cse-controller` only talks to this stack's Redis, nothing calls
`/jobs`/`/suites` externally). Operator chose to add a dedicated
`cse-panel-api.${LAB_DOMAIN}` → `panel-web:8000` route anyway, per the
API's own "stays usable for other integrations" design intent even
with no current consumer. `panel-dash-11` now creates this route.
