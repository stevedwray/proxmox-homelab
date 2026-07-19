# VS Code Local Agentic Coding: Findings and Test Plan

Date: 2026-07-19

Status: planned; no server replacement, model promotion, client installation,
or autonomous access to production infrastructure is approved by this document
alone

Related investigation:
[`vscode-tool-calling-investigation-2026-07-19.md`](./vscode-tool-calling-investigation-2026-07-19.md)

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
