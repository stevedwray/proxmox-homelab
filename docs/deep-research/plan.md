# Local deep-research implementation plan

Status: design complete; implementation not started.

This plan adapts Donato Capitella's Local Agent Builder approach to the
homelab's existing Framework Desktop, `ai-services-stack`, SearXNG, MCP, and
Playwright capabilities. It supersedes assumptions in the companion draft
where live infrastructure now provides better evidence.

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
  insufficient; and
- replacement of OpenWebUI, SearXNG, or the shared MCP services.

## 2. Architecture decisions

### 2.1 Runtime placement

Deploy the first service as a separate container in the existing
`ai-services-stack` LXC on `pve`.

The container must have its own:

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
the runtime. Pi or another coding agent may scaffold and edit it, but the
deployed service must not require an interactive coding-agent session.

Deliver topology in measured stages:

1. **Flat vertical slice:** one agent with search, fetch, bounded file-reading,
   and report-writing tools. Its purpose is to validate every integration and
   produce baseline measurements, not to become the final architecture.
2. **Two tiers:** an orchestrator delegates 2-4 focused angles to fresh
   searcher agents. Searchers return structured findings and sources; the
   orchestrator never receives raw page bodies.
3. **Optional third tier:** add page analyzers only if searcher context growth,
   latency, or quality data demonstrates a need. An analyzer receives a file
   path and question, then uses grep/read-range tools rather than injecting a
   complete document.

The intended steady state is two tiers unless the evaluation favors three.

```text
Question
   |
   v
Orchestrator
   |  delegate(angle, success criteria, budget)
   +------------+-------------+
   v            v             v
Searcher A   Searcher B    Searcher C
   |            |             |
   +-- search/fetch/inspect ---+
                |
                v
structured findings + source records
                |
                v
Orchestrator -> final_report.md
```

### 2.3 Model endpoint

Target the Framework llama.cpp OpenAI-compatible API:

```text
http://framework.gibbsgreatly.xyz:8080/v1
```

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

Implement providers in this order:

1. **SearXNG JSON:** default, using the co-located internal service URL.
2. **Existing Playwright web-search MCP:** experimental fallback for a failed or
   low-quality search, after it is made reachable from the runtime.
3. **Direct API provider:** optional controlled fallback if Brave API through
   SearXNG proves hard to observe or rate-limit correctly.
4. **DDGS:** evaluation comparator only initially; do not make an unpinned
   automatic backend the production foundation.

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

Use a constrained HTTP/Markdown fetcher first. It should support HTML, text,
and PDF within explicit limits, store the original URL and response metadata,
and return a workspace path rather than the full document.

Escalate to Playwright only when:

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

MCP is an integration boundary, not a requirement for every tool.

- Call co-located SearXNG directly over HTTP for the primary web search.
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

### Phase 0: freeze a baseline

- Copy or scaffold the Local Agent Builder application into an appropriate
  source directory in this repository.
- Pin Python and Node dependencies, including the exact Agent Framework and
  extraction-library versions.
- Capture a small fixed evaluation set and run metadata schema before tuning.
- Record the current SearXNG engine health and Brave quota behavior.
- Confirm the live llama.cpp model, slot state, and safe request limits.

Exit: the baseline inputs are versioned and a run can be reproduced.

### Phase 1: local flat vertical slice

- Configure Microsoft Agent Framework against Framework's `/v1` endpoint.
- Implement the provider-neutral SearXNG search adapter.
- Implement guarded HTTP fetch-to-workspace and bounded file inspection.
- Produce `manifest.json`, structured sources, and `final_report.md`.
- Run one known-answer query end to end.

This may run from a development workstation first. It must not depend on the
workstation in the eventual server deployment.

Exit: one query completes with correct clickable citations and fully recorded
provenance.

### Phase 2: search evaluation and fallback

- Build a query set covering technical, general, recency-sensitive,
  multilingual, niche, and no-answer cases.
- Compare SearXNG's selected engines with DDGS and the existing Playwright MCP.
- Measure relevance, unique useful sources, failure rate, latency, rate-limit
  behavior, and memory use.
- Test plain HTTP versus Playwright page extraction on JavaScript-heavy pages.
- Select and document the fallback threshold and ordering.

Exit: provider choices are supported by results from this network rather than
demo assumptions.

### Phase 3: hierarchical delegation

- Add the orchestrator and fresh-context searcher instances.
- Define a strict structured return contract for findings and sources.
- Start sequentially, then compare concurrency 1 and 2.
- Verify that raw page content does not enter the orchestrator context.
- Add the analyzer tier only as a controlled comparison if needed.

Exit: hierarchical runs outperform or materially scale beyond the flat
baseline without citation or completion regressions.

### Phase 4: package in `ai-services-stack`

- Add a dedicated application image, Compose service, volume, health check,
  and resource limits to the stack playbook.
- Connect it to SearXNG over the internal Compose network and Framework through
  the existing allowed path.
- If selected, package Playwright separately with pinned browser images.
- Keep the service private during initial validation.
- Add backup policy only for irreplaceable configuration/results; downloaded
  web pages should have a defined retention period rather than indefinite
  backup.

This is an Ansible task/role change. Under the repository validation policy it
must be deployed directly to `pve` through the production approval flow; it is
not a `pve-test-vm` structural-network change unless the design later adds or
modifies zones/firewall topology.

Exit: a private production service completes the evaluation smoke set without
regressing OpenWebUI or SearXNG.

### Phase 5: optional UI and specialist tools

- Decide whether the Textual UI is sufficient or a small authenticated web UI
  is warranted.
- If externally routed, add Traefik and Authentik deliberately and validate
  the actual login path.
- Add `docs-rag` and `cve-mcp` as scoped tools with task-dependent exposure.
- Add result browsing, retention, cancellation, and observability.

Exit: the operator-facing workflow is usable without widening tool or network
access unnecessarily.

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

These should be answered with Phase 1-3 evidence:

1. Is the final topology two tiers or three?
2. Is the existing Playwright MCP reliable enough to package, or should only
   its ideas be retained?
3. Should Playwright use network MCP, an internal HTTP adapter, or a direct
   library integration?
4. What concurrency gives the best completed-research throughput on the live
   Qwen model?
5. Is Brave's available quota sufficient when shared with OpenWebUI?
6. What result and fetched-source retention period is appropriate?
7. Does a TUI meet the operating need, or is an Authentik-protected web UI
   worth the additional surface?
8. At what measured threshold should the service move to a dedicated LXC?

## 10. Definition of done

The first production milestone is complete when:

- the service runs in an isolated container in `ai-services-stack`;
- inference uses the live Framework llama.cpp endpoint;
- SearXNG is the primary search provider with observable engine attribution;
- browser fallback is either validated and packaged or explicitly rejected by
  evaluation;
- all fetches enforce the documented network and content controls;
- important claims in reports have valid source URLs;
- the fixed evaluation set meets an agreed correctness/citation threshold over
  repeated runs;
- failed and quota-limited runs are diagnosable from their manifests;
- OpenWebUI, SearXNG, and the shared MCP services show no regression; and
- the runbook covers deploy, smoke test, rollback, retention, and recovery.

## References

- [Local Agent Builder](https://github.com/kyuz0/local-agent-builder)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [SearXNG search API](https://docs.searxng.org/dev/search_api.html)
- [DDGS search implementation](https://github.com/deedy5/ddgs/blob/main/ddgs/ddgs.py)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [web-search-mcp](https://github.com/mrkrsl/web-search-mcp)
- [OWASP prompt-injection prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
