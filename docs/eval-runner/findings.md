# Model evaluation findings

Hand-written analysis to read alongside the generated `leaderboard.md`
and the Nextcloud Tables table **Model evaluations**. The numbers in those
come from `eval-run publish`; this file explains how far to trust them.
The canonical copy is `docs/eval-runner/findings.md` in the repo. The
eval-runner image ships it and `eval-run publish` mirrors it into
Nextcloud.

Last updated: 2026-10-01.

## How results are produced

- **Harness.** lm-evaluation-harness 0.4.12, `local-chat-completions`
  against an OpenAI-compatible server, with `--apply_chat_template`.
  - GPQA: `gpqa_diamond_cot_zeroshot`, 198 questions.
  - IFEval: 541 prompts.
- **Decoding.** Greedy: both task configs pin `temperature: 0`, overriding
  any server default. The seed is 1234.
- **Token budget.** `max_gen_toks` is 8192 per answer, the same for every
  historical result.
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
- The honest fix is a larger budget. That needs a decision: results at a
  different budget aren't comparable with history, so both would need to
  be kept and labelled.

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

## Open questions

- **Budget:** should new runs (GLM-5.3-Flash first) also be measured at a
  larger budget, such as 32k, kept separate from the comparable 8192
  series?
- **Comparability with history:** GLM-5.3-Flash runs on llama.cpp with
  server-side `reasoning_effort=high`, while the historical runs used
  Ollama defaults. A runtime or reasoning-mode difference is recorded per
  run (Runtime and Note columns), but it still limits how directly the
  numbers compare.
