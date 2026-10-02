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

- [x] Operator prerequisite: cloned `lidless-labs/maltego-mcp` to `~/git/maltego-mcp`, pinned to `cb8100423d6cc4215e546f2c4125f5225d9dc282` — 2026-10-02
- [x] `maltego-01-vendor-source` — 2026-10-02
- [x] `maltego-02-dockerfile-and-driver` — 2026-10-02
- [x] `maltego-03-compose-service` — 2026-10-02
- [x] `maltego-04-stack-contract` — 2026-10-02
- [x] Deployed to `pve-tiny` (`provision.sh --stack mcp-utility-stack`) — 2026-10-02, 8 total deploy rounds across the two bug-fixing passes below
- [x] Phase 1 test run on pve-tiny: produced a valid `.mtgx` — 2026-10-02
- [x] **Operator opened the file in real Maltego Desktop 4.13.0 and confirmed it renders correctly** — 2026-10-02: correct entity icons (Domain/IPv4Address/AS/Phrase), correct values (not placeholder text), correct link labels (`resolves_to`/`has_nameserver`/`hosted_in`/`certificate`/`SAN`), correct topology. **This is the actual Phase 1 milestone, and it's done.** Confirmed artifact saved at `artifacts/test-example-com-v4-confirmed-working.mtgx`.
- [x] **Phase 2 Tier 1 enrichment (VirusTotal/Shodan/GreyNoise) — done 2026-10-02.** See "Growing Phase 2" below.
- [x] **Phase 2 Tier 2 (AlienVault OTX) — fully live, confirmed 2026-10-02.** Operator provisioned a real key, written to OpenBao and added to `secrets/manifest.json`. Confirmed live on pve-tiny: real pulse data for `example.com` (50 pulses on the domain, 2 and 0 on its two IPs). Saved at `artifacts/test-example-com-tier2-otx-confirmed-prod.mtgx`.
- [x] Phase 2 Tier 3 (OCCRP Aleph) — **dropped, not pursued.** Requires a vetted journalist/public-interest application (organization affiliation, evidence of prior work), not a self-serve signup like OTX. A poor fit for a homelab OSINT lab, with no guarantee of approval. Operator decision 2026-10-02: skip it, move to Phase 3 instead.
- [x] **Phase 3: osint-mcp, a real HTTP MCP server — fully live, confirmed 2026-10-02.** `investigate_domain` MCP tool, Streamable HTTP, bearer-token auth, confirmed reachable end-to-end from `deep-research-agent`'s actual container across the container boundary. See "Phase 3" section below. `deep-research-agent` itself has not been wired to call it yet — that's the next real step.

## Real bugs found and fixed via live deployment (2026-10-02)

The plan's four step-blocks all passed their gates (syntax-check, grep
counts) on first execution, but gates only prove the file edits landed —
none of them actually build or run the image. Every one of the following
was found by actually deploying and running it, not by review:

1. **`provision.sh` silently skipped the deploy** the first time —
   resolved its repo root to the unrelated `proxmox-homelab-eval-runner`
   git worktree (inventory.yml is gitignored/per-checkout, not shared
   between worktrees). Fix: run from the main checkout.
2. **`maltego-mcp`'s image was never built at all** on the first real
   deploy — `community.docker.docker_compose_v2`'s `state: present`
   only touches default-profile services, and `maltego-mcp` is
   deliberately `profiles: ["tools"]` (see README above). Added an
   explicit `docker compose --profile tools build maltego-mcp` task.
3. **`tsup.config.ts` needs `scripts/demo-basic.ts`** as a build entry —
   `maltego-01`'s copy list never included `scripts/`, so `npm run
   build` failed outright on the very first build attempt.
4. **`ENTRYPOINT ["node"]` doubled up with the run command** —
   `docker compose run --rm maltego-mcp node dist/phase1-expand-domain.js`
   became `node node dist/phase1-expand-domain.js` (MODULE_NOT_FOUND).
   Dropped the entrypoint; a bare `CMD` lets `run` fully override it.
5. **The driver script's whole import strategy was wrong.**
   `tsup.config.ts` has `splitting: false`, so each entry bundles into
   one flat file (confirmed locally: `npm run build` produces
   `dist/index.js`, `dist/cli.js`, etc. — never `dist/graph/`,
   `dist/lookups/`). The original driver imported from assumed
   `./dist/graph/graph.js`-style paths that could never have existed.
   Rewrote it as `phase1-expand-domain.ts` importing from `./src/...`
   and bundled it with the project's own `tsup`/esbuild mechanism in
   the builder stage — this also incidentally fixed a file-ownership
   bug (tsup output is world-readable like the project's own entries,
   no `--chown` workaround needed).
6. **`Graph.addEntity` throws on a duplicate type+value pair** — a
   domain with multiple A records on one ASN (e.g. `example.com` →
   `AS13335` for every IP) crashed on the second occurrence. Switched
   every entity that can legitimately repeat (IP, ASN, nameserver,
   cert) to `ensureEntity`.
7. **`"DNSName"` and `"Certificate"` aren't valid entity types** — this
   project has a fixed 12-type allowlist
   (`src/graph/entities.ts`:`ENTITY_TYPES`) and throws immediately on
   anything else, not a silent fallback. Nameservers now use `"Domain"`;
   certificates use `"Phrase"` with a `"[Certificate] "` prefix, matching
   the project's own convention for anything without a dedicated type.

Each fix was verified locally against the real pinned `~/git/maltego-mcp`
clone before being redeployed, to avoid burning repeated full
`provision.sh` cycles on fixes that could be proven wrong (or right)
faster with a local `tsup`/`node` run. See commit history on
`docs/maltego-integration-plan` for the individual fixes.

## The real finding: maltego-mcp's writer doesn't work against real Maltego Desktop

The 7 bugs above all got the pipeline running, but the resulting file
produced an import that **spun forever with no error** in real Maltego
Desktop 4.13.0 — not a hang in the usual sense, confirmed by reading
Maltego's own `~/.maltego/v4.13.0/var/log/messages.log`: the graph loader
threw a `NullPointerException` on a background thread every time
(`StaxGraphReader.flushEntities`, "Cannot read field 'x' because 'center'
is null"), and the exception never reached the UI, so the tab just sat
there loading indefinitely. This reproduced identically even on a
hand-built single-entity, zero-edge file — ruling out anything about
*our* graph content and pointing at the library's writer itself.

Root cause, found by comparing against `pcbje/pymtgx` (a different,
older, independently-written library that genuinely works against real
Maltego): `maltego-mcp`'s `writeMtgxFile` emits node position as generic
yFiles GraphML (`y:ShapeNode`/`y:Geometry`). Real Maltego Desktop's own
graph reader does not read position from that at all — it expects
Maltego's own `mtg:EntityRenderer`/`mtg:Position` element. This is a
genuine bug in the upstream library against current Maltego Desktop, not
a misuse on our part — its own test suite only round-trips through its
own reader, never against a real Maltego installation, so this was never
caught. This directly answers `brief.md`'s open question #1/#2 ("how does
maltego-mcp actually construct MTGX files" / "is its graph model
sufficient") — **no, not as shipped.**

**The fix**: stopped using `writeMtgxFile` entirely. The driver script
now uses `maltego-mcp`'s `Graph` class and lookup functions (`dnsLookup`,
`whoisLookup`, `asnLookup`, `crtshLookup` — these are fine, just HTTP
calls) for building and deduplication, but serializes the final
`.mtgx` itself with a small native writer matching the proven
`mtg:EntityRenderer`/`mtg:Position` schema. Two further bugs surfaced by
the same live-Maltego-Desktop testing loop, both real and both confirmed
against this machine's actual installed Maltego:

1. **`<edge>` needs an explicit `id` attribute.** GraphML allows omitting
   it; Maltego's `StaxGraphReader.readEdge` throws "Mandatory attribute
   does not exist: id" without it.
2. **Every entity rendered (correct icon, correct links, correct
   topology) but showed `<empty>` as its value.** `"properties.value"`
   isn't a real field on any Maltego entity type. Extracted the actual
   per-type field names directly from this machine's installed Maltego
   entity definitions (`com-paterva-maltego-entities-common.jar`,
   `maltego.<Type>.entity`'s `<Properties value="...">` attribute):
   `maltego.Domain` → `fqdn`, `maltego.IPv4Address` → `ipv4-address`,
   `maltego.AS` → `as.number`, `maltego.Phrase` → `text`.

**Confirmed working end-to-end by the operator**, not just inspected
locally: the resulting `.mtgx` opens in real Maltego Desktop 4.13.0 with
correct entity icons, correct values, correct link labels, and correct
topology for `example.com`. Saved at
`artifacts/test-example-com-v4-confirmed-working.mtgx`.

## Growing Phase 2: Tier 1 enrichment (VirusTotal/Shodan/GreyNoise)

Prompted by the operator noticing how many genuinely useful free-tier
providers show up in Maltego's own Data Hub tab — those tiles themselves
can't be invoked headlessly (they're Transform Distribution Server
transforms, designed around an interactive Desktop client, gated behind
Maltego's paid automation products for anything else), but many of their
*underlying providers* have perfectly good standalone REST APIs we can
call directly. VirusTotal, Shodan, and GreyNoise were picked as the
simplest possible first batch: `shared/external-apis` in OpenBao already
has live, populated keys for all three from earlier work, so this needed
zero new secrets, zero new firewall rules — just new code.

Verified current API terms before building anything (per this repo's own
"don't assume a free tier is still free" rule): VirusTotal Public API is
still free (500/day, 4/min, non-commercial), GreyNoise Community is
limited (50/week with a business-email account), AlienVault OTX (Tier 2,
not yet built) is the most generous of the bunch (10,000/hr with a key,
no paid tier even required).

Rather than re-deriving request/response shapes from API docs, pulled the
exact verified shapes from this operator's own already-working
`cve-mcp-server` fork (`~/git/cve-mcp-server/src/cve_mcp/api/{ip_intel,
shodan_client,hash_intel}.py`) — real code already running in this
infrastructure, not documentation that might be stale. That comparison
surfaced two real, separate findings:

- **GreyNoise's free `/v3/community` endpoint was deprecated in January
  2026** (per that fork's own code comment) — this operator's own prior
  work had already discovered and adapted to this. The new enrichment
  code calls the real `/v3/ip/{ip}` endpoint instead of the officially-
  documented-but-dead community one.
- **`VIRUSTOTAL_KEY` in OpenBao is broken** — confirmed live with a real
  test call: HTTP 401 "Wrong API key". The stored value is 23 characters;
  real VT v3 keys are 64-character hex strings, so this was likely never
  a valid key, not an expired one. This isn't new — `cve-mcp-server`'s
  own already-deployed hash-lookup code uses this exact same key and has
  been silently failing the same way (caught by try/except, logged as a
  warning no one sees) in production this whole time. Documented in
  `terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md`'s Inputs
  table; rotating the key is a separate, operator-owned fix, out of scope
  here.

Implementation: three new best-effort lookup functions added directly to
`phase1-expand-domain.ts` (not to `maltego-mcp`'s own vendored source —
this is our own driver, extending it is the lowest-friction path and
keeps the pinned upstream library untouched). Each degrades gracefully
on a missing/invalid key or network error — enrichment never blocks
graph generation. VirusTotal enriches the root `Domain` and every
`IPv4Address` entity with `vt_malicious`/`vt_suspicious`/`vt_reputation`;
Shodan adds `shodan_org`/`shodan_ports`/`shodan_vulns`; GreyNoise adds
`greynoise_classification`/`greynoise_noise`/`greynoise_riot`. The
`maltego-mcp` compose service, which previously had no `environment:`
block at all, now passes through the three keys from the same Ansible
vars already used for `cve-mcp-server`.

**Confirmed working live on pve-tiny** (not just locally): Shodan
returned real org/port data for `example.com`'s Cloudflare IPs, GreyNoise
returned a real (negative) classification. VirusTotal absent as expected
given the broken key. Saved at
`artifacts/test-example-com-tier1-confirmed-prod.mtgx`.

**Not done yet**: Tier 3 (OCCRP Aleph — needs an account application
first).

## Tier 2: AlienVault OTX (done)

`otxLookup()` in the driver: `GET /api/v1/indicators/{domain|IPv4}/
{value}/general` with header `X-OTX-API-KEY`, enriching the root `Domain`
and every `IPv4Address` entity with `otx_pulse_count`/`otx_pulse_names`.
Endpoint verified against the official LevelBlue docs
(`otx.alienvault.com/assets/static/external_api.html`) after an
unrelated, older community gist showed a different `/indicator/`
(singular) path that looked plausible but didn't match the canonical
source — checked rather than trusted.

Shipped in two stages, deliberately: code first with a safe
`default('', true)` env lookup (no manifest entry, confirmed live with
both no key and a deliberately bogus key — clean no-op either way, never
a crash), *then* the real secret once the operator had provisioned one.
Adding a manifest field before the real value exists would trip
`secrets_env.py`'s fail-closed check for every stack on every node
profile that includes `shared/external-apis` (all of them) — the exact
failure mode already hit once during the deep-research Nextcloud push
work. The actual write used the exact commands in
`docs/reference/secrets-management.md`'s "Adding or rotating a secret"
(the entry is `shared/external-apis`, not `services/external-apis` as an
earlier draft of this doc wrongly said):

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # Authentik, group homelab-admins
LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py shared/external-apis OTX_API_KEY
unset BAO_TOKEN
```

Verified before trusting it: a scratch-manifest `--check` dry run
confirmed the field was non-empty and 64 hex characters (matching OTX's
real key format, unlike the still-broken 23-char `VIRUSTOTAL_KEY`), then
a direct `curl` with the real key against the real API confirmed actual
data (`pulse_info.count: 50` for `example.com`) before the real
`secrets/manifest.json` was touched at all. Then: added `OTX_API_KEY` to
the real manifest (re-verified `--check` passes for both `pve` and
`pve-tiny`), switched the compose var to `mandatory()`, redeployed, and
confirmed live on pve-tiny — real pulse data for `example.com` itself
(50 pulses) and both its IPs (2 and 0). Saved at
`artifacts/test-example-com-tier2-otx-confirmed-prod.mtgx`.

## Hand-back: maltego-01 through maltego-04 (2026-10-02)

All four step-blocks executed directly (not via a separate local-model
`/implement-step` pass — the frontier-model session that planned this also
ran it, since every step was a plain file edit with no production access
needed). Planning commits: `903890fb`, `f2c1eee8`, `07e247c8`. Execution
commit: `b2de3035` (`feat(mcp-utility-stack): vendor maltego-mcp for Phase
1 OSINT -> MTGX PoC`), all on `docs/maltego-integration-plan`.

Real edits made:

- `terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml`: added
  `maltego_source_dir`/`maltego_build_dir` vars, three source-copy tasks,
  a literal Dockerfile-writing task, a literal driver-script-writing task,
  the `maltego-mcp` compose service (`profiles: ["tools"]`, no port, no
  `restart:`), and the `maltego-mcp-output` named volume.
- `terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md`: added a
  `maltego-mcp` row to Provides and a gotcha bullet about the deliberate
  lack of `profiles` auto-start.

Gate results (all passed):

- `ansible-playbook --syntax-check` (run from `terraform/lxc/ansible/`
  with its own `ansible.cfg` — running it from the repo root fails to
  resolve `roles/`, that's a pre-existing environment quirk, not a defect
  in this change): clean, only a pre-existing unrelated `wazuh_agent`
  deprecation warning.
- `grep -c 'maltego-mcp'` on the playbook: 17 (gate wanted ≥5)
- `grep -c 'phase1-expand-domain.mjs'` on the playbook: 6 (gate wanted ≥2)
- `grep -c 'maltego-mcp-output'` on the playbook: 2 (gate wanted ≥2)
- `grep -c 'maltego-mcp'` on `STACK_CONTRACT.md`: 2 (gate wanted ≥2)

Not done yet — explicitly operator actions, not local-model steps:
deploying (`provision.sh --stack mcp-utility-stack`, needs the normal
production approval flow), running the Phase 1 test command inside the
deployed LXC, and manually opening the resulting `.mtgx` in Maltego
Desktop. That last one is the actual milestone this whole plan exists to
answer — nothing above it proves Maltego will accept the file, only that
the pipeline that produces it is wired up correctly.

## Phase 3: osint-mcp, a real HTTP MCP server (done)

The brief's own architecture called for `deep-research-agent` to call
the OSINT backend as a real MCP client, not a plain HTTP tool (decided
earlier, see "Key decisions"). Before writing any code, confirmed two
things that weren't already known:

- **`agent_framework`'s actual MCP client support**, by reading the
  package installed inside the real `deep-research` container
  (`/usr/local/lib/python3.12/site-packages/agent_framework/_mcp.py`):
  `MCPStdioTool`, `MCPStreamableHTTPTool`, and `MCPWebsocketTool` are all
  real, built-in classes. No need to hand-roll an MCP client.
- **`maltego-mcp`'s own `mcp-server.ts` speaks stdio only** — a stdio
  transport spawns a child process in the *caller's* own container and
  cannot reach a server running in a *different* container. Since
  `deep-research-agent` (`ai-services-stack`) and `maltego-mcp`
  (`mcp-utility-stack`) are genuinely separate LXCs on the same pve-tiny
  host, stdio literally cannot work here. The serving side needs
  Streamable HTTP — the same pattern `cve-mcp-server`/`docs-rag-mcp`
  already use in this stack.

Built `osint-mcp-server.ts`, a new purpose-built server (same precedent
as `docs-rag-mcp`: written in-repo, not a vendored dependency) exposing
one real MCP tool, `investigate_domain`, over Streamable HTTP. Used the
MCP SDK's own `createMcpExpressApp()` + `StreamableHTTPServerTransport`
(the SDK's own stateless example was the template, not invented wiring)
— `express` is already a transitive dependency of
`@modelcontextprotocol/sdk` itself, no new package needed.

**Refactored first**: `phase1-expand-domain.ts`'s lookup/graph-building
logic (previously one top-level-await script) moved into a new shared
`investigate.ts` module (`investigateDomain()`/`writeMtgxNative()`), so
the CLI driver and the new MCP server share one implementation instead
of duplicating Tier 1/2 enrichment logic. Verified the CLI still behaved
identically after the refactor before building anything on top of it.

**Auth, a deliberate departure from precedent**: unlike `cve-mcp-server`/
`docs-rag-mcp` (zero app-layer auth, network-only via MikroTik rules),
`osint-mcp` requires `Authorization: Bearer <OSINT_MCP_TOKEN>` on every
request — the original brief explicitly asked for real auth even on
LAN, and this is the first new network-reachable surface since that
requirement was written, so it was worth actually doing rather than
repeating the existing gap. The server calls `process.exit(1)` if no
token is configured, rather than ever listening unauthenticated.

Token provisioning followed the same safe pattern as `OTX_API_KEY`
(generate-then-verify-then-promote), but since this is an *internal*
secret (not a third-party API key), it lives in `services/mcp-utility`
(same entry as `DOCS_RAG_POSTGRES_PASSWORD`), not `shared/external-apis`:

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
openssl rand -hex 32   # the operator generates this value themselves
LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/mcp-utility OSINT_MCP_TOKEN
unset BAO_TOKEN
```

**Three real bugs found via live testing**, none caught by local testing
alone:

1. **`restart: unless-stopped` + no token = an active crash-loop**, not
   a quiet stopped container — found live (`docker ps` showed
   `Restarting (1)` every ~10s). Stopped manually while the token was
   being provisioned; resolved cleanly once the real token landed.
2. **`createMcpExpressApp()` defaults to localhost-only DNS-rebinding
   protection** (`host: "127.0.0.1"`) — any request with a Host header
   other than `127.0.0.1`/`localhost`/`::1` gets a 403 *before auth even
   runs*. A real call from `deep-research-agent`'s container to the
   LXC's actual IP (`192.168.50.10:8010`) was rejected outright. Fixed
   with explicit `allowedHosts` — the same class of gotcha already
   documented for `docs-rag-mcp`'s own `MCP_ALLOWED_HOSTS`, hit a second
   time on a different service.
3. **`hostHeaderValidation()` compares hostname only, port-agnostic** —
   the first fix attempt passed `"192.168.50.10:8010"` verbatim as an
   allowed host, which never matched the parsed hostname
   `"192.168.50.10"` alone, so it still 403'd. `OSINT_MCP_ALLOWED_HOSTS`
   keeps the familiar `host:port,host:port` shape operators already know
   from `MCP_ALLOWED_HOSTS`; the port is stripped in code before being
   passed to `allowedHosts`.

**Confirmed working fully end-to-end**, the real path this whole phase
exists to prove: a request from inside `deep-research-agent`'s actual
Docker container, across the container boundary, to `osint-mcp`'s real
LXC IP, with the real `OSINT_MCP_TOKEN`, returning a real `tools/list`
result over HTTP 200. Not simulated, not same-host-only — the actual
cross-container call.

**Not done yet**: `deep-research-agent` itself has not been changed —
no `MCPStreamableHTTPTool` has been added to its tool list, so nothing
in the running agent can call `osint-mcp` yet. That's the next real
step, and it touches a different, actively-in-use codebase (the
deep-research agent's own `app.py`/tool registration), not just this
stack's own files.
