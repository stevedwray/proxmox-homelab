# Framework AI benchmark harness

Run the full suite on `framework.gibbsgreatly.xyz` with one command:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh
```

The launcher starts a detached systemd user service and enables user lingering
when needed. Closing SSH or VS Code does not stop it. Check progress with:

```bash
/home/steve/framework-ai-benchmark/run-overnight.sh --status
```

Use `--foreground --smoke` for a short interactive validation. The default
performs three repetitions of 17 tasks on llama.cpp, LM Studio, and Ollama.
Results go to `/storage/artifacts/framework-ai-benchmarks/<timestamp>/`.

The harness has no third-party Python dependencies. It discovers live models,
selects a task-appropriate model, serializes GPU-heavy runtimes, checkpoints
after every request, restores initial service states on exit, and records raw
responses plus deterministic graders. It also records one-second CPU, memory,
GPU, power, temperature, disk, and network telemetry; request-level timing and
resource summaries; complete runtime/kernel logs; anomaly-triggered incident
snapshots; and a separate JSONL corpus for later cloud-LLM evaluation. See
[`docs/framework-ubuntu/overnight-llm-benchmark.md`](../../docs/framework-ubuntu/overnight-llm-benchmark.md)
for the matrix, safety model, outputs, and overrides.

Local regression tests:

```bash
python3 -m unittest discover -s scripts/framework-ai-benchmark -p 'test_*.py' -v
```

`run-creative-followup.sh` is a queue helper for the 2026-07-20 run. It waits
for a named benchmark user unit to finish successfully, then runs the two story
tasks three times against each of the three installed Dark/uncensored creative
models. Each model receives its own ordinary checkpointed benchmark directory.
