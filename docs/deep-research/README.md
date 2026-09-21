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

Start by adding a separate, isolated application container to the existing
`ai-services-stack` LXC on `pve`. Do not create another LXC for the first
version.

```text
User / TUI / future web UI
           |
           v
Deep-research runtime (Microsoft Agent Framework)
  in ai-services-stack, separate container and volume
           |
           +---- OpenAI-compatible API ----------------------+
           |                                                 |
           +---- SearXNG JSON search --+                     v
           |                           |       Framework Desktop
           +---- HTTP/Markdown fetch   |       Nathanw llama.cpp
           |                           |       Qwen3.8-Flash-Next
           +---- optional Playwright --+
           |
           +---- optional specialist MCP tools
                    +-- docs-rag
                    +-- CVE/threat intelligence
```

The first working slice should use SearXNG for search and a constrained plain
HTTP fetcher for documents. The existing Playwright-based web-search MCP is a
measured fallback for browser-dependent searches and pages, not a mandatory
dependency of every request.

## Decisions captured here

1. Reuse `ai-services-stack` for the initial runtime.
2. Use the existing SearXNG JSON API as the primary search interface.
3. Keep search behind an application adapter so another provider can be used
   without changing agent prompts or orchestration.
4. Reuse the existing Playwright implementation only after an evaluation shows
   that it improves coverage enough to justify its browser cost.
5. Keep `mcp-utility-stack` focused on its existing docs-RAG and CVE services;
   do not add browser workloads to its current 1 GiB LXC.
6. Use Microsoft Agent Framework as the deployed agent runtime. Pi may build or
   edit the application, but Pi is not a required production runtime layer.
7. Deliver a flat end-to-end slice first, then introduce two-tier delegation;
   add page-analyzer agents only when measurements justify a third tier.

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
