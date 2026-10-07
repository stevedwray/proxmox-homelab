# Benchmark panel: one control panel for every benchmark

Status: **decisions made (2026-10-08): the operator accepted every
recommendation below. Phase 1 is in progress.**

## Goal

One Dash panel (`https://cse-panel.<domain>`) to start, watch and compare
every benchmark against whatever model Framework serves:

- CyberSecEval (10 benchmarks);
- the eval battery (GPQA, IFEval, BFCL, AgentBench, RepoBench).

Every run should record the same facts: which model answered, its scores,
duration, tokens used, and tokens/s. Models are still loaded on
`https://llm-control.<domain>` (`docs/llama-swap/`).

## Where things stand (2026-10-08)

Two systems share cse-panel's Redis and Framework :8080, but nothing
else:

| | CyberSecEval | Eval battery |
|---|---|---|
| Docs | `docs/cyberseceval-panel/` | `docs/eval-runner/` (`plan.md`, `panel-plan.md`, `findings.md`) |
| UI | Dash, `cse-panel.<domain>` (`app-ui/app.py`) | HTML page on panel-web, `cse-panel-api.<domain>/eval` (`app/eval_battery.py`), linked from the Dash header |
| Worker | `cse-controller` (cse_seg), Celery default queue, `cse_tasks.py` | `ai-services-stack` (ai_seg), queues `eval-runner` and `eval-runner-ctl`, `eval_tasks.py` → `eval-run` |
| Records which model answered | **No.** Only the preset label: the default preset always says the old Qwen GGUF path | **Yes.** `runmeta.py` records `/v1/models` and `/props` (alias, path, build, n_ctx, sampling, chat-template hash) in `run.json` |
| Tokens, tokens/s | **Yes**, since 2026-10-07: `run_metrics` from a per-call usage log | **No.** Start and finish times only |
| Waits for Framework | **No** | **Yes:** waits until `/slots` shows no busy slot (polls every 60 s, up to 12 h) |
| Durable record | `report.md` on cse-controller, and Nextcloud `Reports/CyberSecEval/…` folders | Nextcloud Tables "Model evaluations" (one view per benchmark), `leaderboard.xlsx`/`.md`, per-run `report.md` |
| Panel history | Only what Redis still holds (24 h job metadata, then results expire) | `/eval/api/state` jobs list |
| Charts | Misleading: plots each run's *first* percentage (MITRE: C2 refusal, 0 or 100), labelled by job id | None in the panel; the leaderboard is in Nextcloud |

Facts checked for this plan:
- `/eval/api/state`, `/eval/api/jobs` (POST), `…/cancel`, `…/resume` and
  `/eval/api/publish` are already JSON endpoints on panel-web. Each job
  carries `task, mode, limit, note, state, started, finished, results,
  log_tail, published`. A Dash tab can use them unchanged.
- llama-server's `/metrics` exposes counters that only grow between
  model loads: `llamacpp:tokens_predicted_total`,
  `tokens_predicted_seconds_total`, `prompt_tokens_total` and
  `prompt_seconds_total`. A before/after snapshot gives a run's tokens
  and tokens/s, as long as nothing else used Framework meanwhile. A
  model reload resets them, which shows up as a negative delta.
- Both workers already reach Framework :8080 and the panel's Redis.

## What stays the same

- No new stacks or network paths. cse-controller and ai-services-stack
  keep their workers. Redis on cse-panel-stack stays the queue for both.
- `eval-run` stays the eval battery's single entry point, and PurpleLlama
  is run as now.
- Nextcloud stays the durable record.
- Loading models stays on llm-control.

## Proposed design

### A. One Dash panel with tabs

- **Tabs:**
  - **CyberSecEval**: today's Run and Results.
  - **Eval battery**: a Dash rebuild of the HTML page, calling the
    existing `/eval/api/*` endpoints. That covers start (benchmarks,
    full/pilot/limit, note, 32k budget), the job list with log tail,
    cancel, resume, publish and the Nextcloud links.
  - **Compare**: see D.
- **Header:**
  - the model currently loaded, from the Framework status the eval worker
    already writes to Redis every 30 s;
  - a link to llm-control;
  - who is using Framework (see C).
- **Retire the old page.** Once the tab covers it, remove the HTML page
  and the header link (`eval_battery.py`'s HTML route only; its API
  stays).

### B. The same run record for every run

- **Which model answered (CyberSecEval).** At run start, `cse_tasks.py`
  reads the backend's `/v1/models` and `/props`: the same fields
  eval-runner's `runmeta.py` records. They go in `result["model"]`. The
  panel, `report.md` and Nextcloud show the real model name, not the
  preset label.
- **Run metrics (eval battery).** `eval_tasks.py` snapshots the four
  `/metrics` counters before and after each run. That gives:
  - generated and prompt tokens;
  - generation and prompt tokens/s;
  - duration (already recorded).

  It's marked "unavailable" when a counter went down (the model was
  reloaded mid-run). It's only exact when no other client used Framework
  during the run, which C provides. The result goes into `run.json`, the
  job record and the Nextcloud report, plus new columns in the Tables
  views.
- **Same names on both sides.** Both systems use the field names
  CyberSecEval's `run_metrics` already uses, so the panel renders them
  with one piece of code.
- **Fix in passing:** the cse-lab answer cap is 16384 tokens for model
  names that don't start with `/` (e.g. `glm-5.3-flash`). It should
  apply 65536 to every Framework-served model.

### C. One queue for Framework

- **A Redis lock** (for example `framework:run-lock`, holding the job id
  and suite, renewed while the run is active) that both workers take
  before a run and release after.
  - CyberSecEval jobs wait their turn, as eval jobs already do. Today
    nothing stops a CSE run and an eval run from overlapping.
  - The panel shows "waiting for Framework (held by <job>)".
- **It replaces the eval worker's "wait for idle slots" check.** That
  check also waits for interactive clients, which can hold a run up for
  hours.

### D. Results and comparison

- **Replace the CyberSecEval chart:**
  - one bar per run with the benchmark's real headline, labelled by
    model and time (for MITRE: the overall malicious/benign/refusal
    split across all categories);
  - test-case count on hover, so thin samples are visible;
  - a second chart of tokens/s and duration per run.
- **Compare tab:** rows are models, columns are each benchmark's headline
  score plus tokens/s. The data source is decision 1.

## Decisions (accepted 2026-10-08)

The operator accepted the recommendations below:
1. **Results store:** CyberSecEval headline rows go into the Nextcloud
   Tables "Model evaluations" table, and Compare reads that.
2. **Lock scope:** benchmark runs only.
3. **Sampling and effort:** record both on every run now; the policy
   comes later.
4. **Eval battery UI:** rebuild it as a Dash tab.
5. **Loading models:** stays manual for now.

The options as they were presented:


1. **Where the Compare tab reads results from.**
   - *(a) Recommended:* add CyberSecEval headline rows to the existing
     Nextcloud Tables "Model evaluations" table, and read that one
     store. It's already the eval battery's record, with per-benchmark
     views.
   - *(b)* Read each system's own results: CyberSecEval from
     cse-controller's `result.json` files, the eval battery from Tables.
     Two readers, and CSE history beyond Redis's 24 h needs a new
     endpoint on cse-controller.
   - *(c)* A small new results database, only if (a) proves too limiting.
2. **Lock scope.**
   - *Recommended:* only benchmark runs take the lock.
   - *Or* also have the scheduled CVE enrichment job wait for it.
   - Deep-research and Open WebUI are interactive and shouldn't block.
     Their traffic during a run is the one remaining source of noise in
     the metrics; the run record could note it (slots busy at
     start/end).
3. **Sampling and reasoning effort.** Should comparisons use
   PurpleLlama's fixed temperature 0.6 / top-p 0.9 for every model, or
   each model's recommended settings? And at which reasoning effort?
   Qwen defaults to `xhigh` and GLM is set to `high`.
   - *Recommended now:* record sampling and effort in every run (B
     already captures `/props`), and add explicit effort entries on
     llm-control (e.g. Qwen `xhigh`/`medium`).
   - The comparison policy itself can be decided separately.
4. **Eval battery UI.**
   - *Recommended:* rebuild it as a Dash tab.
   - *Alternative:* keep the HTML page and only link it. That's cheaper,
     but it leaves two UIs.
5. **Should the panel load models?** For example, "run this suite on
   model X" would call llm-control first.
   - *Recommended:* not yet. Keep loading manual, show the loaded model,
     and revisit once the lock exists.

## Phases (after the decisions)

Each phase is its own branch, with unit tests, deployed through the
production approval flow. The validation tier is app-level: deploy
directly to pve-tiny.

1. **CyberSecEval records which model answered,** plus the 16384-cap
   fix. Standalone, small: cse-controller and the panel's display.
   **In progress on `task/cse-model-identity`** (see README).
2. **The Framework lock in both workers, plus eval-runner run metrics.**
   cse-controller, ai-services-stack (eval-runner play), and the panel's
   status line.
3. **The Dash Eval battery tab and loaded-model header,** then retire
   the old page. cse-panel-stack.
4. **The chart replacement and the Compare tab,** following decision 1.
   cse-panel-stack, plus the publishing changes in cse-controller and
   eval-runner if (a).

## Out of scope

- New benchmarks.
- Laguna on Ollama: it isn't served behind llm-control.
- Changing benchmark scoring or harnesses beyond the run-record fields
  above.
