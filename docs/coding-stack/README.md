# coding-stack (planning workspace name — not a new stack)

Status: **live in production, confirmed working end-to-end from a real
VS Code Copilot Chat Agent-mode session.** `docs-rag-mcp` + `pgvector`
are deployed on `pve`, folded into the existing `mcp-utility-stack` LXC
(no new Terraform stack was created — see Phase 2's correction below).
Phase 4 (2026-08-24) opened the `:8001` firewall rule, wired up VS
Code's `.vscode/mcp.json` and fixed two stale/wrong Copilot custom-model
config bugs, worked around a VS Code Copilot Chat extension crash bug,
and got a real `search_docs` call confirmed via `Ran search_docs — docs-
rag (MCP Server)` in an actual Agent-mode trace, with a correct, well-
grounded answer. See `plan.md`'s Phase 4 section for the full account.
The `docs/coding-stack/` name is just this planning workspace's name (this
repo's `docs/mcp-stack/` workspace similarly covers two differently-named
stacks already, so a workspace name not matching a stack 1:1 is an
established pattern here).

## Purpose

Give AI-assisted coding workflows against this repo reliable retrieval over
its documentation (378 tracked `.md` files, ~537K words across `docs/`,
plus 20 `STACK_CONTRACT.md` files and `CLAUDE.md`) — the patterns, network
topology, per-stack gotchas, and decisions a coding agent needs to get new
work right instead of reinventing something already solved.

This is **not** a general "add RAG" project. It's scoped specifically to one
concrete gap: driving agentic coding (Cline/OpenCode/Aider-style tool-loop,
not just chat) against a **local model — Laguna S 2.1 on Ollama** — where
this project's own history shows two real risks that don't apply the same
way to a cloud frontier model:

1. **Large-context stuffing is unvalidated for this model.** Laguna S 2.1
   has a confirmed-good BFCL result on Ollama up to `ctx131k`
   (92.75%, matching default) but **nothing at 256k**. Separately, other
   models on this same Ollama build have shown severe corruption
   (degenerating into pure `?` output) specifically on *dense, structured*
   long content, not just long content generically — including one case at
   only ~3.2K tokens. "As big a context as fits" is an assumption, not a
   measured-safe setting, for this repo's docs.
2. **Tool-calling isn't perfect and sustained multi-turn sessions have a
   known corruption bug** on this Ollama build (silent empty-content
   responses after several varied prompts in a row), mitigated only by
   reloading the model before every call (~17s tax per call). A retrieval
   step that hands back a small, targeted set of doc chunks reduces both
   how much the model must hold in context at once and how many chained
   tool calls a task needs.

Claude Code / Codex driven directly in VS Code against this repo were
**explicitly evaluated and rejected** as the target for this project — they
already do fine with native grep/Read at this corpus size; building
retrieval infra for them would solve a problem they don't have. See
`plan.md`'s Background section for the full reasoning and the options
that were reviewed and set aside.

## Current state

**Phase 1 is done and resolved (2026-08-23) — Laguna S 2.1 on Ollama is
reliable.** The investigation initially found a real corruption bug and
mis-scoped it as "Ollama-specific"; the operator correctly pushed back
twice, and the actual root cause turned out to be narrower still: the
`laguna-s-2.1:q4_k_m` tag on `framework` had been built from a
**locally-imported, third-party GGUF conversion** (`UD` /
Unsloth-Dynamic-style, not Ollama's own published artifact). Pulling
Ollama's official `laguna-s-2.1:q4_k_m` fresh and re-running the identical
tests confirmed it: clean, well-formed, highly accurate responses on real
dense repo content up to at least ~26K tokens (17/17 exact VMID matches on
the largest test). The stale `-ctx131k` tags were rebuilt from the
official base the same day. See `plan.md`'s Phase 1 section for the full
evidence trail, including both corrections along the way.

**Phase 2 (design the docs-rag MCP server) is also done, including one
correction.** Tool surface (`search_docs`/`list_stacks`), chunking
strategy, pgvector schema, embedding pipeline, and reindex mechanism are
all written up in `plan.md`. The first pass proposed a brand-new LXC/VMID;
the operator asked whether it should reuse the existing AI-tooling LXC
instead, which correctly prompted re-checking this repo's own stated
convention (`docs/mcp-stack/plan.md`: bundle by trust level, don't
fragment one-LXC-per-tool) — **corrected to fold docs-rag into the
existing `mcp-utility-stack` LXC** as two more Compose services, not a new
stack.

**Phase 3 (build and deploy) is done — live on `pve`, real data verified
(2026-08-24).** The operator clarified the actual target was `pve`
(production), where `mcp-utility-stack`/`cve-mcp-server` already runs, not
`pve-test-vm`. Deployed there via the full production approval flow
(preflight → chat approval → `TASK_APPROVAL` + `./with-secrets-prod`).
Along the way: a genuinely destructive path was caught and avoided (a
naive `terragrunt apply` for the storage resize would have force-replaced
the live container; used the repo's existing safe `pct resize` path
instead, after fixing a real bug in it), a real safety guard correctly
blocked an unrelated Terraform entanglement (an SDN-attachment destroy
guard — left alone, not overridden), and four more real bugs surfaced
only by running against live infrastructure (a `.terragrunt-cache`
discovery bug, a missing-parent-directory copy bug, an intermediate-
directory permission bug that let a "successful" reindex silently index
zero files, and a Host-header allowlist gap). All fixed; final state
confirmed with real queries against real production data — see
`plan.md`'s Phase 3 section for the complete account, not just the
summary. **The one Claude Code detail worth flagging for future sessions**:
its own auto-mode Bash classifier blocked every mutating command even
after CLAUDE.md's in-chat approval flow was satisfied — a separate,
harness-level gate, not an application-level one. The operator ran each
mutating command themselves after being handed the exact text; this isn't
a workaround Claude Code can self-serve around.

## Prior art this reuses

- **Embedding pipeline**: `nomic-embed-text` (768-dim) via
  `framework.gibbsgreatly.xyz:11434` (Ollama) — already pulled and in daily
  use by PentAGI's own `pgvector`-backed memory (see
  `docs/pentagi-stack/README.md`, `upstream-control.md`). No new model pull,
  no new embedding infra.
- **Vector store**: `pgvector` — same reasoning, reuse PentAGI's proven
  pattern rather than standing up Qdrant fresh.
- **MCP hosting pattern**: `mcp-utility-stack` (`ai_seg`, typed narrow tools,
  no internal infra credentials) is the template for how a new docs-search
  MCP server would be deployed — see `docs/mcp-stack/plan.md`.
- **Not reused**: the parked `ai-stack` rebuild (Qdrant/AnythingLLM/n8n/
  LiteLLM on the old VMID 116 LXC) stays deferred, per existing guidance in
  `docs/framework-ubuntu/local-ai-development.md`. This project doesn't pull
  that rebuild forward — it's a narrower, purpose-built slice.

## Layout

```text
docs/coding-stack/
├── README.md      # this file — durable entrypoint
├── plan.md        # durable plan, options reviewed, phases, open questions
└── artifacts/     # local-only, gitignored — validation logs, transcripts
```

See `docs/workflow/documentation-workspaces.md` for the pattern this
follows.
