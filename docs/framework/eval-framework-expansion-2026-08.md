# Local-model eval framework expansion — 2026-08

## Status: harnesses in place — all 9 frameworks smoke-test-clean

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

1. SWE-rebench model-inference wiring.
2. Optionally: patch GAIA's `visual_qa.py` to route image captioning
   through the same `LiteLLMModel` abstraction as everything else, once
   there's a genuinely vision-capable local candidate model to test it
   with.
3. Move from plumbing checks to real (small-`n`, then full) runs against
   the actual slot-1/slot-2 candidate models across all 9 frameworks, not
   just the 3B/Coder plumbing models used for setup verification.
