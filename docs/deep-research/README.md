# Local deep-research agent

This workspace defines a local deep-research service that uses the Framework
Desktop for inference and the existing Proxmox AI services for search and
application hosting.

The intended outcome is an agent that can:

- decompose a question into bounded research tasks;
- search the public web and selected internal sources;
- fetch and inspect sources without filling the report writer's context with
  raw pages;
- corroborate claims across sources; and
- produce a Markdown report with working, attributable citations.

No deep-research service has been deployed yet. The documents here record the
researched design and the implementation sequence:

- [Current state](current-state.md) inventories the components that already
  exist and separates workstation-local capabilities from network services.
- [Implementation plan](plan.md) defines the target architecture, phased
  delivery, security boundaries, evaluation, and promotion gates.

## Recommended architecture

Delivery is staged in two parts, both running in Proxmox containers — never
on the operator workstation.

**Stage A — faithful replication.** Reproduce Donato Capitella's own
design as literally as practical: the vendored Local Agent Builder skill,
Microsoft Agent Framework, three-tier orchestrator → searcher →
page-analyzer delegation, and DDGS (DuckDuckGo) search — in a throwaway,
unmanaged LXC created directly on `pve` (not `pve-test-vm`, which is
stopped and not part of current operations). The point of Stage A is to
get his already-validated design running against this homelab's own model
endpoint and egress path, unmodified, before substituting any homelab
component for one of his.

**Stage B — refine into production.** Once Stage A has run against real
queries from this network, use its measurements (not assumptions) to
decide what changes for the homelab: SearXNG vs. DDGS, two-tier vs.
three-tier, Playwright fallback or not. Land the resulting design as a
new, isolated application container inside the existing `ai-services-stack`
LXC on `pve`. Do not create another LXC for this.

```text
Stage A (pve, throwaway LXC)
User / Textual TUI
           |
           v
Local Agent Builder scaffold (Microsoft Agent Framework)
  orchestrator -> searcher -> page-analyzer (three tiers, as designed)
           |
           +---- DDGS web search -----------------------------+
           |                                                  |
           +---- httpx fetch_url_to_workspace + MarkItDown     v
                                                     Framework Desktop
                                                     Nathanw llama.cpp
                                                     Qwen3.8-Flash-Next

Stage B (pve, ai-services-stack, production)
User / TUI / future web UI
           |
           v
Deep-research runtime (refined per Stage A findings)
  in ai-services-stack, separate container and volume
           |
           +---- OpenAI-compatible API ----------------------+
           |                                                 |
           +---- search provider(s) chosen in Stage B --+    v
           |                                             |  Framework Desktop
           +---- HTTP/Markdown fetch                     |  Nathanw llama.cpp
           |                                             |  Qwen3.8-Flash-Next
           +---- optional Playwright --------------------+
           |
           +---- optional specialist MCP tools
                    +-- docs-rag
                    +-- CVE/threat intelligence
```

## Decisions captured here

1. **Test Donato's design as he describes it first (Stage A)**, in a
   throwaway LXC created directly on `pve` (not `pve-test-vm`): Local
   Agent Builder skill, Microsoft Agent Framework, three tiers, DDGS
   search. Do not pre-substitute SearXNG, two-tier delegation, or
   Playwright before this runs and is measured.
2. **Refine in Stage B** using Stage A's own measurements: SearXNG vs.
   DDGS, two-tier vs. three-tier, and Playwright fallback are Stage B
   questions, not decisions already made here.
3. **No workstation development or execution at any stage.** Scaffolding
   (including any coding-agent session that builds or edits the
   application), running the service, and evaluation all happen inside
   containers on `pve` — a throwaway LXC for Stage A, `ai-services-stack`
   for Stage B. `pve-test-vm` is not used.
4. Reuse `ai-services-stack` for the Stage B production runtime; do not
   create another LXC for it.
5. Keep search behind an application adapter so the Stage B provider
   choice doesn't require changing agent prompts or orchestration.
6. Keep `mcp-utility-stack` focused on its existing docs-RAG and CVE
   services; do not add browser or search-agent workloads to its current
   1 GiB LXC.
7. Pi (or another coding agent) may build or edit the application, but
   only against a container on `pve` — never the workstation, never
   `pve-test-vm` — and is not a required production runtime layer.
8. **Rebuild the live Nathanw llama.cpp deployment as Ansible IaC before
   depending on it further.** The live service was deployed manually and
   has no reproducing playbook (see "Nathanw llama.cpp IaC gap" below).
   This is now a prerequisite phase, not a documentation footnote.

## Nathanw llama.cpp IaC gap

Checked 2026-09-21: the live Framework endpoint
(`qwen38-flash-next-q4`, `ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan`,
port 8080, `Qwen3.8-Flash-Next-UD-Q4_K_XL`, 4 slots, 262144 ctx) was
deployed manually by the operator, not through this repo's Ansible.

The one existing file,
`ansible/00-initial-setup/framework-desktop-llamacpp-nathanw.yml`, is
explicitly marked "NOT WIRED UP — kept as reference only, do not run
as-is" in its own header, and does not reproduce the live configuration
even in principle: it targets port 8081, a different model
(`Qwen3.8-27B-Q4_K_M`), and a from-source build rather than the live
prebuilt image. Running it would collide with the live container, not
recreate it.

This must be fixed before the deep-research plan can treat the model
endpoint as a dependable, rebuildable dependency — see Phase 0 below.

## Source material

The design began with the companion repository's
`docs/DeepResearch/plan.md` and
`docs/DonatoCapitela/LocalDeepResearchAgent.txt`. It has been reconciled with
the live homelab and the following upstream implementations:

- [Local Agent Builder](https://github.com/kyuz0/local-agent-builder)
- [DDGS](https://github.com/deedy5/ddgs)
- [SearXNG search API](https://docs.searxng.org/dev/search_api.html)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [web-search-mcp](https://github.com/mrkrsl/web-search-mcp)
