# Local-model eval framework expansion — 2026-08

## Status: harnesses in place — all 9 frameworks smoke-test-clean

## Overnight budget cap (2026-08-05, operator directive)

ARC-AGI's real battery revealed a genuine, task-content-dependent
degenerate-output failure mode in `eval-qwen3-coder-30b-a3b` (see below)
that made unbounded per-framework runs impractical — the full 120-task
ARC-AGI set alone projected to ~14-15 hours at observed pace. Operator
capped scope: **13 hours total, overnight, covering both Qwen models**
(Qwen3-Coder-30B's remaining Tier 2/3 + Qwen3.6-35B's full Tier 1-3).

Caps applied to the three open-ended frameworks (GPQA/IFEval run at
full size — cheap and valuable, not capped):
- **ARC-AGI**: 30 tasks (`--max-tasks-per-run`), 5-min per-task timeout
  (`--max-task-timeout 300`)
- **GAIA**: 15 tasks (`GAIA_SMOKETEST_LIMIT`)
- **AgentBench**: 15 episodes (`AGENTBENCH_SAMPLE_LIMIT`)

τ²-bench/CyberSecEval run at a reasonable full/near-full scale — both
are naturally fast (seconds per trial), not worth capping. **Correction
mid-run**: CyberSecEval's `mitre-frr` (750 prompts) is *not* naturally
fast against a local model — the first prompt alone climbed past 4,000
generated tokens with no sign of stopping. Root cause: PurpleLlama's
`OPENAI` adapter (`CybersecurityBenchmarks/benchmark/llms/openai.py`)
only sends `max_completion_tokens` when the model name matches one of
OpenAI's own hardcoded reasoning-model strings (`o1`, `o3`, etc.) — for
any other model, including ours, the field is `NOT_GIVEN` and omitted
from the request entirely. OpenAI's real API applies a sane default
when that happens; Ollama does not, so it just generates until it
exhausts context. Real bug in a third-party dependency, not something
to patch in that dependency's own code — fixed at the Ollama layer
instead by baking `PARAMETER num_predict 2048` into both Qwen ctx32k
tags as a safety net (a client-set `max_tokens` still overrides this
per normal Ollama precedence, so nothing that already caps its own
tokens is affected). Also capped the CyberSecEval prompt set itself to
100 (`mitre_frr_100.json`, first 100 of 750) given the overnight budget.

## Autonomous overnight execution (2026-08-05)

Operator will not stay at the machine overnight and does not want
`this session's own liveness` (tied to VSCode staying open) to be a
dependency for the rest of the Qwen battery. Sequencing was moved out
of the interactive session and into two self-contained driver scripts,
launched via `setsid nohup ... &; disown` so they survive both this
session ending and any SSH/VSCode disconnect:

- **`~/eval-harnesses/overnight-framework.sh`** (on `framework`) —
  Qwen3.6-35B's GPQA → IFEval → ARC-AGI (capped 30/5min) → τ²-bench,
  sequentially. Touches `~/eval-harnesses/FRAMEWORK_SEQUENCE_DONE` when
  finished. Driver's own stdout/stderr: `overnight-framework-driver.log`;
  each step logs to its usual `qwen36-35b_<step>.log`.
- **`~/eval-harnesses/overnight-garuda.sh`** (on `garuda`) —
  Qwen3-Coder-30B's remaining CyberSecEval → GAIA → AgentBench, then
  the same three for Qwen3.6-35B (AgentBench's task server is started
  once and reused across both models' runs rather than restarted).
  Touches `GARUDA_CODER_DONE` after Coder's three, `GARUDA_ALL_DONE` at
  the very end. Driver's own stdout/stderr:
  `overnight-garuda-driver.log`; each step logs to its usual
  `<model>_<step>.log`.

Both scripts use `set -x` and `cd ... || exit 1` throughout (fail loud
and stop rather than silently continue in the wrong directory
unattended). Repo copies of both scripts are *not* committed — they're
transient session tooling in `~/eval-harnesses/`, not project source;
if this pattern proves durable it should move into
`scripts/pentagi-test-harness/`-style tracked tooling later.

**To check progress on a resumed session**: `ssh framework.gibbsgreatly.xyz`
and check for `FRAMEWORK_SEQUENCE_DONE`; on `garuda`, check for
`GARUDA_ALL_DONE`. Absence of either marker + a live `pgrep` for the
driver script means still running; absence of the marker + no live
process means it crashed partway — check the driver's own log first
for a Python traceback or `cd` failure.

### Overnight run outcome (2026-08-06): budget blown ~2x, real bugs found

The driver scripts did survive the session interruption exactly as
designed — that part worked. But the run itself overshot the 13-hour
ceiling badly (launched 2026-08-05 07:52, still running unintended work
at 2026-08-06 07:57 — **~24 hours elapsed**) due to two independent bugs
found only once real (non-capped-by-design) execution exposed them.
Stopped all further autonomous runs once this was clear rather than
risk compounding the overrun with an undiscovered third bug.

**Bug 1 — `AGENTBENCH_SAMPLE_LIMIT` never applied.** The env var was
exported right before launching the *assigner*, but `get_indices()`
(the code that reads it) executes in the **task-server worker
process**, which the driver script starts earlier — before that env
var was ever set in its environment. The cap silently never took
effect. Consequence: Qwen3-Coder-30B's AgentBench ran the full 800/800
episodes (not the intended 15) — **took 7h25m instead of an intended
~15min**. The result itself is genuinely valid (800/800 completed
successfully, real data, just far more of it than intended). Qwen3.6-35B's
AgentBench was still at 123/800 (~2h08m in, projecting ~14 more hours)
when caught and killed — no usable result.

**Bug 2 — Qwen3.6-35B needed a much larger token budget than assumed.**
Confirmed via direct testing: this tag is a genuine reasoning model with
a separate `reasoning` field distinct from `content` — even a trivial
one-word-answer question burned 160 completion tokens, and a
moderately complex question hit `finish_reason: length` at 2048 tokens
with its `content` field cut off mid-sentence. The `num_predict=2048`
safety net (sized for CyberSecEval's short prompts, and reasonable for
Qwen3-Coder-30B which isn't nearly as verbose) starved Qwen3.6-35B of
room to reach a parseable final answer on anything non-trivial. Bumped
to `num_predict=8192` on the Ollama tag once found, but this was
**not** re-run before stopping — every framework that used the old
2048 cap (or, for τ²-bench, an even smaller explicit `max_tokens: 500`
in the driver script itself) for Qwen3.6-35B produced compromised
results:

- **GPQA**: 0% (both metrics) — see Bug 2, not a real capability result
- **IFEval**: ~15-18% across metrics — same
- **ARC-AGI**: 0.00%, but "Average Prompt/Output/Total Tokens per Task:
  0.0" across all 30 attempted/92 total attempts — essentially zero
  real generations succeeded, pure infra failure, not a capability result
- **τ²-bench**: 47/50 marked "Infra Errors", only 3 tasks actually
  evaluated (0.33 avg reward on that tiny n=3) — not usable
- **AgentBench**: killed at 123/800, likely also affected by its own
  agent config's `max_tokens: 1024` cap — not usable

**Bug 3 (separate, smaller) — GAIA never ran at all, either model.**
The driver script's `run_gaia()` function never activated
`smolagents`' venv (unlike `run_agentbench()`, which correctly does)
— bare `python3` doesn't have the `smolagents` package installed,
so both GAIA invocations crashed immediately with
`ModuleNotFoundError: No module named 'smolagents'`. Zero GAIA data
for either model tonight.

**What's actually valid from tonight, in full:**

| Test | Qwen3-Coder-30B | Qwen3.6-35B |
|---|---|---|
| GPQA | 11.62% flex / 0% strict ✅ | 0% / 0% — compromised, not real ❌ |
| IFEval | 79-88% across metrics ✅ | 15-18% — compromised, not real ❌ |
| ARC-AGI-2 | 0.00% (0/18 scored, real) ✅ | 0.00% (pure infra failure) ❌ |
| τ²-bench (airline) | 0.46 avg reward, 50/50 evaluated ✅ | 0.33 avg reward, only 3/50 evaluated ❌ |
| CyberSecEval (mitre-frr, 100) | 99% accept / 1% refusal ✅ | not yet run |
| GAIA | crashed, 0 data ❌ | crashed, 0 data ❌ |
| AgentBench (os-std) | 800/800 completed (real, just way over the intended 15-sample cap) ✅ | killed at 123/800, not usable ❌ |

**Fixes already made, ready for a clean re-run:**
- `AGENTBENCH_SAMPLE_LIMIT` needs to be exported *before* the task
  server (`python -m src.start_task -a`) is launched, not just before
  the assigner — the driver script needs restructuring, not just a
  reorder of two lines in the same function.
- Qwen3.6-35B's Ollama tag (`eval-qwen36-35b-a3b:q4_k_m-ctx32k`) now has
  `num_predict=8192` (was 2048) — needs GPQA/IFEval/ARC-AGI re-run
  against the fixed tag.
- τ²-bench's driver invocation needs `max_tokens` raised well past 500
  for Qwen3.6-35B specifically (its agent-llm-args, not the tag default).
- AgentBench's `configs/agents/qwen36-35b.yaml` `max_tokens: 1024` likely
  needs raising too, unverified.
- `run_gaia()` in `overnight-garuda.sh` needs `source
  ~/eval-harnesses/smolagents/.venv/bin/activate` (or wherever its venv
  actually lives — not yet confirmed) added before invocation.

**Not re-run tonight** — stopping here rather than risk a third
undiscovered bug burning more unsupervised hours. Pending operator
decision on whether/how to redo the compromised Qwen3.6-35B battery and
both models' GAIA runs.

### Interpretation for real use cases (2026-08-06)

AgentBench's real pass rate (`overall.json`, not just "800/800
completed" which only means no crash): **27% (216/800 pass, 76.9%
ran-to-completion, 16.4% invalid/malformed actions, 6.75% ran out of
turns)**.

**Scope correction (2026-08-06, see the "os-std scope correction" note
under the RX 9070 XT section below for full detail)**: this 800-task
os-std set is not general multi-category OS-interaction — the active
task config in this fork only exercises 14 ordinary sysadmin-style
tasks replayed with the environment's tool output laced with injected
adversarial content (660/800 have `injection_present: true`). Read
every "AgentBench 27%/22%/24%" figure in this doc as "task completion
under adversarial tool-output content," which if anything is a more
demanding, more pentesting-relevant test than plain os-std would have
been — not a weaker one — but it's not measuring what the original
"Frameworks in scope" table description implied.

**Strong, confirmed**: BFCL tool-calling (96.25%, fastest — already won
`framework`'s slot-2 role), IFEval (79-88%, reliable structured output),
CyberSecEval mitre-frr (99% accept/1% refuse — low friction in a
pentesting context, though this only measures false refusals on benign
prompts, not correct refusal of genuinely malicious ones).

**Weak, confirmed — the important finding**: GPQA 11.62%/0%, *below*
the 25% random-guess baseline for 4-choice questions — not a
general-reasoning model, narrowly coding-specialized. AgentBench 27%
pass and τ²-bench's 4.4%-correct read-actions (despite 0.46 avg reward)
both point the same direction: strong at atomic, well-specified tool
calls (BFCL's exact shape), but reliability drops sharply on sustained
multi-step agentic sequences — exactly PentAGI's terminal/pentester
role shape, not BFCL's.

**Practical read**: slot-2 tool-use role stands (matches BFCL's atomic
shape). PentAGI adviser role — poor fit (weak general reasoning), keep
routing through a stronger model there as already established.
PentAGI terminal-operator/pentester role — real caution, ~3-in-4
multi-step OS-interaction attempts failed; would need tight supervision
or short subtasks, not open-ended autonomous pentesting. Coder/
report-writing role — still genuinely unknown, SWE-rebench (the actual
code-gen benchmark) isn't wired up yet; don't extrapolate from IFEval.

**Operator directive (2026-08-05): fully autonomous from this point.**
No more pausing between stages for confirmation — chain straight through
the remaining plan (Qwen3-Coder-30B Tier 2/3, then Qwen3.6-35B Tier
1-3), only stopping for a genuine blocker (permission-classifier denial,
destructive/production action, or a decision only the operator can make
— not routine config/sample-size choices already covered by this plan).

### Qwen3-Coder-30B — Tier 1 final results (Ollama)

| Test | Metric | Score |
|---|---|---|
| GPQA (198 q) | flexible-extract | 11.62% |
| GPQA (198 q) | strict-match | 0.0% |
| IFEval (541 q) | inst-level, loose | 88.01% |
| IFEval (541 q) | inst-level, strict | 85.37% |
| IFEval (541 q) | prompt-level, loose | 82.62% |
| IFEval (541 q) | prompt-level, strict | 79.11% |
| ARC-AGI-2 (30 attempted, 18 scored, capped) | accuracy | **0.00%** (0/18) |

ARC-AGI's 0% reflects both genuine task difficulty (ARC-AGI-2 is hard
even for frontier models) and the degenerate-output failure mode
documented above, which affected an unquantified fraction of attempts.
Not re-run at larger scale given the overnight time budget — treat this
as a directional result, not a precise measurement.

### Qwen3.6-35B vs Qwen3-Coder-30B: direct AgentBench os-std comparison (2026-08-06)

Operator flagged AgentBench os-std results as weak and asked for a
direct, controlled comparison between the two Qwen models before doing
anything else. Ran Qwen3.6-35B against the identical standardized
sample (`AGENTBENCH_SAMPLE_LIMIT=100`, `AGENTBENCH_SAMPLE_SEED=42`) that
Coder's 24/100 baseline (from its earlier full-800 run) was drawn from,
this time with the `num_predict=8192`/`max_tokens=3072` fixes already
in place — so unlike the overnight run's compromised Tier 1 results,
this one is real capability data, not an infra-failure artifact.

| Model | Pass | Acc | Notes |
|---|---|---|---|
| Qwen3-Coder-30B | 24/100 | 24% | full-800 baseline, seed=42/limit=100 subsample |
| Qwen3.6-35B | 22/100 | 22% | clean run, token-budget fixes applied |

(Same os-std scope-correction note as above applies: this is task
completion under adversarial/injected tool-output content, not generic
multi-category OS interaction — see the RX 9070 XT section below.)
Essentially tied (within noise at n=100) — Qwen3.6-35B is **not** a
meaningfully better fit for sustained multi-step OS-interaction agentic
tasks despite being the larger/newer model. Its validation breakdown
also surfaced a genuine (non-infra) weakness: **71% "agent invalid
action"**, only 26% "completed" cleanly — the model frequently fails to
produce a parseable Think:/Act:-formatted action on these tasks, a real
formatting/instruction-following gap, not truncation (token budget was
already generous here).

**Practical read**: neither Qwen model is a safe fit for open-ended
autonomous multi-step agentic operation (PentAGI terminal/pentester
role) without tight supervision or short subtasks — reconfirms and
sharpens the "Interpretation for real use cases" conclusion above rather
than changing it.

## Runtime policy: Ollama only (2026-08-05, superseding earlier mixed policy)

**`llamacpp-router` is stopped on `framework`.** Earlier in this phase the
runtime was mixed per-model (see the BFCL table below), on the theory that
each model should use whichever runtime it scored best on. The operator
overruled this: mixing runtimes within one comparison makes the
comparison itself untrustworthy, since a runtime-driven quality/config
difference can't be distinguished from a genuine model-capability
difference. **All models in this project now run on Ollama
(`http://framework.gibbsgreatly.xyz:11434`), no exceptions.**

Consequence: every result recorded under the old mixed policy
(Qwen3-Coder-30B's GPQA, IFEval, and AgentBench runs, all on llama.cpp)
was deleted, not just superseded — see "Stale results cleared
2026-08-05" below. All framework configs (`arc-agi-benchmarking`'s
`models.yml`, AgentBench's `configs/agents/qwen3-coder-30b.yaml`) were
rewritten from `localhost:8080`/llama.cpp model names to Ollama's
`:11434` endpoint and Ollama tag names (e.g.
`eval-qwen3-coder-30b-a3b:q4_k_m-ctx163k`). lm-eval-harness invocations
(GPQA/IFEval) take `base_url` on the command line, not a config file, so
those just get the new endpoint at launch time going forward.

### Stale results cleared 2026-08-05

- `~/eval-harnesses/results/qwen3-coder-30b/{gpqa,ifeval}` (framework) — deleted
- `~/eval-harnesses/qwen3-coder-30b_{gpqa,ifeval,ifeval_retry}.log` (framework) — deleted
- `~/eval-harnesses/AgentBench/outputs/2026-08-05-12-4{2,3}-*` (garuda) — deleted (the real 93.35s/episode llama.cpp result)

The IFEval run that triggered this whole re-think crashed twice with a
hard llama.cpp 500 (`"model produced output that does not match the
expected peg-native format"` — Qwen3-Coder-30B briefly generating
unrelated Kannada-script text, which llama.cpp's grammar-enforcing
parser couldn't recover from). That crash plus the operator's
independent, stronger observation that Laguna S 2.1 scored
significantly better on Ollama than llama.cpp are what prompted
abandoning llama.cpp for this project entirely, not just working around
the crash.

**The Laguna S 2.1 runtime gap, quantified (found 2026-08-05):** raw
BFCL `simple`-category run logs and scores existed on `framework` in
`~/bfcl-eval/venv/lib/python3.14/site-packages/{result,score}/` (BFCL's
default output location — never copied into this repo, which is why an
earlier repo-only doc search for this comparison came up empty) but were
never folded into the table above. The real numbers:

| Laguna S 2.1 config | Runtime | Accuracy | Time (400 cases) |
|---|---|---|---|
| `Laguna-S-2-1-UD-Q4-K-M-FC` | **llama.cpp** | **75.5%** (302/400) | 1:23:31 |
| `Laguna-S-2-1-Ollama-FC` | Ollama | **92.75%** (371/400) | 51:23 |
| `Laguna-S-2-1-Ollama-Ctx131k-FC` | Ollama (131k ctx) | **92.75%** (371/400) | 48:48 |

17.25-point accuracy gap, and llama.cpp took nearly 2x as long. This is
the hard data behind the runtime-policy change above, not just the
operator's qualitative recollection. `Laguna-XS-2-1-Ollama-FC` also
scored 90.0% (360/400) in this same log set, but has no llama.cpp
counterpart — its runtime comparison remains genuinely untested.

### Real bug found: `eval-qwen3-coder-30b-a3b:q4_k_m-ctx163k` degenerates on long prompts (2026-08-05)

While running ARC-AGI's real 120-task battery, both of the first two
tasks (each with a ~13-14k-token prompt) failed every retry identically
— the model producing pure repeated `?` characters until hitting
`max_tokens`/`finish_reason: length`, never a real answer. Root-caused
by bypassing the harness and hitting Ollama directly:

- Replaying the exact same prompt via raw curl against
  `eval-qwen3-coder-30b-a3b:q4_k_m-ctx163k` (`num_ctx=163840`)
  reproduced the bug deterministically (100% `?` output,
  `finish_reason: length`).
- A repetition penalty (`frequency_penalty`/`presence_penalty` via the
  OpenAI-compat endpoint, and native `repeat_penalty`/`repeat_last_n`
  via `/api/chat`) had **zero effect** — ruling out a simple
  token-repeat-loop explanation.
- A content-independent control (generic filler text padded to
  ~18,000 tokens, trivial instruction) reproduced the same 100% `?`
  failure — proving it's **not ARC-AGI-specific content**, purely a
  long-prompt trigger on this one Ollama tag.
- The exact same 18,019-token prompt against
  `eval-qwen3-coder-30b-a3b:q4_k_m-ctx32k` (`num_ctx=32768`) returned a
  clean, correct, instant response. Against
  `eval-qwen3-coder-30b-a3b:q4_k_m-ctx147k` (`num_ctx=147456`) it also
  returned real, coherent (if rambling) text — not degenerate.

**Revised conclusion, after further testing exposed the first fix as
incomplete:** relaunching ARC-AGI's real battery on `-ctx147k` still
failed 2/2 tasks (100%, all retries) — including a *small*, 3,179-token
task, not just the huge outlier. Direct diagnostic requests isolated the
real pattern:

| Tag | `num_ctx` | Generic filler text (18k tok) | Real ARC-AGI content (3.2k tok) |
|---|---|---|---|
| `-ctx163k` | 163840 | fails (100% `?`) | fails (100% `?`) |
| `-ctx147k` | 147456 | **works** | fails (100% `?`) |
| `-ctx32k` | 32768 | works | **works** (coherent, correct reasoning) |

So it's not purely a length trigger — my first "control test" used
generic repetitive filler text, which is far more forgiving than
ARC-AGI's dense, structured grid content, and that masked the real
problem on `-ctx147k`. Only `-ctx32k` — the sole clean power-of-2 value
among the three tags — is reliable on real dense content. Working
hypothesis: RoPE-scaling numerics for the two non-power-of-2 extended
context sizes (147456 = 144×1024, 163840 = 160×1024) are unstable on
information-dense input specifically, not just long input; `32768`
(2¹⁵) doesn't hit the same instability. Not fully proven, but consistent
with everything observed.

**Practical fix: use `-ctx32k`.** Switched both ARC-AGI's `models.yml`
and AgentBench's `configs/agents/qwen3-coder-30b.yaml` to
`eval-qwen3-coder-30b-a3b:q4_k_m-ctx32k`. This means the rare
oversized ARC-AGI-2 tasks (one seen at 69,454 tokens) will now fail
cleanly with a prompt-too-long-style error instead of silently
producing degenerate garbage scored as a wrong answer — an honest
failure signal, acceptable for Tier 1. GPQA/IFEval's already-completed
results are unaffected (prompts far too short to hit any of this) and
are not being re-run. AgentBench's `os-std` transcripts could plausibly
grow past 32k tokens over many tool-call turns — worth re-checking when
Tier 3 actually runs, not assumed fixed by this change alone.

Also noted in passing: all three tags' Modelfiles have
`TEMPLATE {{ .Prompt }}` — a bare passthrough with no chat-role
formatting baked in. Ollama's OpenAI-compat layer still applies its own
chat templating on top of the `messages` array for API calls
regardless, so this didn't block any of the diagnosis above.

## Garuda RX 9070 XT BFCL pilot (2026-08-06)

An independent, bounded BFCL pilot was run on Garuda while the Framework
Desktop remained untouched.  It is **not** a replacement for the existing
400-case comparisons above: this is a labeled 20-case `simple` subset,
selected every 20 IDs from `simple_0` through `simple_380`, and must not be
reported as a leaderboard score.

The service was a separate `ollama-rx9070xt-eval` container running Ollama
0.32.6 with one model/request slot, 4096-token context, and only
`127.0.0.1:11435` published.  It was restricted to Garuda's RX 9070 XT via
`ROCR_VISIBLE_DEVICES`; all BFCL requests targeted that loopback endpoint.
No Framework hostname, process, port, model store, or result directory was
used or modified.  The original local Ollama container was not replaced.

The host's prior Ollama 0.24.0 could not load either requested GGUF because
its llama runtime did not recognize `qwen35moe`; the isolated current runtime
did.  BFCL 2025.8.6.2 was installed in a separate Garuda venv.  Its Qwen XML
tool prompt/result parser was retained while transport was adapted to the
already-running local GGUF service; the subset was then scored with BFCL's
own AST checker.

| Model / quantization | BFCL `simple` pilot | Client request time | GPU residency |
|---|---:|---:|---|
| Qwen3.6-35B-A3B `UD-Q4_K_M` | **20/20 (100%)** | 234.8s total; 11.7s mean/case | 65% GPU / 35% CPU; ~16.0GB VRAM |
| KAT-Coder-V2.5-Dev `Q4_K_M` | **19/20 (95%)** | 381.1s total; 19.1s mean/case | 69% GPU / 31% CPU; ~15.8GB VRAM |

Both models loaded and generated correctly on the RX 9070 XT.  KAT's single
failure was `simple_100`: it reasoned at length about whether a tool call was
necessary, answered in prose instead, and emitted no call (`Wrong number of
functions`).  Its pilot also generated more tokens on average (448.5 versus
Qwen's 318.3), including a several-thousand-token deliberation; this accounts
for the slower elapsed time.  The runtime did emit a non-fatal
`TensileLibrary_lazy_gfx1201.dat` rocBLASLt warning, but GPU offload, memory
residency, and all requests completed successfully.

Raw commands, adapter, generated responses, and per-case official BFCL scores
are intentionally kept under ignored
`docs/framework/artifacts/rx9070xt-bfcl/`.  Before a larger run, fix or
suppress the rocBLASLt gfx1201 warning and set a reviewed response-length
policy for KAT; retain the one-model serial setting so the pilot's isolation
and timing remain valid.

### Parallel AgentBench `os-std` controller (2026-08-06)

An independent AgentBench service is prepared for the two RX 9070 XT models,
without modifying the already-running Framework/Qwen3.6 run.  The latter
continues to own controller port 5098, worker port 5001, its 100-case cap,
and its assignment/output directory.  The new service is a separate copy at
`~/eval-harnesses/AgentBench-rx9070xt`, with controller port **5198**, worker
port **5101**, its own `outputs/rx9070xt/...` paths, and separate local-model
agent configs targeting `127.0.0.1:11435` only.

The new worker was started with `AGENTBENCH_SAMPLE_LIMIT=10` and
`AGENTBENCH_SAMPLE_SEED=9070` *before* worker initialization.  It advertises
a deterministic, randomly selected ten-episode `os-std` set and has zero
active sessions.  The dedicated loopback-only Ollama service is running but
has no model resident, so no GPU VRAM is currently occupied by this setup.
No assigner was started; a model episode begins only when deliberately
launched against either dedicated pilot assignment.

The isolated config/assignment sources live under ignored
`docs/framework/artifacts/rx9070xt-agentbench/`; the active harness copy is
runtime tooling under `~/eval-harnesses/`, consistent with the existing
AgentBench setup.

### RX 9070 XT pilot results: Ollama/ROCm vs llama.cpp/Vulkan (2026-08-06)

Operator ran both models against the RX 9070 XT (16GB) directly, across
two runtimes, to see what a single consumer-class 16GB card can offer for
`framework`'s "slot 2" role — a smaller/cheaper candidate class than
anything tested on `framework` itself so far. Same caution as the BFCL
pilot above: small-`n`, not a leaderboard score, informative direction
only.

**Correction (2026-08-06, superseding an earlier mistake in this doc):**
originally wrote that this pilot's os-std was "different, narrower" than
the main framework-side comparison and not comparable to it. That was
wrong — checked directly this pass: `~/eval-harnesses/AgentBench`'s own
`configs/tasks/os.yaml` (the one behind Qwen3.6-35B's 22/100 and Coder's
24/100 numbers) has the *identical* categories 1/2/3/5/6/7 commented
out, leaving only `data/os_interaction/data/prompt_injection/experiments.json`
active — this isn't specific to the RX 9070 XT copy, it's baked into the
`Eugleo/agent-bench` fork itself (confirmed via `git diff HEAD` showing
no local edit to this file) and has been the active os-std definition
for every AgentBench number in this entire project, including Coder's
original 27%/800 run. So **these RX 9070 XT numbers and the main
Qwen3.6-35B/Coder comparison numbers are on the same scope after all** —
directly comparable, not a different benchmark.

What that scope actually is, checked directly against the 800-entry
`experiments.json`: 14 real, ordinary OS-interaction task templates
(`check-weather`, `recent-file`, `exec-permissions`, `count-files`,
`parse-matrix`, etc. — genuinely representative everyday sysadmin-style
tasks, not synthetic injection puzzles), each replayed up to 70 times
with the environment's own tool output laced with injected adversarial
content (`injection_present: true` for 660/800; 140 are clean
no-injection controls). So "os-std" throughout this project has been
measuring **task completion under adversarial tool-output content**, not
generic multi-category OS capability — arguably a *more* relevant test
for a pentesting-adjacent agent (which will read untrusted scan/log/web
output) than the plain multi-category os-std the "Frameworks in scope"
table originally implied, but it does mean every "AgentBench 27%" /
"22/100" / "24/100" reference elsewhere in this doc should be read as
"under this injection-augmented task suite," not "general OS-interaction."

| Test | Model | Runtime | Result | Notes |
|---|---|---|---|---|
| BFCL `simple` (20-case pilot) | Qwen3.6-35B `UD-Q4_K_M` | Ollama/ROCm | **20/20 (100%)** | 11.7s mean/case |
| BFCL `simple` (20-case pilot) | KAT-Coder-V2.5-Dev `Q4_K_M` | Ollama/ROCm | **19/20 (95%)** | 1 failure: answered in prose instead of calling the tool |
| BFCL `simple` (20-case pilot) | either model | llama.cpp/Vulkan | not run | no Vulkan BFCL data exists yet |
| AgentBench os-std (`prompt_injection` only, n=10, seed=9070) | Qwen3.6-35B | Ollama/ROCm | **3/10 (30%)**, repeat run **1/10 (10%)** | same config both times — real run-to-run variance at this n, not a config change |
| AgentBench os-std (`prompt_injection` only, n=10, seed=9070) | Qwen3.6-35B | llama.cpp/Vulkan | **2/10 (20%)** | single run |
| AgentBench os-std (`prompt_injection` only, n=10, seed=9070) | KAT-Coder-V2.5-Dev | Ollama/ROCm | **4/10 (40%)** | 1 earlier attempt crashed (`AGENT_FAILED`, service still warming up) |
| AgentBench os-std (`prompt_injection` only, n=10, seed=9070) | KAT-Coder-V2.5-Dev | llama.cpp/Vulkan | **3/10 (30%)** | 4 earlier attempts crashed the same way before this one completed |

**Reading this honestly**: n=10 is too small to call a runtime winner —
ROCm and Vulkan land within a task or two of each other for both models,
and Qwen3.6-35B's own ROCm repeat (30%→10%) swung further than the
ROCm/Vulkan gap did. KAT-Coder edges Qwen3.6-35B on both runtimes here,
loosely consistent with its narrower BFCL gap (95% vs 100%). The
repeated crash-then-succeed pattern on both Vulkan attempts (especially
KAT-Coder's 4 failed launches) suggests the Vulkan backend or the
loopback service needs a longer warm-up/retry window before its results
should be trusted at face value — a service-readiness artifact, not
necessarily a capability signal.

**Plan to flesh this out** (not started): the framework-side project
converged on Ollama-only specifically because mixing runtimes made
comparisons untrustworthy (see "Runtime policy" above) — the same logic
applies here once this pilot moves past exploratory status. Before
treating RX 9070 XT numbers as comparable to `framework`'s Qwen3.6-35B/
Coder results: (1) re-run AgentBench os-std here against the full
7-category task set (uncomment categories 1/2/3/5/6/7 in
`AgentBench-rx9070xt/configs/tasks/os.yaml`) on the standardized
`limit=100/seed=42` sample, matching the main harness's methodology
exactly; (2) run a real BFCL pass on Vulkan to fill that gap; (3) pick
one runtime for this card the same deliberate way `framework` picked
Ollama, rather than carrying both forward; (4) once numbers are
genuinely comparable, decide whether a 16GB RX 9070 XT is a viable
*cheaper* "slot 2" host alongside or instead of `framework`'s own GPU —
that's the real question motivating this pilot.

## Context

Follow-on to `docs/framework/model-quality-and-vuln-bench-2026-07-17.md`.
That earlier pass and this session's own BFCL (Berkeley Function-Calling
Leaderboard) bakeoff answered the tool-calling question for `framework`'s
"slot 2" (swappable, small, fast tool-use model) candidates:

| Model | Path | 400-case `simple` time | Accuracy |
|---|---|---|---|
| **Qwen3-Coder-30B** | llama.cpp router | 5m56s | **96.25%** |
| Coder (co-resident, ctx163k) | Ollama | 9m59s | 94.25% |
| Laguna XS 2.1 | Ollama | 11m32s | 90.0% |
| Qwen3.6-35B | llama.cpp router | 17m30s | 94.0% |
| gpt-oss-120b | llama.cpp router | 27m24s | 89.75% |
| Gemma4-26B | Ollama | 29m57s | 94.0% |
| Laguna S 2.1 (131k ctx) | Ollama | 48m48s | 92.75% |
| Laguna S 2.1 | Ollama | 51m23s | 92.75% |
| Laguna S 2.1 | llama.cpp | 1h23m31s | 75.5% |
| DavidAU Fable-Fusion | Ollama | killed at 43% (~1h39m elapsed, ~34s/it and still climbing) | not scored — killed, clearly not competitive on latency regardless of eventual accuracy |

**Decision (2026-08-05): Qwen3-Coder-30B wins slot 2.** Highest accuracy
*and* fastest by a wide margin — no real trade-off to weigh. DavidAU run
killed; its 34GB Ollama load was also unloaded. No PentAGI config has been
changed as a result — that's a separate, deliberate step, not yet taken.

**Runtime is per-model, not uniform.** The "Path" column above is mixed
deliberately, not incidentally: **Laguna S 2.1** (the large variant)
produced significantly better results on Ollama than on llama.cpp, per
the operator directly (2026-08-05) — this was never written into any
lessons-learned/checkpoint doc before now; searched
`runtime-matrix-checkpoint-2026-07-16.md`, `project-brief.md`, and all
four `docs/pentagi-stack/artifacts/harness-runs/*laguna*.md` files and
found no record of it. So Ollama is Laguna S 2.1's correct runtime going
forward, including this framework expansion's later phase (Laguna S
2.1's Tier 1 + SWE-rebench battery). Laguna XS 2.1's runtime comparison
is *not* separately confirmed either way — it only has an Ollama entry
in the table above with no llama.cpp counterpart tested, so treat its
runtime choice as inherited/untested rather than proven the same way.
Qwen3-Coder-30B, Qwen3.6-35B, and gpt-oss-120b ran on the llama.cpp
router in both BFCL and this phase — no switch for those. Don't default
every model in this project to llama.cpp just because it's `framework`'s
primary intended runtime per `project-brief.md` — match each model to
whichever runtime it actually scored well on.

This document covers the next phase: broadening evaluation past BFCL's
single-turn tool-calling focus into coding, agentic multi-step, reasoning,
and security-specific benchmarks, using established third-party frameworks
rather than more hand-rolled scripts.

## Frameworks in scope

| Framework | What it measures | Host |
|---|---|---|
| lm-evaluation-harness (EleutherAI) | General harness; covers GPQA + IFEval as built-in tasks | `framework` |
| GPQA | Graduate-level reasoning (via lm-eval-harness) | `framework` |
| IFEval | Instruction-following adherence (via lm-eval-harness) | `framework` |
| τ²-bench (successor to tau-bench) | Multi-turn tool-agent-user interaction | `framework` |
| ~~ARC-AGI (`arc-agi-benchmarking`)~~ | **Dropped from scope 2026-08-06** (operator call) — even frontier models score near-zero on ARC-AGI-2, not a useful differentiator between local models either; also the source of the real ctx163k/ctx147k degeneration bugs documented below, which is now moot since it's out of scope | ~~`framework`~~ |
| ~~SWE-rebench (`SWE-bench-fork`)~~ | **Dropped from scope 2026-08-06** (operator call: "drop SWE-rebench for now") — model-inference wiring was never actually built; deferred, not abandoned, but off the active list | ~~`garuda`~~ |
| AgentBench | In practice, only `os-std` has been run, and its active task config is narrower than the framework name suggests — see the "os-std scope correction" note below | `garuda` |
| CyberSecEval (Meta PurpleLlama) | Security-specific: insecure-code gen, exploit capability | `garuda` |
| ~~GAIA~~ | **Dropped from scope 2026-08-06** (operator call) — never produced usable data for any model attempted (crashed both times on a venv bug); dropped rather than debugged further | ~~`garuda`~~ |

## Host-split rationale

`framework.gibbsgreatly.xyz` (bare-metal AMD unified-memory APU, 128GB RAM)
is the only place inference happens — that's fixed regardless of where a
harness's own client/orchestration code runs. The 9 frameworks split
sharply by orchestration weight:

- **Lightweight** (pure HTTP client + local scoring — GPQA, IFEval,
  τ²-bench, ARC-AGI, lm-eval-harness itself): safe to run directly on
  `framework`, same pattern as today's BFCL work.
- **Heavy** (spin up real Docker/Podman sandboxes *per task* to execute
  things — SWE-rebench, AgentBench, CyberSecEval's execution tests, GAIA's
  real tool use): genuine resource-contention risk if colocated with a
  loaded model server. This isn't theoretical — this exact host produced a
  real OOM kill and two SSH-unresponsiveness episodes during earlier
  co-resident model testing this session (see `docs/framework/` prior
  session notes). A Docker-heavy grading workload competing with a loaded
  model for RAM/CPU is the same failure mode, and a mid-run OOM would kill
  the model server, not just the benchmark.

Operator decision (2026-08-05, via `AskUserQuestion`): heavy frameworks run
on **`garuda`** (the operator's actual workstation — this is also where
Claude Code itself runs, direct Bash access, no SSH needed), not on a new
`pve` LXC. Rationale given: `pve` is a controlled production node under
this repo's approval workflow, and this is personal model R&D rather than
homelab infrastructure — spinning up a new Terraform-tracked LXC for a
throwaway benchmarking box would mix concerns for no infra benefit.
`pve-test-vm` was considered and rejected for the heavy tier specifically
because it's only a 16GB-RAM bare-metal laptop, too tight for concurrent
Docker-based grading.

`garuda` specs relevant to this: Ryzen 9800X3D (16 threads), 60GB RAM
(44GB free at time of writing), Docker 29.7.1 + Podman both pre-installed,
Docker's storage root (`/var/lib/docker`) lives on its own 932GB disk with
707GB free — no disk constraint for SWE-rebench's ~60 environment images
or any of the others. 0.7ms RTT to `framework`.

## Setup status per framework

### lm-evaluation-harness — installed, IFEval working, GPQA blocked on gating

Host: `framework`, `~/eval-harnesses/venv` (plain venv, system Python
3.14.4 — no version constraint issue here).

```bash
pip install 'lm-eval[api]' 'lm-eval[ifeval]'
```

Real gotchas hit and fixed:
- **`ModuleNotFoundError: tenacity`** on first run — needs the `[api]`
  extra for any API-backed model type (`local-completions` /
  `local-chat-completions`).
- **`ModuleNotFoundError: langdetect`** then **`nltk`** — IFEval needs the
  `[ifeval]` extra.
- **nltk's new (2026) CWD-import-hijacking security hook false-positives**
  when the venv lives *inside* the working directory you invoke from (the
  common `python3 -m venv venv` inside a project dir, then `cd` there and
  run pattern — exactly how `~/eval-harnesses` and `bfcl-eval` are both
  laid out). `nltk/inisec.py`'s `find_spec` treats "resolves to a path
  under `Path.cwd()`" as suspicious regardless of whether the resolved
  package is actually a legitimate venv install; since the venv is nested
  under the project directory, every package `nltk` imports (`regex`,
  transitively) trips it. **Fix: invoke from a directory that is not an
  ancestor of the venv path** (e.g. `cd /tmp` first, or `cd $HOME` won't
  work if the venv is inside `$HOME` too — has to be a genuinely unrelated
  directory). `-P` / `PYTHONSAFEPATH=1` do **not** fix this specific case
  — those only cover the interpreter's own `sys.path` cwd entry, not this
  finder's independent `Path.cwd()` check.
- **CLI is subcommand-based now** (`lm-eval ls tasks`, `lm-eval run ...`),
  not the flat `--tasks list` flag from older docs/blog posts.

Smoke tests (both `--limit 3`, plumbing-only, not real scores):
- IFEval — passed with `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` and again with
  `Llama-3.2-3B-Instruct-Q4_K_M`.
- GPQA (`gpqa_diamond_cot_zeroshot` — the `generate_until` CoT variant,
  since chat-completion APIs can't expose logprobs for the raw
  multiple-choice scorer) — was **blocked** on gating; `Idavidrein/gpqa`
  is gated on HF, and the account had not actually clicked through the
  license terms yet at the time. **Correction to an earlier claim in this
  session**: a successful `hf download ... --include "README.md"` is
  *not* proof of gated-dataset access — READMEs are often visible
  pre-approval. Real access requires successfully pulling an actual data
  file, which failed at the time with
  `Access denied. This repository requires approval.`
  **Resolved 2026-08-05**: operator accepted the license terms; verified
  by pulling the real `gpqa_diamond.csv` (1.37MB, actual question data).
  The `lm-eval-harness` smoke test itself hasn't been re-run yet — that's
  the next action, not done as of this writing.

### τ²-bench (`sierra-research/tau2-bench`) — installed and smoke-tested successfully

Host: `framework`, `~/eval-harnesses/tau2-bench`, `uv` venv pinned to
Python 3.12 (repo requires `>=3.12,<3.14`; framework's system Python is
3.14.4, outside range — `uv venv --python 3.12` downloads and manages the
pinned interpreter automatically, isolated from system Python). `uv`
itself wasn't installed on `framework` before this session — added via
the standard `astral.sh/uv/install.sh` script (now `~/.local/bin/uv`,
v0.12.1).

**Real finding: the original `sierra-research/tau-bench` repo explicitly
deprecates itself** — its own README states "the tasks in this repo are
not updated... please use τ²-bench" (now actually renamed τ³-bench
upstream, repo still at `sierra-research/tau2-bench`). Building on it
would have meant testing against known-stale task data; switched before
sinking further setup time in.

LiteLLM (τ²-bench's LLM backend) supports arbitrary OpenAI-compatible
endpoints via `--agent-llm-args '{"api_base": "...", "api_key": "..."}'`
with an `openai/<model>` prefix — no adapter code needed.

Smoke-test path hit two real config incompatibilities in the `mock`
domain before landing on a working combination:
1. `--user dummy_user` requires `--agent llm_agent_solo` ("Dummy user can
   only be used with solo agent").
2. `llm_agent_solo` + `dummy_user` together then failed with
   `DummyUser.__init__() got an unexpected keyword argument 'tools'` — an
   apparent internal incompatibility in the `mock` domain's own
   solo-agent/dummy-user wiring, not something on our end.

Switched to the **`airline` domain** with `user_simulator` (both agent and
user-simulator roles pointed at the same local `Llama-3.2-3B-Instruct`
model, avoiding any paid-API dependency for the user-simulator side) —
this is the realistic τ²-bench setup. Command:

```bash
uv run tau2 run --domain airline --user user_simulator --agent llm_agent \
  --agent-llm 'openai/Llama-3.2-3B-Instruct-Q4_K_M' \
  --agent-llm-args '{"api_base": "http://localhost:8080/v1", "api_key": "EMPTY"}' \
  --user-llm 'openai/Llama-3.2-3B-Instruct-Q4_K_M' \
  --user-llm-args '{"api_base": "http://localhost:8080/v1", "api_key": "EMPTY"}' \
  --num-tasks 1 --num-trials 1 --max-steps 6
```

**Real finding: runaway generation, not a plumbing hang.** The first
attempt sat with no new log output for 35+ minutes. `docker logs
llamacpp-router` showed it wasn't stuck at all — the router was actively
decoding the entire time, `n_decoded` climbing past 3300+ tokens for a
single user-simulator turn and still rising (~15 t/s, steady). Root
cause: neither `--agent-llm-args` nor `--user-llm-args` capped
`max_tokens`, and the 3B model doesn't reliably emit τ²-bench's expected
control tokens (`###STOP###` / `###TRANSFER###` / `###OUT-OF-SCOPE###`) to
end its turn on its own — so generation just ran on unbounded. This is a
genuine small-model behavioral limitation in the user-simulator role, not
a harness or connectivity bug.

Killed the run, retried with an explicit cap (`"max_tokens": 200` added to
both `--agent-llm-args` and `--user-llm-args`). That retry was itself
stopped partway through on 2026-08-05 (operator asked to stop all
in-flight work cleanly before a result came back) — confirmed clean
shutdown at the time (no stray processes, router idle, Ollama empty).

**Re-ran after resuming — passed.** Full command:

```bash
uv run tau2 run --domain airline --user user_simulator --agent llm_agent \
  --agent-llm 'openai/Llama-3.2-3B-Instruct-Q4_K_M' \
  --agent-llm-args '{"api_base": "http://localhost:8080/v1", "api_key": "EMPTY", "max_tokens": 200}' \
  --user-llm 'openai/Llama-3.2-3B-Instruct-Q4_K_M' \
  --user-llm-args '{"api_base": "http://localhost:8080/v1", "api_key": "EMPTY", "max_tokens": 200}' \
  --num-tasks 1 --num-trials 1 --max-steps 4
```

Completed in 11.5s, `TerminationReason.MAX_STEPS` (expected — 4 steps
isn't enough to actually resolve a real airline task, this was a plumbing
check, not a capability run), zero errors. The `max_tokens` cap fully
resolved the earlier runaway-generation issue. One harmless cosmetic
warning: LiteLLM doesn't have `Llama-3.2-3B-Instruct-Q4_K_M` in its
pricing table, so cost always reports as `$0.0000` — fine, since these
are local/free calls anyway.

### ARC-AGI (`arc-agi-benchmarking`) — installed and smoke-tested successfully

Host: `framework`, `~/eval-harnesses/arc-agi-benchmarking`, `uv sync`
(requires Python `>=3.10`, no version conflict).

**Correction to an earlier caveat in this session**: I'd flagged this one
as possibly needing a custom adapter since its documented provider list
(Anthropic/OpenAI/Google/xAI/DeepSeek/Groq/OpenRouter/Fireworks) didn't
explicitly mention generic custom endpoints. It does, cleanly —
`models.yml` has a documented, ready-made pattern:

```yaml
  - name: "framework-llama3-3b"
    model_name: "Llama-3.2-3B-Instruct-Q4_K_M"
    provider: "openai"
    api_type: "chat_completions"
    base_url: "http://localhost:8080/v1"
    api_key_env: "FRAMEWORK_API_KEY"
    temperature: 0
    max_tokens: 4096
    pricing: {date: "2026-08-04", input: 0.0, output: 0.0}
```

Single-task smoke test against the bundled sample data:

```bash
export FRAMEWORK_API_KEY=EMPTY
uv run cli/run_all.py --data_dir data/sample/tasks --config framework-llama3-3b \
  --save_submission_dir /tmp/arc-agi-smoketest --num_attempts 1 --retry_attempts 1 \
  --max-tasks-per-run 1
```

**Passed** — full preflight validation, ran task `00576224` end-to-end,
216.78s total (slow, but that's the 3B model working an ARC grid-reasoning
prompt, not a plumbing issue — preflight, rate limiter, and circuit
breaker all behaved correctly).

### SWE-rebench (`SWE-bench-fork`) — Docker grading harness confirmed; model-generation wiring not yet done

Host: `garuda`, `~/eval-harnesses/SWE-bench-fork`, `uv` venv pinned Python
3.12 (`requires-python = ">=3.10"`, used 3.12 for consistency).

Real gotcha: first `uv venv --python 3.12 && uv pip install -e .` (single
chained command) reported `requests` as installed in its output, but the
venv's Python couldn't actually import it afterward
(`ModuleNotFoundError: No module named 'requests'`) — a real
install/venv-targeting mismatch, not a flaky report. Fixed by re-running
`uv pip install --python .venv/bin/python -e .` explicitly against the
venv's own interpreter path; import succeeded after that.

**Important architecture note**: this repo's `run_api.py` (the built-in
model-inference script) is the *older* SWE-bench paradigm — single-shot
"oracle"/BM25-retrieval patch generation via a script hardcoded toward
OpenAI/Azure/Anthropic, not built for arbitrary custom `base_url`
endpoints (`openai.api_base` is set once, hardcoded to an Azure URL, in
one specific code path). It is **not** a full agentic coding scaffold
(no multi-turn file editing/tool use) — wiring a real small-model patch
generation smoke test through it, or swapping in a proper agent scaffold
(e.g. `mini-swe-agent`), is unstarted follow-up work, not yet done.

What **was** smoke-tested — the actually heavy, workstation-specific part
of this framework, the Docker-based grading pipeline — using the repo's
own built-in gold-patch validation (no model involved, validates the
harness/grading side only):

```bash
.venv/bin/python -m swebench.harness.run_evaluation \
  --predictions_path gold --max_workers 1 \
  --instance_ids sympy__sympy-20590 --run_id validate-gold
```

**Passed** — built the Docker image, ran the instance, `Instances
resolved: 1`, 47.54s.

### AgentBench — full task-server + assigner pipeline working end-to-end

Host: `garuda`, `~/eval-harnesses/AgentBench`, `uv` venv pinned Python 3.9
(repo's own README explicitly recommends 3.9 for its pinned
`numpy~=1.23.x`/`transformers~=4.34.x` deps; confirmed still actively
maintained — last commit 2026-02-09, not abandoned, just conservatively
pinned).

Created a custom agent config (`configs/agents/framework-llama3-3b.yaml`)
using AgentBench's generic `HTTPAgent` module pointed at `framework`'s
router — this pattern needs no adapter code, same as ARC-AGI:

```yaml
framework-llama3-3b:
  module: src.client.agents.HTTPAgent
  parameters:
    name: framework-llama3-3b
    url: http://framework.gibbsgreatly.xyz:8080/v1/chat/completions
    headers: {Content-Type: application/json, Authorization: "Bearer EMPTY"}
    body: {model: Llama-3.2-3B-Instruct-Q4_K_M, temperature: 0, max_tokens: 512}
    prompter: {name: role_content_dict, args: {agent_role: assistant}}
    return_format: "{response[choices][0][message][content]}"
```

Real gotcha on the first invocation: `agent_test` is an **interactive
REPL** (`input(">>> ")` in a `while True` loop) — piping it through
`| tail -40` in the background left it blocked waiting on stdin forever,
which looked like a hang but wasn't one (confirmed via `ps`: alive,
~0% CPU, no error). Not a bug — just the wrong invocation for a
non-interactive smoke test. Fixed by piping a single line in instead of
backgrounding it open-ended:

```bash
echo "Say hello in one word." | .venv/bin/python -m src.client.agent_test \
  --config configs/agents/framework-llama3-3b.yaml --agent framework-llama3-3b
```

**Passed** — got back a clean `"Hello."` from `Llama-3.2-3B` through the
custom `HTTPAgent` config, then exited on EOF as expected.

**Full pipeline (2026-08-05): a genuine, significant upstream gap, resolved by switching to an older fork.**
Building the real task-server + assigner pipeline (the actual
Docker-sandboxed os/db/web tasks) surfaced something much bigger than
version drift — **THUDM/AgentBench's `main` branch is missing its entire
server-orchestration layer.** `src/start_task.py`,
`src/server/task_controller.py`, `src/server/task_worker.py`, and
`src/server/task.py` (defining the base `Session`/`Task` classes) don't
exist anywhere in the repo, despite being referenced throughout the
README, `docs/Entrance_en.md`, and even the "Lite suite" PR
(`d1e4a10`, merge of #213) that added `configs/start_task_lite.yaml` —
that PR's own new config files reference a `src.start_task` module that
was already absent *before* the PR landed. Not a bug I introduced or a
config issue — genuinely missing core infrastructure in the published
repo.

Found a fix rather than reconstructing this from scratch: **`Eugleo/agent-bench`**, a
legitimate fork directly off `THUDM/AgentBench` (0 stars, personal fork,
last pushed Feb 2024 — predates whatever later removed these files
upstream) still has all four missing files, confirmed via GitHub's tree
API before trusting it. Recovering just those 4 files onto our existing
clone worked partway (`start_task.py` and `task_controller.py` ran) but
then two more real gaps appeared:
- `uvicorn`/`fastapi` were in `requirements.txt` but genuinely not
  installed (reinstalling fixed it) — then a second issue: the fork's
  `start_task.py` hardcodes bare `python` for subprocess spawning
  (not `sys.executable`), so it needs the venv actually **activated**
  (`source .venv/bin/activate`) rather than just invoked via its binary
  path — otherwise subprocess workers resolve `python` from the wrong
  PATH entry and miss the venv's packages entirely.
- The real task implementations (`dbbench`, `os_interaction`, and every
  other task type in this upstream checkout) import
  `from agentrl.worker.environment import create_controller` — an
  undocumented dependency not in `requirements.txt` at all. The PyPI
  package literally named `agentrl` turned out to be a **completely
  unrelated reinforcement-learning library** (submodules `agents`,
  `common/buffers`, `common/policy_networks` — nothing resembling
  `worker.environment`) — a name collision, not the real dependency,
  which appears to be an internal/unpublished THUDM package.

Given upstream's actual task implementations are unusable without an
unpublished dependency, **switched entirely to the `Eugleo/agent-bench`
fork** rather than continuing to patch a partially-broken tree — its
`os_interaction/task.py` is self-contained (uses the `docker` package
directly, no `agentrl`), and being a complete, internally-consistent
snapshot is much lower-risk than cherry-picking further. Re-applied the
Lite-preset-equivalent config (the fork predates that PR, so recreated
`configs/assignments/framework.yaml` + a `qwen3-coder-30b` HTTPAgent
config against its schema) and rebuilt the venv/Docker images.

Two more small real bugs before it ran clean:
- The controller hardcodes port 5000 internally (not configurable via
  YAML) — same conflict as SearXNG's earlier port story, except this
  time with `lxconsole`, a pre-existing unrelated container on `garuda`.
  Confirmed via `docker ps` before doing anything, then patched every
  hardcoded `5000` reference (`start_task.py`, `task_controller.py`,
  `task_worker.py`, `src/client/task.py`'s default, and my own
  definition file) to `5098` instead of touching the other service.
- My own definition file initially had a stale `4000` (copied from an
  unrelated value seen earlier) instead of the real default — my `sed`
  replace targeting `5000` silently found nothing to change there. Fixed
  by hand once the mismatch was traced.

**Result: fully working.** Controller up, `os-std` worker registered
with a successful heartbeat, assigner correctly dispatched real episodes
to `qwen3-coder-30b`, and **sample #1 of the `os-std` task set completed
cleanly in 93.35s** (sample #2 was underway when stopped). Confirmed
clean shutdown after — no stray processes, sandbox container removed,
`docker ps` showing only `garuda`'s own pre-existing unrelated services
(`comfyui`, `lxconsole`).

**Real scale note**: `os-std` alone has 800 episodes; at ~90-100s each
with `--parallel 1` concurrency, a full run is ~20+ hours for a single
model — nowhere near smoke-test scale. Patched `get_indices()` in
`os_interaction/task.py` with an `AGENTBENCH_SAMPLE_LIMIT` env var
(same pattern as GAIA's `GAIA_SMOKETEST_LIMIT`) so future real runs can
be deliberately subsampled rather than accidentally kicking off a
day-long run.

### CyberSecEval (Meta PurpleLlama) — installed and smoke-tested successfully

Host: `garuda`, `~/eval-harnesses/PurpleLlama`, `uv` venv pinned Python
3.12 (no explicit `requires-python` found; 3.12 chosen for consistency
with the other `garuda` harnesses, installed clean).

Confirmed directly in the README (not assumed): custom OpenAI-compatible
endpoints are natively supported via a 4-part `--llm-under-test` spec —
`<PROVIDER>::<MODEL>::<API_KEY>::<BASE_URL>` — no adapter code needed,
same pattern as ARC-AGI and AgentBench.

**Real finding: `--help`'s benchmark list is stale.** It advertises
"Currently supported benchmarks are: autocomplete, instruct, mitre" —
`mitre-frr` (and others: `autopatch`, `interpreter`,
`prompt-injection`, etc.) aren't mentioned there but are genuinely
registered in code (`mitre_frr_benchmark.py`'s `MitreFRRBenchmark.
return_kind()` returns `["mitre-frr"]`). Don't trust the `--help` text
as the authoritative list — checked the `benchmark/*.py` registrations
directly instead.

Chose **`mitre-frr`** (False Refusal Rate) for the smoke test
specifically because it needs no judge/expansion LLM — refusal detection
is local keyword-matching, not a second model call, so there's no extra
API dependency to wire up just to prove connectivity:

```bash
export DATASETS=$PWD/CybersecurityBenchmarks/datasets
.venv/bin/python -m CybersecurityBenchmarks.benchmark.run \
  --benchmark=mitre-frr \
  --prompt-path="$DATASETS/mitre_frr/mitre_frr.json" \
  --response-path="/tmp/mitre_frr_responses.json" \
  --stat-path="/tmp/mitre_frr_stat.json" \
  --llm-under-test="OPENAI::Llama-3.2-3B-Instruct-Q4_K_M::EMPTY::http://framework.gibbsgreatly.xyz:8080/v1" \
  --num-test-cases=2
```

**Passed** — 2 prompts processed (~10s/prompt), judged locally
(`accept`/`refuse`), stats aggregated correctly
(`{"accept_count": 2, "refusal_count": 0, "refusal_rate": 0.0}`). One
harmless warning: the model isn't in OPENAI provider's hardcoded
`valid_models` convenience list (`gpt-3.5-turbo`, `gpt-4`, etc.) — logged
as a `WARNING`, not enforced, run proceeded normally regardless.

Not yet tested: `mitre` proper (needs judge + expansion LLM — could
point both at a local model too, not yet tried), `autopatch` (needs
Podman, compute-intensive, per README), and secure-code-generation
(`instruct`/`autocomplete` — README notes these are "temporarily removed
from the default list" upstream pending an import-path fix).

### GAIA — installed, patched, smoke test in progress

Host: `garuda`, `~/eval-harnesses/smolagents` (`uv` venv pinned Python
3.12; `requires-python = ">=3.10"`), reference agent implementation at
`examples/open_deep_research/run_gaia.py` (GAIA has no purpose-built
harness of its own). Needed the `smolagents[litellm]` extra installed
separately (base install doesn't pull `litellm`, and `LiteLLMModel`
fails at construction time without it).

**SearXNG wired in place of the paid default**, confirmed reachable
first (`curl` to `http://192.168.50.11:8082/search?q=test&format=json` —
same instance PentAGI itself uses, see
`terraform/lxc/ansible/playbooks/deploy-pentagi-stack.yml`; reachable
directly from `garuda`, no MikroTik rule needed unlike PentAGI's
Docker-network case). Wrote a small `SearxngSearchTool(Tool)` in
`examples/open_deep_research/searxng_search_tool.py` matching
`GoogleSearchTool`'s interface, and swapped it in for
`GoogleSearchTool(provider="serper")` in `create_agent_team`.

**Real bugs found and fixed in the reference script** (this is the
oldest/least-maintained-looking of the 9 frameworks, consistent with
being an "example," not a first-class package):

1. **`datasets>=4.0` dropped script-based dataset loading entirely**
   (`RuntimeError: Dataset scripts are no longer supported, but found
   GAIA.py`) — a real, deliberate security hardening upstream (loader
   scripts are arbitrary code execution), not a bug in `datasets` itself.
   `load_gaia_dataset` still called
   `datasets.load_dataset("data/gaia/GAIA.py", name="2023_all", ...)`.
   Fixed by loading the already-downloaded `metadata.jsonl` directly via
   `datasets.load_dataset("json", data_files=..., split="train")` — same
   columns, and arguably a better security posture regardless (no code
   execution from a downloaded script at all).
2. **Path-construction bug this exposed**: `preprocess_file_paths` built
   file paths as `data/gaia/{set_to_run}/...`, missing the `2023/`
   directory component that the (now-bypassed) loader script apparently
   handled internally. Fixed to `data/gaia/2023/{set_to_run}/...`,
   confirmed against the actual downloaded directory layout.
3. **`get_single_file_description` routes non-image documents through
   the same image-captioning path whenever a sibling pre-rendered `.png`
   exists** (`.pdf`/`.xlsx`/`.docx`/etc. → checks for `<uuid>.png` next
   to the real file, many GAIA validation tasks ship one). That path
   (`visual_qa.py`'s `visualizer`) makes a **hardcoded raw HTTP call to
   `https://api.openai.com`**, completely bypassing the `LiteLLMModel`
   abstraction (and thus our `api_base`/`api_key` override) — real
   architectural gap in the reference script, not something to patch
   around for a plumbing smoke test, especially since our smoke-test
   model (`Llama-3.2-3B-Instruct`, text-only) couldn't do image
   captioning even if the endpoint were fixed. Worked around by targeting
   a specific task via a new `GAIA_SMOKETEST_TASK_ID` env-var patch
   (added alongside a `GAIA_SMOKETEST_LIMIT` var — the script has no
   built-in single-task/limit flag) whose attached file is a plain
   `.csv` — falls through `get_single_file_description`'s safe `else`
   branch (`" - Attached file: ..."`, no tool call at all), avoiding both
   the vision-API gap and any audio-transcription path.

Command (once past setup):
```bash
export HF_TOKEN=$(cat ~/.cache/huggingface/token)
export LITELLM_API_BASE="http://framework.gibbsgreatly.xyz:8080/v1"
export LITELLM_API_KEY="EMPTY"
export SEARXNG_URL="http://192.168.50.11:8082"
export GAIA_SMOKETEST_TASK_ID="8d46b8d6-b38a-47ff-ac74-cda14cf2d19b"
.venv/bin/python run_gaia.py --concurrency 1 \
  --model-id "openai/Llama-3.2-3B-Instruct-Q4_K_M" \
  --run-name smoketest6 --set-to-run validation
```

**Result: fully working end-to-end after fixing 5 real bugs across two
passes.**

First pass (`Llama-3.2-3B-Instruct`): the run genuinely executed —
dataset loaded, task prompt built correctly, manager `CodeAgent` invoked
the model for real across all 12 of its `max_steps` (78-113s/step,
~11K-97K cumulative input tokens) — but the 3B model consistently failed
to produce `CodeAgent`'s required Python-code-block format, emitting
degenerate repeated-`?` output that maxed out `max_tokens` each time. A
genuine model-capability finding (`CodeAgent`'s format is a materially
higher bar than the plain tool-calling JSON every other framework in
this doc uses), not a harness defect — the retry-on-parse-error logic
worked correctly throughout.

After hitting `max_steps`, the script's own post-loop handling then
surfaced a chain of real bugs, all version-drift between this pinned
example and the installed `smolagents==1.27.0.dev0`, fixed one at a time
as each was uncovered by the previous fix:
1. `"AgentParsingError" in step` (`step` being a `ChatMessage` instance,
   not a dict/string) → `TypeError: argument of type 'ChatMessage' is
   not iterable`. Fixed: check `step.content` instead of `step` itself.
2. `total_token_counts` was built as a plain
   `{"input": 0, "output": 0}` dict but every consumer does
   `.input_tokens +=` / `.output_tokens +=` on it, expecting a real
   `TokenUsage` instance → `AttributeError`. Fixed: construct
   `TokenUsage(input_tokens=0, output_tokens=0)` properly.
3. `agent.monitor.get_total_token_counts()` returns a `TokenUsage`
   instance in this version, but two call sites did `["input"]`/
   `["output"]` subscript access → `TypeError: 'TokenUsage' object is
   not subscriptable`. Fixed: `.input_tokens`/`.output_tokens` attribute
   access at both sites.
4. Once (1)-(3) were fixed, the JSONL write itself failed:
   `json.dumps()` can't serialize a raw `TokenUsage` dataclass or the
   raw `ChatMessage` objects in `intermediate_steps`. Fixed: `.dict()`
   on the token-usage object, and `[s.dict() for s in intermediate_steps]`
   for the message list.

**Re-ran with `Qwen3-Coder-30B` instead of the 3B model** (since the
original failure mode was the 3B model's `CodeAgent`-format struggles,
not a harness issue — worth re-testing with a model already proven
strong at structured output). Result: **clean pass**, 198.6s, real
answer produced (`"0.00067"`), no crashes, valid serialized JSONL
output. The manager agent chose to solve this particular CSV-based task
by parsing the file directly in Python rather than delegating to the
`search_agent` sub-agent — a model reasoning choice, not a plumbing gap;
the SearXNG tool is proven both standalone (direct invocation, real
Wikipedia/Britannica results) and correctly wired into the agent's
toolset (imported, instantiated, present in `WEB_TOOLS`).

**Bottom line**: GAIA is now genuinely on par with the other 8
frameworks — installed, all discovered reference-script bugs fixed, and
demonstrated with a real clean end-to-end completion.

One known, deliberately-unfixed gap remains: `visual_qa.py`'s
`visualizer` still hardcodes a raw HTTP call to `https://api.openai.com`
for image captioning, bypassing the `LiteLLMModel` abstraction entirely.
Not needed for this smoke test (worked around via task selection — a
`.csv`-only task) and wouldn't be meaningfully testable without a
genuinely vision-capable local model regardless, which none of today's
candidates are. Would need fixing before running GAIA at scale against
tasks with real image content.

## Cross-cutting infra notes

- HF token (`GibbsGreatly` account, OAuth-derived) copied from `garuda`'s
  `~/.cache/huggingface/token` to `framework`'s, so both hosts share
  dataset access under the same account. Whether the account has *actually
  agreed to* GPQA's and GAIA's gating terms is still unconfirmed — see
  "Open items."
- `uv` installed fresh on `framework` this session (wasn't present
  before) — `~/.local/bin/uv`, v0.12.1. Used for every framework that
  pins a Python version outside `framework`'s system 3.14.4 (τ²-bench,
  ARC-AGI) or that benefits from isolated pinned deps (SWE-rebench,
  AgentBench on `garuda`).
- All `framework`-hosted harnesses so far point at the llama.cpp router's
  OpenAI-compatible endpoint (`localhost:8080/v1`), same as BFCL. Two
  models used for smoke tests: `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` (the
  confirmed slot-2 winner) and `Llama-3.2-3B-Instruct-Q4_K_M` (smallest
  available, used for fast pure-plumbing checks per operator steer:
  "quick smoke test with a small model on each... not thorough tests on
  all models yet").

## Open items / blockers

1. **GPQA and GAIA gated-dataset access — resolved 2026-08-05.** Operator
   accepted both license terms on HF; verified for real (pulled actual
   data files, not just READMEs, after the earlier false-positive mistake
   in this doc). GPQA's `lm-eval-harness` smoke test re-run afterward —
   **passed**.
2. **GAIA — resolved 2026-08-05, now fully clean end-to-end.** 5 real
   bugs found and fixed across two passes (dataset-script removal,
   file-path construction, and a chain of 3 `ChatMessage`/`TokenUsage`
   version-drift bugs surfaced one at a time in the reference script's
   post-loop handling). Re-ran with `Qwen3-Coder-30B` instead of the
   original 3B plumbing model (whose failure to produce valid
   `CodeAgent`-format output was the trigger that exposed the bug chain
   in the first place) — clean pass, real answer produced, no crashes.
   One deliberately-unfixed gap remains: `visual_qa.py`'s hardcoded
   OpenAI-only vision endpoint, not needed for text/CSV-only tasks and
   not meaningfully testable without a genuinely vision-capable local
   model anyway. See its section above for full detail.
3. SWE-rebench — Docker/grading side proven; model-inference wiring
   (either patching `run_api.py` for a custom `base_url`, or adopting a
   proper agent scaffold like `mini-swe-agent`) is unstarted.
4. No PentAGI configuration has been touched by any of this — that
   remains a deliberate, separate, not-yet-taken step once the fuller
   picture (this framework buildout + BFCL) is in.

## Next steps

1. ~~SWE-rebench model-inference wiring.~~ Dropped from scope 2026-08-06
   (operator call: "drop SWE-rebench for now") — deferred, not abandoned.
2. ~~Optionally: patch GAIA's `visual_qa.py`...~~ Moot — GAIA itself
   dropped from scope 2026-08-06 (see below).
3. Move from plumbing checks to real (small-`n`, then full) runs against
   the actual slot-1/slot-2 candidate models across all 9 frameworks —
   superseded by the narrower active battery below (GAIA/ARC-AGI/
   SWE-rebench all dropped).

## Scope changes, 2026-08-06 (operator calls, all same session)

- **GAIA dropped.** Never produced usable data for any model attempted
  — crashed both times in the overnight run on a venv-activation bug.
  That bug is fixed in `overnight-garuda.sh`'s `run_gaia()`, but rather
  than spend more time on a framework that's produced zero real results
  so far, it's off the active list.
- **Laguna XS 2.1 dropped.** Operator: "it didn't get anywhere near good
  enough results on the tests we did run" — its only real data point is
  BFCL 90.0% (Ollama), the weakest of the models tested there, and not
  worth carrying through the rest of the battery.
- **SWE-rebench dropped for now.** Model-inference wiring was never
  built (see "Open items" above); deferred rather than built out at this
  point.
- **Gemma4-26B confirmed in scope** — comparative battery, same shape as
  the two Qwen models (GPQA/IFEval/τ²-bench/CyberSecEval/AgentBench).
- **Active battery going forward, per model**: BFCL (already have real
  Ollama numbers for every model below), GPQA, IFEval, τ²-bench,
  CyberSecEval, AgentBench os-std (standardized `limit=100`/`seed=42`
  sample for cross-model comparability).

### Qwen3.6-35B re-run + Laguna S 2.1 comparative battery — launched 2026-08-06

Two chained, fully-detached driver scripts (`setsid nohup ...; disown`,
same survival pattern verified the previous night):

- **`~/eval-harnesses/overnight-framework.sh`** (on `framework`) — two
  parts in sequence:
  1. Re-runs Qwen3.6-35B's GPQA/IFEval/τ²-bench against the fixed
     `eval-qwen36-35b-a3b:q4_k_m-ctx32k` tag (`num_predict=8192`) — the
     overnight run's numbers for these were infra-failure artifacts
     (see "Overnight run outcome" above), this produces the first real
     data for them. Touches `QWEN36_RERUN_DONE`.
  2. Stops the two Qwen Ollama models (frees ~43GB; `eval-llama-3.2-3b`
     deliberately stays resident — small, and needed again immediately
     as τ²-bench's user-simulator LLM), loads the new
     `eval-laguna-s2-1:q4_k_m-ctx131k` tag (created 2026-08-06, reuses
     the existing 73GB blob from `laguna-s-2.1:q4_k_m-ctx131k`, adds a
     `num_predict=8192` safety net that tag never had — same fix class
     as the Qwen3.6-35B CyberSecEval/GPQA bug), warms it with a polled
     curl probe before handing it to any harness, then runs
     GPQA/IFEval/τ²-bench for Laguna S 2.1. Touches
     `LAGUNA_FRAMEWORK_DONE` then `FRAMEWORK_SEQUENCE_DONE`.
- **`~/eval-harnesses/overnight-garuda-laguna.sh`** (on `garuda`) —
  polls `framework` over ssh for `LAGUNA_FRAMEWORK_DONE` (up to ~5h,
  30s interval) so AgentBench traffic doesn't hit Laguna S 2.1 before
  it's loaded and warm, then runs its `os-std` battery on the same
  standardized `limit=100`/`seed=42` sample used for the Qwen
  comparison (new configs: `configs/agents/laguna-s2-1.yaml`,
  `configs/assignments/{definition-,}framework-laguna-s21.yaml`).
  Touches `GARUDA_LAGUNA_DONE`.

**Real bug hit mid-run (2026-08-06): transient `nltk` CWE-427 import-hook
false positive crashed the first IFEval rerun attempt.** `nltk`'s
`inisec.py` (a legitimate upstream security hook blocking module
hijacking from CWD) intermittently raised `ImportError: Blocked import
of regex from current working directory` while `lm_eval` dynamically
loaded `ifeval/utils.py`. Confirmed transient, not a real CWD-shadowing
issue: the identical command (`import nltk`, the exact
`lm_eval.tasks.ifeval.instructions_registry` import chain, and the full
`lm_eval run --tasks ifeval` invocation) all succeeded cleanly on manual
retry seconds later. The driver script had no `|| exit` after this
step, so it survived and moved on to τ²-bench — GPQA and τ²-bench were
unaffected. Recovery: `~/eval-harnesses/recover-qwen36-ifeval.sh`,
polling for `FRAMEWORK_SEQUENCE_DONE` (so it doesn't race the main
script's own model-unload/Laguna-load transition) then re-running just
IFEval, output to `ifeval-rerun2`, `QWEN36_IFEVAL_RECOVERY_DONE` marker.

**Superseded 2026-08-06, same session: Laguna S 2.1's battery moved off
`overnight-framework.sh`/`garuda` entirely, onto a new dedicated
eval-harness box.** Before Laguna's Part 2 actually launched, the
operator asked to re-architect: a legacy, disposable LXC at
`192.168.1.27` ("ai-stack", Debian 13, root SSH) exists specifically to
take this off both `framework`'s own driver script and the operator's
own workstation (`garuda`) for long-running batteries going forward.
Rationale, confirmed by the numbers: τ²-bench alone was averaging
~8 min/episode for Qwen3.6-35B, and Laguna S 2.1 is ~3x slower per-call
per the existing BFCL timing data — running its full GPQA/IFEval/
τ²-bench/AgentBench battery the same way could easily have run another
10-20+ hours on top of what was already elapsed, repeating the earlier
budget blowout.

**192.168.1.27 setup**: 2 CPU / 2GB RAM / 100GB disk (ZFS `gaming` pool
— a separate, personal Proxmox host, not tracked in this repo's
Terraform). Had 8 already-running legacy Docker containers (n8n,
searxng, postgres, litellm, redis, flowise, qdrant, anythingllm — up
30h) eating most of the 2GB; operator stopped them (`docker stop`, not
removed) to free ~1.9GB, and is bumping the LXC's own RAM allocation
directly via Proxmox. Installed `python3.13-venv`, `docker.io`, `rsync`,
`uv`. Synced `AgentBench` (from `garuda`, `Eugleo/agent-bench` fork,
already carries the `AGENTBENCH_SAMPLE_SEED` patch) and `tau2-bench`
(from `framework`) via `rsync`, rebuilt venvs fresh on-box (`uv venv
--python 3.9` for AgentBench per its pinned old dependency set, `--python
3.12` for τ²-bench and a new `venv-lmeval` for `lm_eval[api]`). Copied
`framework`'s HF token to `~/.cache/huggingface/token` (needed for
GPQA's gated dataset) — this specific step was blocked by the session's
auto-mode classifier as credential-handling and done manually by the
operator instead. Set up bidirectional SSH key auth between
`192.168.1.27` and `framework` (new `ed25519` keypair, added to
`framework:~/.ssh/authorized_keys`) so the driver script can poll and
issue `ollama stop`/warm-up commands remotely. New AgentBench configs:
`configs/agents/laguna-s2-1.yaml` (points at `192.168.1.8:11434`,
`framework`'s LAN IP — the `framework` hostname alias only exists in
`garuda`'s own SSH config, not on the LXC), `configs/assignments/
{definition-,}laguna-s21.yaml`.

**`~/eval-harnesses/laguna-battery.sh`** (on `192.168.1.27`, launched
2026-08-06): polls `framework` over SSH for `QWEN36_FULL_RERUN_DONE`
(so it doesn't touch model residency while the Qwen3.6-35B rerun is
still using the GPU), then stops the Qwen Ollama models, warms
`eval-laguna-s2-1:q4_k_m-ctx131k`, and runs GPQA → IFEval → τ²-bench →
AgentBench os-std (`limit=100`/`seed=42`, same standardized sample as
the Qwen comparison) sequentially, all as HTTP calls against
`framework:11434` — no inference happens on the LXC itself. Touches
`LAGUNA_TIER1_DONE` after τ²-bench, `LAGUNA_BATTERY_DONE` at the end.

**On `framework` itself**, a matching interceptor —
`~/eval-harnesses/intercept-before-laguna.sh` — was launched to poll for
`QWEN36_RERUN_DONE` and kill the original `overnight-framework.sh`
process *before* it could reach its own Part 2 (which would otherwise
race the new LXC-driven Part 2 for the same Ollama model-swap). It then
runs the IFEval recovery itself (the `nltk` transient-crash step above)
and touches `QWEN36_FULL_RERUN_DONE` — the signal `laguna-battery.sh`
is waiting on. The original `~/eval-harnesses/recover-qwen36-ifeval.sh`
and `~/eval-harnesses/overnight-garuda-laguna.sh` (which were polling
for markers this new flow no longer produces) were killed as stale.

**Real bug (2026-08-06): the interceptor's own poll loop timed out and
raced the thing it was built to prevent.** `intercept-before-laguna.sh`'s
`for _ in $(seq 1 5000); do ...; sleep 2; done` caps its own wait at
5000×2s ≈ 2h47m — but τ²-bench's rerun (the very last step of Part 1)
took ~3h20m in practice. The loop exhausted its iteration budget and
fell through to the post-loop IFEval-recovery code *without* ever
detecting `QWEN36_RERUN_DONE`, killing the main script, or touching
`INTERCEPTED_BEFORE_LAGUNA` — so when `overnight-framework.sh` finished
Part 1 for real ~15 minutes later, nothing stopped it from proceeding
into Part 2 on its own: it stopped both Qwen models and started loading
Laguna S 2.1 itself, *while* the interceptor's now-stale fallback was
simultaneously trying to run IFEval against the Qwen tag it had just
unloaded. Caught via the "status?" check that showed `ollama ps` missing
Coder and the IFEval log stuck against a model no longer resident.
Resolved by killing all four processes involved (`overnight-framework.sh`,
`intercept-before-laguna.sh`, the orphaned IFEval `lm_eval` call, and a
leftover `llama-server` subprocess `ollama serve` had already spawned
mid-load) and reassessing from a clean read of actual state — Laguna S
2.1 turned out to already be genuinely loaded and warm (a harmless
side-effect of the race, not wasted), so rather than unwind that, a
simplified `laguna-battery-v2.sh` (no wait-for-marker, no model-stop
step — those preconditions were already true) was launched directly
from `192.168.1.27` against the already-warm model, and Qwen3.6-35B's
IFEval recovery was relaunched separately and directly on `framework`
(confirmed 43Gi available with both 73GB Laguna and a reloaded 22GB
Qwen3.6-35B resident simultaneously — unified memory has the headroom,
no need to serialize the two). Stale scripts (`intercept-before-laguna.sh`,
`recover-qwen36-ifeval.sh`, the original `laguna-battery.sh` v1) deleted
on both hosts. Lesson for any future poll-loop-with-timeout: size the
timeout with real margin above the measured/estimated wait, or better,
make it unbounded (`while true`) when there's no independent reason to
ever give up — a timeout that's shorter than the thing it's waiting for
is worse than no timeout at all, since it fails silently into exactly
the race it existed to prevent.

**Resuming after these finish**: check for `LAGUNA_TIER1_DONE` /
`LAGUNA_BATTERY_DONE` on `192.168.1.27`, and the IFEval recovery log on
`framework`; read `qwen36-35b_{gpqa,tau2}_rerun.log` and
`qwen36-35b_ifeval_rerun2.log` on `framework`, and
`laguna-s21_{gpqa,ifeval,tau2,agentbench}.log` /
`AgentBench/outputs/<timestamp>/laguna-s2-1/os-std/overall.json` on
`192.168.1.27`, then fold real numbers into the tables above and the
BFCL comparison table.
