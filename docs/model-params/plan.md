# Model settings, run settings and a long-context benchmark

Three things the operator asked for on 2026-10-09, after the first round of
one-item benchmark runs over the model/llama.cpp combinations:

1. **Model settings on the server, changed from the panel.** Each llm-control
   entry's llama-server settings (context, default sampling, reasoning
   format, chat-template options) are editable on a new **Models** page.
2. **Named variants.** Extra llm-control entries for the same model and build
   with different settings, e.g. `glm-5.3-flash-upstream-effort-medium`. The
   entry id is the server's alias, so results record which variant ran.
3. **Run settings.** The Eval battery's Run form can set temperature,
   top_p/top_k/min_p, token budget, reasoning, system prompt and seed for a
   run.

And a long-context benchmark: **RULER**, from lm_eval 0.4.12 (already in the
eval image).

## Decisions (operator, 2026-10-09)

| Question | Decision |
|---|---|
| Which parameters | Per run, per model on the server, and named variants |
| How server settings change | A Models page in the panel |
| Where they live | An overrides file on Framework, layered over the repo catalogue. The panel requests changes through Redis and Framework applies them. Settled overrides are folded back into the repo on request. |
| Run settings scope | Eval battery only. CyberSecEval keeps its fixed sampling (0.6/0.9), which its grading assumes. |
| Long-context benchmark | RULER |
| RULER and thinking | Selectable per run (a run setting, default off) |
| RULER lengths | 4k to 128k |

## Facts checked (2026-10-09)

- **Today's settings are fixed in two places:**
  - llama-swap entries get their flags from `models.json`.
  - GPQA and IFEval get `--gen_kwargs max_gen_toks=N` and the tasks' own
    temperature 0.
  - BFCL, AgentBench and RepoBench hard-code their historical settings
    (`bfcl_run.py` temperature 0.001, `agentbench_run.py` 0 and 3072
    tokens, `repobench_run.py` 0).
- **Series:** a run's ranking series is its token budget
  (`summarize.series`). Pilots and limited runs aren't ranked.
- **RULER in lm_eval 0.4.12** (`lm_eval/tasks/ruler`): 13 tasks — 8
  needle-in-a-haystack variants, variable tracking, common-word extraction,
  frequent-word extraction, and QA over SQuAD and HotpotQA.
  - It needs a Hugging Face tokenizer (`tokenizer=` in model_args) to build
    texts of each length.
  - Lengths come from `--metadata '{"max_seq_lengths": [...]}'`.
  - Answers are capped at 128 tokens at temperature 0.
  - It downloads Paul Graham essays from the web and SQuAD/HotpotQA from
    Hugging Face.
- **Cost is prompt reading:** about 150 tok/s on GLM, 575–665 on Qwen and
  Laguna. One 128k item takes about 14 min on GLM and 3–4 min on the
  others.
- **Network direction:** the panel can't reach Framework. Framework connects
  out to cse-panel's Redis (`llama-builds status --publish` already does).
- **Reloads:** writing llama-swap's config reloads it, which stops the
  loaded model (docs/llama-swap/plan.md, phase 4). `llama-builds
  swap-config` refuses while `framework:run-lock` is held.

## Phase A: structured settings and variants in the catalogue (Framework)

- **`models.json`:** each model gets a `settings` object instead of raw
  `args`. Keys:
  - `ctx_size`, `parallel`;
  - `temperature`, `top_p`, `top_k`, `min_p`;
  - `reasoning_format` (`auto`, `deepseek`, `none`);
  - `reasoning_budget`;
  - `chat_template_kwargs` (an object);
  - `chat_template_file`;
  - `extra_args` (a list, for anything else).

  The generator turns them into llama-server flags. Today's args become
  settings with the same effect, so the generated commands don't change.
- **`variants`:** per model, a list of `{suffix, label, settings}`. Each
  becomes an entry `<model>-<backend>-<suffix>` on every backend the model
  has, with its settings layered over the model's.
- **Overrides:** `/etc/llama-builds/overrides.json` (owned by steve), as
  `{model_id: {settings: {...}, variants: [...]}}`, merged over the
  catalogue by `swap-config`. Missing means no overrides.
- **Status for the panel:** `llama-builds status --publish` also publishes
  the effective model list (catalogue + overrides, entry ids, which model
  is loaded) to Redis key `framework:llama-models`.
- **First use:** `reasoning_format: deepseek` on the two Laguna models, for
  the stray `</think>` seen 2026-10-09. Test-load one to check.
- **Tests:** settings to flags, variants, merge order, and the shipped
  catalogue producing the same commands as before.

## Phase B: the Models page (panel + Framework applier)

- **Panel:** a fourth top-level tab, **Models**, alongside CyberSecEval,
  Eval battery and Compare.
  - A table of models, with the loaded entry marked. Pick one to see a
    form with every setting, the catalogue value shown as the placeholder,
    and the override (if any) as the value.
  - A variants list (add, edit, remove) and Save.
  - "Clear override" puts a setting back to the catalogue value.
- **Request path:**
  1. panel-web `POST /models/requests` validates the change (known keys,
     numeric ranges, model id) and pushes a request onto Redis list
     `framework:model-requests` as `{id, by, at, model, settings,
     variants, reload}`.
  2. On Framework, `llama-builds apply-requests`, run every 30 s by
     `llama-builds-apply.timer`, pops requests, validates again, writes
     `overrides.json` and runs `swap-config`.
  3. The result goes to `framework:model-request:<id>` (kept 1 day), and
     the page shows it.
- **Reload safety:** a rewrite stops the loaded model.
  - If nothing is loaded, it applies at once.
  - If a model is loaded, the request waits ("waiting: X is loaded")
    unless it was saved with **Apply now (reloads X)**.
  - It never applies while the benchmark lock is held. The page shows the
    pending state.
- **Back to the repo:** the page shows overrides that differ from the
  catalogue. Folding them into `models.json` is a request to Claude.
- **Deploy:** cse-panel-stack (panel-web + UI), and the llama-builds playbook
  for the timer.

## Phase C: run settings for the Eval battery

- **Run form:** a collapsed "Run settings" section under the benchmarks,
  applying to every benchmark in that submission:
  - temperature, top_p, top_k, min_p, seed;
  - token budget (replaces the 32k switch: 8k standard, 32k, or a number);
  - reasoning: server default, off, low, medium or high;
  - a system prompt (text).

  Blank means the standard settings, as today.
- **Plumbing:**
  - Panel → `/eval/api/jobs`, validated → `eval_tasks.run` kwargs →
    `eval-run` flags (`--temperature`, `--top-p`, `--top-k`, `--min-p`,
    `--seed`, `--reasoning`, `--system-prompt-file`) → `runmeta.py`, which
    records `settings` in `run.json`.
  - GPQA, IFEval and RULER get the sampling through lm_eval's gen_kwargs
    and the system prompt through `--system_instruction`.
  - Reasoning becomes `chat_template_kwargs` (`enable_thinking` for
    Qwen-family and Laguna, `reasoning_effort` for GLM, from the
    catalogue's per-model mapping) or `reasoning_budget: 0`. To verify in
    0.4.12: whether gen_kwargs can carry a nested object, or whether
    `runmeta exec` has to call lm_eval's Python API instead of the CLI.
  - The BFCL, AgentBench and RepoBench wrappers take the same overrides in
    place of their hard-coded values.
- **Series:**
  - A run with any non-standard setting gets `-custom-<6 hex>` in its name,
    a hash of its settings, and its own series.
  - `summarize.series` returns e.g. `8k custom-1a2b3c`, so it's never
    ranked against standard runs.
  - Reports, Tables (a new "Run settings" column) and Compare show the
    settings.
  - Same settings give the same hash, so like runs compare with each other.
- **Panel:** the runs table and detail show a run's settings.
- **Deploy:** the ai-services-stack eval play (image + worker) and
  cse-panel-stack.

## Phase D: RULER

- **Task `ruler`** in eval-run, runmeta, eval_tasks, the panel's SIZES,
  publish's TASK_LABELS and summarize's HEADLINE.
- **Lengths:** 4096, 8192, 16384, 32768, 65536 and 131072, measured with
  the reference tokenizer.
  - Before a run, eval-run asks the loaded server to count tokens
    (`/tokenize`) for a fixed 128k-reference-token text. If the model's own
    count wouldn't fit its context with the answer budget, the 131072 level
    is dropped for that run, and run.json and the report say so. So a run
    never fails on context.
- **Tokenizer:** one public, ungated reference tokenizer for every model
  (`Qwen/Qwen2.5-7B-Instruct`'s). Every model then gets the same texts.
  Lengths are exact for the reference and approximate for the rest; the
  report records each model's own count from the pre-flight check.
- **Thinking:** the run setting from phase C, default **off**. With
  thinking on, the answer budget rises from 128 to 4096 tokens, and the run
  is its own series.
- **Sizes**, all with the same 6 lengths:
  - Pilot: 4 tasks (`niah_single_2`, `niah_multikey_2`, `ruler_vt`,
    `ruler_qa_squad`) × 3 items. About 1.5 h on Qwen or Laguna, about 6 h
    on GLM.
  - Standard: all 13 tasks × 5 items. About 7–8 h fast, about 30 h on
    GLM.
  - Choose: items per task and length.

  To verify: how lm_eval limits items *per length* (`--limit` counts
  documents, and RULER puts every length in one document list). Likely the
  `num_samples` metadata.
- **Scores:**
  - Accuracy per length, averaged over tasks: the curve.
  - The headline is the mean over lengths.
  - report.md has the curve table.
  - Tables: Score % = mean, plus per-length columns `RULER 4k` … `RULER
    128k`.
  - The panel's Results shows the curve per model.
- **Data:** essays and datasets download on first use into the eval image's
  Hugging Face cache volume. The selftest checks a 4k pilot against the
  stand-in server.
- **Deploy:** the ai-services-stack eval play and cse-panel-stack. The
  first real run is a GPU job, so the operator starts it.

## Order

A → C → D → B:
- **A** is small and fixes Laguna.
- **C** is needed for D's thinking setting.
- **D** is then mostly wiring.
- **B** is the largest UI piece and builds on A's settings. Until B,
  server settings change by asking Claude to edit `models.json`
  (phase A's format).

Each phase is deployed and checked on its own.

## Not in scope

- CyberSecEval run settings.
- LongBench v2 and BABILong (possible later; same plumbing as RULER).
- Changing the standard settings that existing results were run with.
