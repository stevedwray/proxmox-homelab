# Model recommendations for PentAGI (from the eval battery)

Source project: `docs/framework/eval-battery-phase2-plan.md` (branch
`task/eval-battery-phase2-plan`) — a general-purpose battery (BFCL,
GPQA, IFEval, CyberSecEval, RepoBench, SWE-rebench) run across every
model candidate on `framework.gibbsgreatly.xyz`, not built for PentAGI
specifically. This doc translates those results into PentAGI-specific
role recommendations, cross-checked against PentAGI's own real,
live-flow evidence (`README.md`, `lessons-learned.md`) wherever it
exists — real PentAGI behavior always wins over a generic benchmark
when the two disagree.

**PentAGI's role split, as currently deployed** (see
`lessons-learned.md` §"Material differences: custom (llama.cpp) stack
vs vanilla (Ollama) stack"): one model for almost every role
(`primary_agent`, `pentester`, `coder`, `generator`, `refiner`,
`searcher`, `simple`), a separate model for `adviser` only.

## Full score table (all axes actually measured, this project)

Numbers pulled directly from each model's own result file, not
reconstructed from memory — BFCL is the `BFCL_v3_simple_score.json`
accuracy for each model (not the cross-model `data_overall.csv`
leaderboard, which dilutes real scores with untested categories).

| Model | BFCL (tool-calling) | GPQA (reasoning) | IFEval (strict/loose) | CyberSecEval (refusal) | RepoBench (EM/ES) | SWE-rebench |
|---|---|---|---|---|---|---|
| **Qwen3.6-35B-A3B** (current `PRIMARY_MODEL`) | 94.0% (376/400) | **57.07%** (best of any model) | 90.39% / 91.87% | 3% | **17.33% / 41.0%** (best of any model) | not tested |
| Qwen3-Coder-30B-A3B | **96.25%** (385/400, best) | not tested | 81.33% / 85.03% | **1%** | 1.67% / 14.04% (misleading — see caveat below) | **2/4 resolved (50%)**, 1 wrong fix, 1 invalid patch |
| Gemma4-26B (dense) | 94.0% (376/400) | 43.94% | **92.98% / 93.90%** (best) | 6% | 9.67% / 26.35% | not tested |
| Qwen3-Coder-Next | 93.25% | dropped (coding specialist, low expected signal) | dropped | not tested | not tested | not tested |
| Gemma4-26B-A4B-QAT | 92.5% (370/400) | 27.27% | 89.83% / 91.13% | 6% | 6.33% / 17.7% | not tested |
| Laguna S2.1 (base) | 92.75% (371/400) | 24.24% | 75.42% / 80.59% | **0%** (lowest of any model) | not tested | not tested |
| Qwen3.8-27B | 91.25% | 43.43% (~27h run, possible truncation) | 89.46% / 91.31% | not tested | not tested | not tested |
| **gpt-oss-120b** (current `adviser`) | 89.75% (359/400) | **not tested** | not tested | not tested | not tested | not tested |
| Laguna-Heretic | 83.75% | dropped | cancelled | not tested | not tested | not tested |
| Llama-3.3-70B-Instruct | not tested (this battery) | not tested | not tested | not tested | not tested | not tested |
| Llama4 Scout 17B-16E | 16.25% (rejected outlier) | not tested | not tested | not tested | not tested | not tested |

## Recommendation 1: keep Qwen3.6-35B-A3B for the primary role group

**No change recommended.** This is already the live, validated choice,
and the battery now gives it strong independent confirmation rather
than just PentAGI-specific anecdote:

- Best GPQA (57.07%) and best RepoBench (17.33%/41.0%, ~1.8x the next
  model) of **any** model this project has tested, general-purpose or
  specialist.
- BFCL (94.0%) is within 2.25 points of the best tool-calling score
  measured (Qwen3-Coder-30B, a coding specialist), and matches dense
  Gemma4-26B exactly.
- Low refusal rate (3%) — not the lowest measured, but comfortably in
  the safe range for a tool that legitimately needs to discuss and
  execute security-testing actions without over-refusing.
- Directly matches PentAGI's own real evidence: passed Phase 4 Test 1
  cleanly on the first attempt after Llama-3.3-70B failed it three
  times, is the sole model in the clean 5/5-subtask vanilla/Kali-VM
  control run, and already powers the custom llama.cpp stack's primary
  role group in production.

## Recommendation 2: re-test the adviser role — real open question, not yet closed

`gpt-oss-120b` is currently the sole `adviser` model, and
`lessons-learned.md` already flags this as one of two leading
explanations for the custom stack's remaining subtask-transition
reliability gap versus the vanilla/Qwen3.6-only control — but that
question was never closed with real data. This project's own plan
document designates **GPQA as the priority proxy specifically for the
adviser-role decision** (general reasoning, not tool-use) — and
`gpt-oss-120b` has never been run through it. The one axis we *do* have
for both models points the other way: gpt-oss-120b's BFCL (89.75%,
359/400) is measurably lower than Qwen3.6-35B's (94.0%) — weak evidence
on its own since the adviser doesn't call tools directly, but it
removes "gpt-oss-120b is just better across the board" as a safe
assumption.

Meanwhile the operational cost of keeping a second, much larger model
loaded is real and already documented: GPU OOM fights, ~60–90 minute
cold-load time, and the `ctx-size`/`reasoning-budget` tuning fights in
`lessons-learned.md` all trace back to running two models concurrently
on unified memory.

**Recommended next step** (cheap — the infrastructure already exists):
run GPQA against `gpt-oss-120b` directly, and/or reuse the existing
vanilla-comparison-instance pattern for a controlled adviser-only swap
(same flow, same primary model, `adviser` = gpt-oss-120b vs `adviser` =
Qwen3.6) to settle whether the second model is earning its memory and
reliability cost.

## Recommendation 3: consider Qwen3-Coder-30B for the `coder` role specifically — real trade-off, not a clean win

Qwen3-Coder-30B has the best raw tool-calling score measured (96.25%)
and is the only model in this project with a real agentic-coding track
record: **2 of 4 real SWE-rebench instances resolved** (patches
generated against real GitHub issues, verified against the repo's own
test suite) — a believable result in the range frontier models land in
on SWE-bench Lite/Verified.

The real caveat, and it's a significant one: this is also the model
with the **worst measured output-format compliance** in the whole
project. On RepoBench's strict "output only code, no commentary"
prompt it ignored the instruction 25–36% of the time (two independent
runs), and its one SWE-rebench failure that wasn't just "wrong fix" was
worse than wrong — the model lost the thread mid-task and dumped raw
file content into the patch file instead of running `git diff`,
producing an unparseable submission. That's the exact failure shape
(model output doesn't match the format the harness expects) that
already hard-disqualified Llama-3.3-70B from PentAGI entirely.

**Recommendation**: worth a scoped, real test on the `coder` role
specifically (not a blind swap of `PRIMARY_MODEL`) — the tool-calling
and real-patch-generation upside is genuine, but so is the compliance
risk, and PentAGI's own reflector/format-checking is exactly the kind
of thing this failure mode could slip past.

## Models not recommended, with reasons

| Model | Reason |
|---|---|
| Llama-3.3-70B-Instruct | Hard-disqualified by real PentAGI evidence — failed Phase 4 Test 1 three independent times (`does not match the expected peg-native format`), independent of any general benchmark standing. Was `PRIMARY_MODEL` per `decisions.md` Decision 12 (a VSCode/Copilot/Continue-specific finding, never validated against PentAGI's own calling conventions) before Qwen3.6-35B replaced it. |
| Llama4 Scout 17B-16E | BFCL 16.25% — drastically worse than every other candidate measured. Not worth further testing for any role. |
| Gemma4-26B-A4B-QAT | Consistently trails the dense Gemma4-26B checkpoint on every axis measured in this project's dedicated head-to-head (BFCL -1.5, GPQA -16.67, IFEval -3.15/-2.77, RepoBench -3.34 EM/-8.65 ES, CyberSecEval identical). If a Gemma variant is ever wanted for a role, prefer dense over A4B-QAT. |
| Laguna-Heretic | Lowest BFCL of the viable candidates (83.75%), and separately flagged as DeepResearch-Bench-untrustworthy in this project's own findings. No clear PentAGI role fit identified. |

## Caveats carried over from the source battery

- **CyberSecEval numbers measure refusal rate on security-adjacent
  prompts in isolation** — they say a model won't reflexively refuse
  legitimate pentest-style requests, not that it performs well at
  pentesting. Useful as a risk check for PentAGI specifically (a tool
  that legitimately needs to discuss exploitation), not a capability
  ranking.
- **Qwen3-Coder-30B's RepoBench score (1.67% EM) is misleading read
  raw** — it reflects the model ignoring a strict no-commentary
  instruction on 25–36% of prompts, not poor code quality. Read
  alongside the SWE-rebench finding above: the same
  format-non-compliance pattern shows up in a real agentic context too,
  which is the more operationally relevant read for PentAGI.
- **Qwen3.8-27B's GPQA run took ~27 hours** (vs a few hours for every
  other model), with many responses landing at exactly the 8192-token
  generation ceiling — a real signal some answers may have been
  truncated mid-reasoning rather than reaching a natural stop. Its
  43.43% may understate its true reasoning ability; not yet re-tested
  with a larger budget.
- **AgentBench is excluded from this table** — this project found it
  noise-dominated at practical sample sizes (Qwen3.6-35B's own
  identical-config repeat swung 30%→10% at n=10) and only Gemma4-26B/
  A4B-QAT have a trustworthy full-size (n=100) result (47%/42%), which
  doesn't cover any of the models actually relevant to these
  recommendations.

## Related documentation

- [README.md](./README.md) — current deployment status, the Decision-12
  Qwen ban's actual scope (VSCode/Copilot/Continue tool-calling, not
  PentAGI), and the real live evidence that led to `PRIMARY_MODEL`
  switching to Qwen3.6-35B.
- [lessons-learned.md](./lessons-learned.md) — the adviser-model plan,
  the llama.cpp migration, memory/OOM findings, and the still-open
  question this doc's Recommendation 2 addresses.
- `docs/framework/eval-battery-phase2-plan.md` — the source battery:
  full methodology, bugs found/fixed, and every model's complete result
  set (including axes not relevant to PentAGI and dropped here).
- `docs/framework-integration/decisions.md` Decision 12 — the original
  Qwen tool-calling ban this doc's models were tested against; scope is
  VSCode/Copilot/Continue only, not PentAGI's own provider.
