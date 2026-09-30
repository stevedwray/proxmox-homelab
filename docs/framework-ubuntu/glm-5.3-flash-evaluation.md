# GLM-5.3-Flash: bounded capability test on Framework

Status: **GLM-5.3-Flash is serving on Framework :8080 and ready for
CyberSecEval runs (2026-10-01).** Load, GPU residency, sanity, speed and a
CSE smoke run all pass (§7). This needed one fix not in the original plan: a
metadata rewrite of the Unsloth GGUF (§5a). Qwen3.8-Flash-Next
(`nathanw-llamacpp.service`) and ComfyUI are **stopped** while this runs,
at operator direction.

## TL;DR

Z.ai's GLM-5.3 comes in two sizes. Only the smaller one can run on
Framework (122 GiB unified memory, 112 GiB GTT ceiling):

| | GLM-5.3 | GLM-5.3-Flash |
|---|---|---|
| Params | ~744B total / ~40B active | 320B total / 18B active, text+vision |
| Smallest GGUF | UD-IQ1_S 217 GB | UD-IQ1_S 86.7 GiB |
| Fits Framework | **No** (full model needs the disk-streaming route, see [`colibri-evaluation.md`](./colibri-evaluation.md)) | **Yes, at ~2-bit** |
| llama.cpp | Existing `glm_moe_dsa` arch (GLM-5.2) | New `glm5next` arch, upstream PR #27773, merged 2026-09-30 |
| License | Custom (MIT-like below $10B revenue) | MIT |

This test answers four questions, in order: does Flash **load**, does it
run **fully on the GPU** (Vulkan), is it **fast enough** to be useful, and
how does it **score on CyberSecEval** compared with the current default
(Qwen3.8-Flash-Next).

## 1. Scope

In scope:

- An upstream llama.cpp build at `a4d880fd5` (includes #27773 plus the
  follow-up fix #29745), in a **separate git worktree**
  (`~/llama.cpp-upstream`). The Nathanw fork checkout (`~/llama.cpp`,
  `strix-halo-vulkan` @ `b02cb35`) and its `build-vk` are left alone.
- One quant: `unsloth/GLM-5.3-Flash-GGUF` `UD-IQ2_XXS` (94.9 GiB, 4
  shards), pinned to repo revision `621d456e`, stored at
  `/mnt/nvme2/models-gguf/glm-5.3-flash/`.
- Temporarily stopping `nathanw-llamacpp.service` (Qwen3.8-Flash-Next,
  ~111 GB resident) and the `comfyui` container, then serving GLM on
  **port 8080 with the same API key file**. The CyberSecEval panel's
  `custom` backend can then reach it with no firewall or
  `FRAMEWORK_LLM_API_KEY` changes, and it can never be co-resident with
  Qwen, because only one process can hold the port.
- A CyberSecEval smoke run and a small comparison suite via
  `https://cse-panel.lab.gibbsgreatly.xyz`.

Out of scope:

- Any Ansible role, systemd unit, or other permanent change. GLM runs as a
  `nohup` process under `steve` and is removed at the end.
- Changing `nathanw-llamacpp.service` or its unit file (including the known
  stale ctx-size note).
- The full-size GLM-5.3, multimodal (`mmproj`), and MTP speculative
  decoding.
- Ollama and LM Studio. Neither ships a `glm5next`-capable llama.cpp a day
  after the upstream merge. They are only worth checking again (release
  notes only) if the llama.cpp path fails for an engine-side reason
  (§6).
- `nathanw-llamacpp-embed.service` (port 8085, nomic-embed, <1 GiB) keeps
  running.

## 2. Why this quant

The GTT ceiling is `ttm.pages_limit=29360128` × 4 KiB = **112 GiB**.

| Quant | Size | Headroom under 112 GiB | Decision |
|---|---|---|---|
| UD-IQ1_M | 90.9 GiB | ~21 GiB | Fallback if IQ2_XXS won't fit |
| **UD-IQ2_XXS** | **94.9 GiB** | **~17 GiB** | **Primary** |
| UD-Q2_K_XL | 101.3 GiB | ~10 GiB | Too tight next to host RAM needs (swap already 7.9/9 GiB used at baseline) |
| UD-IQ3_XXS | 112.1 GiB | none | No |

Flash is a hybrid model: 34 KDA linear-attention layers with fixed-size
recurrent state, and only 11 DSA/MLA layers holding a growing KV cache.
Context should therefore cost far less memory than in the dense models
used here before. That is expected, not verified; G2 measures it.

Known risk: Unsloth uploaded these quants on 2026-09-06, **before** the
upstream merge (presumably from a pre-merge branch). If GGUF metadata keys
changed during review, loading fails at G2 with an arch/key error. That
counts as a finding, not something to patch around (§6).

## 3. Pre-state (captured 2026-10-01, read-only)

- `nathanw-llamacpp.service`: active, port 8080, alias
  `qwen3.8-flash-next`, `--ctx-size 131072`, `Restart=on-failure`.
- `nathanw-llamacpp-embed.service`: active, port 8085.
- Docker: `comfyui` (8188), `openwebui`, `searxng`, `cadvisor`,
  `portainer-agent` up; `ollama` exited 13 days ago. `lmstudio.service`
  inactive.
- `free -h`: 114 GiB used / 7.5 GiB free; swap 7.9/9 GiB.
- `/mnt/nvme2`: 1.2 TB free. `sudo -n` works for `steve`.

Consumers that lose the Qwen backend while the test runs: Open WebUI
(:8081), any deep-research or CSE jobs pointed at the default
`framework-llama-server` preset. Check the panel's Status tab for running
jobs before step 3.

## 4. Steps

Run as `steve@framework.gibbsgreatly.xyz`. Working dir for logs:
`~/glm53-flash-test/`.

### Step 1: Download (non-disruptive)

```bash
hf download unsloth/GLM-5.3-Flash-GGUF \
  --revision 621d456e93e926e4b52f85cff5f634358c1828f9 \
  --include "UD-IQ2_XXS/*" \
  --local-dir /mnt/nvme2/models-gguf/glm-5.3-flash
```

Done when all 4 shards are present, with a combined 101,844,951,808 bytes
(9,429,888 + 49,896,298,080 + 49,248,507,840 + 2,690,716,000; each matches
the HF API).

### Step 2: Build upstream llama.cpp (non-disruptive)

```bash
cd ~/llama.cpp
git fetch https://github.com/ggml-org/llama.cpp master:refs/remotes/upstream/master
git worktree add --detach ~/llama.cpp-upstream a4d880fd5
cd ~/llama.cpp-upstream
cmake -B build-vk -DGGML_VULKAN=ON -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF
cmake --build build-vk -j 16 --target llama-server llama-cli llama-bench
```

**G1:** `build-vk/bin/llama-server --version` reports commit `a4d880fd5`.

### Step 3: Free the GPU (disruptive, approved)

```bash
sudo systemctl stop nathanw-llamacpp
docker stop comfyui
free -h                     # expect ~110 GiB+ available
ss -ltn | grep -c ':8080 '  # expect 0
```

Stop if available memory is under 105 GiB. Find what's holding it before
going further. The 2026-09-21 hard reset was a double load.

### Step 4: Load and serve GLM-5.3-Flash on :8080

```bash
cd ~/glm53-flash-test
nohup ~/llama.cpp-upstream/build-vk/bin/llama-server \
  -m /mnt/nvme2/models-gguf/glm-5.3-flash/UD-IQ2_XXS/GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf \
  --alias glm-5.3-flash --host 0.0.0.0 --port 8080 \
  --ctx-size 65536 --n-gpu-layers 999 --jinja \
  --temp 1.0 --top-p 0.95 --min-p 0.01 \
  --metrics --api-key-file /etc/llamacpp/api-key \
  > server.log 2>&1 < /dev/null &
echo $! > server.pid
```

`--ctx-size 65536` matches the value verified necessary for CSE's
`autonomous-uplift`. Sampling follows Z.ai/Unsloth's recommendation.

**G2 (load, GPU residency):**

- `curl -s localhost:8080/health` returns 200.
- `server.log` shows every layer offloaded to `Vulkan0`
  (`offloaded N/N layers`).
- There are no "unsupported op" or CPU fallback warnings. The graph split
  count is recorded; a high count means ops are bouncing to the CPU.
- `free -h` still shows at least 8 GiB available, and nothing new in
  `dmesg` (OOM, amdgpu, GPF).

### Step 5: Sanity and speed

```bash
KEY=$(cat /etc/llamacpp/api-key)
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"glm-5.3-flash","messages":[{"role":"user","content":"What is 17*23? Answer with just the number."}],"max_tokens":4096}' \
  | jq '{content: .choices[0].message.content, reasoning_len: (.choices[0].message.reasoning_content // "" | length), usage, timings}'
```

Then repeat with `"chat_template_kwargs":{"reasoning_effort":"low"}` and
check whether reasoning length actually drops. The template is supposed to
support low/high/max, with max as the default. This matters because CSE
caps every request at 8192 tokens (`cse-lab` `999598b`). A model that
reasons at max effort by default can burn the whole cap in
`reasoning_content` and return empty `content`, the failure mode already
seen with Qwen.

Speed: one ~4k-token prompt (any repo doc) with `max_tokens` 512. Read
`timings.prompt_per_second` and `timings.predicted_per_second`.

**G3:** the answer is correct (391), the reasoning/content split works, and
decode speed is recorded. Anything under ~5 tok/s makes the CSE suite
impractical: run only step 6's smoke test and stop.

### Step 6: CyberSecEval

The panel is at `https://cse-panel.lab.gibbsgreatly.xyz`, "Run tests" tab.
Choose the **custom** backend:

- Base URL: `http://framework.gibbsgreatly.xyz:8080/v1`
- Model: `glm-5.3-flash`
- API key: leave blank (the worker falls back to `FRAMEWORK_LLM_API_KEY`,
  which is the same key file already in use).

1. Smoke test: `mitre-frr`, 1 test case. It must finish with a real scored
   response, not an empty-content error.
2. Comparison suite, default 2 test cases each: `mitre`, `mitre-frr`,
   `prompt-injection`, `interpreter`, `instruct`, `autocomplete`,
   `threat_intel_reasoning`, `malware_analysis`. Add `autonomous-uplift`
   only if G3's speed is at least 10 tok/s, since it is the long agentic
   one.

Compare against the most recent Qwen3.8-Flash-Next results in the panel's
Status tab. Treat 2-case samples as a capability signal, not a score.

### Step 7: Restore (always, including after any failure)

```bash
kill $(cat ~/glm53-flash-test/server.pid); sleep 5
ss -ltn | grep -c ':8080 '     # expect 0
sudo systemctl start nathanw-llamacpp
docker start comfyui
# wait for load, then:
curl -s -H "Authorization: Bearer $(cat /etc/llamacpp/api-key)" localhost:8080/v1/models | jq -r '.data[].id'
# expect: qwen3.8-flash-next
```

The downloaded model and `~/llama.cpp-upstream` stay in place for reruns.
Cleanup: `git -C ~/llama.cpp worktree remove ~/llama.cpp-upstream` and
`rm -r /mnt/nvme2/models-gguf/glm-5.3-flash`.

## 5. Incident during setup (2026-10-01)

A chained `git fetch … && git worktree add … && cd ~/llama.cpp-upstream`
failed at the fetch (a bare short SHA isn't fetchable). The following
`nohup cmake -B build-vk …` still ran, but in the **fork's** directory
(`~/llama.cpp`). It rebuilt the fork's `build-vk` from its own unchanged
source (`git status` clean, `--version` still `b02cb35`) with the same
flags, so the binaries are functionally identical. The running
`nathanw-llamacpp` kept serving (its old binary/libs stay mapped as
`(deleted)` inodes), and `/health` returned 200 throughout. Fixed by
fetching `master` into a named ref and building from an explicit
`cd /home/steve/llama.cpp-upstream || exit 1`.

## 5a. Arch-name mismatch and the metadata rewrite (2026-10-01)

The first load failed: `unknown model architecture: 'glm5next'`. Unsloth's
quants (uploaded 2026-08-29, last touched 2026-09-06) were made with a
pre-merge branch that named the architecture `glm5next`. The merged
upstream code registers it as `glm5-next` (`src/llama-arch.cpp`), and every
hparam key is prefixed with the arch name. No corrected re-upload existed
on 2026-10-01.

At the operator's direction ("focus on getting GLM5 working"), this
overrode the "don't hand-edit GGUF metadata" stop condition below. The
fix:

- Shard 1 is metadata only (72 KVs, 0 tensors). Shards 2–4 hold only
  `split.*` KVs plus tensors, with no arch-prefixed keys.
- Wrote a new shard 1 into `/mnt/nvme2/models-gguf/glm-5.3-flash/UD-IQ2_XXS-glm5-next/`
  with `general.architecture = glm5-next` and the 40 `glm5next.*` keys
  renamed to `glm5-next.*`. The values are copied unchanged, using the
  `GGUFReader` → `GGUFWriter` field-copy pattern from
  `gguf-py/gguf/scripts/gguf_new_metadata.py`.
- Shards 2–4 are **hard links** to the originals, so no extra disk is used.
  The untouched originals stay in `UD-IQ2_XXS/`.

Tensor names matched the merged loader as-is: no missing-tensor errors.
The only load warnings are `blk.45.*` "unused tensor", which is the MTP
(`nextn`) draft layer, expected when not running speculative decoding,
and a tokenizer note that `special_eot_id`/`special_eom_id` aren't in
`special_eog_ids`. Responses still end cleanly (`finish_reason: stop`).

## 6. Stop conditions

| Symptom | Meaning | Action |
|---|---|---|
| Load fails with an unknown arch/key error | GGUF predates the merged format | Record, restore (step 7). Recheck whether Unsloth re-uploads. Don't hand-edit GGUF metadata |
| Loads but ops fall back to the CPU / many graph splits / <2 tok/s | Vulkan lacks kernels for KDA/DSA ops | Record the op names from the log, restore. A HIP build (`-DGGML_HIP=ON`) is the one allowed retry, only if the missing ops are Vulkan-only |
| OOM, amdgpu errors in `dmesg`, SSH sluggish | Memory ceiling | Kill immediately, restore, retry once with UD-IQ1_M and `--ctx-size 32768` |
| Empty `content` on CSE runs | Reasoning exhausted the 8192 cap | Restart the server with `--chat-template-kwargs '{"reasoning_effort":"high"}'` (or `low`), if G3 showed it works |

## 7. Results

| Gate | Result |
|---|---|
| G1 build | **Pass.** `llama-server` 0.5.0-dev build 11309, commit `a4d880fd5`, Vulkan (RADV STRIX_HALO) |
| G2 load / GPU | **Pass after the §5a rewrite.** Healthy in 45–55 s. GTT 96.0 GiB at 64k ctx, 98.6 GiB at 131k ctx, 21 GiB host RAM still available. No `dmesg` errors |
| G3 sanity / speed | **Pass.** `17*23` → `391`, clean content/reasoning split. Decode 16.6–18.8 tok/s. Prefill 148 tok/s on a 4k-token prompt (33 tok/s on tiny prompts) |
| Reasoning effort | **Works.** Same security prompt: `low` 279 tokens, no reasoning; `high` 458 tokens, 843 reasoning chars; `max` (model default) 1813 tokens, 7326 reasoning chars. The server default is now set to `high` via `--chat-template-kwargs` because CSE sends no effort field |
| CSE smoke | **Pass.** `mitre-frr`, 1 case, custom backend, job `46abd249`: `SUCCESS`, real scored response (accept, 0% refusal), ~8 min wall time |
| CSE suite | Not yet run: handed to operator |

### Current serving command (as running)

```bash
setsid nohup ~/llama.cpp-upstream/build-vk/bin/llama-server \
  -m /mnt/nvme2/models-gguf/glm-5.3-flash/UD-IQ2_XXS-glm5-next/GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf \
  --alias glm-5.3-flash --host 0.0.0.0 --port 8080 \
  --ctx-size 131072 --n-gpu-layers 999 --jinja \
  --chat-template-kwargs '{"reasoning_effort":"high"}' \
  --temp 1.0 --top-p 0.95 --min-p 0.01 \
  --metrics --api-key-file /etc/llamacpp/api-key \
  > ~/glm53-flash-test/server.log 2>&1 < /dev/null &
```

`--ctx-size` was raised from the planned 65536 to 131072 so the ~117k-token
`malware_analysis` prompts fit, matching Qwen's setting. Prefill at ~148
tok/s means a prompt that size takes roughly 13+ minutes before the first
token.

### Using it from CyberSecEval

Panel → Run tests → backend **custom**. Base URL
`http://framework.gibbsgreatly.xyz:8080/v1`, model `glm-5.3-flash`, API key
blank. Via the API, `POST /jobs` takes query parameters, for example
`?benchmark=mitre-frr&num_test_cases=1&backend_base_url=...&backend_model=glm-5.3-flash`.

## Sources

- [unsloth/GLM-5.3-Flash-GGUF](https://huggingface.co/unsloth/GLM-5.3-Flash-GGUF)
- [Unsloth: GLM-5.3 How to Run Locally](https://unsloth.ai/docs/models/glm-5.3)
- llama.cpp `649dcb103` "add GLM-5.3-Flash (GLM5-Next) support (#27773)",
  `05af0d2b1` "glm5-next: give dead indexer slots unique scatter rows (#29745)"
- [runaihome: GLM-5.3 open weights, license and GGUF sizes](https://runaihome.com/blog/glm-5-3-open-weights-live-hardware-guide-2026/)
