# Local AI development tooling — coding agents, MCP, and workflow platforms

Status: **plan only, nothing built.** Next workspace after
[`plan.md`](./plan.md) (inference layer, done) — this covers the
agent/orchestration/UI layers on top of it.

## Current state (2026-07-21)

- `framework.gibbsgreatly.xyz` is still a **production-trust node**
  (`pve-framework` in `terraform/PRODUCTION_NODES`) — mutating changes need
  `./with-secrets-prod-framework` + `TASK_APPROVAL` per CLAUDE.md.
- Three validated OpenAI-compatible endpoints already live: LM Studio
  (`:8090`, Vulkan, `qwen3-coder-30b-phase6`, the validated Copilot path),
  llama.cpp (`:8080`, HIP), Ollama (`:11434`, ROCm). No new inference work
  needed to point an agent at any of them.
- One shared GPU, exclusivity is manual (`switch-to-llm`/`switch-to-comfyui`);
  LM Studio runs `--parallel 1` — concurrent agent sessions will serialize.
- No API key enforced on the LLM endpoints yet (open gap, `plan.md` Phase 6).
- **`ai-services-stack` (OpenWebUI + SearXNG) is now deployed**, not mid-flight
  (commits `0cca6d81`/`58ff5cdb`/`3ed64fdb`, 2026-07-21) — it exposes all
  three backends (LM Studio via the public `llm.${LAB_DOMAIN}` route,
  llama.cpp/Ollama via `host.docker.internal` same-host gateway), and its own
  Ansible task confirms model discovery against all three. **Production
  Traefik/Authentik/DNS reconcile against `pve` confirmed live, 2026-07-23**
  (read-only dry-run + direct `curl`/`dig` checks — see `plan.md` Phase 6
  entry for detail) — this note itself was stale, confirming the warning
  below was warranted. **Human verification (browser SSO login + RAG
  web-search check) also done, 2026-07-23** — operator confirmed Authentik
  login works and a real chat with web search enabled returned a
  visible `search_web` tool call plus a "3 Sources" citation strip with
  real external URLs. **Phase 6 is now fully complete**, `plan.md`'s own
  checkpoint updated to match.
- **Real long-context benchmark data now exists** (`benchmarks.md`,
  2026-07-21): at 65,536-token context with 41,508 input tokens, end-to-end
  latency was Ollama/ROCm 83.9s, llama.cpp/HIP 96.4s, LM Studio/Vulkan 146.8s
  (43% slower than Ollama) — despite LM Studio being fastest at short-context,
  low-latency use. No crash/reset/OOM occurred on *any* engine at this length,
  including LM Studio — the Vulkan long-context bug (`plan.md` §8) remains a
  theoretical risk for this model/config, not something reproduced here.
- The old `ai-stack` LXC on `pve` (VMID 116) already runs
  n8n/LiteLLM/Flowise/Qdrant/AnythingLLM — operator is rebuilding it
  **separately, later**. Don't duplicate LiteLLM/n8n here in the meantime.
- Reusable test infra already exists: `run-overnight.sh` (model/runtime
  benchmark) and `replay_runner.py`/`ensure_model_loaded.sh` (tool-calling
  replay harness) — the agent bake-off below should follow the same shape.
- ComfyUI's own Phase 4 validation isn't fully closed (`plan.md` §9) —
  image-gen additions here wait on that.
- **Repo composition drives the engine/context choice below**: 908 tracked
  files, ~145K lines (py/sh/yml/yaml/tf/md), of which 76.5K lines are docs
  — more than half the repo is prose reasoning, not code, and individual
  playbooks/scripts run 30–60KB. No single file needs the full 256K window,
  but a real multi-file agent task easily needs several large files plus
  their related docs loaded at once, and validation is heterogeneous
  (`unittest`, `ansible --syntax-check`, `terraform validate`,
  `provision.sh` on pve-test) — this repo rewards agentic search/tool-use
  over raw context stuffing, but still needs a large working window.

## Candidates

### Coding agents

| Tool | Best use | Priority |
| --- | --- | --- |
| Cline | primary VS Code driver, gradual path to automation | Test 1st |
| Aider | control experiment — isolates model vs. framework as the fault | Test 1st, alongside |
| OpenHands | autonomous repo-level tasks; needs ≥32K context, sandboxed workspace | Test 1st |
| OpenCode | lightweight terminal agent, parallel worktree sessions | Test 2nd, vs. Cline |
| Goose | MCP experimentation, mixed coding/ops tasks | Test 2nd |
| Open Interpreter | host diagnostics/ops automation, not repo-focused | Test 3rd |

### Supporting services

| Tool | Role | Decision |
| --- | --- | --- |
| LiteLLM | model gateway/aliases | Defer — design only, build against `ai-stack` rebuild |
| Continue | per-role IDE models (autocomplete/edit/agent split) | Try after Phase 1 bake-off |
| Tabby | always-on completion server | Low priority — verify ROCm on Strix Halo before trying, historically CUDA-oriented |
| n8n | MCP tool layer over infra (host facts, logs, ansible/terraform actions) | Defer to `ai-stack` rebuild |
| Dify | internal AI apps (triage assistants, plan reviewers) | Low priority |
| Flowise | visual agent-graph experimentation | Low priority |

### Chat UI

| Tool | Status |
| --- | --- |
| OpenWebUI + SearXNG | Deployed 2026-07-21 — confirm production reconcile + login/RAG check, then done |
| LibreChat | Optional add-on later, only if a specific gap appears |
| AnythingLLM | Optional add-on later, only if a specific gap appears |

### Image generation

| Tool | Status |
| --- | --- |
| Krita AI Diffusion | Client plugin against existing ComfyUI `:8188`; next once ComfyUI Phase 4 closes |
| SwarmUI | Only if day-to-day generation shows a gap Krita/ComfyUI don't cover |

## MCP layer

Small trusted layer, not a grab-bag of community servers:

```text
Agent hosts (Cline/OpenHands/Goose/OpenCode)
        │
        ▼
Git/filesystem (scoped dirs) · Playwright (isolated profile) · SearXNG
        │
        ▼
Custom infra MCP server — typed, narrow tools, not ssh_run(command)
        │
        ▼
n8n (approved infra workflows — deferred to ai-stack rebuild)
```

Custom infra tools: start read-only (`get_host_facts`, `collect_service_logs`,
`run_ansible_check`); anything mutating (`run_ansible_apply`,
`terraform_apply`) stays behind the same approval gate CLAUDE.md already
requires for a human — no lesser bar for an agent.

## Security boundaries

- Run agents in a container/VM/disposable worktree, never against a live
  clone with the operator's own credentials mounted.
- Dedicated SSH key + dedicated, allowlisted remote account for any agent
  with SSH access — never `~/.ssh`, personal browser profiles, or cloud
  credential directories.
- Separate read-only diagnostics from state-changing tools; require approval
  for `terraform apply`, package/firewall changes, production Ansible runs.
- Treat web content as untrusted (prompt-injection risk to an agent with
  command authority); keep browser automation off authenticated personal
  sessions.
- Log every MCP call, command, and resulting diff.
- Any tool that can mutate `framework.gibbsgreatly.xyz`/`pve` routes through
  `with-secrets-prod*` + `TASK_APPROVAL` — an agent is just another caller,
  not an exemption.

## Development and test plan

### Phase 0 — Decisions (no host changes)

- **Agent execution runs on the workstation, not `framework.gibbsgreatly.xyz`.**
  Point agents at its existing endpoints over the LAN instead — keeps the
  production node inference-only, avoids a production approval flow for
  every experiment.
- **LiteLLM/n8n: design, don't build**, until the `ai-stack` rebuild exists.
- **Confirm/close the LLM-endpoint no-auth gap** before widening exposure to
  more agents/MCP tools (doesn't block Phase 1).
- **Autonomous/agentic sessions default to llama.cpp/HIP (`:8080`), test
  Ollama/ROCm (`:11434`) alongside it; keep LM Studio (`:8090`) for
  interactive Copilot only.** Two independent reasons, one measured, one
  theoretical:
  - **Measured**: the 2026-07-21 long-context benchmark (above) put LM
    Studio 43% slower than Ollama and 34% slower than llama.cpp end-to-end
    at 65K context — the profile a sustained agent session looks like, not
    the short-prompt case LM Studio wins. Ollama was actually fastest, so
    it's worth testing as a real candidate, not just a fallback.
  - **Theoretical, secondary**: LM Studio has no `--batch-size`/
    `--ubatch-size` exposed, so it has no mitigation available if the
    documented Vulkan long-context ring-timeout bug (`plan.md` §8) ever
    does trigger, unlike llama.cpp. This hasn't reproduced at 65K on this
    model (see above), so treat it as a tie-breaker in llama.cpp's favor,
    not the primary argument anymore.
  - **Real gap, not yet closed**: the 84-tool Copilot-scale tool-calling
    reliability sweep (`findings-plan.md` "Bare-metal re-verification") was
    run against **LM Studio only** — llama.cpp and Ollama have no equivalent
    tool-calling validation yet. Don't assume it carries over; Phase 1 must
    check this explicitly before trusting either as an agent backend.
- **Context budget: configure each client explicitly, don't trust its
  default.** The model serves 262144 tokens; VS Code Copilot's own client
  once silently capped usable context at 65536 (`maxInputTokens` +
  `maxOutputTokens`) and that already proved insufficient for a real
  multi-file task (`plan.md` §0) — same failure mode will recur on any new
  agent client unless its input/output token settings are raised to match
  (comfortably under 262144, mirroring the 180000/24000 split that fixed it
  for Copilot).
- **Memory**: no host change needed up front — `ttm.pages_limit`'s ~93GB
  GTT ceiling / 32GB host reservation split already has headroom for a
  larger llama.cpp KV cache. If a long agent session and host RAM actually
  contend, revisit that split (shrinking the 32GB reservation) rather than
  truncating context — changing it is acceptable, per the operator.

### Phase 1 — Coding-agent bake-off

Client-side, disposable `task/*` branches or worktrees, never `main`/`stable`.

0. **Prerequisite check, not optional**: run the existing 84-tool
   `replay_runner.py` sweep against llama.cpp `:8080` and Ollama `:11434`
   directly, the same way it was already run against LM Studio
   (`findings-plan.md`). Neither engine has this validated yet — confirm
   tool-calling reliability holds before building a bake-off on top of it.
1. Stand up Cline, Aider, OpenHands, OpenCode, Goose — same model
   (`qwen3-coder-30b-phase6` via **llama.cpp/HIP `:8080`** as primary,
   Ollama/ROCm `:11434` as a secondary comparison run — not LM Studio
   `:8090` — per the engine decision above) for comparability.
2. Set each client's input/output token limits explicitly (large, e.g.
   180000/24000) before running anything — don't inherit a tool's default
   context cap.
3. Reuse the existing harness shape: detached/overnight run, JSONL +
   Markdown evidence under a gitignored `docs/framework-ubuntu/artifacts/`.
4. Fixed task suite run identically against each: broken Python project
   (hidden tests), a real Ansible role defect (`--syntax-check` +
   `provision.sh` as part of grading), a Terraform module missing tests, a
   ShellCheck failure, two parallel worktree sessions (OpenCode's claim).
   Pick at least one task that requires pulling in a large doc (e.g. a
   `decisions.md`-style file) alongside code, to exercise the
   docs-are-half-the-repo characteristic directly.
5. Record: pass/fail vs. hidden tests, tool-call failures, elapsed time,
   context tokens used, manual interventions.
6. **Done when**: a short writeup names a primary daily-driver + fallback.

### Phase 2 — Model gateway

- No build now. Capture the alias design (`local-agent`/`local-coder`/
  `local-fast`/`cloud-escalation` → LM Studio/llama.cpp/Ollama/cloud) as a
  requirement for the `ai-stack` rebuild.
- Exception: a narrow, explicitly temporary LiteLLM is fine if Phase 1
  surfaces a real hardcoded-model-name blocker — track it for retirement.

### Phase 3 — Chat UI

- `ai-services-stack` (OpenWebUI+SearXNG) is already deployed — don't redo
  it. Confirm the remaining acceptance items instead (separate task, not
  this one): production Traefik/Authentik/DNS reconcile against `pve`, and
  a real browser login + RAG-search check.
- Only once those are confirmed: evaluate LibreChat/AnythingLLM for a
  specific gap OpenWebUI doesn't cover. Not a default addition.

### Phase 4 — Trusted MCP layer

- Stand up now, workstation-side: scoped Git/filesystem tools, Playwright
  with an isolated profile, SearXNG search (once Phase 3 lands).
- Design now, build later: custom infra MCP server's read-only tool set.
- n8n-backed infra tools: wait for the `ai-stack` rebuild.

### Phase 5 — Security hardening

Not a separate step — apply the Security boundaries checklist above as
Phases 1 and 4 happen, not retroactively.

### Phase 6 — Image-gen additions

- Confirm ComfyUI's remaining Phase 4 items first.
- Krita AI Diffusion (client-only, low risk) before SwarmUI (needs its own
  Ansible playbook, syntax-checked like the other `framework-desktop-*.yml`).

## Open questions

- Agent-execution placement (Phase 0) needs operator sign-off before Phase 1.
- No timeline yet for the `ai-stack` rebuild that Phases 2/4 depend on.
- LLM-endpoint no-auth gap has no owner yet.
- Whether llama.cpp/Ollama actually hold up on the 84-tool tool-calling
  sweep (Phase 1, step 0) is unknown — the whole llama.cpp-as-agent-backend
  recommendation depends on this passing; if it doesn't, fall back to
  LM Studio despite its worse long-context latency.
- `plan.md`'s own Phase 6 checkpoint text is stale (still reads "not
  started" despite `0cca6d81`/`58ff5cdb`/`3ed64fdb` landing) — worth a
  fix in that doc independent of this one, since it'll mislead the next
  reader.

## References

- OpenHands: https://docs.openhands.dev/openhands/usage/llms/local-llms
- Cline: https://cline.bot/
- Goose: https://github.com/block/goose
- OpenCode: https://opencode.ai/
- Open Interpreter: https://docs.openinterpreter.com/
- Aider: https://aider.chat/docs/llms/openai-compat.html
- LiteLLM: https://github.com/BerriAI/litellm
- Continue: https://docs.continue.dev/customize/models
- Tabby: https://github.com/TabbyML/tabby
- n8n MCP: https://docs.n8n.io/connect/connect-to-n8n-mcp-server
- Dify: https://docs.dify.ai/en/introduction
- Flowise Agentflow: https://docs.flowiseai.com/using-flowise/agentflowv2
- LibreChat: https://www.librechat.ai/docs/compatibility
- AnythingLLM MCP: https://docs.anythingllm.com/mcp-compatibility/overview
- Krita AI Diffusion: https://github.com/Acly/krita-ai-diffusion
- SwarmUI: https://github.com/mcmonkeyprojects/SwarmUI
- Playwright MCP: https://github.com/microsoft/playwright-mcp
