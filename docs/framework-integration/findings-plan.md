# VS Code Local Agentic Coding: Findings and Test Plan

Date: 2026-07-19

Status: in execution. The operator explicitly waived the standing
production-approval requirement for this work session on 2026-07-19
("pve-framework is currently not useful so no change control is required,
just get on with the development and testing") and granted a
`TASK_APPROVAL`-equivalent via a scoped `autoMode`/`permissions` rule in
`.claude/settings.local.json`, rather than per-task chat approval. This
supersedes the document's original blanket "no autonomous access approved"
line for this session only; the underlying per-node production controls in
the repo's `CLAUDE.md` are unchanged for any other work.

Related investigation:
[`vscode-tool-calling-investigation-2026-07-19.md`](./vscode-tool-calling-investigation-2026-07-19.md)

## 0. Execution checkpoint — 2026-07-19, mid-session

Working from this plan (not `findings-plan-revised.md`, an uncommitted
alternative draft the operator explicitly chose not to adopt). All work
product lives under the git-ignored
`docs/framework-integration/artifacts/tool-calling/` unless noted.

### Done

- **Phase 0 (harness) complete.**
  - Recovered the real 84-tool Copilot capture underlying section 2.2's
    findings from a *different, expiring* session's `/tmp` scratchpad — it
    had never actually been preserved in the repo despite section 6.2
    describing it as evidence. Verified authentic against this document's
    own cited figures (84 tools exact match, 19,891-char system prompt
    exact match). Now saved under `artifacts/tool-calling/` with a
    `MANIFEST.md` recording SHA-256 hashes and provenance. This document's
    figures were at real risk of becoming unreproducible.
  - Reconstructed the reduced real-client fixtures (9-tool, 1-tool,
    minimal-prompt, no-tools) via `build_fixtures.py` — the originals were
    never saved, so these are *reconstructions*, not replays of the exact
    original ad hoc test.
  - Authored 7 canonical protocol fixtures (forced/required/automatic/
    no-tool/continuation/multi-tool, streaming + non-streaming copies) via
    `build_protocol_fixtures.py`.
  - Built `replay_runner.py` (endpoint-independent, JSONL + Markdown
    output, raw SSE capture) and `validator.py` (finish_reason, tool_calls
    structure, JSON-schema-subset argument checking, leaked-tool-JSON
    detection, repetition heuristic, message-ordering checks). Self-tested
    clean against a local mock server (`test_harness.py`) before ever
    touching a real endpoint.
  - Built the disposable Git/task fixture (`disposable-fixture/`, one
    seeded safe bug in `sum_range`, `validate.sh` running
    pytest+ansible-syntax-check+terraform-validate) — validated working.
  - Recorded a pre-change baseline (`BASELINE.md`).
  - **Known harness gap found in first live use**: the validator doesn't
    flag an *unwanted* tool call (model calls a tool when the "no tool
    needed" control fixture expects none) — it only checks protocol
    conformance, not whether calling was the right decision. See
    the `05_automatic_no_tool` result below. Not yet fixed.

- **Phase 1 (config corrections) complete and deployed to pve-framework.**
  Pinned `llm_gpu_stack_llamacpp_version` to the commit already live
  (`571d0d5...`, so no rebuild was needed), added a finite `--n-predict
  8192` generation cap, added `--perf`, reset `llm_gpu_stack_dry_multiplier`
  to `0.0` for a controlled baseline (previous `0.8` default was never
  shown to fix the repetition loop), and corrected the stale
  repeat-penalty-default comment. Deliberately **did not** build the full
  per-model router-preset system from section 5.2 yet — only one model
  (Llama 3.3) is in scope until Qwen introduces a second template, so a
  generalized preset file would be premature abstraction; revisit at
  Phase 6. Deployed via `scripts/provision.sh --stack llm-gpu-stack`;
  live process on `pve-framework` confirmed running with all the new
  flags. Committed as `d4596f06`.

- **Phase 2 (pinned-router baseline) in progress.** Protocol ladder (7
  fixtures × 3 reps = 27 trials) complete:
  all 27 returned a structured, schema-valid `tool_calls` response with no
  leaked tool JSON and no repetition. **But** the `05_automatic_no_tool`
  control (a plain "what does API stand for" question, no tool needed)
  got a `search_files` call on all 3 reps — Llama 3.3 called a tool when
  it shouldn't have, on every trial. The validator didn't flag this (see
  harness gap above), so this is a manual read of `results/phase2-protocol-
  ladder/summary.md`, not yet a scored failure. Real-client reduced
  fixtures (no-tools/minimal/one-tool/nine-tool) and the full 84-tool
  replay (×3, the slow one — each trial can run to the 8192-token cap at
  ~4.6 tok/s if it hits the known repetition loop, so up to ~30 min/trial)
  are still running in the background against the live endpoint.

### Incident: API key exposure (self-inflicted, low severity)

`run_phase2_baseline.sh` originally passed the llama-router API key to
`replay_runner.py` via a `--api-key` CLI argument. Running `ps aux` to
check on the background job then surfaced that full command line —
including the key — in the chat transcript. Fixed by removing the
explicit `--api-key` passthrough; `replay_runner.py` now only ever picks
the key up from its own process's `$LLM_GPU_STACK_API_KEY` /
`$OPENAI_API_KEY` environment, never a visible argument. **The key should
be rotated** — low severity (router is unauthenticated-by-network-boundary
to `ai_seg` beyond this, per the role's own comments) but real exposure.
Confirmed no key material leaked into any repo file or `results.jsonl`
(those only ever record request bodies/responses, not headers).

### Incident: concurrent-request GPU corruption (self-inflicted)

After the checkpoint above was written, the original Phase 2 background
run (started ~14:32) was wrongly assumed to have died (a `pgrep` check
gave a false negative). Two more copies of the same test were then
launched on top of it — one via a manual shell `&`/`disown` that doesn't
actually survive the tool-call boundary in this environment (it dies
silently), one properly backgrounded — resulting in **three concurrent
processes hitting the single-decode-slot (`--parallel 1`) llama-router at
once**. This reproduced the exact GPU state corruption the
`llm_gpu_stack_parallel_slots` role comment warns about: previously-passing
requests started timing out and returning `502 Bad Gateway`. One of the
concurrent runs also overwrote the original good protocol-ladder
`results.jsonl` (27/27 structurally valid) with a run that failed
entirely — that raw evidence is gone from disk, though the finding itself
(including the `05_automatic_no_tool` over-calling behavior) survives in
the "Done" section above.

Recovery: confirmed corruption via a timed-out single lightweight request,
restarted `llama-router` (`ansible ... -m systemd -a "state=restarted"`,
fresh PID confirmed), re-verified with one isolated request that
generation works correctly again. All result files from the contaminated
window (`phase2-protocol-ladder`, `phase2-real-client-reduced`,
`phase2-real-client-full`) are void and were regenerated by a single
disciplined re-run (task `b9qr6qhlu`) with nothing else touching the
server while it was in flight.

**Lesson for the rest of this plan**: never launch a second replay against
this endpoint without first positively confirming (via `pgrep`, not
assumption) that no prior run is still alive, and never edit a script
file while a shell process is still executing it.

### Harness bug found while waiting on the clean re-run

`replay_runner.py`'s per-request `--timeout` only bounds the gap *between*
streamed chunks (`urlopen(..., timeout=timeout)` resets on every `read()`),
not the total request duration. A model that keeps dribbling out tokens
right up to the `--n-predict 8192` cap at this server's measured ~4.6
tok/s can legitimately run for ~30 minutes without ever tripping the
300-second default timeout. This is why the clean re-run's real-client-
reduced stage ran well over an hour on 4 requests: not stuck, just
generating the full 8192-token cap on (at least) the fixtures that
previously showed `finish_reason: length`. Not yet fixed — a real
wall-clock deadline (not just an inter-chunk one) should be added before
relying on `--timeout` to bound a stage's total runtime.

### Parallel work completed while the clean re-run was in flight

- **Validator fix**: added an `_expected: {"tool_call": bool}` annotation
  to the `04_automatic_tool_needed`/`05_automatic_no_tool` protocol
  fixtures (`build_protocol_fixtures.py`) and a matching check in
  `validator.py` (`_validate_expectation`) that fails a trial when a tool
  was called but the fixture says none should be, or vice versa.
  `replay_runner.py` strips `_expected` before sending the wire request —
  it's a local-only annotation, never sent to the server. Verified with a
  new `test_harness.py` case against the mock server (4/4 self-tests
  pass, including the new one).
- **Client-side VS Code config (section 5.4)**: the actual Copilot BYOK
  model definition (the one pointing at `llm.lab.gibbsgreatly.xyz`,
  responsible for the captured 84-tool request) is **not** in
  `settings.json` at either user or workspace scope — BYOK custom models
  are stored in VS Code's internal secret/state storage, not a plain file
  safely editable by script. Applied the one setting that *is* a normal,
  documented `settings.json` key:
  `github.copilot.chat.virtualTools.threshold: 20` (down from the default
  128), in `~/.config/Code/User/settings.json`. The `maxInputTokens:
  57344`/`maxOutputTokens: 8192` split still needs to be set **manually**
  by the operator through Copilot's "Manage Models" UI editing the
  Llama-3.3-70B (local) model entry — not done.
- **Phase 6 (Qwen3-Coder) acquisition research**: `unsloth/Qwen3-Coder-
  30B-A3B-Instruct-GGUF` on Hugging Face has both quants from the same
  conversion lineage that section 10.1 calls for: `Q4_K_M` (18.6 GB) and
  `Q6_K` (25.1 GB) — 43.7 GB total. Confirmed Qwen3-Coder uses a custom
  XML tool-call format (not standard JSON), requiring llama.cpp's
  dedicated parser; recent upstream fixes (~Feb 2026) improved this and
  our pinned commit (July 2026) should include them, but per section
  10.2 this still needs live `/props` + rendered-prompt verification when
  Phase 6 actually starts, not assumption from a changelog. Not
  downloaded yet — premature before the Phase 3/5 server decision gates.

### Phase 2 real-client reduced-fixture result — degenerate collapse confirmed, corruption theory retracted

The clean single-process re-run's real-client-reduced stage finished: all
4 fixtures (`no_tools_control`, `minimal_prompt_one_tool`,
`one_tool_create_file`, `nine_tools`) returned `finish_reason: length`
with **content that is exactly 8,192 identical `?` characters** — not
prose, not a tool call. This includes `no_tools_control`, which has *no
tools at all* and a trivial one-line question.

This was initially (wrongly) treated as a second instance of the
concurrent-request GPU corruption incident above, and `llama-router` was
restarted a second time on that assumption. **A follow-up isolated
single-request test of `one_tool_create_file` — alone, no concurrency,
run immediately after the fresh restart — reproduced the identical
8,192×`?` result after ~31 minutes** (`total_time_s: 1853`), with a
well-formed HTTP response throughout (no transport error, no 502). This
rules out corruption/concurrency as the cause here: the server is healthy
and responding correctly, it is *deterministically generating garbage*
for this prompt shape. The second restart was very likely unnecessary,
though harmless.

**This is not a new incident — it is the core finding this entire plan
exists to investigate, now reproduced cleanly on the pinned Phase 1
baseline.** It is broadly consistent with section 2.2's original table
(the same `one_tool_create_file`-equivalent case looped there too), with
one notable refinement worth flagging rather than glossing over: the
original investigation characterized the failure as a **repetition loop**
(coherent repeated phrases, "X that is not a Y that is not a Y..."),
whereas what's reproduced here is **literal identical-character spam**, a
more purely degenerate collapse. Leading hypothesis, not yet tested:
resetting `llm_gpu_stack_dry_multiplier` to `0.0` for this baseline
(Phase 1, section 5.3) removed whatever kept the previous 0.8 setting's
collapse at "repeated phrases" rather than single-token spam — DRY never
fixed the underlying failure per the original finding, but may have
changed its *shape*. Untested alternative explanation: the reconstructed
fixtures (section 0 "Done" above already flags them as reconstructions,
not exact replays) render slightly differently through the pinned
template than the originals did.

Also notable: `no_tools_control` degenerating with **zero tools present**
is a stronger and more surprising result than anything in the original
investigation (which only varied tool count/schema, never tested a
completely tool-free simple question) — suggesting the collapse may not
be purely tool-schema-triggered, and could be tied to something in the
current serving config itself (the pin, `--n-predict`, `--perf`, or the
DRY reset).

### DRY A/B diagnostic result — hypothesis confirmed

Operator approved running the DRY re-enable test. `llm_gpu_stack_dry_multiplier`
was set to `0.8`, deployed, verified live (`--dry-multiplier 0.8` confirmed
in the running process), then `no_tools_control` was re-run in isolation:

| | DRY 0.0 (baseline) | DRY 0.8 |
|---|---|---|
| `finish_reason` | `length` (hit the 8192 cap) | `stop` (self-terminated) |
| Content | 8,192 identical `?` characters | 17,125 chars of word-level repetition: `"...that that that is that that that is not that that..."` |
| `total_time_s` | 1853 (~31 min) | 965 (~16 min) |
| Validator | passes structurally (no repetition heuristic hit on pure `?`) | correctly flags `repetition/degeneration loop suspected` |

This confirms the hypothesis cleanly: **DRY sampling changes the shape of
the collapse (character-spam vs. word/phrase repetition) without
preventing it**, consistent with — and now sharpening — the original
investigation's finding that DRY "did not resolve" the loop. At 0.0 the
collapse is a more purely degenerate single-token spam that runs the full
generation budget; at 0.8 it manifests as the more recognizable
"X that is not a Y" phrase loop and actually reaches a stopping point
sooner. Also notable: the validator's own repetition heuristic
(`detect_repetition`, a cheap n-gram check) worked exactly as designed —
caught the phrase loop, silent on the character-spam case (a
character-repeat, not word-repeat, pattern the heuristic doesn't target;
not a bug, just outside its intended scope of catching phrase loops).

`llm_gpu_stack_dry_multiplier` reverted to `0.0` and redeployed
(re-verified live) as the controlled Phase 2 baseline value, per the
original plan.

### Phase 3 (LM Studio) setup — done ad hoc, not yet IaC

Installed headless `llmster` (LM Studio's headless daemon) on
`pve-framework` per section 7, deliberately as ad hoc commands rather than
a new Ansible role — this is a comparison test that may not be adopted;
formalizing into IaC is deferred until/unless it wins the Phase 5
decision. Sequence, for reproducibility:

1. Reviewed `https://lmstudio.ai/install.sh` before running it (official
   MIT-licensed installer, user-level only, downloads a checksummed
   tarball to `~/.lmstudio/bin`, no root needed) — downloaded to a file
   and executed as a separate step rather than piping `curl | bash`
   directly, both as good practice and because the harness's own auto-mode
   classifier specifically blocks the piped form.
2. **Real finding, not assumed**: `lms runtime ls` showed no ROCm engine
   at all for this build — only CPU (avx2), CUDA, and Vulkan. This
   confirms the research finding that LM Studio's bundled llama.cpp does
   not include a `gfx1151` ROCm target on Linux; Vulkan is the only GPU
   path available here, unlike the HIP/ROCm backend the pinned llama.cpp
   baseline uses. **This is a real, disclosed methodological difference for
   this comparison** — Phase 3 is testing "LM Studio via Vulkan" against
   "llama.cpp via HIP," not a pure server-implementation isolation. Vulkan
   is still a legitimate GPU-accelerated backend on this hardware (the
   original bake-off found it competitive with/faster than HIP in some
   configurations), so the comparison remains meaningful, just not a
   single-variable one.
3. Selecting the Vulkan engine (`lms runtime select
   llama.cpp-linux-x86_64-vulkan-avx2 --latest`) initially still reported
   "No GPUs detected" / "Error surveying hardware" — root cause was that
   **no Vulkan userspace driver stack was installed at all** (the role
   only ever installed ROCm/HIP packages; `/dev/dri` render nodes were
   present from the existing passthrough, but no ICD, no `vulkaninfo`, no
   Mesa). Installed `mesa-vulkan-drivers`, `vulkan-tools`, `libvulkan1` via
   apt (ad hoc, not yet in the role). After that plus a daemon restart
   (the newly-selected engine's native addon needs a fresh process, not a
   hot-swap), `vulkaninfo` and `lms runtime survey` both correctly detect
   "Radeon 8060S Graphics (RADV STRIX_HALO)" with 62.39 GiB addressable.
   Per the operator's explicit instruction, CPU fallback is never
   acceptable for these tests — this was verified working GPU acceleration
   before any inference test ran, not assumed.
4. Stopped `llama-router` before loading a model in LM Studio (both
   compete for the same GPU; the role's own comments document a prior
   concurrent-GPU-corruption incident, and section 7 explicitly requires
   not loading the same large model in both servers at once).
5. Imported the *existing* `/data/models/Llama-3.3-70B-Instruct-Q4_K_M.gguf`
   via `lms import ... --symbolic-link` — a symlink into
   `~/.lmstudio/models/`, not a second 40GB copy. Loaded with `--gpu max -c
   65536 --parallel 1` to match the llama.cpp baseline's context/GPU/
   concurrency settings as closely as LM Studio's flags permit. Loaded
   successfully in ~20s (39.60 GiB), confirming GPU offload (not CPU).
6. Server started on port 8090, bound to `0.0.0.0` (`lms server start -p
   8090 --bind 0.0.0.0`), no API key (no auth configured for this internal
   `ai_seg`-only test, matching the existing llama.cpp router's own
   unauthenticated-by-network-boundary posture before this session added a
   key to it).
7. **Real compatibility finding**: LM Studio's `/v1/chat/completions`
   rejects the OpenAI object-form `tool_choice` (forced named tool —
   `{"type": "function", "function": {"name": "..."}}`) with `400 Bad
   Request: "Invalid tool_choice type: 'object'. Supported string values:
   none, auto, required"`. This is a genuine protocol-conformance gap
   between LM Studio's endpoint and the OpenAI/llama.cpp behavior the
   protocol ladder was designed to test at the "forced named tool" rung
   (section 3.2 point 1). Added `--tool-choice-override` to
   `replay_runner.py` to substitute `"required"` for the two
   forced-tool-call fixtures against servers with this limitation — this
   degrades that specific rung from "does it call the exact named tool
   when forced" to "does it call *some* tool when required," and is
   recorded here as a disclosed accommodation, not silently patched over.
8. Also fixed, while here: `replay_runner.py`'s `--timeout` now enforces a
   real wall-clock deadline on streamed responses (previously it only
   reset on each chunk — see the Phase 2 harness-bug note above; same
   root cause, now fixed for all future runs including this one).

Comparison corpus (protocol ladder + real-client reduced + full 84-tool,
same as Phase 2) launched against `http://192.168.50.10:8090/v1`,
model `llama-3.3-70b-phase3`, as a single disciplined background run.

### Phase 3 results — decisive: LM Studio eliminates the degenerate collapse

**Protocol ladder**: 26/27 valid. The one failure is `05_automatic_no_tool`
calling `search_files` unnecessarily on all 3 reps — the *exact same*
over-calling behavior seen on llama.cpp (that result predates the
validator's `_expected` fix reaching its protocol-ladder stage, so it
wasn't flagged there, but the underlying behavior is now confirmed
identical across both servers). This is a useful cross-server data point:
the no-tool over-calling looks like a **Llama-3.3 model tendency**, not a
server-specific artifact.

**Real-client reduced fixtures — the decisive result**: **4/4 valid, zero
degenerate collapse.** Not merely "no garbage" — genuinely *correct*
behavior:

| Fixture | `finish_reason` | Result | `total_time_s` |
|---|---|---|---|
| `no_tools_control` | `stop` | Coherent reasoning about the (quicksort) task in plain text | 185.6 |
| `minimal_prompt_one_tool` | `tool_calls` | `create_file` with a correct quicksort implementation | 36.3 |
| `one_tool_create_file` | `tool_calls` | `create_file`, correct implementation, correct file path | 85.9 |
| `nine_tools` | `tool_calls` | `create_file`, correct implementation, correct file path | 110.4 |

Same GGUF (`Llama-3.3-70B-Instruct-Q4_K_M.gguf`, same file via symlink,
not a re-download), same prompts, same `--ctx-size`/`--parallel`. The only
things that differ are the serving stack (LM Studio's bundled llama.cpp
fork/version vs. our pinned upstream commit) and the GPU backend (Vulkan
vs. HIP/ROCm) — see the disclosed methodological caveat above. **This is
the first evidence in the whole investigation that the failure is not
inherent to the model weights on this hardware** — some combination of
{llama.cpp version, HIP backend, our specific build/config} that our
pinned baseline uses is implicated, not Llama 3.3 itself.

This reopens a question deliberately set aside earlier: the dedicated
single-model llama-server comparison (section 6.2) was skipped as
"unnecessary — not ambiguous." **That judgment no longer holds.** A
different backend on the same weights changing the outcome this
dramatically means router-mode-vs-dedicated is no longer the only
plausible confound — HIP-vs-Vulkan is now a live, competing hypothesis,
and it hasn't been isolated from "different llama.cpp build/version"
(LM Studio bundles its own fork, not our exact pinned commit). Revisit
per the next-steps update below.

### Phase 3 full-scale result — a different, severe failure mode at 84 tools

The full 84-tool capture (3 reps, default 300s timeout) **timed out on all
3 reps** — but this did not mean "stuck": a retry with a 1500s timeout
returned after 287.9s with `finish_reason: null` and a raw SSE `event:
error` payload:

```
{"code":500,"message":"decode() failed: vk::Queue::submit: ErrorDeviceLost","type":"server_error"}
```

**A genuine Vulkan GPU driver crash** (`ErrorDeviceLost`) under the full
84-tool request's much larger prompt (~33K tokens) — not a semantic
failure like llama.cpp's garbage collapse, a hardware/driver-level one.
Worse: **this left the server in a broken state for subsequent requests
too** — a re-test of the previously-passing `nine_tools` fixture then
failed with `"Engine protocol predict request failed: fetch failed"`,
confirming the crash didn't stay contained to one request. Recovery
required a full daemon/model/server restart (`lms daemon down` → `up` →
reload model → restart server); `nine_tools` then passed cleanly again
(`tool_calls: ['create_file']`), confirming the restart fully cleared it.

**Revised Phase 3 verdict — real and decisive, but scale-bounded, not
unconditional:**

- At small-to-medium scale (tested up to 9 tools, ~40KB prompts): LM
  Studio/Vulkan **decisively fixes** the exact failure this investigation
  exists to characterize — same GGUF, same prompts, correct tool calls
  and coherent reasoning instead of llama.cpp's garbage collapse. This
  holds even where llama.cpp fails with as little as **one** tool
  (`one_tool_create_file` collapsed on llama.cpp; passed correctly on LM
  Studio).
- At full scale (84 tools, ~134KB, the literal captured Copilot request):
  LM Studio has its own severe failure — a Vulkan driver crash, not a
  content failure.
- **Qualitative distinction worth weighing**: llama.cpp's failure is
  silent and content-shaped (a plausible-looking response that is
  actually garbage or a phantom tool call) — the more dangerous failure
  mode for an agent that might act on it. LM Studio's failure is loud and
  structural (an explicit `500`/stream error) — a client would see a
  clear failure, not a confidently-wrong action.
- **This is exactly why section 5.4's tool-list narrowing
  (`virtualTools.threshold` lowered to 20, already applied client-side
  this session) is a load-bearing mitigation, not an optional
  optimization**: it's specifically designed to keep the tools actually
  sent per-request well under the scale where either server's failure
  mode triggers.

### Phase 5 decision — LM Studio (Vulkan) selected as leading server

Per section 7's decision criteria ("eliminates the Copilot repetition/
tool-call failure with the same GGUF") and section 9's weighting
(structured tool reliability is 45%; a server "cannot win solely through
speed" if it has an unresolved repetition loop, but the converse also
holds — llama.cpp's *silent content* failure at even one tool is worse
than LM Studio's *loud structural* failure only at full 84-tool scale):
**LM Studio (Vulkan backend) is selected as the leading server**, bounded
by the tool-count mitigation above. Per section 5's own routing rule
("If LM Studio is a useful improvement, select between it and pinned
llama.cpp; Ollama will not have been tested in this cycle by design"),
**Phase 4 (Ollama) is skipped** — this was always the designed outcome of
LM Studio succeeding, not a shortcut.

This is provisional pending Phase 6 (Qwen3-Coder) and real VS Code
acceptance testing — the plan's own rule that the final decision names a
*complete combination*, not a server in isolation, still applies.

### Outstanding items (carried forward)

1. **Operator action needed**: set `maxInputTokens: 57344`/`maxOutputTokens:
   8192` manually on the Llama-3.3-70B (local) BYOK model entry via
   Copilot's "Manage Models" UI — not scriptable.
2. Phase 6 (Qwen3-Coder) acquisition: source identified
   (`unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF`, Q4_K_M + Q6_K), operator
   downloading via their own Garuda-desktop + `hf` + rsync workflow —
   not yet confirmed landed on `pve-framework`. Also noted in passing:
   several other staged models (`Command-R-35B-Dark-Horror-V2...`,
   `L3.1-MOE...Uncen...`, `L3.2...uncen-ablit...`) are community
   roleplay/uncensored finetunes unrelated to this investigation —
   flagged for the operator's awareness, not acted on.
3. **Rotate `LLM_GPU_STACK_API_KEY`** (see the exposure incident above) —
   still outstanding.
4. Consider (not yet done, optional): rebuilding the pinned llama.cpp with
   `-DGGML_VULKAN=ON` instead of `-DGGML_HIP=ON` would isolate whether the
   backend (HIP vs Vulkan) or the different llama.cpp build/version is the
   true cause of the Phase 2 vs Phase 3 divergence — an interesting root-
   cause question, but not necessary to reach the plan's practical goal
   now that a working combination (LM Studio) exists. Revisit only if LM
   Studio itself fails later acceptance testing and a fallback is needed.

### Phase 6 (Qwen3-Coder) started — near-miss caught before damage

`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` (18.56 GB) landed on
`/data/models` via the operator's own `hf` + rsync workflow while Phase 3
work was wrapping up; `Q6_K` had not yet arrived. Started Q4 testing
immediately rather than wait idle (section 10.2), reusing the LM Studio
harness: unloaded Llama 3.3, imported the new GGUF via
`--symbolic-link` (no duplicate copy), loaded with the same `-c 65536
--parallel 1 --gpu max` settings (17.28 GiB, ~18s).

**Near-miss, caught before any data was lost**: `run_phase3_lmstudio.sh`
had hardcoded output paths (`results/phase3-lmstudio-protocol-ladder`
etc.) — running it a second time for a new model would have silently
overwritten the Llama 3.3 results it had just produced. Caught this
*before* the overwrite occurred (the script only writes at the very end
of each stage), killed the run, renamed the existing Llama 3.3 result
directories to `results/phase3-lmstudio-llama33-*`, and added a required
`<result_label>` argument to the script so every model's results get
their own namespaced directory going forward
(`results/phase3-lmstudio-<label>-*`). Re-launched cleanly as
`qwen3coder-q4`.

### Phase 6 Q4 results — fast and mostly correct, but a real tool-selection concern

**Protocol ladder**: 26/27 by the validator, but two of the "valid" cases
are confounded by the `--tool-choice-override required` substitution and
deserve separate scrutiny. Looking at the *un-confounded* rungs (where
`tool_choice` was already a plain string in the original fixture, no
override applied):

- `03_required_selection` (task: find every reference to `DATABASE_URL` —
  the obviously correct tool is `search_files`): **called `read_file` on
  all 3 reps.** Wrong tool, unambiguous case — *initially* read as a model
  weakness; corrected below.
- `06_tool_result_continuation` (task: after reading a file's content,
  write a summary — the obviously correct next action is `create_file`):
  **called `read_file` again on all 3 reps** — same pattern.
- `05_automatic_no_tool`: same over-calling pattern seen on both llama.cpp
  and Llama-3.3-on-LM-Studio (calls `search_files` when no tool is
  needed) — consistent with this being a cross-model/cross-server
  tendency, not model- or server-specific. This one is unaffected by the
  parser bug found below (it's an `auto` rung).

**Correction — this is an LM Studio parser bug, not a Qwen3-Coder
reasoning failure.** Inspecting the raw `content` alongside the parsed
`tool_calls` for `03_required_selection` shows the model's own generated
text is *correct*:

```
I'll search for all references to "DATABASE_URL" in the repository.
<function=search_files>
<parameter=query>
DATABASE_URL
</parameter>
</function>
```

— but the extracted `tool_calls` entry that LM Studio's OpenAI-compat
layer produced from this is `read_file` with `{"path":"README.md"}`,
matching neither the function name nor the arguments the model actually
generated. `06_tool_result_continuation` shows the identical pattern:
content correctly shows `<function=create_file><parameter=path>
summary.txt</parameter>...`, parsed as `read_file` with
`{"path":"summary.txt"}`. **Qwen3-Coder generated the right call in its
native XML format both times; LM Studio's XML-to-JSON tool-call parser
mis-translated it into a different name and different arguments.** This
is exactly the protocol/parser-vs-model distinction section 3.2 exists to
make, and exactly the risk flagged for Qwen3-Coder's "completely custom
XML format" during acquisition research.

The two `tool_choice`-overridden rungs (forced `read_file`/`create_file`,
substituted to `"required"`) show the same mis-parse pattern. Put
together, **every rung that used `tool_choice: "required"` (native or
overridden) hit this parser bug; every rung using `"auto"` or no
`tool_choice` — including all real-client fixtures, which is how Copilot
actually calls the API — parsed correctly.** This looks like a bug
specific to LM Studio's `required`-choice code path for this model's
custom parser, not a general breakage. Not independently confirmed
against LM Studio's upstream issue tracker; recorded here as an empirical
finding from this harness, not a verified root cause.

**Real-client reduced fixtures — corrected**: initially recorded as 3/4
valid with `no_tools_control` flagged for "repetition." **That flag was a
false positive in the validator, corrected before being relied on**: the
actual content is a long (6,466-char), well-structured, entirely
coherent response — a complete, correct quicksort implementation plus
test data, README, a test runner, and requirements.txt, all syntactically
valid Python/Markdown. The repetition heuristic's n-gram check counted
legitimate repeated code-comment patterns (`# Test case`, `# Test Data`,
`for _ in`) that recur naturally across a long structured response, with
no requirement that the repeats be *clustered* the way a genuine
degenerate loop's repeats are. Fixed `detect_repetition()` in
`validator.py` to require repeats within a bounded nearby window
(`cluster_span_words`), not just "occurs N times somewhere in the
document" — verified against both the real DRY=0.8 degenerate case (still
correctly flagged) and this Qwen3-Coder response (no longer flagged).
Corrected result: **4/4 real-client-reduced fixtures pass**, and
noticeably fast — 9.5s/13.8s/21.2s for the tool-calling ones, vs. Llama
3.3's 36–110s on the same fixtures on the same server (consistent with
the A3B MoE architecture's 3.3B active parameters vs. Llama's 70B dense).

**Net assessment so far**: Qwen3-Coder Q4 does **not** reproduce the
degenerate-collapse failure this investigation is chasing, and its own
tool-*selection* reasoning is correct even where the parser mangled the
output (the model's raw XML named the right function with the right
arguments both times). The real, load-bearing finding is narrower than
first thought: **LM Studio's `tool_choice: "required"` path has a parser
bug for Qwen3-Coder's custom XML format; `"auto"` (what Copilot actually
sends) does not.** Given real client usage is `auto`-shaped, this doesn't
disqualify the combination the way a `05_automatic_no_tool`-style failure
would — but it does mean any client or workflow that relies on forcing a
specific tool (`tool_choice: "required"` or a named function) against
Qwen3-Coder on LM Studio cannot currently be trusted, until/unless
retested against a newer LM Studio/llama.cpp-fork build.

**Correction, found overnight — the auto/required split doesn't hold.**
Built `auto`-mode twins of `03_required_selection` and
`06_tool_result_continuation` (via `build_protocol_fixtures.py`,
`_expected: {"tool_call": true}`) specifically to get a clean read past
the required-mode confound. Result: **the exact same leak-into-content
failure happened in `auto` mode too**, 3/3 and 3/3. Comparing the raw
`content` field against a correctly-parsed `auto`-mode response
(`04_automatic_tool_needed`, where `content` is only
`"I'll check what's in the config.py file for you. Let me read it.\n"`,
tool call cleanly extracted) against a failing one (`content` is the
*entire raw XML block* verbatim, including a stray unmatched
`</tool_call>` closing tag with no corresponding opening tag, tool_calls
empty): **this is not an auto-vs-required split at all — it's an
inconsistent parser that sometimes fails to extract the tool-call block
regardless of `tool_choice` mode**, plausibly tied to formatting variance
in exactly how the model closes/wraps its XML (the stray unmatched
closing tag is a real clue, not confirmed as the root cause). The
practical conclusion stands regardless of exact mechanism: **this parser
issue is real and not fully understood, needs eyes-on review of raw
responses rather than trusting the validator's `valid`/`invalid` count
alone**, and is a genuine, open reliability question for Qwen3-Coder on
this LM Studio build — separate from, and less severe than, the
degenerate-collapse failure this whole investigation started from (a
malformed response a client can detect and retry, not a silently wrong
one).

**Quantified overnight**: a 15-trial varied-seed sweep across
`nine_tools`/`one_tool_create_file`/`minimal_prompt_one_tool` (5 seeds
each) hit this same leak exactly once (seed 1004,
`minimal_prompt_one_tool`) — manually confirmed by reading the raw
content (correct `<function=create_file>` XML, correctly formed,
simply not extracted). **Empirical rate so far: roughly 1-in-15 to
1-in-8 depending how the earlier 2/2 auto-mode-twin trials are weighted
in** — real, worth tracking, but the other 14/15 in this sweep parsed
correctly, including every `nine_tools` and `one_tool_create_file` trial.
Not frequent enough to be a blocking concern on its own, but frequent
enough that any client integration should treat a `content` field
containing `<function=` as a signal to retry rather than display as
prose.

### Phase 6 Q4 full-84-tool result — no crash, correct, fast

Where Llama 3.3 on LM Studio crashed with `vk::Queue::submit:
ErrorDeviceLost` at this exact scale, **Qwen3-Coder Q4 handled the full
84-tool capture correctly on all 3 reps** — `create_file` with the
correct path and a correct quicksort implementation each time, no crash,
no timeout. Timings: 101.8s / 37.1s / 23.2s — the first rep likely
includes cold-cache/prompt-processing warmup; even the slowest is far
faster than Llama 3.3 ever got at this scale (crashed before completing).

Combined with the reduced-fixture results: **Qwen3-Coder Q4 is 7/7
correct across every real-client scale tested (small through the full
84-tool capture), with no degenerate collapse and no crash anywhere** —
a materially better result than either llama.cpp/HIP (collapses even at
one tool) or Llama-3.3/LM-Studio-Vulkan (correct through 9 tools, crashes
at 84). This is weighed against the two genuine protocol-ladder
tool-selection misses noted above, which are real but did not manifest
in any of the real-client-shaped tests (whose correct tool was
essentially unambiguous — the task always maps to `create_file`). The
tool-selection weakness needs to be kept in view for Phase 8's more
varied acceptance tasks (search, refactor, diagnostics), not dismissed,
but it doesn't offset the decisive real-client result on its own.

### First real VS Code acceptance signal — and a real-usage crash

With Qwen3-Coder pointed at directly from Copilot BYOK (operator edited
`~/.config/Code/User/chatLanguageModels.json` directly — a real, plain
JSON file, not opaque internal state as earlier assumed; corrected that
understanding), the operator ran an actual live Copilot Chat session
against `qwen3-coder-30b-phase6`: "create a Python quicksort
implementation with test data." Result, in `~/git/vscode-ai-testing/`:
a correct recursive quicksort, a separate correct in-place iterative
version with proper edge-case handling, a test suite, and test data —
genuinely good, well-organized multi-file output. Running the generated
test suite: 12/15 pass; **the 3 failures are all the model making
arithmetic mistakes hand-writing its own expected test values** (e.g.
dropping a duplicate element when manually working out the sorted form
of an 8-element array) — verified by comparing the actual
`quicksort()` output against Python's own `sorted()`, which match
exactly. The algorithm itself is 100% correct; only the model's manual
verification-by-hand of its own test fixtures was sloppy. This is this
plan's first genuine, if informal, positive VS Code acceptance signal.

**Then, mid-session, the server crashed** — same signature as the
full-84-tool synthetic crash (`vk::Queue::submit: ErrorDeviceLost` →
`Engine protocol predict request failed: fetch failed`), but this time
during **real Copilot usage** (7 messages, real ~11,000-token prompt with
much of Copilot's full tool roster still present despite
`virtualTools.threshold: 20`). This is the most important finding of the
session: **the Vulkan crash is not a synthetic-scale-only curiosity — it
can and did hit genuine interactive usage.** Recovered with the same
reload procedure as before (`lms load` + `lms server start`), verified
healthy with a clean sanity request.

**Implication**: LM Studio + Qwen3-Coder is not yet a "just works"
combination for sustained real Copilot sessions — it's demonstrably
capable of excellent output, but carries a real, recurring crash risk
once conversation/tool-schema size grows past some threshold between
"9 tools, clean" and "real Copilot session, crashed." Locating that
threshold more precisely, and/or getting Copilot's tool roster reliably
narrowed (the `virtualTools.threshold` change alone did not appear
sufficient to shrink the schema actually sent), are now load-bearing
open questions before this combination could be trusted for unattended
or high-stakes use.

### Overnight autonomous testing (operator handed off for the night)

Operator confirmed the crash above and explicitly authorized continuing
autonomously overnight, checking in again in the morning. Built two new
pieces of harness infrastructure first:

- `ensure_model_loaded.sh` — idempotent health-check-and-recover: checks
  `lms ps` for the expected identifier, reloads + restarts the server if
  missing. Run before any further server-touching test, given the
  demonstrated real crash risk. (First attempt to invoke it piped a
  script via ansible's shell module over stdin — ansible does not forward
  stdin that way and the command hung; killed it and switched to the
  proven copy-then-execute pattern used for the LM Studio installer.)
- `agent_loop.py` — a genuine multi-turn agentic loop: sends the
  conversation, executes any returned tool calls for real (read/create/
  edit files, run shell commands) scoped to a disposable repo root, feeds
  results back, repeats until the model stops or a turn limit is hit.
  Closer to real Phase 8 acceptance testing than single-request replay,
  and the first tool able to reproduce a *multi-turn* conversation the
  way a real crash-triggering Copilot session does (all prior testing was
  single-shot). Also fixed to catch transport errors (HTTP/connection
  failures) cleanly instead of an unhandled traceback, since a transport
  error here may mean the server itself just crashed again.

**First real multi-turn task — clean success.** Task: "there is a
failing test in this repository, find and fix it." Using only the 5-tool
narrow set (`read_file`, `create_file`, `replace_string_in_file`,
`list_dir`, `run_in_terminal`) from section 5.4's recommendation — 10
turns, 9 tool calls, `finish_reason: stop` on its own: explored
(`list_dir`, read README/source/tests) → reproduced the failure
(`pytest`) → applied a precise minimal fix (`replace_string_in_file`,
correctly changing `range(low, high)` to `range(low, high + 1)` — the
exact seeded bug, nothing extraneous) → re-ran `pytest` → ran the
project's own `validate.sh` → exit code 0 across pytest + ansible-lint +
terraform validate. **No crash, no wasted turns, no fabrication** — this
is a full section-8-style acceptance pass on this task. Repo reset
(`git checkout`) for further runs.

This is an important data point for the crash-trigger question: a
genuine multi-turn conversation (10 turns) with a **narrow** tool set
(5 tools) completed cleanly, while a **real Copilot session** (7
messages, Copilot's much larger tool schema) crashed. This points at
tool-schema/prompt size as the more likely trigger dimension than raw
turn count — consistent with, and now better isolated from, the
"probably tool-schema-triggered" hypothesis in the full-84-tool crash
note above. Not yet conclusively isolated (turn count and schema size
both differ between the two cases); more multi-turn runs at varying tool
counts would sharpen this further.

### Crash-trigger experiment result — hypothesis refuted, root cause still open

Extended `agent_loop.py` with `--extra-tools-from-fixture` to pad the
5-tool set with the other 79 tools from the real captured Copilot
request (same names/schemas, not synthetic), giving a genuine
Copilot-sized 84-tool schema while keeping the same 5 tools actually
executable (calling any of the other 79 returns a stub "not available"
error, the way a real client would handle an unsupported tool). Re-ran
the identical defect-repair task from the clean 5-tool success above.

**Result: no crash.** 10/10 turns completed, `finish_reason: tool_calls`
throughout, ending on `replace_string_in_file` — `validate.sh` still
exits 0 (the fix was correct even though the run hit `--max-turns` before
a final verification call). **This refutes the "large tool schema +
multi-turn" hypothesis as stated** — the exact same 84-tool schema that
appears in the request that crashed during real Copilot usage did *not*
crash across 10 full turns here.

Checked actual growth to understand why: this run's assistant-generated
content totalled only ~1,812 characters across all 10 turns (the
disposable-fixture's files/test output are tiny), so total context
likely stayed well below what accumulated in the real Copilot session by
its 7th message. The crash-triggering session's exact prompt shape
(system prompt content/length, precise tool-result formatting, possibly
larger real file contents) hasn't been replicated — the difference could
be genuine context-size growth (not just tool-schema size, which is
mostly fixed overhead regardless of turn count), something specific to
Copilot's own request formatting this harness doesn't reproduce, or the
crash could simply be non-deterministic (a driver-level race condition
under sustained decode load, which wouldn't reproduce on every attempt
regardless of prompt shape).

**Decision: stop chasing the exact root cause for now** — diminishing
returns given the effort already spent, and not necessary to reach the
plan's practical goal. Redirecting remaining overnight effort toward
building empirical crash-rate statistics across many varied trials
(useful for the promotion gate regardless of mechanism) rather than
further isolating this one mechanism.

### Overnight reliability sweep result — 10/10, zero crashes

Built `overnight_reliability_sweep.sh`: repeats the full 84-tool fixture
N times against Qwen3-Coder, health-checking/auto-recovering
(`ensure_model_loaded.sh`) between every rep, tallying pass/fail/crash.
Ran 10 reps unattended.

**Result: 10 pass, 0 fail, 0 crash.** Timings: 107.9s (first rep, likely
cold-cache warmup), then 22.2–37.8s for the remaining 9, one anomalously
fast at 4.1s (not investigated further — didn't fail validation, may just
have been a shorter correct response). Combined with the earlier 3/3
single-shot reps and 2/2 multi-turn reps (one of which used this exact
84-tool schema), **the full-84-tool fixture is now 15/15 clean across
every test run today** on Qwen3-Coder. The one and only crash observed
all day remains the single real Copilot session — still unreproduced by
any synthetic test, despite deliberately targeting tool-schema size,
multi-turn accumulation, and now sustained repeated load as candidate
triggers.

**Working conclusion for tonight**: whatever triggered the real-session
crash is either rare/probabilistic (a driver-level race that doesn't fire
on most attempts) or tied to some aspect of Copilot's actual request
shape not yet reproduced here (exact system prompt, exact tool-result
formatting, or real accumulated file-content sizes larger than the tiny
disposable-fixture repo's). Given 15/15 clean synthetic runs, this reads
as a real but apparently low-frequency risk, not a reliably-reproducible
blocker — worth the operator's awareness before relying on this
combination unattended, but not disqualifying given no test today has
been able to make it recur on demand.

### Second crash, on the small proven-reliable schema — confirms "probabilistic," not schema-tied

A third agent_loop task (add an `is_prime` function + tests, same 5-tool
set that ran 10/10 clean turns earlier) **crashed at turn 4** — same
signature (`HTTP 400: "Engine protocol predict request failed: fetch
failed"`), caught cleanly this time by `agent_loop.py`'s transport-error
handling (no unhandled traceback). This is the single most important
data point on the crash question: **the exact small, previously-proven
5-tool schema that completed 10/10 clean turns in an earlier task
crashed here at only 4 tool calls in.** Combined with the 15/15 clean
full-84-tool reps and the clean 10-turn 84-tool-padded run, this rules
out tool-schema size, turn count, and sustained repeated load as reliable
predictors — **the crash looks genuinely probabilistic**, a driver-level
race under GPU decode load that can strike a small, simple request
almost as readily as a large one, just infrequently.

Recovery this time was notably different: `ensure_model_loaded.sh`
reported the model "already loaded" (no reload needed), and a follow-up
real request succeeded immediately — this crash instance was
self-recovering, unlike the earlier two which needed a full
`lms load`/`lms server start` cycle. Suggests there may be more than one
severity tier of the same underlying Vulkan issue. Repo reset via `git
checkout` for any further runs.

**Net conclusion on reliability**: this combination (LM Studio + Vulkan +
Qwen3-Coder) is very good but not bulletproof — expect an occasional
crash requiring a health-check-and-reload (now automated via
`ensure_model_loaded.sh`), roughly on the order of a few times across
today's ~30+ trials (2 clearly needing reload, 1 self-recovering, out of
single-shot and multi-turn tests numbering well over 30 all told). Any
production use of this combination should assume this and wrap requests
with the same kind of health-check-and-retry logic built here, not treat
it as "just works."

## 1. Purpose

Establish a reliable complete configuration for local agentic coding in VS Code
on the Framework Desktop. A complete configuration includes the client, server,
model and quantisation, template/parser, sampling and context settings, and tool
exposure policy.

Codex, Copilot, and Claude Code are the preferred client candidates because the
operator already uses them. They are preferences, not constraints. Each remains
in scope only if its local-model path is technically supported and passes the
same acceptance suite. Roo Code, Cline, or another diagnosable local-first
client may be selected if the preferred clients are not realistic. Continue is
not part of the active selection path.

The target is real file, terminal, search, edit, diagnostic, and multi-turn tool
use, not success on a small synthetic function-calling prompt.

This plan deliberately changes one layer at a time:

1. Preserve the evidence and build a protocol-validation harness.
2. Correct and pin the current configuration.
3. Establish a reproducible router baseline with the current
   `Llama-3.3-70B-Instruct-Q4_K_M` on pinned llama.cpp.
4. Compare the same commit/model/settings in a dedicated single-model
   llama.cpp service to isolate router mode.
5. Test the same model and request through headless LM Studio.
6. Test Ollama only if LM Studio does not produce a useful improvement.
7. Select the leading server, with correctness weighted ahead of speed.
8. Test `Qwen3-Coder-30B-A3B-Instruct` Q4 and then Q6 on that server.
9. If Qwen has a verified template/parser incompatibility, permit one bounded
   rescue test on another already-tested server before rejecting it.
10. Select and validate the complete client/server/model configuration through
    disposable and then real VS Code agent workflows.

The sequence is important. Changing server, model, quantisation, prompt, and
client configuration together would produce a result without a defensible root
cause. The final selection is nevertheless the complete combination, not a
server or model considered in isolation.

## 2. Executive findings

### 2.1 llama.cpp is not out of date

The live server and upstream `master` were checked on 2026-07-19:

| Item | Result |
|---|---|
| Live llama.cpp build | `b10068` |
| Live commit | `571d0d540df04f25298d0e159e520d9fc62ed121` |
| Upstream `master` commit | `571d0d540df04f25298d0e159e520d9fc62ed121` |
| Live HIP runtime | `7.1.52801-9999` |

There was therefore no newer llama.cpp revision available to test at the time
of this review. An upgrade is not a plausible immediate fix.

The deployment is nevertheless not reproducible. The Ansible role tracks
mutable `master` with `update: true`. A later provision can silently change the
binary and invalidate comparisons. The verified commit must be pinned before
the next test cycle.

### 2.2 The original Copilot failure has now been reproduced directly

The real Copilot request was captured and replayed directly against llama.cpp,
bypassing VS Code and the logging proxy as active components of the request
path.

The captured request contained:

- 84 tools;
- approximately 109,299 characters of tool schemas;
- approximately 131,876 characters in the complete request body;
- a system prompt of approximately 19,891 characters; and
- an estimated 33,469 prompt tokens.

The direct replay reproduced the Llama 3.3 repetition loop. Important reduction
tests then showed:

| Test | Result |
|---|---|
| Full captured Copilot request | Repetition loop |
| Same Copilot prompt reduced to nine tools | Repetition loop |
| Same Copilot prompt reduced to one `create_file` tool | Repetition loop |
| Same task and one tool with a minimal system prompt | Correct structured `tool_calls` response |
| Full prompt with no tools | Broadly coherent response; no early loop |

This is strong evidence that:

- the VS Code transport is not the primary cause;
- llama.cpp and Llama 3.3 can perform a basic structured tool call;
- the small one-tool test in the original investigation is not representative
  of Copilot agent mode; and
- the dominant failure is an interaction among the model, Copilot agent
  prompt, tool protocol, chat template, and tool-call parser.

The earlier statement that the Copilot failure had not been reproduced by a
direct API test is now obsolete.

### 2.3 Several original interpretations were too strong

The observed test results remain useful artifacts, but some conclusions drawn
from them do not follow:

- Toggling global `--jinja` does not rule out a template problem. Current
  llama.cpp supports explicit per-model templates and router presets. Its own
  function-calling guide shows Hermes 3 with a specific `tool_use` template.
  The Hermes 3 result is not a valid model verdict until that template is
  tested.
- Qwen2.5 emitting tool JSON in `content` is a valid observed failure, but does
  not by itself distinguish a model failure from a template/parser failure.
- Two different models producing repetition does not rule out a model-specific
  or prompt-specific cause.
- Global DRY sampling did not resolve the preserved Llama/Copilot replay or the
  Devstral loop. It should not be treated as a proven fix.
- The role comment says llama.cpp's default repeat penalty is `1.1`. The
  current documented default is `1.00`, which disables it.
- The approximately 50 tokens/second value recorded for Llama 3.3 70B Q4 is
  not output-generation speed. Live full-request testing produced about
  4.5-4.7 output tokens/second. The earlier value was probably prompt
  processing throughput.

References:

- [llama.cpp function-calling guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
- [llama.cpp server and router options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

### 2.4 Alternative servers are viable but not guaranteed fixes

Ollama officially supports Ryzen AI Max+ 395/`gfx1151` on Linux with ROCm 7,
and the live container has ROCm 7.1. Ollama also supports structured,
parallel, and multi-turn tool calling. It is technically viable, but previous
local tests gave it the worst performance. It is therefore the fallback server
test after LM Studio, not the first replacement candidate.

LM Studio provides `llmster`, a Linux headless daemon with OpenAI-compatible
endpoints. Current LM Studio releases explicitly support AMD Strix Halo. Its
tool layer has native model-specific handling plus a default compatibility
format, and `lms log stream` can expose the rendered prompt. That makes it the
more useful first alternative for this specific template/parser investigation.

Neither server can make unchanged model weights inherently more capable. A
server can improve prompt rendering, template selection, tool-call parsing,
scheduling, and operational behaviour. The same GGUF must be tested first to
measure those effects.

References:

- [LM Studio headless service](https://lmstudio.ai/docs/developer/core/headless)
- [LM Studio tool use](https://lmstudio.ai/docs/developer/openai-compat/tools)
- [LM Studio changelog](https://lmstudio.ai/changelog)
- [Ollama hardware support](https://docs.ollama.com/gpu)
- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)

### 2.5 The current model is probably not the best agent model

Llama 3.3 70B Q4 is a large dense general instruction model. It is capable of
simple tool calling, but is slow on this system and fails under the real
Copilot agent prompt.

`Qwen3-Coder-30B-A3B-Instruct` is the first planned model alternative because
it is explicitly trained for agentic coding and tool use. It has approximately
30.5 billion total parameters but only 3.3 billion active parameters. This is a
more promising performance/capability shape for the Framework Desktop than a
dense 70B model. Its model-specific tool format still means that server and
parser compatibility must be demonstrated rather than assumed.

Reference:
[official Qwen3-Coder model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct).

### 2.6 Client feasibility is part of the experiment

The preferred clients do not expose equivalent local-model paths:

- **Copilot BYOK** already reaches an OpenAI-compatible chat-completions
  endpoint and produced the captured failure. It is demonstrably connectable,
  but its large agent prompt and tool roster are a compatibility risk.
- **Codex** is a realistic candidate for LM Studio and Ollama. The locally
  installed Codex CLI (`0.145.0-alpha.18` at review time) exposes `--oss` with
  `--local-provider lmstudio` or `ollama`. Direct llama.cpp is not exposed as a
  built-in local-provider choice by that client. Confirm whether the Codex VS
  Code extension shares this local-provider path; a CLI-only success does not
  by itself satisfy the VS Code goal.
- **Claude Code** supports an Anthropic-format LLM gateway through
  `ANTHROPIC_BASE_URL`. Its official gateway guidance is written around access
  to Claude models, not around arbitrary local GGUF models. A local-model test
  therefore requires an Anthropic Messages-compatible adapter and is an
  experimental compatibility path, not a presumed direct connection to the
  OpenAI-compatible server.
- **Roo Code** uses OpenAI-native tool calling and accepts OpenAI-compatible
  endpoints, making it useful as a clean protocol client if the preferred
  clients fail.
- **Cline** supports local models through LM Studio and Ollama and documents a
  compact prompt intended for local inference. It is another bounded fallback.

References:

- [OpenAI Codex documentation](https://developers.openai.com/codex/)
- [Anthropic Claude Code LLM gateways](https://docs.anthropic.com/en/docs/claude-code/llm-gateway)
- [Roo Code OpenAI-compatible provider](https://docs.roocode.com/providers/openai-compatible)
- [Cline local models](https://docs.cline.bot/running-models-locally/overview)

## 3. Test principles and acceptance criteria

### 3.1 Reliability is more important than throughput

"Best performing" means the combination with the best reliable end-to-end
agent behaviour, not the highest tokens/second figure.

Use this decision order:

1. End-to-end task success and a correct resulting Git diff.
2. Correct structured tool-call rate.
3. Correct tool selection and arguments.
4. Correct multi-turn handling after tool results.
5. Absence of repetition, malformed output, fabricated tool results, state
   loss, and silent non-invocation.
6. Time to first useful tool call and total task latency.
7. Output tokens/second.
8. Memory use, cold-load time, operational complexity, and recoverability.

If two servers have statistically indistinguishable correctness and practical
latency, retain pinned llama.cpp because it is already automated and understood.

### 3.2 Separate protocol conformance from model judgement

`tool_choice: auto` combines protocol handling with the model's decision about
whether to call a tool. Test these separately:

1. **Forced named tool**: can the endpoint, template, model and parser emit the
   requested call?
2. **Required tool selection**: can the model choose correctly from a small
   available set?
3. **Automatic choice**: does it call a tool when required and answer directly
   when no tool is needed?
4. **Tool-result continuation**: can it consume a result and take the correct
   next action?
5. **Multi-tool sequence**: can it complete dependent calls without losing
   state?
6. **Streaming equivalence**: is the semantic structured result the same in
   streaming and non-streaming modes?

A forced-call failure is first classified as a protocol-conformance failure.
Verify that the endpoint implements the requested `tool_choice`, inspect the
rendered prompt and raw output, and confirm parser behaviour before assigning
the failure to the model. Conversely, a forced-call pass proves only the
constrained path; automatic tool choice and real coding ability still require
separate tests.

### 3.3 Required test corpus

Preserve test material under the ignored
`docs/framework-integration/artifacts/` directory. Do not commit captured
prompts, repository content, API keys, or raw logs.

The replay corpus must contain two distinct fixture classes.

Canonical protocol fixtures:

1. Forced `read_file` and `create_file` calls.
2. Required selection among read, search, and write tools.
3. An automatic tool-needed case.
4. An automatic no-tool case.
5. A tool result followed by a required second call.
6. A supported multi-tool response.
7. Streaming and non-streaming copies.

Real-client and task fixtures:

1. The exact preserved full Copilot request.
2. The same request reduced to nine tools.
3. The same request reduced to one `create_file` tool.
4. A minimal system prompt with that one tool.
5. A no-tools control.
6. Captured requests from each client that reaches feasibility testing.
7. Disposable coding tasks representing create, edit/refactor, repository
   search, terminal investigation, diagnostics, tests, Ansible syntax/lint,
   Terraform format/validate without apply, and recovery after restart.

Sanitise a reusable copy if the raw request contains secrets or sensitive
workspace content. Confirm that sanitisation does not materially change prompt
length, role structure, tool count, or schemas. Run agent tools only in a
disposable Git repository and isolated command environment during early
testing.

### 3.4 Metrics to capture

For every trial, record:

- server and exact version/commit;
- inference backend and version;
- model source repository, source revision, GGUF filename, quantisation, size,
  and SHA-256;
- chat template and tool parser selected;
- server context, parallelism, batch, micro-batch, KV-cache type, and sampling
  settings;
- client input/output limits and tool count;
- client name/version, system-prompt size, and tool-schema size;
- prompt tokens, completion tokens, prompt-evaluation time, time to first
  token/tool call, total time, and output tokens/second;
- raw streaming events and the normalised final semantic response;
- structured tool call present or absent;
- correct tool and arguments;
- valid multi-turn continuation;
- repetition, malformed output, refusal, direct answer, or fabricated result;
- peak memory/GTT usage and cold model-load time.

### 3.5 Promotion gate

A candidate must pass all of the following before becoming the VS Code default:

- 10/10 correct structured calls on the reduced deterministic replay set;
- 10/10 correct tool-result continuations;
- matching semantic results for streaming and non-streaming protocol tests;
- at least 18/20 correct calls across the full replay and varied coding set;
- zero repetition loops;
- zero fabricated claims that an unexecuted tool result was observed;
- correct handling of at least five consecutive multi-turn tool interactions;
- successful real VS Code create, edit, search, terminal, diagnostics, and test
  workflows; and
- acceptable interactive latency as judged against the pinned llama.cpp
  baseline.

Passing forced protocol tests is the entry gate for real agent testing. A
candidate is promoted only when the requested repository state exists and its
task-specific validation passes; a plausible conversational answer is not a
successful task.

With small sample sizes, a single severe failure is operationally important
even if the aggregate percentage still looks good. Record it and investigate
before promotion.

## 4. Phase 0: Preserve evidence and make the harness reproducible

### Objective

Create a repeatable test process before changing the live serving path.

### Tasks

1. Move or recreate the logging/replay tooling under
   `docs/framework-integration/artifacts/tool-calling/`.
2. Preserve the raw request only in ignored local artifacts.
3. Produce a sanitised replay fixture if required.
4. Add a runner that can target any OpenAI-compatible base URL without
   changing the request body.
5. Make the runner save machine-readable JSONL results and a concise Markdown
   summary under artifacts.
6. Capture raw SSE as well as the client-visible response.
7. Add strict validation for `finish_reason`, `tool_calls`, tool name, JSON
   argument encoding, declared-schema conformance, and assistant/tool message
   ordering.
8. Support fixed-seed diagnostic runs and a separate varied-seed reliability
   set.
9. Create the disposable Git/task fixture and automated validation commands.
10. Confirm that the captured request hashes and token/tool counts remain stable
   across replays.
11. Record the current live service, client configuration, model hashes, ROCm
   version, and current llama.cpp commit as the pre-change baseline.

### Exit criteria

- One command can replay the same corpus against a selected endpoint.
- A second run against the current server produces comparable results.
- The validator can distinguish malformed content from a structured tool call.
- No secrets or raw prompt captures are staged by Git.

## 5. Phase 1: Apply recommended configuration corrections

This phase changes configuration before the formal llama.cpp baseline. Changes
must be made on the current short-lived branch and validated according to the
repository's Ansible validation tier.

### 5.1 Pin and instrument llama.cpp

1. Replace `version: master` with variable-driven pinning.
2. Set the initial pin to
   `571d0d540df04f25298d0e159e520d9fc62ed121`.
3. Record the pin in service/version evidence.
4. Add `--perf` for the test cycle or otherwise collect separate prompt and
   generation timing from the server.
5. Add a finite server output cap, initially `--n-predict 8192`, to prevent an
   unlimited repetition loop. A client may request less.
6. Correct the repeat-penalty comment and do not introduce a new repeat penalty
   until the clean baseline is measured.

### 5.2 Move to per-model router presets

1. Add a version-controlled llama.cpp router preset file.
2. Retain the globally safe settings:
   - context size `65536`;
   - `--parallel 1`;
   - full GPU offload; and
   - one loaded model unless a later capacity test justifies otherwise.
3. Put model-specific chat templates, reasoning controls, sampling, and other
   exceptional flags in the relevant preset rather than making them universal.
4. Verify the selected template/tool-call format through `/props` and server
   logs for every tested model.
5. Retest Hermes only with llama.cpp's documented Hermes 3 `tool_use` template
   if it is retained as a diagnostic model.

Router presets improve the operational deployment, but they are not assumed to
be neutral. After the pinned router baseline, run a dedicated single-model
`llama-server` with the same GGUF and effective settings. Reintroduce router mode
only after the dedicated and router results have been compared.

### 5.3 Remove unproven global sampling changes from the baseline

1. Set DRY multiplier to `0.0` for the controlled baseline.
2. Use the model publisher's recommended sampling as the starting point for
   each model.
3. For deterministic diagnostic repetitions, use a fixed seed and low or zero
   temperature where supported.
4. Treat DRY as a later per-model experiment, not a platform-wide fix.
5. Keep F16 K/V caches during correctness testing. Test Q8 KV caches only if
   memory pressure creates a demonstrated need.

Flash attention currently defaults to `auto`; confirm the selected state in
the logs instead of assuming a missing explicit flag means it is disabled.

### 5.4 Correct the current client configuration

1. Restore the Framework Copilot endpoint from the inactive
   `localhost:8899` capture proxy to the real endpoint after capture work is
   complete, or deliberately start the proxy when capturing.
2. Start with an advertised 65,536-token total budget divided approximately as:
   - `maxInputTokens: 57344`; and
   - `maxOutputTokens: 8192`.
3. Create a narrow local coding agent with approximately 6-10 essential tools.
4. Experiment with lowering
   `github.copilot.chat.virtualTools.threshold` from `128` to approximately
   `20`, so the captured 84-tool roster is grouped on demand.
5. Keep background Copilot utility-model work away from the single local decode
   slot.
6. Remove inline API keys from ordinary configuration where the client offers
   a secret store or environment-backed mechanism. Never copy keys into test
   artifacts.
7. Preserve Continue only as historical evidence; do not spend implementation
   or acceptance-test time on it.

Reducing tools is primarily a prompt-size and tool-selection improvement. It
must not be credited as the complete fix because the preserved Copilot prompt
still failed when reduced to one tool.

Reference:
[VS Code AI settings](https://code.visualstudio.com/docs/agents/reference/ai-settings).

### Validation and rollback

1. Run syntax checks on affected playbooks.
2. Run the repository-mandated `llm-gpu-stack` provision validation against
   the appropriate test target where the role is supported.
3. Because final GPU behaviour exists only on the Framework hardware, perform
   the live restart as a controlled, reversible validation after confirming the
   target is `pve-framework` and obtaining the required production approval.
4. Preserve the previous systemd unit and configuration in ignored artifacts.
5. Roll back by restoring the previous service configuration and restarting
   `llama-router`; do not delete model files during rollback.

### Exit criteria

- The live binary reports the pinned commit.
- The service has a finite generation cap.
- Model-specific preset selection is observable.
- Copilot reaches the intended endpoint.
- The replay harness can execute through the corrected configuration.

## 6. Phase 2: Baseline current Llama Q4 on pinned llama.cpp

### Fixed candidate

- Server: pinned llama.cpp commit
  `571d0d540df04f25298d0e159e520d9fc62ed121`
- Model: `Llama-3.3-70B-Instruct-Q4_K_M`
- Backend: live ROCm/HIP, recorded exactly
- Context: 65,536
- Parallel slots: one
- KV cache: F16
- DRY: disabled
- Output cap: 8,192

### 6.1 Pinned router baseline

1. Confirm `/health`, `/v1/models`, and model-specific `/props`.
2. Record the selected Llama chat template and tool-call handler.
3. Use `/apply-template` where it can reproduce the request and verbose/raw
   logging where it cannot; record the rendered tool format rather than merely
   assuming the embedded template is correct.
4. Run the forced, required, automatic, no-tool, continuation, and streaming
   protocol ladder.
5. Run the minimal one-tool control 10 times.
6. Run the one-tool Copilot-prompt replay 10 times.
7. Run the nine-tool replay 10 times.
8. Run the complete captured request at least five times because it is slow.
9. Run the multi-turn tool-result cases.
10. Run the real VS Code coding tasks with the restricted agent tool list.
11. Repeat a representative trial with the full default VS Code tool roster to
   measure the benefit of tool reduction without conflating it with server
   correctness.
12. Record prompt-processing throughput and output throughput separately.

### 6.2 Dedicated single-model comparison

1. Stop the router cleanly and start a dedicated `llama-server` with the exact
   same commit, GGUF, context, GPU offload, parallelism, KV cache, sampling, and
   output cap.
2. Use one explicit model path and a verified embedded or explicit Llama
   tool-use template; do not enable model discovery or switching.
3. Run the protocol ladder and the complete preserved Copilot replay.
4. Compare normalised semantic results and validator outcomes. Do not require
   byte-identical response IDs, timestamps, whitespace, or SSE chunking.
5. If dedicated mode changes the result, repeat the decisive fixture before
   attributing the difference to router mode.
6. Restore and health-check the router after the comparison unless dedicated
   mode becomes the temporary leading configuration.

### 6.3 Optional protocol sentinel

If both router and dedicated Llama fail the forced-call protocol gate, test a
small model documented as working by the pinned llama.cpp function-calling
guide, such as Granite 4.1 3B. This is a fast diagnostic of the harness and
server path, not a production coding candidate.

Record the exact GGUF and template provenance, then run only the protocol
ladder. If the documented sentinel also fails, stop model scoring and repair
the endpoint/template/parser/harness. If it passes while Llama fails only on the
Copilot-shaped prompt, the base API path is functioning and the remaining
failure is combination-specific.

### Expected result

Based on the preserved replay, the likely result is that simple tool calls pass
but the Copilot-shaped prompt remains unreliable. That expectation must not be
substituted for measurement after the configuration corrections.

### Exit criteria

- A complete baseline report exists under artifacts.
- Every subsequent server can receive the identical request corpus.
- The effect of router versus dedicated mode is measured rather than assumed.
- The result clearly identifies whether the pinned/configured baseline now
  passes or retains the known failure.

## 7. Phase 3: Test headless LM Studio

### Entry condition

The pinned llama.cpp baseline is complete. LM Studio is tested even if the
baseline improves, because it is the planned first serving-layer comparison.

### Deployment approach

1. Record and pin the LM Studio/llmster and runtime versions used for the test.
2. Install headless `llmster` in a reversible test arrangement.
3. Expose it on a separate internal port with the same API authentication and
   network restrictions as practical.
4. Do not allow llama.cpp and LM Studio to load the large model concurrently.
   Stop one service before loading the model in the other.
5. Load the exact existing Llama Q4 GGUF; do not download a different
   conversion for the first comparison.
6. Match context, output cap, GPU offload, and concurrency to the llama.cpp
   baseline as closely as LM Studio permits.
7. Confirm from runtime logs that acceleration is using the intended AMD GPU
   backend rather than silently falling back to CPU.

### Test sequence

1. Run the entire Phase 2 corpus unchanged.
2. Capture `lms log stream` for the one-tool and full Copilot requests.
3. Compare LM Studio's rendered prompt and tool format with llama.cpp's.
4. Determine whether the returned structured `tool_calls` are native model
   output or LM Studio compatibility parsing.
5. Confirm the installed Codex client's LM Studio local-provider mode, then
   determine whether the Codex VS Code extension can use the same local path.
   Record CLI-only success separately if the extension cannot.
6. Repeat Copilot and any feasible Codex VS Code workflows by changing only the
   endpoint/model configuration required by that client.
7. Capture streaming and non-streaming results separately.
8. Record cold-load time, prompt latency, output speed, memory use, and
   operational recovery.

### LM Studio improvement decision

LM Studio counts as an improvement if it provides one of the following without
a material regression elsewhere:

- passes the reliability promotion gate that llama.cpp fails;
- eliminates the Copilot repetition/tool-call failure with the same GGUF;
- materially improves time to the first correct tool call while preserving
  correctness; or
- makes template/parser behaviour observably correct and maintainable where
  llama.cpp remains ambiguous.

A small tokens/second increase with unchanged tool failure is not an
improvement. A tool-call improvement accompanied by unusable latency must be
recorded but is not automatically a production win.

### Exit and rollback

- If LM Studio improves the result, mark it as the current leading server and
  skip Ollama testing unless an additional comparison is later requested.
- If it does not improve the result, unload the model, stop/disable llmster,
  restore llama.cpp, confirm health, and proceed to Phase 4.

Do not remove the LM Studio test installation or artifacts until the final
server decision is complete; they may be needed to reproduce the comparison.

## 8. Phase 4: Test Ollama only if LM Studio does not improve the result

### Entry condition

LM Studio produced no useful improvement over pinned llama.cpp. Ollama is kept
third because earlier Framework testing found it had the worst performance.

### Deployment approach

1. Record and pin the Ollama version.
2. Use the ROCm backend first; current official support includes `gfx1151`.
3. Confirm the backend in logs and do not compare a CPU fallback with the GPU
   baselines.
4. Configure one parallel request and one loaded large model.
5. Set the context to 65,536 and match output/sampling settings as closely as
   possible.
6. Import the exact Llama Q4 GGUF first. This is the valid serving-layer
   comparison.
7. Optionally test Ollama's packaged copy of the nominally same model only as a
   second, separately labelled experiment; it may differ in conversion or
   template.
8. Do not run Ollama and another server with the large model resident at the
   same time.

### Test sequence

Run the complete Phase 2 corpus and real VS Code tests unchanged. Record the
same correctness, prompt latency, output speed, memory, cold-load, and
operational metrics. Also test the installed Codex client's Ollama
local-provider mode and separately verify whether that path is available in the
Codex VS Code extension.

### Exit criteria

- A directly comparable result exists for the exact GGUF on all servers that
  reached testing.
- Ollama's previously poor performance is confirmed or disproved on the
  current ROCm/software stack.
- The current server is restored after the test if Ollama does not win.

## 9. Phase 5: Select the provisional leading server

Compare the completed server reports using this weighting. This selects the
server on which Qwen Q4/Q6 is tested first; it does not pre-ordain the final
complete combination.

| Area | Weight |
|---|---:|
| Structured tool reliability and correct arguments | 45% |
| Multi-turn correctness and absence of fabrication/loops | 25% |
| Time to first correct tool call and prompt latency | 15% |
| Output throughput and memory behaviour | 5% |
| Reproducibility, observability, automation, and rollback | 10% |

Rules:

1. A server with any unresolved repetition loop cannot win solely through
   speed.
2. A server relying on a compatibility parser may win if its behaviour is
   correct, observable, version-pinned, and repeatable.
3. If LM Studio is a useful improvement, select between it and pinned
   llama.cpp; Ollama will not have been tested in this cycle by design.
4. If LM Studio is not an improvement, include Ollama in the comparison.
5. If no alternative materially improves reliability, retain pinned llama.cpp
   and treat the next phase as a model-change experiment rather than a server
   migration.

Freeze the leading server version, backend, base configuration, and endpoint
before changing models. The bounded rescue rule in Phase 6 is the only planned
exception.

## 10. Phase 6: Test Qwen3-Coder Q4 and Q6 on the leading server

This phase corresponds to model tests 4 and 5 in the recommended path. It does
not begin until the server decision is frozen.

### 10.1 Model acquisition and provenance

1. Use `Qwen/Qwen3-Coder-30B-A3B-Instruct` as the upstream model identity.
2. Select a reputable GGUF conversion or convert from the pinned upstream
   revision.
3. Record the upstream revision, converter and version, GGUF source, exact
   filename, quantisation, file size, and SHA-256.
4. Acquire both Q4_K_M and Q6_K from the same conversion lineage where
   possible.
5. Do not substitute an abliterated, uncensored, creative, or unrelated
   fine-tune.

### 10.2 Q4 test

1. Configure the winning server with the model's correct chat template, tool
   parser, and publisher-recommended sampling.
2. Verify the chosen template/parser in logs before interpreting model output.
3. Run the full corpus and promotion gate.
4. Run real VS Code workflows.
5. Record prompt latency, active generation speed, total memory/GTT use, and
   multi-turn reliability.

### 10.3 Q6 test

1. Change only the model quantisation from Q4_K_M to Q6_K.
2. Keep server, prompt corpus, template, parser, context, client, and sampling
   fixed.
3. Repeat the full corpus and real VS Code workflows.
4. Compare whether Q6 changes structured-call correctness, argument accuracy,
   repetition, latency, throughput, or memory pressure.

If Q4 exhibits an obvious structural parser/template failure, perform enough
Q6 trials to confirm that quantisation does not alter it, then fix the serving
format before spending time on repeated Q6 runs. A higher quant is not expected
to repair a missing parser.

### Model decision

Promote the lowest-cost quantisation that passes the reliability gate. Prefer
Q6 only if it provides a measurable correctness advantage or Q4 remains
borderline while Q6 is reliable. Prefer Q4 if both are equally reliable and it
provides materially better latency or memory headroom.

Compare the winning Qwen result with Llama Q4, not merely Qwen Q4 against Qwen
Q6. Retain Llama if Qwen's faster architecture does not deliver reliable real
agent behaviour.

### 10.4 Bounded cross-server rescue test

Do not expand Qwen into a full server/model matrix by default. Permit one
cross-server rescue test only when all of these are true:

1. Qwen fails on the leading server at a verified template/parser boundary or
   emits an otherwise plausible native call that the server does not structure.
2. Another already-tested server has documented Qwen-native or compatibility
   handling that could address that exact boundary.
3. The same GGUF, quantisation, fixture, context, and sampling can be retained.
4. The result is explicitly labelled as a combination test, not a general
   server rerun.

Run the structural protocol ladder and decisive real-client replay first. Run
the expensive reliability suite only if that rescue path passes. If it wins,
reopen the complete-combination decision instead of preserving the earlier
server choice dogmatically.

## 11. Phase 7: Select and validate the client

### 11.1 Preferred-client feasibility order

Test preferred clients that have a technically credible path to the selected
server/model combination:

1. **Codex**
   - for LM Studio or Ollama, test the installed client's documented
     `--oss --local-provider` path;
   - verify the VS Code extension, not only the CLI;
   - if the extension cannot use the local provider, record Codex as CLI-only
     and do not count it as the VS Code solution;
   - direct llama.cpp remains unproven unless the current client documents or
     demonstrates a supported custom provider path.
2. **Copilot BYOK**
   - test the restricted tool policy and the full preserved prompt;
   - compare direct server replay with raw client SSE and visible behaviour;
   - treat virtual-tool grouping as a required client setting if it is needed
     for success.
3. **Claude Code**
   - test only through a deliberately configured Anthropic Messages-compatible
     gateway/adapter;
   - verify request, tool-use, tool-result, streaming, and model-name mapping;
   - do not assume that official support for Claude-model gateways guarantees
     compatibility with a local non-Claude model;
   - stop if the adapter rewrites the protocol in a way the harness cannot
     observe.

This order is pragmatic rather than preferential. Skip a client when its
required API surface is unavailable on the winning server and no bounded,
observable adapter exists.

### 11.2 Alternative clients

If none of the preferred clients passes, test alternatives in this order:

1. Roo Code using its OpenAI-compatible provider and native tool calling.
2. Cline using LM Studio or Ollama with its compact local-model prompt.
3. Another actively maintained client only after documenting its protocol,
   permissions, prompt size, capture path, and local endpoint support.

Review extension provenance, permissions, telemetry/data handling, update
behaviour, and auto-approval controls before installation. Run with no command
auto-approval outside the disposable fixture.

The goal is a working configuration, not validation of a preferred brand. A
preferred client that cannot reliably use the local model is rejected; an
alternative that passes all gates may win.

### 11.3 Client selection gate

A client remains eligible only if it:

- passes the protocol gate with the winning server/model;
- exposes sufficiently complete raw request/response evidence for diagnosis;
- completes the disposable create/edit/search/test workflow;
- has an acceptable prompt/tool-schema footprint and context behaviour;
- enforces scoped permissions and approvals; and
- can be pinned or upgraded through a repeatable regression process.

A client-specific failure does not invalidate a server/model combination that
passes through another suitable VS Code client.

## 12. Phase 8: Real agentic coding acceptance and operationalisation

### Acceptance tests

Using the selected complete client/server/model/quantisation configuration in a
disposable Git repository:

1. Create a new file with exact requested content.
2. Read and edit an existing file with a constrained change.
3. Search the repository and use the result in an edit.
4. Run a non-destructive terminal command and interpret its output.
5. Run project diagnostics/tests, fix a seeded safe defect, and rerun them.
6. Complete at least five consecutive tool turns without losing tool history.
7. Repeat with a fresh VS Code session and after a server/model restart.
8. Confirm background utility calls do not compete for the single decode slot.
9. Confirm no secrets appear in logs or tracked files.
10. Make a bounded Ansible change and run syntax/lint without deployment.
11. Make a bounded Terraform change and run format/validation without apply.
12. Resume a task after VS Code reload and server restart using repository
    state rather than invented memory.

Run the full set on the leading client. Run a smaller final compatibility smoke
test on any additional preferred client that remains a realistic secondary
option. Do not infer that success in one client proves success in another;
their prompts and tool protocols differ.

### Operational work

1. Encode the winning server and model configuration in Ansible and document
   the required client/tool policy.
2. Pin all client/server/runtime/model/template inputs needed for
   reconstruction where the component supports pinning.
3. Add health, model-properties, and a minimal structured-tool smoke test to
   the stack verification path.
4. Document upgrade procedure: change one pin, replay the regression suite,
   then promote.
5. Document rollback to the last known-good complete combination.
6. Restore ordinary log verbosity after diagnosis while retaining useful
   performance metrics.
7. Fold durable conclusions into `current-state.md`, `decisions.md`, or the
   stack runbook.
8. Delete stale ignored artifacts after conclusions have been summarised.

### Final promotion gate

Apply the repository's normal validation tier and security scan for every
implementation change. Do not promote to `stable` until the live Framework
acceptance tests pass. Do not promote `stable` to `main` until the incremental
production deployment and smoke test succeed.

## 13. Stop conditions

Stop and investigate rather than continuing the matrix when:

- the intended GPU backend silently falls back to CPU;
- the request or rendered prompt changes unexpectedly between server tests;
- a server cannot use the exact comparison GGUF;
- a captured request includes an exposed credential;
- context truncation occurs;
- a repetition loop reaches the output safety cap;
- concurrent GPU workloads approach the host memory/GTT safety boundary;
- a change reintroduces the previously observed multi-slot corruption;
- a client or adapter hides or mutates the request/response beyond reliable
  diagnosis;
- an agent tool executes outside the disposable target during early testing;
- or validation/security scanning reports a new issue.

The purpose of the matrix is to isolate variables. When an invariant is broken,
repair or explicitly relabel that experiment before drawing a conclusion.

## 14. Planned decision record

At completion, record the complete combination rather than only a server/model
pair. Possible outcomes include:

1. Codex + LM Studio/Ollama + Llama or Qwen selected.
2. Copilot BYOK + a passing server/model with a documented tool policy selected.
3. Claude Code + an observable Anthropic-compatible gateway + a passing local
   server/model selected.
4. Roo Code or Cline + a passing server/model selected after preferred clients
   fail their feasibility or acceptance gates.
5. A dedicated coding-agent service selected while the existing llama.cpp
   router remains available for ordinary chat.
6. No tested local combination meets the acceptance gate; retain the last
   safe configuration and define the next bounded experiment.

The decision must include the client and tool policy, exact versions and hashes,
template/parser evidence, test summary, known limitations, and rollback target.
