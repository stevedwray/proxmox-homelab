# maltego-integration

Status: **planning done for Phase 1, no steps executed yet.**

## What this is

A headless OSINT/Maltego integration for the local AI environment. Maltego
Desktop is a graph viewer, not the research backend — the actual investigation
work (DNS/RDAP/crt.sh/WHOIS/ASN lookups, later richer threat-intel enrichment,
AI-assisted analysis) runs independently and produces `.mtgx` files Maltego
opens. See `brief.md` for the original design brief this plan was scoped from.

## Key decisions made during planning (2026-10-02)

Resolved with the operator before `plan.md` was written — see `brief.md`'s
"Questions the Design Phase Should Resolve" for the open items these answer:

- **Reuse the `mcp-utility-stack` LXC rather than building a new OSINT-
  service LXC, but keep `cve-mcp-server` itself CVE-only.** `cve-mcp-
  server` already lives here (`ai_seg`, pve-tiny) and its upstream bundles
  ~21 threat-intel integrations, about half currently disabled (keys
  unset, not firewall-allowlisted) specifically because they were deferred
  for "a different use case (network/IOC investigation)" — i.e. this exact
  effort. **Revisited 2026-10-02**: enabling those dormant tools (IP
  reputation, domain intel, Shodan, etc.) directly on `cve-mcp-server`
  would quietly turn a server whose name, repo, and `STACK_CONTRACT.md`
  all say "CVE research" into the backend for an unrelated Maltego OSINT
  workflow too — two unrelated consumers sharing one identity, one quota
  story, and one blast radius, with nothing in the contract saying so.
  Instead: **Phase 2's enrichment lookups (IP reputation, domain intel,
  Shodan, etc.) will be built as new tools on `maltego-mcp` itself**
  (already in this same LXC/zone from Phase 1, already has an extensible
  `tools/` directory), leaving `cve-mcp-server` untouched and honestly
  CVE-scoped. `cve-mcp-server`'s own dormant tools stay dormant — they
  were useful evidence that this use case was anticipated, not a
  component to repurpose.
- **deep-research-agent will call the OSINT backend via a true MCP client**,
  not a plain HTTP tool. This is a genuinely new pattern for that codebase —
  confirmed by grep, it has zero existing MCP client code today (every
  existing tool, e.g. `web_search`, is a direct HTTP call). This is Phase 3
  scope, not needed for Phase 1.
- **New OSINT provider API keys go into the existing `shared/external-apis`
  OpenBao entry**, matching precedent (`VIRUSTOTAL_KEY`, `SHODAN_KEY`,
  `GREYNOISE_API_KEY` already live there; `ABUSEIPDB_KEY`/`URLSCAN_KEY`/
  `CIRCL_PDNS_*` are already declared-but-unset in the same bucket).
- **Only Phase 1 (the minimal graph PoC) is written as bounded step-blocks
  right now.** Phases 2-6 are intentionally left as prose/future work in
  `brief.md` until Phase 1's result — whether Maltego actually adds enough
  value — is known.
- **`maltego-mcp` (the brief's proposed MTGX-generation tool) was inspected,
  not assumed.** Web search surfaced several near-identical forks by
  unrelated-looking GitHub accounts (a real supply-chain caution sign), so
  the operator asked for a source read before depending on it. Inspected
  `lidless-labs/maltego-mcp` directly (commit `16a27a0`... — actually: see
  `plan.md`'s maltego-01 step for the exact pin): MIT-licensed, clean
  module layout, real `SECURITY.md` with an honest threat model, no
  shell-outs (uses the pure-JS `whois` npm package, not a spawned CLI —
  no injection surface), and its `.mtgx` writer matches Maltego's real,
  documented GraphML+zip format. Cleared for use.

## Real architectural finding worth remembering

`maltego-mcp` speaks **stdio MCP transport only** — it is not a long-running
HTTP daemon like `cve-mcp-server`/`docs-rag-mcp`. Phase 1 deliberately avoids
needing an MCP client at all: it calls the project's own exported TypeScript
lookup/graph functions (`dnsLookup`, `whoisLookup`, `asnLookup`,
`crtshLookup`, `Graph`, `writeMtgxFile`) directly from a small driver script,
run via `docker compose run --rm` (the compose service is defined with
`profiles: ["tools"]` so it never starts as a background daemon). Real MCP
protocol usage (stdio, spawned per-call) is deferred to whichever later
phase actually needs an LLM agent driving it interactively.

## Status

- [ ] `maltego-01-vendor-source` — not started
- [ ] `maltego-02-dockerfile-and-driver` — not started
- [ ] `maltego-03-compose-service` — not started
- [ ] `maltego-04-stack-contract` — not started
- [ ] Operator: clone `lidless-labs/maltego-mcp` to `~/git/maltego-mcp`, deploy via `provision.sh --stack mcp-utility-stack`, run the Phase 1 test, open the resulting `.mtgx` in Maltego Desktop — not started

Hand-backs from `implement-step` land below this line as each step runs.
