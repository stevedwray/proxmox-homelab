# Deep research: current state

Checked 2026-09-21. This is an inventory, not a deployment record. No service
or infrastructure changes were made while gathering it.

## Executive summary

Most prerequisites already exist:

- the Framework Desktop is serving the intended Qwen model through an
  OpenAI-compatible llama.cpp endpoint;
- `ai-services-stack` is running on `pve`, already reaches Framework, and
  already hosts SearXNG;
- SearXNG has JSON output enabled and a deliberately curated engine list;
- the shared MCP LXC provides internal-doc and vulnerability research tools;
  and
- a Playwright-based general web-search MCP is installed on the operator
  workstation.

The missing component is the deep-research application itself. The existing
Playwright server is local stdio, not a network service, and is not deployed in
either Proxmox stack.

## Framework Desktop inference

The live endpoint at `framework.gibbsgreatly.xyz:8080` reported:

| Property | Observed state |
|---|---|
| Runtime | Nathanw1014 Strix Halo fork of llama.cpp |
| Build | `b10710-b02cb35f` |
| Model | `Qwen3.8-Flash-Next-UD-Q4_K_XL` |
| Parameters | approximately 176.9B total |
| Model size | approximately 111.3 GB |
| Context | 262,144 tokens |
| Slots | 4 |
| API shape | OpenAI-compatible `/v1` API |
| Authentication | none enforced at the llama.cpp endpoint |

Health, model discovery, properties, and slot state were all readable. Four
slots being configured does not establish that four concurrent research
agents are the best operating point; concurrency still needs a workload test.

The live Nathanw deployment was performed directly by the operator. The older
repository playbook at
`ansible/00-initial-setup/framework-desktop-llamacpp-nathanw.yml` is explicitly
documentation/reference and must not be assumed to reproduce the live model.
The established current-state description is also recorded in
[CyberSecEval current state](../cyberseceval-implementation/current-state.md).

## `ai-services-stack` on `pve`

The production LXC is VMID `50013` in `ai_seg`. It is running and currently
hosts:

- OpenWebUI;
- SearXNG; and
- the Ollama reliability proxy.

Its declared stack size is 2 cores, 4 GiB RAM, 1 GiB swap, and a 24 GiB Docker
volume. The live Proxmox inventory reported 6 GiB RAM, so the declared/live
difference must be resolved or deliberately accepted before treating the
manifest as a capacity source of truth.

This stack is the natural initial home for deep research because it already:

- is an AI application tier rather than the GPU-serving tier;
- has broad internet egress for SearXNG;
- has the permitted path to Framework on TCP 8080; and
- owns the SearXNG configuration and lifecycle.

Its contract is
[terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md](../../terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md).

## SearXNG

The live SearXNG instance is available inside `ai-services-stack` and on the
host's machine-to-machine port 8082. Its managed settings enable both HTML and
JSON response formats. A co-located research container should use the internal
Docker service URL where possible:

```text
http://searxng:8080/search?q=<query>&format=json
```

The engine set has already been adapted to this network:

| Engine | Current disposition | Reason |
|---|---|---|
| Mwmbl | enabled | Returned useful results without bot rejection |
| SearchMySite | enabled | Returned results without bot rejection |
| Bing scraper | enabled | Generally works, but produced noisy results for some recency queries |
| Brave Search API | enabled when a key is present; weighted above Bing | API-backed, but subject to the account's shared rate limit |
| DuckDuckGo HTML | disabled | Hard TCP timeout from this WAN path |
| Google CSE, Startpage, scraped Brave, Qwant, Yahoo, Presearch | disabled | CAPTCHA, suspension, bot detection, or unsuitable general-web behavior |

A live probe during this research confirmed that JSON search works, but it
also reproduced the quality problem: Mwmbl contributed relevant material,
Bing contributed unrelated results for a technical query, and Brave API was
rate-limited. SearXNG availability therefore does not by itself guarantee
research-quality retrieval.

The configuration and its operational history are documented in:

- [AI services deployment](../../terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml)
- [SearXNG lessons learned](../design/lessons-learned.md#searxng)

OpenWebUI currently uses Brave's standard API directly rather than SearXNG for
AI search. The Brave key and quota are shared concerns if deep research also
uses the `braveapi` engine through SearXNG.

## Shared MCP services

The production `mcp-utility-stack` is VMID `50011` in `ai_seg`. Its declared
size is 2 cores, 1 GiB RAM, and 512 MiB swap. It provides two network MCP
servers:

| Server | Endpoint | Role |
|---|---|---|
| `docs-rag` | `http://192.168.50.10:8001/mcp` | `search_docs`, `list_stacks`, and `get_document` over this repository's documentation |
| `cve-mcp` | `http://192.168.50.10:8000/mcp` | CVE, NVD, EPSS, KEV, OSV, advisory, and threat-intelligence research |

These are specialist sources that can improve relevant investigations. They
do not provide general web search. Their client configuration is in
[.vscode/mcp.json](../../.vscode/mcp.json), and the service boundary is in the
[MCP utility stack contract](../../terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md).

The MCP LXC should not absorb Playwright merely because both expose MCP. A
browser workload has different memory, internet-egress, and untrusted-content
characteristics, while the LXC currently has only 1 GiB RAM.

## Existing Playwright web search

The operator workstation has an existing checkout at:

```text
/home/steve/mcp-servers/web-search-mcp
```

Observed state:

| Property | State |
|---|---|
| Package | `web-search-mcp-server` 0.3.1 |
| Playwright | 1.54.2 installed |
| Browsers | Chromium, Chromium Headless Shell, and Firefox installed |
| Transport | local stdio, launched by VS Code |
| Running continuously | no; MCP client starts it on demand |
| Network reachable | no |

It exposes three tools:

- `get-web-search-summaries`;
- `full-web-search`; and
- `get-single-web-page-content`.

Its current search sequence is browser-driven Bing, browser-driven Brave, then
an Axios DuckDuckGo fallback. It enforces a ten-searches-per-minute limiter and
can fetch full page content. This is a genuine existing capability, but its
location matters: an application running in the Proxmox LXC cannot consume a
workstation-local stdio process without relocating it or adding a supported
network transport.

The current architecture notes had already called for workstation-side
Playwright with an isolated profile; see
[local AI development](../framework-ubuntu/local-ai-development.md#mcp-layer).

## What Donato's implementation actually does

The Local Agent Builder scaffold is based on Microsoft Agent Framework. Pi is
used to copy and modify that scaffold; the resulting Python application is the
runtime. The TUI comes from Textual.

The scaffold's
[current `web_search` tool](https://github.com/kyuz0/local-agent-builder/blob/e5b048925acbf9a981ddb28bf61a72a46f60e34a/skills/local-agent-builder/examples/basic-tui-agent/src/tools/web.py):

1. imports `DDGS` from the Python `ddgs` package;
2. creates a shared client;
3. calls `client.text(query, max_results=...)` or `client.news(...)`; and
4. returns titles, URLs, and snippets to the agent.

The configuration calls this provider `duckduckgo`, but the call does not pass
`backend="duckduckgo"`. The
[current DDGS implementation](https://github.com/deedy5/ddgs/blob/main/ddgs/ddgs.py)
defaults to `backend="auto"`, which can select and combine multiple search
backends. The dependency is also unpinned in the example. Consequently,
current scaffold behavior can drift with DDGS and should not be interpreted as
use of a stable DuckDuckGo API.

Page retrieval is separate from search. `fetch_url_to_workspace` uses `httpx`,
follows redirects, caps stored content at 5 MB, and converts HTML or PDFs to
Markdown using MarkItDown, BeautifulSoup, and optionally LiteParse. It does not
use Playwright.

The important reusable design is therefore:

```text
search for candidate sources
       -> fetch selected sources to isolated workspace files
       -> inspect only relevant sections
       -> return distilled findings and source URLs
       -> synthesize a cited report in a clean context
```

The video's recent date does not remove the operational uncertainty of scraped
search. Results depend on egress IP reputation, geography, rate history, exact
package version, query shape, and provider anti-bot changes. The sustained
homelab workload must be evaluated from the homelab's own egress path.

## Gaps before implementation

- No deep-research application or persistent workspace exists.
- There is no stable application-level search-provider contract.
- The existing Playwright MCP is not packaged for Proxmox or exposed through a
  network MCP transport.
- Search quality, rate limits, and fallback behavior lack a fixed evaluation
  dataset.
- Source fetches need SSRF, redirect, size, type, and prompt-injection controls.
- The llama.cpp endpoint is unauthenticated; access relies on network policy.
- The correct runtime concurrency and model request limits have not been
  established for this workload.
