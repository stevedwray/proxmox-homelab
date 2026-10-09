# model-params (planning workspace)

Model settings on the server (editable from the benchmark panel), named
variants, per-run settings for the Eval battery, and RULER as a long-context
benchmark. See [plan.md](plan.md).

Status: **phase A built 2026-10-09** (branch `task/llama-swap-catalogue`), not deployed. Order A → C → D → B.

Related: [docs/llama-swap](../llama-swap/README.md) (the catalogue and
`llama-builds swap-config`), [docs/benchmark-panel](../benchmark-panel/README.md),
[docs/eval-runner](../eval-runner/README.md).

## Log

- 2026-10-09: planned. Decisions are in plan.md.
- 2026-10-09, phase A built:
  - `models.json` uses structured `settings` and `variants`.
  - `llama-builds` turns settings into flags in a fixed order, layers
    `/etc/llama-builds/overrides.json` over the catalogue (a null value
    removes a setting), and adds entries `<model>-<backend>[-candidate]-<suffix>`
    for variants.
  - It publishes `framework:llama-models` for the Models page.
  - Checked against the previous code: all 29 commands are identical except
    the six Laguna entries, which gain `--reasoning-format deepseek`.
  - 32 llama-builds tests.
