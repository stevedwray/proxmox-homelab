# llama.cpp Router Mode — Deployment Pattern

Reference pattern for serving multiple GGUF models from a single llama.cpp
endpoint, replacing the one-systemd-unit-per-model approach used throughout
the [code-quality and vulnerability-finding benchmarks](model-quality-and-vuln-bench-2026-07-17.md).
Validated live on container 9001 (`llamacpp-gpu-native`) on 2026-07-16/17.

## Why this exists

Every benchmark in this project so far ran one `llama-server -m
<model>.gguf` process per model, on its own port, started and stopped by
hand (or by a script) whenever the active model needed to change. That's
fine for a scripted A/B benchmark where you control the sequence, but it's
the wrong shape for an actual service: callers would need to know which
port serves which model, and switching models means someone (or something)
running `systemctl stop`/`start` at the right moment.

llama-server has a native **router mode** for this (confirmed against
`tools/server/README.md` on the `ggml-org/llama.cpp` repo, and confirmed
working on our own HIP build — this is not a third-party add-on). One
process, one stable endpoint, one port. The `"model"` field in each request
picks which GGUF gets loaded; the router loads it on first use and unloads
whatever's in the way, according to a concurrency cap you set.

The community proxy [llama-swap](https://github.com/mostlygeek/llama-swap)
solves the same problem and is worth knowing about if you ever need to
front a mix of backends (llama.cpp + vLLM, say) behind one endpoint — but
for a pure llama.cpp deployment, router mode is native and requires nothing
extra.

## The pattern

### 1. GPU passthrough is a container property; model choice is not

This is the key architectural point: **you do not need one container per
model.** The expensive, fiddly one-time setup — `/dev/kfd` passthrough,
AppArmor/cap-drop config, ROCm or Vulkan driver install (see
[proxmox-strix-halo-setup-notes.md](proxmox-strix-halo-setup-notes.md)) — is
done once per container. Model selection happens at the process level
inside it. A single container can host as many GGUF files as fit on disk,
with the router (or, as before, hand-managed systemd units) choosing which
one is actually resident in GPU/host memory at any moment.

### 2. Directory layout

Router mode's `--models-dir` just wants a flat directory of `.gguf` files
(or one subdirectory per model, only needed for multimodal/multi-shard
models — not relevant to anything downloaded so far):

```
/data/models/
├── DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf
├── Llama-3.3-70B-Instruct-Q4_K_M.gguf
└── Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf
```

The model `id` exposed over the API is the filename without extension —
no manifest or registration step. Confirmed live: `GET /v1/models` listed
all three of the above the moment the router started, all `"unloaded"`.

### 3. Launch command

```sh
llama-server \
  --host 0.0.0.0 --port 8080 \
  --models-dir /data/models \
  --models-max 1 \
  --n-gpu-layers 999 \
  --ctx-size 8192
```

- **No `-m` flag** — that's what puts the server in router mode instead of
  single-model mode. Passing `-m` alongside `--models-dir` is a mistake, not
  a hybrid mode.
- `--n-gpu-layers` and `--ctx-size` here are *global defaults inherited by
  every model instance* the router spawns — not tied to one model. Use
  `--models-preset some.ini` instead if different models need different
  context sizes or GPU-layer counts.
- `--models-max N` is the concurrency cap, default 4. This is the one
  setting that has to match your actual memory budget — see below.

### 4. Systemd unit (persistent, not the transient one used for testing)

The validation run used `systemd-run --unit=llama-router ...` for a quick
live test. For anything that should survive a reboot, write it as a real
unit instead:

```ini
# /etc/systemd/system/llama-router.service
[Unit]
Description=llama.cpp router mode - multi-model
After=network.target

[Service]
ExecStart=/opt/llama.cpp/build-hip/bin/llama-server \
  --host 0.0.0.0 --port 8080 \
  --models-dir /data/models \
  --models-max 1 \
  --n-gpu-layers 999 \
  --ctx-size 8192
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now llama-router`. This is the piece not yet added to
the Ansible roles (see "Not yet done").

### 5. Client usage — no port-tracking required

Every caller talks to the same `http://<host>:8080/v1/chat/completions` and
just names the model:

```json
{
  "model": "Qwen2.5-Coder-32B-Instruct-Q4_K_M",
  "messages": [{"role": "user", "content": "..."}]
}
```

The router loads it if it isn't already resident, evicts whatever's
occupying the slot if `--models-max` is full, and proxies the request
through. `GET /v1/models` at any time shows exactly which model(s) are
currently `"loaded"` vs `"unloaded"`.

### 6. Adding a new model later

Drop the new `.gguf` into `/data/models/` and call `GET
/v1/models?reload=1` — no restart needed for files added to a
`--models-dir`. (A restart *is* required if you add a model via the
`-hf user/repo` HuggingFace-cache path instead; not relevant to this
container, which uses local files.)

### 7. Idle unloading, if you want it

`--sleep-idle-seconds N` unloads a model's memory (including its KV cache)
after N seconds of no real traffic, reloading automatically on the next
request. `GET /health`, `/props`, and `/models` don't count as traffic and
won't reset the idle timer or trigger a reload — useful for a monitoring
probe that shouldn't itself keep a model pinned in memory. Not enabled in
the tested config; worth adding for a deployment with genuinely bursty,
unpredictable usage rather than the back-to-back benchmark traffic used
here.

## Live validation (2026-07-16, container 9001, 8GB memory limit)

`--models-max 1` was chosen to match the memory ceiling already established
during the vulnerability-finding benchmark: two 32B-class models loaded
concurrently caused real swap pressure at 8GB, so router mode was tested to
confirm it enforces strict one-at-a-time residency rather than trying to
cram more in.

| Request (model asked for) | Resident before | Resident after | Wall time (swap + inference) |
|---|---|---|---|
| Qwen2.5-Coder-32B | (none) | Qwen | 5.5s |
| Llama-3.3-70B | Qwen | **Llama** (Qwen auto-unloaded) | 8.9s |
| DeepSeek-R1-Distill-32B | Llama | **DeepSeek-R1** (Llama auto-unloaded) | 12.6s |
| Qwen2.5-Coder-32B again | DeepSeek-R1 | **Qwen** (DeepSeek-R1 auto-unloaded) | 6.2s |

`GET /v1/models` after each request confirmed exactly one entry `"loaded"`
and the other two `"unloaded"`, matching `--models-max 1`. Swap peaked at
166MB of the container's 512MB swap allocation across the whole rotation —
comparable to (not worse than) the single-model-at-a-time systemd approach
used for the benchmarks. Swap times here (5.5-12.6s per full round-trip,
including model load) were faster than the 40-90s cold-start times observed
earlier in the session when starting fresh systemd units — the OS page
cache already held these GGUF files' bytes from repeated benchmark runs, so
this isn't a like-for-like "cold disk" number; a freshly booted host would
be slower, closer to the systemd-unit cold-start times already on record.

## Memory sizing guidance (ties directly to prior findings)

- **8GB container**: `--models-max 1`. This is what's running now. Matches
  the empirically-confirmed ceiling for one 32B-class Q4_K_M model with
  8192 context without significant swap.
- **32GB container**: `--models-max 2` is a reasonable starting point —
  two 32B-class models were confirmed to coexist comfortably (swap ~32MB)
  during the vulnerability-finding benchmark's dual-server setup.
- Router mode does not reduce the per-model memory footprint. It only
  automates the same load/unload decision this project made by hand via
  `systemctl start`/`stop` all session. Sizing math is unchanged; only the
  mechanism doing the swapping is different.

## When you'd still want separate manual units instead

Router mode is the right default for "one endpoint, pick a model per
request." Separate per-model systemd units (the pattern used for every
benchmark in this project) are still the better fit when:

- You need two specific models resident *simultaneously* on a hard
  guarantee, not best-effort under a concurrency cap.
- You want independent restart/monitoring/logging per model (a crash in one
  model's instance is more clearly isolated with its own unit).
- You're deliberately running a fixed A/B comparison, as every benchmark in
  this project has been so far — controlling exactly which model is up via
  script is simpler than going through a router API to get the same effect.

## Adding an embedding model

Not yet built or benchmarked — this is a design decision recorded ahead of
implementation, from a 2026-07-17 discussion, so the reasoning doesn't need
re-deriving later.

### Candidate models (no retrieval-quality benchmark run yet)

- **Nomic Embed Text v1.5** (137M params, 8192 context, Matryoshka-truncatable
  768→256 dims, Apache 2.0) — default recommendation absent a specific
  requirement.
- **BGE-M3** (568M params, 8192 context, multilingual, supports dense +
  sparse + multi-vector retrieval from one model) — better fit if
  multilingual or hybrid sparse+dense search is ever needed.
- **mxbai-embed-large-v1** (335M params, strong MTEB retrieval scores,
  English-focused) — alternative if pure English retrieval quality is the
  priority over Nomic's context length/license profile.

If/when this gets benchmarked, BEIR or the MTEB retrieval subset are the
standard choices (parallel to how HumanEval/SecurityEval were used for the
code and vulnerability benchmarks — prefer a real published benchmark over
hand-authoring one, where one exists).

### Where it runs: same container, own process, not in the router's pool

Two reasons this isn't "just another model" in `llama-router`'s
`--models-dir`:

1. **GPU passthrough is a container-level cost, model choice is a
   process-level one** (the same principle section 1 above makes for
   generation models). The embedding model would reuse container 9001's
   already-configured `/dev/kfd` passthrough and ROCm/Vulkan install — a
   separate container would just redo that setup for no benefit.
2. **It can't be permanently resident if it shares the router's eviction
   pool.** `--models-max N` evicts on demand across every model pointed at
   by `--models-dir` — an embedding request would compete with generation
   requests for the same slot(s), defeating "always available." To
   guarantee permanence, it needs to be a separate `llama-server
   --embedding` process on its own port, running *alongside*
   `llama-router`, not routed through it.

### CPU vs GPU for the embedding process

On Strix Halo's unified-memory architecture, VRAM is a small fixed
carve-out and nearly everything else is GTT (shared system RAM) regardless
of whether a workload targets CPU or GPU — so, unlike a discrete-GPU box,
running the embedding model on CPU doesn't save memory; the same RAM is
used either way. The actual benefit of CPU-only would be avoiding GPU
compute-queue contention with whatever generation model the router
currently has loaded, since embedding is a cheap single-forward-pass
workload that may not need GPU acceleration to be fast enough. Worth
testing both placements if the generation router's latency under
concurrent embedding traffic matters; not tested yet either way.

## Not yet done

- No Ansible role wraps this yet — the persistent unit file above is a
  manual reference, not automated. A `llamacpp_router` role (parallel to
  the existing `llamacpp_server_bench`) would be the natural next step if
  this becomes the standing deployment rather than a validated pattern.
- `--models-preset` (per-model context size / GPU layers / chat template
  overrides) not tested — every model here shares the same global
  `--ctx-size 8192` / `--n-gpu-layers 999`, which happens to suit all three
  but won't generalize to models with very different context needs.
- `--sleep-idle-seconds` not enabled or tested.
- No authentication (`--api-key`) configured — the router is only bound to
  the container's internal network in this test, but worth flagging before
  this is exposed any wider.
