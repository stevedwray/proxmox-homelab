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
