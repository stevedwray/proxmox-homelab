# Local-model eval framework expansion — 2026-08

## Status: in progress (paused 2026-08-05, safe to resume)

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
| DavidAU Fable-Fusion | Ollama | killed at 43% (~1h39m elapsed, ~34s/it and still climbing) | not scored — killed, clearly not competitive on latency regardless of eventual accuracy |

**Decision (2026-08-05): Qwen3-Coder-30B wins slot 2.** Highest accuracy
*and* fastest by a wide margin — no real trade-off to weigh. DavidAU run
killed; its 34GB Ollama load was also unloaded. No PentAGI config has been
changed as a result — that's a separate, deliberate step, not yet taken.

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
| ARC-AGI (`arc-agi-benchmarking`) | Abstract reasoning, contamination-resistant | `framework` |
| SWE-rebench (`SWE-bench-fork`) | Real-repo issue-fix patches, Docker-executed test grading | `garuda` |
| AgentBench | Multi-environment agent tasks (OS, DB, web, etc.) | `garuda` |
| CyberSecEval (Meta PurpleLlama) | Security-specific: insecure-code gen, exploit capability | `garuda` |
| GAIA | Real-world multi-step tool-use + web search | `garuda` |

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
  multiple-choice scorer) — **blocked**. `Idavidrein/gpqa` is gated on HF;
  copied `~/.cache/huggingface/token` from `garuda` to `framework` (same
  `GibbsGreatly` account) so both hosts share auth, but the account itself
  has not actually clicked through the dataset's license terms yet — see
  "Open items" below. **Correction to an earlier claim in this session**:
  a successful `hf download ... --include "README.md"` is *not* proof of
  gated-dataset access — READMEs are often visible pre-approval. Real
  access requires successfully pulling an actual data file, which failed
  with `Access denied. This repository requires approval.`

### τ²-bench (`sierra-research/tau2-bench`) — installed; smoke test paused after a real runaway-generation finding

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

Killed the run, retried with an explicit cap
(`"max_tokens": 200` added to both `--agent-llm-args` and
`--user-llm-args`) — that retry was itself stopped partway through
(operator asked to stop all in-flight work cleanly before a result came
back). **Confirmed clean shutdown**: no `tau2`/`uv` processes left on
`framework`, router idle, Ollama empty. τ²-bench is therefore installed
and its connectivity/config path is proven (the first attempt did
successfully complete the agent's opening turn and start the
user-simulator's), but **no completed smoke-test result yet** — re-running
the `max_tokens`-capped command above is the next step, not yet done.

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

### AgentBench — installed, connectivity smoke-tested successfully

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
custom `HTTPAgent` config, then exited on EOF as expected. Full
task-server + assigner pipeline (the actual Docker-sandboxed os/db/web
tasks) not yet attempted; AgentBench ships a **"Lite preset"**
(`configs/start_task_lite.yaml` / `configs/assignments/lite.yaml`)
explicitly for "laptops / limited RAM" that's the right next step now
that basic connectivity is confirmed.

### CyberSecEval (Meta PurpleLlama) — not started

Host: `garuda` (planned). Known from research before setup began: the
`AutoPatch` sub-benchmark needs Podman (already installed on `garuda`) and
is explicitly compute-intensive; its LLM-client abstraction's support for
a custom `base_url` has not yet been verified against actual source —
flagged as a check to do at setup time, not assumed.

### GAIA — repo cloned, not yet configured

Host: `garuda`, `~/eval-harnesses/smolagents` cloned (reference agent
implementation lives at
`examples/open_deep_research/run_gaia.py`, since GAIA has no
purpose-built harness of its own). Not yet installed/configured.

Known open item: the reference agent's default web-search tool
(`GoogleSearchTool`) expects a paid SerpApi/Serper key. Plan is to swap in
the existing SearXNG instance (already deployed for PentAGI) instead of
paying for a new search API — real infra reuse, not yet implemented.

**Gating status genuinely unconfirmed** (same false-positive risk as GPQA
above — a README-only download proves nothing) — needs an actual
data-file pull test before relying on it.

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

1. **GPQA and GAIA gated-dataset access**: neither is actually confirmed
   accepted under the `GibbsGreatly` HF account despite an earlier
   (incorrect) claim in this session that it was. Needs the operator to
   click through license terms at
   [huggingface.co/datasets/Idavidrein/gpqa](https://huggingface.co/datasets/Idavidrein/gpqa)
   and GAIA's dataset page — this is a web click-through, not something
   automatable from here.
2. τ²-bench airline smoke test — connectivity/config path proven, but no
   completed run yet. Root cause of the first stall identified (unbounded
   generation — small model doesn't reliably emit `###STOP###`-style
   control tokens without a `max_tokens` cap) and a fix in hand
   (`max_tokens: 200` on both `--agent-llm-args`/`--user-llm-args`); the
   capped retry was stopped mid-run at operator request (2026-08-05,
   "stop what you are doing cleanly and safely") before finishing —
   re-running it is the next step.
3. AgentBench `agent_test` connectivity check — **done, passed**.
4. CyberSecEval — not started.
5. GAIA — cloned only; needs install, SearXNG tool wiring, and a real
   gating check.
6. SWE-rebench — Docker/grading side proven; model-inference wiring
   (either patching `run_api.py` for a custom `base_url`, or adopting a
   proper agent scaffold like `mini-swe-agent`) is unstarted.
7. No PentAGI configuration has been touched by any of this — that
   remains a deliberate, separate, not-yet-taken step once the fuller
   picture (this framework buildout + BFCL) is in.
8. Session paused 2026-08-05 at operator request, mid-way through the
   τ²-bench retry. Confirmed clean state on stop: no stray `tau2`/`uv`/
   `agent_test`/`swebench` processes on either host, llama.cpp router
   idle, Ollama empty. Nothing destructive or partially-written was in
   flight — safe to resume from here.

## Next steps

1. Re-run the `max_tokens`-capped τ²-bench airline smoke test (command in
   its section above) to get a completed result.
2. Operator accepts GPQA/GAIA gating terms on HF.
3. CyberSecEval setup on `garuda`.
4. GAIA setup on `garuda` (install smolagents deps, wire SearXNG in place
   of a paid search API, verify gating, run a 1-task smoke test).
5. Once all 9 are smoke-test-clean: move from plumbing checks to real
   (small-`n`, then full) runs against the actual slot-1/slot-2 candidate
   models, not just the 3B plumbing model.
