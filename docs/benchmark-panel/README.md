# benchmark-panel (planning workspace)

One Dash control panel for every benchmark: CyberSecEval and the eval
battery (GPQA, IFEval, BFCL, AgentBench, RepoBench). Every run records
which model answered, its scores, duration, tokens and tokens/s, and
both kinds of run share one queue for Framework.

Status: **decisions made; phase 1 deployed (2026-10-08); phase 2 next.** See
[plan.md](plan.md).

## Where things stand (2026-10-08)

**Branches:**
- **`task/cse-model-identity`:** phase 1 code plus this plan. Deployed to
  pve-tiny. Not pushed or merged; the operator decides.
- **`task/framework-run-lock`:** phase 2, cut from
  `task/cse-model-identity` (so it carries phase 1 too). Deployed to
  pve-tiny 2026-10-08; not pushed or merged.
- **`task/benchmark-panel-plan`:** superseded; its one commit was
  cherry-picked onto `task/cse-model-identity`.
- `stable` already has llama-swap (#456) and CSE run metrics (#457).

**Phase 1 (deployed):**
- CSE runs record `served_model` and the reports show it.
- The panel has a Model column.
- The 65536 cap applies to every model with a base URL.
- Seen on a real run: MITRE job `ebe57cd0` (2026-10-07) recorded
  glm-5.3-flash, its GGUF path, build b11309-a4d880fd5 and 131072 ctx.

**Eval battery today:**
- **Already has:** which model answered (`runmeta.py`, `run.json`) and
  start/finish times.
- **Missing:** tokens and tokens/s, the shared Framework lock, a Dash
  tab, and Compare.
- Reasoning effort isn't visible through llama-server's API. It's
  recorded only through `eval-run --note`. Idea, not done: llm-control
  entry names that carry the effort (e.g. `qwen3.8-flash-next-xhigh`).
  The alias is the entry name, so both systems would record it
  automatically.

**Phase 2 (built 2026-10-08, see "Phase 2 as built" below).** The
original build notes:
- **The lock.**
  - A Redis key on cse-panel's Redis, e.g. `framework:run-lock`, set
    with NX and a TTL, holding `{job_id, suite, benchmark, started}`.
  - The holder renews it every ~60 s while its run is active.
  - The eval worker (`eval_tasks.py`, which today uses
    `framework_idle()` and `wait_until`) and the CSE worker
    (`cse_tasks.run_benchmark`) both acquire it before a run and release
    it in `finally`.
  - The panel shows the holder.
  - The CSE side has no wait or state machinery yet. Add a "waiting for
    Framework" job state that the panel's `_state_label` understands.
- **Eval metrics.**
  - In `eval_tasks.py`, snapshot Framework's `/metrics` before and after
    the run: `llamacpp:tokens_predicted_total`,
    `tokens_predicted_seconds_total`, `prompt_tokens_total` and
    `prompt_seconds_total`. ai-services-stack reaches :8080 with the API
    key.
  - Compute CSE's `run_metrics` fields (`model_under_test`: tokens,
    tokens/s; duration).
  - If a counter went down, mark the result unavailable: the model was
    reloaded.
  - Store it in the job record and `run.json`. Then show it in the Eval
    page and publish it in the Nextcloud report and as Tables columns.
- **Where it deploys:** cse-controller and cse-panel-stack with
  `./with-secrets-prod-tiny scripts/provision.sh --stack <name>`, and the
  ai-services-stack eval-runner play per `docs/eval-runner/README.md`.
  All on pve-tiny; check that no job is running first.

**Phase 2 as built (`task/framework-run-lock`):**
- **The lock:** `terraform/lxc/ansible/files/framework-lock/framework_lock.py`,
  one file copied next to each worker by its playbook. Key
  `framework:run-lock` in cse-panel's Redis DB 1 (both workers' result
  backend), value `{job_id, suite, benchmark, started}`, NX with a 180 s
  TTL, renewed every 60 s by a thread while the run is active, released
  in `finally`. A dead worker frees Framework within 3 minutes. A job
  redelivered after a worker restart has the same id, so it takes its
  own lock back at once.
- **CyberSecEval:** `run_benchmark` takes the lock only when the backend
  is Framework's host. While waiting, its Celery state is `WAITING` with
  the holder in its meta; once it holds the lock it reports `STARTED`.
  Before this, running CSE jobs showed "Queued", because the worker never
  reported STARTED. It gives up after 12 h. Cancelling a waiting job from
  the panel works as before (revoke with SIGTERM).
- **Eval battery:** the lock replaces the idle-slots wait. The "another
  eval run" wait stays, for runs started over ssh. The lock is held from
  launch until the container exits. Publishing happens after release.
- **Eval run metrics:** `/metrics` counters are read just before
  `eval-run` starts the run and again after the container exits. They
  give `run_metrics` in CSE's shape: `duration_seconds` plus
  `model_under_test {prompt_tokens, completion_tokens, prompt_seconds,
  generation_seconds, generation_tokens_per_second,
  prompt_tokens_per_second}`. If a counter went down, `unavailable`
  replaces the token figures. They go in the job record and the run's
  `run.json`, where a resumed run's segments are summed. `publish.py`
  adds a "Run metrics" section to each run's `report.md` and columns
  `Duration (min)`, `Tokens generated` and `Tokens/s` to the Tables rows,
  views and xlsx. Runs from before phase 2 have none.
- **Panel:**
  - panel-web `GET /framework` returns the lock holder plus the eval
    worker's Framework status (loaded model, busy slots).
  - The Dash header shows "Framework: <model> · free" or "· busy with
    <suite> <benchmark> (job …); new benchmark runs wait".
  - The CSE jobs table shows "Waiting for Framework (eval bfcl)".
  - The Eval page shows the holder and each run's duration, tokens and
    tokens/s.
- **Tests:** `framework-lock/test_framework_lock.py` (8),
  `test_cse_framework_lock.py` (5), plus new cases in `test_eval_tasks.py`
  and `test_publish.py`, and panel tests for `/framework` and the
  WAITING label.
- **Deploy order:** ai-services-stack eval worker, then cse-controller,
  then cse-panel-stack. Either worker without the other would run
  unlocked against the other side, so deploy both back to back with
  nothing running. The panel is display only.

**Phases 3–4 (after phase 2):**
- **Phase 3:** the Dash Eval battery tab on `/eval/api/*`, then retire
  the old HTML page.
- **Phase 4:** a chart that plots each run's real headline, labelled by
  model, plus a tokens/s and duration chart. CSE headline rows go into
  Nextcloud Tables "Model evaluations", and the Compare tab reads that
  table.

## Log

- 2026-10-08, phase 2 deployed (`task/framework-run-lock`, 8f7f01e9),
  approval `framework-run-lock`, in order:
  - ai-services-stack eval-runner play: image rebuilt, `eval_tasks.py`
    and `framework_lock.py` installed, both workers restarted and
    active.
  - `provision.sh --stack cse-controller`: `cse_tasks.py` and
    `framework_lock.py` written, worker restarted and ready. The one
    ignored error is node_exporter's optional step-ca reachability probe,
    unrelated.
  - `provision.sh --stack cse-panel-stack`: panel-web and the Dash UI
    restarted, with no errors in the UI log.
  - Live check: `GET /framework` returned `lock: null`,
    `model: glm-5.3-flash`, 0 of 4 slots busy.
  - Not yet seen: a real run taking the lock, or eval run metrics.
    Both need a GPU run, which the operator starts.
  - Noticed, not changed: the Celery workers log "clock drift 46800 s"
    (exactly 13 h) between ai-services-stack and cse-controller. That
    looks like a timezone difference in Celery's event timestamps, not
    real clock skew. The lock doesn't depend on it: its TTL is
    Redis-side, and its timestamps are UTC.

- 2026-10-08, phase 1 (`task/cse-model-identity`):
  - `cse_tasks.py` records `served_model` from the backend's
    `/v1/models` and `/props` at the start and end of each run, and
    flags a mid-run change. Reports show `**Model:**`; the panel has a
    Model column and a Model line in the run detail.
  - The cse-lab cap is now 65536 for any model with a base URL. It was
    16384 for named models.
  - 6 new unit tests. A live read from the worker container returned
    glm-5.3-flash, its GGUF path, build b11309-a4d880fd5 and 131072
    context.

Related workspaces:
- `docs/cyberseceval-panel/`: the CyberSecEval panel and controller.
- `docs/eval-runner/`: the eval battery, its worker and the current
  HTML page.
- `docs/llama-swap/`: the llm-control page that loads models on
  Framework.
- `docs/reporting-platform/`: the shared report convention.
