# ComfyUI Image/Video Generation — Setup, Models, and Memory Findings

Companion to the LLM-side work in [model-quality-and-vuln-bench-2026-07-17.md](model-quality-and-vuln-bench-2026-07-17.md)
and [llamacpp-router-mode-deployment.md](llamacpp-router-mode-deployment.md). Covers a
second workload class on the same Framework Desktop hardware: PyTorch/ROCm-based
image and video diffusion via ComfyUI, run in its own container (9002,
`comfyui-gpu`) deliberately separate from the llama.cpp container (9001) —
see "Why a separate container" in the router-mode doc for the reasoning
(heavier/more version-sensitive dependency stack, larger custom-node attack
surface, long GPU-saturating jobs).

## Status: working, with real memory-management lessons learned

Both image and video generation are confirmed working end-to-end with real
GPU compute (verified via `rocm-smi` utilization, not just log text) on
gfx1151. Getting there required fixing two real upstream bugs and, later,
diagnosing and fixing a genuine host-wide OOM incident. Both are documented
below in full since they're exactly the kind of thing that would otherwise
need re-discovering.

## 1. Environment setup

Container 9002 (`comfyui-gpu`): Ubuntu 26.04, same GPU-passthrough pattern
as container 9001 (`/dev/kfd` + `/dev/dri`, `lxc.cgroup2.devices.allow`) —
see `roles/proxmox_lxc_native` for the Ansible version of this pattern;
9002 was built the same way but ad hoc (not yet wrapped in a role — see
"Not yet done").

- **ROCm 7.1.1** from Ubuntu's own apt repos (`rocm-dev`, `rocm-smi`) —
  no custom AMD repo needed, unlike earlier llama.cpp work.
- **PyTorch**: installed via AMD's own `gfx1151`-specific pip index, not
  PyPI:
  ```
  pip install --index-url https://repo.amd.com/rocm/whl/gfx1151/ \
    "torch==2.9.1+rocm7.13.0" "torchvision==0.26.0+rocm7.13.0"
  ```
  This wheel bundles its **own** self-contained ROCm SDK (`rocm-sdk-core`,
  `rocm-sdk-libraries-gfx1151`, ~1GB combined) independent of the system
  apt ROCm install — the version numbers don't need to match apt's
  `rocm-dev` (7.1.1) and shouldn't be expected to.
  torchaudio needed a separate, slightly different version
  (`torchaudio==2.9.0+rocm7.13.0` — no `2.9.1` build exists for this index).
- Verified with a real matmul on `cuda:0` (ROCm exposes itself through
  PyTorch's CUDA-compatible API) — result checked against the expected
  value for a 4096×4096 uniform-random product, not just "did it error."
- ComfyUI itself: standard `git clone` of `comfyanonymous/ComfyUI`, venv-installed
  requirements with `torch`/`torchvision`/`torchaudio` lines stripped from
  `requirements.txt` first (otherwise pip pulls vanilla PyPI wheels and
  clobbers the ROCm build).

## 2. Bugs found and fixed

1. **`RuntimeError: operator torchvision::nms does not exist`** — a real,
   currently-open upstream bug ([ROCm/TheRock#3134](https://github.com/ROCm/TheRock/issues/3134),
   also reported generically at [pytorch/vision#9085](https://github.com/pytorch/vision/issues/9085)).
   Root cause: this specific torchvision build's compiled extension exposes
   **zero** custom ops (`torchvision.extension._has_ops()` returns `False`),
   and `torchvision/_meta_registrations.py` has exactly one `nms` registration
   that calls `@torch.library.register_fake(...)` directly instead of going
   through the file's own safe `register_meta()` helper (which every other
   registration in the same file uses, and which checks `_has_ops()` first).
   Fixed by patching that one registration to use the same guard the rest
   of the file already uses. No official fix existed at the time of writing.
2. **`ModuleNotFoundError: No module named 'torchaudio'`** — `comfy/sd.py`
   unconditionally imports `comfy/ldm/lightricks/vae/audio_vae.py` (LTX-Video's
   audio-VAE support) even though nothing we run touches audio. Fixed by
   installing the matching-enough torchaudio wheel rather than trying to
   patch around the import.

## 3. Model survey — what's realistic on this hardware

Backend picture mirrors the llama.cpp bake-off almost exactly: **ROCm 7.1.1+
now has real gfx1151 support** (AMD's own official
[ComfyUI + Z-Image Turbo playbook](https://developer.amd.com/playbooks/comfyui-image-gen/)
targets it explicitly), but at least one independent report described an
earlier ROCm experience as unstable ("constant GPU hangs") and used
**Vulkan instead, via [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)**
(a llama.cpp-sibling GGML project, `-DSD_VULKAN=ON`, bypasses ROCm/PyTorch
entirely) — not tested in this round, but a real, cheap-to-try alternative
given how much of the existing GPU-passthrough/Vulkan toolchain in container
9001 would carry over directly.

Ready-made community toolkits exist for this exact hardware and were used
as reference rather than building from scratch:
[kyuz0/amd-strix-halo-comfyui-toolboxes](https://github.com/kyuz0/amd-strix-halo-comfyui-toolboxes)
(Podman toolbox, documents Qwen-Image/Flux/HunyuanVideo/Wan 2.2) and
smarttechlabs' equivalent.

**Image models considered**: Flux.1[dev] (12B, best prompt adherence/text
rendering, 12-24GB), SDXL (3.5B, largest LoRA ecosystem, 6-8GB), Qwen-Image
(20B, best in-image text), **Z-Image Turbo** (6B, S3-DiT architecture,
Alibaba Tongyi Lab, Nov 2025) — chosen first for its combination of small
size, a dedicated AMD playbook naming gfx1151 explicitly, and a published
report of someone running it on this exact hardware family.

**Video models considered**: Wan 2.1 I2V 480p 14B (older, heavier, needs
`CLIPVisionLoader`), LTX-2 (19B checkpoint + 12B Gemma3 text encoder,
heaviest), **Wan 2.2 TI2V 5B** (smallest, unified text+image-to-video),
**Wan 2.2 I2V 14B** (dual high-noise/low-noise MoE experts + a 4-step
"Lightning" LoRA distillation) — both Wan 2.2 variants tested and compared
below.

### Finding real workflows: docs embed them as images, not text

Every public Z-Image-Turbo/Wan-2.2 tutorial page embeds its actual node
graph as a screenshot or downloadable file, not as readable text — asking
a page-summarizer for "the exact sampler settings" reliably comes back
empty. The real, tested workflows are shipped as JSON inside the
`comfyui-workflow-templates` pip package (already a ComfyUI dependency):
`site-packages/comfyui_workflow_templates_json/templates/*.json`. These use
ComfyUI's newer "subgraph" UI feature, which isn't directly postable to the
`/prompt` API — each template had to be manually flattened (subgraph inner
nodes re-wired as top-level API nodes) before submission. Model download
URLs are embedded in each template's `MarkdownNote` widget text.

## 4. Image generation results

Both used the flattened Z-Image Turbo template: `UNETLoader` (`z_image_turbo_bf16.safetensors`),
`CLIPLoader` (`qwen_3_4b.safetensors`, type `lumina2` — **not** `qwen_image`,
despite the text encoder being a Qwen model), `VAELoader` (`ae.safetensors`),
`ModelSamplingAuraFlow` shift=3, `KSampler` 8 steps/cfg=1/`res_multistep`/`simple`.

- "Mini PC on a wooden workbench, glowing RGB fan" — 1024×1024, ~34s,
  GPU 84-100% utilization confirmed via `rocm-smi` during the run.
- "Crimson-armored medieval knight, oversized greatsword" — same settings,
  succeeded cleanly, used as the source image for the video tests below.

## 5. Video generation results

### Knight: brandishing the greatsword (image-to-video)

| | Wan 2.2 TI2V 5B | Wan 2.2 I2V 14B (dual-expert + 4-step LoRA) |
|---|---|---|
| Settings | 1280×704, 121 frames, 24fps, 20 steps, cfg=5, `uni_pc`/`simple`, `ModelSamplingSD3` shift=8 | 640×640, 49 frames (after an 81-frame OOM — see §6), 16fps, 4 steps (2+2 split across experts), cfg=1, `euler`/`simple`, shift=5 |
| Result | Succeeded, but the knight's **helmet disappears mid-clip** revealing an unrequested face — a real identity-drift weakness of the smaller/faster model | Succeeded (296.5s), **helmet and armor stay fully consistent** across the whole clip, and the sword motion matches "raise overhead and brandish" much more closely |

### Mini PC: camera pan + RGB lighting cycling

| | Wan 2.2 TI2V 5B | Wan 2.2 I2V 14B |
|---|---|---|
| Resolution / frames / fps | 1280×704 / 49 / 24fps | 640×640 / 49 / 16fps |
| Sampling | 20 steps, no distillation | 4 steps (2+2), Lightning LoRA |
| **Duration (execution_start→success)** | **502.5s** | **313.1s** |
| Peak container memory | ~5.6GB | ~22.8GB steady-state (see §6 for why the raw "peak" number needs a caveat) |
| Reliability this round | 2/2 clean | 1 success / 3 crashes before the memory fixes in §6, then clean after |

Both produced real, dynamic RGB cycling (purple→blue→green on the 5B run,
a full rainbow sweep on the 14B run) with the case geometry held together
well — a much easier subject for identity consistency than a human figure.
The 14B run also added a hallucinated hand opening the side panel, not
requested but a coherent extrapolation of "revealing the open side panel."

**Speed note**: the 14B model is faster than the 5B model despite being
larger, on both tests. The 4-step Lightning LoRA distillation (4 total
sampling steps vs the 5B's 20 full steps) matters more for wall-clock time
than raw parameter count.

## 6. Memory findings — the important part

### 6a. Real memory usage vs. resolution (isolated, controlled test)

Same model (Wan 2.2 I2V 14B dual-expert), same frame count (49), same
prompt/source image, resolution varied 480²→640²→768²:

| Resolution | Pixels | Duration | Peak `anon` (true working-set memory) |
|---|---|---|---|
| 480×480 | 230,400 | 169.7s | ~37.2 GiB |
| 640×640 | 409,600 | 313.1s | ~38.5 GiB |
| 768×768 | 589,824 | 859.8s | ~37.3 GiB |

**Memory is essentially flat across this whole range.** The working set is
dominated by the fixed cost of loading both 14B experts (~28GB) plus the
text encoder (~6.7GB) — roughly 35GB before a single frame is generated.
The resolution-dependent piece (latents, attention activations, VAE decode
buffers) is a small increment on top of that fixed cost.

**Time scales steeply, and faster than pixel count predicts.** 480→640 is
a 1.78x pixel increase for a 1.84x time increase (roughly proportional),
but 480→768 is a 2.56x pixel increase for a **5.07x** time increase —
consistent with the well-known quadratic cost of self-attention as the
number of latent tokens grows.

**Practical implication**: on this model, resolution is a *time* lever, not
a *memory* lever. If you're memory-constrained, changing resolution won't
help — the fixed model-loading cost dominates regardless. If you're
time-constrained, resolution matters a lot, and costs compound faster than
naive pixel-count scaling would suggest.

### 6b. `anon` vs `file` — why raw cgroup "peak" numbers can mislead

`memory.current`/`memory.peak` in cgroup v2 count **both** true working
memory (`anon`) and page cache (`file` — bytes cached from reading the
~35GB of model files off disk, which varies with how warm the OS disk
cache happens to be between runs and has nothing to do with the actual
generation parameters). Two runs with identical `anon` can report quite
different raw "peak" values depending on disk-cache warmth. **`anon` from
`/sys/fs/cgroup/<service>/memory.stat` is the number to trust for sizing
decisions**, not the raw peak/current figures.

### 6c. The OOM incident: from host-wide collateral damage to safe containment

A real operational crisis, worth preserving in full because the fix
generalizes to anything memory-heavy sharing this host:

1. First 81-frame/14B attempt: crashed. `dmesg` showed
   `constraint=CONSTRAINT_NONE, global_oom` — a genuine **host-wide**
   physical OOM, even though the container's own 48GB cgroup ceiling was
   never exceeded (anon-rss was only ~33.5GB at the moment of the kill).
   Root cause: on Strix Halo's unified memory architecture, GPU-visible
   (GTT) memory and regular host RAM draw from the same physical pool —
   total real demand (host-side anon + GPU/GTT-backed weights/activations)
   can exceed physical RAM well before any single container's own
   cgroup ceiling registers a problem.
2. Reduced to 49 frames: succeeded cleanly.
3. Immediately re-running a **different** model (5B) without restarting
   ComfyUI first: crashed again — leftover partially-unloaded memory from
   the previous model ("Unloaded partially: 858MB freed, 486MB remains
   loaded...") stacked with the new model's requirements.
4. Restarted cleanly, retried the *same* 49-frame/14B settings that had
   worked before: **crashed again anyway** — this time the host-wide OOM
   killed an entirely unrelated process, the llama.cpp router in container
   9001, as collateral damage (`task_memcg=/lxc/9001/ns/system.slice/llama-router.service`
   in the `dmesg` output).

**Root diagnosis**: container 9002's memory ceiling (48GB) was loose enough
relative to what the workload actually needed that the container could
push toward genuine host-wide exhaustion before its own cgroup ever
intervened — so failures escalated to killing random unrelated host
processes instead of being contained to the one offending container.

**Fix, in order**:
1. Stopped container 9001 entirely (removed a variable, freed its memory
   unconditionally).
2. Right-sized container 9002's ceiling empirically: 48GB → 32GB (too
   tight — job needed slightly more, but critically, this confirmed the
   fix: the OOM this time showed `constraint=CONSTRAINT_MEMCG,
   oom_memcg=/lxc/9002` — properly **contained**, zero collateral damage,
   host completely unaffected) → 40GB (sufficient, job completed cleanly).
3. Added two ComfyUI launch flags: `--vram-headroom 6` (keep 6GB
   deliberately unused as safety margin) and `--disable-smart-memory`
   (more aggressive offloading between different models/requests).

**Important nuance on `--disable-smart-memory`**: its usual benefit (moving
model weights from VRAM to regular RAM to free VRAM for something else) is
a **no-op on unified memory** — there's no separate pool to move data
into, since VRAM *is* system RAM here. Confirmed directly: a model stayed
fully resident in the container's memory even after its job completed,
flag enabled. The flag's real value on this hardware is preventing
*multiple different* models from accumulating residue across separate
requests (item 3 above), not freeing memory within a single job.

**Takeaway that generalizes beyond this specific crash**: a cgroup memory
ceiling is a cap, not a reservation, and setting it too loosely relative to
real usage doesn't make things safer — it just moves the failure from
"this one process gets killed" to "the kernel starts killing things at
random, potentially in a completely different container." Size ceilings
close to real observed need (`anon`, not raw peak) rather than generously
loose, specifically *because* a tighter ceiling fails more predictably.

## 7. Command reference (as currently run, ad hoc — not yet a systemd unit or Ansible role)

```
/opt/comfyui-venv/bin/python3 main.py --listen 0.0.0.0 --port 8188 \
  --vram-headroom 6 --disable-smart-memory
```

Container 9002 memory ceiling: 40GB (`pct set 9002 --memory 40960`) as the
empirically-validated minimum for the 640×640/49-frame Wan 2.2 14B I2V
workload; bump further only if testing larger frame counts/resolutions,
and prefer restarting the container cleanly between different-model runs
over trusting in-process model switching.

## 8. Not yet done

- No systemd unit or Ansible role wraps the ComfyUI launch yet (ad hoc
  `systemd-run` throughout this work, mirroring how the llama.cpp router
  started before being written up as a reusable pattern).
- Vulkan/stable-diffusion.cpp path not tested as an alternative to
  ROCm/PyTorch, despite being flagged as a real option during research.
- SDXL, Flux, Qwen-Image, HunyuanVideo, LTX-2 not yet tried — Z-Image
  Turbo and Wan 2.2 were chosen specifically for being small/well-validated
  starting points, not because they're necessarily the best fit long-term.
- The dual-container coexistence problem (this container vs. the
  llama.cpp router in container 9001) has a design written up separately —
  see [dual-workload-gateway-design.md](dual-workload-gateway-design.md).
