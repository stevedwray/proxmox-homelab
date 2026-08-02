# Framework overnight LLM benchmark

Status: **harness complete and smoke-tested live, full overnight run not yet started**.

Date: 2026-07-20.

## Purpose

This harness compares the three inference runtimes installed on the rebuilt
bare-metal Ubuntu 26.04 Framework Desktop:

| Runtime | API | Backend | Current model used by the harness |
| --- | --- | --- | --- |
| llama.cpp router | `http://127.0.0.1:8080/v1` | HIP/ROCm | Llama 3.3 70B Q4 for chat/story; Qwen3-Coder 30B Q4 for code; DeepSeek-R1-Distill-Qwen 32B Q4 for security |
| LM Studio/llmster | `http://127.0.0.1:8090/v1` | Vulkan | `qwen3-coder-30b-phase6` for every suite (the only suitable imported generation model) |
| Ollama | `http://127.0.0.1:11434` | ROCm | `qwen2.5:0.5b`, currently the only installed Ollama model; smoke/performance data only, not quality-eligible |

The test is client-independent and fully local. It does not require VS Code,
Copilot, OpenWebUI, a browser, or an active SSH session after launch.

## One command

The validated harness is installed on Framework at:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh
```

The command starts a detached `systemd --user` service. It enables lingering
for the invoking user when necessary, so the run survives logout. Follow it
from a later session with:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh --status
```

For an interactive short check:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh --foreground --smoke
```

## Default matrix

The default is 17 tasks × 3 runtimes × 3 varied seeds: **153 requests**. Runs
are serial by design because the host has one unified-memory GPU and the
llama.cpp service requires `--parallel 1` for correctness.

| Suite | Tasks | Grading |
| --- | ---: | --- |
| Chat | 3 | constraint following, supplied-context retention, deterministic time arithmetic, concision |
| Story generation | 2 | required narrative elements, length, ending, point of view, forbidden clichés, lexical variety; raw prose retained for subjective review |
| Code generation | 2 | AST safety gate followed by resource-limited hidden Python tests |
| Code refactoring | 2 | behavior-preserving hidden tests plus structural checks for requested improvements |
| Vulnerability review | 8 | vulnerable/safe matched pairs for command injection, unsafe deserialization, JWT algorithm confusion, and Ansible TOCTOU/permissions; strict JSON verdict and CWE grading |

Execution-based code grading is intentionally narrow. Model code cannot import
modules, perform I/O, use dangerous attributes, or place executable statements
at module scope. Accepted code runs in a temporary directory under CPU, memory,
file-size, file-descriptor, process-count, and wall-time limits. A response
that fails the AST gate is never executed.

Security tests use structured verdicts rather than the earlier free-text
keyword grader described in
[`model-quality-and-vuln-bench-2026-07-17.md`](../framework/model-quality-and-vuln-bench-2026-07-17.md).
Matched safe variants measure false positives directly. The raw reasoning and
verdict remain available for manual review because security prose cannot be
fully judged by automation.

## Model selection

The harness discovers `/v1/models` or `/api/tags` at run start; it does not
assume that a model is still present. Preferences follow the earlier measured
findings:

- Llama 3.3 70B Q4 is the strongest resident general-chat model with reliable
  direct API behavior and is used for chat and creative work.
- Qwen3-Coder 30B is the current validated coding default and is used for code
  generation and refactoring.
- DeepSeek-R1-Distill-Qwen 32B previously had the best vulnerability catch/
  precision result, including multi-step exploit chains, and is used for the
  security suite.
- LM Studio currently exposes Qwen3-Coder 30B as its only suitable generation
  model, so it is used for all five suites. This measures that deployed runtime
  as it exists, but is not a same-model comparison for chat/security.
- Ollama currently exposes only Qwen2.5 0.5B. The harness runs it so endpoint,
  GPU, latency, and functional behavior are measured, but marks all results
  below 7B (chat/story) or 14B (code/security) as `quality_eligible: false`.
  Those scores must not be used to rank runtime quality.

An exact installed model can be forced per runtime and suite, for example:

```bash
FRAMEWORK_BENCH_OLLAMA_CODE_GENERATION_MODEL=qwen2.5-coder:32b \
  /home/steve/framework-ai-benchmark/run-overnight.sh
```

The variable pattern is
`FRAMEWORK_BENCH_<RUNTIME>_<SUITE>_MODEL`, with runtime `LLAMACPP`,
`LMSTUDIO`, or `OLLAMA` and suite `CHAT`, `STORY`, `CODE_GENERATION`,
`CODE_REFACTORING`, or `SECURITY`. An override must already be exposed by the
runtime; the benchmark never downloads a model silently.

## Autonomous runtime and memory handling

Before the first request, the harness records whether LM Studio, its health
timer, llama.cpp, and Ollama are running. It then:

1. calls ComfyUI's supported `/free` endpoint;
2. pauses LM Studio and its two-minute auto-reload timer during llama.cpp work;
3. unloads Ollama models with `keep_alive: 0`;
4. restarts the llama.cpp router between runtime groups to release its resident
   model before LM Studio or Ollama runs; and
5. restores the original service/container active states in a `finally` path
   after success, error, Ctrl-C, or termination.

This is why the default launcher requires the Framework user's existing
non-interactive sudo access. `--no-manage-runtime-memory` exists for diagnostic
use but is unsafe for the default large-model matrix.

Only one benchmark process can run at once (`flock` on a host-local lock).
Each request has a 15-minute default timeout. One failed request is recorded
and the matrix continues unless `--fail-fast` is supplied.

## Results and recovery

Each run is written to
`/storage/artifacts/framework-ai-benchmarks/<timestamp>/`:

- `manifest.json` — host, Python version, arguments, complete live model
  inventory, selected models, eligibility warnings, and harness SHA-256;
- `results.jsonl` — one fsynced record per request with prompt, raw response,
  deterministic score checks, API errors, server token timing, wall time,
  tokens/second, and the matching resource-usage window;
- `telemetry.jsonl` — one-second host samples for CPU, load, RAM, swap, GPU
  busy/GTT, temperature, power, disk I/O, network I/O, and runtime state;
- `evaluation-corpus.jsonl` and `cloud-evaluation-guide.md` — a clean prompt,
  response, model, runtime, and timing corpus plus a suggested judge schema for
  later correctness/usefulness evaluation by a cloud LLM. Operational logs are
  deliberately excluded from this export;
- `incidents/` — a timestamped evidence bundle for every failed request or new
  kernel/runtime signature such as OOM, segfault, AMD GPU reset/fault, device
  loss, watchdog, panic, or container death;
- `system-logs/` — initial/final/fatal host snapshots and complete run-window
  kernel, llama.cpp, LM Studio, and Ollama logs. Snapshots include `uname`,
  uptime, memory, process state, systemd state, Docker inspect/stats, ROCm SMI,
  and API health;
- `progress.json` — atomic current checkpoint for status reporting;
- `summary.json` and `summary.md` — aggregate scores, strict-pass rates,
  latency, throughput, and eligibility; and
- `run.log` — concise operational timeline.

Each request's resource record contains start/end/min/max/mean readings and
deltas for cumulative counters. The API calls are deliberately non-streaming,
so exact time-to-first-token is not available; that field is explicitly null
rather than being confused with whole-response latency.

The harness writes a checkpoint after every request and skips completed
runtime/suite/task/repetition keys when resumed:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh --foreground \
  --run-dir /storage/artifacts/framework-ai-benchmarks/<timestamp>
```

## Validation completed

- Nine local unit tests pass, covering the task matrix, live-format rubric
  variants, model selection/eligibility, structured security grading, hidden
  code execution, rejection of malicious generated code before execution,
  result-path confinement, telemetry aggregation, anomaly detection, and the
  separation of cloud-evaluation data from operational evidence.
- A real Ollama smoke run completed three requests, observed up to 52% GPU
  utilization, produced valid checkpoints/summaries, and restored all services.
- A real llama.cpp + LM Studio smoke run completed six requests using Llama
  3.3 70B and Qwen3-Coder 30B respectively. Both endpoints, model switching,
  telemetry, summary generation, and service restoration worked.
- The second smoke run revealed and fixed three rubric bugs: correct finish
  time is Thursday 14:00, Unicode bullet characters count as bullets, and a
  database-free answer need not mention the word “database” to respect the
  constraint. Regression coverage now pins all three cases.
- The final Ollama validation captured 23 one-second telemetry samples for
  three requests, populated every performance/resource field, generated a
  three-record cloud-evaluation corpus, and restored the original systemd and
  Docker states.
- A deliberately forced 1 ms request timeout exited non-zero as intended and
  produced an 80 KB incident bundle plus fatal/final system snapshots and all
  runtime/kernel logs. The restoration path again left LM Studio, its timer,
  llama.cpp, and Ollama active.
- The installed launcher completed a detached smoke run below the default
  `/storage/artifacts` location after the initiating SSH process had exited;
  user lingering is enabled and the transient systemd unit was collected on
  completion.

The smoke artifacts are temporary validation evidence on Framework, not
tracked repository output. The first full run remains operator-triggered via
the one command above.
