# Framework ComfyUI benchmark harness

This standard-library-only harness runs against ComfyUI on
`http://127.0.0.1:8188`. It uses the installed Z-Image Turbo stack and retains
the PNG, exact API workflow, prompt, seed, API history, timing, one-second host
and GPU telemetry, container memory, and diagnostic logs.

Run the quick functional check:

```bash
./run-comfyui-benchmark.sh --smoke
```

Run the eight-image benchmark:

```bash
./run-comfyui-benchmark.sh --benchmark
```

Both commands detach by default. Use `--status` to inspect progress or
`--foreground` to keep the run attached. The launcher temporarily stops LM
Studio and its health-check timer plus the llama.cpp and Ollama containers,
calls ComfyUI `/free`, and restores their original states at the end. Use
`--no-manage-runtime-memory` only when intentionally accepting contaminated
resource measurements and possible unified-memory contention.

Results default to `/storage/artifacts/framework-ai-benchmarks/comfyui/`.
