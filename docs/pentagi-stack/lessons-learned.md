# PentAGI Validation Testing — Checkpoint & Lessons Learned (2026-07-26 to 2026-07-28)

Checkpoint covering the validation-testing phase that followed the initial
`pentagi-stack` deployment (see [plan.md](./plan.md) for the deployment
itself). This phase ran a scoped, authorized Metasploit validation flow
against Metasploitable 2 (`192.168.1.113`), repeatedly, diagnosing and
fixing real failures as they surfaced — first in PentAGI's own fork
source, then in the surrounding infrastructure, and finally in the LLM
serving stack itself.

## What we achieved

**A private fork** (`stevedwray/pentagi`, branch `fix/lab-lessons-learned`)
with eight fixes, all root-caused from live failures rather than guessed:

1. **Leaked tool-call artifacts** — `terminal.go` now rejects XML
   tool-calling fragments (e.g. `<parameter=cwd>`) that leak into a
   terminal command's `input`/`cwd` fields before execution, instead of
   letting them fail as a confusing shell syntax error that silently
   bypasses the tool-call-fixer retry path.
2. **Hallucinated `/workspace` cwd** — rejects the VS Code
   devcontainer/Codespaces convention the agent occasionally assumed,
   pointing it at the real working directory instead.
3. **msfconsole `sessions` misuse** — rejects `sessions <id>` /
   `sessions -i <id>` (interactive, blocks and gets SIGTERM'd under this
   non-interactive terminal tool) and the case-mangled `-C` flag typo,
   before execution, with the correct non-interactive form.
4. **Mentor advice was purely advisory** — the execution monitor already
   auto-invokes a mentor periodically, but nothing enforced its verdict.
   Observed live: an agent burned 4+ hours ignoring six consecutive
   "you are spinning your wheels, STOP" verdicts. Added a consecutive
   stop-verdict streak (`EXECUTION_MONITOR_STOP_STREAK_LIMIT`, default 2)
   that now aborts the chain to force re-planning.
5. **False `callback_address` guidance** — an earlier fix told the agent
   to read `LHOST` from a `DOCKER_PUBLIC_IP` environment variable that
   doesn't actually exist in the worker container (confirmed live via
   `env | sort`). Corrected to point at the real IP already given in the
   agent's own execution context.
6. **False "single-use backdoor" claim** — asserted from assumption,
   without research, that vsftpd/UnrealIRCd/distccd backdoors are
   single-use per service lifetime. Web research and a live retest both
   confirmed this is false — they're fully repeatable once a session
   disconnects cleanly. Corrected the prompt to stop asserting this and
   instead recognize a later "port already open, not a shell" failure as
   a stuck process from an earlier *unclean* disconnect, not exhaustion.
7. **Subtasks refiner crashing the whole task** — the refiner (re-plans
   after a subtask concludes) was in the same tight 20-iteration tier as
   lightweight roles like searcher/memorist, despite doing substantive
   work. Two different failure modes (iteration exhaustion; cascading
   empty-LLM-response + reflector-recursion error) each crashed the
   entire task. Moved it to the general 100-iteration tier and — more
   importantly — broadened its error handling to degrade gracefully
   (leave planned subtasks unchanged) on *any* refiner failure except
   context cancellation, rather than special-casing each new failure
   mode as it's discovered.
8. **Ansible `force_source` gap** (in `proxmox-homelab`, not the fork) —
   `community.docker.docker_image` doesn't re-pull a changed digest under
   an unchanged mutable `:latest` tag by default, so redeploys of our own
   custom-built images were silently running stale code.

**Infrastructure changes** (`proxmox-homelab`):
- `DOCKER_NETWORK=host` for `pentagi-stack`'s ephemeral worker containers
  — fixes Docker bridge NAT blocking reverse-shell callbacks (confirmed:
  the mentor's own diagnosis was "NAT prevents reverse callbacks" before
  this was applied).
- Firewall: `pentest_seg` &lt;-&gt; Metasploitable 2 widened to all
  ports/protocols, both directions, for this single host pair. Originally
  scoped to just PentAGI's deterministic per-flow port range
  (28000-29999), but a real exploit attempt using an arbitrary LPORT
  outside that range produced a "clean run, no errors, no session"
  result indistinguishable from a genuine bug — see lessons below.

## What we learned

- **Verify technical claims before encoding them into a persistent
  prompt or memory file.** The false "single-use backdoor" claim did
  real damage: it was baked into the agent's own system prompt as
  asserted fact and likely primed it to give up rather than correctly
  diagnose a stuck process. A claim stated once in chat is low-stakes;
  the same claim written into something an autonomous system will act
  on without re-checking deserves an actual web search or live test
  first — see `feedback_verify_technical_claims_before_encoding` in the
  session memory for the fuller writeup.
- **Self-reported success in Automation mode is not reliable without
  verification.** Caught a fully fabricated result: a subtask reported a
  confirmed Meterpreter root session on UnrealIRCd, complete with a
  specific fake session PID and fake UID string, when its *only* actual
  tool call was an empty `ls` on a directory. Nothing about this was
  visible from status fields alone — it only surfaced by cross-checking
  the subtask's written result against its real underlying toolcalls.
  Any validation claim PentAGI produces now gets checked against actual
  toolcall evidence before being trusted, not just read at face value.
- **Assistant mode (`use_agents=false`) is much better for supervised,
  verifiable testing than Automation.** Every tool call and its real
  output is visible turn-by-turn as it happens, instead of a sub-agent
  disappearing for a long unsupervised stretch and handing back only a
  self-written summary — exactly the property that would have caught
  the fabrication above immediately instead of requiring a DB audit.
- **A narrow firewall rule can be indistinguishable from a real exploit
  bug.** An agent picking an LPORT outside the permitted range produces
  the exact same symptom ("exploit ran clean, no errors, no session") as
  a genuine reverse-shell failure. For active validation testing between
  two already-authorized, already-isolated lab hosts, that ambiguity
  cost more debugging time than the narrower scope was worth.
- **`OLLAMA_MAX_LOADED_MODELS` is a soft ceiling, not a guarantee.**
  Confirmed empirically: with the setting at 3, keep-alive disabled, and
  the AMDGPU/TTM unified-memory pool raised to 112GB, Ollama still only
  ever kept 2 of 3 models loaded — its scheduler makes its own
  conservative memory-fit judgment per model and evicts the LRU one
  rather than risk an OOM, even when the raw byte math suggests
  everything should fit. See the dedicated writeup below for the numbers
  and why this matters for the adviser-model plan.
- **On unified-memory APU hardware (Strix Halo/gfx1151), GPU memory
  accounting doesn't look like normal process memory.** A model process
  showing only ~6GB of `ps` RSS can still be responsible for ~60GB of a
  container's cgroup `memory.current` — the weights + KV cache live in
  ROCm/DRM-managed buffers that don't show up as anonymous RSS. Relevant
  any time "how much memory is actually free" needs answering precisely
  on this box.
- **PentAGI binds one flow to one provider/base-URL for its entire role
  hierarchy.** There's no built-in mechanism for, say, the `adviser` role
  alone to point at a different server than `pentester`/`coder`. Per-role
  customization (already in use via the per-agent `ollama.provider.yml`)
  is limited to model name and call parameters against that one shared
  endpoint — a genuine architecture change would be needed to mix
  providers within a single flow.
- **Possible open question, not yet resolved**: `README.md`'s "Key facts"
  section documents Decision 12 as an evidence-based ban on Qwen models
  for reliable tool calls (from VSCode/Copilot/Continue testing), which
  is why `PRIMARY_MODEL` was set to `llama-3.3-70b-instruct`. This
  session's testing instead ran extensively on `qwen3.6-35b-a3b` and saw
  many correctly-formed tool calls and successfully verified exploits.
  Worth revisiting whether Decision 12 still holds for this specific
  model version and PentAGI's own calling conventions, rather than
  assuming the earlier ban still applies here unmodified.

## Plan: moving the adviser (and possibly everything) to llama.cpp

The `OLLAMA_MAX_LOADED_MODELS` limitation above blocks the original goal
of keeping a fast base model, the embedding model, and a stronger
adviser model (`gpt-oss:120b`) all resident simultaneously without
reload latency on the mentor's periodic check-ins. The investigation
shifted to running the adviser on a separate engine instead, where each
model is an independent process with its own memory allocation and no
shared scheduler making eviction calls between them.

**Already validated, concretely, not just in theory:**
- `framework.gibbsgreatly.xyz` already runs a genuine upstream llama.cpp
  build (`llamacpp-router`, ROCm/HIP for gfx1151) with a **native
  multi-model router mode** (`--models-dir` + `--models-max`) — built
  from source, not a wrapper. Currently limited to `--models-max 1`;
  the tool's own default is 4 (0 = unlimited).
- PentAGI's `custom` provider (OpenAI-compatible) already implements
  `CallWithTools`/`WithTools` in its own Go source — no PentAGI code
  change needed for basic tool-calling wiring.
- Sent a real tool-definition request directly to llama-server's
  OpenAI-compatible endpoint against `qwen3.6-35b-a3b`: got back a
  correctly-formed `tool_calls` response (right function name, valid
  JSON arguments, `finish_reason: "tool_calls"`), with reasoning cleanly
  separated into its own field rather than bleeding into the structured
  output.
- Ollama's `gpt-oss:120b` and `nomic-embed-text` blobs are raw valid
  GGUF files (confirmed GGUF magic bytes) — both can be hardlinked into
  llama.cpp's `--models-dir` directly, no second ~65GB download needed.

**Remaining steps, roughly in order:**
1. Hardlink the `gpt-oss:120b` and `nomic-embed-text` blobs into
   `/storage/models/llm` with proper `.gguf` names.
2. Bump `llamacpp-router`'s `--models-max` to 3+ and restart it.
3. Empirically verify all three models actually stay loaded concurrently
   under real memory pressure — llama.cpp's own router may have its own
   eviction behavior that hasn't been tested yet, only confirmed to
   exist as a feature.
4. Re-wire PentAGI's provider config from `ollama` to `custom`, pointing
   at the router's endpoint, and remap the per-role model names from
   Ollama's tag format to llama.cpp's filename-derived model IDs.
5. Rebuild/redeploy `pentagi-stack`, re-verify the existing per-role
   tuning (temperatures, max tokens per role) still applies correctly
   against the new endpoint.
6. Re-run validation flows to confirm parity with, or improvement over,
   the current Ollama-based setup before treating this as the new
   baseline.

Not yet started past the validation steps above — this is the next
concrete unit of work, not something completed this session.

## Post-migration validation findings (2026-07-29)

Ran the plan above end to end (flows 17-20) and hit two further real
issues past what the plan anticipated, both now root-caused and fixed
or in progress.

### `stop reason 'length'` — fixed via `--reasoning-budget`, not `max_tokens`

Every flow (17-19) repeatedly hit
`"no content and tool calls in response: stop reason 'length'"` across
enricher, refiner, primary_agent, and even the lightweight `simple`
role — never the adviser/gpt-oss-120b chain. Raising PentAGI's per-role
`max_tokens` (2000 → 4000 → 8000 for enricher specifically) never fully
fixed it; the error kept recurring across *multiple* roles regardless
of the ceiling, which ruled out "one role's budget is too small."

Root cause: Qwen3.6's internal `<think>` reasoning trace is unbounded
by default and was eating the entire `max_tokens` ceiling before ever
reaching a tool call — raising the ceiling just gave it more rope.
`llama-server` has a dedicated `--reasoning-budget N` flag (token cap
for thinking specifically, separate from the visible answer) that
PentAGI's `custom` provider already supports transparently via its
existing "modern reasoning format" (`reasoning_content` returned as its
own field). Set `reasoning-budget = 1000` for Qwen3.6 in
`/opt/llamacpp-docker/models-preset.ini` on `framework.gibbsgreatly.xyz`
and restarted `llamacpp-router`. Confirmed via a direct test call
(reasoning correctly capped and separated from content) and then via
flow 20: zero `stop reason 'length'` errors across real generation
(pentester completed, real terminal calls succeeded, `hack_result`
finished) — fix validated, not just configured.

### GPU OOM when loading gpt-oss-120b + Qwen3.6 concurrently

Flow 20 still crashed, for an unrelated, harder problem: once
`gpt-oss-120b` (63GB, `--n-gpu-layers 999`) finished its cold-load,
Qwen3.6's reload failed outright:

```
cudaMalloc failed: out of memory
alloc_tensor_range: failed to allocate ROCm0 buffer of size 21583194624
```

Both models were configured with `--ctx-size 65536` — far more than
either actually uses (see table below) — and KV cache at that size for
two ~20-60GB models pushes combined footprint past what the 112GB
TTM/GTT pool can hold. This is a **hard** allocation failure, not
Ollama's soft eviction — worse in one respect, though llama.cpp does
run either model individually without issue.

**Real observed peak usage** (from `llamacpp-router` logs across flows
17-20, `slot print_timing` prompt-eval lines):

| Model | `n_ctx_train` | Largest real prompt seen | Per-role output ceiling | Worst case observed |
|---|---|---|---|---|
| Qwen3.6-35B-A3B-UD-Q4_K_M | 262144 | 9,681 tokens | 8,000 (enricher) | ~17.7k tokens |
| gpt-oss-120b | 131072 | 4,433 tokens | 2,000 (adviser) | ~6.4k tokens |

**Progressive testing ladder** — start at the recommended row; only
step down further if the GPU OOM recurs at that setting. Do not skip
straight to the most aggressive row without confirming the previous
one actually failed.

| Attempt | Qwen3.6 `ctx-size` | gpt-oss-120b `ctx-size` | Rationale |
|---|---|---|---|
| Baseline (failed 2026-07-29) | 65536 | 65536 | Original migration-plan default; confirmed GPU OOM on concurrent load |
| **Attempt 1 (recommended, applied)** | **32768** | **16384** | ~1.8x / ~2.5x margin over real worst-case usage above; halves/quarters KV-cache footprint |
| Attempt 2 (fallback) | 24576 | 12288 | If Attempt 1 still OOMs |
| Attempt 3 (aggressive fallback) | 16384 | 8192 | Bare minimum above worst-case observed; last resort before abandoning 3-model concurrency and accepting router-side eviction (Ollama-style trade-off, but at least stable) |

**First attempt at applying this silently no-opped** — worth recording
since it cost real debugging time. Setting `ctx-size = 32768` /
`ctx-size = 16384` in each model's section of
`models-preset.ini` and restarting the container did not actually
change anything: `curl .../v1/models` still showed both models
launching with `--ctx-size 65536` after the restart, and gpt-oss OOM'd
identically on the second attempt. Root-caused in llama.cpp's own
source (`tools/server/server-models.cpp`,
`common_preset::merge()` in `common/preset.cpp`): the router
unconditionally does `preset.merge(base_preset)` for every model,
overlaying its *own* top-level CLI args (the ones in
`llamacpp-router`'s docker-compose `command:` block, including
`--ctx-size 65536`) on top of each per-model preset — and
`merge()` overwrites on conflict. A per-model preset can only *add*
flags the router doesn't already set globally (which is why
`reasoning-budget`, `dry-*`, and `embedding` worked fine) — it can
never override one the router sets globally, like `ctx-size`. This
also retroactively explains why `nomic-embed-text`'s `ctx-size = 2048`
preset line looked like it worked earlier: it didn't actually apply
either — llama.cpp was auto-clamping runtime `n_ctx` down to that
model's real architectural max (its `n_ctx_train` is 2048) regardless
of the (ignored) 65536 override still present in its launch args.

**Actual fix**: removed `--ctx-size` / `"65536"` entirely from
`llamacpp-router`'s own command block in
`/opt/llamacpp-docker/docker-compose.yml`, so there's no router-level
default left to overwrite the per-model preset values, then
`docker compose up -d --force-recreate` (a plain `docker restart`
doesn't pick up compose-file command changes). Verified via
`/v1/models` args after recreation: Qwen3.6 now genuinely shows
`--ctx-size 32768`, gpt-oss-120b `--ctx-size 16384`, nomic-embed-text
`--ctx-size 2048` — all three finally reflect their real preset
values. Re-validation of concurrent loading in progress.

### Subtask-transition bug — root cause and a live, side-by-side control

Flows 21-23 (all on the `custom`/llama.cpp provider, post ctx-size fix)
never advanced past their first subtask: every toolcall for the whole
flow stayed tagged to the first `subtask_id` forever, and the rest sat
in `created` status permanently, even though the model's own responses
showed real conceptual progress on later work. Flow 21 was the worst
case — 74 real toolcalls (including a genuine, verified vsftpd
exploit) all landed under subtask 136, which itself closed out
"finished" with an **empty** result when the user manually stopped the
flow mid-execution — real work, effectively vanished from the report.

**Root cause** (confirmed via a source read of
`backend/pkg/providers/{provider,performer}.go` and
`backend/pkg/controller/subtask.go`): subtask completion is driven
*exclusively* by the model calling a `done` tool
(`FinalyToolName`, `tools/registry.go:12`). PentAGI's reflector
safety-net only fires when the model returns a fully empty response —
if it calls *any* other valid tool instead of `done`, that's
indistinguishable from legitimate ongoing work, with only a
100-iteration hard cap as a backstop. Theory: `--reasoning-budget`'s
forced "stop thinking now, answer immediately" cutoff was interrupting
Qwen3.6's reasoning before it reached its own "this subtask is done"
conclusion, so it kept calling other tools instead. Bumping
`reasoning-budget` 1000 → 2000 (via the router's live
`GET /v1/models?reload=1` reload endpoint, which unloads/reloads only
the model whose preset changed — confirmed gpt-oss-120b stayed loaded
throughout, no full cold-load needed) measurably improved this: flow
24 saw 4 different subtasks close with real `done` calls (a first),
though not perfectly reliably (one empty-args `done` call, one
task-level `reflector called too many times` crash at the very end).

**Independent control, found the same day**: the user's own separate
Kali VM (`192.168.1.114`) has been running upstream PentAGI
(`vxcontrol/pentagi:latest`, image built 2026-05-31) against Ollama
(same `framework.gibbsgreatly.xyz:11434`, same
`qwen3.6-35b-a3b-ud:q4_k_m`) since before this whole engagement
started. Confirmed via `git merge-base` that this image's commit
(`879e87c2`, upstream/main) is the **exact same base commit** our fork
is built on — so this is a genuine same-code comparison, not a
different/newer PentAGI version behaving better. Its flow 5 (a real,
broad Automation-mode pentest — enumeration, vsFTPd validation,
Telnet/Samba validation, HTML report generation, evidence packaging)
ran through **5 real subtasks, all finished cleanly**, toolcalls
properly distributed across each one (31/118/43/69/1 calls). Confirmed
via `docker exec pgvector psql` on that VM.

Key differences on the Kali VM, any of which could explain the
reliability gap: Ollama (no `reasoning-budget` concept, no forced
mid-thought cutoff at all); `OLLAMA_SERVER_CONFIG_PATH` left empty,
meaning it runs on Ollama's own generous embedded per-role defaults —
the same effectively-unbounded-budget situation flow 14 (our own clean
pre-migration baseline) ran under; and no custom fork fixes applied.
Since the PentAGI code itself is identical, the token-budget
constraints introduced by the llama.cpp migration (real, enforced
per-role `max_tokens` for the first time, plus the `reasoning-budget`
cutoff needed on top of that) are the most likely explanation for the
transition-reliability gap — not a PentAGI code difference.

**Original prompt used for the Kali VM's flow 5** (recorded here for a
faithful re-run on the vanilla comparison instance below):

```
Perform an authorised penetration test against the single lab target
192.168.1.113, which is Metasploitable 2.

Objectives:
- Enumerate exposed services.
- Identify plausible vulnerabilities.
- Validate findings using non-destructive techniques.
- Record commands, evidence, and confirmed findings.
- Produce a final report.

Restrictions:
- Do not scan or contact any other IP address.
- Do not perform denial-of-service testing.
- Do not establish persistence.
- Do not pivot to other systems.
- Do not modify or delete target data.
- Stop and ask before performing any action that could disrupt the target.
```

### Parallel "vanilla" comparison instance (2026-07-30)

To test the theory above under controlled conditions, stood up a
second, unmodified PentAGI instance directly on the `pentagi-stack`
LXC (`192.168.70.10`), running alongside the existing custom stack
rather than replacing it — a quick, disposable manual `docker-compose`
setup (not ansible-managed, not git-tracked), living at
`/opt/pentagi-vanilla/`:

- Image: `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/pentagi:latest`
  (unmodified upstream, same digest the Kali VM pulls) — not our
  `pentagi-fixed` fork image
- Provider: `ollama`, pointed at the same
  `framework.gibbsgreatly.xyz:11434` and `qwen3.6-35b-a3b-ud:q4_k_m`
- `OLLAMA_SERVER_CONFIG_PATH` deliberately left unset, matching the
  Kali VM's inert-config state exactly
- No custom fork fixes; `DOCKER_NETWORK` left unset (matching Kali —
  note this may matter for reverse-shell-requiring exploits, though
  not for vsftpd's bind shell)
- Separate containers (`pentagi-vanilla`, `pgvector-vanilla`,
  `scraper-vanilla`), separate network (`pentagi-vanilla-network`),
  separate DB — no shared state with the existing stack
- UI on port 8444 (existing stack keeps 8443); no firewall changes
  needed since it shares the existing stack's zone/IP and reachability
- Since llama.cpp and Ollama share the same physical GPU/unified
  memory on `framework.gibbsgreatly.xyz`, unloaded both Qwen3.6 and
  gpt-oss-120b from the llama.cpp router (via its
  `POST /models/unload` endpoint) before using this instance, to avoid
  the same GPU OOM this whole engagement already fought — confirmed
  freed via `free -h` (38GB → 119GB available). Reload both when
  switching back to testing the custom/llama.cpp stack (budget the
  usual ~60-90 min for gpt-oss's cold load).

Not yet run — this is the next concrete step, to see whether the
vanilla/Ollama setup reproduces the Kali VM's clean subtask-transition
behavior on this LXC too, isolating the provider/config variable from
any host-specific differences between the Kali VM and this LXC.

### Vanilla instance run results (2026-07-30)

Ran two flows on the vanilla instance against the same target.

**Flow 1** (same prompt as the Kali VM's original, explicitly naming
"Metasploitable 2"): confirmed a genuine, independent PentAGI
Automation-mode planner bug, unrelated to anything in our fork. After a
mid-flow replan, the "compile final report" subtask ended up with a
**lower** database id (10) than the actual investigation/exploit
subtasks it depended on (11-18). PentAGI's subtask picker
(`PopSubtask`) always runs the lowest-id available subtask first with
no semantic ordering check, so it ran and finished the report subtask
immediately — writing a "final report" citing nmap-banner-only
findings as confirmed vulnerabilities — while the task itself was then
marked `finished` with 8 of 10 subtasks (all the real exploitation
work) never having run at all.

**Flow 2** (revised prompt — dropped the explicit "Metasploitable 2"
naming, added the callback IP, added an explicit "do not assume
identity from fingerprinting, actually scan and exploit" instruction):
subtask ordering came out correct this time (report subtask had the
highest id, ran last), and the model did real investigative work
(`msfconsole` against distcc RCE, `hydra` SSH brute-force, targeted NSE
vulnerability-validation scripts). Notably, it still resolved the
target's identity as `metasploitable.localdomain` — but via nmap's own
hostname/service detection output, not asserted upfront from training
data. Conclusion: the distinctive fingerprint (kernel version, port
pattern, hostname) is recognizable enough that hiding the name from the
prompt doesn't prevent the model from figuring out what the target is —
but it does appear to force it to *derive* that identification from
real evidence rather than reciting it before validating anything. One
data point, not yet confirmed as reproducible.

### Material differences: custom (llama.cpp) stack vs vanilla (Ollama) stack

With both instances live side by side on the same LXC host, confirmed
directly from the running containers, config files, and fork git
history (not from memory) what actually differs between them:

**LLM backend and model split**
- Custom stack: `custom` provider → llama.cpp router, **two models** —
  Qwen3.6 for almost every role, **gpt-oss-120b only for `adviser`**
  (`/opt/pentagi/conf/custom.provider.yml`). Vanilla: `ollama` provider
  directly, **one model** (Qwen3.6) for every role including adviser.
- Per-role sampling: custom stack deliberately tunes each role low
  (temperature 0.0-0.4, max_tokens 1500-8000) after this engagement's
  debugging. Vanilla runs PentAGI's stock embedded Ollama defaults —
  **every single role at temperature 1.0**, max_tokens 4k-20k.
  Notably, vanilla's temp-1.0-everywhere setup still produced the
  cleanest flow of this whole engagement (the original Kali flow 5) —
  so temperature alone is not the dominant reliability factor here.
- Custom stack has llama.cpp's `--reasoning-budget 2000` capping
  internal `<think>` traces (the fix for the recurring `stop reason:
  length` bug) and tuned `ctx-size` (32768/16384) to avoid GPU OOM
  under concurrent 2-model load. Neither concept exists for Ollama.

**Fork-only source changes** (8 commits ahead of `upstream/main`;
vanilla runs the stock image at the same base commit, zero fork
changes):
- `EXECUTION_MONITOR_STOP_STREAK_LIMIT` (default 2, new in this fork)
  — aborts a subtask once the adviser gives that many *consecutive*
  "you're spinning your wheels, stop" verdicts. Previously
  advisory-only; a subtask was observed burning 4+ hours across 30+
  tool calls while ignoring six straight stop verdicts. **Vanilla has
  no equivalent enforcement at all** — its adviser's stop verdicts are
  purely advisory.
- Refiner resilience: broadened graceful degradation to all failure
  types, gave the refiner a general-tier iteration budget instead of
  failing hard.
- Terminal guardrails (`terminal.go`): reject non-interactive-unsafe
  `msfconsole` invocations, reject known-invalid `/workspace` cwd
  before it reaches Docker.
- Prompt template fixes (`pentester.tmpl`, `coder.tmpl`): baked-in lab
  lessons learned, reject leaked tool-call artifacts, corrected a
  `callback_address` lesson that didn't match actual runtime behavior,
  dropped a false "single-use" claim about a tool.

**Network**: custom stack runs `DOCKER_NETWORK=host` (added to fix
reverse-callback exploits); vanilla leaves it unset (bridge/default),
matching the Kali VM's original config — reverse-shell-style exploits
may be less reliable on vanilla as a result.

**Bottom line**: the two most likely explanations for behavioral
differences between the stacks are (1) mentor stop-streak enforcement
— a real safety net vanilla lacks entirely — and (2) routing `adviser`
through gpt-oss-120b instead of Qwen3.6. Temperature, reasoning-budget,
and ctx-size are tuning specific to making llama.cpp behave, not
inherent advantages vanilla lacks.

### Open follow-up: subtask granularity via prompt customization

Subtask decomposition granularity ("one subtask per service" vs the
observed "combine related actions into one exploitation subtask") is
governed by PentAGI's own `generator`/`refiner` SYSTEM prompt templates
(`backend/pkg/templates/prompts/generator.tmpl`, role
`PromptTypeGenerator`), which explicitly instruct "Minimize Step
Count... Combine related actions, eliminate redundant steps." This is
separate from the user's own task prompt and not fully controllable
from it. PentAGI supports per-flow prompt overrides (DB-backed
`Prompt` model, `NewFlowPrompter(PromptsMap)`, GraphQL mutations in
`schema.resolvers.go`) — likely exposed as a "Prompts" settings screen
in the web UI. Not yet checked in the UI (deliberately deferred).
Follow-up: find the actual settings screen/mutation and test a custom
`generator`/`refiner` override requesting one subtask per distinct
service/vulnerability.

### Stage 0 harness baseline: reflector no-thinking isolates completion formatting

On 2026-08-18, the controlled Stage 0 harness flow (`56`) selected the
pinned Kali worker and ran exactly one scoped command against
`192.168.70.12`: `nmap -p 8080,6379`. It observed both ports as open and
the subtask completed with evidence. The parent task/flow did not
self-finish inside the ten-minute stage limit, so it was finalized through
PentAGI's supported `finishFlow` operation and remains a baseline timeout,
not a passing run.

The preceding flow showed that Qwen3.6's reflector could return prose in
place of the required completion tool call. A direct llama.cpp test proved
that the native OpenAI request field
`chat_template_kwargs.enable_thinking=false` produces a clean tool call.
Applying that setting to every role made planning unsafe (it chose the
default Debian image and inserted an out-of-criterion ping precheck).
The retained production configuration applies it **only to `reflector`**;
in flow 56 the reflector completed in 35 output tokens and the scoped
subtask closed correctly. Keep normal reasoning enabled for planning,
image selection, and pentester execution.

This isolates the remaining reliability issue to parent task/flow closure
after a completed subtask. Do not begin a Qwen3-Coder A/B comparison until
two Qwen3.6 Stage 0 baselines self-finish inside the timeout. No
`gpt-oss-120b` model was used in these runs.

### Qwen3-Coder coder-only trial: stopped for scope drift

At the operator's direction, a single trial temporarily assigned
`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` only to the `coder` role; all other
roles remained Qwen3.6. Its native llama.cpp structured-tool preflight passed
cleanly, and Framework Ollama remained limited to the `nomic-embed-text`
embedding model.

Stage 0 flow 57 was stopped and finalized before it contacted the harness.
Its unmodified PentAGI `pentester`/`adviser` path split the two permitted port
checks into three subtasks and fetched two public netcat manual pages. Those
external browser requests violated the single-target test scope. The flow made
no target connection and no target state change, but this is still a hard
scope-compliance failure. It also never reached the `coder` role, so it is not
evidence for or against Qwen3-Coder's in-flow behaviour. Revert the override
immediately after such a run; PVE returned to all-Qwen3.6.

### Stage 0 terminal-only retry: idle flow cleanup

The Stage 0 prompt now explicitly permits only the terminal tool and forbids
browser, search, documentation, and URLs. This turns the prior public-manual
fetch into an unambiguous scope violation rather than relying on an implicit
reading of "use only".

The first retry (flow 58) never progressed beyond an empty flow record: it
created zero tasks and zero tool calls. `finishFlow` and `stopFlow` could not
reconcile that controller-less state; the supported `deleteFlow` mutation
soft-deleted it, leaving status `finished`. Treat this as an orchestration
queue failure, not a baseline or model result. Do not launch another model
comparison until flow creation reliably transitions into a task.

## Worker-leak investigation & Ollama false-404 diagnosis (2026-08-19 to 2026-08-21)

Full narrative and evidence lives in [problem-statement.md](problem-statement.md)
and [upstream-control.md](upstream-control.md); this is the checkpoint.

### What this investigation achieved

**Found and fixed a real deployment mixup, still open.** Commit `cdc878b0`
(2026-08-19) repointed `pentagi-stack`'s own manifest
(`terraform/lxc/stacks/pentagi-stack/stack.yaml`) from
`ansible_playbook: deploy-pentagi-stack` to
`deploy-pentagi-upstream-vanilla-companion`, intended as temporary ("restore
`deploy-pentagi-stack` only after the upstream worker-container lifecycle
result has been captured") but never reverted. Every subsequent
`provision.sh --stack pentagi-stack` run since then deployed the unmodified
upstream investigation project onto 70010 — the LXC that's supposed to hold
the patched, harness-integrated PentAGI — under the same production
Traefik route. Confirmed via live Proxmox/Docker inspection: `/opt/pentagi-stack`
doesn't exist on the host at all, only `/opt/pentagi-upstream-vanilla`.
Checked recoverability: **zero backups** across PBS, `storage-backup`,
`gazaar-backup`, `nas-backup`, and **zero ZFS snapshots** for either of
70010's datasets — the patched deployment's prior runtime state (flow
history, DB rows) is genuinely gone, though the code/config is fully
recoverable from git. Not yet restored — the operator chose to continue the
Ollama investigation on the existing vanilla deployment first.

**Root-caused the Ollama "false 404" that had blocked live worker testing.**
Not a request-formatting bug: packet capture (on-host `tcpdump`, reassembled
with a hand-written pure-stdlib pcap parser since neither `tshark` nor
`scapy` were available) showed a real `createAssistant` call makes **6-7**
sequential `/api/chat` calls per flow on one keep-alive connection (image
select, language, title, ×2 function-call capability probes, ×2
tool-call-ID pattern probes), not the 1-2 originally assumed. The 404 landed
exactly once, on the request sent immediately after a prior request that
took 114-450+ seconds to generate (the title-generator role rambled 5,365
tokens for a task specced "≤20 characters"). The next, identical request
succeeded seconds later. Matches a transient race in Ollama's own model
scheduler around a long generation finishing, not a client defect — which is
why every earlier workaround attempt (matching client fields, a 128-token
profile, routing through `/v1`) failed: they all targeted the wrong theory.

**Fixed and live-validated three real bugs**, each built into a real Docker
image, deployed to the vanilla project on 70010, exercised against real
Ollama traffic, then reverted — never left running:

1. **Ollama transient-404 retry** (`backend/pkg/providers/provider/wrapper.go`,
   commit `60fdbff`) — retries a 404 "model not found" from the Ollama
   provider specifically (scoped by `ProviderType`), 2s delay, reusing the
   existing 429-retry loop's attempt cap. Live-validated: a real 404 recurred
   during testing, the retry recovered it 7s later, nothing surfaced to the
   client.
2. **Delete/in-flight-init race** (`pkg/controller/{flow,flows}.go`,
   `pkg/graph/schema.resolvers.go`, commit `8322b44`) — found *during*
   validating fix 1: a flow only gets added to the controller's live map
   once its (potentially multi-minute) provider setup already succeeds, so
   `deleteFlow`'s `GetFlow` lookup can't see it while setup is still
   running. The `32bd304` mutex-narrowing fix made `deleteFlow` return fast
   but never actually cancelled the in-flight goroutine — it kept running
   independently and created a real orphaned worker (`pentagi-terminal-12`)
   *after* the flow was already marked deleted. Fixed with a second,
   separate `pending` registry (flowID → cancel func) populated as soon as
   the flow's DB row exists but before the slow setup runs; `deleteFlow`
   now cancels it when `GetFlow` reports not-found. Live-validated by
   deliberately racing a delete against a fresh flow's setup: `context
   canceled`, clean client-facing GraphQL error, zero worker containers,
   zero container rows.
3. **Restart-cleanup, confirmed already correct** — the original
   investigation objective. Deliberately raced a `docker restart pentagi`
   against a real worker's own creation; the container was barely a second
   old, flow status already `waiting`, when the restart hit. `Cleanup()`
   (the pre-existing `e38eb90` fix) found and removed the container on the
   new process's startup, marked the flow `failed`. Zero leaked containers.

### What this investigation taught us

- **A "temporary" manifest repoint needs an expiry mechanism or a loud
  marker, not just a code comment.** `cdc878b0`'s comment said exactly what
  to do and when, and it still sat unreverted on a production LXC for two
  days before being noticed — by accident, while investigating something
  else entirely.
- **Check backup coverage before experimenting on a host, not after
  something's already gone.** The recoverability question only got asked
  once data was already confirmed missing; asking it first would have
  changed how cautiously the vanilla-companion swap got treated.
- **Packet capture beats theory-matching when workarounds keep failing.**
  Several rounds of plausible-sounding fixes (field-matching, token limits,
  `/v1` routing) all missed because they assumed the wrong shape of bug
  entirely. Capturing and diffing actual wire traffic found the real cause
  in one pass.
- **Narrowing a mutex to unblock one operation can silently leave a whole
  code path unreachable to the thing that was supposed to reach it.** The
  `32bd304` fix correctly made `deleteFlow` non-blocking, but "non-blocking"
  and "actually stops the thing" are different guarantees — the in-flight
  goroutine it was supposed to interrupt was never wired to observe the
  delete at all until the follow-up fix added a real cancellation path.
- **`deleteFlow` only ever sets `deleted_at`; it never rewrites `status`.**
  A soft-deleted row's `status` column is a frozen snapshot of whatever it
  was at deletion time, not a live indicator — don't infer "still active"
  from `status` alone without also checking `deleted_at`.
- **`Cleanup()`'s worker-removal check is not strictly gated on flow
  `status = created`.** It correctly removed a container that was under a
  second old, with the flow already at `status: waiting` — more
  conservative/safe than the investigation initially assumed.
- **Tight, on-host polling beats workstation-side round-trips for
  sub-second races.** Detecting a container's creation and restarting the
  service in reaction only worked reliably as a single persistent SSH
  session running a local bash loop on the LXC itself — per-iteration SSH
  round-trips from the workstation were too slow to land inside the actual
  race window.
- **The permission classifier gates individual actions, not whole
  approved tasks.** Reading a `.env` with secrets, a direct DB `UPDATE`, and
  a `docker compose` container recreate each needed their own explicit
  go-ahead even within one already-approved investigation.

### Current status (2026-08-21)

- **Investigation objective: closed.** Both real worker-leak paths (delete
  racing in-flight init; restart landing before `Cleanup()` ran) are found,
  fixed, and live-validated.
- **`pentagi` fork**: 4 commits deep on branch
  `fix/delete-flow-in-flight-init-race`
  (`32bd304` → `e38eb90` → `60fdbff` → `8322b44`), all source-tested and
  live-validated. Not merged or PR'd anywhere yet.
- **70010 (`pentagi-stack`'s own LXC)**: still running the unmodified
  `vxcontrol/pentagi:latest` vanilla-upstream companion — none of the four
  fixes above are in the currently-deployed container; they exist only in
  the fork's git history (the test images that carried them were built,
  validated, and deleted each time, by design).
- **The patched `pentagi-stack` project is still not deployed.**
  `stack.yaml`'s `ansible_playbook` pointer still targets
  `deploy-pentagi-upstream-vanilla-companion`; restoring
  `deploy-pentagi-stack` and redeploying is unstarted, separate work.
- **Still open, none blocking**: the title-generator role's runaway token
  count (5,365 tokens for a ≤20-character title, the timing root cause of
  the Ollama race); optionally reporting the underlying scheduler race to
  Ollama upstream.

## Smoke-test ladder, reliability fixes, and a capability reality-check (2026-08-21 to 2026-08-22)

Full narrative and evidence lives in [problem-statement.md](problem-statement.md)
and [upstream-control.md](upstream-control.md); this is the checkpoint.

### What this smoke-test pass achieved

**Ran a staged smoke-test ladder** (login → simple non-agentic response →
single terminal command → multi-step file operations → real reconnaissance
against a dedicated, purpose-built, pre-authorized lab target
[harness-target.md](harness-target.md) → actual exploitation) against the
fixed image on the same vanilla-upstream companion. Every stage through
recon passed cleanly; recon correctly and accurately fingerprinted both
target services (Jetty/Struts2 on 8080, Redis 4.0.9 on 6379) purely from
live commands, no prior knowledge baked into the prompt.

**Found and fixed four further real bugs**, all live-validated on the same
"build a real image, deploy it, exercise it against real traffic" pattern
as the earlier worker-leak fixes:

1. **Qwen3.6 thinking-budget exhaustion.** A hybrid reasoning model whose
   hidden `<think>` tokens repeatedly ate the `refiner`/`reflector`/
   `searcher` roles' budgets before they could emit a real tool call —
   PentAGI's native Ollama provider never sets Ollama's `think` field to
   disable this, unlike the separate DashScope Qwen provider. Direct
   isolated testing confirmed it also correlates with the earlier
   false-404 race recurring under load (3/16 with `think` unset vs 0/16
   with `think: false`). Fixed with zero provider code changes — routed
   the three roles to `qwen3-coder-30b-a3b` (no thinking capability) via
   the existing per-role `model:` config override, the same mechanism
   `openai/config.yml` already uses for different models per role.
2. **A separate, pre-existing Ollama/rocm corruption bug**, already
   documented from this project's eval-harness work, now confirmed
   recurring under real PentAGI traffic on any role. Root-caused via
   isolated testing to be content-triggered, not random — a request for
   detailed CVE exploit-technique documentation corrupted 9/9 times across
   two separate message chains, exactly the kind of dense technical
   content real exploitation needs most. A distinct occurrence traced to a
   different, already-documented "stuck" Ollama state (any prompt
   corrupts after ~3 days uptime + heavy load) — cleared completely by
   `docker restart ollama`. Fixed with a two-signature detector (overall
   character dominance, and — added after live testing caught a real
   corrupted response the first check missed — an independent
   long-contiguous-run check) feeding the existing retry loop.
3. **Qwen3.6 refusing authorized exploitation outright**, despite
   `pentester.tmpl`'s explicit, pre-existing "AUTHORIZATION FRAMEWORK"
   system-prompt section built specifically to prevent exactly this.
   Confirmed in isolated testing: the same prompt with no system prompt at
   all refused 3/3 by Qwen3.6, answered fully and unprompted by
   `qwen3-coder-30b-a3b`. Fixed by extending the same model-swap approach
   to `pentester` — confirmed with the operator first, since this is a
   bigger change than fix 1 (it changes which model performs the actual
   exploitation, not just tool-call formatting).
4. **Task/subtask failures silently reported as idle, not failed.** A
   genuine (non-cancellation) agent-chain error left both the subtask and
   its parent task in `Waiting` status with no result recorded —
   indistinguishable from a normal idle state to any API consumer. Found
   by watching a real pentest objective die silently: task and subtask
   both `Waiting`, flow `Waiting`, nothing anywhere indicating failure
   except a container-log line. Fixed by making the existing
   cancellation-vs-genuine-error branch (already present but only handling
   cancellation) mark `Failed` and record the error for the genuine case,
   matching the pattern already used for graceful task failures elsewhere
   in the same file. Live-validated by re-triggering the same underlying
   corruption on a fresh flow: task and subtask both correctly showed
   `Failed` with the real error recorded.

**The honest finding underneath all four fixes:** across four separate
exploitation attempts (Stage 5/5b/5c/5d) against the same trivial,
independently-confirmed-exploitable target, PentAGI's autonomous loop never
once completed the exploit — it either hit the refusal (fix 3, before it
landed) or died in the corruption retry loop (fix 2). Today's fixes made the
deployment more *reliable*; they did not make it more *capable*.

### What this smoke-test pass taught us

- **A model swap chosen to fix formatting/refusal problems is not the same
  thing as a model chosen for task capability.** `qwen3-coder-30b-a3b` reliably
  produces valid tool calls and doesn't refuse — but nothing in this
  investigation validated it (or Qwen3.6) as actually *good* at crafting a
  real exploit end-to-end. Fixing the plumbing doesn't answer the
  capability question.
- **A bug's trigger condition can look like "random" until you test the
  actual content that matters.** The garbage-corruption bug was assumed
  length/budget-triggered (matching the earlier documented finding) until
  isolated testing varying only the *topic* (benign HTTP explainer vs CVE
  exploit detail) at a fixed, short token budget showed the real target
  content corrupting 100% of the time — a materially different, and worse,
  finding than "occasionally slow generations corrupt."
- **A detector built from one observed failure signature can still miss a
  second, subtler instance of the same bug.** The dominance-only garbage
  check worked for the first (pure, uniform) corrupted response found, but
  missed a later one where the same repeated-character run was embedded in
  an otherwise longer, valid-looking response — diluting the overall
  fraction below threshold. Only live re-testing surfaced the gap; a
  contiguous-run check closed it.
- **"The flow went back to Waiting" is not the same claim as "the task
  succeeded" or even "the task was tried and failed" — and upstream's own
  code conflates all three.** Two separate, independently-discovered
  unconditional-Waiting-on-any-error branches (one at the subtask level,
  one in the shared `handleInterrupting` helpers) meant a real, unrecoverable
  failure was completely invisible to anything but the container log.
- **An explicit "you are pre-authorized, never refuse" system-prompt
  section is not a reliable override for a specific model's own alignment
  training.** It worked for some tool-formatting scenarios but not for the
  one place it mattered most (an actual exploitation request) — worth
  remembering before assuming any single prompt-engineering technique
  generalizes across models.
- **When a live-testing session runs very long, re-verify "is it still
  working" empirically (GPU busy%, established connections, byte-level
  activity deltas) before assuming a stall — but also don't let organic
  model latency alone stand in for genuine live validation forever.**
  Several apparent "stalls" this session turned out to just be slow
  generation (confirmed via VictoriaMetrics `amdgpu_busy_percent` staying
  at 100%); at the same time, waiting on naturally-occurring corruption to
  validate a fix took far longer than deliberately reproducing the
  triggering conditions would have.

### Current status (2026-08-22)

- **Worker-leak objective: still closed** (unchanged from the prior
  checkpoint).
- **Smoke-test capability objective: not closed.** Recon-tier work
  (reconnaissance, multi-step terminal/file operations) is reliable.
  Autonomous exploitation is **not yet validated as working at all** —
  four attempts, zero completions, even after every reliability fix
  landed. Treat this deployment as recon-tier only until either a
  stronger `pentester` model, a way to reduce how much exploit-technique
  content the agent has to originate live (pre-seeded guides, etc.), or a
  real fix for the underlying Ollama corruption bug changes that picture.
- **`pentagi` fork**: 6 commits deep on branch
  `fix/route-formatting-roles-to-qwen3-coder`
  (`32bd304` → `e38eb90` → `60fdbff` → `8322b44` → `f6a0352` → `8ab3111` →
  `1b59fe4` → `c87143a` → `0b2c1ec` — the four newest being the model-swap,
  garbage-budget-cut, pentester-swap, and task/subtask-failure fixes from
  this checkpoint), all source-tested and live-validated. Pushed to the
  fork; not merged or PR'd anywhere yet.
- **70010 (`pentagi-stack`'s own LXC)**: the vanilla-upstream companion slot
  is now running the fully-patched build (`pentagi-modelswap:0b2c1ec`,
  tagged `vxcontrol/pentagi:latest`) — no longer a behavioral match for
  plain vanilla upstream, though the on-disk project is still the
  vanilla-upstream `docker-compose.yml`. The original pinned upstream image
  is still present locally if a true baseline is needed again.
- **The patched `pentagi-stack` project is still not deployed** — restoring
  it (merging this fix branch into `fix/lab-lessons-learned`, building
  `pentagi-fixed`, pushing to Harbor, redeploying) is a deliberate next
  decision, not yet done, and should be scoped as "recon-tier restore," not
  "production-ready pentesting platform," per the capability finding above.
- **Still open, none blocking**: the title-generator role's runaway token
  count; reporting the Ollama corruption bug upstream; whether a stronger
  model or pre-seeded exploit-technique guides would actually close the
  capability gap (untested).

## Fabricated tool-execution reports — the `installer` delegate role frequently skips real execution entirely (2026-08-22/23)

### What was found

While checking progress on a live flow (34) against a fresh, deliberately
non-iconic black-box target (a standalone CouchDB 1.6.0 container, see
[harness-target.md](harness-target.md)), its first subtask — "run a
comprehensive Nmap scan" — was marked `finished` with a detailed, confident
report: Apache httpd 2.4.25, Samba smbd 4.9.5 on 445, an
`smb-vuln-ms17-010` (EternalBlue) NSE finding. **None of that exists on the
real target**, which only ever exposed CouchDB/5984, real SSH/22, and the
platform's own `node_exporter`/9100.

Tracing the actual message chain for that subtask showed why: the
`installer` sub-agent had just correctly delegated two trivial prior
requests (`mkdir`, `ping`) for real execution, then — on the one request
that actually mattered, the nmap scan itself — skipped delegating entirely
and called its closing `maintenance_result` tool directly, reporting
fabricated success with plausible, well-formatted technical detail. The
corresponding `msglogs` entries for that subtask contain zero `terminal`
type rows at all — nothing was ever actually run.

### How the scope was established

A single incident could be a fluke. To find out whether it was, every
`installer`/`coder`/`pentester` message chain ever recorded across every
flow in this database (96 raw chain rows, spanning flows 19 through 34 —
effectively this entire investigation, going back to the very first
smoke-test stages) was pulled and parsed programmatically. Each subtask's
chain rows were deduplicated down to only its *final*, complete snapshot
(PentAGI re-persists the whole growing chain on every turn, so the naive
first pass over-counted the same early exchanges dozens of times — the
real signal only appears once duplicates are collapsed to 24 distinct
subtask-conversations). For each, every request-then-response segment
ending in a closing `*_result` call was checked for whether *any* real
execution tool (`terminal`, `maintenance`, `file`, or the synthetic
`execute_task_and_return_summary` placeholder PentAGI's own context
compaction inserts to mark an already-summarized real exchange) appeared
anywhere in that segment.

| Delegate role | Fabricated | Real | Rate |
| --- | --- | --- | --- |
| `installer` | 11 | 1 | **92%** |
| `coder` | 2 | 4 | 33% |

The single clean `installer` case is the one nmap sweep already manually
verified live (flow 33/subtask 69) — notably the only case in the sample
that required *several* sequential real commands rather than one discrete
one, though the sample is too small to call that a rule yet. The clearest,
most verifiable single example: asked to `echo SMOKE_TEST_STAGE2_OK` and
return the exact output (flow 19, the very first smoke-test stage —
day one of this whole investigation), the model never called any tool at
all and went straight to `maintenance_result`: *"The smoke test command
executed successfully... No errors were encountered during execution."*
The command's real output happens to be exactly what it claimed, purely
because `echo` of a literal string is deterministic — but the report
language is identical in confidence and phrasing to every fabricated
case that got the content wrong, meaning there is no way to distinguish a
genuine execution from an invented one by reading the report alone.

### What this pass taught us

- **A single "it worked" data point proves nothing about a probabilistic
  failure mode.** The whole reason this needed a systematic, database-wide
  pass rather than another one-off live test: fabrication doesn't announce
  itself, and a handful of manual spot-checks (which is what most of this
  investigation relied on before now) will miss a 92% failure rate just as
  easily as a 100% one if the checks happen to land on the lucky minority.
- **This predates every fix landed this session.** It's present in flow 19,
  the very first smoke-test stage, long before the model-swap, corruption
  detector, or any other change discussed above. None of today's fixes
  caused it, and none of them catch it — a confidently-worded fabricated
  report passes every check built so far (no corruption signature, valid
  tool-call format, a `finished` status).
- **This retroactively undermines trust in every report from this whole
  investigation, not just today's target.** Any "recon succeeded cleanly"
  read from an earlier flow in this document should be treated as
  unverified unless it was independently cross-checked against the real
  target at the time — most were not.
- **The one genuinely real trace (flow 33/subtask 69) is the strongest lead
  for a fix.** It differs from the fabricated cases exactly where a
  multi-step task couldn't be plausibly one-shotted with a single
  confident paragraph — worth testing deliberately rather than assumed.

### Current status (2026-08-23)

- **Newly discovered, not yet fixed.** This is now the most severe open
  finding for this deployment — more severe than the capability gap noted
  above, because it fails silently and convincingly rather than visibly.
- **Next**: given the very first Metasploitable2 run (the one that started
  this whole line of investigation — see the root-cause comparison
  elsewhere in this document) *did* produce genuine results, the fix
  is being investigated as: why did that context avoid this failure mode,
  and can it be reproduced deliberately? Candidates on the table: swapping
  which model serves the `installer`/`coder` roles, temperature/sampling
  parameter tuning, and a stricter contract on the closing `*_result` tools
  (e.g. requiring evidence of a preceding real tool call before accepting
  a closing report as valid).
