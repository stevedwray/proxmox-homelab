# Framework AI benchmarks

Status: **complete and analysed**.

Primary matrix: 2026-07-20 06:31-07:16 UTC (18:31-19:16 NZST).

## Controlled one-model runtime comparison (2026-07-21)

A follow-up performance run compared all three runtimes using the same source
model, `Llama-3.2-3B-Instruct-Q4_K_M.gguf`, after it had been made available to
llama.cpp directly, LM Studio by symbolic link, and Ollama through its required
canonical blob import. Each runtime used an 8,192-token context, temperature
zero, seed 4242, the same prompt, and a 512-token output cap. The runtimes were
serialized. One warm-up request was excluded, followed by five measured
requests; every measured request reached exactly 512 output tokens.

| Runtime | Mean wall tok/s | Median wall tok/s | Std. dev. | Mean wall s | Server tok/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| LM Studio / Vulkan | 87.93 | 87.97 | 0.63 | 5.82 | not exposed |
| llama.cpp / HIP | 80.97 | 80.93 | 0.18 | 6.32 | 81.66 |
| Ollama / ROCm | 78.41 | 78.46 | 0.13 | 6.53 | 80.61 |

On this controlled generation workload, LM Studio was 8.6% faster than
llama.cpp and 12.1% faster than Ollama by the common wall-clock measure.
llama.cpp was 3.3% faster than Ollama. The low run-to-run variation makes the
ordering credible for this model and configuration.

Load-to-ready observations were 1.128 seconds for the isolated llama.cpp
container, 3.803 seconds for LM Studio daemon plus model plus server startup,
and 1.146 seconds from Ollama's reported model-load duration. These boundaries
are not equivalent, so they are diagnostic observations rather than a ranked
cold-start result. LM Studio does not expose server-side generation timing in
its OpenAI-compatible response, hence wall-clock throughput is the primary
comparison metric. Output text was not bit-identical across engines despite
aligned model, prompt, context, temperature, and seed; this run establishes
performance, not cross-engine deterministic or quality equivalence.

Evidence and the exact one-off runner are retained on Framework at
`/storage/artifacts/framework-ai-benchmarks/apples-llama32-20260721T000313Z/`.
The exit path restored the original state: LM Studio's Qwen model resident,
the pilot unloaded from llama.cpp and Ollama, and all normal services active.

## Controlled 30B/65K-context comparison (2026-07-21)

A second controlled run used the larger
`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` model and a 65,536-token context in
all three engines. llama.cpp read the shared GGUF directly, LM Studio used its
symbolically linked copy of the same model, and Ollama used the canonical blob
created from that GGUF. The Ollama import requires an additional 18,556,689,568
bytes of storage; a hard link cannot avoid that canonical rewrite.

The serialized test used temperature zero and seed 4242. The short workload
contained 74 input tokens and requested 512 output tokens; one warm-up was
excluded and five requests were measured. The long workload contained 41,508
input tokens and requested 256 output tokens; one warm-up was excluded and
three requests were measured. A per-repetition nonce appeared before the long
reference ledger to prevent prompt-prefix cache reuse. Every accepted request
reached its output cap.

Short-prompt generation:

| Runtime | Mean wall tok/s | Median wall tok/s | Std. dev. | Mean wall s | Server tok/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| LM Studio / Vulkan | 84.13 | 84.08 | 0.14 | 6.09 | not exposed |
| llama.cpp / HIP | 68.16 | 68.15 | 0.04 | 7.51 | 68.82 |
| Ollama / ROCm | 66.57 | 66.56 | 0.15 | 7.69 | 68.25 |

Long-context end-to-end performance:

| Runtime | Mean total wall s | Prompt eval s | Prompt tok/s | Generation s | Generation tok/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ollama / ROCm | 83.92 | 74.74 | 555.37 | 8.26 | 31.01 |
| llama.cpp / HIP | 96.41 | 87.55 | 474.08 | 8.19 | 31.24 |
| LM Studio / Vulkan | 146.75 | not exposed | not exposed | not exposed | not exposed |

The winner therefore depends on workload. LM Studio was 23.4% faster than
llama.cpp and 26.4% faster than Ollama for short-context generation. With
41,508 input tokens, Ollama had 13.0% lower end-to-end latency than llama.cpp
and 42.8% lower latency than LM Studio; llama.cpp was 34.3% lower-latency than
LM Studio. llama.cpp and Ollama both fell to approximately 31 generated tok/s
once the active context was large, while prompt ingestion dominated total
latency. LM Studio's API does not split prompt and generation timing, but its
end-to-end result is directly comparable.

The accepted evidence and exact runner are retained at
`/storage/artifacts/framework-ai-benchmarks/apples-qwen30b-65k-20260721T003809Z/`.
An earlier attempt in the adjacent `...T002941Z` directory is diagnostic only:
its repeated prefix was cached and most long responses stopped after one
token, so those long-context numbers were explicitly rejected. The accepted
run produced no GPU reset, OOM-kill, segfault, or watchdog signature and
restored all normal services and the original LM Studio model residency.

## Ollama Docker versus native host execution (2026-07-21)

The accepted Qwen 30B/65K Ollama workloads were repeated with Ollama executing
directly on the Framework host. Framework had no native Ollama package or
service installed, so the test extracted the exact Ollama 0.32.1 binary and
2.5 GiB ROCm runtime bundle from the existing Harbor-sourced Docker image into
a temporary directory. A transient host systemd unit ran those files as user
`steve` on port 11435, using the same canonical model store. This held the
Ollama version, libraries, model, backend, prompts, context, and sampling
settings constant while changing the Docker boundary. The temporary runtime
was removed after the run; no persistent native installation was made.

| Workload | Docker Ollama | Native Ollama | Result |
| --- | ---: | ---: | --- |
| Short, 74 input + 512 output | 66.57 wall tok/s | 64.19 wall tok/s | Docker 3.7% faster |
| Long, 41,508 input + 256 output | 83.92 s total | 89.85 s total | Docker 6.6% lower latency |

The long-context timing breakdown explains most of the difference:

| Deployment | Prompt eval s | Prompt tok/s | Generation s | Generation tok/s |
| --- | ---: | ---: | ---: | ---: |
| Docker | 74.74 | 555.37 | 8.26 | 31.01 |
| Native host | 80.59 | 515.04 | 8.41 | 30.44 |

Native execution therefore provided no performance benefit. Docker was
slightly faster in both workloads, with most of the long-context delta in
prompt ingestion rather than generation. This is one sequential paired run,
not randomized interleaving, so the small short-generation difference may
include normal system variance; it is nevertheless sufficient to reject a
meaningful Docker overhead on this stack.

The native log confirms `library=ROCm`, `compute=gfx1151`, all 49 layers
offloaded, a 17.5 GiB GPU model buffer, and a 6 GiB GPU KV cache. All eight
measured native requests reached their output caps, and there was no GPU reset,
OOM-kill, segfault, or watchdog signature. Evidence, runtime hashes, the host
systemd cgroup, logs, and the exact comparison are retained at
`/storage/artifacts/framework-ai-benchmarks/native-ollama-qwen30b-65k-20260721T011048Z/`.
Docker Ollama remained the persistent deployment and was restored with no
resident model.

The accepted evidence consists of 171 successful requests across the primary
matrix and creative follow-ups. A separate six-request failed Command-R launch
is retained as configuration/reliability evidence; it is not part of quality or
performance averages.

| Run | Purpose | Accepted records | Result |
| --- | --- | ---: | --- |
| `20260720T063153` | Full llama.cpp, LM Studio, and Ollama matrix | 153 | Complete |
| `20260720T071650` | L3.1 creative follow-up | 6 | Complete |
| `20260720T072420` | L3.2 creative follow-up | 6 | Complete |
| `20260720T072622` | Command-R at router default 65,536 context | 0 | Six model-load failures; diagnostic only |
| `20260720T080605` | Command-R retry at 8,192 context | 6 | Complete |

This is the operator record and morning-processing runbook. See
[`overnight-llm-benchmark.md`](./overnight-llm-benchmark.md) for the detailed
harness design, model-selection rationale, safety controls, and validation
history.

## What was implemented

The repository harness is in
[`scripts/framework-ai-benchmark/`](../../scripts/framework-ai-benchmark/)
and the validated copy is installed on Framework at
`/home/steve/framework-ai-benchmark/`.

The launcher runs the Python harness as a transient detached `systemd --user`
service. User lingering is enabled, so the run continues after SSH, VS Code,
and the interactive login close. The process serializes the GPU-heavy
runtimes, checkpoints after every request, and restores the original LM Studio,
llama.cpp, and Ollama states on success, interruption, or failure.

The full matrix contains 153 requests: 17 tasks, three runtimes, and three
repetitions with varied seeds.

| Suite | Tasks | What is tested |
| --- | ---: | --- |
| Chat | 3 | supplied-context comprehension, incident-response planning, and time/schedule reasoning |
| Story generation | 2 | narrative constraints, coherence proxies, viewpoint, ending, length, cliché avoidance, and lexical variety |
| Code generation | 2 | generated Python, an AST safety gate, and resource-limited hidden functional tests |
| Code refactoring | 2 | behaviour preservation under hidden tests plus requested structural improvements |
| Security review | 8 | matched vulnerable/safe cases for command injection, unsafe deserialization, JWT algorithm confusion, and Ansible TOCTOU/file permissions |

The task-specific resident models selected at run start are:

- llama.cpp: Llama 3.3 70B Q4 for chat/story, Qwen3-Coder 30B Q4 for
  generation/refactoring, and DeepSeek-R1-Distill-Qwen 32B Q4 for security;
- LM Studio: `qwen3-coder-30b-phase6`, its only suitable imported generation
  model; and
- Ollama: `qwen2.5:0.5b`, its only installed model. Ollama is retained for
  runtime/performance evidence but marked `quality_eligible: false`; it must
  not be used in comparative quality rankings.

The primary run completed all 153 requests in 44 minutes 23 seconds. Its
follow-ups completed without requiring an interactive terminal or VS Code.

## Results and recommendations

### Reliability

- All 171 accepted requests returned successfully, with no benchmark-detected
  kernel, GPU-reset, segfault, OOM-kill, or service-death signature.
- The first Command-R attempt failed cleanly at model load on all six requests.
  The router requested approximately 81,920 MiB for the 65,536-token context
  and `cudaMalloc` returned out-of-memory. This was a model/context
  configuration failure rather than an inference crash. Retrying the same
  model through an isolated 8,192-token llama.cpp instance produced six
  successful responses. The temporary instance was removed and original
  services were restored.
- The highest reported temperature sensor reading was 92.625 C during a
  DeepSeek `pickle_safe` request. Peak observed swap was 0.59 GiB, load was
  2.62, and CPU busy was 9.47%. There was no correlated reset or thermal error
  signature, but the 92.625 C peak merits watching on future long runs.
- GPU use reached 100% for every large llama.cpp model. The primary run and all
  accepted follow-ups restored the initially active LM Studio, llama.cpp, and
  Ollama services.

### Performance and deterministic quality

The following table uses the corrected offline grades described below. “Cloud”
is the mean of correctness, usefulness, and instruction-following scores from
the full-output review, on a 0-5 scale. Wall time is per request. These are
model-and-runtime pair results, not a pure runtime contest: the runtimes did not
serve identical model files.

| Runtime/model | Suite | Deterministic | Strict | Cloud | Wall s | Gen tok/s | Peak RAM GiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| llama.cpp / Llama 3.3 70B Q4 | Chat | 1.000 | 100.0% | 4.63 | 19.12 | 4.77 | 63.2 |
| llama.cpp / Llama 3.3 70B Q4 | Story | 1.000 | 100.0% | 4.00 | 166.47 | 4.70 | 64.6 |
| llama.cpp / Qwen3-Coder 30B Q4 | Code generation | 0.500 | 50.0% | 3.17 | 4.39 | 69.51 | 27.0 |
| llama.cpp / Qwen3-Coder 30B Q4 | Refactoring | 0.875 | 50.0% | 4.50 | 3.05 | 69.50 | 27.1 |
| llama.cpp / DeepSeek R1 Qwen 32B Q4 | Security | 0.827 | 70.8% | 3.33 | 50.60 | 10.47 | 40.5 |
| LM Studio / qwen3-coder-30b-phase6 | Chat | 0.941 | 66.7% | 4.04 | 1.57 | 77.67 | 45.7 |
| LM Studio / qwen3-coder-30b-phase6 | Code generation | 0.500 | 50.0% | 3.17 | 2.17 | 80.09 | 46.1 |
| LM Studio / qwen3-coder-30b-phase6 | Refactoring | 0.875 | 50.0% | 4.50 | 2.54 | 78.87 | 46.2 |
| LM Studio / qwen3-coder-30b-phase6 | Security | 0.694 | 50.0% | 3.83 | 1.29 | 78.27 | 46.4 |
| LM Studio / qwen3-coder-30b-phase6 | Story | 0.972 | 83.3% | 3.72 | 8.38 | 82.47 | 45.9 |

Ollama's only resident model, Qwen 2.5 0.5B, completed every request at
255-260 generated tokens/s, 1.1-3.3 seconds per request, and at most 4.7 GiB
RAM. It achieved no strict passes and remains a smoke/throughput baseline only;
it is excluded from quality comparisons.

The LM Studio pair is the clear practical throughput winner in this inventory:
approximately 78-82 generated tokens/s and single-digit wall times. Llama 3.3
70B is much slower at 4.7 tokens/s and consumes about 65 GiB, but it is the most
reliable chat and literal story-constraint follower. Qwen3-Coder through
llama.cpp used substantially less RAM than the LM Studio variant, while LM
Studio was modestly faster on the same code task prompts.

### Correctness and usefulness findings

- **Chat:** Llama 3.3 won overall. It obeyed every bounded constraint and gave
  the correct schedule result. Its incident responses did assume resolution in
  the customer message before verification. LM Studio was much faster, but it
  invented rollback outcomes and measurements, and one response contradicted
  the supplied “no database” fact.
- **Code generation:** Both eligible Qwen variants passed `merge_intervals`
  three times and failed `unicode_slugify` three times. The slug implementations
  used explicitly prohibited imports and mishandled separators or Unicode
  normalization. There is no eligible code-generation winner on this small
  corpus.
- **Refactoring:** Both Qwen variants passed the order refactor after correcting
  the grader's nested-helper defect. Both accepted `True` as an integer chunk
  size, contrary to the prompt, so their strict pass rate is 50%. They are tied
  on output quality; LM Studio is faster and llama.cpp uses less RAM.
- **Security:** DeepSeek made the correct safe/vulnerable decision on 19/24
  samples and LM Studio on 15/24. DeepSeek is therefore the better detector in
  this run, but it wrapped every answer in Markdown despite the exact-JSON
  requirement. LM Studio returned directly parseable JSON, but produced nine
  false positives across the safe Ansible, command, and pickle cases and used
  the wrong CWE on all three vulnerable Ansible cases. Neither should be used
  as an autonomous security gate without schema validation and a second-stage
  verifier.
- **Repeatability:** Many temperature-zero chat, code, and security responses
  were identical across seeds. Three repetitions provide stability evidence,
  but not three independent reasoning approaches.

### Creative-model comparison

| Model/runtime | Deterministic | Strict | Cloud | Wall s | Gen tok/s | Peak RAM GiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Llama 3.3 70B / llama.cpp | 1.000 | 100.0% | 4.00 | 166.47 | 4.70 | 64.6 |
| qwen3-coder-30b-phase6 / LM Studio | 0.972 | 83.3% | 3.72 | 8.38 | 82.47 | 45.9 |
| L3.1 MoE 36B / llama.cpp | 0.873 | 33.3% | 3.14 | 71.81 | 9.60 | 32.9 |
| L3.2 MoE 21B / llama.cpp | 0.905 | 66.7% | 2.94 | 17.20 | 46.57 | 24.2 |
| Command-R 35B / llama.cpp, 8K context | 0.790 | 0.0% | 2.64 | 95.10 | 9.10 | 38.3 |

Llama 3.3 is the best of the tested story models for constraint compliance and
coherence, although its prose is formulaic. LM Studio's Qwen is the best
speed/quality compromise and sometimes more vivid, but contains more factual
and internal inconsistencies. The creative fine-tunes did not improve judged
literary usefulness: L3.2 scored well mechanically but moved two Mars stories
to Earth's Svalbard/arctic setting; L3.1 was repetitive and uneven; Command-R
leaked `<|END_OF_TURN_TOKEN|>` after every response, breaking exact endings,
and included serious Martian-atmosphere errors.

### Recommended use of the installed stack

- Use **LM Studio/qwen3-coder-30b-phase6** for interactive drafting and coding
  where latency matters, with tests or review applied to every code result.
- Use **llama.cpp/Llama 3.3 70B** when instruction fidelity and supplied-context
  retention matter more than latency.
- Use **llama.cpp/DeepSeek R1 Qwen 32B** as a security-review assistant, not a
  decision-maker; normalize its fenced JSON and independently verify findings.
- Keep **Ollama/Qwen 0.5B** only as a health and maximum-throughput baseline
  until a quality-eligible Ollama model is installed.
- Prefer **Llama 3.3** for unattended story generation, or LM Studio Qwen when
  throughput is the priority. Do not prefer the three creative fine-tunes on
  the evidence from this corpus.

### Analysis corrections and limitations

The audit found and corrected two harness-analysis defects:

1. The AST gate recognized only top-level functions, despite the order-refactor
   prompt requiring a helper. It now accepts calls to generated nested helpers
   and counts them for the structural check. This changes both eligible order
   tasks from false failures to passes.
2. Model-size parsing selected the first `B` token in a name. That marked the
   `8X4B ... 21B` model as 4B and ineligible. Parsing now uses the largest
   explicit parameter count, correctly classifying it as 21B.

The corrected harness and its regression tests were installed at
`/home/steve/framework-ai-benchmark/` after analysis; all 11 tests also pass on
Framework. No rerun is needed because the raw outputs were regraded offline.

Imports remain prohibited in code tasks exactly as the prompts specify. The
original run artifacts are immutable; corrected grades are derived alongside
them. Non-streaming API calls cannot report time to first token. One-second
telemetry also leaves some sub-two-second LM Studio and Ollama requests with
zero to two resource samples, so their request-level resource means are less
robust than the longer llama.cpp samples. The corpus is deliberately compact;
its rankings are directional, not a comprehensive model certification.

The processed results are on Framework at
`/storage/artifacts/framework-ai-benchmarks/analysis-20260720/`. A local ignored
working copy is in
`docs/framework-ubuntu/artifacts/benchmark-analysis-20260720/`. Both contain
`corrected-results.jsonl`, `corrected-summary.json`, `cloud-scores.jsonl`, and
`cloud-summary.json`. The cloud review contains one judgment for each of the
171 accepted responses. Every quality-eligible output was reviewed in full;
the excluded Ollama smoke records retain mechanically derived scores for
completeness.

## Creative-model follow-up mechanics

The detached follow-up did not modify or interrupt the 153-request matrix. It
ran both story tasks three times for each creative model. Each model has a
separate timestamped result directory, preserving clear provenance.

The queue writes `creative-followup-<timestamp>.tsv` in the benchmark results
root, mapping each model to its result directory and final status. If a future
parent benchmark fails or is interrupted, the follow-up exits without running;
resume and complete the parent before re-queuing it.

## Evidence collected

The run directory contains:

- `manifest.json`: arguments, host details, discovered model inventory,
  selected models, eligibility, and harness hash;
- `results.jsonl`: complete prompts and raw outputs, deterministic grades,
  errors, wall/server timing, token throughput, and per-request resource data;
- `telemetry.jsonl`: one-second CPU, load, RAM, swap, GPU/GTT, temperature,
  power, disk, network, and periodic runtime-state samples;
- `progress.json`: the durable completion checkpoint;
- `summary.md` and `summary.json`: per-runtime/suite success, quality, latency,
  and throughput aggregates;
- `evaluation-corpus.jsonl`: the clean dataset intended for cloud-LLM judging;
- `cloud-evaluation-guide.md`: judge instructions and required output schema;
- `incidents/`: request-failure or anomaly-triggered evidence bundles; and
- `system-logs/` plus `system-snapshot-*.json`: kernel/runtime logs and
  initial, final, or fatal system state.

An incident bundle includes the failing record, nearby kernel/runtime logs,
API health, memory/process state, Docker state and stats, systemd state, and
ROCm information. Signatures include OOM kills, segfaults, AMD GPU faults or
resets, device loss, watchdog/panic events, and container deaths.

## Morning procedure

The 2026-07-20 evidence has already been processed and its conclusions are
recorded above. The procedure below is retained for independent verification
and future overnight runs.

Set the run location once in the morning shell:

```bash
RUN_DIR=/storage/artifacts/framework-ai-benchmarks/20260720T063153
```

### 1. Confirm completion

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh --status
jq . "$RUN_DIR/progress.json"
```

A successful complete run has `"complete": true` and `"total_records": 153`.
The transient benchmark unit normally disappears once it has finished.

A queued creative follow-up may still be active after its parent unit
disappears. Check it and locate its result index with:

```bash
systemctl --user status framework-ai-benchmark-creative-followup.service
ls -1t /storage/artifacts/framework-ai-benchmarks/creative-followup-*.tsv | head -n 1
```

Wait for that follow-up unit to finish before processing the three additional
story runs. Apply the same review procedure below to each directory named in
the TSV index. They are deliberately separate from the 153-record parent, so
their `progress.json` files each report six records.

If the unit is no longer active but `complete` is not true, inspect the end of
the operational log:

```bash
tail -n 100 "$RUN_DIR/run.log"
```

After addressing any recorded failure, resume the same checkpoint as another
detached service; completed request keys will be skipped:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh --run-dir "$RUN_DIR"
```

Do not launch an ordinary new run when the intent is to resume this directory.

### 2. Verify services were restored

```bash
sudo systemctl is-active lmstudio.service lmstudio-healthcheck.timer
sudo docker inspect -f '{{.Name}} {{.State.Running}}' llamacpp-router ollama
```

For this run, both systemd units and both containers were active initially and
should therefore all report active/true afterward.

### 3. Triage failures and incidents first

Count failed API requests and print their identities/errors:

```bash
jq -s '[.[] | select(.request_ok != true)] | length' "$RUN_DIR/results.jsonl"
jq -c 'select(.request_ok != true) | {runtime,model,suite,task,repetition,error}' "$RUN_DIR/results.jsonl"
```

List captured incident evidence:

```bash
find "$RUN_DIR/incidents" -maxdepth 1 -type f -printf '%f\n' | sort
```

Print records where the harness saw a crash/error signature even if the API
request itself returned:

```bash
jq -c 'select(((.log_anomalies // []) | length) > 0) | {runtime,model,suite,task,repetition,log_anomalies}' "$RUN_DIR/results.jsonl"
```

Review a listed incident JSON before the larger final logs. Use
`system-snapshot-final.json` and `system-logs/*-final.log` for run-wide context.
Operational evidence can contain host details, so keep it local unless it is
specifically needed for troubleshooting.

### 4. Review deterministic quality and performance

Start with the human-readable aggregate:

```bash
less "$RUN_DIR/summary.md"
jq . "$RUN_DIR/summary.json"
```

The important columns are request success, mean deterministic score, strict
pass rate, mean wall seconds, and mean tokens/second. Exclude rows whose
`quality_eligible` value is false from quality conclusions.

This command produces an eligible-model timing table directly from raw data:

```bash
jq -s '
  map(select(.request_ok == true and .quality_eligible == true))
  | group_by([.runtime, .suite])
  | map({
      runtime: .[0].runtime,
      suite: .[0].suite,
      requests: length,
      mean_wall_seconds: (map(.performance.wall_seconds) | add / length),
      mean_generation_tokens_per_second:
        (map(.performance.generation_tokens_per_second)
         | map(select(. != null))
         | if length > 0 then add / length else null end)
    })' "$RUN_DIR/results.jsonl"
```

This command summarizes peak observed resources by runtime and suite:

```bash
jq -s '
  map(select(.request_ok == true))
  | group_by([.runtime, .suite])
  | map({
      runtime: .[0].runtime,
      suite: .[0].suite,
      peak_gpu_percent: (map(.resource_usage.gpu_busy_percent.max // 0) | max),
      peak_memory_gib:
        ((map(.resource_usage.memory_used_bytes.max // 0) | max) / 1073741824),
      peak_temperature_c:
        (map(.resource_usage.temperature_max_c.max // 0) | max),
      peak_power_w: (map(.resource_usage.power_total_w.max // 0) | max)
    })' "$RUN_DIR/results.jsonl"
```

Treat these request windows as comparative observations, not isolated process
measurements: unified GPU memory is included in host memory and other host
activity can contribute to power and I/O.

### 5. Evaluate correctness and usefulness with a cloud LLM

Use only these two files for normal cloud judging:

- `evaluation-corpus.jsonl`
- `cloud-evaluation-guide.md`

Do not upload `system-logs/`, `incidents/`, or system snapshots as part of the
quality evaluation. They add irrelevant operational context and may disclose
host details.

The corpus has one self-contained JSON object per request. Give the guide to
the cloud model as its judging instruction and supply corpus records in small
batches (approximately 10–20 lines) to avoid context pressure. Ask it to return
JSONL only, with one result per input and these fields:

```text
runtime, model, suite, task, repetition,
correctness_0_to_5, usefulness_0_to_5,
instruction_following_0_to_5, concise_rationale, critical_error
```

Preserve the identity fields exactly so results can be joined later. Use the
same cloud model, system prompt, temperature, and judging procedure for every
batch. Do not tell the judge which local runtime is expected to win.

Create manageable batches on Framework with:

```bash
mkdir -p "$RUN_DIR/cloud-evaluation/batches" "$RUN_DIR/cloud-evaluation/results"
split -l 15 -d -a 3 "$RUN_DIR/evaluation-corpus.jsonl" "$RUN_DIR/cloud-evaluation/batches/batch-"
```

For each `batch-*` file, upload the guide and that batch. Save the returned
JSONL under `cloud-evaluation/results/` using the matching batch name. Validate
each response before combining it:

```bash
jq -e . "$RUN_DIR/cloud-evaluation/results/batch-000.jsonl" >/dev/null
```

After all batches are judged, combine them and confirm the count is 153:

```bash
find "$RUN_DIR/cloud-evaluation/results" -type f -name 'batch-*.jsonl' -print0 \
  | sort -z \
  | xargs -0 -r cat > "$RUN_DIR/cloud-evaluation/cloud-scores.jsonl"
wc -l "$RUN_DIR/cloud-evaluation/cloud-scores.jsonl"
```

Generate an eligible-only cloud quality summary:

```bash
jq -s --slurpfile source "$RUN_DIR/evaluation-corpus.jsonl" '
  map(. as $score
    | ($source[]
       | select(.runtime == $score.runtime
                and .model == $score.model
                and .suite == $score.suite
                and .task == $score.task
                and .repetition == $score.repetition)) as $input
    | . + {quality_eligible: $input.quality_eligible})
  | map(select(.quality_eligible == true))
  | group_by([.runtime, .model, .suite])
  | map({
      runtime: .[0].runtime,
      model: .[0].model,
      suite: .[0].suite,
      samples: length,
      correctness: (map(.correctness_0_to_5) | add / length),
      usefulness: (map(.usefulness_0_to_5) | add / length),
      instruction_following:
        (map(.instruction_following_0_to_5) | add / length),
      critical_errors: (map(select(.critical_error != null and .critical_error != "")) | length)
    })' "$RUN_DIR/cloud-evaluation/cloud-scores.jsonl" \
  > "$RUN_DIR/cloud-evaluation/cloud-summary.json"
```

The join prevents Ollama's ineligible 0.5B results from entering the comparative
quality table while retaining its raw judge scores for completeness. Compare
cloud scores with deterministic grades rather than replacing them: large
disagreements are the most useful records for manual review.

### 6. Preserve the completed evidence

Once processing is complete, create checksums without changing the raw files:

```bash
cd "$RUN_DIR"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
```

Keep derived cloud results inside `cloud-evaluation/`. Benchmark artifacts stay
on Framework under `/storage/artifacts`; only durable conclusions should be
folded back into tracked documentation.

## Validation and source state

The installed harness passed foreground success, deliberate-timeout incident,
and detached logout-survival tests on Framework. The audited source passes 11
regression tests, Ruff, Bandit, ShellCheck, and repository whitespace checks.
SonarCloud reports no unresolved issue or security hotspot in the harness; the
repository-wide quality gate remains red because of existing unrelated
backlog. Development and analysis are on
`task/framework-overnight-benchmarks`; the initial deployed harness is commit
`87a8fed0`, with the grader corrections documented above made after the run.
