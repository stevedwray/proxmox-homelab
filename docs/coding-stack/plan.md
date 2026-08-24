# coding-stack — Plan

Status: **live and validated through Phase 6.** `docs-rag-mcp` + `pgvector`
are deployed on `pve` and confirmed working end-to-end from a real VS Code
Copilot Chat Agent-mode session; a `post-commit` git hook keeps the corpus
current; and a reliability proxy + regression canary now protect the
Laguna S 2.1 + Copilot + MCP pipeline itself. See `README.md` for the
one-paragraph purpose/scope, and each Phase section below for what
actually happened at each step (including every bug found along the way —
this doc is a history, not just a plan).

## Background

Trigger: operator asked whether a RAG database over this repo's
documentation could help AI-assisted coding, given a large amount of
documentation and an existing `ai-services-stack`. Researched and reviewed
in-session (2026-08-23); this doc captures the durable conclusions.

### Corpus measured

- 378 tracked `.md` files, ~537K words (`docs/` + 20 `STACK_CONTRACT.md`
  files + `CLAUDE.md`).
- `docs/` is 304M on disk, but 249M of that is `docs/pentagi-stack` and 32M
  `docs/framework-integration` — almost entirely gitignored `artifacts/`
  (logs, transcripts), not durable content. The real indexable corpus is
  much smaller than the raw directory size suggests.

### Options reviewed

| Option | What it is | Verdict |
|---|---|---|
| OpenWebUI Knowledge (already deployed in `ai-services-stack`) | Point it at the docs tree, use as a chat sidebar | **Rejected as primary** — human-chat-only, no MCP exposure, no agentic coding tool can call into it |
| Custom MCP "docs-rag" server | pgvector + `nomic-embed-text` via existing Ollama, hosted in `ai_seg` alongside `mcp-utility-stack` | **Selected** — the only option that's actually callable by an agentic tool-loop |
| AnythingLLM (parked `ai-stack` rebuild) | Full RAG app, native MCP-server support | Good fit in principle, but bundled with unrelated deferred scope (n8n/LiteLLM/Flowise) and no rebuild timeline — not pulled forward for this |
| Claude Code / Codex driven directly in VS Code | Native Read/Grep/Glob against the checkout | **Out of scope for this project** — demonstrated in-session that targeted grep across this exact corpus (~6 calls, two rounds) already finds what's needed; building retrieval infra for a client that already does fine here has poor ROI |
| Do nothing | Status quo, grep-only | Fine for lexical lookups; the real gap is semantic recall of past incidents/decisions across differently-worded docs, plus the local-model-specific risks below |

### Why the local-model angle changes the answer

The real driver for this project isn't Claude Code — it's the operator's
actual daily workflow, which also includes driving an agentic coding loop
against a **local model, Laguna S 2.1 on Ollama**, with as much context as
can be made to fit (the ask that prompted this: "maybe 256k?"). Three
findings from this project's own eval history bear directly on that:

1. **Laguna S 2.1's only validated tool-calling result is on Ollama, not
   llama.cpp** (BFCL: 92.75% vs. 75.5%, a 17-point gap) — confirming Ollama
   is the right runtime, already true today.
2. **Nothing has validated Laguna S 2.1 above `ctx131k`.** The BFCL table
   only has a `-ctx131k` entry (92.75%, matching default) — no 256k
   measurement exists for this model. Separately, other models on this same
   Ollama build have shown severe, repeatable corruption (pure `?` output)
   specifically on *dense, structured* content at large context — in one
   case at only ~3.2K tokens actually used, in another at a clean
   power-of-2 `ctx256k` tag with an ~85-100% corruption rate on sustained
   long-form generation. "As big as fits" is not a validated-safe setting
   for this model on real repo content (code + structured docs), only an
   assumption.
3. **A related failure mode was directly observed**: a judge model given
   two long, asymmetric documents in a single call lost track partway
   through ("Article 2 is not provided"). That's the same shape of failure
   a coding agent would hit trying to synthesize something from deep inside
   a single huge stuffed context.
4. **Sustained multi-turn sessions with varied prompts hit a separate
   silent-corruption bug** on this Ollama build (empty `content` on an
   apparently-successful response after roughly 2-15 varied calls),
   mitigated only by reloading the model before every single call (~17s
   tax per call, not a one-time fix). An interactive coding session
   (edit → ask → grep → ask again) is exactly the "many varied prompts in a
   row" pattern that triggers this.

Together, these argue that for the local-model path, retrieval (small,
targeted context per call) is a better fit than large-context stuffing —
the opposite of the Claude Code conclusion, and the reason this is worth
building even though "just grep" was the right call for the cloud-agent
path.

## Decisions

- **Build a narrow, purpose-built MCP docs-search server**, not a chat app
  and not the parked `ai-stack` rebuild.
- **Reuse `nomic-embed-text` via `framework.gibbsgreatly.xyz:11434`** —
  already pulled, already proven (PentAGI). No new embedding model.
- **Reuse `pgvector`** as the vector store — same reasoning, one fewer new
  service to operate than introducing Qdrant standalone.
- **Host in `ai_seg`**, following `mcp-utility-stack`'s trust model (typed,
  narrow tools; no internal infra credentials; read-only against the repo).
- **Index only the 378 tracked `.md` files** (`docs/**/*.md` excluding
  `docs/**/artifacts/`, plus every `STACK_CONTRACT.md` and `CLAUDE.md`) —
  never the transient log/transcript material that inflates `docs/`'s raw
  size.
- **Do not build until Phase 1 (below) passes.** Building retrieval
  infrastructure around a model whose large-context reliability is unproven
  on this exact kind of content would be solving the wrong problem if the
  actual failure turns out to be elsewhere (e.g. the repeated-prompt
  corruption bug, which retrieval doesn't fix by itself).

## Phases

### Phase 0 — Decisions (done, this doc)

Recorded above.

### Phase 1 — Validate Laguna S 2.1 reliability before building anything

**Done (2026-08-23) — result: blocking bug found, not a capacity number.**
Raw evidence (curl bodies, `ollama-server-log.txt`) under
`artifacts/phase1-2026-08-23/` (local-only, not this doc's concern to keep
forever — summarize further and delete per the cleanup rule once acted on).

**Method**: real repo content, not filler text — `STACK_CONTRACT.md` files
(20 stacks, exact known VMIDs as ground truth) sent to
`laguna-s-2.1:q4_k_m` on `framework.gibbsgreatly.xyz:11434`, asking the
model to extract every VMID it saw. Tested via both `/api/chat` and
`/api/generate`, streamed and non-streamed, at increasing sizes.

**Finding: Laguna S 2.1 on this Ollama build cannot currently generate any
response at all for real dense repo content above roughly 1-3K tokens —
this is a bug, not a context-size tradeoff.**

- Boundary observed: a single small `STACK_CONTRACT.md` (885 prompt
  tokens) succeeded cleanly (correct VMID answer). A single medium
  `STACK_CONTRACT.md` alone (3,343 prompt tokens) failed. Every larger test
  (2 files/~5.7K tokens, 6 files/~13.6K tokens, all 20 files/~25.8K tokens)
  failed the same way, at every `num_ctx` tried (16384 up to 65536 — not a
  context-size-too-small problem, confirmed by `prompt_eval_count` always
  fitting comfortably under the configured `num_ctx`).
- **Failure signature**: HTTP 200, but the response body is Ollama's Go
  zero-value struct (`{"model":"","message":{"content":""},"done":false}`
  or the `/api/generate` equivalent) — indistinguishable at the JSON level
  from the pre-existing "silent output corruption" bug in
  [[reference_ollama_corruption_and_reasoning_budget_bugs]], but this
  reproduces on the **first** call after a fresh `docker restart ollama`
  and on **every subsequent call above the ~3K token line**, not after 2-15
  varied prompts — a different trigger condition than previously
  documented, same symptom.
- **Server-side confirmation** (`ollama-server-log.txt`): the server does
  real work — prompt processing completes normally (e.g. "prompt
  processing, n_tokens = 13602, progress = 1.00"), the sampler initializes
  ("init_sampler... took 1.59 ms") — and then immediately: `srv stop:
  cancel task, id_task = 0`, before a single token is generated. The
  request is logged as `200` at the HTTP layer despite returning nothing.
- **Not fixed by streaming**: `"stream": true` against the same failing
  prompt produced zero NDJSON lines — same silent failure, just with no
  body at all instead of a zero-value JSON object.
- **Model-specific, not a whole-build issue**: the identical ~3.4K-token
  prompt sent to a different resident model
  (`eval-qwen3-coder-30b-a3b:q4_k_m`) succeeded normally (wrong answer —
  it missed the VMID — but a real, well-formed response, no corruption).
  This rules out "Ollama itself is broken right now" and points at
  something specific to Laguna S 2.1 (a 117.6B reasoning model that emits
  a separate `thinking` field — plausible connection to the task
  cancellation, not confirmed) or its specific GGUF/build.
- **Environment**: `ollama version 0.32.5`,
  `harbor.lab.gibbsgreatly.xyz/dockerhub/ollama/ollama:rocm` — a floating
  `:rocm` tag, not pinned to a specific release. Worth checking whether a
  newer/older pinned build changes this before assuming it's unfixable.

**Why this matters more than a missed capacity target**: the original
question was "how much context can Laguna S 2.1 hold reliably" so Phase 2
could size retrieval chunks against a real number. The actual answer is
that **basically nothing above trivial single-fact lookups works right
now** — this is below the size of a single meaningfully-sized retrieval
chunk, let alone 131K or 256K. It blocks the retrieval-based design in this
plan just as much as it blocks large-context stuffing; a RAG server handing
back even a few thousand tokens of matched context would hit the same wall
today. **This needs to be root-caused or worked around before Phase 2
proceeds** — it is now the actual blocker, not context size.

**Not done, deliberately out of scope for this pass** (time-boxed; hand off
as the next concrete task rather than open-ended debugging in this
session):

- Root-cause whether this is the `thinking`/reasoning-field handling,
  Ollama 0.32.5's context-checkpointing feature (every failing case logged
  creating a 2nd checkpoint — `create_check: ... checkpoint 2 of 32` —
  immediately before the cancel; correlation observed, not proven causal),
  or something specific to this GGUF.
- Try a pinned, different Ollama version.
- Check whether `eval-laguna-s2-1:q4_k_m-ctx131k` (the separately-tagged
  eval variant, different Modelfile params) reproduces the same failure —
  not tested, only the plain `laguna-s-2.1:q4_k_m`/`-ctx131k` tags were.
- The originally-planned **repeated-varied-prompt check** (Bug 1's own
  trigger condition) — not reached; the dense-content failure above is a
  lower, more urgent bar than the repeated-prompt one.

**Revised "done when"**: superseded — Phase 1 is done in the sense of
producing a real, evidence-backed result, but that result is "fix this
bug first," not a chunk-size number for Phase 2.

#### Correction: this is Ollama-specific, not a Laguna-the-model problem

The operator pushed back with real, contradicting evidence: Laguna S 2.1
worked well for them in VS Code via GitHub Copilot's custom-endpoint
feature, at large configured context (`maxInputTokens: 180000,
maxOutputTokens: 24000`). That run was against **llama.cpp's router
(`framework.gibbsgreatly.xyz:8080/v1/chat/completions`), not Ollama** — a
different server implementation entirely. This does not contradict the
finding above; it scopes it correctly.

Follow-up testing same-session:

- **Ollama's OpenAI-compatible endpoint (`/v1/chat/completions`) has the
  same bug**, not just the native `/api/chat`/`/api/generate` — a 3,326-
  token real prompt succeeded (wrong answer, but well-formed); a ~8.7K-
  token one (3 `STACK_CONTRACT.md` files) hit the identical zero-value
  degenerate response. So the corruption is a genuine Ollama-side issue on
  this build, reproducible regardless of which API surface a client uses
  — not an artifact of testing the "wrong" endpoint.
- **Attempted a direct llama.cpp comparison, blocked by real environment
  gaps, not declined**: `framework:8080` isn't currently running (GPU
  exclusivity here is manual — confirmed via `ss -tlnp`/`docker ps`, only
  Ollama is up). The router-mode build this project's own
  `llamacpp-router-mode-deployment.md` documents
  (`/opt/llama.cpp/build-hip/bin/llama-server`) no longer exists on this
  host, and neither do the split GGUF files
  (`Laguna-S-2.1-UD-Q4_K_M-00001-of-00003...`) the operator's working
  config pointed at. The only `llama-server` binary present
  (`/usr/local/lib/ollama/llama-server`, Ollama's own bundled copy) is
  **CPU-only** ("no usable GPU found... compiled without GPU support") and
  **fails to load the current merged GGUF** that does exist
  (`/storage/models/llm/Laguna-S-2.1-UD-Q4_K_M-merged.gguf`) with
  `missing tensor 'blk.0.attn_g.weight'` — a real tensor-layout mismatch,
  not a config error on this attempt. The process exited immediately on
  its own; nothing was left running, no GPU/memory contention caused.
- **Net effect**: the environment that produced the operator's good
  real-world result no longer exists on `framework` in a form this session
  could quickly stand back up. A fair llama.cpp-vs-Ollama comparison for
  this specific question needs an actual rebuild task, not a quick restart.

**Revised recommendation**: don't treat "Ollama is the right backend for
Laguna" (the BFCL tool-calling result) as settling the large-context
question too — those are different capabilities, and the one that matters
for this project (reliably reading a big stuffed/retrieved context) is the
one that's currently broken on Ollama and unverified-but-previously-good
on llama.cpp. Options going forward:

1. **Rebuild a GPU-enabled llama.cpp router on `framework`** (production
   node — needs its own approval/task) and re-run this exact test against
   it, to get a real like-for-like comparison instead of relying on old,
   no-longer-reproducible experience.
2. **Root-cause the Ollama corruption bug** directly (the `thinking`-field/
   context-checkpointing leads above) if Ollama's tool-calling edge is
   worth keeping for the agentic-loop role specifically.
3. **Split roles instead of picking one winner**: llama.cpp for large-
   context reads (RAG-retrieved chunks, doc synthesis), Ollama only for
   short tool-calling turns where its BFCL edge actually applies — avoids
   betting the whole design on either backend being the answer to both
   questions at once.

Not decided yet — needs operator input on how much effort to put into
option 1 before choosing 2 or 3.

#### Second correction: narrowed to Laguna-specific, likely the local GGUF/import — not Ollama itself

The operator pushed back again, correctly: "Ollama is broken on real
content over ~3-9K tokens" would be an enormous, widely-known bug for
software this widely used, and the framing above didn't survive that
scrutiny. Ran the missing control test and researched what's actually
different about this model:

- **Control test**: sent the identical 13.8K-token real-content prompt
  (the exact 6-file case that broke Laguna) to a mainstream model already
  on this same server (`eval-qwen3-coder-30b-a3b:q4_k_m`, Qwen3 MoE) via
  the same endpoint. **It returned a clean, well-formed response** —
  wrong/hallucinated VMIDs (a capability miss, not a corruption), but real
  content, `finish_reason: "stop"`, no zero-value struct. This directly
  rules out "Ollama is broken on this host for dense content generally" —
  the same server, same endpoint, same content size, different model,
  works fine.
- **What Laguna actually is**: confirmed via web search — a real, publicly
  released model (Poolside AI, 118B MoE,
  [poolside/Laguna-S-2.1 on HuggingFace](https://huggingface.co/poolside/Laguna-S-2.1)),
  with a genuine official Ollama library entry
  ([ollama.com/library/laguna-s-2.1](https://ollama.com/library/laguna-s-2.1))
  — not a private hack. But it is **brand new** and uses its own dedicated
  `RENDERER laguna` / `PARSER laguna` code path (confirmed via `ollama show
  laguna-s-2.1:q4_k_m --modelfile`) — genuinely newer, far less battle-
  tested code than the mainstream template path the control model above
  uses.
- **The likely local-usage factor**: the GGUF actually loaded on
  `framework` is `/storage/models/llm/Laguna-S-2.1-UD-Q4_K_M-merged.gguf`
  — the `UD` naming convention is associated with **Unsloth Dynamic**
  quantization, a third-party community conversion pipeline, not
  confirmed to be Ollama's own vendor-published artifact. The local
  Ollama manifest structure (`ollama show --modelfile` resolving `FROM` to
  a local blob path) is consistent with either a real `ollama pull` or a
  manual `ollama create -f Modelfile` import from that locally-placed
  file — **not fully distinguishable from manifest inspection alone**, so
  this is a strong circumstantial lead, not proven.

**Revised, better-calibrated conclusion**: this is not "Ollama is broken."
It's most plausibly the intersection of (a) a genuinely new,
less-hardened Ollama code path specific to this one very new model
architecture, and (b) possibly a third-party GGUF/quantization that isn't
Ollama's own tested artifact. Both point at the same next step.

**Decisive next test, not yet run (needs approval — new ~73GB download +
model registration on `framework`, a production node)**: `ollama pull
laguna-s-2.1:q4_k_m` fresh from Ollama's own official registry (1019G free
on `/storage`, no disk concern) and re-run the identical 13.8K-token test
against *that* artifact.

- If clean → confirms the locally-imported third-party GGUF is the actual
  cause, not Ollama or the model architecture itself.
- If it still corrupts → narrows to "very new architecture support,
  genuinely immature in Ollama today" — worth reporting upstream, but
  still not a broad Ollama indictment, since the control model proved the
  rest of this exact deployment is fine.

#### Resolved (2026-08-23): confirmed — the locally-imported third-party GGUF was the cause

Ran the decisive test. Before pulling, tagged the existing local artifact
as `laguna-s-2.1:q4_k_m-local-import-backup` (digest `3f4a1d200dc328ab...`,
73GB) so nothing was lost. `ollama pull laguna-s-2.1:q4_k_m` fetched
Ollama's own official artifact (digest `1adabf138c90af2b...`, 96GB — a
genuinely different build, not just a re-tag) — the pull stalled once
near the end (93/96GB, connection throttled to <1MB/s) and needed one
`docker restart ollama` + reissue to resume from the cached partial data
and finish at full speed; no data lost, confirms Ollama's pulls are
properly resumable.

**Re-ran the identical tests against the official artifact — both clean:**

- 6-file / 13.6K-token prompt: real response, **all 6 VMIDs reported,
  6/6 correct** against ground truth — better than the mainstream control
  model's mostly-hallucinated attempt at the same size.
- Full 20-file / 25.8K-token prompt (the one that failed every previous
  attempt, at every size, on the local-import artifact): real response,
  **17/17 VMIDs reported were exactly correct**, only one stack
  (`secpipe-stack`) omitted from the list entirely — a completion miss,
  not a hallucination or corruption. `finish_reason: "stop"`,
  `prompt_tokens: 25779`.

**Conclusion, fully confirmed, not just plausible**: the corruption was
caused by the locally-imported third-party (`UD` / Unsloth Dynamic-style)
GGUF conversion this deployment had been running under the
`laguna-s-2.1:q4_k_m` tag — not Ollama, not the Laguna architecture, not
this project's general local-AI setup. Ollama's own official artifact is
reliable and highly accurate on real dense repo content at least up to
25.8K tokens, tested at the actual scale a retrieval-based design would
use. The operator's instinct to push back on "Ollama is broken" was
correct at every step of this investigation.

**Follow-up housekeeping**:

- **Done (2026-08-23)**: `laguna-s-2.1:q4_k_m-ctx131k` and
  `eval-laguna-s2-1:q4_k_m-ctx131k` rebuilt via `ollama create -f
  Modelfile` with `FROM laguna-s-2.1:q4_k_m` (the new official base) +
  their original `PARAMETER num_ctx 131072` (and, for the `eval-` tag,
  `num_predict 8192`) preserved. Both now carry new manifest digests
  (`4524d1c4dfcfbc8f...` / `ce5f795eda8b9f47...`) built from the official
  blob's existing layers (no re-download — `ollama create` reused the
  already-pulled layers), verified loadable and responsive via a smoke
  test. `eval-laguna-heretic:i1-q4_k_m-ctx131k` is a different, deliberately
  distinct fine-tune ("Heretic") — left untouched, not assumed affected or
  unaffected without its own test.
- `laguna-s-2.1:q4_k_m-local-import-backup` (the original 73GB local
  import) is kept for now in case a future test needs to reproduce the
  original bug directly; delete once no longer needed.
- Phase 1's original goal is now actually met: Laguna S 2.1, on Ollama's
  official artifact, reliably handles real dense repo content at least to
  ~26K tokens with high accuracy. **Phase 2 (design the docs-rag MCP
  server) can proceed** — no longer blocked. Testing above 26K tokens
  (toward 131K/256K) is still open if the operator wants a real ceiling
  number rather than "at least 26K, no observed limit yet."

### Phase 2 — Design the docs-rag MCP server

**Done (2026-08-23).** Design only — nothing built (that's Phase 3).

#### Tool surface

Resolves the "separate `search_stack_contracts` tool?" open question:
**no, fold it into one tool via a filter parameter** — narrower surface,
consistent with `mcp-utility-stack`'s "typed, narrow tools" philosophy,
and a second near-identical tool would just be `search_docs` with a
`WHERE` clause pre-applied.

- **`search_docs(query: str, k: int = 8, stack: str | None = None) ->
  list[{file_path, heading_path, stack_name, chunk_text, score,
  last_modified}]`** — the one tool. `stack` filters to a single stack's
  `STACK_CONTRACT.md` (and any `docs/<stack>-stack/` material) when the
  caller already knows which stack it's asking about, e.g. from a filename
  it's editing.
- **`list_stacks() -> list[str]`** — cheap affordance so an agent can
  discover valid `stack` filter values instead of guessing spellings.

#### Chunking strategy

By heading/section, not fixed-size — these docs are structured prose
(every `STACK_CONTRACT.md` has the same Purpose/Network/Inputs/Provides/
Dependencies/Persistent State/"What Must Not Be Edited Casually"/Playbook
shape), and losing that structure would make retrieval worse than grep,
not better:

- One chunk per markdown section (heading to next same-or-higher-level
  heading). A `STACK_CONTRACT.md`'s natural sections map directly to
  chunks.
- Cap ~1,500 tokens per chunk; a section over that gets sub-chunked by
  paragraph, with the full heading breadcrumb re-prepended to each
  sub-chunk so it's never returned without its structural context.
- Every chunk's embedded text is prefixed with its heading breadcrumb
  (e.g. `ai-services-stack > STACK_CONTRACT.md > What Must Not Be Edited
  Casually`) — the breadcrumb is part of what gets embedded, not just
  returned metadata, so semantically-similar sections in different stacks
  don't collide in vector space.
- Given Phase 1's confirmed reliable ceiling (~26K tokens, clean and
  accurate, no failure observed), a `k=8` result set at ~1,500 tokens/chunk
  is ~12K tokens worst case — comfortably inside the validated range with
  headroom for the agent's own prompt/instructions on top.

#### Storage schema (pgvector)

Reusing PentAGI's proven `nomic-embed-text` (768-dim) + `pgvector`
pattern, but as **this stack's own container and schema** — not sharing
PentAGI's instance, which is that stack's private task memory, a different
concern entirely.

```sql
CREATE TABLE doc_chunks (
  id            SERIAL PRIMARY KEY,
  file_path     TEXT NOT NULL,
  stack_name    TEXT,                 -- derived from path, NULL if not stack-scoped
  heading_path  TEXT NOT NULL,        -- "H1 > H2 > H3" breadcrumb
  chunk_text    TEXT NOT NULL,
  chunk_tokens  INT NOT NULL,
  content_hash  TEXT NOT NULL,        -- sha256 of chunk_text, change detection
  file_mtime    TIMESTAMPTZ NOT NULL,
  embedding     VECTOR(768) NOT NULL,
  indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON doc_chunks USING ivfflat (embedding vector_cosine_ops);

CREATE TABLE file_index (              -- drives incremental reindex
  file_path     TEXT PRIMARY KEY,
  content_hash  TEXT NOT NULL,         -- sha256 of whole file
  last_indexed  TIMESTAMPTZ NOT NULL
);
```

#### Embedding pipeline

- Index time: for each new/changed chunk, `POST
  http://framework.gibbsgreatly.xyz:11434/api/embed` with model
  `nomic-embed-text`, store the 768-dim vector.
- Query time: embed the incoming query the same way, then `ORDER BY
  embedding <=> query_vector LIMIT k`.
- No new model, no new egress rule — `ai_seg → framework:11434` already
  exists for `ai-services-stack`'s own Ollama use.

#### Reindex mechanism — corrected: Ansible-copied corpus, not an in-container git pull

**First pass (superseded) proposed the container doing its own periodic
`git pull`.** That needs a new credential this LXC doesn't have: the repo
is private, so an in-container clone/pull needs a read-only GitHub deploy
key or PAT provisioned and stored in SOPS — a real new secret/trust
surface for a stack whose entire selling point (in the trust-level
comparison above) is holding no credentials.

**Corrected**: follow the exact pattern already used for
`cve-mcp-server`'s own source in this same playbook — `ansible.builtin.
copy` pushes the corpus (`docs/**/*.md` excluding `docs/**/artifacts/`,
every `STACK_CONTRACT.md`, `CLAUDE.md`) from the Ansible controller (which
already has the full repo checked out) into the LXC at deploy time. No
git credential, no new egress, no new inbound exposure.

- Reindexing then runs **once, at container startup**, over whatever
  corpus was just copied in — hash each file against `file_index`,
  re-chunk/re-embed only what changed, delete chunks for removed files.
  No internal scheduler needed: the corpus is static between deploys, so
  a periodic in-container rescan would find nothing new anyway.
- Refreshing the index is a normal `scripts/provision.sh --stack
  mcp-utility-stack` re-run — the same update mechanism every other stack
  in this repo already uses, not a new autonomous-reconciliation concept.
- `indexed_at` still gets surfaced in query results, so an agent can tell
  if a hit might predate a very recent edit it's making that hasn't been
  provisioned yet.

#### Implementation pattern

Python, following `cve-mcp-server`'s existing shape in this repo: MCP
Streamable HTTP endpoint (`/api/mcp`), no auth (network-level access
control via the same MikroTik-rule posture as `mcp-utility-stack` — this
tool holds no credentials, only read access to public repo docs, so that
posture is appropriate here too). One Docker Compose stack, three
containers: the MCP/query server, the reindex job (scheduled in-process or
a sidecar cron), and `pgvector`.

#### Stack identity — corrected: fold into `mcp-utility-stack`, not a new LXC

**First pass (below, superseded) proposed a new dedicated `coding-stack`
LXC/VMID.** The operator asked directly whether this should reuse the
existing AI-tooling LXC, which prompted re-checking this repo's own
stated convention in `docs/mcp-stack/plan.md`: *"One LXC per individual
adapter would be over-fragmented relative to every other stack in this
repo"* — services get bundled into one LXC when they share a trust level,
not split one-per-tool.

**Does docs-rag share `mcp-utility-stack`'s trust level?** Yes, and it's
if anything a lower-risk member of the same class:

| | `mcp-utility-stack` (`cve-mcp-server`, existing) | docs-rag (this project) |
|---|---|---|
| Internal infra credentials | None | None |
| Internet egress | Broad, named CVE/threat-intel APIs | Narrow — just the git host, plus `framework:11434` (already open for `ai-services-stack`) |
| Content trust | Untrusted (external CVE text — a real prompt-injection surface) | Trusted (the operator's own repo) |
| Purpose | MCP tools for agents | MCP tools for agents |

`ai-services-stack` (OpenWebUI+SearXNG) was **not** the reuse candidate
here — that's a human chat UI and its search backend, a different
audience/purpose than an agent-facing MCP tool, a worse trust/purpose
match than `mcp-utility-stack`.

**Corrected decision**: fold docs-rag into the existing `mcp-utility-stack`
LXC (VMID `50011`) as two more Compose services — the MCP query server
(its own port, e.g. `8001`, alongside `cve-mcp-http`'s `8000`) and
`pgvector` — rather than a new dedicated LXC. No new VMID, no new zone
entry, no new firewall rule beyond what's already open.

**Honest tradeoff, not a blocker**: `pgvector` is a genuinely new,
persistent, stateful component — `mcp-utility-stack` today only carries a
small SQLite cache + rotating audit log, with `docker_storage` sized at
just 5G (confirmed in its `STACK_CONTRACT.md`). That volume needs
resizing for Phase 3, and the new pgvector data deserves its own row in
`mcp-utility-stack`'s `STACK_CONTRACT.md` Persistent State table when
built — but this doesn't disqualify bundling, it's just a real change to
account for.

**Superseded (kept for the record, not the current plan)**: the original
proposal was a new stack named `coding-stack`, its own `ai_seg` VMID
`50014` (`50010` harness-target, `50011` mcp-utility-stack, `50012`
secpipe-stack, `50013` ai-services-stack were the existing occupants).
Not used — see correction above.

### Phase 3 — Build and deploy

**Code built (2026-08-23); live infra validation deliberately deferred.**

Built on branch `feat/docs-rag-mcp`:

- `terraform/lxc/ansible/files/docs-rag-mcp/` — the actual application:
  `chunking.py` (heading-based, verified against a real
  `STACK_CONTRACT.md` — 10 correctly-scoped sections, correct
  breadcrumbs), `embeddings.py` (`nomic-embed-text` via the existing
  Ollama endpoint), `db.py` (`pgvector` storage, fixed two real bugs found
  during review: missing `::vector` casts on bound parameters, and an
  over-complicated manual statement-splitter in `ensure_schema()` that
  asyncpg's `execute()` already handles natively for multi-statement
  scripts), `reindex.py` (incremental, hash-based), `server.py`
  (`search_docs`/`list_stacks` tools).
- `terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml` — extended
  (not replaced) to also build/deploy `docs-rag-mcp` + pull `pgvector`
  through Harbor, copy the corpus from the controller's own checkout, and
  health-check port `8001`.
- `terraform/lxc/stacks/mcp-utility-stack/stack.yaml` — `memory`/`swap`/
  `docker_storage_size` grown (1024→2048 / 512→1024 / 5G→15G) for the two
  new services, new `docs-rag-mcp-http` `provides` entry.
- `terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md` — updated:
  new Inputs/Provides/Persistent State rows, and explicit "What Must Not
  Be Edited Casually" entries for the corpus being a point-in-time copy
  and port `:8001` having no firewall rule yet.
- New SOPS secret `DOCS_RAG_POSTGRES_PASSWORD` (internal-only, no
  published host port).

**Validated so far, without touching any live infrastructure**:

- `ansible-playbook --syntax-check` passes on the modified playbook.
- The embedded `docker-compose.yml` Jinja template renders to valid YAML
  with all three services (`cve-mcp-server`, `pgvector`, `docs-rag-mcp`)
  and both volumes correctly formed (checked by rendering it standalone
  with placeholder values and parsing the result).
- The actual `docs_rag_mcp` server code was smoke-tested end-to-end
  against the real, currently-installed `mcp` Python SDK (v2.0.0) — this
  mattered: the SDK's current API (`mcp.server.mcpserver.MCPServer`,
  `Context`, a `lifespan` async context manager, `TransportSecuritySettings`
  for the Host-header allowlist) is a real, meaningfully restructured
  surface from the older `FastMCP` API a first draft assumed, verified by
  actually installing the package and inspecting it rather than trusting
  memory. Confirmed via a `Starlette` `TestClient` round-trip (initialize
  → `tools/list` → `tools/call`) against a stubbed DB/embedding backend:
  the full MCP handshake, tool registration, and a `search_docs` call all
  worked and returned correctly-shaped results.

**Superseded below**: the operator clarified the real target was `pve`
(production), not `pve-test-vm` — `mcp-utility-stack`/`cve-mcp-server`
actually lives on `pve`. Full live deployment happened there instead; see
"Deployed live on `pve` (2026-08-24)" below for the real outcome and every
bug this surfaced.

#### Deployed live on `pve` (2026-08-24) — full success, four real bugs found and fixed

Ran the complete Preflight → approval → `TASK_APPROVAL` +
`./with-secrets-prod` flow against `pve` (confirmed live beforehand:
`cve-mcp-server` already answering on `:8000`). The harness's own
auto-mode Bash classifier blocked mutating commands even after in-chat
approval (a known, separate gate from `CLAUDE.md`'s own flow); the
operator ran each mutating command themselves in their own terminal after
being handed the exact command, and outcomes were verified via read-only
checks after each step.

**Step 1 — storage resize.** `terragrunt plan` revealed growing
`docker_storage_size` (5G→15G) the way `stack.yaml` declared it would
**force-replace the entire live production container** (Terraform's
`mount_point.size` change isn't resizable in-place at the provider level).
Used the repo's existing safe path instead:
`scripts/resize-lxc-mount.sh` (live `pct resize`, no container
disruption) — but it was still broken for stacks already migrated to the
per-environment Terragrunt layout: it hardcoded the legacy
`terraform/lxc/stacks/<name>/inventory.yml` path instead of checking
`terraform/lxc/environments/<env>/<name>/inventory.yml` first, the same
`ENV_ROOT`-first pattern `provision.sh` already uses. Fixed the script,
confirmed the resolved path locally, operator re-ran it successfully.
`terragrunt plan` afterward showed the mount-size diff gone and the
container as a safe in-place update.

**Step 2 — memory/swap, deliberately not applied.** Even scoped with
`terragrunt apply -target=...container.docker_host`, Terraform pulled in
`null_resource.configure_network_sdn_attachment` as a dependency. Its
replacement runs `destroy-network-sdn-vnet.yml` on the "destroy" half,
which has its own safety guard (`network_sdn_allow_destroy`) that
correctly refused — a real, working safety net, not a bug to route
around. Root cause: an unrelated, pre-existing drift (a `"network_sdn_
vmid"` key disappearing from a generated vars file) forces this stack's
SDN-attachment resource to want replacing on *any* apply right now,
regardless of what triggered the apply. Operator chose to revert the
memory/swap bump in `stack.yaml` (back to 1024/512) rather than
investigate that unrelated issue as a side quest — the resize (the part
that actually mattered) was unaffected and already done. The SDN drift is
a legitimate, separate finding for whoever picks it up next.

**Step 3 — the actual deploy, three more real bugs found via live runs,
not caught by syntax-check or local smoke tests:**

1. **`.terragrunt-cache/` pollution**: the `STACK_CONTRACT.md` discovery
   `find` recursed into Terragrunt's own working-directory caches, which
   hold full nested copies of the stacks tree — inflated 20 real files
   into 343 matches, several levels deep. Fixed with the same
   `rejectattr('path', 'search', ...)` pattern already used for
   `artifacts/`.
2. **`ansible.builtin.copy` doesn't create missing parent directories**:
   every `STACK_CONTRACT.md` copy failed with "Destination directory ...
   does not exist." Fixed by creating every unique destination directory
   first — but that fix was itself incomplete the first time:
3. **`ansible.builtin.file` only sets `mode` on the *leaf* directory it
   creates**, not intermediate ancestors it implicitly creates along the
   way. `corpus/terraform`, `corpus/terraform/lxc`, and
   `corpus/terraform/lxc/stacks` (none of which are any file's *immediate*
   parent, only ancestors of one) silently ended up at a restrictive mode
   from an earlier run, blocking the container's non-root user from ever
   traversing into the correctly-mode'd leaf directories — the reindex
   ran, found 0 files under `terraform/`, and reported success anyway
   (`{'failed': []}`), which is its own lesson: a "successful" reindex
   summary doesn't prove the corpus was actually reachable. Confirmed via
   `docker exec ... find /corpus/terraform` returning "Permission denied"
   despite the leaf directory itself showing `755`. Fixed by computing the
   full ancestor closure (every path prefix, not just immediate parents)
   and explicitly setting `mode` on every level.
4. **`DOCS_RAG_ALLOWED_HOSTS` never included `127.0.0.1:8001`**: the
   in-LXC Ansible health check hits the container over loopback, which
   the `mcp` SDK's DNS-rebinding protection correctly rejected with `421`
   — a status not in the accepted-codes list, so the wait task always
   timed out even though the server was healthy. Fixed by adding
   `127.0.0.1:8001` to the allowlist rather than loosening the accepted
   status codes (keeps the actual DNS-rebinding protection meaningful).

**Final verified state, real data, real queries, no stubs**:

- `list_stacks` returns all 20 real stack names.
- `search_docs` (unfiltered) returned real, correctly-ranked chunks from
  genuine docs about cross-stack VMID/zone inventories.
- `search_docs` with `stack="ai-services-stack"` correctly scoped to just
  that stack's `STACK_CONTRACT.md`, returning its real Dependencies and
  Provides sections with accurate `heading_path`/`score`.
- Incremental reindex confirmed working as designed: a `docker restart`
  after the permission fix reported `{'total_files': 401, 'changed': 20,
  'unchanged': 381}` — exactly the 20 previously-invisible
  `STACK_CONTRACT.md` files newly indexed, the other 381 correctly
  skipped as unchanged.

**docs-rag-mcp is now genuinely live on `pve`**, alongside `cve-mcp-server`,
serving real semantic search over this repo's documentation.

### Phase 4 — Index and wire up

**Done (2026-08-24) — confirmed working end-to-end from a real VS Code
Copilot Chat Agent-mode session, not just direct MCP client tests.**

**Firewall**: `:8001` had no MikroTik inbound rule (Phase 3 deliberately
left this out of scope). Read the live rule set first rather than guess —
found the existing `:8000` precedent (`*50`/`*51`, `lan`/`pentest_seg` →
the *whole* `ai_seg` subnet, not host-scoped — a documented imprecision
per `pve-test-vm.yaml`'s own comments) plus a correctly host-scoped
precedent (`*5D`, PentAGI's dedicated `cve-mcp-server` rule). Added two
new rules mirroring the *correct* (host-scoped) pattern, `place-before`
the zone's own `*53` ("ai_seg explicit deny — everything else") anchor,
resolved dynamically via `[find comment="..."]` rather than a fragile
numeric position:

```text
lan -> mcp-utility-stack docs-rag-mcp 8001         192.168.1.0/24  -> 192.168.50.10:8001
pentest_seg -> mcp-utility-stack docs-rag-mcp 8001 192.168.70.0/24 -> 192.168.50.10:8001
```

Operator applied both via the RouterOS CLI (outward-facing production
mutation, handed the exact commands rather than run directly — same
harness-classifier reasoning as Phase 3). Verified live afterward, twice:
read-only re-query of the MikroTik REST API showed both rules present and
correctly ordered before `*53`; a direct `curl` from the workstation to
`http://192.168.50.10:8001/mcp` returned the MCP server's own JSON-RPC
`"Missing session ID"` error (not a timeout, not a 421) — proof the
packet reaches the app, not just the network layer.

**VS Code wiring — two real config bugs found and fixed, unrelated to
`docs-rag-mcp` itself:**

1. `~/.config/Code/User/chatLanguageModels.json` (Copilot's custom-model/
   BYOK config) still pointed at `framework:8080` (llama.cpp — not
   currently functional, per Phase 1) and at
   `Laguna-S-2.1-UD-Q4_K_M-00001-of-00003`, the exact locally-imported
   third-party GGUF that Phase 1 proved was the corruption root cause.
   Also declared `maxInputTokens: 180000` — never tested at any size
   near that. Corrected to Ollama's real endpoint (`:11434`), the
   official rebuilt `laguna-s-2.1:q4_k_m-ctx131k` tag, and
   `maxInputTokens` reset to 24000 (matching what Phase 1 actually
   validated), `maxOutputTokens` to 8000.
2. `.vscode/mcp.json` didn't exist yet — created it, registering
   `docs-rag` as an `http` server at `docs-rag-mcp`'s real address.

**A third bug, in VS Code's Copilot Chat extension itself, not this
project's config**: the first live Agent-mode message crashed with
`"No lowest priority node found (path: Gte)"` — a known, long-running bug
class in the extension's prompt-tsx renderer/token-budget pruner (10+
tracked issues on `microsoft/vscode-copilot-release` going back to
`#5903`, not specific to `docs-rag-mcp` or even to custom/BYOK models —
one report ties a recurrence to Claude models plus history
summarization). Registering `docs-rag-mcp`'s tool schemas into that same
prompt tree, against the tight `maxInputTokens: 24000` budget, is a
plausible trigger. Mitigated by raising `maxInputTokens` to 110000 (still
well inside the `-ctx131k` tag's real 131,072-token window, leaving
~13K headroom) — explicitly **not** a claim that output is
validated-accurate at that input size, only that it removes a plausible
crash trigger for Copilot's own renderer.

**Confirmed actually working, twice, with different outcomes worth
recording honestly:**

- First real attempt (after the crash fix): the model answered correctly
  but via VS Code's *built-in* `search`/`read` tools, not `docs-rag-mcp`
  — a legitimate outcome (matches this project's own stated reasoning for
  *not* building this for Claude Code/Codex — native tools already
  suffice at this corpus size for a capable-enough agent loop), but not a
  test of what we built.
- Disabling the built-in `search`/`read` tool categories didn't force the
  issue either — the model fell back to shell `find`/`grep` via the
  `execute` tool category instead.
- Explicit `#search_docs` tool-reference syntax did force it: trace shows
  `Ran search_docs — docs-rag (MCP Server)` with a real query and `k=15`,
  alongside (not instead of) several native search/read calls — the model
  doesn't yet treat the MCP tool as primary, just as one option it will
  use when directed. The resulting answer was substantively correct and
  well-grounded in the real retrieved content, with one small invented
  detail (a wrong example LAN IP, `192.168.50.11` vs. the real
  `192.168.50.10`) — a reminder that grounded retrieval reduces but
  doesn't eliminate small confabulations.

**Net result**: the full chain — VS Code Agent mode → Laguna S 2.1 via
Ollama → `docs-rag-mcp` → `pgvector` → grounded answer — is confirmed
live and working. Whether Copilot's own tool-selection reaches for it
*without* being told to is a separate, still-open question — see Phase 5.

### Phase 5 — Iterate

**Auto-reindex on doc commits — done (2026-08-25).** The manual-refresh
model (Phase 2/3: reindex only via an explicit `provision.sh` re-run) was
a deliberate design choice at the time, but it also meant staleness was
easy to hit by accident — exactly what happened testing Phase 4. The
operator's call: refreshing `docs-rag-mcp`'s corpus/index is a *data*
housekeeping action, not an infra mutation, so it doesn't need CLAUDE.md's
per-task production-mutation approval the way a real infra change would
(same reasoning already applied elsewhere to e.g. Harbor's scheduled
repull).

- `scripts/git-hooks/post-commit-docs-reindex.sh` + `scripts/
  install-git-hooks.sh` (tracked, symlinked into `.git/hooks/post-commit`
  by the installer since `.git/hooks/` itself isn't version-controlled).
  On any commit touching `docs/**/*.md`, a `STACK_CONTRACT.md`, or
  `CLAUDE.md`, it backgrounds a `provision.sh --stack mcp-utility-stack`
  run and logs to `/tmp/docs-rag-reindex-<timestamp>.log`.
- **Two real bugs found getting this working, not just theoretical
  risk:**
  1. First version used `./with-secrets` (this repo's default
     *development* wrapper, targets `pve-test-vm`) instead of
     `./with-secrets-prod` (targets the real `pve` where `docs-rag-mcp`
     actually runs) — every run failed with `No route to host` against
     `pve-test-vm`'s address. Fixed; `TASK_APPROVAL` is set to a fixed
     value inside the hook itself, matching the operator's explicit
     housekeeping-not-infra call above.
  2. Deeper bug, in the underlying playbook, not the hook: `docker
     compose` never restarts a container over a bind-mount *content*
     change alone (no config diff to detect) — so `provision.sh` could
     report full success while the corpus file changed on disk and the
     running container's `pgvector` index stayed stale, silently, same
     failure shape as a Phase 3 bug recurring for a new reason. Fixed in
     `deploy-mcp-utility-stack.yml`: the corpus-copy task now registers
     its result, and an explicit `docker_container` restart (plus a
     post-restart health re-check) fires only when at least one file
     actually changed.
- **Verified live, three layers deep, not just "the ansible run
  succeeded":** hook fired (log created) → `provision.sh` completed
  against real `pve` (`failed=0`) → a direct `psql` query against
  `docs-rag-pgvector` returned the actual just-committed
  `STACK_CONTRACT.md` text (the `:8001` MikroTik-rule wording from
  earlier in this same phase) as an embedded, retrievable chunk. Confirms
  the whole chain — commit → hook → `provision.sh` → corpus copy →
  restart → reindex → `pgvector` → `search_docs` — actually works, not
  just that each individual step looked fine in isolation.

- Whether Copilot's/the model's own tool-selection reaches for
  `search_docs` unprompted, or only when explicitly `#`-referenced, is
  still open — Phase 4 only forced one confirmed real call via explicit
  reference. Worth watching across real coding sessions rather than
  engineering further right now.
- Revisit chunk size / retrieval count against Phase 1's measured
  reliable-context number if either the model or the Ollama build
  changes.
- If the Copilot Chat "No lowest priority node found" crash (Phase 4)
  recurs even with the larger `maxInputTokens`, that's an upstream
  extension bug (see Phase 4's tracked-issue list) — not something to
  chase further in this project.

### Phase 6 — Reliability proxy + regression canary

**Done (2026-08-25), both built and verified live, not just designed.**
Prompted by "is there anything else we can set up to empower local models
to work well with this project" — the answer that mattered wasn't more
housekeeping, it was addressing two *documented, repeated* real failure
classes head-on rather than building more speculative surface:

1. **This project's own history shows real, recurring Ollama corruption**
   (degenerate empty responses, dense content degenerating into `?`
   garbage, mitigated only by reloading the model) — and Copilot talks to
   Ollama's OpenAI-compat endpoint directly, with zero protection against
   any of it.
2. **Everything validated in this doc is a snapshot.** Ollama updates,
   GGUF re-imports, VS Code Copilot updates, and this repo's own docs
   drifting have all independently broken parts of this chain before,
   silently, until someone hit it in a real session.

**`scripts/ollama-reliability-proxy/`** — a small stdlib-only Python
proxy between any Ollama consumer and `framework:11434`. Forces the
upstream call non-streaming so the full response can be validated before
the caller ever sees it; on a detected degenerate response (empty
content, or >50% `?`-character content — real patterns from this
project's own history, not hypothetical), unloads the model
(`keep_alive: 0`) and retries once before ever handing anything back.
Verified live standalone first: normal passthrough, streaming-response
SSE-wrapping, the detection function correctly classifying real bug
patterns without false-positiving on legitimate content (including
genuine question marks), the unload call succeeding against real Ollama,
and a full unload→reload→correct-answer cycle actually completing
(~23s, matching the previously-documented reload cost). One real,
deliberate tradeoff: streaming responses arrive as a single chunk, not
token-by-token — traded for being able to validate before ever showing
the user anything.

**Centralized on `ai-services-stack`, not left as a per-workstation
process (2026-08-25, operator's explicit call).** First built and tested
as a workstation-local `systemd --user` service, purely for VS Code
Copilot's benefit. The operator correctly pushed back: Ollama's
corruption bugs affect every consumer, not just Copilot, and
`ai-services-stack`'s own `OpenWebUI` is itself a direct Ollama consumer
that would otherwise get none of this protection. Moved into
`deploy-ai-services-stack.yml` as a real Docker Compose service
(`ollama-reliability-proxy`, built from the same `proxy.py`, no build
step — bind-mounted into a plain `python:3.12-slim` image), with
`OpenWebUI`'s own `OLLAMA_BASE_URL` repointed through it internally.
Published on the LXC host (`192.168.50.11:11435`) for external
reachability too (VS Code Copilot from the workstation), gated by a new
host-scoped MikroTik rule (`lan → 192.168.50.11:11435`), same pattern as
`docs-rag-mcp`'s `:8001` rule.

**A real, unrelated bug found and fixed along the way, not glossed
over**: deploying this re-exercised `ai-services-stack`'s existing
"verify all managed LLM routes" task, which had a stale hard/soft
requirement split — `llamacpp` was originally (2026-08-02) the one hard
requirement, back when it was the actively-used backend. It failed the
whole deploy when `llamacpp-router` turned out to be genuinely down on
`framework` (confirmed directly, not assumed — a real
`ConnectionRefusedError`, same fact Phase 1 of this doc already
established). **Not a regression from this work** — a pre-existing,
already-stale assumption this deploy just happened to be the first to
re-trigger. Fixed by reversing which routes are hard vs. soft: Ollama
(the actively-used backend today) is now the hard requirement,
`llamacpp`/LM Studio are soft/warning-only — kept fully configured and
documented, not removed, since the operator wants to be able to come back
to them later. Re-ran clean afterward (`failed=0`), and confirmed
directly inside the `openwebui` container that both soft routes warn
correctly (`llamacpp`: connection refused; LM Studio: `502`, a separate
pre-existing known issue) while Ollama, via the new proxy, correctly
returns its full real model list (19 models).

**`scripts/local-ai-canary/`** — a small regression check (not a full
eval battery) against four facts this pipeline should always be able to
reproduce: `list_stacks` includes a known stack subset, `search_docs`
correctly surfaces two specific known facts (the `127.0.0.1:8001`
allowed-hosts requirement and the `*78`/`*79` MikroTik rule IDs — both
things this exact conversation already proved were retrievable), and the
model answers a deterministic arithmetic prompt correctly through the
reliability proxy (now pointed at the centralized address). **Verified
both directions, not just the happy path**: all four pass against the
live pipeline, and killing the reliability proxy correctly produces one
clear `[FAIL]` (connection refused) while the three independent MCP
checks still correctly pass — proving the canary actually discriminates
rather than trivially passing.

**Final state**: `chatLanguageModels.json` points at
`http://192.168.50.11:11435/v1/chat/completions`; the workstation-local
`systemd --user` variant was stopped and its unit file removed (fully
superseded, not left as a confusing second path).

## Open questions

- ~~Stack name~~ — **resolved, then corrected, in Phase 2**: not a new
  stack at all — docs-rag folds into the existing `mcp-utility-stack` LXC
  (VMID `50011`) as two more Compose services. See Phase 2's "Stack
  identity" section for the full reasoning (this repo's own
  one-LXC-per-trust-level convention, not one-LXC-per-tool).
- ~~Whether `search_stack_contracts` deserves its own tool~~ — **resolved
  in Phase 2**: no, folded into `search_docs`'s `stack` filter param.
- Whether Laguna XS 2.1 (untested head-to-head vs. llama.cpp per
  `[[project_laguna_ollama_runtime]]`-equivalent finding) is in scope for
  this workflow at all, or only the S 2.1 variant already validated on
  Ollama.
- No timeline dependency on the parked `ai-stack` rebuild — this stays
  independent of it unless Phase 3 finds a reason to fold in.
- Testing above ~26K tokens (toward 131K/256K) is still open if a real
  ceiling number is wanted rather than "at least 26K, no observed limit."

## References

- `docs/framework-ubuntu/local-ai-development.md` — coding-agent bake-off,
  MCP layer design, current local-AI state.
- `docs/mcp-stack/plan.md` — MCP hosting/trust pattern this follows.
- `docs/pentagi-stack/README.md`, `upstream-control.md` — the proven
  `nomic-embed-text` + `pgvector` pattern being reused.
- `docs/framework/llamacpp-router-mode-deployment.md` — embedding model
  candidates (Nomic Embed Text v1.5, BGE-M3, mxbai-embed-large-v1).
- `terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md`,
  `terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md` — existing
  `ai_seg` stacks this would sit alongside.
