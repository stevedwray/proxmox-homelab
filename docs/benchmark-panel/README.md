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
- **`task/benchmark-panel-plan`:** superseded; its one commit was
  cherry-picked onto `task/cse-model-identity`.
- `stable` already has llama-swap (#456) and CSE run metrics (#457).

**Phase 1 (deployed):**
- CSE runs record `served_model` and the reports show it.
- The panel has a Model column.
- The 65536 cap applies to every model with a base URL.
- Not yet seen on a real run (it needs a GPU run, which the operator
  starts).

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

**Phase 2 (next): how to build it.**
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

**Phases 3–4 (after phase 2):**
- **Phase 3:** the Dash Eval battery tab on `/eval/api/*`, then retire
  the old HTML page.
- **Phase 4:** a chart that plots each run's real headline, labelled by
  model, plus a tokens/s and duration chart. CSE headline rows go into
  Nextcloud Tables "Model evaluations", and the Compare tab reads that
  table.

## Log

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
