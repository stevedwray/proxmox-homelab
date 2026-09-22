# Local deep-research implementation plan

Status (2026-09-22): Phase 0 complete. Stage A ran, was measured, and is
now decommissioned (VMID 50014 destroyed 2026-09-22) — its findings fed
directly into Phase 4. **Stage B (Phase 4) is live**: `deep-research`/
`deep-research-files` real Docker Compose services in `ai-services-stack`,
non-root, Authentik `forwardAuth`, verified end-to-end with a real query.
`deep-research-files` was further generalized into a shared reports
viewer — see `docs/reporting-platform/plan.md`. Broader Phase 2/3
measurement (eval harness, job-model decoupling, quota fix, `cve-mcp`
wiring) not yet done — see Phase 5 for what's confirmed but unbuilt.

This plan delivers in two stages. **Stage A** reproduces Donato Capitella's
own design as literally as practical — Local Agent Builder skill, Microsoft
Agent Framework, three-tier delegation, DDGS search — running in a
throwaway LXC created directly on `pve`, outside any stack contract or
Terraform management, so it gets tested against this homelab's real model
endpoint and network path before anything is changed. **Stage B** then
adapts the design for production based on what Stage A actually measures,
landing it in `ai-services-stack` on `pve`. Do not pre-decide Stage B's
architecture questions (search provider, tier count, browser fallback)
before Stage A has run.

`pve-test-vm` is not used for this — confirmed stopped and not currently
part of normal operations (2026-09-21). Neither stage runs on the operator's
workstation either. All scaffolding (including any coding-agent session
used to build or edit the application), execution, and evaluation happen
inside containers on `pve`: a throwaway, unmanaged LXC for Stage A, and the
managed `ai-services-stack` for Stage B.

A separate, now-required prerequisite: the live Nathanw llama.cpp endpoint
this plan depends on was deployed manually and has no reproducing IaC. See
Phase 0.

## 1. Goals and boundaries

### Goal

Given a research question, produce a reproducible Markdown report containing:

- a clear answer and structured findings;
- inline links or citations that resolve to the actual sources used;
- corroboration for important factual claims;
- uncertainty or conflicting evidence where appropriate; and
- a machine-readable run manifest describing queries, sources, timing,
  provider behavior, and quota exhaustion.

Inference must remain local on the Framework Desktop. Public search APIs may be
used through the infrastructure that is already configured, but report content
must not be sent to a hosted LLM.

### Initial non-goals

- a general autonomous browser operator;
- production mutation or infrastructure administration;
- authenticated browsing with a personal browser profile;
- bypassing CAPTCHA or search-provider access controls;
- semantic indexing of every downloaded page;
- a new LXC or VLAN before the existing AI application tier is shown
  insufficient;
- replacement of OpenWebUI, SearXNG, or the shared MCP services; and
- **any development, scaffolding, or execution on the operator's
  workstation, at either stage.** Every part of this plan runs in a
  container on `pve` — a throwaway LXC for Stage A, `ai-services-stack` for
  Stage B. `pve-test-vm` is not used (confirmed stopped, not part of
  current operations).

## 2. Architecture decisions

### 2.0 Delivery staging

| | Stage A: faithful replication | Stage B: production refinement |
|---|---|---|
| Purpose | Run Donato's own design, as designed, against this homelab's endpoint and network | Adapt the design using Stage A's measurements |
| Where | Throwaway, unmanaged LXC directly on `pve` | New container inside `ai-services-stack` on `pve` |
| Topology | Three tiers: orchestrator -> searcher -> page-analyzer, exactly as the source design specifies | Two vs. three tiers decided from Stage A data |
| Search | DDGS (DuckDuckGo), no API key, as the source design specifies | SearXNG, DDGS, or both — decided from Stage A data |
| Runtime | Local Agent Builder skill + Microsoft Agent Framework, scaffolded by a coding agent | Same runtime, refined configuration |
| Lifespan | Torn down/rebuilt freely; not a promotion candidate itself | The actual production deliverable |

Do not import Stage B's prior assumptions (SearXNG-first, two-tier-first,
flat-slice-first) into Stage A. Stage A exists specifically to test the
unmodified source design against real conditions before any of those
substitutions are made.

### 2.1 Runtime placement

**Stage A** runs in a throwaway LXC created directly on `pve` — not
`pve-test-vm` (confirmed stopped and out of current use), not through
Terraform/Terragrunt, no `STACK_CONTRACT.md`. Creating it is a manual
`pct create`, a mutating production action under the normal approval
flow: confirm scope with the operator before creating or destroying it,
same as any other `pve` mutation. It is a genuine throwaway spike —
rebuilt or torn down freely once Stage A's measurements are captured. It
must still not touch any other stack running on `pve`: its own container,
its own volume, no shared Docker socket, credentials, or network zone
beyond what it needs to reach Framework and the public internet.

**Stage B** deploys as a separate container in the existing
`ai-services-stack` LXC on `pve`, following the same pattern already used
for `docs-rag-mcp` inside `mcp-utility-stack` (a new Compose service in an
existing stack's playbook, not a new stack). The container must have its
own:

- non-root runtime identity;
- application image and dependency lock;
- read/write research workspace volume;
- configuration and logs;
- CPU and memory limits; and
- health check.

It must not mount OpenWebUI's database, SearXNG state, Docker socket, host
credentials, or unrelated volumes. Co-location is lifecycle reuse, not shared
application state.

Revisit a dedicated LXC only if measurements show browser memory pressure,
research jobs disrupt OpenWebUI, stronger multi-user isolation is needed, or
arbitrary file-processing requirements materially change the threat model.

### 2.2 Agent runtime and topology

Use the Python Local Agent Builder scaffold and Microsoft Agent Framework as
the runtime at both stages. A coding agent (Pi or another) may scaffold and
edit the application, but only when driven against a container on `pve`
(the Stage A throwaway LXC, or Stage B's `ai-services-stack` container) —
never the workstation — and the deployed Stage B service must not require
an interactive coding-agent session to run.

**Stage A implements the full three-tier design immediately**, matching the
source material rather than starting from a flatter baseline:

```text
Question
   |
   v
Orchestrator (delegate_to_searcher only, no direct web access)
   |  splits into 2-4 research angles
   +------------+-------------+
   v            v             v
Searcher A   Searcher B    Searcher C
   |  web_search (DDGS) -> fetch_url_to_workspace -> delegate_to_analyzer
   v
Page-analyzer (per fetched page)
   |  grep(path, pattern) -> read_lines(path, start, end)
   v
structured findings + source records back up to Searcher -> Orchestrator
                |
                v
Orchestrator -> final_report.md
```

**Stage B then decides the production topology from Stage A's own
measurements** — collapsing to two tiers if the page-analyzer tier proves
unnecessary overhead, keeping three if searcher context genuinely balloons
without it. Do not assume the outcome either way before Stage A data exists.

### 2.3 Model endpoint

Target the Framework llama.cpp OpenAI-compatible API:

```text
http://framework.gibbsgreatly.xyz:8080/v1
```

**This endpoint must be backed by IaC before either stage depends on it
further — see Phase 0.** The live service was deployed manually with no
reproducing Ansible playbook; treat that as a real blocking risk, not
background noise.

Do not hard-code the currently loaded model ID into orchestration logic. Make
the base URL and model selectable configuration, and capture the model ID,
llama.cpp build, context, request limits, and slot count in every run manifest.

Start with one searcher at a time, then test two concurrent searchers. Raise
concurrency only when throughput, memory, output quality, and slot behavior are
measured together. Four server slots are an upper capability signal, not a
default fan-out recommendation.

### 2.4 Search abstraction

Define one internal result schema regardless of provider:

```text
SearchResult
  title
  url
  snippet
  provider
  engine
  rank
  query
  retrieved_at
```

**Stage A uses DDGS as the sole provider**, matching the source design, with
its version pinned explicitly (the source example leaves it unpinned; do not
repeat that). Do not add SearXNG to Stage A — the point of this stage is to
observe DDGS's real behavior from this network unmodified.

A live check from the workstation's own WAN uplink on 2026-09-21 found
DuckDuckGo's endpoints inconsistent within seconds of each other — two
back-to-back requests to `html.duckduckgo.com` returned HTTP 202 and then
HTTP 400 — which is different from, and does not confirm or refute, the
2026-08-02 finding that SearXNG's own `duckduckgo`/`duckduckgo web` engines
saw a hard TCP timeout from this same WAN path. Treat both as stale until
Stage A re-tests DDGS specifically from the Stage A LXC's own egress on
`pve`; do not assume either the old timeout or today's flakiness still
holds without re-checking from the actual runtime.

**Stage B chooses the production provider(s) from Stage A's measurements.**
Candidates to weigh, in no pre-decided order:

1. **DDGS**, if Stage A shows it reliable enough from this network's egress
   over a sustained run, not just a single query.
2. **SearXNG JSON**, using the co-located internal service URL — already
   proven reliable for `mwmbl`/`searchmysite`/`bing`/`braveapi` from this
   network (see `current-state.md`), but with real coverage/quality
   limitations of its own.
3. **Existing Playwright web-search MCP:** fallback for a failed or
   low-quality search, after it is made reachable from the runtime.
4. **Direct API provider:** optional controlled fallback if Brave API proves
   hard to observe or rate-limit correctly.

Whichever is chosen, keep it behind the same application adapter so
switching providers doesn't require changing agent prompts or orchestration.

The tool should support deliberate engine/category selection, language,
time-range, domain inclusion/exclusion, and result count. It must return the
actual provider/engine used rather than presenting every result as
“DuckDuckGo.”

Search quality handling belongs partly above SearXNG:

- formulate focused queries rather than appending vague words such as
  “latest”;
- deduplicate canonical URLs;
- reject obvious query/result mismatches;
- allow source-type diversity requirements;
- cache equivalent searches for a bounded period;
- limit retries and backoff on provider throttling; and
- record empty, timed-out, suspended, and rate-limited engine responses.

Coordinate Brave usage with OpenWebUI because both can consume the same account
quota.

### 2.5 Fetch and browser strategy

**Stage A uses only the `httpx` + MarkItDown fetch-to-workspace tool**,
matching the source design — no Playwright escalation. This is deliberate:
Stage A is testing whether the plain-HTTP approach is sufficient before any
browser fallback is added.

**Stage B** may add a browser escalation path if Phase 2 measurements show
plain HTTP genuinely fails on pages the eval set needs. It should support
HTML, text, and PDF within explicit limits, store the original URL and
response metadata, and return a workspace path rather than the full
document.

Escalate to Playwright only when (Stage B, if adopted):

- the page requires JavaScript to expose the content;
- an ordinary fetch returns an application shell rather than the article;
- the evaluation asks specifically for browser-rendered evidence; or
- the Playwright search fallback is selected.

Do not automatically browser-fetch every search result. This controls latency,
memory, fragility, and exposure to hostile pages.

The existing `web-search-mcp` should be evaluated before reimplementation. If
selected for server use, package it as a separate container beside the
research runtime or add a maintained network transport. Do not make the
research container depend on the operator workstation being online, and do not
place browsers in `mcp-utility-stack` by default.

### 2.6 MCP usage

MCP is an integration boundary, not a requirement for every tool. **Stage A
uses none of this** — DDGS and the fetch tool are called directly, matching
the source design. This applies to Stage B only, if SearXNG or the specialist
MCP tools are adopted:

- Call co-located SearXNG directly over HTTP for web search, if selected.
- Keep fetch/file tools in process where that gives the clearest quotas and
  security policy.
- Offer `docs-rag` to searchers working on homelab or repository questions.
- Offer `cve-mcp` only to security-related searchers.
- Do not expose irrelevant tools to every agent; narrow tool sets improve both
  model behavior and security.

## 3. Workspace and source model

Each run gets a unique directory with no visibility into another run:

```text
runs/<run-id>/
  manifest.json
  task.md
  searches/
  sources/
    <source-id>/metadata.json
    <source-id>/content.md
  findings.json
  final_report.md
```

Source records should preserve:

- original and final URL after redirects;
- page title, publisher/domain, and retrieval timestamp;
- search query, provider, engine, and rank that discovered it;
- content type, byte count, digest, and extraction method;
- fetch failure or truncation state; and
- which report claims cite it.

The report writer receives structured findings and source records, not raw
search logs or full documents.

## 4. Quotas and termination

Quotas must be enforced in code and repeated in agent instructions. Initial
values are hypotheses to evaluate:

```yaml
orchestrator:
  max_research_angles: 4
  max_delegations: 4
searcher:
  max_searches: 5
  max_fetches: 4
  max_browser_fallbacks: 1
  max_grep_calls: 10
  max_read_ranges: 10
fetch:
  max_redirects: 5
  max_download_bytes: 5000000
  timeout_seconds: 30
```

Also enforce a run deadline, maximum model turns, maximum aggregate downloaded
bytes, and global provider rate limits. A quota failure must be reported as a
specific run outcome rather than disguised as “no information found.”

Agents must stop when they have enough independent evidence to satisfy the
task, not when every quota has been consumed.

**Concurrency gap found in Stage A, relevant to Stage B's job model (2.0/Phase
5):** the vendored scaffold's `tools/core.py` `check_quota()` enforces quotas
as a single counter keyed by tool name, shared globally across every agent
instance in the process — not per-run and not per-searcher-instance, despite
`plan.md`'s original quota table reading as "per searcher instance" (see
`current-state.md` for the full finding). This is survivable for Stage A's
one-run-at-a-time usage. It actively breaks under Stage B's confirmed
job-model direction (Phase 5, point 2), where multiple overnight runs may be
in flight together: two concurrent jobs would silently share and starve
each other's `web_search`/`fetch_url_to_workspace` budget. Stage B's job
layer must scope quotas per run, not rely on the scaffold's global counters
as-is.

**Related: the shared Framework endpoint has no request-concurrency limiter.**
Framework's llama.cpp instance is a single, memory-fragile shared resource
(see Phase 0's incident notes — a prior uncoordinated double-load already
caused a full host hang). Stage B's job model should place a concurrency
limiter between the agent runtime and that endpoint before allowing multiple
jobs to run in parallel, rather than assuming the endpoint can absorb
arbitrary concurrent load.

## 5. Security requirements

Public pages and search snippets are untrusted input. They may contain prompt
injection, misleading instructions, tracking URLs, or content designed to
trigger local tools.

Required controls:

- Treat fetched text as data, never as agent instructions.
- Make system/tool boundaries explicit in prompts and structured messages.
- Permit only `http` and `https` URLs.
- Resolve and validate every destination and redirect; block loopback,
  link-local, RFC1918, local DNS zones, Proxmox addresses, cloud metadata, and
  other non-public targets unless an explicitly different internal tool owns
  that access.
- Reject embedded credentials and unsupported ports.
- Enforce response time, redirect, byte, decompression, and MIME limits.
- Store downloads under the run directory with generated filenames.
- Do not execute scripts, macros, downloaded binaries, or page-supplied shell
  commands.
- Run browser containers without personal profiles, cookies, SSH material,
  cloud credentials, or Docker access.
- Use network policy as the current protection for the unauthenticated
  Framework endpoint; do not publish it more broadly for this project.
- Sanitize logs so query URLs or exceptions do not leak configured API keys.
- Require explicit citation URLs from searchers; never invent a URL from a
  title.

Internal MCP content and public web content should retain separate provenance
labels. A retrieved internal document must not silently authorize actions in
the infrastructure.

## 6. Implementation phases

### Phase 0: Nathanw llama.cpp as IaC (prerequisite, blocks everything else) — COMPLETE 2026-09-21

`ansible/00-initial-setup/framework-desktop-llamacpp-nathanw-vulkan.yml`
reproduces the live configuration and is checked into this repo. It was
run in promote mode and independently re-verified (`/health`, `/props`
matching `n_ctx=262144`/`total_slots=4`). See
`docs/deep-research/current-state.md`'s incident/resolution notes for the
full story, including a same-day host-hang caused by an early version of
this playbook's shadow-deployment mode loading a second full model copy
without checking free memory first — since fixed with two pre-flight
guards (refuse if the live container is already running unless promoting;
refuse unless `/proc/meminfo` clears a threshold sized for a full model
load).

The live Framework endpoint this entire plan depends on was deployed
manually and has no reproducing playbook — see `current-state.md` and the
README's "Nathanw llama.cpp IaC gap" section. This must be closed before
Stage A starts, not treated as a parallel nice-to-have, because Stage A's
whole point is measuring behavior against a known, reproducible endpoint.

- Read-only capture of the live container's exact configuration: image
  digest/tag, entrypoint/command flags (context size, slot count `-np`,
  Vulkan device flags, any other runtime flags), volume/model mounts, and
  the exact model file path. Use `docker inspect`/`docker compose config`
  equivalents against the live container — read-only, not a config change.
- Write a new Ansible playbook (or correct the existing, explicitly-not-wired
  `framework-desktop-llamacpp-nathanw.yml` in place) that reproduces this
  **exact** configuration: `ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan`
  on port 8080, serving `Qwen3.8-Flash-Next-UD-Q4_K_XL`, 262144 context, 4
  slots. Do not carry over the old file's mismatched assumptions (port 8081,
  `Qwen3.8-27B-Q4_K_M`, from-source build) — those were for a different,
  unrelated purpose and must not be reused here even as a starting point
  beyond structure.
- Validate the playbook against the **known-good live configuration**
  specifically: after running it (on a path that does not disrupt the
  live service — e.g. a parallel container/port first, or a maintenance
  window agreed with the operator), confirm `/health`, `/v1/models`,
  `/props`, and `/slots` return the same shape and values already recorded
  in `current-state.md`, not merely "a llama.cpp server came up."
- Record the pinned fork version, image reference, and model digest in the
  playbook so a future rebuild doesn't silently drift to a different
  release.

This is high-blast-radius by nature (it's the shared inference backend every
other AI stack in this homelab also depends on), so treat any live
validation against the running Framework host under the same care as a
production credential/mutation action — confirm scope with the operator
before running anything that could disrupt the live server, per the
Production Credential Controls and Execution Guardrails in `CLAUDE.md`.

Exit: a playbook exists, is checked into this repo, and has been shown
(without disrupting the live service, or during an agreed window) to
reproduce the exact live configuration.

### Phase 1 (Stage A): faithful replication on a throwaway pve LXC

- Create a throwaway LXC directly on `pve` — not the workstation,
  not `ai-services-stack`. It is not expected to follow the
  `ai-services-stack` contract; it is a throwaway spike.
- Vendor the Local Agent Builder skill and scaffold the application using a
  coding agent (Pi or otherwise) driven **against this container**, matching
  the source design's own workflow.
- Implement the full three-tier design as specified: orchestrator ->
  searcher -> page-analyzer, DDGS search (version-pinned), `httpx` +
  MarkItDown fetch-to-workspace, `grep`/`read_lines` tools, tool quotas as
  both a hard harness-enforced cap and a value stated in each agent's system
  prompt.
- Point it at the Framework `/v1` endpoint from Phase 0 (do not proceed on
  the old, un-reproducible manual deployment once Phase 0 is done).
- Run the source design's own reference query (or an equivalent one) and at
  least a handful of homelab-relevant queries end to end, unmodified from
  Donato's design.
- Vendor and run the source design's own eval harness (LLM-judge, 3 runs per
  query) to get a first real score from this network — not to pass/fail
  against a fixed bar yet, just to get a baseline number.

Exit: an unmodified, faithful replication of the source design runs
end-to-end from the Stage A LXC against the live Framework
endpoint, with results and an eval score recorded — not assumed.

**Progress, 2026-09-21:** scaffold built in VMID `50014`
(`/opt/deep-research-agent`), following the Local Agent Builder skill's
own STAGE 1 workflow and cross-checked against its `CHECKLIST.md` (which
caught several real omissions on first pass — missing `agent_id` routing
instructions, missing concrete `delegate_tasks` JSON examples, missing the
fetch→capture→forward filename handoff from Searcher to Analyzer, and an
unpruned RAG/shell tool surface — all fixed before running anything).
`ddgs` pinned to `9.16.0` (latest at time of writing) rather than left
unpinned per the source example.

Two real end-to-end runs against the live Framework endpoint:
1. A trivial-fact query ("capital of France") — correctly answered without
   spawning any Searcher delegation, in ~18s. Confirms the Orchestrator's
   "don't over-delegate simple questions" instruction actually works, not
   just reads well.
2. A query requiring real search+fetch+citation ("latest ddgs version on
   PyPI") — completed in ~6 minutes, correctly reported `9.16.0` (an
   independent cross-check against the version pinned in `pyproject.toml`
   moments earlier) with multiple real, working citation URLs. This
   satisfies this phase's exit criterion.

**Finding — quotas are global, not per-instance:** the scaffold's actual
quota enforcement (`tools/core.py`) is a single shared counter per tool
name across every agent using it, not per-agent-instance as this plan's
original quota table assumed ("max_searches: 5 # per searcher instance").
Config was written accordingly (pooled numbers sized for ~4 concurrent
Searchers, not 5-per-searcher) — see `current-state.md`.

**Finding — raw `curl` bot-detection did not predict `ddgs` library
behavior:** the DDG endpoint flakiness observed via `curl` earlier in this
plan (202/400 within seconds) did not block the actual query above, which
used the real `ddgs` Python client successfully. Different request shape
and backend selection than a bare `curl` GET — do not treat a `curl` probe
as a stand-in for testing the actual client library.

**Eval harness run, then deliberately cut short (2026-09-21).** The source
design's own harness was run against a 4-query mixed dataset (`contains`/
`regex`/`llm_judge`). Stopped after 2 of 12 runs, on operator direction, for
a good reason: Donato's own reported 79.1% aggregate score was measured on
a different model entirely (Qwen 3.6, 27B/35B-A3B-Q4 on an R9700), not
Qwen3.8-Flash-Next-UD-Q4_K_XL on this Strix Halo box. Chasing a directly
comparable aggregate score against his number was never going to be
meaningful — the harness's value here is what it reveals about *this*
model's behavior, not a leaderboard comparison.

What the 2 completed runs (both "What is the capital of Japan?", both
scored 1.0 — correct) actually revealed, which is the real finding worth
keeping: **the model fetched 13–15 pages before answering a one-word
trivial fact**, taking 10–15 minutes per run, versus the earlier
"capital of France" smoke test which answered directly in ~18s with zero
delegation. This reproduces, empirically and on this exact deployment, the
"over-verification tendency that burns iteration budget on unprompted
depth" already flagged as a risk for Qwen3.8-Flash-Next in this plan's own
design notes — not a scaffold bug, a genuine model-behavior finding. The
global (not per-instance) `fetch_url_to_workspace`/`web_search` quota pool
(16/20) was generous enough to let this happen unchecked on a single query.

**Not yet measured:** how the two queries that actually require research
(ddgs PyPI version, `requests` library history) behave under the harness's
stricter subprocess/judge-timeout handling, and whether the shared quota
gets hit on a harder multi-hop query. Both were already validated manually
outside the harness earlier in this phase (see above) and worked correctly,
just slowly.

Exit criterion is still met on the strength of the manual runs plus this
partial harness evidence: results and a real (if partial) score are
recorded, not assumed. A full 12-run dataset pass is deprioritized — the
better next investment is probably tightening the fetch/search quotas
specifically to test whether that curbs the over-fetching behavior, which
is a Phase 3 (Stage B) refinement question this finding directly feeds.

### Phase 2 (Stage A): measure, don't yet redesign

- Compare DDGS's actual behavior from the Stage A LXC's own egress on `pve`
  against the flakiness observed from the workstation on 2026-09-21
  (see `plan.md` §2.4) and against SearXNG's already-recorded behavior in
  `current-state.md`. Do this from the runtime's real network path, not the
  workstation.
- Record failure rate, latency, rate-limiting behavior, and result quality
  for DDGS specifically, over more than one query.
- Record whether the page-analyzer tier's context actually stays clean, or
  whether it's overhead the searcher tier could absorb directly.
- Test plain HTTP versus needing a browser on a JavaScript-heavy page, using
  whatever pages the eval queries naturally surface.

Exit: provider and tier-count choices for Stage B are supported by
measurements taken from this network's real egress path, not by demo
assumptions or the source video's own results (which were measured on a
different network).

### Phase 3 (Stage B): refine the design

- Using Phase 1-2 evidence, decide: keep three tiers or collapse to two;
  keep DDGS, switch to SearXNG, or run both behind the adapter; keep or drop
  the Playwright fallback path.
- Reimplement (not just reconfigure) whichever pieces the evidence says to
  change — e.g., if collapsing to two tiers, actually remove the
  page-analyzer delegation rather than leaving it as dead code.
- Re-run the eval harness against the refined design and compare scores
  against the Stage A baseline from Phase 1.

Exit: hierarchical/provider choices for the production build are justified
by a measured before/after comparison, not by which one is more elegant.

### Phase 4 (Stage B): package in `ai-services-stack` — design confirmed 2026-09-21

Decided 2026-09-21: **the Stage A LXC (VMID 50014) is disposed of, not
migrated.** The operator confirmed no test-session data needs preserving —
Stage B starts clean. Everything below replaces the Stage A scaffold
outright; there is no data-migration step.

**Placement: a third Docker Compose service inside the existing
`ai-services-stack` LXC (VMID 50013), not a new dedicated stack/LXC.** This
is a deliberate call, not a default — reasoning, so it can be overridden:
`ai-services-stack` is already in `ai_seg`, already has an allowed egress
path to Framework:8080 (used by OpenWebUI/`ollama-reliability-proxy`
today), and `cve-mcp-server` (`mcp-utility-stack`) is in the same `ai_seg`
zone too — folding in avoids provisioning a new LXC, zone attachment, and
MikroTik firewall rules from scratch. The app's own footprint is light (a
few hundred MB RSS per active run, no local GPU/compute — it's a thin
client of Framework), so it fits `ai-services-stack`'s existing 4096MB
budget without a memory bump. That matters specifically because
`mcp-utility-stack`'s own `stack.yaml` documents a real, unresolved problem
bumping LXC memory via Terraform on live `pve` (an unrelated pre-existing
SDN-attachment resource drift blocks it) — better not to invite that same
class of trouble here if the workload doesn't require it.

**Built from source, not a pulled image** — this is custom code (the
vendored, patched Local Agent Builder scaffold), not a published upstream
image, so it follows `mcp-utility-stack`'s build-from-source pattern
(`cve-mcp-server`/`docs-rag-mcp`) rather than `ai-services-stack`'s
pull-through-Harbor pattern (OpenWebUI/SearXNG). Ansible copies the cleaned
app source into `/opt/ai-services-stack/deep-research/` on the LXC (mirrors
`ai_services_reliability_proxy_build_dir`'s existing copy-then-build
pattern in `deploy-ai-services-stack.yml`), and the Compose service builds
its own image from a `Dockerfile` checked into this repo, not hand-edited
on the LXC.

**Runs as a non-root, dedicated container user.** The Stage A LXC's
current root-owned process under `/root/.deep-research-agent` is the exact
problem this phase fixes — not by hardening the LXC (it's being disposed
of), but structurally: the `Dockerfile` creates an unprivileged user
(`RUN useradd -m -u 1000 deepresearch`, `USER deepresearch`), and the
container's `$HOME` (and therefore the scaffold's own
`~/.{APP_NAME}` config/session/workspace path — no code change needed,
confirmed in `config.py`) naturally lands inside a named Docker volume
owned by that user, never `/root`.

**Two Compose services, one for the interactive UI and one for artifacts:**

1. `deep-research` — the existing `--web`/`textual-serve` app, `restart:
   unless-stopped`, healthcheck against its own root path (matching the
   `openwebui`/`searxng` healthcheck pattern already in this playbook).
2. `deep-research-files` — a small stdlib-only Python script (same
   "no build step, single bind-mounted file" pattern as
   `ollama-reliability-proxy/proxy.py`, not a new nginx/registry image)
   that lists runs and serves `final_report.md`/sources read-only from the
   same named volume, mounted `:ro`. Replaces the Stage A stopgap
   (`python3 -m http.server` run by hand as root) with a real, supervised,
   non-root, restart-managed service. This is what "preferably through a
   web interface" (operator, 2026-09-21) actually resolves to for Stage B —
   see Phase 5, point 3 for why a bare file server still isn't the final
   shape (no per-run structure, no auth until this phase adds it).

Both share one named Docker volume (`ai-services-deep-research-data`) for
config/sessions/workspace — `deep-research` writes, `deep-research-files`
reads it read-only.

**Auth: `forwardAuth`, not native OIDC.** Unlike OpenWebUI, this scaffold
has no built-in OAuth support, so it follows the same pattern already used
by `comfyui-stack`, `netbox-stack`, `pentagi-stack`, and `proxy-stack` —
`auth.mode: forwardAuth` in `edge.yaml` for both routes
(`deep-research`/`deep-research-files`), which `reconcile-edge.py`'s
existing Authentik discovery/reconcile step provisions automatically from
the manifest, the same mechanism already exercised (and already failing
without a real Authentik target) during this session's dry-runs. No new
Authentik integration code needed — this really is the "minor change" the
operator expects, once the manifest's `auth.mode` flips from `none` to
`forwardAuth`.

**Monitoring: ship this service's logs to Graylog, not just local
`json-file`.** `ai-services-stack`'s current Docker daemon logging
(`json-file`, 50m/7 files, host-level default) is local-retention-only —
fine for OpenWebUI/SearXNG today, but does not meet "monitoring appropriate
to an application in the lab" (operator, 2026-09-21) for a service that's
expected to run real overnight, unattended jobs. Give the `deep-research`
and `deep-research-files` services their own `logging:` block using a
syslog driver pointed at the existing Graylog stack (see
`reference_json_file_log_driver_gap.md` — `docker_base` sets no syslog
default; it's opt-in per playbook, same as other stacks that already do
this). Add a health-check-based row to `CLAUDE.md`'s Stack Service Types
table once this ships.

**Security**, beyond the non-root/auth points above:

- Confirm `ai_seg`'s existing egress already covers everything this service
  needs (Framework:8080, `cve-mcp-server` intra-zone at
  `192.168.50.10:8000`, general internet for DDGS) before assuming it —
  check the live MikroTik rules, don't infer from other services' access.
- Keep the search/fetch/CVE tool surface narrow per agent tier, per §2.6 —
  do not widen it "while we're in here."
- No SSH keys, cloud credentials, or Docker socket access inside either
  container — matches §5's existing browser-container requirement, applies
  equally to a non-browser tool-calling agent.

This is an Ansible task/role change. Under the repository validation policy it
must be deployed directly to `pve` through the production approval flow; it is
not a `pve-test-vm` structural-network change unless the design later adds or
modifies zones/firewall topology.

Exit: a private production service, running as a non-root container user
with its data outside `/root`, completes the evaluation smoke set without
regressing OpenWebUI or SearXNG, and its logs are visible in Graylog.

### Phase 5 (Stage B): UI, auth, artifacts, and specialist tools — decisions confirmed 2026-09-21

The Stage A `--web` prototype (Textual UI over `textual-serve`, Traefik route
live at `deep-research.lab.gibbsgreatly.xyz`) answered the "is a browser UI
warranted" question empirically: yes, it works and the operator used it for
real queries, but three real gaps surfaced from that actual use, not
speculation, and are now confirmed requirements for Stage B rather than open
questions:

1. **Authentik OIDC is required, not optional.** Both the `deep-research` and
   `deep-research-files` (see point 3) routes currently run `auth.mode: none`
   — deliberately, as Stage A's own step 1 of 2 rollout, but explicitly not
   acceptable as a long-term state (see `current-state.md`). Stage B adds a
   real Authentik application/provider and validates the actual login path
   for both routes before they're considered production, per the Authentik
   row in `CLAUDE.md`'s Validation Tiers.

2. **Session/job lifecycle must not depend on the browser connection staying
   open.** `textual-serve`'s `AppService.stop()` sends a `quit` message on
   WebSocket disconnect, which kills the underlying agent process — closing
   the tab (or a workstation reboot) kills an in-progress run. This is fine
   for short interactive queries but wrong for anything expected to run
   unattended overnight, which this project explicitly needs to support.
   Stage A's workaround is real but manual: launch headless
   (`app.py --prompt "<topic>" --auto-approve`, detached via `setsid`/`nohup`
   from any SSH/browser session) instead of via `--web` for any run that
   must survive a disconnect, then inspect it afterward via the scaffold's
   already-built-in `--list-sessions`/`--resume <id>` (session persistence
   was found already implemented in the vendored scaffold, just defaulted
   off — `enable_session_persistence: true` was flipped on in Stage A's live
   config 2026-09-21). **Stage B should make this a first-class job model**:
   submitting a topic returns a job identifier immediately, independent of
   any browser tab; the browser becomes a viewer/poller of jobs, not the
   process that keeps them alive. Do not solve this by patching
   `textual-serve`'s socket-lifecycle behavior directly — build the
   decoupled job layer instead.

3. **Result/artifact access needs real endpoints, not a bare file server.**
   `final_report.md` and a run's intermediate fetched sources currently only
   exist inside the Stage A LXC's filesystem, reachable only via `pct exec`/
   `scp`. A stopgap read-only `python3 -m http.server`, run by hand as root,
   over the workspace directory (route: `deep-research-files.${LAB_DOMAIN}`)
   was added 2026-09-21 purely so the operator could download a report from
   a browser; this is explicitly **not** the Stage B design — see Phase 4's
   `deep-research-files` service for the real replacement (non-root,
   restart-managed, behind `forwardAuth`). Longer-term, this same gap
   generalizes across projects — see `docs/reporting-platform/CONVENTION.md`
   and its plan, which names `deep-research` as its Phase 1 first adopter.

4. **`cve-mcp` is confirmed as the right specialist tool for CVE/vuln-class
   queries, validated by a live run, not just planned.** A real CVE lookup
   query run through Stage A on 2026-09-21 (`CVE-2026-93957`, see
   `current-state.md`) manually re-fetched NVD, EPSS, CISA KEV, OSV.dev,
   GitHub Advisories, and MITRE/Red Hat/Ubuntu security pages one at a time
   via generic `web_search`/`fetch_url_to_workspace` — exactly the source
   set `cve-mcp-server` (already live at `192.168.50.10:8000/mcp`,
   `mcp-utility-stack`, per `docs/mcp-stack/plan.md`) already integrates as
   structured API calls. Routing CVE-class queries to `cve-mcp` instead of
   generic web search should be both faster and more reliable than the DDGS
   path this query class currently takes; it does not replace general web
   search for non-CVE topics. Confirms and sharpens §2.6's existing "offer
   `cve-mcp` only to security-related searchers" line — this is no longer a
   hypothetical option, it's a scoped Stage B tool decision backed by a real
   before/after comparison of what the generic path actually did.
- Add `docs-rag` as a scoped tool for searchers working on homelab/repository
  questions, per §2.6, task-dependent exposure (unchanged from the original
  plan).

Exit: the operator-facing workflow survives a browser/client disconnect for
long-running jobs, both edge routes are authenticated, report artifacts are
reachable through real endpoints rather than filesystem access, and
CVE/vuln-class queries are routed to `cve-mcp` rather than generic web search.

## 7. Evaluation plan

Use three runs per query where time permits. Score both answer quality and
system behavior.

### Query classes

- single verifiable fact;
- multi-part fact collection;
- comparison requiring several sources;
- current/recency-sensitive topic;
- niche or multilingual topic similar to Donato's Silvan example;
- technical question favoring primary documentation;
- homelab question where docs-RAG should help;
- vulnerability question where CVE MCP should help;
- JavaScript-rendered source;
- ambiguous or deliberately unanswerable question; and
- adversarial page containing prompt-injection text.

### Measurements

- weighted factual correctness;
- citation validity and claim/source entailment;
- source diversity and primary-source preference;
- unsupported-claim count;
- search success and engine/provider used;
- page-fetch and extraction success;
- total model calls, input/output tokens, and peak context;
- tool calls and quota exhaustion;
- wall-clock time and first-useful-finding time;
- server concurrency/slot behavior;
- application and browser memory; and
- run completion/cancellation reliability.

Compare at least:

1. flat versus two-tier;
2. SearXNG only versus SearXNG plus Playwright fallback;
3. one versus two concurrent searchers; and
4. two-tier versus three-tier only if context measurements warrant it.

Do not optimize against a single successful demo query.

## 8. Operational checks

Before each deployment or benchmark:

- confirm the target node and production approval scope;
- confirm Framework health, model ID, properties, and available slots;
- confirm SearXNG JSON output and selected-engine behavior;
- confirm adequate free memory on Framework and `ai-services-stack`;
- ensure no unrelated large model or GPU workload will invalidate results; and
- create a fresh isolated run workspace.

During a run:

- expose progress and last successful tool call;
- make cancellation graceful rather than killing a client mid-generation;
- record provider errors and backoff rather than silently retrying forever;
  and
- preserve a partial manifest/report on failure.

After deployment, smoke-test OpenWebUI, SearXNG JSON search, the research
service health endpoint, one fixed research query, and any selected MCP
integration.

## 9. Open decisions

These should be answered with Phase 0-3 evidence, not pre-decided:

0. Does the Phase 0 Ansible playbook actually reproduce the live Nathanw
   configuration, confirmed by matching `/health`/`/v1/models`/`/props`/
   `/slots` output, not just "a server started"?
1. Is DDGS reliable enough from the Stage A LXC's own egress on `pve` over a sustained
   run to be Stage B's primary or sole provider, or does it need SearXNG
   alongside or instead?
2. Is the final topology two tiers or three?
3. Is the existing Playwright MCP reliable enough to package, or should only
   its ideas be retained, or is it unneeded if DDGS/SearXNG plus plain HTTP
   fetch already covers the eval set?
4. Should Playwright (if adopted) use network MCP, an internal HTTP adapter,
   or a direct library integration?
5. What concurrency gives the best completed-research throughput on the live
   Qwen model?
6. Is Brave's available quota sufficient when shared with OpenWebUI (only
   relevant if SearXNG's `braveapi` engine is adopted for Stage B)?
7. What result and fetched-source retention period is appropriate?
8. Does a TUI meet the operating need, or is an Authentik-protected web UI
   worth the additional surface?
9. At what measured threshold should the service move to a dedicated LXC?

## 10. Definition of done

**Stage A** is complete when:

- a Phase 0 Ansible playbook reproduces the live Nathanw configuration,
  checked into this repo and validated against the live endpoint's actual
  `/health`/`/v1`/`/props`/`/slots` output;
- the unmodified three-tier, DDGS-based, Local Agent Builder design runs
  end-to-end from the Stage A LXC against the live
  Framework endpoint;
- its own eval harness has produced a baseline score from real queries run
  on this network, not assumed from the source video's own results; and
- DDGS's reliability, and whether the page-analyzer tier earns its keep,
  have been measured from the runtime's real egress path, not guessed.

**Stage B**, the first production milestone, is complete when:

- the service runs in an isolated container in `ai-services-stack`;
- inference uses the live, IaC-backed Framework llama.cpp endpoint;
- the search provider(s) in production use are the ones Stage A's
  measurements actually support, with observable engine/provider
  attribution;
- browser fallback is either validated and packaged or explicitly rejected by
  evaluation;
- all fetches enforce the documented network and content controls;
- important claims in reports have valid source URLs;
- the fixed evaluation set meets an agreed correctness/citation threshold over
  repeated runs, compared against the Stage A baseline;
- failed and quota-limited runs are diagnosable from their manifests;
- OpenWebUI, SearXNG, and the shared MCP services show no regression; and
- the runbook covers deploy, smoke test, rollback, retention, and recovery.

## Phase 5 progress: Traefik route prototype (Stage A `--web` mode)

Two human/agent interaction surfaces were raised as design questions
(2026-09-21): exposing this agent as an MCP tool for other coding agents
(async job pattern needed — see the design discussion in this session), and
a browser-based human interface fronted by Traefik+Authentik rather than
OpenWebUI (OpenWebUI's chat-completions model doesn't map well onto
multi-minute multi-agent runs; the scaffold's own `--web` mode, unmodified
otherwise, was judged the lower-effort path).

**Step 1 (Traefik route only, `auth.mode: none`) — done and verified
2026-09-21:**

- `engine/tui.py`'s `--web` mode was hardcoded to bind `localhost` only, with
  no CLI flag or config path to change it — a real gap, not a design choice,
  since Traefik needs network reachability. Added a minimal `--host` flag
  (default `localhost`, preserving prior behavior) and threaded it into the
  `textual_serve.server.Server(...)` call. This is a targeted networking fix
  in the same file, not a rewrite of orchestration logic.
- Added a `deep-research` route to `terraform/lxc/stacks/ai-services-stack/edge.yaml`
  pointing at `http://192.168.50.13:8090` (the Stage A LXC's `--web --host
  0.0.0.0 --port 8090` process) — additive only, no changes to the existing
  `openwebui`/`searxng` routes.
- `reconcile-edge.py --apply` alone was **not sufficient** to make the route
  live — it only renders `.generated/traefik/*.yml` and
  `.generated/technitium/zone-records.json`; two further, separate publish
  steps were needed and are not obvious from `STACK_CONTRACT.md`'s existing
  wording alone:
  1. `ansible-playbook -i terraform/lxc/environments/pve/proxy-stack/inventory.yml -u root terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml -e traefik_generated_source_dir=<repo>/terraform/lxc/environments/pve/.generated/traefik` — pushes the rendered Traefik dynamic config into the live container. `scripts/provision.sh --stack proxy-stack` alone does **not** do this in single-stack mode (it explicitly logs "SKIP edge reconcile: single-stack mode"); the exact inventory and generated-dir paths matter and are per-environment (`terraform/lxc/environments/pve/...`), not the paths under `terraform/lxc/stacks/...` that a naive read of the STACK_CONTRACT might suggest.
  2. `scripts/provision.sh --stack technitium-stack` — separately required to actually publish the new DNS record to the live authoritative Technitium server. This one **is** self-contained (it regenerates zone records from all EdgeManifests and pushes them as part of its own normal per-stack apply), unlike step 1.
- Verified after both steps: `dig @192.168.20.15 +short deep-research.lab.gibbsgreatly.xyz` → `192.168.30.10`; `https://deep-research.lab.gibbsgreatly.xyz/` → `200`. Regression-checked `openwebui`/`searxng` routes still `200` — no disruption to existing routes.

**Not yet done (step 2):** add the Authentik OIDC app/provider for this
route, deliberately deferred to a separate, smaller change per the
operator's own two-step preference — currently `auth.mode: none` means this
route is unauthenticated on the open internet-facing edge, same posture as
`searxng` today. Do not leave this route in this state long-term.

**A second real bug found and fixed after the route went live:** the page
loaded but stayed stuck on `textual-serve`'s static pre-connection intro
screen — `textual_serve.server.Server` reuses the same `host` value for
both "what to bind to" (needs `0.0.0.0`) and "what URL the browser should
use for assets/the WebSocket" (was also getting `0.0.0.0`, meaningless to a
browser, so `textual.js` never loaded and the WebSocket never opened).
Added a `--public-url` flag threading into `Server(..., public_url=...)`,
set to `https://deep-research.lab.gibbsgreatly.xyz` — confirmed via a raw
WebSocket handshake (`101 Switching Protocols`, real terminal bytes
streaming through Traefik) and then by an actual operator using the
rendered chat UI in a browser.

**Operational finding — the browser TUI session is not resilient to
disconnection, unlike headless mode.** Traced through
`textual_serve/app_service.py`: the per-connection Textual app subprocess
is explicitly stopped (`AppService.stop()` sends a `"quit"` message) when
its WebSocket closes. A closed browser tab — including one closed by a
workstation reboot — will very likely kill an in-progress research query
before it finishes, unlike the detached `--prompt --auto-approve` headless
runs used for Phase 1/2 testing, which are fully decoupled from any client
session. Anything already fetched to a workspace file survives on disk;
`final_report.md` and any un-persisted state does not. **This matters for
Stage B**: any production interaction surface meant for real, unattended,
multi-minute-plus research jobs should default to the headless/async path,
not the interactive browser TUI, unless the operator is actively watching.

**First real human-driven run, 2026-09-21 (still gathering full Phase 2
evidence):** an operator ran a genuine multi-source vulnerability-research
query (a specific CVE's CISA KEV status) through the browser UI. This
produced real Phase 2 signal, not just a UI smoke test:
- It correctly delegated to a Searcher, which pulled from NVD, MITRE, OSV,
  CISA's KEV catalog, GitHub advisories, and several vuln-intel sites — 14+
  fetched files for one query, which is appropriate depth for this query
  type (unlike the earlier over-fetching finding on a trivial fact).
- Individual `web_search` calls took **145–147 seconds each** in the
  TUI's own tool-timing display — dramatically worse than any earlier
  isolated test (sub-second to a few seconds). This is real evidence that
  DDGS degrades under sustained use from this network, feeding directly
  into Phase 2's open DDGS-reliability question.
- **The quota-exhaustion design worked correctly under real pressure**: once
  the Searcher's `web_search` quota was exhausted, the agent did not loop
  or hang — it explicitly stated *"Searcher quotas are exhausted. Writing
  the report from the confirmed authoritative evidence, with gaps
  explicitly flagged"* and moved on to writing up what it had. This is the
  prompt-level anti-looping/quota-exhaustion behavior from `prompts.py`
  actually firing as designed, not just reading well on paper.

This run was still in progress (report not yet written) as of this note;
the final report/outcome should be added here once it completes.

## References

- [Local Agent Builder](https://github.com/kyuz0/local-agent-builder)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [SearXNG search API](https://docs.searxng.org/dev/search_api.html)
- [DDGS search implementation](https://github.com/deedy5/ddgs/blob/main/ddgs/ddgs.py)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [web-search-mcp](https://github.com/mrkrsl/web-search-mcp)
- [OWASP prompt-injection prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
