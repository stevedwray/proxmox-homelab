# model-params (planning workspace)

Model settings on the server (editable from the benchmark panel), named
variants, per-run settings for the Eval battery, and RULER as a long-context
benchmark. See [plan.md](plan.md).

Status: **phase A live 2026-10-09** (branch `task/llama-swap-catalogue`). Order A → C → D → B.

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
- 2026-10-09, phase A deployed (approval `model-params-a`):
  - The llama-builds playbook ran with failed=0. The rewrite changed exactly
    the six Laguna lines; the loaded `laguna-s-2.1-nathanw` reloaded in 1m20s.
  - `--reasoning-format deepseek` did not fix Laguna on the Nathanw build.
    Raw output showed the real cause: 465 of 476 generated tokens were
    control token 14 (`〈|`), which the server hides. That's the "thinking":
    the GPQA 32k runaway, the empty answers and the stray `</think>`.
  - The same prompts on `laguna-s-2.1-upstream` (b11514) gave real
    reasoning (98 and 530 tokens), a correct answer each time, and clean
    reasoning/answer separation with the deepseek format.
  - So: the fork's b10814 can't run Laguna's architecture properly. Both
    Laguna models now offer upstream and HIP only.
  - The earlier Laguna Heretic one-item results (run on the fork) don't
    count.
