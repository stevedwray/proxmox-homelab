# ComfyUI smoke tests and image benchmark

This is the operator runbook for the autonomous ComfyUI harness in
[`scripts/framework-comfyui-benchmark/`](../../scripts/framework-comfyui-benchmark/).
It complements the LLM benchmark rather than sharing its request format:
ComfyUI produces binary images and asynchronous API history, so the harness
retains the exact workflow and output PNG as well as timing and system evidence.

## Current test coverage

The rebuilt Framework currently has one complete ComfyUI generation stack:

- `z_image_turbo_bf16.safetensors` — diffusion model;
- `qwen_3_4b.safetensors` — `lumina2` text encoder;
- `ae.safetensors` — VAE.

No complete video model or second image-model stack is installed. The harness
records those facts in each manifest and does not imply that unrun model or
video comparisons passed.

The smoke mode generates one 512×512 image with four sampling steps. It checks
the HTTP API, required loader nodes and model names, workflow validation, ROCm
execution, sampler, VAE decode, output retrieval, PNG dimensions, and a
nontrivial output size.

The benchmark mode generates eight images:

1. 512×512 immediately after ComfyUI `/free` (model-load plus generation time);
2. a warm 512×512 repeat with a different seed;
3. the baseline scene at 768×768;
4. the same scene and seed at 1024×1024;
5. a photorealistic environmental portrait, including face and hands;
6. an exact-text modernist poster;
7. a counted and spatially constrained illustrated scene;
8. an open-ended surreal illustration for creativity judging.

Z-Image Turbo uses the known-good rebuilt-host workflow: Euler/simple,
`cfg=1`, 9 steps for benchmark images, `EmptySD3LatentImage`, and the loader
types confirmed through the live API. Seeds and prompts are fixed in source.

## Run it on Framework

Install or refresh the self-contained directory:

```bash
scp -r scripts/framework-comfyui-benchmark steve@framework:/home/steve/
```

Run the quick smoke test:

```bash
/home/steve/framework-comfyui-benchmark/run-comfyui-benchmark.sh --smoke
```

Run the complete image benchmark:

```bash
/home/steve/framework-comfyui-benchmark/run-comfyui-benchmark.sh --benchmark
```

Both detach into a transient systemd user unit by default. They continue after
SSH or VS Code closes because user lingering is enabled, but they do not survive
a workstation shutdown. View progress with:

```bash
/home/steve/framework-comfyui-benchmark/run-comfyui-benchmark.sh --status
```

The launcher refuses concurrent ComfyUI benchmark runs. Before submitting work,
it also refuses to disturb a non-empty ComfyUI queue. For repeatable unified-
memory measurements it records the initial runtime state, temporarily stops LM
Studio and its reload timer plus the llama.cpp and Ollama containers, calls
ComfyUI `/free`, and restores the initial service/container states in a `finally`
block. It calls `/free` again during cleanup so the LLM workload can reclaim
memory.

## Evidence collected

Runs are timestamped below:

```text
/storage/artifacts/framework-ai-benchmarks/comfyui/<UTC timestamp>/
```

Each run contains:

- `summary.md` and `summary.json` — result table and inline image review;
- `progress.json` and `run.log` — live status and operator-readable events;
- `results.jsonl` — one complete request/result/performance record per image;
- `evaluation-corpus.jsonl` — prompt-to-image mapping for cloud judging;
- `cloud-evaluation-guide.md` — a ready judging rubric;
- `outputs/*.png` — copied API outputs with dimensions, size, and SHA-256 in
  the corresponding result record;
- `workflows/*.json` — exact submitted ComfyUI API graphs;
- `telemetry.jsonl` — one-second CPU, load, RAM, swap, GPU busy, GTT, thermal,
  power, disk/network counters, and ComfyUI cgroup memory samples;
- `system-snapshot-{before,after,restored}.json` — versions, device state,
  process list, storage, Docker state/statistics, and ROCm state before the run,
  before cleanup, and after original runtime states are restored;
- `system-logs/run-logs.json` — kernel and ComfyUI logs since the run began;
- `incidents/*.json` — request-scoped logs, API history, anomalies, and full
  system state for failures.

Records are flushed after every image, and a partial `summary.md` is regenerated,
so completed evidence remains usable if a later request crashes.
While a request is active, `progress.json` and `run.log` receive a heartbeat at
least every 30 seconds with the active task, elapsed time, GPU busy percentage,
GTT use, and ComfyUI anonymous memory. During the unusually slow first model
load, rising anonymous memory with 0% GPU means CPU-side safetensors loading is
still progressing; sampling begins only after that phase completes.

## Processing results

In the morning (or after the short run), start here:

```bash
latest=$(find /storage/artifacts/framework-ai-benchmarks/comfyui \
  -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
less "$latest/summary.md"
python3 -m json.tool "$latest/summary.json"
```

Then:

1. Confirm every row succeeded and open each linked PNG in `summary.md`.
2. Compare `baseline_unloaded_512` with `baseline_warm_512` for model-load
   overhead. Do not treat them as pixel-quality pairs because their seeds differ.
3. Compare the warm 512/768/1024 baseline rows for wall-time scaling and peak
   GTT/RAM. Those three rows reuse the same seed and scene; the unloaded 512 row
   uses a different seed so ComfyUI cannot return a cached sampler result.
4. Inspect `system-logs/anomalies.json` and `incidents/` if present. Treat OOM,
   amdgpu reset/fault, HIP failure, container restart, unexpected swap growth, or
   a failed PNG validation as an operational failure even if another image ran.
5. Give a cloud vision model the PNGs, `evaluation-corpus.jsonl`, and
   `cloud-evaluation-guide.md`. Do not upload system logs: they are irrelevant to
   visual quality and may contain host details.
6. Record cloud scores alongside `results.jsonl`, keeping task names unchanged,
   then compare prompt adherence, composition, technical quality, aesthetics,
   originality, typography accuracy, and critical artifacts separately. A
   single blended score hides the exact weaknesses these prompts target.

For a quick local performance view without third-party packages:

```bash
python3 - "$latest/results.jsonl" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(line)
    gtt = r.get("resources", {}).get("mem_info_gtt_used", {}).get("max")
    print(f"{r['task']:24} ok={r['request_ok']!s:5} "
          f"wall={r['elapsed_seconds']:7.1f}s "
          f"peak_gtt={(gtt / 2**30 if gtt else 0):5.1f}GiB")
PY
```

## First complete rebuilt-host run — 2026-07-21

Artifacts: `/storage/artifacts/framework-ai-benchmarks/comfyui/20260720T183229Z/`
(the directory timestamp is UTC). The run completed 8/8 requests, produced all
eight dimension-validated PNGs, recorded no kernel/ComfyUI crash signature, and
restored LM Studio, its health-check timer, llama.cpp, and Ollama to their
initial active states.

| Case | Wall time | Peak GTT | Peak host RAM used |
| --- | ---: | ---: | ---: |
| First 512² after `/free` | 503.0s | 21.8 GiB | 26.0 GiB |
| Warm 512² | 6.0s | 21.8 GiB | 26.0 GiB |
| Warm 768² | 12.2s | 25.6 GiB | 29.7 GiB |
| Warm 1024² baseline | 22.1s | 29.1 GiB | 33.0 GiB |
| Three other 1024² use cases | 23.0–23.2s | 29.1 GiB | 32.6–32.7 GiB |

All generating requests reached 99–100% GPU busy. Peak observed sensor power
was 111 W and peak temperature was 79.1°C. Swap stayed at the pre-existing
~1.08 GiB level rather than growing. The 503-second first request was not a GPU
hang: ComfyUI mapped the 8 GB Qwen encoder and spent the long interval loading
and converting the model stack on one CPU core, with container anonymous memory
steadily increasing. Sampling itself was fast once the model was resident. This
is why the final harness now emits the 30-second active-request heartbeat.

Initial visual review (not a substitute for the saved cloud rubric):

- The baseline images obeyed the main arrangement and count: red teapot,
  napkin on the left, and three lemons on the right.
- The portrait was strong and photorealistic, with coherent hands, watchmaking
  tools, skin, hair, and lighting at first inspection.
- The spatial illustration followed all prominent count/color/position
  constraints: two orange cats left, purple suitcase right, blue robot centered
  under a green umbrella, crescent upper-left, and red aircraft upper-right.
- The typography image rendered every requested word legibly but failed the
  exact layout constraint: `FRAMEWORK AI` was split over two lines and
  `WINTER LAB` appeared twice. This is a useful real prompt-adherence failure,
  not a harness failure.
- The surreal image was coherent and attractive, but it added a title despite
  the negative `text` instruction and represented the forest-shadow concept
  more literally than requested. It needs comparative vision-model judging
  before making a creativity claim.

## Known operational caveat found during the first smoke

The first 2026-07-21 smoke exposed that the older
`/usr/local/bin/switch-to-comfyui` script still looked for `lms` under user
`steve`, while LM Studio had since moved to the dedicated `lmstudio` account.
The benchmark does not depend on that installation-specific CLI path: it stops
`lmstudio-healthcheck.timer` and `lmstudio.service` for the isolated measurement
and restores their initial state afterward. The general switch script should be
updated separately before relying on it for interactive workload switching.
