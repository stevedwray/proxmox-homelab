# CyberSecEval Control Panel — planning workspace

Entrypoint per `docs/workflow/documentation-workspaces.md`. `plan.md` is the
step-by-step plan (`docs/agent-design/step-packet-schema.md` shape); this
file is the durable status record and where each step's hand-back gets
written (see `docs/agent-design/README.md`'s process).

## Read this first: current state (2026-09-19, end of day)

**Live, deployed, browser-reachable, SSO-enforced, and now genuinely
usable by a non-technical operator.** Everything in "What this
is"/"Architecture" below is built and running for real. Backend
selection, test suites, real results surfacing, a human-readable
homepage UI, and a real reliability fix for lost in-flight jobs have
all landed and been verified live against real submitted jobs (not
just read the code and assumed) -- see "Frontend redesign + reliability
fixes" at the bottom for the fullest detail.

**How to use it right now:**
- Browser: `https://cse-panel.lab.gibbsgreatly.xyz` (Authentik SSO) --
  tick the benchmark(s) you want, pick a backend, hit Run. The status
  table below it polls every 4s and shows benchmark/backend/state/result
  in plain language (e.g. "Malicious: 1/1 (100%)"), not JSON. An
  "Advanced / API" section at the bottom links to the raw JSON endpoints,
  `/docs`, and Flower, de-emphasized but still there.
- API directly: `http://192.168.20.30:8000` (from inside the lab
  network) -- `POST /jobs`, `POST /suites`, `GET /jobs/{id}`,
  `GET /suites/{id}`, `GET /benchmarks`, `GET /backends`. This is the
  real integration surface; the homepage is just one client of it.
- To point a run at a different backend (Ollama, llama.cpp server,
  etc.), pass `backend_base_url`/`backend_model` (UI: pick "custom" and
  fill in the fields) -- the target engine must already have a model
  loaded, this does not manage model loading.

**Known non-blocking gaps, not yet done:**
- No Ollama/llama.cpp presets in `GET /backends` -- no confirmed real
  endpoint for either in this lab yet to encode; `custom` fully works,
  just isn't a one-click preset.
- Result-summary formatting (`_flatten_stats` in `app.py`) is only
  tuned against the two real `stat.json`/`stats.json` shapes actually
  seen so far (`mitre`'s model->category->count-cluster nesting,
  `mitre-frr`'s flat rate/count fields). The other 8 benchmarks
  (`prompt-injection`, `interpreter`, `instruct`, `autocomplete`,
  `malware_analysis`, `threat_intel_reasoning`, `multiturn-phishing`,
  `autonomous-uplift`) fall back to generic label-cleanup formatting
  and may look rawer than mitre's until their real output is seen and
  the formatting is tuned the same way.
- No automated test coverage -- every check in this doc was a real,
  hands-on, one-off verification (including a throwaway local
  Redis+uvicorn sandbox used once to verify `app.py`'s new endpoints
  before deploying; per explicit operator feedback, that kind of live
  verification belongs on `pve-test-vm` going forward, not the
  workstation -- see `feedback_no_workstation_test_processes` in
  persistent memory).
- `deploy-cse-controller.yml` still runs `apt-get update`/pip installs/
  submodule-update checks on every deploy even though the heaviest ones
  (apt install, unit tests, submodule recursive update, threat-intel
  report download) are now gated to first-bootstrap-only -- see
  "Frontend redesign + reliability fixes" below for exactly what's
  gated and what still isn't.

## What this is

A web-based control panel for triggering CyberSecEval benchmark runs against
`cse-controller`/`cse-code-eval` and watching their progress live, instead of
the ad hoc Ansible-driven shell scripts used so far this implementation pass.
Requested 2026-09-19, after running a manual small-batch test made clear how
much repeated manual work (writing throwaway scripts, `docker exec`, reading
raw log files) each run currently takes.

## Architecture, in one paragraph

A new stack, `cse-panel-stack`, on `mgmt_seg` — the existing home for
every ops/dashboard stack in this repo (Grafana/Graylog/Portainer,
confirmed via `terraform/lxc/network/pve.yaml`) — runs Redis (the Celery
broker/result backend), Flower (Celery's own monitoring UI — reused as-is
for progress display, not rebuilt), and a small bespoke FastAPI app
(`panel-web`) that only handles job submission. **Placed on `pve-tiny`,
not `pve`** (operator's choice, 2026-09-19): `mgmt_seg` is already
defined on `pve-tiny` too (same VLAN/subnet as `pve`'s, MikroTik trunk
already tagged) with zero occupants so far — this is the first thing to
land there, not a new zone-extension project. A Celery **worker** process
is added to `cse-controller` itself (not a separate reachable service),
because that's where the actual PurpleLlama venv, datasets, and `cse-kali`
agent SSH key already live — the worker connects *out* to Redis in
`mgmt_seg`, which is the one new cross-zone firewall rule this needs
(`cse_seg -> mgmt_seg:6379`). Benchmark run logs also start forwarding to
Graylog as part of this work, fixing a real, already-confirmed gap
(`cse-controller`/`cse-code-eval` currently use the Docker default `json-file`
log driver, not `syslog` like every other stack).

## Operator decisions already made (2026-09-19)

- Zone: `mgmt_seg`, matching every existing dashboard stack.
- Trigger mechanism: a real job queue (Celery + Redis), not a bespoke REST
  API on `cse-controller` or an SSH-based trigger.
- Progress display: hybrid — bespoke UI for triggering, Flower (reused, not
  built) plus Graylog/Grafana for live status and log drill-down.
- Build scope for this pass: write the full plan now; implementation happens
  afterward, one step at a time.

## Status

**Deployed, live, and browser-reachable with SSO enforced (2026-09-19).**
All 5 operator-only actions have now run for real: `terragrunt apply`,
`provision.sh` redeploys for `cse-panel-stack`/`cse-controller`/
`cse-code-eval`, the real MikroTik firewall rule, Authentik/Traefik edge
reconcile + `proxy-stack` redeploy, and a Technitium DNS redeploy (a
real sixth action the plan's "5 operator actions" list missed — see
below). End-to-end confirmed the same day: a real `mitre` job submitted
through the browser UI ran to completion and its actual result (not
just a return code) displayed correctly — see "Frontend redesign +
reliability fixes" below.

## Step hand-backs

All 14 steps (`cse-panel-01` through `cse-panel-14`) landed with every
`critical: true` gate passing for real (not "looks right" — each YAML/
compose file was parsed, each Ansible playbook syntax-checked with the
real `ansible-playbook` binary, each Python file `py_compile`d and, for
`app.py`, actually executed to confirm no runtime error). Files: see
`git log` / `git show` on this commit for the full list (new
`cse-panel-stack` directory, new `environments/pve-tiny/cse-panel-stack`
terragrunt entrypoint, edits to `cse-controller`'s compose/deploy
playbook, new firewall playbook, `.env`/`variables.tf`/`main.tf`
additions, `pve-tiny.yaml` zone registration).

**Real bugs found and fixed while executing, not assumed away**
(the plan's own literal content was wrong in these ways until now):

1. `app.py`'s homepage route had an f-string that would throw a real
   `NameError` on first load (`${{'{LAB_DOMAIN}'}}` inside an f-string
   evaluates `{LAB_DOMAIN}` as a live expression, not a literal).
   Fixed: pass `LAB_DOMAIN` as a real env var, read via
   `os.environ.get`. Verified by actually calling the function, not
   just `py_compile`.
2. The `STACK_CONTRACT.md` gate referenced
   `terraform/lxc/scripts/validate-stack-metadata.sh` (wrong path --
   no `scripts/` subdirectory) with a `cse-panel-stack` positional arg
   the script doesn't accept at all, and the script itself only
   validates a fixed list of already-*active* stacks, so it could
   never have caught a real problem with this one anyway. Fixed the
   gate's command and scope, and documented the real limitation.
3. `deploy-cse-controller.yml`'s worker-support tasks (`cse-panel-11`/
   `cse-panel-12` in the original plan) were missing the actual copy
   task that writes `cse_tasks.py` to
   `/srv/cyberseceval/config/cse_tasks.py` -- without it, the worker's
   `PYTHONPATH=/srv/cyberseceval/config` has nothing to import.
4. The biggest one: `worker.env`'s write task was originally placed
   *after* `deploy-cse-controller.yml`'s "Validate docker compose
   configuration"/"Start controller container" tasks. Since the
   `worker` service's `env_file` points at that exact path, this would
   have broken `cse-controller`'s **entire** deploy on a fresh apply --
   `docker compose config` genuinely fails with "env file not found"
   the moment it runs, confirmed by actually reproducing it locally
   with a real `docker compose config` call. Fixed by moving the task
   to right after "Create stack directory", well before compose ever
   reads the file. Re-verified with a second real `docker compose
   config` call, this time with the file present -- passes.

`terragrunt plan` for `cse-panel-stack` (read-only, real Proxmox API
call) also confirmed clean: 5 to add, 0 to change, 0 to destroy, correct
IP (`192.168.20.30/24`), VMID (`20030`), zone (`mgmt_seg`), and node
(`pve-tiny`) -- this also caught that `lab_ip_cse_panel` needed adding
to `variables.tf`/`main.tf`'s hardcoded template-vars list, not just
`.env` (same class of gap as the earlier `cse_seg` lesson).

## Deploy pass (2026-09-19) — 5 more real bugs found, all fixed live

Executing the 5 operator-only actions surfaced 5 further real bugs,
none of which the file-authoring pass caught (they only show up when
actually running against live infrastructure):

5. `docker_registry_host` used in `deploy-cse-panel-stack.yml`'s
   daemon.json task but never defined anywhere in that playbook (every
   other stack's playbook defines it itself — it's not a role
   default). First real deploy attempt failed outright ("undefined").
6. `deploy-cse-controller.yml`'s early `docker compose up -d` tried to
   start **both** `controller` and `worker` before the venv (and
   celery inside it) existed — `worker`'s command execs a binary that
   isn't there yet on a fresh apply. Fixed: early start targets
   `controller` only; a new, later task starts `worker` after celery
   is actually installed.
7. `LAB_IP_CSE_PANEL` never reached Docker Compose's `${VAR}`
   substitution for `cse-controller`'s own compose file — Compose
   silently defaulted it to a blank string, breaking the worker's
   Redis URLs. Fixed with a `.env` file written into the stack
   directory (Compose auto-reads one there for substitution).
8. **The big one**: `cse-panel-stack`'s `redis` service had no
   `ports:` mapping at all, so port 6379 was reachable only inside
   that host's own Docker network — never from `cse-controller`, a
   different LXC on a different node. The worker's startup banner
   printing `transport: redis://192.168.20.30:6379/0` was **not**
   proof of a working connection (Celery prints the configured URL
   unconditionally at startup); the real first connection attempt
   came seconds later and failed with "Connection refused" for over
   two minutes until this was fixed and `cse-panel-stack` redeployed.
   Confirmed fixed by watching the worker's own logs reconnect for
   real (`Connected to redis://192.168.20.30:6379/0`) and pick up the
   already-queued test job (`Task cse_tasks.run_benchmark[...]
   received`).
9. The new hostnames (`cse-panel.lab.gibbsgreatly.xyz`,
   `cse-panel-flower.lab.gibbsgreatly.xyz`) didn't resolve at all
   after the Authentik/Traefik edge reconcile + `proxy-stack` redeploy
   -- DNS records only get regenerated and pushed to the live
   Technitium server (the actual DNS authority) when `technitium-stack`
   itself is redeployed, a separate step the plan's "5 operator
   actions" list didn't account for. Fixed by redeploying
   `technitium-stack` too; confirmed both hostnames resolve
   afterward.

**Verified independently after every fix, not just trusted from "ok"
status**: `terragrunt plan` clean (5 add/0 change/0 destroy, correct
IP/VMID/zone/node); all three `cse-panel-stack` containers up and its
`/healthz`/`/benchmarks` endpoints returning real data; the MikroTik
rule confirmed present with real non-zero packet/byte counters through
it; both new routes returning real, distinct Authentik OAuth redirects
(proof the proxy-provider objects were genuinely created per-route,
not stale/shared config); two existing consumers (Grafana, NetBox)
re-checked afterward and still returning their normal 302s -- no
regression from the `proxy-stack`/`technitium-stack` redeploys.

The first real end-to-end job (`mitre-frr`, 1 test case) ended up stuck
for 40+ minutes with near-zero CPU time -- genuinely hung, not just
slow (Framework's `/health` endpoint kept responding fine throughout,
so the server itself wasn't down). Superseded by the feature work
below, which needed a `cse-controller` redeploy anyway; the stuck job
was cleared by that restart. Root cause not investigated further --
noted here as a real, unresolved observation about Framework's
`llama-server` under this specific request, not a bug in the panel
itself.

## Backend selection + test suites (2026-09-19)

Two feature requests, both now live:

- **Backend selection**: `cse_tasks.run_benchmark` no longer hardcodes
  Framework's `llama-server` -- callers pass `backend_base_url`/
  `backend_model`/`backend_api_key` (all optional; default is still
  Framework's server, matching every benchmark proven so far). Works
  for any OpenAI-compatible server (Ollama's `/v1`, llama.cpp server's
  `/v1`, etc.) since CyberSecEval's own `OPENAI` provider class just
  points the `openai` SDK's `base_url` wherever it's told -- no new
  provider code needed. Deliberately does not manage model loading
  (assumes the engine already has one loaded, per the request).
  `panel-web` exposes a `GET /backends` preset list (currently just the
  one confirmed-real entry, `framework-llama-server`, plus `custom` for
  anything else -- no Ollama/llama.cpp presets added since there's no
  confirmed real endpoint for either in this lab yet to encode).
- **Test suites**: `POST /suites` submits a list of tests as one Celery
  `group` -- each test is still an independently trackable task (its
  own id, its own row in Flower), not one opaque long-running job,
  since the worker's concurrency is 1 anyway (one inference backend can
  only do one thing at a time regardless). `GroupResult.save()`/
  `.restore()` makes the group re-lookupable by id from a later,
  separate request (`GET /suites/{id}`).

**Verified for real, not just by reading the code**: `_build_mut_spec`
tested directly (default backend, and an explicit override matching
what a real Ollama endpoint would look like); the group
save/restore round-trip tested against the real Redis backend before
touching the actual worker; `index()` actually executed (not just
`py_compile`d) after adding the suite-submission form, same lesson as
before. After redeploying, submitted one job with an explicit backend
override and one 2-test suite for real -- confirmed via `docker top`
inside the worker container that the executed subprocess command line
carries the exact overridden `--llm-under-test=...` value, and via
`GET /suites/{id}` that both suite jobs are independently tracked.

**3 more real bugs found deploying this, all fixed live**:

10. `docker compose up -d`/`restart` does **not** restart a container
    just because a bind-mounted file it reads (`app.py`, `cse_tasks.py`)
    changed on disk -- only a real compose-file/image change does.
    Confirmed live: after redeploying with the new code, `/backends`/
    `/suites` still 404'd, and the container's own `StartedAt`
    predated the deploy. Fixed with an explicit
    `docker compose restart <service>` task in both
    `deploy-cse-panel-stack.yml` and `deploy-cse-controller.yml`.
11. That fix's first version gated the restart on the copy task's own
    `changed` flag -- which has a real gap: if the file already
    matched on disk from an *earlier* deploy that itself never
    restarted anything (exactly the state left by bug 10 before it was
    fixed), the flag reports no change and the restart never fires,
    even though the running process is still stale. Fixed by making
    both restarts unconditional (cheap, and simpler than getting
    change-detection right across this transition).
12. Once panel-web was actually restarted, its Flower link broke --
    `LAB_DOMAIN` resolved to a genuinely empty string inside the
    container (confirmed via `docker exec ... env`, not assumed), same
    root cause as the earlier `LAB_IP_CSE_PANEL` bug: the remote shell
    `ansible.builtin.command` runs in doesn't have the operator's local
    `LAB_DOMAIN` in its own environment, and Compose only auto-reads a
    `.env` file in the same directory as the compose file. Fixed the
    same way -- wrote that `.env` file explicitly.

## Results weren't actually visible through the panel (2026-09-19)

Operator question that surfaced a real gap: a completed job's result
only ever contained a return code, a `log_path` on `cse-controller`'s
own filesystem (unreachable from the panel or the browser), and which
backend ran -- never the actual benchmark outcome (MITRE's refusal/
malicious/benign breakdown, `instruct`'s vulnerable-code percentage,
etc.). Those numbers were sitting in `stat.json`/`stats.json` on disk
the whole time, just never read back.

Fixed: `run_benchmark` now reads whichever stat file the benchmark
actually wrote (`stat.json` for most; `stats.json` for
`malware_analysis`/`threat_intel_reasoning`/`multiturn-phishing`) and
inlines its parsed content into the Celery result under `"stats"` --
so `GET /jobs/{id}`'s `result` field now carries the real numbers, not
just metadata. Verified the read/parse logic against a realistic fake
stat file before deploying, then redeployed `cse-controller` for real.

## Framework `llama-server` failure modes -- two distinct kinds, found for real (2026-09-19)

The verification job left running above (`job_id
9d682665-f76b-4f48-bbfc-c6d2b554368f`) never resolved -- it, and three
other queued jobs behind it, sat stuck for 50+ minutes. Investigating
this properly (rather than just restarting and moving on) surfaced two
separate, real problems, one on Framework's side and one in the panel's
own worker config:

**On Framework's side -- not a panel bug.** `dmesg` on
`framework.gibbsgreatly.xyz` shows two distinct failure modes on the
same `ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan` build (confirmed
live via `docker ps`/`docker inspect`, not assumed from memory):
- A genuine **hang**: the requesting subprocess (confirmed via `docker
  top` -- exact expected command, `00:00:00` CPU time) sits alive doing
  nothing for 50+ minutes while `/health` keeps responding `200` the
  whole time. No kernel-level trace at all (`dmesg` shows nothing during
  the hang window) -- this is invisible below the application layer.
- A genuine **segfault crash** (`general protection fault` in
  `libc.so.6`, same crash offset both times): happened twice on
  2026-09-17, ~14:26 and ~14:28 **NZST** (framework's system clock is
  set to `Etc/UTC` as a deliberate server convention -- that is *not*
  the same as NZ local time, and this session initially got that
  conversion wrong before correcting it). Both times self-healed via
  Docker's restart policy within about a minute -- no manual
  intervention needed, unlike the hang.

Both known hangs and both known crashes happened in the NZ afternoon.
That's only 3-4 data points across 2 days, so it's a lead (maybe
thermal, maybe host load, maybe unrelated) not a confirmed cause. Not
investigated further -- this needs looking at directly on Framework
(GPU thermals/power state, the container's own resource limits) if it
keeps recurring; see `reference_framework_llama_server_real_hang` in
persistent memory.

**In the panel's own worker config -- a real, now-fixed bug.**
`cse_tasks.py`'s Celery app used Celery's default `task_acks_late =
False`, which acks (removes from the queue) a task the moment it's
handed to the worker process, not when it finishes. Restarting the
worker to clear the hang **silently and permanently lost** whatever job
was actually executing at that instant -- confirmed live: `9d682665` and
a second job (`081fe9c2`) never came back after the restart and will
sit at `PENDING` forever with nothing left to process them (harmless --
they'll just expire out of Redis on their own). Jobs that were merely
*queued but not yet started* did correctly get redelivered on restart.

Fixed: added `task_acks_late = True` and `worker_prefetch_multiplier =
1` to the Celery app config in `cse_tasks.py`, so a future killed/
restarted worker redelivers an in-flight job instead of dropping it
silently. This does not fix the underlying Framework hang/crash --
it just stops the panel from making a bad situation worse by losing
work on top of it. Deployed and live.

## Frontend redesign + reliability fixes (2026-09-19)

Direct operator feedback after using the panel for real: triggering
runs shouldn't go through Ansible (it doesn't -- that's already just
for code deploys; `/jobs`/`/suites` is and always was the real trigger
path), the deploy playbook was doing far more than a code push needs,
and both Flower and the homepage were showing far too much technical
detail (workers/queues/brokers/raw JSON) for what the operator actually
wants: which tests are queued/running/done, and what the results were.

**`deploy-cse-controller.yml` trimmed** -- four tasks that only matter
once, right after the initial checkout, were running on *every* deploy
(including a plain code push like the `acks_late` fix above) for no
benefit: `apt-get update`/install, the CyberSecEval unit test suite,
the CyberSOCEval_data submodule's recursive update, and the threat
intel report download. All four are now gated behind first-bootstrap
sentinels (a container-internal marker file for the apt tasks, since
package installs live in the container's writable layer, not the
`/srv/cyberseceval` bind mount that the other sentinels correctly use).
The report-download step is also now wrapped in `timeout 300` -- pulled
its real upstream source (`download_reports.py` at the pinned
PurpleLlama commit) and confirmed live that `requests.get()` there has
no timeout at all, which is the actual, mundane reason that step was
seen hanging (a slow/unresponsive third-party report host, nothing to
do with CyberSecEval or Framework). A code-only push to `cse-controller`
now goes straight to copy-file-and-restart-worker, confirmed by
redeploying with the `acks_late` fix under the new lighter path.

**`panel-web`'s `app.py` homepage rewritten.** Checkbox benchmark
picker + backend dropdown + Run button, replacing the JSON-textarea
suite form and the `alert(JSON.stringify(...))` result popups. A status
table polls `/jobs` and `/suites` every 4s and renders plain-language
rows (benchmark, backend, state, result) -- Flower and the raw JSON
endpoints moved into a de-emphasized `<details>` "Advanced / API"
section rather than removed (still useful for debugging, operator
doesn't need them day-to-day).

Job/suite metadata (benchmark, backend, submitted-by, submitted-at) is
now stored explicitly in Redis at submission time (`cse_panel:job_meta:
<id>` / `cse_panel:suite_meta:<id>` hashes, `EXPIRE`d at 86400s to
match Celery's own default `result_expires`) -- before this, `GET
/jobs`/`/jobs/{id}` only ever had a bare Celery state code, nothing
about *what* the job actually was. Pre-existing jobs from before this
change correctly degrade to `"?"` fields rather than erroring.

**Result formatting made genuinely readable, not just present.** The
first version of the results fix (above) put raw stats into the
response, but `mitre`'s real shape (`{<model-path>: {<category>:
{refusal_count, malicious_count, benign_count, total_count,
benign_percentage}}}`) is nested two levels deeper than `mitre-frr`'s
flat shape, so the first flattening pass produced an empty summary for
a `mitre` job that had actually succeeded -- caught by the operator
running a real `mitre` test through the new UI and asking why the
result looked empty. Fixed with a proper recursive flattener
(`_flatten_stats` in `app.py`) that: collapses a dict with exactly one
key wrapping another dict (mitre's redundant model-name wrapper);
recognizes a "count cluster" (a `total_count` sibling plus one or more
`*_count` fields) and renders it as `"Malicious: 1/1 (100%)"` instead of
raw field names; and falls back to humanized labels (`benign_percentage`
-> `Benign Percentage`) plus rate/percentage-aware formatting
(`0.4123` -> `41.2%`) for anything else. Verified against both real
shapes with plain-`python3` logic checks (no server needed, this is a
pure function) before deploying, then confirmed live against the
operator's actual `mitre` job.

Honest scope limit: this is tuned against the two shapes actually seen
(`mitre`, `mitre-frr`). The other 8 benchmarks may render less
informatively until their real `stat.json`/`stats.json` shapes are seen
and the same tuning is applied -- see "Known non-blocking gaps" at the
top of this file.
