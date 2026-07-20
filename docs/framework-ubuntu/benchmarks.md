# Framework AI benchmarks

Status: **full overnight run in progress**.

Started: 2026-07-20 06:31 UTC (18:31 NZST).

Run directory:
`/storage/artifacts/framework-ai-benchmarks/20260720T063153`.

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

The current run was observed completing its first request successfully while
continuous telemetry, raw results, and the evaluation corpus were all growing.
No incident was present at that checkpoint.

### Queued creative-model follow-up

A detached follow-up is queued behind the main run. It does not modify or
interrupt the 153-request matrix. After the parent reports successful
completion, it runs both story tasks three times with each of these llama.cpp
models (18 additional requests):

- `L3.1-MOE-6X8B-Dark-RS-Dantes-Peak-HRR-R1-Uncen-36B-Q4_K_M-imat`;
- `L3.2-8X4B-MOE-V2-Dark-Champion-Inst-21B-uncen-ablit-D_AU-Q4_k_m`; and
- `Command-R-35B-Dark-Horror-V2-D_AU-Q4_k_s`.

Each model has a separate normal timestamped result directory. The queue writes
`creative-followup-<timestamp>.tsv` in the benchmark results root, mapping each
model to its result directory and final status. If the parent benchmark fails
or is interrupted, the follow-up exits without running; resume and complete the
parent before re-queuing it.

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

The queued creative follow-up may still be active after this parent unit
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
jq -c 'select(((.anomalies // []) | length) > 0) | {runtime,model,suite,task,repetition,anomalies}' "$RUN_DIR/results.jsonl"
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
and detached logout-survival tests on Framework. Nine regression tests, Ruff,
Bandit, ShellCheck, and repository whitespace checks pass. SonarCloud reports
no unresolved issue or security hotspot in the harness; the repository-wide
quality gate remains red because of existing unrelated backlog.

Source commit: `87a8fed0` on `task/framework-overnight-benchmarks`.
