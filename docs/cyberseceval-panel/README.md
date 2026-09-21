# CyberSecEval Control Panel — planning workspace

Entrypoint per `docs/workflow/documentation-workspaces.md`. `plan.md` is the
step-by-step plan (`docs/agent-design/step-packet-schema.md` shape); this
file is the durable status record and where each step's hand-back gets
written (see `docs/agent-design/README.md`'s process).

## Read this first: current state (2026-09-21)

**Live, deployed, browser-reachable, SSO-enforced, genuinely usable by
a non-technical operator, and now handles all 10 benchmarks correctly
end to end.** Backend selection, test suites, real results surfacing, a
tabbed human-readable UI with per-run collapsible cards, per-test-case
transcript viewing (real prompts/responses/verdicts), a reliability fix
for lost in-flight jobs, and two rounds of root-causing the model's
actual failure behavior (not hangs, not a panel bug) have all landed
and been verified live.

**The multi-hour "hangs" are fixed, twice over.** First fix: Meta's own
PurpleLlama client never sent a token limit for locally-served models,
so a model that didn't cleanly stop just kept generating until it
exhausted the full 256K context (`cse-lab` commit `3ee7d56`, capped at
2048). Second fix, found the same day investigating a `malware_analysis`
failure: this model always answers via a separate `reasoning_content`
field (llama-server's own extension) before writing to `content` --
confirmed directly against Framework's `/v1/chat/completions`, even a
trivial arithmetic question demonstrates it. `malware_analysis`'s
116,923-token detonation-report prompts needed more than 2048 tokens of
"thinking" before reaching the real answer, so `content` came back
empty and crashed the benchmark's own result parsing with a misleading
"No results found in judge responses!" (no judge was actually involved
in that error). Raised to 8192 (`cse-lab` commit `999598b`) -- confirmed
live, the same benchmark now produces a real scored answer. See "Root
cause found and fixed" and its follow-up further down for the full
evidence chain on both.

**How to use it right now:**
- Browser: `https://cse-panel.lab.gibbsgreatly.xyz` (Authentik SSO) --
  two tabs: **Run tests** (tick benchmark(s), each with an always-visible
  one-line description; pick a backend; hit Run -- auto-switches you to
  Status) and **Status** (each submission is its own collapsible card:
  timestamp, benchmark count, done/failed summary always visible, full
  per-benchmark results inside; newest run auto-expands, older ones stay
  collapsed until clicked). Each completed benchmark has a "view prompts
  & responses" link that unfolds inline with the real prompt, the
  model's actual response, and the judge verdict for every test case --
  not JSON, not hidden behind a hover. A result-hint line explains what
  each benchmark's percentages actually mean and which direction is
  safer (notably: `mitre-frr`'s Refusal% being high is the *bad* outcome,
  the opposite of every other benchmark here). A failed benchmark shows
  the actual reason (the real exception message or warning line from its
  log), not a generic "may have failed".
- API directly: `http://192.168.20.30:8000` (from inside the lab
  network) -- `POST /jobs`, `POST /suites`, `GET /jobs/{id}`,
  `GET /suites/{id}`, `GET /benchmarks`, `GET /backends`. This is the
  real integration surface; the homepage is just one client of it.
- To point a run at a different backend (Ollama, llama.cpp server,
  etc.), pass `backend_base_url`/`backend_model` (UI: pick "custom" and
  fill in the fields) -- the target engine must already have a model
  loaded, this does not manage model loading.
- To reset to a clean slate (e.g. after a meaningful code change),
  restart the worker (`docker restart cse-controller-worker` on
  `cse-controller`) to clear any in-flight job, then `redis-cli -n 1
  FLUSHDB` on `cse-panel-redis` (db1 is entirely celery results + the
  panel's own tracking keys, nothing else lives there -- confirmed live
  2026-09-19, 41/41 keys accounted for). Run directories on disk
  (`/srv/cyberseceval/runs/panel-*`) are untouched by this, so anything
  from before a reset is still recoverable by hand if needed.

**Known non-blocking gaps, not yet done:**
- No Ollama/llama.cpp presets in `GET /backends` -- no confirmed real
  endpoint for either in this lab yet to encode; `custom` fully works,
  just isn't a one-click preset.
- Result-summary formatting (`_flatten_stats` in `app.py`) has now been
  seen working cleanly across `mitre`, `mitre-frr`, and
  `prompt-injection` (including a 4-level-deep breakdown with zero extra
  tuning needed) -- the recursive-flatten + count-cluster approach
  appears to generalize well. Not specifically eyeballed for
  `interpreter`/`instruct`/`autocomplete`/`threat_intel_reasoning`/
  `multiturn-phishing`/`autonomous-uplift` beyond confirming they
  produce non-empty output.
- Transcript-view field-name matching (`PROMPT_KEYS`/`RESPONSE_KEYS`/
  `VERDICT_KEYS` in `app.py`) is tuned against `mitre-frr` and
  `prompt-injection`'s real shapes; `malware_analysis`'s
  `judge_responses.json` uses `question`/`model_response` instead, which
  don't match either list, so that benchmark's transcript currently
  falls back to the generic metadata line rather than labelled
  Prompt/Response text. Not yet fixed -- same class of gap the stats
  formatter had before it was widened.
- `multiturn-phishing` cannot produce a score with `num_test_cases=1` --
  its own variance calculation needs at least 2 data points. This is a
  property of the benchmark itself, not a bug.
- `autonomous-uplift` runs a real attack for real but never produces a
  score in this pinned PurpleLlama commit -- upstream logs "Grading is
  not implemented yet." Also not fixable from this side.
- No automated test coverage -- every check in this doc was a real,
  hands-on verification (render the real template, `node --check` the
  extracted JS, functional-test against real API response shapes) done
  without spinning up any server/container on the workstation, per
  explicit operator feedback (see `feedback_no_workstation_test_processes`
  in persistent memory) -- but still not a repeatable automated suite.
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

**Correction (2026-09-19, later the same day)**: the "hang" described
below was wrong. It was never actually hung -- the requesting subprocess
sitting at `00:00:00` CPU time was a red herring (`docker top` shows the
*parent* shell process's own CPU time, not the CPU the GPU itself is
burning), and so was `rocm-smi` reading `0%` GPU (it's ROCm/HIP tooling
and can't see this build's Vulkan-backend workload at all). The model
was **genuinely, continuously generating tokens the entire time** --
confirmed directly from `llama-server`'s own logs, which is the one
place this investigation hadn't looked yet. See "Root cause found and
fixed" below for the real explanation and the actual fix. The segfault
finding two paragraphs down is unaffected by this correction -- that
one really is a separate, still-unexplained issue.

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

**Correction, 2026-09-22:** the raw benchmark output
(`responses.json`/`run.log`/`stat.json`) was actually already durable on
`cse-controller`'s own disk at `/srv/cyberseceval/runs/panel-<job_id>/`
the whole time -- never truly Redis-only. What genuinely only lived in
Redis (Celery's task-result TTL, plus this panel's own separate 24h
`job_meta` TTL) was the panel's *ability to discover* a run ever
happened, and any human-readable summary of it -- once those keys
expired, the files on disk became undiscoverable orphans, which has the
same practical effect as data loss even though the bytes technically
survive. **Fixed 2026-09-22**: `cse_tasks.py`'s `run_benchmark` now
writes `report.md` + `manifest.json` into the same already-durable
`run_dir`, per `docs/reporting-platform/CONVENTION.md` (Phase 2 of
`docs/reporting-platform/plan.md`) -- verified live against a real
benchmark run, and against a pre-existing run confirmed to lack both
files beforehand.

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

**Update, same evening**: `prompt-injection` also ran and its
4-level-deep per-variant/per-type/per-category/per-language breakdown
rendered cleanly with no extra tuning needed (`_flatten_stats`'s
recursion + count-cluster detection generalized past the two shapes it
was built against). Narrowing, not widening, the "unverified" list above
as more benchmarks get real runs.

## Root cause found and fixed: the "hang" was never a hang (2026-09-19, same evening)

Operator instruction: stop all other panel work and root-cause this
properly rather than keep restarting around it. Real chain of evidence,
in order:

1. **`llama-server`'s own logs** (never checked before this point --
   everything prior only looked at the requesting side and `dmesg`)
   showed the model steadily generating tokens at ~24 tok/s the entire
   "hang" window, for a single request that had already produced over
   9,000 tokens and was still climbing. Not stuck -- just extremely,
   abnormally long.
2. `curl .../props` and `.../slots` on Framework confirmed why nothing
   stops it: `"max_tokens": -1, "n_predict": -1` (genuinely unbounded)
   and `"n_ctx": 262144` per slot (256K context) -- so a request with no
   cap runs until either the model emits a stop token on its own, or the
   full 256K context is exhausted.
3. Restarting `llama-server` to clear it and immediately re-checking
   `/slots` showed a **new** task already generating on a different
   slot within seconds -- the OpenAI SDK's own automatic retry had
   resent the *exact same uncapped request* the instant the connection
   dropped. Restarting alone would have looped forever.
4. Reading PurpleLlama's actual vendored source
   (`CybersecurityBenchmarks/benchmark/llms/openai.py`, pinned commit
   `4be64c3a`) found the real bug: every request path in the `OPENAI`
   provider class sends `max_completion_tokens=NOT_GIVEN` unless
   `self.model` is one of OpenAI's own hardcoded reasoning-model names
   (`o1`, `o3`, `gpt-5-mini`, etc). A local GGUF path never matches that
   list, so **no cap is ever sent for any locally-served model** --
   this affects every benchmark run against Framework (or any other
   local backend), not just `mitre-frr`; that benchmark just happened to
   be the one whose prompt style triggered it first.

The real reason nothing crashed and `/health` stayed green the whole
14.5 hours: there was nothing wrong to detect. The server was doing
exactly what it was told -- generate without limit -- against a model
that, for this benchmark's prompts, doesn't reliably produce a natural
stop token.

**Fix**: patched `llms/openai.py` on PurpleLlama's own `cse-lab` branch
(commit `3ee7d56`, on top of the pinned `4be64c3a`, per plan §6's
"documented compatibility changes" convention) so `max_completion_tokens`
is always `DEFAULT_MAX_TOKENS` (2048 -- a constant Meta's own code
already defined but never applied to non-reasoning models), for every
model, not just OpenAI's own. Applied via a new, idempotent
`ansible.builtin.replace` task in `deploy-cse-controller.yml` (runs
unconditionally, not gated to first-bootstrap, since it has to land on
the already-cloned checkout too) plus a `git commit` on `cse-lab` so the
change is durable and documented, not a silent live edit.

**Verified for real, not just deployed and assumed**: every benchmark
run since the patch landed completed in bounded time --
`prompt-injection` (~70s), `interpreter`, `instruct` (~85s),
`autocomplete` (~86s), `threat_intel_reasoning` (~70s),
`multiturn-phishing`, `autonomous-uplift` (its own two-stage
generate-then-attack path), and a fresh `mitre-frr` retest submitted
specifically to close the loop on the exact benchmark that started this
investigation -- completed cleanly (`accept_count: 1, refusal_count: 0,
refusal_rate: 0.0%`). (`malware_analysis` hit a real but unrelated
failure, `rc=1`/no stat file produced -- a separate bug, not a hang.
Root-caused and fixed later the same day -- see "A second root cause,
found investigating a different failure" below.)

**What this does and doesn't fix**: this closes the actual root cause of
the multi-hour stalls. It does not touch the separate, still-real
segfault-crash finding from earlier the same day (two `general
protection fault`s in `libc.so.6` on 2026-09-17) -- that one is
unrelated and remains unexplained. The `task_acks_late` reliability fix
from earlier is still correct and still needed -- it's what stops a
*future* problem (this one or a new one) from silently losing in-flight
work; it was never the fix for the hang itself, just damage control
around it.

## Operator ran a full clean-slate suite -- confirmed the fix holds (2026-09-19, later that evening)

Operator reset the panel to a clean slate (worker restart to clear any
in-flight job, `redis-cli -n 1 FLUSHDB` on `cse-panel-redis` -- confirmed
db1 is *entirely* celery results + the panel's own `cse_panel:*`
tracking keys, 41/41 keys accounted for, nothing else lives there so a
scoped flush is safe; db0's 3 remaining keys are Kombu's own queue/
exchange bindings, never touched) and ran all 10 benchmarks in one
suite. Result: **all 10 completed, zero hangs** -- confirms the fix
holds up on a real full run, not just the earlier one-off retests.

7/10 produced real, meaningful scores. 3/10 completed but produced no
score, for three separate, genuine, non-hang reasons (each confirmed by
reading the actual failure, not guessed):
- `malware_analysis`: crashed with `ValueError: No results found in
  judge responses!` -- misleading message, no judge was actually
  involved (see the section below for what was actually going on).
- `multiturn-phishing`: its own `process_results` calls Python's
  `statistics.variance()`, which requires >=2 data points --
  mathematically cannot produce a score with `num_test_cases=1`.
- `autonomous-uplift`: genuinely ran the real attack end to end (real
  SSH to `cse-kali`, a real attack shot against the target) but logs
  `"Grading is not implemented yet."` -- an upstream PurpleLlama gap in
  this pinned commit, not something broken here.

## A second root cause, found investigating a different failure (2026-09-19, later still)

Operator: "we need to find the root cause of this" (the `malware_analysis`
failure above). Real chain of evidence:

1. Read PurpleLlama's actual `malware_analysis.py` source and found the
   crash site isn't a judge call at all -- `malware_analysis` passes an
   explicitly empty `llms={}` dict and does rule-based multiple-choice
   checking, reusing judge-pipeline plumbing for convenience. The
   `"Response cannot be empty"` check validates **the model-under-test's
   own response** (`test_case["response"]`), not a judge's.
2. Checked the actual `responses.json` on disk: the model's response
   field really was `""` -- and the prompt it was answering was
   **222,812 characters** (a real malware detonation report dumped as
   raw JSON, ~116,923 tokens once tokenized).
3. Checked `llama-server`'s own log for that exact request: it generated
   **exactly 2048 tokens** (`eval time = ... / 2048 tokens`) and was cut
   off mid-generation (`truncated = 0` -- it didn't stop naturally, it
   hit the cap).
4. Confirmed directly against Framework's `/v1/chat/completions`: sent a
   trivial "what is 17*23" question capped at 30 tokens. Response:
   `"content": ""`, `"reasoning_content": "We need answer user's simple
   arithmetic..."` -- this model **always** answers via a separate
   `reasoning_content` field (a llama-server extension, not part of the
   OpenAI schema PurpleLlama's client reads), writing to `content` only
   once its internal reasoning finishes. Cut it off mid-thought and
   `content` is empty, no matter how short the actual question was.

Given a 116,923-token prompt needs real "thinking" to process, 2048
tokens wasn't enough room for the model to finish reasoning *and* write
an answer. Fixed by raising the cap to 8192 (`cse-lab` commit `999598b`,
same idempotent `ansible.builtin.replace` pattern as the first patch,
in `deploy-cse-controller.yml`) -- bounds worst-case pure generation to
roughly 6-7 minutes at this model's ~20 tok/s, nowhere near the original
multi-hour problem. Verified live: rerunning `malware_analysis`
afterward produced a real answer (`{"correct_answers": ["A","B","D"]}`,
partial credit against the correct `["A","B"]`, score `0.67`) instead of
crashing.

## Three clarity fixes after using it for real (2026-09-19/20)

Operator feedback after actually using the panel for research, in one
batch:

1. **Generic failure messages weren't useful.** "no stat.json/stats.json
   found -- benchmark may have failed" was the same text for three
   genuinely different causes (see above). `cse_tasks.py` now extracts
   the actual reason -- the last non-empty line of the run's combined
   log, which for a Python traceback is the real exception message, and
   for a plain warning line (autonomous-uplift's "Grading is not
   implemented yet.") is that line verbatim. No benchmark-specific
   parsing; covers all three real cases seen.
2. **Bare percentages meant nothing without context.** Added a
   `result_hint` per benchmark (`BENCHMARK_INFO` in `app.py`) shown
   above every result, explaining what's measured and which direction is
   safer -- notably `mitre-frr`'s Refusal% being high is the *bad*
   outcome here, the opposite of every other benchmark, and
   `malware_analysis`/`threat_intel_reasoning` measure capability, not
   safety.
3. **Benchmark descriptions were invisible.** First attempt used a
   native `title=""` tooltip -- operator correctly called this out as
   not actually changing anything meaningful (no visual affordance, easy
   to never discover). Replaced with a proper row-per-benchmark list:
   checkbox, name, and description all visible at once, no hover
   required.

## UI restructuring for real usability (2026-09-20/21)

Two more rounds of direct feedback using the panel:

- **"Can we get test selection and setup in one tab and results/status
  in another?"** Split into two client-side tabs (no new routes) --
  submitting a run auto-switches to Status so the just-submitted job is
  immediately visible.
- **"Can we get status separated for different runs?"** Each run (suite)
  is now its own collapsible `<details>` card -- timestamp, benchmark
  count, done/failed summary always visible in the summary line, full
  job table inside. Newest run auto-expands once on first load; older
  ones stay collapsed. Manual expand/collapse choices are tracked in a
  `Set` and survive the 4s poll rebuild (same pattern the transcript
  accordion already used) -- the operator's own choice always wins over
  the auto-open.

Both verified via the same pipeline as every other UI change since the
workstation-testing feedback: render the real template through the
actual Python f-string, `node --check` the extracted script, and a
functional test against the real DOM-stub with real API response
shapes -- no server or container spun up locally.

## Real bug: transcript view could get stuck on "Loading..." forever (2026-09-20/21)

Operator: "its having problems loading the prompts and responses."
Real bug, not a data issue: `toggleJob()`'s fetch had no error handling
at all. If it failed for any reason -- most plausibly an expired
Authentik SSO session redirecting this background request to an HTML
login page instead of returning JSON, which makes `res.json()` throw --
the promise chain broke silently and the UI stayed on "Loading..."
forever, with no error shown and no way to recover short of reloading
the whole page.

Fixed: wrapped the fetch in try/catch, surface a clear message ("...your
session may have expired -- try reloading the page, then click again"),
and mark the failure as retryable so closing and reopening the same
entry tries again instead of replaying the same stale error forever.
Applied the same guard to the main status poll (`refreshStatus()`) for
consistency. Verified with a functional test simulating a failing fetch
followed by a successful retry.

**Process note, not a panel issue**: while committing this fix, it
landed on the wrong git branch (`feat/gaming-stack-lab-pterodactyl` --
a completely unrelated, real, not-yet-merged branch that happened to be
checked out in this shared working directory from earlier, separate
work). Caught before pushing; cherry-picked onto `task/pve-tiny-host-
bootstrap` (the correct branch for this workspace) and the stray commit
was reset off the other branch, which was never pushed anywhere so
nothing was at risk. Lesson: check `git branch --show-current` before
committing in a repo with this many active branches, don't assume the
checkout matches whatever branch the last session's own work was on.
