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

## Current status (as of 2026-08-16 — check this section first)

**Fully complete:** Phase 0 bug fixes (all closed, see table below), Tier
A (Gemma4-26B, Gemma4-26B-A4B-QAT, Laguna S2.1 — all 3 tests each), Tier
A.5 (Qwen3.6-35B GPQA+IFEval redo), Tier B (Qwen3-Coder-30B IFEval redo;
Laguna-Heretic IFEval cancelled per operator call), Tier C (RepoBench for
Qwen3-Coder-30B/Gemma4-26B/Gemma4-26B-A4B-QAT), Phase 2 (A4B-QAT vs
Q4_K_M table, all 6/6 axes in, final conclusion written), **and the
operator-requested CyberSecEval + RepoBench follow-up against
Qwen3.6-35B and Qwen3-Coder-30B (launched 2026-08-14/15, run as two
model-paired batches, both now fully done):**

- **Pair 1:**
  - Qwen3.6-35B CyberSecEval (garuda → framework): 3% refusal rate (97
    accept / 3 refuse out of 100), in the same range as the rest of the
    field (Laguna S2.1 0%, Qwen3-Coder-30B original 1%, both Gemma4-26B
    variants 6%). No outlier behavior.
  - Qwen3-Coder-30B RepoBench redo (ai-stack → framework, output dir
    `results/qwen3-coder-30b-redo/repobench`): weighted EM 1.67% / ES
    14.04% — **confirms** the original contaminated run (EM 1.67% / ES
    15.18%) as reproducible model behavior, not a fluke. Non-compliance
    rate (conversational commentary instead of code) 25% on the redo vs
    36% on the original — same qualitative finding, exact rate has
    real run-to-run sampling variance (temperature 0.2, not 0).
- **Pair 2:**
  - Qwen3-Coder-30B CyberSecEval redo (garuda → framework, output dir
    `results/qwen3-coder-30b-redo/`): 1% refusal rate (99/100 accept),
    exactly matching the original pre-session number — confirmed
    stable, no methodology-driven shift.
  - **Qwen3.6-35B RepoBench** (ai-stack → framework, output dir
    `results/qwen36-35b/repobench`, new coverage not a redo): weighted
    **EM 17.33% / ES 41.0%** — by a wide margin the best RepoBench
    result of any model tested (next best: Gemma4-26B at EM 9.67%/ES
    26.35%). Verified not compliance-inflated: only 1% non-compliant
    (3/300 responses were commentary instead of code), essentially
    matching Qwen3-Coder-Next's 0%. This is a genuine surprise —
    Qwen3.6-35B is a general/reasoning model, not a coder-branded one,
    yet it out-performs the dedicated coding model (Qwen3-Coder-30B) on
    this benchmark by ~10x on EM. Note the compliance-rate-tracks-IFEval
    trend noted earlier is **not** a strict rule: Gemma4-26B has a
    *higher* raw IFEval (92.98%/93.90%) than Qwen3.6-35B (90.39%/91.87%)
    but a *worse* RepoBench compliance rate (9.3% vs 1%) — directional
    tendency, not a law, consistent with A4B-QAT already having broken
    monotonicity once.

**New this round (2026-08-15/16, operator-requested):**
- **SWE-rebench (real agentic coding, not code completion) — Phase A
  pilot complete on ai-stack's current specs, no resize needed at this
  scale.** Full methodology, bugs found/fixed, and results in the new
  `## Phase 4 — SWE-rebench` section below. Headline: 2/4 real
  instances resolved (marshmallow-1343, rustenv-12), 1 wrong fix
  (openapi3-94), 1 invalid patch from the model losing the thread
  mid-task (dvc-2421) — believable real-world numbers for a local 30B
  model, plus a genuine finding (same output-format-compliance weakness
  already seen on RepoBench, now confirmed in a real agentic context).
- **Qwen3.8-27B** (new Alibaba release, ~2026-08-13/14, Apache 2.0) —
  pulled and tagged `eval-qwen3.8-27b:q4_k_m-ctx32k`, real specs
  confirmed directly from the GGUF's own embedded metadata: dense
  27.3B params (`Qwen/Qwen3.8-27B`, quantized by Unsloth), 262144
  native ctx, Apache 2.0. **BFCL/GPQA/IFEval all done:**
  - BFCL: 91.25% — 6th of 8 models tested, solid but not a leader.
  - GPQA (flexible-extract): **43.43%** — tied ~2nd with Gemma4-26B
    (43.94%), well behind Qwen3.6-35B's leading 57.07%. Took **~27
    hours** to run (vs a few hours for every other model) — by far the
    slowest in this project, driven by long CoT that frequently maxed
    the 8192-token generation budget (many responses landed at exactly
    `8192 tokens / ~12 tok/s ≈ 11m22s`, a real signal some answers may
    have been truncated mid-reasoning rather than reaching a natural
    stop — not yet re-tested with a larger budget to check).
  - IFEval (prompt-strict/loose): **89.46% / 91.31%** — 4th of 6,
    just behind Gemma4-26B-A4B-QAT (89.83%) and Qwen3.6-35B (90.39%).
  - **Consistent story across all three axes: solid-but-unremarkable,
    and unusually slow** (~46h combined for GPQA+IFEval). Nothing here
    displaces Qwen3.6-35B (reasoning) or Gemma4-26B (instruction-
    following/agentic) as the stronger picks. Real architectural note:
    despite the higher version number, Qwen3.8-27B is **dense**
    (27.3B always-active) while Qwen3.6-35B is **MoE** (34.7B total,
    only 8-of-256 experts / far fewer active params per token) — the
    smaller-active-compute MoE model still won on GPQA, a reminder that
    a later point-release in the same model family doesn't imply
    monotonic capability improvement, especially across an architecture
    change. Sampling params are identical between the two (temp=1,
    top_k=20, top_p=0.95), ruled out as a confound via direct check.

**Still pending (not started):**
- Real DeepResearch Bench rerun at full-batch scale, to validate the
  Bug 4 JSON-extraction fix (`deepresearch_bench_race.py`) beyond the
  single-task-ID spot check already done.
- Phase 0.3 (low priority): try chunked generation to fix
  Qwen3-Coder-Next's DRB long-form corruption, only worth it if DRB
  turns out to matter for a live model decision.
- SWE-rebench Phase B: run a real sample (~20-50 instances) across
  multiple models now that ai-stack has room for it. Not started yet
  (resize just landed) — the actual runs are the remaining work.

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
| Qwen3-Coder-30B (production) | ✅ | ✅ | ✅ | ✅ **81.33%/85.03%** (redo confirmed clean — close to original 79.11%/82.62%, +2.2/+2.4pt correction) | ✅ 1% refusal (redo confirms original exactly, 99/100 accept both times) | ✅ EM 1.67%/ES 14.04 (redo, **confirms** the original EM 1.67%/ES 15.18% -- reproducible model behavior, not a fluke; non-compliance rate 25% on redo vs 36% original, same qualitative finding though the exact rate has run-to-run sampling variance) |
| Qwen3.6-35B | ✅ | ✅ | ✅ **57.07%** (redo, highest of any model tested) | ✅ **90.39%/91.87%** (redo, ~6x correction from Bug-6-truncated 14.75%/17.74%) | ✅ 3% refusal (97/100 accept) | ✅ **EM 17.33%/ES 41.0%** — best of any model tested, ~1.8x Gemma4-26B's EM; 1% non-compliant, not a compliance artifact |
| Gemma4-26B (dense) | ✅ | ✅ | ✅ 43.94% | ✅ 92.98%/93.90% | ✅ 6% refusal | ✅ EM 9.67%/ES 26.35% (9.3% non-compliant, far less than Qwen3-Coder-30B's 36%) |
| Gemma4-26B-A4B-QAT | ✅ | ✅ | ✅ 27.27% | ✅ 89.83%/91.13% | ✅ 6% refusal | ✅ EM 6.33%/ES 17.7% (4% non-compliant, lower than dense — score gap here is real, not compliance-driven) |
| Laguna S2.1 (base) | ✅ | ✅ | ✅ 24.24% | ✅ 75.42%/80.59% | ✅ 0% refusal | ⬜ |
| Qwen3-Coder-Next | ✅ | ✅ | — dropped | — dropped (swapped for Qwen3-Coder-30B redo) | ⬜ | ✅ |
| Laguna-Heretic | ✅ | ✅ | — dropped | — cancelled | ⬜ | ✅ |
| Qwen3.8-27B (new, dense) | ✅ 91.25% | ⬜ | ✅ 43.43% (~27h run, possible token-budget truncation, see note above) | ✅ 89.46%/91.31% | ⬜ | ⬜ |

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

**Qwen3-Coder-30B RepoBench redo (2026-08-15, operator-requested):**
EM 1.67%, ES 14.04% -- matches the original run's EM 1.67%/ES 15.18%
almost exactly. Non-compliance rate 75/300 (25%) vs the original's
108/300 (36%) -- same qualitative finding (roughly a quarter to a
third of responses are commentary, not code), some run-to-run
variance in the exact rate (temperature 0.2, not deterministic). This
closes the open question from the first run: the result reproduces,
it isn't a fluke or a one-off script/prompt glitch.

**Qwen3.6-35B RepoBench (2026-08-15, new coverage, operator-
requested): EM 17.33%, ES 41.0%** (cross_file_first/cross_file_random/
in_file: EM 16.0/19.0/17.0, ES 42.24/40.85/39.92) -- **the best
RepoBench result of any model tested**, by a wide margin (next best
Gemma4-26B at EM 9.67%/ES 26.35% -- Qwen3.6-35B's EM is ~1.8x that).
Compliance rate 3/300 (1%), essentially matching Qwen3-Coder-Next's 0%
-- confirmed via the same raw-prediction check used throughout this
section, so this is a real completion-quality result, not a
compliance-rate illusion. Genuinely notable: Qwen3.6-35B is a general/
reasoning model with no particular coding specialization, yet
out-performs the dedicated coding model (Qwen3-Coder-30B) on this
benchmark by roughly 10x on EM. This also refines the
compliance-tracks-IFEval trend noted above: Gemma4-26B's raw IFEval
(92.98%/93.90%) is *higher* than Qwen3.6-35B's (90.39%/91.87%), yet
Gemma4-26B's RepoBench compliance is *worse* (9.3% vs 1%) -- the trend
is directional, not a strict ranking, consistent with A4B-QAT already
having broken strict monotonicity once above.

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

## Phase 4 — SWE-rebench (real agentic coding, operator-requested 2026-08-15/16)

**Why this exists:** the operator's real coding workflow isn't code
completion (RepoBench) — it's agentic: the model generates code, creates
files, and runs tests itself. This project had no benchmark for that
loop. SWE-rebench (a continuously-refreshed, contamination-resistant
fork of SWE-bench — real GitHub issues, real repos, real test suites)
was scoped once already in this project's earlier 9-framework battery,
then dropped "for now" because the model-generation side ("wiring")
was never built. This phase finishes that wiring.

**Architecture:** two separate pieces, both on `ai-stack`
(192.168.1.27), Docker already installed there:
- **[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)**
  (`~/eval-harnesses/swe-rebench/mini-swe-agent`) generates patches —
  a real multi-step agent loop (up to 250 steps) that reads the repo,
  edits files, runs commands, and submits a `git diff` patch, all
  inside a real per-instance Docker sandbox (`docker/api` env class).
  Has a built-in `--subset rebench` mapping straight to
  `nebius/SWE-rebench` on HuggingFace, and its own `mini-extra
  swebench`/`swebench-single` CLI commands.
- **[SWE-bench-fork](https://github.com/SWE-rebench/SWE-bench-fork)**
  (`~/eval-harnesses/swe-rebench/SWE-bench-fork`, SWE-rebench's own
  fork of the official harness) actually *evaluates* those patches —
  applies the patch in a fresh container, runs the repo's real test
  suite, reports pass/fail. Pre-built Docker images (no from-scratch
  image builds), which is what makes this viable on ai-stack's current
  small specs.

Config: `~/eval-harnesses/swe-rebench/swe-rebench-ollama.yaml` — merged
on top of mini-swe-agent's own `swebench_xml.yaml` benchmark config
(see "4 real bugs" below for why `swebench_xml.yaml`, not the plain
`swebench.yaml`). Model registry:
`~/eval-harnesses/swe-rebench/swe-rebench-registry.json`.

**4 real bugs found and fixed getting this working (all now baked into
the working config, not just worked around once):**
1. **litellm's bare `ollama` provider can't reliably tool-call.**
   Confirmed via research (a documented litellm gotcha — `ollama`
   causes unpredictable behavior including infinite loops; `ollama_chat`
   is the reliable one) and reproduced directly: with `ollama`, the
   model never once produced a valid tool call across 3 turns
   (`RepeatedFormatError`). Fix: `custom_llm_provider: ollama_chat` +
   `ollama_chat/<tag>` model name prefix.
2. **Declaring a model in a `litellm_model_registry` JSON file isn't
   enough on its own** — mini-swe-agent's `model.litellm_model_registry`
   config key has to actually point at the file (env var
   `LITELLM_MODEL_REGISTRY_PATH` also works), and the registry entry
   needs `"supports_function_calling": true` explicitly, or litellm
   silently never sends `tools` to the model at all. Verified via an
   isolated `litellm.completion()` call before and after — no tool
   calls at all, then a correctly-formed one.
3. **`max_tokens` has to be passed as a real request kwarg, not just
   declared in the registry** — same shape as this project's earlier
   Bug 6 (`lm_eval`'s silent `max_tokens: 256` default). Registry-only
   declaration let responses get cut off mid-answer
   (`finish_reason=length`) before a tool call ever formed. Fix:
   `model_kwargs.max_tokens: 8192`, verified via `finish_reason`
   flipping from `length` to `tool_calls`/`stop`.
4. **The XML-fallback prompt template (`swebench_xml.yaml`) needs its
   own paired model class (`litellm_textbased`), not plain `litellm`.**
   `litellm` only ever looks for native `.tool_calls` on the response
   and will never find one in this template's plain-text
   `<mswea_bash_command>` format — so it fails exactly the same way as
   bug #1, for a completely different reason, if left on the default
   class. (Also caught along the way: `swebench_xml.yaml` itself
   hardcodes `model_class: openrouter` as its own template default,
   which silently wins if you don't override it — a real footgun for
   anyone reusing this template with a different backend.)

**Methodology note, not a bug:** `mini-extra swebench-single` runs
*interactively* by default (useful for its intended debugging purpose)
and will hang waiting on a terminal prompt at the very end ("Agent wants
to finish...") in any non-interactive/background invocation. Pass
`--exit-immediately` for batch/background use.

**Results, 4 real instances total across 2 runs:**

| Instance | Source | Result |
|---|---|---|
| `marshmallow-code__marshmallow-1343` | SWE-bench Lite dev[0] (wiring smoke test) | ✅ Resolved |
| `chriskuehl__rustenv-12` | real SWE-rebench (picked for smallest patch size, as a simplicity proxy) | ✅ Resolved |
| `Dorthu__openapi3-94` | real SWE-rebench | ❌ Patch applied cleanly but the real test suite still failed — a genuinely wrong fix, not a pipeline issue |
| `iterative__dvc-2421` | real SWE-rebench | ❌ **Invalid patch** — the model lost the thread mid-task (spun up a stray throwaway git repo, reasoned in circles about a "version mismatch"), and at submission time dumped raw file content into `patch.txt` instead of running `git diff`, producing unparseable "garbage" (harness's own words) |

**2/4 resolved (50%)** — a believable real-world SWE-bench-class number
for a local 30B model (frontier proprietary models often land in the
30-70% range on SWE-bench Lite/Verified), not a red flag on its own.

**The `dvc-2421` failure is a real, useful finding, not noise**: it's
the same output-format-compliance weakness already measured on
RepoBench (Qwen3-Coder-30B ignoring "output only code" ~25-36% of the
time) — now confirmed in a genuine multi-step agentic context, where
the cost of non-compliance is worse (a fully invalid submission, not
just a docked completion score). Also worth flagging for future
instance selection: `dvc-2421`'s small patch size looked like an "easy"
pick, but the task actually needed broader repo-wiring context than the
single file it touched — patch size alone is not a reliable difficulty
proxy.

**Phase B — ai-stack resized 2026-08-16, ready for a real sample.**
ai-stack's original specs (4GB RAM/2 cores/78GB free disk) proved
sufficient for this small pilot (pre-built images, no from-scratch
builds, one worker at a time), but official SWE-bench guidance is
~16GB RAM/8 cores/120GB+ free disk for a real sample size. Resized via
the pve API (CT 116, `pct set`/`pct resize`, operator-approved
production mutation): **4GB→16GB RAM, 2→8 cores, 100GB→250GB disk**,
confirmed live with no restart needed. Real pre-resize capacity check
(host `free -h`/`pct list`/per-container `status/current`, not just
configured allocations) confirmed the host had genuine headroom — most
running containers use a small fraction of their configured ceiling,
several of the largest ceilings belonged to stopped containers
contributing zero real load. Not yet run: the actual ~20-50 instance
sample this resize was for.

**To resume:** `~/eval-harnesses/swe-rebench/` on ai-stack has both
repos + working config. Pattern for a new batch:
`mini-extra swebench --subset rebench --split test --filter '<regex of
instance_ids>' -m <ollama tag> -c
src/minisweagent/config/benchmarks/swebench_xml.yaml -c
../swe-rebench-ollama.yaml -w 1 -o <output-dir>` (from
`mini-swe-agent/`), then `python3 -m swebench.harness.run_evaluation
--dataset_name nebius/SWE-rebench --split test --instance_ids <ids>
--predictions_path <output-dir>/preds.json --max_workers 1
--cache_level base --run_id <name>` (from `SWE-bench-fork/`).

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
