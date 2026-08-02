# Colibrì: research and fit evaluation

Research only, prompted by the operator hearing about the project.
**No host or repo changes made beyond this document** — nothing has been
installed, downloaded, or containerized yet.

## TL;DR

[Colibrì](https://github.com/JustVugg/colibri) is a pure-C, zero-dependency
inference engine (16.9k GitHub stars as of 2026-07-21, created 2026-07-01 —
new and moving fast) that runs **one specific model**, Z.ai's GLM-5.2
(744B-parameter MoE), on consumer hardware by streaming the routed experts
from disk instead of holding them in RAM/VRAM. It is not a general-purpose
runtime like llama.cpp/Ollama/LM Studio — it's a single-purpose engine built
around one enormous model.

It's a genuinely interesting fit for this host on paper: 128GB unified
memory is exactly the class of box the project targets, and community
members have already benchmarked **this literal hardware model**
(Framework Desktop, Ryzen AI Max+ 395, 128GB) upstream — see Evidence below.
But two things temper that fit:

1. **No working GPU acceleration for this iGPU yet.** AMD/HIP and Vulkan
   backends both exist only as open, unmerged PRs. Every benchmark on this
   hardware class so far, including the ones matching our exact machine, is
   CPU-only.
2. **CPU-only throughput on this hardware is ~1 token/second at best**
   (0.06 tok/s cold, ~1.1 tok/s sustained with a fast NVMe and tuning — see
   Evidence). That rules out interactive chat use. It's realistically an
   "ask something before bed, read the answer in the morning" tier, not a
   fifth backend alongside llama.cpp/Ollama/LM Studio/ComfyUI.

Recommendation: worth a bounded proof-of-concept (Phase 0–3 below), not
worth committing to an Ansible role or platform integration yet. Revisit
GPU acceleration once #339 (HIP) or #418 (Vulkan) lands upstream — see
Evidence, since even the AMD GPU datapoint that exists today is only
marginally faster than CPU-only on the same machine.

## What it is

- **Engine**: pure C, ~1,300 lines, GCC + OpenMP to build, no external
  runtime dependencies. Python is only needed for one-time model conversion
  and an optional API gateway wrapper.
- **Model**: GLM-5.2, 744B MoE, 78 layers, 256 experts/layer, top-8 routing.
  Colibrì keeps the dense parts (attention, shared experts, embeddings —
  ~17B params, int4, ~9.9GB) resident in RAM, and streams the ~370–384GB of
  routed-expert shards from disk on demand, tracking per-token expert usage
  (`.coli_usage`) to pin the hottest experts in RAM over time — it gets
  faster the more it's used, within a session.
- **Pre-converted weights**: available on Hugging Face as
  [`mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp`](https://huggingface.co/mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp)
  (144 shard files, ~384GB total) — avoids needing to run the from-scratch
  converter against the original 756GB release.
- **License**: engine is Apache 2.0; GLM-5.2 weights are released by Z.ai
  under MIT. No licensing blocker.
- **Interfaces**: `coli chat` (interactive), `coli serve` (OpenAI-compatible
  API only), `coli web` (API + web dashboard), `coli plan` (inspect
  VRAM/RAM/disk placement before running), `coli doctor` (read-only
  readiness check), `coli convert` (one-time conversion from raw weights).
  `coli serve`/`coli web` being OpenAI-compatible means it could sit behind
  the same kind of Traefik route as `llm.lab.gibbsgreatly.xyz` if it ever
  graduates past proof-of-concept.

## Evidence: this exact hardware class, already benchmarked upstream

Two community-submitted benchmark issues on the upstream repo are, as far
as I can tell, this literal machine model:

- **[#39 — "Framework Desktop Ryzen AI Max+ 128GB - CPU Only"](https://github.com/JustVugg/colibri/issues/39)**:
  same CPU (Ryzen AI Max+ 395), same 128GB LPDDR5x, Ubuntu 26.04, same
  pre-converted model. Confirms build and run both work cleanly on this
  class of box out of the box (`make`, no special flags).
- **[#124 — "Strix Halo datapoint (Ryzen AI Max+ 395, 128 GB): 0.06 cold to 1.10 tok/s sustained"](https://github.com/JustVugg/colibri/issues/124)**:
  explicitly notes "gfx1151 iGPU unused, CPU path only" — i.e. even this
  most-relevant existing datapoint has no GPU acceleration in the mix.
  Headline numbers:

  | config | tok/s |
  | --- | --- |
  | first run, fully cold | 0.06 |
  | warm, default knobs | 0.23–0.26 |
  | `DIRECT=1 PIPE=1 --topp 0.7`, slower drive | 0.55 |
  | same config, faster NVMe (SK hynix P41) | 0.81–1.24 across repeats |
  | 128-token sustained run, best config | **1.10** (best 32-token run: 1.35) |

  Also flags that **NVMe controller thermals**, not raw bandwidth, were the
  binding constraint on longer runs — the SSD controller climbed from 56°C
  to 84°C (throttle threshold) over a ~2-minute decode run, and back-to-back
  runs on a heat-soaked drive ran ~2× slower than the same config after a
  cooldown pause. Worth planning for if this ever runs for real: expect
  degraded throughput on sustained/repeated runs unless the NVMe has decent
  thermal headroom (heatsink, airflow).

GPU acceleration status (why the above is CPU-only, not a gap in testing):

- **[#339 — AMD GPU support via HIP/ROCm](https://github.com/JustVugg/colibri/issues/339)**
  (open, unmerged as of 2026-07-21): the submitter's own numbers, on an
  RX 9070 XT (discrete RDNA4, not this iGPU): **0.33 tok/s with the GPU path
  vs. 0.22–0.27 tok/s CPU-only on the same machine** — a real but marginal
  gain, because the bottleneck is disk I/O for expert streaming, not
  compute. No gfx1151/Strix Halo datapoint yet even for this branch.
- **[#418 — Vulkan backend](https://github.com/JustVugg/colibri/issues/418)**
  (open, unmerged as of 2026-07-21, successor to the now-closed #84):
  targets any Vulkan 1.2 GPU including iGPUs — this is the one that would
  actually be relevant to gfx1151 — with benchmarks on an RX 9070 (RDNA4)
  showing the Vulkan path beating the project's own HIP path on the same
  card. Still pre-merge.
- Several earlier AMD/GPU issues (#69, #90, #105, #112) are closed/
  superseded by the two above — the project's GPU story is actively in
  flux, not stalled, but nothing merged yet that changes the CPU-only
  conclusion for this host today.

**Takeaway**: don't wait on GPU acceleration to evaluate this — even when
it lands, the project's own numbers suggest disk I/O dominates over
compute, so the CPU-only ~1 tok/s ceiling measured on this exact hardware
class is a reasonable planning baseline, not a stand-in for an eventually-
much-faster number.

## Containerization

Straightforward to containerize for the CPU-only path used today; nothing
about it needs the host's GPU device nodes (`/dev/dri`, `/dev/kfd`) the way
llama.cpp/Ollama/ComfyUI do:

- **Build**: standard multi-stage Dockerfile — `apt install gcc make
  libomp-dev python3`, clone at a **pinned commit** (matches this repo's
  existing llama.cpp convention — the upstream project has no tagged
  stable release yet, just a `v1.0` banner string and frequent
  merges/reverts), `make`.
- **Runtime deps**: none beyond what's in the build stage (pure C, static
  within the image). No CUDA/ROCm libraries needed for the CPU path.
- **Volumes**: model directory (~384GB) needs a **bind mount to real local
  NVMe**, not an overlay/copy-on-write layer or a network filesystem — the
  project's own tuning flags (`DIRECT=1`, `O_DIRECT` reads) are about raw
  block-device random-read latency, which a network mount (this repo's
  NFS/NAS pattern) would undermine. `/storage/models/colibri` on the
  existing `models` LV (ext4, local NVMe) fits this and matches the
  existing `/storage/models/{llm,comfyui}` layout.
- **CPU/memory**: no device passthrough needed; would want most/all host
  cores available (OpenMP) and a generous memory ceiling — see the RAM
  conflict risk below, which is a host-level resource question, not a
  container one.
- **No Docker instructions exist upstream** — this would be a from-scratch
  Dockerfile, same posture as llama.cpp's custom image (`decisions.md`
  Decision 5) rather than reusing a maintained image like ComfyUI's
  `yanwk/comfyui-boot:rocm`.

## Resource conflicts with the existing four services

This is the main operational risk, not the throughput number:

- Host has **~125.8GB total RAM** (`125780MB`, confirmed live on
  `framework.gibbsgreatly.xyz`), of which **~93GB is the GTT ceiling**
  (`ttm.pages_limit`/`page_pool_size`, a ceiling not a reservation — see
  `plan.md` §8) available to GPU workloads, with the remaining ~32GB as the
  deliberate host-side reservation.
- Colibrì's own auto-cap logic in the #39 benchmark log raised its RAM
  budget to a **projected peak of 111.2GB** on this same 128GB class of
  box. That's the CPU-side engine alone — before any GPU workload's GTT
  allocation is added on top, since this is unified memory: GPU-resident
  models and Colibrì's RAM-resident cache draw from the **same physical
  pool**.
- Concretely: if LM Studio or ComfyUI currently holds e.g. 40–80GB of GTT
  (both measured in `plan.md` §9 Phase 5: 41.7GiB and 19.4–81.1GiB
  respectively) at the same time Colibrì tries to grow toward its ~111GB
  peak, the box doesn't have enough real RAM for both — and per the
  existing `ttm.pages_limit` guidance in `plan.md` §8, **the host-OOM
  failure mode this project already hit once (LXC memory-ceiling OOM,
  the whole reason for the bare-metal migration) is worse than a clean
  GPU allocation failure.**
- Practical implication: Colibrì would need the same kind of exclusivity
  discipline the host already has for GPU memory
  (`switch-to-comfyui`/`switch-to-llm`, `plan.md` §9 Phase 5) — but for
  **host RAM**, not GPU VRAM/GTT. Realistically: unload LM Studio/Ollama
  models and confirm ComfyUI is idle before running Colibrì, or cap
  Colibrì's own RAM budget (`RAM_GB=` env var, seen in the #39 log) well
  below its auto-raised default so it can coexist with a modest GPU
  workload. This needs to be validated live (Phase 3 below), not assumed.

## Storage impact

- `/storage` (the `models` LV, ~1.7TB, ext4) currently holds ~258GB
  (238GB LLM + 20GB ComfyUI per `plan.md` §0), leaving roughly ~1.4TB free
  — comfortably enough for the ~384GB pre-converted GLM-5.2 shard set, with
  headroom to spare. (Exact live free space not re-verified for this
  document — read-only `df -h /storage` on `framework.gibbsgreatly.xyz`
  would confirm; that host is a listed production node per
  `terraform/PRODUCTION_NODES`, so even a read-only check goes through the
  normal `with-secrets-prod-framework` read-only path, not ad hoc SSH.)
- Downloading straight from Hugging Face onto `/storage/models/colibri`
  (rather than round-tripping through the NAS first) is simplest for a
  proof-of-concept; decide whether it also gets NAS-backed once/if it
  becomes a kept service, matching the existing LLM/ComfyUI model backup
  pattern (`plan.md` §4).
- Given the NVMe-thermal finding in #124, worth checking this host's NVMe
  has adequate cooling before a long sustained run — not currently
  characterized either way.

## Recommendation

Treat this as a **bounded, opt-in proof-of-concept**, not a fifth
production backend:

- It's a real fit for the *hardware class* (128GB unified memory is
  exactly the sweet spot the project targets) and there's already
  community evidence it builds and runs on this literal machine model.
- It is **not** a fit for the *interactive-use pattern* the other four
  services serve — ~1 tok/s sustained means a short answer takes minutes.
  The realistic use case is closer to this repo's own overnight-benchmark
  culture (`overnight-llm-benchmark.md`, `comfyui-benchmarks.md`): queue a
  hard question before bed, read a frontier-class (744B) answer in the
  morning, rather than a live chat/coding backend.
- GPU acceleration for this exact iGPU doesn't exist yet upstream (open,
  unmerged PRs), and even the closest existing AMD GPU datapoint suggests
  the win would be marginal (disk I/O bound, not compute bound) — don't
  gate the decision on waiting for it, and don't expect it to change the
  ~1 tok/s planning number much when it does land.
- The main real risk is host RAM contention with the other three GPU
  services sharing the same unified-memory pool, not throughput or
  containerization difficulty — that needs to be tested live, not assumed
  away.

## Proposed test plan

**Phase 0 — Preflight (read-only, no host changes)**
- Confirm current `/storage` free space and live total/free RAM on
  `framework.gibbsgreatly.xyz` via the read-only production path
  (`with-secrets-prod-framework`, `df`/`free` — both read-only commands).
- Decide and pin the upstream commit to build against (matches the
  llama.cpp precedent — this project has no tagged stable release).
- Check whether the upstream repo ships a small/synthetic test model for
  its own CI, to validate a build without downloading the full 384GB set
  first.

**Phase 1 — Build & containerize (no model download yet)**
- Write a Dockerfile: pinned commit, `gcc`/`make`/`libomp-dev`/`python3`,
  `make` build, `coli` as entrypoint. No GPU device passthrough.
- Build and smoke-test `coli doctor`/`coli plan` against an empty/no-model
  state to confirm the image itself is sound before committing to the
  large download.

**Phase 2 — Model acquisition**
- Download `mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp` (~384GB) to
  `/storage/models/colibri`, verify shard count/sizes against the upstream
  README's documented values.

**Phase 3 — Live benchmark on this host, with resource-conflict testing**
- Run `coli run` with the same methodology as upstream issue #124
  (`DIRECT=1 PIPE=1`, greedy decoding) as a sanity check against that
  issue's numbers (0.06 cold / ~1.1 tok/s sustained) — a large deviation
  either way would flag a local misconfiguration worth chasing before
  going further.
- **Explicitly test the RAM-conflict scenario**: run Colibrì while LM
  Studio and/or ComfyUI have models loaded, watch `free -h` and
  `mem_info_gtt_total`, and confirm whether the host stays stable or needs
  Colibrì's `RAM_GB` capped / the other services unloaded first. This is
  the go/no-go gate for Phase 4, not the throughput number.
- Check NVMe thermals across a longer sustained run.

**Phase 4 — Decide operational posture (contingent on Phase 3)**
- If RAM contention is manageable: wire up as an opt-in, manually-started
  container (own `docker compose` stack, `restart: no` — deliberately not
  `unless-stopped` like the other four, since this shouldn't compete for
  memory by default) exposing `coli serve`'s OpenAI-compatible API on a
  dedicated port, in the same spirit as the "overnight oracle" framing
  above rather than an always-on backend.
- If RAM contention isn't manageable without manual choreography every
  time: document that finding and stop — don't force platform integration
  onto something that needs babysitting the other four services don't.

**Phase 5 — Platform wiring (only if Phase 4 says go)**
- Traefik route (e.g. `colibri.lab.gibbsgreatly.xyz`) behind Authentik
  forwardAuth, matching the existing `llm.lab.gibbsgreatly.xyz` pattern —
  low priority given how expensive each request is; a bookmarked local
  port is probably sufficient for the actual use pattern.

## Open questions

- Does the upstream project ship any way to validate a build without the
  full 384GB download (small test model, unit tests)? Not confirmed here.
- What's the actual current free space on `/storage`? Stated above as
  "comfortably enough" from the last recorded model-size figures in
  `plan.md`, not re-verified live for this document.
- Would capping Colibrì's `RAM_GB` env var below its auto-raised default
  meaningfully hurt its already-slow throughput, or is the auto-raise
  mostly about caching hot experts (nice-to-have) rather than correctness?
  Not established from the issues reviewed here — worth checking upstream
  docs/`coli plan` output during Phase 1.

## Sources

- [JustVugg/colibri](https://github.com/JustVugg/colibri) — main repo,
  README
- [Issue #39 — Framework Desktop Ryzen AI Max+ 128GB, CPU only](https://github.com/JustVugg/colibri/issues/39)
- [Issue #124 — Strix Halo datapoint, 0.06–1.10 tok/s](https://github.com/JustVugg/colibri/issues/124)
- [Issue #339 — AMD GPU support via HIP/ROCm (open)](https://github.com/JustVugg/colibri/issues/339)
- [Issue #418 — Vulkan backend (open)](https://github.com/JustVugg/colibri/issues/418)
- [mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp on Hugging Face](https://huggingface.co/mateogrgic/GLM-5.2-colibri-int4-with-int8-mtp)
- [Tom's Hardware coverage](https://www.tomshardware.com/tech-industry/artificial-intelligence/colibri-proof-of-concept-gains-frontier-level-1-5-tb-ai-model-novel-approach-runs-on-only-25gb-of-ram-and-shows-promise-for-local-ai-setups)
