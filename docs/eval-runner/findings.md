# Model evaluation findings

Hand-written analysis to read alongside the generated `leaderboard.xlsx`
(or `leaderboard.md`) and the Nextcloud Tables table **Model
evaluations**. The numbers in those
come from `eval-run publish`; this file explains how far to trust them.
The canonical copy is `docs/eval-runner/findings.md` in the repo. The
eval-runner image ships it and `eval-run publish` mirrors it into
Nextcloud.

Last updated: 2026-10-01 (32k series; BFCL/AgentBench/RepoBench added).

## How results are produced

- **Harness.** lm-evaluation-harness 0.4.12, `local-chat-completions`
  against an OpenAI-compatible server, with `--apply_chat_template`.
  - GPQA: `gpqa_diamond_cot_zeroshot`, 198 questions.
  - IFEval: 541 prompts.
- **Decoding.** Greedy: both task configs pin `temperature: 0`, overriding
  any server default. The seed is 1234.
- **Token budget.** `max_gen_toks` is 8192 per answer, the same for every
  historical result. Runs at a larger budget (`--max-gen-toks 32768`)
  form a separate **32k series**, ranked only among themselves.
- **Historical results.** These were run on framework through Ollama in
  August–September 2026. New results come from `eval-runner` on
  `ai-services-stack`, against whatever llama-server serves.
- **Comparable** means a full run (no `--limit`) at the 8192 budget, as
  recorded in lm_eval's own results file. Pilots and runs without the cap
  are listed but not ranked.

## Findings

### 1. Under 8192 tokens, GPQA mostly measures whether the model finishes

Empty GPQA answers in the comparable historical runs:

| Model | GPQA flex | Empty answers | No parseable letter |
|---|---|---|---|
| Qwen3.6-35B-A3B (Q4_K_M) | 57.07% | 49 / 198 (24.7%) | 54 |
| Gemma4-26B (Q4) | 43.94% | 91 / 198 (46.0%) | 95 |
| Qwen3.8-27B (Q4_K_M) | 43.43% | 105 / 198 (53.0%) | 107 |
| Gemma4-26B-A4B-QAT (Q4_0) | 27.27% | 134 / 198 (67.7%) | 137 |
| Laguna S2.1 (Q4_K_M) | 24.24% | 114 / 198 (57.6%) | 127 |

An empty answer means the response had no answer content: the reasoning
used up the budget first. This matches the earlier observation that many
Qwen3.8-27B responses stopped at exactly 8192 tokens.

**Implications:**
- The GPQA ranking is largely a ranking of reasoning *length* against a
  fixed budget, not of correctness. A model that thinks less can outscore
  a more accurate one that thinks more.
- Don't compute "accuracy on the questions it answered" to correct for
  this. The questions a model finishes inside the budget are likely the
  easier ones, and they differ per model. That figure came out at an
  implausible 94.5% for Qwen3.8-27B, so it isn't comparable either.
- The honest fix is a larger budget. Results at a different budget
  aren't comparable with history, so they are kept as a separate,
  labelled series: the 32k series (decided 2026-10-01). No 32k results
  exist yet.

### 2. IFEval is far less affected

IFEval empty answers run from 0% to 4.8% in the same runs, because its
prompts need short outputs. The IFEval ranking is the more trustworthy of
the two:
- Gemma4-26B 92.98%
- Qwen3.6-35B 90.39%
- A4B-QAT 89.83%
- Qwen3.8-27B 89.46%
- Qwen3-Coder-30B 81.33%
- Laguna S2.1 75.42%

### 3. GPQA "strict-match" is always 0% and carries no information

The task's strict filter only accepts the literal text `The answer is
(X)`. The zero-shot prompt never asks for that format, and models write
things like `The correct answer is **(C)**`. So strict-match scores 0.00%
for every model.

Use **flexible-extract** (the last `(A)`–`(D)` in the response) as the
GPQA score. The table shows strict-match only for completeness.

### 4. Excluded historical runs, and why

- **Bug 6 (no token cap):** `lm_eval`'s client sent `max_tokens: 256`
  unless `max_gen_toks` was passed.
  - Qwen3.6-35B's first runs scored GPQA 0.00% and IFEval 17.74%
    (redo: 57.07% / 90.39%).
  - Qwen3-Coder-30B's first run (GPQA 11.62%, IFEval 79.11%) also used a
    `ctx163k` Ollama tag, since found to degenerate on dense content.
- **Pilots** (`--limit 40`), for example Gemma4-26B's: these were for
  checking the infrastructure, not for scoring.

The automatic rule (full run with `max_gen_toks=8192`) selects exactly the
set the eval-battery doc treats as valid.

### 5. BFCL, AgentBench and RepoBench history

- **BFCL simple (18 imported results)** clusters at 90-96% for every
  usable model, so it separates broken tool calling more than it ranks
  good models. Two outliers are runtime problems, not capability:
  - Laguna S2.1 on the llama.cpp router scored 75.50% with 34 empty
    answers, against 92.75% on Ollama (the reason Laguna stays on
    Ollama).
  - Llama4-Scout scored 16.25%.
  The Qwen3.8-27B reasoning-effort variants (none/low/medium/high) all
  land within 92.5-93.75%, so effort doesn't matter on single calls.
- **AgentBench os-std:** only two historical outputs survive.
  - Qwen3.6-35B: 22% on the seed-42 sample of 100 (comparable).
  - Qwen3-Coder-30B: 27% over all 800 episodes (its own series).
  - The other historical numbers are known only from
    `docs/framework/eval-battery-phase2-plan.md` and can't be imported:
    Gemma4-26B 47%, the A4B-QAT 42%, Qwen3-Coder-Next 36% and
    Laguna-Heretic 38%.
  - Sampling noise is large: an identical-config Qwen3.6-35B repeat
    swung 30% to 10% at n=10, which is why the floor is n=100.
  - os-std is the prompt-injection variant, so eval-runner also records
    `injection_success_rate` (lower is better) in each results file.
- **RepoBench:** the six historical results (for example Qwen3.6-35B EM
  17.33% / ES 41.0%) came from lost scripts that sent chat prompts with
  an "output only code" instruction, and scored a compliance rate as
  well. The rebuilt series uses upstream's raw-completion method, so
  expect different absolute numbers. It ranks only against itself.

## Open questions

- **Budget:** how much do the 32k-series scores differ from the 8k ones
  for the same model? The first pair of runs (8k and 32k for one
  reasoning model) will show whether the 8k ranking holds up.
- **RepoBench calibration:** re-running one historical RepoBench model
  in the rebuilt series would show how far the two methods differ. That
  needs the same model served by llama.cpp.
- **Comparability with history:** GLM-5.3-Flash runs on llama.cpp with
  server-side `reasoning_effort=high`, while the historical runs used
  Ollama defaults. A runtime or reasoning-mode difference is recorded per
  run (Runtime and Note columns), but it still limits how directly the
  numbers compare.
