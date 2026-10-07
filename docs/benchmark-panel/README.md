# benchmark-panel (planning workspace)

One Dash control panel for every benchmark: CyberSecEval and the eval
battery (GPQA, IFEval, BFCL, AgentBench, RepoBench). Every run records
which model answered, its scores, duration, tokens and tokens/s, and
both kinds of run share one queue for Framework.

Status: **decisions made, phase 1 in progress (2026-10-08).** See
[plan.md](plan.md).

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
