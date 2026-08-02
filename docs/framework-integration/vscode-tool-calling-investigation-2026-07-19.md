# VSCode Agentic Tool-Calling Investigation — 2026-07-19

## Status: unresolved, handed off for a fresh critical pass

This document exists so a session with no memory of the original
conversation can pick this up, verify or challenge every claim in it, and
continue. It separates **confirmed facts** (with exact commands/results)
from **hypotheses** (clearly labeled, not yet independently verified).
Where a claim is a hypothesis, do not treat it as settled — re-derive it.

## 1. Goal

The operator has invested in the Framework Desktop specifically to run
local models, not to fall back to cloud-hosted Copilot models. The goal
was to find a model served by `llm-gpu-stack` that works reliably for
**real agentic coding work in VSCode** (file creation, tool use via
Continue and/or GitHub Copilot Chat's BYOK custom-endpoint feature) —
not just a model that answers questions correctly in isolation.

## 2. Current state (as of end of this session)

- **`chatLanguageModels.json`** (`~/.config/Code/User/chatLanguageModels.json`,
  Copilot BYOK config) and **`~/.continue/config.yaml`** both point at
  `Llama-3.3-70B-Instruct-Q4_K_M` — the only model that has shown 100%
  reliable tool-calling across every direct-API test run today.
- **This is not a confirmed-good end state.** Llama-3.3-70B-Q4_K_M has
  twice shown a degenerate repetition-loop failure *specifically when
  used through the real Copilot client* (not reproduced via direct API
  testing — see §6, the actual unresolved loose end).
- `llm-gpu-stack` now serves 12 models total (up from the 8 at the start
  of this specific investigation). Full list and status in §5.
- Server-side sampling changed: DRY sampling enabled globally
  (`--dry-multiplier 0.8 --dry-base 1.75 --dry-allowed-length 3
  --dry-penalty-last-n -1`) — tested, did **not** fix the repetition
  issue on the one model it was tested against (Devstral Small 2).
  Whether it affects the Llama-3.3-70B/Copilot repetition case is
  **untested** — that capture was never completed (§6).
- `--jinja` was temporarily disabled, tested against two models, found
  to make no difference either way, and reverted to enabled (the
  original, working state). Full detail in §7.

## 3. Background / infrastructure context (predates this specific investigation)

- `llm-gpu-stack`: `llama-server` router mode (`--models-dir`,
  `--models-max 1`, one model loaded at a time, swapped on demand),
  native HIP/ROCm build on `gfx1151` (Strix Halo unified memory), on
  container `llm-gpu-stack` (192.168.50.10) on the `pve-framework` host.
  Ansible role: `terraform/lxc/ansible/roles/llm_gpu_stack/`.
- `--parallel 1` (single decode slot): added earlier this session
  (Decision 10) after confirming concurrent multi-slot decode corrupts
  shared GPU state on this HIP/ROCm build — reproduced by firing
  simultaneous requests at the same model. This is load-bearing; do not
  revert without re-confirming the corruption is actually fixed upstream
  first.
- `--ctx-size`: raised 8192 → 32768 → 65536 earlier this session
  (Decision 10 follow-up, Decision 12) to fix a confirmed
  `truncated = 1` mid-reasoning failure on Qwen3.6 and to give VS Code
  Copilot's own client-side context-budget bookkeeping headroom. See
  `decisions.md` Decision 10's follow-up for the full root-cause chain
  (initially misdiagnosed as cross-session context contamination, ruled
  out via a systematic marker-plant/probe test, actual cause found in
  `llama-router`'s own request logs).
- Model download/staging pattern: large files downloaded via `hf` CLI
  (`HF_XET_HIGH_PERFORMANCE=1`) on a separate workstation ("Garuda")
  with real RAM headroom, then `rsync -avP --partial` to
  `/storage/models/llm/` on the `pve-framework` host directly (bypasses
  both `llm-gpu-stack`'s 8GB container memory ceiling, which Xet's
  buffering can OOM against on 20GB+ files, and avoids installing
  tooling on production infra). Small files (<20GB) are safe to `wget`
  directly inside the container.
- Router reload after staging a new file:
  `GET /v1/models?reload=1` (with the `LLM_GPU_STACK_API_KEY` bearer
  token) — the router does **not** auto-discover new files.

## 4. Test methodology used throughout this investigation

Two distinct test types were used. Neither substitutes for the other —
this distinction matters for §6.

**A. Direct API tool-calling test** (used for every model in §5's table):
```python
tools = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of a file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path to read"}},
            "required": ["path"]
        }
    }
}]
# POST https://llm.lab.gibbsgreatly.xyz/v1/chat/completions
{
    "model": "<model-id>",
    "messages": [{"role": "user", "content": "Read the file at /etc/hostname and tell me what it says."}],
    "tools": tools,
    "tool_choice": "auto",
    "max_tokens": 300,
    "temperature": 0.3
}
```
Run 4-5 times per model (temperature 0.3, not deterministic — single-run
results are not reliable, this was learned the hard way earlier in the
session). A "pass" means `message.tool_calls` is populated with a
correctly-structured call to `read_file`. A "fail" is either: raw/
malformed JSON dumped into `content` instead of the `tool_calls` field,
a hallucinated claim that no tool is available, degenerate/repetitive
output, or the model directly answering (correctly-worded refusal or,
worse, a confabulated wrong answer) without calling the tool at all.

**B. Speed test** (separate, no tools, longer generation):
```python
{
    "model": "<model-id>",
    "messages": [{"role": "user", "content": "Write a quicksort implementation in Python with detailed comments."}],
    "max_tokens": 600,
    "temperature": 0.3
}
```
`approx_tps = usage.completion_tokens / wall_clock_elapsed_seconds`. This
is a rough, single-sample measurement, not an average over multiple runs
— treat the numbers in §5 as indicative, not precise benchmarks.

**C. Real-client capture** (used once successfully, see Decision 12; the
one attempt to reuse it for the Llama-3.3-70B repetition mystery was
never completed — see §6): a local logging reverse-proxy
(`http.server`-based, stdlib only, script preserved at
`/tmp/claude-1000/.../scratchpad/logging_proxy.py` in the session that
wrote it — **not currently in the repo, worth relocating into the repo
if this technique will be reused**) sits between the VSCode client and
`llm-gpu-stack`, logs the raw request body verbatim before forwarding it
unmodified. The client's `apiBase`/`url` is temporarily pointed at
`http://localhost:8899/v1/...` instead of the real endpoint. This is the
only technique that has definitively distinguished "the client sent a
malformed/unexpected request" from "the model/server produced a bad
response to a normal request" in this investigation.

## 5. Models tested — results

All tests used the methodology in §4A/§4B against `llm-gpu-stack`
directly (`https://llm.lab.gibbsgreatly.xyz/v1/chat/completions`), not
through any VSCode client, unless noted otherwise.

| Model | Tool-calling (n trials) | Speed (approx t/s) | Verdict |
|---|---|---|---|
| **Llama-3.3-70B-Instruct-Q4_K_M** | **Pass, every trial across multiple separate test sessions today** (structured `tool_calls`, correct arguments) | ~50 t/s (from earlier `journalctl` capture) | Only consistently reliable model via direct API. **Not confirmed reliable via actual Copilot client** — see §6 |
| Llama-3.3-70B-Instruct-Q3_K_M | Pass (4/4) | **5.6 t/s** — dramatically slower than the Q4 quant despite being a smaller file | Reliable but counter-intuitively much slower; likely a quant-type/HIP-kernel support gap for this specific K-quant on this backend, **not independently verified**, just the working hypothesis. Not recommended |
| Qwen2.5-Coder-32B-Instruct-Q4_K_M | Fail — dumps raw/malformed JSON into `content` instead of populating `tool_calls` | ~8.7-10.4 t/s (from original pre-reinstall bake-off benchmark, not re-measured this session) | Confirmed broken earlier this session (Decision 10). Disabled in OpenWebUI, removed from VSCode configs |
| Qwen3.6-35B-A3B-UD-Q4_K_M | Mixed — has hallucinated that no file-creation tool existed despite one being documented in its own system prompt (via Continue); ctx-size truncation issue (fixed by the ctx-size raise) also affected it | Not cleanly measured (reasoning-model token budget confounds simple t/s) | Confirmed unreliable earlier this session (Decision 12). Disabled in OpenWebUI, removed from VSCode configs |
| Devstral-Small-2-24B-Instruct-2512-Q5_K_M | Fail — degenerate repetition loop ("...that is not a good that is not a good...") | **~5.9 t/s**, dramatically slow for a 24B model | Likely incomplete `llama.cpp` support for its newer Ministral-3/Scalable-Softmax architecture — **corroborated by upstream docs**: Unsloth's own Devstral Small 2 guide states "Current llama.cpp implementations may not be accurate." DRY sampling (added specifically hoping to fix this) did **not** resolve it — retested after deploying DRY, same failure pattern, different specific wording. Not recommended |
| Devstral-Small-2507-Q5_K_M ("Devstral 1.1", built on the older, established Mistral-Small-3.1 base — deliberately chosen as an architecture-only comparison against Devstral Small 2) | **Fail, 0/9 across two separate test batches** (5 trials with `--jinja`, 4 without) — never invokes the tool, instead confabulates a plausible-but-wrong direct answer every time (e.g. claims `/etc/hostname` contains `"localhost"` or shows fabricated content in a code block) | Fast: 1.1-9.7s per response | Consistently fails at tool invocation specifically, despite Mistral's own marketing claiming Devstral "excels at tool-calling." Tested explicitly to rule out `--jinja` as the cause (§7) — made no difference |
| Hermes-3-Llama-3.1-8B-Q5_K_M (NousResearch, specifically fine-tuned by them for reliable function-calling, built on the Llama 3.1 base) | **Fail, 0/5** — but differently: honestly declines ("I'm unable to directly access or read files from your system") rather than confabulating, never populates `tool_calls` | 36.3 t/s — faster than the broken Q3 quant, but still slower than the 14x-larger Llama-3.3-70B-Q4_K_M (also counter-intuitive, not explained) | Fails at the same specific step (tool invocation) as everything except Llama-3.3-70B, despite being explicitly marketed/fine-tuned for exactly this |

**Not tested for tool-calling in this investigation** (staged for other
purposes): `Llama-3.2-3B-Instruct-Q4_K_M` (OpenWebUI utility-model role
only), `Command-R-35B-Dark-Horror-V2-D_AU-Q4_k_s`,
`L3.1-MOE-6X8B-Dark-RS-Dantes-Peak-HRR-R1-Uncen-36B-Q4_K_M-imat`,
`L3.2-8X4B-MOE-V2-Dark-Champion-Inst-21B-uncen-ablit-D_AU-Q4_k_m` (chat/
creative-writing models, not agentic use), `DeepSeek-R1-Distill-Qwen-32B-Q4_K_M`
(kept for the separate, already-validated vuln-review use case from the
original bake-off benchmark, not re-tested here).

## 6. Unresolved loose end — the actual real-world failure was never root-caused

**This is the most important open item.** The original, real-world
trigger for this entire investigation was: Llama-3.3-70B, used through
the *actual* Copilot client (not direct API), produced a degenerate
repetition loop **twice**, on different occasions, with different
specific repeated text each time. Every attempt to reproduce this via
direct API testing — default params, `temperature=0`, replaying the
literal captured request from a similar Continue incident, concurrent
requests, sequential requests — has failed to reproduce it.

The diagnostic logging proxy (§4C) was specifically restarted and the
Copilot config re-pointed at it (`http://localhost:8899/v1/chat/completions`)
*for the explicit purpose* of capturing the real request that triggers
this. **That capture was never completed** — the investigation got
redirected into testing Devstral Small 2 (which reproduced a
superficially similar repetition symptom via a completely unrelated
direct API test) and the DRY sampling fix, then into trying alternative
models entirely.

**Verified at time of writing (end of this session)**: the proxy process
is still running (`ps aux` confirms `python3 logging_proxy.py` alive),
and `chatLanguageModels.json`'s Llama-3.3-70B entry's `url` field is
still `http://localhost:8899/v1/chat/completions`, not the real
endpoint. **This is actually the correct, ready-to-go state** — the
setup for the capture is already in place. A fresh session (or the
operator directly) just needs to reload the VS Code window, retry the
prompt that originally triggered the repetition loop through Copilot
with Llama 3.3 70B selected, let it fail, then read
`/tmp/claude-1000/-home-steve-git-proxmox-homelab/acc7d237-2872-418d-ac76-d20de8adf53a/scratchpad/proxy_requests.log`
for the captured request — no setup work remains, only the actual retry
and read. **Before trusting the model for daily use again, remember to
point the `url` back at `https://llm.lab.gibbsgreatly.xyz/v1/chat/completions`**
once the capture is done, and stop the proxy process.

**What should happen to actually resolve this**: retry the exact prompt
that triggered it through Copilot with the proxy capturing, then read
`proxy_requests.log` for the literal request body Copilot sent —
sampling parameters, full system prompt, message history — and compare
it against what's been tested directly. This is the same technique that
conclusively resolved two earlier mysteries this session (the "no files
created" false lead, per Decision 12) and should be trusted over further
speculation.

**Open question this raises**: is Llama-3.3-70B's apparent reliability
actually specific to *how I've been testing it* (small system prompt, a
single `read_file` tool, no real file/workspace context) rather than
genuinely reliable under Copilot's real, much larger system prompt and
full tool roster? This has not been ruled out. The "6 models, 5 failed
at the same step" pattern in §8 was drawn entirely from my own simplified
direct-API tests — it does not account for the two confirmed Copilot-
specific failures on the one model that otherwise looked clean.

## 7. `--jinja` toggle test (ruled out as the variable)

Hypothesis tested: that non-Llama models fail because `llama-server`'s
`--jinja` flag (renders each GGUF's own embedded chat template) doesn't
correctly handle those models' tool-schema conventions, and that the
generic built-in template (used when `--jinja` is absent) might do
better, or that `--jinja`'s presence might be *helping* Llama-3.3-70B
specifically in a way that doesn't generalize.

Method: `llm_gpu_stack_use_jinja` was added as a new Ansible role
variable (`terraform/lxc/ansible/roles/llm_gpu_stack/defaults/main.yml`,
templated into `templates/llama-router.service.j2`), temporarily set to
`false`, deployed via `scripts/provision.sh --stack llm-gpu-stack`,
tested against both Devstral-Small-2507 (4 trials) and Llama-3.3-70B (1
trial), then reverted to `true` (original working value) and redeployed.

**Result: no difference either way.** Devstral-Small-2507 failed
identically with and without `--jinja` (0/4 without, 0/5 with — same
confabulation pattern). Llama-3.3-70B succeeded identically with and
without `--jinja`. This rules out `--jinja` as *the* explanatory
variable, though it does not rule out that `llama-server`'s tools-schema
rendering is broken for other templates via some *other* mechanism
(built-in template selection logic, grammar generation from the tools
schema, etc. — not investigated).

## 8. Working hypothesis (NOT independently verified — treat with real skepticism)

Pattern observed: 5 of 6 tested models fail at the identical specific
step (never populate `message.tool_calls`), each with different
surface symptoms, while exactly one model (Llama-3.3-70B) succeeds
consistently across every direct-API trial. This was not explained by
`--jinja` (§7), quant type alone (Q3 vs Q4 changed speed dramatically
but not reliability), or model size (an 8B, a 24B/two variants, a 32B,
and a 35B all failed; only a 70B succeeded).

**Hypothesis**: something in how `llama-server` converts the OpenAI
`tools` API parameter into a grammar/prompt structure for constrained
decoding works correctly for Llama-family chat templates specifically,
and is broken or incomplete for others (Hermes's ChatML `<tools>` XML
convention, Qwen's `<tool_call>` wrapping, Mistral/Devstral's own
format). This has **not** been directly verified — nobody has inspected
the actual rendered prompt/grammar sent to a failing model to confirm
tool definitions are even reaching it correctly, or checked whether
`llama-server` has model-family-specific tool-parser logic that's simply
missing an entry for these families.

**How to actually verify this** (not yet done): `llama-server` has
verbose/debug logging options (`--verbose` or similar — check current
`--help` output, not verified this session) that may show the exact
rendered prompt including how the `tools` array got serialized into it.
Comparing that rendered output between a passing (Llama) and failing
(Hermes, say) request would directly confirm or refute this hypothesis
instead of leaving it as pattern-matching speculation.

## 9. Recommended next steps for whoever picks this up

In rough priority order:

1. **Finish the §6 capture** — verified ready to go, no setup needed:
   the proxy is running and the config already points at it. Retry the
   original failing prompt through the real Copilot client with the
   proxy active, read the captured request, and determine whether
   Llama-3.3-70B's Copilot-specific failure is explained by something
   about Copilot's real request shape that none of today's direct-API
   tests replicated.
2. **Verify or refute the §8 hypothesis directly** by inspecting
   `llama-server`'s actual rendered prompt/tool-grammar for a passing
   vs. failing model, rather than continuing to infer it from black-box
   pattern-matching.
3. If §8 is confirmed, the fix is at the infrastructure level (a
   `llama-server` version/config/flag issue affecting tool-schema
   rendering for non-Llama templates), not more model-shopping — worth
   checking `llama-server --help` for any tool-call-parser-selection
   flag, and checking whether upstream `llama.cpp` has model-specific
   tool-parser support that needs an explicit flag per family (this
   session found and confirmed such flags don't exist as simple CLI
   options for at least the models tried, but did not exhaustively check
   `--help` output for this specific purpose).
4. Only after 1-3: decide between accepting Llama-3.3-70B's speed,
   trying yet another model, or considering whether a genuinely
   different serving stack (not `llama-server` router mode) is warranted
   for the subset of models that fail here.

## 10. Config file locations (current state, for reference)

- `~/.continue/config.yaml` — Continue's model config, currently
  `Llama-3.3-70B-Instruct-Q4_K_M`. Real cleanup identified but not done
  in `~/.continue/` — see `decisions.md` Decision 12's "Not yet done"
  section (stale 1.7GB index cache, global rather than workspace-scoped
  rules leaking into unrelated projects).
- `~/.config/Code/User/chatLanguageModels.json` — Copilot BYOK config
  (separate file from `settings.json`, a common trap — see Decision 12).
  Currently `Llama-3.3-70B-Instruct-Q4_K_M`; **verify its `url` field
  before trusting it** (§6).
- `~/.config/Code/User/settings.json` — `chat.byokUtilityModelDefault:
  "copilot"` (routes Copilot's own background/utility calls to GitHub's
  hosted models, off `llm-gpu-stack` entirely — see Decision 12).
- `terraform/lxc/ansible/roles/llm_gpu_stack/defaults/main.yml` — all
  current server-side defaults (`ctx-size`, `parallel`, DRY sampling
  params, `use_jinja`), each with an inline comment explaining why.
