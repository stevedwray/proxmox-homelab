# Model download scripts — pulled from `pve-framework` before reinstall

`download-llm-models.sh` and `download-comfyui-models.sh` were found only
on the live host (`/root/download-*.sh`), never committed anywhere in this
repo. Pulled back here on 2026-07-20, ahead of the Ubuntu 26 rebuild, so
model provenance survives as tracked history rather than host-local files
that were about to be wiped.

**Not a complete record.** `download-llm-models.sh` covers
Qwen2.5-Coder-32B-Instruct, DeepSeek-R1-Distill-Qwen-32B, and
Llama-3.3-70B-Instruct — it predates and does not include
**Qwen3-Coder-30B-A3B-Instruct-Q4_K_M**, the model actually selected as
the production configuration in
[`findings-plan.md`](../../framework-integration/findings-plan.md). That
model was obtained via the operator's normal workflow instead (`hf
download` on the Garuda desktop, then `rsync` over) — see
[`findings-plan.md`](../../framework-integration/findings-plan.md) for
the exact model/quantization in current use. These scripts document how
the *other* models present in `/storage/models/llm` got there, not the
current default.

Both scripts are plain `wget -c` fetches against HuggingFace URLs
(`bartowski`'s GGUF quants for the LLM set, `Comfy-Org/z_image_turbo`'s
split-file safetensors for the ComfyUI set) — reusable as-is on the
rebuilt host if these particular models are wanted again, with paths
adjusted to wherever `plan.md` §3's `models` LV ends up mounted.
