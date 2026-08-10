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

## Phase 0 — bug fixes (do first; running more tests on broken infra wastes time)

| # | Bug | Fix | Priority | Notes |
|---|---|---|---|---|
| 1 | RACE judge fails JSON extraction ~85% of the time, even on real content | Root-cause via direct inspection: check whether the judge's raw output is truncated (num_predict too small for a full multi-criterion JSON object), wrapped in markdown fences the extractor doesn't strip, or a genuine prompt/parser mismatch. Fix whichever it is. | **Highest** — blocks trustworthy DeepResearch Bench scores for every model, not just one | Cheapest fix on this list relative to its payoff |
| 2 | BrowseComp sits at the floor for every model tested | Iteration cap was already fixed (5→12) and didn't move the score. Improve the SearXNG shim itself: more results per query, query reformulation, or a better-tuned backend. If still at floor after that, treat BrowseComp as not currently viable for model differentiation and say so plainly rather than keep re-running it. | Medium | Real engineering, uncertain payoff — timebox this |
| 3 | Qwen3-Coder-Next corrupts long-form generation (~85-100%) | Try chunked generation (smaller `num_predict` per call, stitched together — same pattern the article-cleaner already uses) as a real attempt before accepting permanent exclusion. | Low | Only worth it if DeepResearch Bench turns out to matter for a decision this model is actually a candidate for |
| 4 | Kimi-Dev-72B tool-calling broken (real upstream Ollama bug) | Try `volker-mauel/Kimi-Dev-72B-GGUF` — untested alternate conversion that might ship a working chat template. One download + smoke-test, not a big commitment. | Low-medium | If it doesn't work, drop Kimi-Dev-72B from this project for good rather than revisiting again |
| 5 | Every multi-hour test currently runs at full size with no early-abort | Build `--pilot` support (see Phase 3) | Medium | Prerequisite for running Phase 1/2 efficiently, do alongside #1 |

## Phase 1 — coverage gaps

Current state (✅ = real number exists, ⬜ = missing, — = out of scope for this model):

| Model | BFCL | AgentBench | GPQA | IFEval | CyberSecEval | RepoBench |
|---|---|---|---|---|---|---|
| Qwen3-Coder-30B (production) | ✅ | ✅ | ✅ | ✅ | ✅ | ⬜ |
| Qwen3.6-35B | ✅ | ✅ | ✅ | ✅ | ⬜ | — |
| Gemma4-26B (dense) | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Gemma4-26B-A4B-QAT | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Laguna S2.1 (base) | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |
| Qwen3-Coder-Next | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ |
| Laguna-Heretic | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ✅ |

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

**Tier B — new coverage** (never tested at all on these axes; matters
because BFCL/AgentBench alone don't tell you general-reasoning fit for
the adviser role):
- Qwen3-Coder-Next: GPQA, IFEval
- Laguna-Heretic: GPQA, IFEval — also directly answers whether
  decensoring cost anything on general reasoning, not just tool-call
  format (see the BFCL/AgentBench split-signal finding already on
  record)

**Tier C — RepoBench expansion** (currently only 2 of 7 models tested):
- Qwen3-Coder-30B — the actual production pick has never been measured
  against the benchmark that now exists specifically for large-context
  code completion; establishes a real baseline against Qwen3-Coder-Next
- Gemma4-26B + Gemma4-26B-A4B-QAT — cheap enough to add, gives the
  A4B-QAT comparison a code-completion data point too

Not proposed: running every test against every model. IFEval/GPQA are
cheap enough to extend broadly; RepoBench/BrowseComp/DeepResearch Bench
stay targeted at models where the question ("is this good for
large-context code/research work") is actually live.

## Phase 2 — A4B-QAT vs Q4_K_M head-to-head (dedicated deliverable)

Once Tier A lands, produce one focused comparison table:

| Test | Gemma4-26B (Q4_K_M) | Gemma4-26B-A4B-QAT |
|---|---|---|
| BFCL | 94% (376/400) | 92.5% (370/400) |
| AgentBench | 47% | 42% |
| GPQA | TBD | TBD |
| IFEval | TBD | TBD |
| CyberSecEval | TBD | TBD |
| RepoBench | TBD | TBD |

This directly answers the question the A4B-QAT test was built for
(does official QAT beat general PTQ at 26B, the way it clearly did at
12B in the RX 9070 XT pilot) — currently unanswerable with only 2 of 6
axes filled in.

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
