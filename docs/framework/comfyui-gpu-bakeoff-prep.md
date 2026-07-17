# ComfyUI GPU Bake-off — Prep

## Status: complete — see [comfyui-image-video-gen-findings.md](comfyui-image-video-gen-findings.md)

Operator decision (2026-07-17): before committing real integration effort
to ComfyUI as a Phase 3+ candidate in `docs/framework-integration/plan.md`,
run a hardware-validation bake-off for it on this specific GPU (Strix
Halo / Radeon 8060S, gfx1151), mirroring the rigor already applied to
`llama.cpp` in this same directory. This doc scoped that bake-off; the
operator then ran it directly (same day) and it succeeded — image and
video generation both confirmed working with real GPU compute (verified
via `rocm-smi`, not just log text), running in its own container (9002,
`comfyui-gpu`). See the findings doc for the full result: model survey,
two real upstream bugs found and fixed, and a genuine host-wide OOM
incident that was diagnosed and fixed (with lessons that generalize well
beyond ComfyUI specifically). This prep doc is kept as-is below for the
scoping reasoning that shaped the bake-off; treat the findings doc as the
authoritative result.

## Why this needs its own bake-off, not just "reuse the LLM findings"

The existing `docs/framework/` research (OS bake-off,
`proxmox-strix-halo-setup-notes.md`, the runtime matrix) proved Vulkan and
ROCm/HIP both work well for `llama.cpp` on this hardware. None of that
transfers automatically to ComfyUI:

- `llama.cpp` is a purpose-built C++ inference engine with its own minimal
  Vulkan and HIP backends (GGUF-quantized weights, hand-written kernels).
  ComfyUI's actual compute stack is **PyTorch + ROCm** — a much larger,
  more general dependency chain (PyTorch's ROCm build, `torchvision`,
  often `xformers`-equivalent attention kernels, sometimes ONNX Runtime).
  A GPU/driver combination that works cleanly for one does not guarantee
  the other.
- Strix Halo (`gfx1151`) is a very new GPU architecture. ROCm's official
  supported-GPU list has historically lagged behind the newest consumer/
  APU silicon by one or more releases, often requiring
  `HSA_OVERRIDE_GFX_VERSION` to make the GPU present itself as an older,
  officially-supported architecture (a known, somewhat fragile workaround
  pattern, not a real fix). Whether current ROCm + current PyTorch's ROCm
  wheels actually recognize `gfx1151` (natively or via override) is
  unverified here.
- Image/video-gen tooling in general has historically been far more
  NVIDIA/CUDA-centric than LLM inference — the AMD path is less trodden,
  with more community-reported friction (VRAM/GTT allocation quirks,
  attention-kernel compatibility, `xformers` often being CUDA-only with
  ROCm alternatives lagging in performance or missing features entirely).
- The `proxmox-strix-halo-setup-notes.md` Vulkan-batch-size crash (a real
  GPU hang on this hardware under large-context, high-batch workloads) is
  a hardware/driver-level finding, not an application-level one — worth
  keeping in mind since image/video-gen workloads are also
  compute-and-memory-heavy in ways that could plausibly trigger similar
  driver stress, though the actual failure mode would likely differ
  (PyTorch/ROCm crash signatures, not `ttm`/Vulkan ones).

## Candidate paths to test

1. **PyTorch + ROCm/HIP**, inside an Ubuntu-based LXC (matching the
   already-proven pattern: Debian's Mesa/ROCm story is worse across the
   board per the setup notes — don't re-litigate that, just reuse the
   conclusion). This is ComfyUI's primary, best-supported backend on AMD
   today.
2. **ROCm with `HSA_OVERRIDE_GFX_VERSION`**, if native `gfx1151`
   recognition turns out to be incomplete — test as a fallback, not the
   default assumption.
3. Vulkan-backed alternatives are a secondary/exploratory track, not the
   primary candidate — ComfyUI's own Vulkan support (via community
   forks/extensions) is far less mature than its ROCm path, unlike the
   llama.cpp case where Vulkan was a first-class, well-performing option.
   Worth a quick look only if the ROCm path proves genuinely broken.

## Deployment shape questions to answer alongside the backend choice

- LXC (privileged, `/dev/kfd`+`/dev/dri` passthrough per the existing
  recipe) vs. bare-metal vs. VM — default expectation is LXC, matching
  the proven `llm-gpu-stack` pattern, but confirm ComfyUI's own dependency
  footprint (Python version, CUDA/ROCm toolkit versions, custom node
  ecosystem) doesn't fight the same container image conventions used for
  `llm-gpu-stack`.
- Does ComfyUI share the GPU-passthrough container with `llm-gpu-stack`,
  or get its own? Revisit Decision 5's reasoning (GPU passthrough setup
  cost is container-level, not per-workload) — likely argues for sharing
  one GPU-passthrough LXC across every GPU-bound service on this box,
  same as the router-mode doc argues for one container serving multiple
  LLM models. But ComfyUI's dependency stack (PyTorch/ROCm) is heavier
  and less isolated than llama.cpp's, so confirm there's no meaningful
  conflict (Python/CUDA-vs-HIP env conflicts, VRAM contention under
  concurrent LLM+image-gen load) before assuming co-location is free.
- Memory sizing: image/video-gen VRAM footprints (especially video models
  — Stable Video Diffusion, Mochi, Hunyuan Video, Wan2.1 workflows) can be
  substantial and very different in shape from LLM KV-cache sizing. Needs
  its own sizing pass against the unified-memory GTT ceiling
  (`docs/framework/proxmox-strix-halo-setup-notes.md` §6), not an assumed
  reuse of the LLM sizing numbers.

## Suggested scope for the actual bake-off (when run)

Mirroring `docs/framework/project-brief.md`'s goals list, adapted:

1. Hardware enablement — does ROCm/PyTorch actually detect and use the
   GPU on this hardware (native or via override)?
2. Backend build/runtime success — does ComfyUI actually start and serve
   its web UI with GPU acceleration confirmed active (not silently
   falling back to CPU — this exact failure mode was caught and fixed for
   Ollama during the LLM runtime matrix; watch for it here too)?
3. A minimal image-generation smoke test (one SD1.5 or SDXL workflow,
   confirmed GPU-utilized via `rocm-smi` sampling during generation, same
   verification discipline as the LLM matrix — log-text claims alone
   aren't sufficient).
4. A minimal video-generation smoke test, if scope allows — likely a
   separate, heavier follow-up given the VRAM/compute difference from
   image generation.
5. Stability under a longer/repeated-generation loop (parallel to the
   LLM matrix's stability-loop phase) — image/video-gen workloads keep
   the GPU pinned at high utilization for much longer per-job than LLM
   token generation, worth specifically checking for thermal/driver
   issues over a sustained run.
6. Management-friction/operational-simplicity assessment, same criteria
   as the OS bake-off (this is meant to inform "is this worth running
   long-term on this box," not just "can it technically run once").

## Not yet decided

- Which specific ComfyUI distribution/install method (official repo +
  manual venv, a maintained Docker image, or a community AMD-specific
  fork/build) — survey options as part of the bake-off itself rather than
  picking now.
- Whether video generation is in scope for the first pass or a deliberate
  follow-up phase once image generation is proven.
- Whether this becomes its own GPU-passthrough LXC or shares one with
  `llm-gpu-stack` (see deployment-shape questions above) — likely
  resolved by what the bake-off finds about resource contention, not
  decided a priori.
