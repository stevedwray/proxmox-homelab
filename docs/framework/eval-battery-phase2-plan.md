# Eval battery — phase 2 plan of action

Follow-on to `eval-framework-expansion-2026-08.md` (the 9-framework
battery, wound down mid-way when the project pivoted to large-context
testing) and the large-context expansion session that followed it. This
doc is the forward plan: fix known bugs, fill real coverage gaps, and
make future runs more robust — not a retrospective log like the other
doc.

**Scope decisions this plan carries forward, as directed:**
- **τ²-bench is dropped entirely.** No further τ²-bench runs, for any
  model. Existing partial data (Qwen3-Coder-30B 0.46 avg reward,
  Qwen3.6-35B's compromised 0.33/n=3) stays as historical record only.
- **GPQA is the priority proxy for the PentAGI adviser-role decision** —
  general reasoning ability, not tool-use. Every model still missing it
  gets it before anything lower-priority.
- **BFCL stays the priority tool-use signal** — already the most
  complete dataset in the project; phase 2 fills the few remaining gaps
  (Qwen3-Coder-Next/Laguna-Heretic already have it — no action needed
  there) rather than re-running what's solid.
- **A4B-QAT vs Q4_K_M at 26B gets a real, complete head-to-head** — BFCL/
  AgentBench already exist for both; GPQA/IFEval/CyberSecEval/RepoBench
  do not, and this comparison was the explicit motivation for testing
  A4B-QAT in the first place (see the other doc's "genuinely new test,
  not redundant" reasoning).
- **RepoBench and IFEval get broader coverage** — both currently sit on
  2-3 models when they're cheap/informative enough to justify more.

## Current status (as of 2026-08-15 — check this section first)

**Fully complete:** Phase 0 bug fixes (all closed, see table below), Tier
A (Gemma4-26B, Gemma4-26B-A4B-QAT, Laguna S2.1 — all 3 tests each), Tier
A.5 (Qwen3.6-35B GPQA+IFEval redo), Tier B (Qwen3-Coder-30B IFEval redo;
Laguna-Heretic IFEval cancelled per operator call), Tier C (RepoBench for
Qwen3-Coder-30B/Gemma4-26B/Gemma4-26B-A4B-QAT), and Phase 2 (A4B-QAT vs
Q4_K_M table, all 6/6 axes in, final conclusion written).

**Currently running (launched 2026-08-14/15, operator-requested
follow-up):** CyberSecEval + RepoBench against Qwen3.6-35B and
Qwen3-Coder-30B, run as two model-paired batches to avoid contending
both scripts' reload-before-every-call pattern against the *same*
model at once:
- **Pair 1:**
  - Qwen3.6-35B CyberSecEval (garuda → framework) — **done 2026-08-15.**
    Refusal rate 3% (97 accept / 3 refuse out of 100), in the same
    range as the rest of the field: Laguna S2.1 0%, Qwen3-Coder-30B
    (original run) 1%, Gemma4-26B 6%, Gemma4-26B-A4B-QAT 6%. No
    outlier behavior.
  - Qwen3-Coder-30B RepoBench redo (ai-stack → framework, output dir
    `results/qwen3-coder-30b-redo/repobench`) — **still running**, on
    the `cross_file_random` level as of last check (`cross_file_first`
    level finished clean: 100/100, 2 transient reload-race 400s
    recorded as empty preds, in line with the ~3.5% baseline failure
    rate). The redo uses identical methodology to the original
    contaminated run (EM 1.67%/ES 15.18%, 36% non-compliant) -- expect
    a similar result, which would *confirm* that finding as
    reproducible model behavior rather than a fluke, not indicate a
    new problem.
- **Pair 2 (queued, launch automatically once Pair 1's RepoBench leg
  finishes):** Qwen3.6-35B RepoBench (ai-stack) + Qwen3-Coder-30B
  CyberSecEval redo (garuda) -- Qwen3-Coder-30B's existing CyberSecEval
  number predates this session's methodology, being redone for
  consistency.

**Still pending after that (not started):**
- Real DeepResearch Bench rerun at full-batch scale, to validate the
  Bug 4 JSON-extraction fix (`deepresearch_bench_race.py`) beyond the
  single-task-ID spot check already done.
- Phase 0.3 (low priority): try chunked generation to fix
  Qwen3-Coder-Next's DRB long-form corruption, only worth it if DRB
  turns out to matter for a live model decision.

**Operational notes for picking this up fresh:** all four
CyberSecEval/RepoBench jobs above use the same launch pattern as
everywhere else in this doc -- `cyberseceval-battery.sh <model_tag>
<short_name>` from `~/eval-harnesses` on garuda; `repobench_generate.py
--model <tag> --output-dir .../results/<name>/repobench
--sample-per-level 100` then `repobench_eval_local.py --path
<same-dir>` from `~/eval-harnesses/benchmarks` on ai-stack. Always use
the `ctx32k` Ollama tag variant for any model that has one (`ctx163k`/
`ctx147k` tags are confirmed broken on dense content). Check
`~/eval-harnesses/cyberseceval-battery.log` (garuda) and
`gpqa-ifeval-battery.log` (framework) for cross-model run history.

## Phase 0 — bug fixes (do first; running more tests on broken infra wastes time)

| # | Bug | Fix | Priority | Notes |
|---|---|---|---|---|
| 1 | RACE judge fails JSON extraction ~85% of the time, even on real content | Root-cause via direct inspection: check whether the judge's raw output is truncated (num_predict too small for a full multi-criterion JSON object), wrapped in markdown fences the extractor doesn't strip, or a genuine prompt/parser mismatch. Fix whichever it is. | **Highest** — blocks trustworthy DeepResearch Bench scores for every model, not just one | Cheapest fix on this list relative to its payoff |
| 2 | BrowseComp sits at the floor for every model tested | **Investigated 2026-08-10, timeboxed as planned.** Iteration cap fix (5→12) didn't move the score. Diagnosed via direct testing: the shim itself is correct (a genuinely different query returns good, varied results); the floor is production SearXNG's engine coverage/ranking for niche factual queries (two different phrasings of the same hard question returned identical generic/homepage-heavy results). That's shared production infra outside this project's authorized scope to reconfigure. Applied the one safe, in-scope lever: bumped the hardcoded `num_results` default 5→10 in both `browsecomp_ollama_sampler.py` and `deepresearch_agent.py` (the model can't control this itself — the tool schema only exposes `query`). **Real fix would need either a different/better-configured search backend or query reformulation logic, neither in scope right now — BrowseComp should be read as a known-floor test until that changes, not re-chased further.** | Medium — closed at current scope | |
| 3 | Qwen3-Coder-Next corrupts long-form generation (~85-100%) | Try chunked generation (smaller `num_predict` per call, stitched together — same pattern the article-cleaner already uses) as a real attempt before accepting permanent exclusion. | Low | Only worth it if DeepResearch Bench turns out to matter for a decision this model is actually a candidate for |
| 4 | Kimi-Dev-72B tool-calling broken (real upstream Ollama bug) | **Investigated, not attempted, 2026-08-10.** `volker-mauel/Kimi-Dev-72B-GGUF` does report a promising `qwen2` architecture tag with a real working `<tool_call>`-rendering chat template (unlike the original broken conversion) — genuinely looked promising. But it only ships Q8_0 (76.7GB, sharded across 4 files) and extreme low-bit TQ1_0/TQ2_0 quants — no single-file Q4-tier option matching this project's established convention, and `ollama pull hf.co/...` rejects sharded repos outright. A manual shard-download-then-merge-then-`ollama create` path was possible but risked ~150-230GB of transient disk usage against only 237GB free on framework — the same disk-full failure mode this project already hit once (see [[reference_ollama_blob_store_duplication]]). Given this was already flagged low-priority and the operator was unreachable to weigh the risk, made the call to skip rather than risk a repeat crisis unsupervised. **Drop Kimi-Dev-72B from this project for good** — this was the last reasonable attempt. | Low-medium — closed, not pursued | |
| 5 | Every multi-hour test currently runs at full size with no early-abort | Build `--pilot` support (see Phase 3) | Medium | Prerequisite for running Phase 1/2 efficiently, do alongside #1 |
| 6 | `lm_eval`'s own client sends `max_tokens: 256` by default, independent of the Ollama tag's `num_predict` -- silently truncates reasoning models regardless of tag-level fixes | Always pass `--gen_kwargs max_gen_toks=8192` on every `lm_eval` GPQA/IFEval invocation | **Highest** -- found 2026-08-10 while validating the Tier A pilot; **retroactively invalidates Qwen3.6-35B's previously-"final, clean" IFEval numbers** (14.75%/17.74%, recorded 2026-08-07) since that run never passed this flag either | Fixed in `gpqa-ifeval-battery.sh`; confirmed via pilot A/B on Gemma4-26B: IFEval ~40%→95%, GPQA flexible-extract 0%→57.5% |

## Phase 1 — coverage gaps

Current state as of 2026-08-13 (✅ = real number exists, 🔄 = running
now, ⬜ = missing, ⚠️ = a number exists but is invalidated (Bug 6
truncation) and needs a redo, — = out of scope for this model):

| Model | BFCL | AgentBench | GPQA | IFEval | CyberSecEval | RepoBench |
|---|---|---|---|---|---|---|
| Qwen3-Coder-30B (production) | ✅ | ✅ | ✅ | ✅ **81.33%/85.03%** (redo confirmed clean — close to original 79.11%/82.62%, +2.2/+2.4pt correction) | ✅ | ⚠️ EM 1.67%/ES 15.18% — see Tier C note, 36% of responses were non-compliant commentary, not a real code-quality score |
| Qwen3.6-35B | ✅ | ✅ | ✅ **57.07%** (redo, highest of any model tested) | ✅ **90.39%/91.87%** (redo, ~6x correction from Bug-6-truncated 14.75%/17.74%) | ✅ 3% refusal (97/100 accept) | 🔄 running (redo, Pair 2) |
| Gemma4-26B (dense) | ✅ | ✅ | ✅ 43.94% | ✅ 92.98%/93.90% | ✅ 6% refusal | ✅ EM 9.67%/ES 26.35% (9.3% non-compliant, far less than Qwen3-Coder-30B's 36%) |
| Gemma4-26B-A4B-QAT | ✅ | ✅ | ✅ 27.27% | ✅ 89.83%/91.13% | ✅ 6% refusal | ✅ EM 6.33%/ES 17.7% (4% non-compliant, lower than dense — score gap here is real, not compliance-driven) |
| Laguna S2.1 (base) | ✅ | ✅ | ✅ 24.24% | ✅ 75.42%/80.59% | ✅ 0% refusal | ⬜ |
| Qwen3-Coder-Next | ✅ | ✅ | — dropped | — dropped (swapped for Qwen3-Coder-30B redo) | ⬜ | ✅ |
| Laguna-Heretic | ✅ | ✅ | — dropped | — cancelled | ⬜ | ✅ |

**Tier A — fill first** (the 3 models whose battery was mid-flight when
the project pivoted; harness and methodology already proven, this is
compute time not engineering):
- Gemma4-26B: GPQA, IFEval, CyberSecEval
- Gemma4-26B-A4B-QAT: GPQA, IFEval, CyberSecEval *(this + existing
  BFCL/AgentBench completes the A4B-QAT vs Q4_K_M head-to-head — see
  Phase 2)*
- Laguna S2.1: GPQA, IFEval, CyberSecEval — genuinely rerun, not
  resumed (the earlier attempt overlapped the OOM-crash leak window and
  was never trusted)

**Tier A.5 — redo, not new** (added 2026-08-10, Bug #6 fallout):
- Qwen3.6-35B: IFEval **and GPQA** redo, both invalidated by the same
  lm_eval client-side bug. Confirmed 2026-08-13 by inspecting the raw
  result files directly: both the 2026-08-05 GPQA run and its
  2026-08-06 rerun used `gen_kwargs: {}` (no `max_gen_toks` override)
  and both scored a flat 0.0%/0.0% (flexible-extract/strict-match) --
  the exact truncated-to-empty signature diagnosed for Bug 6, not a
  real capability measurement. IFEval's 2026-08-07 "final, clean"
  numbers (14.75%/17.74%) share the identical root cause.

**Tier B — new coverage** (never tested at all on these axes; matters
because BFCL/AgentBench alone don't tell you general-reasoning fit for
the adviser role):
- Qwen3-Coder-30B (production): IFEval **redo**, not new coverage --
  swapped in for Qwen3-Coder-Next's slot (operator call, 2026-08-13).
  Its existing 2026-08-05 numbers (79.11%/82.62% strict/loose) used
  `gen_kwargs: {}`, the same missing-flag condition Bug 6 exploited on
  Gemma4-26B/Qwen3.6-35B -- but scored real, plausible numbers rather
  than the flat-zero truncation signature those runs showed. Working
  read: Qwen3-Coder-30B likely isn't a reasoning-preamble model the way
  those two are, so a 256-token cap probably didn't starve it -- but
  that run also has no `--log_samples` output to check directly, so
  it's a plausible inference, not a verified-clean number. Rerun with
  `--gen_kwargs max_gen_toks=8192` to settle it properly rather than
  leave an unverified assumption on the books, same standard applied
  to every other model in this project.

GPQA dropped from Tier B for both Qwen3-Coder-Next and Laguna-Heretic
(operator call, 2026-08-13): this project's own Tier A timings put
full GPQA anywhere from ~7h (Gemma4-26B) to ~14h+ (Laguna S2.1, a
similarly reasoning-heavy model), and neither of these two is a
general-reasoning candidate -- Qwen3-Coder-Next is a coding specialist,
Laguna-Heretic is a decensored variant of a base model already scored
on GPQA at Tier A. Low expected signal, high time cost -- not worth it.
Qwen3-Coder-Next's IFEval was then dropped entirely in favor of the
Qwen3-Coder-30B redo above -- 30B is the actual production pick, so
verifying its one questionable number takes priority over new coverage
on a non-production model. Laguna-Heretic's IFEval was then also
cancelled outright (operator call, 2026-08-14) -- Tier B now covers
only the Qwen3-Coder-30B IFEval redo; Laguna-Heretic gets no new Tier B
coverage. Its existing BFCL/AgentBench split-signal finding
(decensoring cost tool-call format but not agentic task completion)
stands as its only post-Tier-A data point.

**Tier C — RepoBench expansion** (currently only 2 of 7 models tested):
- Qwen3-Coder-30B — the actual production pick has never been measured
  against the benchmark that now exists specifically for large-context
  code completion; establishes a real baseline against Qwen3-Coder-Next
- Gemma4-26B + Gemma4-26B-A4B-QAT — cheap enough to add, gives the
  A4B-QAT comparison a code-completion data point too

**Qwen3-Coder-30B result (2026-08-14): EM 1.67%, ES 15.18%
(cross_file_first/cross_file_random/in_file: EM 2.0/3.0/0.0, ES
15.18/16.67/13.69) -- badly misleading if read as a raw code-quality
score.** Root-caused via direct sample inspection, not assumed:
compared against Qwen3-Coder-Next's saved raw predictions using the
identical prompt template (`COMPLETION_INSTRUCTION`, "Output ONLY the
next line of code -- no explanation") -- Qwen3-Coder-Next complied on
300/300 rows, Qwen3-Coder-30B replied with conversational commentary
("Looking at your code, I can see...") instead of a completion on
**108/300 rows (36%)**. This is a real, model-specific
instruction-following weakness, not a corruption bug or a script
issue -- and it's consistent with Qwen3-Coder-30B already having the
weakest IFEval score (81.33%/85.03%) of any general-purpose model
tested. The raw EM/ES numbers are a legitimate measurement of "how
this model behaves under this exact strict-format prompt," but
substantially understate its actual code-completion quality, since
over a third of responses never attempt a completion at all. Treat
this as "Qwen3-Coder-30B struggles to comply with strict
no-commentary output constraints," not "Qwen3-Coder-30B writes bad
code" -- those are different findings and only the former is what this
result actually measures. Not yet decided: whether a stricter
prompt/few-shot pass is worth a re-run to get a cleaner
code-quality-only signal, or whether the compliance-failure rate
itself is the more operationally relevant finding for PentAGI (which
also needs the model to follow strict output-format instructions in
its own tool-calling/code-generation prompts).

**Gemma4-26B result (2026-08-14): EM 9.67%, ES 26.35%**
(cross_file_first/cross_file_random/in_file: EM 6.0/16.0/7.0, ES
25.15/30.14/23.77), **zero generation failures** (vs Qwen3-Coder-30B's
7/300 reload-race failures). Checked its compliance rate too, same
method as above: **28/300 rows (9.3%)** conversational instead of a
completion -- present, but far less than Qwen3-Coder-30B's 36%. This
lines up cleanly with the IFEval ordering (Gemma4-26B 92.98%/93.90% >
Qwen3-Coder-30B 81.33%/85.03%) and gives a real cross-benchmark
validation: the model that follows strict-format instructions best on
IFEval also drifts into commentary least often on RepoBench's
raw-completion prompt. Qwen3-Coder-Next (0/300, the coding specialist)
sits at one end of this spectrum, Qwen3-Coder-30B (36%) at the other,
Gemma4-26B (9.3%) in between -- instruction-following capability, not
architecture or coding-specialization, appears to be the actual driver
of RepoBench compliance rate here.

**Gemma4-26B-A4B-QAT result (2026-08-14): EM 6.33%, ES 17.7%**
(cross_file_first/cross_file_random/in_file: EM 6.0/8.0/5.0, ES
18.03/17.03/18.04), zero generation failures, **12/300 rows (4%)**
conversational -- notably *lower* than Gemma4-26B's own 9.3%, which
breaks the clean IFEval-compliance correlation above (A4B-QAT's IFEval
of 89.83%/91.13% is below Gemma4-26B's, so a strict correlation would
predict *more* drift, not less). Worth being honest about rather than
force-fitting: the correlation above is a real, useful trend, not a
strict law. What it does confirm is that **A4B-QAT's lower RepoBench
score isn't a compliance artifact** the way Qwen3-Coder-30B's was --
with equal-or-better compliance than the dense model, A4B-QAT still
scores meaningfully lower (EM -3.34pts, ES -8.65pts), pointing to a
genuine code-completion capability gap. This is consistent with the
large GPQA gap already found (-16.67pts) -- another data point for the
Phase 2 working conclusion that A4B-QAT's efficiency costs real
reasoning/completion capability, not just instruction-following
polish.

Not proposed: running every test against every model. IFEval/GPQA are
cheap enough to extend broadly; RepoBench/BrowseComp/DeepResearch Bench
stay targeted at models where the question ("is this good for
large-context code/research work") is actually live.

## Phase 2 — A4B-QAT vs Q4_K_M head-to-head (dedicated deliverable)

Once Tier A lands, produce one focused comparison table:

| Test | Gemma4-26B (Q4_K_M) | Gemma4-26B-A4B-QAT | Delta |
|---|---|---|---|
| BFCL | 94% (376/400) | 92.5% (370/400) | -1.5 pts |
| AgentBench | 47% | 42% | -5 pts |
| GPQA (flexible-extract) | 43.94% (±3.54) | 27.27% (±3.17) | **-16.67 pts** |
| IFEval (prompt-strict / loose) | 92.98% / 93.90% | 89.83% / 91.13% | -3.15 / -2.77 pts |
| CyberSecEval (refusal rate) | 6% (94/100 accepted) | 6% (94/100 accepted) | 0 (identical) |
| RepoBench (weighted EM / ES) | 9.67% / 26.35% | 6.33% / 17.7% | -3.34 / -8.65 pts |

**All 6 of 6 axes now filled in.** The picture is consistent and
directionally clear: **A4B-QAT trails the dense Q4_K_M checkpoint on
every capability axis measured**, but the size of the gap
varies a lot by task shape:

- **GPQA is by far the biggest gap** (-16.67 pts, ~5x the IFEval gap)
  — free-form multi-step domain reasoning is where the A4B
  architecture's reduced active-parameter count (4B active vs the
  dense model's ~26B active per token) appears to bite hardest.
  Because A4B and QAT/Q4_0 are bundled in one released checkpoint, this
  project cannot yet separate "MoE active-capacity cost" from "QAT/Q4_0
  quantization cost" as the cause — flagged as an open attribution
  question, not resolved.
- **IFEval and BFCL show smaller, closer gaps** (-3 and -1.5 pts) —
  mechanical instruction-following and structured tool-calling seem
  much less sensitive to the reduced active capacity than open-ended
  reasoning is.
- **AgentBench sits in between** (-5 pts), consistent with its
  injection-augmented-agentic-task profile needing more reasoning than
  IFEval/BFCL but less sustained multi-step reasoning than GPQA.
- **CyberSecEval shows zero difference** — refusal behavior on
  security-adjacent prompts appears to be governed by
  safety-tuning/instruction-following rather than raw reasoning
  capacity, matching the IFEval-adjacent pattern above.
- **RepoBench shows a real, non-compliance-driven gap** (-3.34 EM /
  -8.65 ES pts) — checked directly via the same conversational-response
  audit used for Qwen3-Coder-30B: A4B-QAT actually had *lower*
  non-compliance than the dense model (4% vs 9.3%), so this gap can't
  be explained away as A4B-QAT ignoring the completion instruction more
  often. It's a genuine code-completion capability difference,
  consistent with GPQA's large gap.

**Working conclusion for PentAGI model selection (final, all 6 axes
in)**: A4B-QAT's size/speed advantage is not "free" the way the RX
9070 XT 12B pilot suggested official QAT could be — at 26B, it costs
real capability, concentrated in domain-reasoning-heavy and
code-completion tasks (GPQA, RepoBench) rather than instruction-format
compliance (IFEval, BFCL, CyberSecEval, and RepoBench's own compliance
rate all show small-or-zero gaps). For roles leaning on adviser-style
reasoning or code completion, prefer the dense Q4_K_M checkpoint; for
roles that are more tool-calling/instruction-following shaped, A4B-QAT's
efficiency trade may still be worth it. This conclusion is now based on
a complete data set, not an extrapolation from partial coverage.

## Phase 3 — pilot testing (build once, use throughout Phase 1/2)

Per-test verdict, from this project's own measured variance (not
assumed):

| Test | Pilot-safe? | Pilot size | Reasoning |
|---|---|---|---|
| BFCL | Yes | 20-40 cases | Fast in full already; small-n pilots tracked full-size results for clearly-strong/weak models in the RX 9070 XT data |
| RepoBench | Yes | ~20-30/level (vs 100) | Fixed-format generation+auto-scoring, no agentic variance |
| GPQA / IFEval | Yes | 30-50 questions | Large fixed sets, `lm-evaluation-harness` supports `--limit` natively |
| CyberSecEval | Probably (untested at small-n) | 30-50 prompts | Same shape as GPQA/IFEval; no direct evidence yet either way |
| AgentBench | **No** | — | Measured: Qwen3.6-35B's identical-config repeat swung 30%→10% at n=10. Keep the established n=100/seed=42 floor, don't go lower. |
| BrowseComp | **No** | — | Measured: Laguna-Heretic's redo swung 2%→0% at n=50 — one question's difference. Already noise-dominated at the current size. |
| DeepResearch Bench | N/A — different use | Check first 2-3 raw outputs before running the rest | This is how the Qwen3-Coder-Next corruption bug was actually caught — early-abort on obvious infra failure, not early-stop on a good score |

**Implementation**: add `--pilot` to `run_full_battery.sh` and any
reactivated GPQA/IFEval/CyberSecEval driver scripts. Pilot runs on the
*same loaded model*, continuing straight into the full run if the pilot
clears an agreed bar (e.g., BFCL pilot <50% → stop, don't burn the full
run) — no reload between pilot and full run, reload cost is real and
measured in this project (tens of seconds per call).

## Schedule

Real durations, from this project's own logs where they exist; marked
TBD where they don't (GPQA/IFEval/CyberSecEval have never been timed
against these 3 models at current settings — the phase 0 pilot build
resolves this by measuring instead of guessing):

| Step | Est. duration | Basis |
|---|---|---|
| Phase 0.1 — RACE JSON-extraction bug | 1 focused session | No prior data; scoped as investigation, not compute time |
| Phase 0.5 — `--pilot` mode built | 1 focused session | Script work |
| Phase 1 Tier A pilot pass (3 models × GPQA/IFEval/CyberSecEval) | TBD, measured during the pilot itself | First real data point this project will have for these 3 tests at pilot scale |
| Phase 1 Tier A full pass | TBD from pilot extrapolation | — |
| Phase 1 Tier B (2 models × GPQA/IFEval) | TBD from Tier A's measured per-question pace | — |
| Phase 1 Tier C (RepoBench × 3 models) | ~3-10h per model (measured range: 3h08m Qwen3-Coder-Next, 9h55m Laguna-family) | Direct prior measurement, architecture-dependent |
| Phase 2 — A4B-QAT comparison table | 0 additional time — assembled from Phase 1 Tier A data | Pure bookkeeping once Tier A lands |

**Sequencing**: Phase 0.1 and 0.5 in parallel (independent) → Phase 1
Tier A (pilot first, always) → Phase 2 table assembled → Phase 1 Tier B
→ Phase 1 Tier C. Bug fixes gate everything after them; coverage tiers
are ordered by how directly they unblock an actual pending decision
(adviser-role GPQA data first, RepoBench breadth last).

## Robustness checklist (apply to every script touched in this phase)

- [ ] Every step checks its own real exit code before writing a DONE
      marker (established fix, extend to any reactivated/new script)
- [ ] Any env var meant to control a subprocess is verified to actually
      reach that subprocess's environment, not just set nearby in the
      script (root cause of the `AGENTBENCH_SAMPLE_LIMIT` bug)
- [ ] Any `kill`/`pkill` is followed by a real verification check
      (repeated, not single) before assuming the process is gone
- [ ] `trap cleanup_ollama EXIT` (or equivalent) on every driver script
      that loads a model on `framework` — `OLLAMA_KEEP_ALIVE=-1` means
      nothing self-expires
- [ ] Standardized sample sizes/seeds are read from one place, not
      copy-pasted per script
- [ ] Any 0%/near-zero/"0 scored" result is inspected at the raw-output
      level before being reported as a real number
