# MCP Stack Plan

Status: **proposed — planning only.** No server in this document is approved
for production access or installation merely by being listed here.

## Purpose

Provide AI agents with useful, structured access to repository and homelab
state without granting a general shell, bypassing established Terraform/
Ansible workflows, or weakening the production approval controls.

The expected benefits are faster investigation and more reliable evidence
gathering: an agent can inspect a Proxmox guest, router state, GitHub checks,
or a limited worktree through typed tools instead of screen-scraping commands.
MCP is not the source of truth for infrastructure declarations; Terraform,
Ansible, manifests, and repository scripts remain that source.

## Design decisions

1. **Local first.** The first useful MCP tools run as local `stdio` processes
   for one agent session, rather than as network services. This does not
   require a deployed/hosted container: the MCP client spawns the server
   process itself (either a direct `uvx <package>` process or an ephemeral
   `docker run --rm -i <image>` container tied to that one session), on the
   workstation, for the lifetime of the session only. A persistently-running,
   infrastructure-provisioned container only enters the picture with the
   shared `mcp-stack` service in Phase 3/4 below — do not conflate the two.
2. **Discovery before mutation.** A shared MCP service, if built, is for
   read-only diagnostics. It does not keep production write credentials.
3. **Separate trust planes.** Agent worktrees, shared discovery, and mutation
   execution have different credentials, network paths, and lifecycles.
4. **Do not place a control plane on the Framework host.** It runs AI services
   and shares a Docker daemon with inference/UI workloads. It must not become a
   general credential or operations host.
5. **Do not place MCP in `mgmt_seg`.** That segment contains Authentik,
   step-ca, and observability. A service capable of querying several systems
   deserves its own blast-radius boundary.
6. **Production mutation remains operator-led.** It continues to require the
   preflight, `with-secrets-prod*`, and `TASK_APPROVAL` process defined in
   [production credentials](../reference/production-credentials.md) and
   `AGENTS.md`.

## Proposed architecture

```text
Clients (each with a distinct identity)
  ├─ Operator workstation — Claude Code / VS Code session (interactive)
  └─ Automated agent/workflow elsewhere — e.g. reviews snyk/sonar-scanner
     findings on a schedule and researches the CVEs they surface (service
     identity, no human present; likely lands in the ai-stack/n8n rebuild)
                                      │
                    authenticated, internal-only connection (mTLS)
                                      │
                 ┌────────────────────┴────────────────────┐
                 ▼                                          ▼
  automation_seg (VLAN 80, zero internet)      research_seg (VLAN 81, narrow internet)
  ┌───────────────────────────────────┐        ┌───────────────────────────────────┐
  │ mcp-discovery-stack                 │        │ mcp-utility-stack                   │
  │   Proxmox · MikroTik · Grafana ·    │        │   cve-mcp-server (CVE research,     │
  │   NetBox · VictoriaMetrics          │        │   scoped subset of its 21 sources)  │
  │ audit/request logs → central logging│        │ audit/request logs → central logging│
  └───────────────────────────────────┘        └───────────────────────────────────┘
             │                                                    │
    internal only (mgmt_seg/infra_seg)                 zone-wide named allowlist only
             │                                                    │
 Proxmox/MikroTik/Grafana/NetBox/VM APIs              NVD / OSV / vendor advisory APIs

Mutation request → disposable repo runner → existing approved script/wrapper
```

Each zone carries exactly one egress policy, applied to everything in it —
`automation_seg` never reaches the internet, full stop; `research_seg` never
reaches internal infra APIs, and reaches the internet only via its named
allowlist. No per-host exception is needed inside either zone (see Placement
and network model below for why this replaced an earlier single-subnet
design).

Local-only developer tools (GitHub MCP, Filesystem MCP — see Phase 1) still
run as local `stdio` per session on the workstation, unrelated to the shared
service above; they are omitted from this diagram for clarity.

### Placement and network model

The permanent shared service, if warranted, is two workloads split across
**two new network segments**, not one — see below for why one shared
segment was rejected in favor of this simpler split.

**LXC layout: two stacks, two zones, split by adapter class.** This repo's
existing convention (`terraform/lxc/stacks/*-stack/`) bundles multiple
docker-compose services into one LXC when they share a trust level — e.g.
`monitoring-stack` runs Grafana, VictoriaMetrics, Loki, and Promtail together
in `mgmt_seg`. The two adapter classes above do *not* share a trust level, so
each gets its own LXC *and* its own network segment:

- **`mcp-discovery-stack`**, in **`automation_seg`** — one LXC/docker-compose
  bundling all internal-discovery adapters: Proxmox, MikroTik, and now three
  named candidates confirmed 2026-07-26 — **Grafana** (`grafana/mcp-grafana`),
  **NetBox** (`netboxlabs/netbox-mcp-server`), **VictoriaMetrics**
  (`VictoriaMetrics/mcp-victoriametrics`) — see the dedicated review below the
  Candidate server assessment table. They share one posture: real internal
  infra credentials, zero internet egress ever — the same reasoning that
  already justifies bundling Grafana+VictoriaMetrics+Loki together in
  `monitoring-stack` today (note: that's the *application* Grafana/
  VictoriaMetrics being monitored; the MCP adapters here are separate
  processes that *talk to* those same applications, not the same containers).
  Five adapter containers in one LXC (plus the `mcp-proxy` bridge for
  Proxmox) is more than this repo's other stacks typically bundle — worth
  revisiting the one-LXC assumption if the container count keeps growing,
  but not a blocker for adding these three now.
- **`mcp-utility-stack`**, in **`research_seg`** — a separate LXC *and*
  separate zone for external-utility adapters (CVE research, and any future
  ones). Different posture: no infra credentials, but named internet egress
  to a public API, and it ingests untrusted internet content (CVE
  descriptions/advisories — a prompt-injection surface per the Security
  boundaries note in `local-ai-development.md`). Must not share a Docker
  daemon, or a broadcast domain, with `mcp-discovery-stack`'s credentials —
  same logic as keeping MCP off the Framework host (design decision 4).

One LXC per individual adapter would be over-fragmented relative to every
other stack in this repo; one LXC for both classes would put a compromised or
poisoned external-utility adapter on the same Docker daemon as live Proxmox/
MikroTik credentials, defeating design decision 3 ("separate trust planes").

**Why two zones, not one zone with two stacks (revised 2026-07-26):** the
first draft of this plan put both stacks in one `automation_seg`/VLAN 80
subnet and tried to give them different egress policy via per-source-IP
MikroTik firewall rules (deny internet from one IP, allow a narrow list from
the other). That works, but it's needless complexity: SDN zones in this
architecture aren't independently firewalled — the MikroTik router is the L3
gateway and firewall enforcement point *per zone/subnet*, and every other
zone in this repo expresses its policy that way, once, for the whole zone
(`mgmt_seg` = internal-only for everything in it, `infra_seg` = same,
`pentest_seg` = same). Cramming two stacks with genuinely different egress
needs into one zone would have made `automation_seg` the first zone in the
repo whose policy isn't uniform — auditing it would mean cross-referencing a
separate per-host exception list instead of just reading the zone's policy
block. **Giving each stack its own zone removes that entirely**: the zone
boundary *is* the trust boundary, exactly like everywhere else in this repo,
and adding a future third internal-discovery adapter needs zero new firewall
work — it just joins `automation_seg` and inherits the existing zone-wide
deny.

**Network allocation (resolved 2026-07-26, revised same day for the split
above)**: two new zones, VLANs **80** and **81**, both skipping VLAN 60
(already a documented-but-not-live reservation for a future `game_seg` —
`docs/plan/pve-migration-inventory.md`, `docs/application-migration/`) to
avoid a later collision. SDN zone/vnet short names both fit Proxmox's 8-
character cap (`pentest_seg`'s build hit this live — `tvpentest` was rejected
and renamed `tvpent`).

| Zone | VLAN | Subnet | Gateway | SDN name | Egress policy |
| --- | --- | --- | --- | --- | --- |
| `build_seg` | 10 | 192.168.10.0/24 | 192.168.10.1 | `tvsegc`/`tvnetc` | — |
| `mgmt_seg` | 20 | 192.168.20.0/24 | 192.168.20.1 | `tvmgmt` | internal-only |
| `edge_seg` | 30 | 192.168.30.0/24 | 192.168.30.1 | `tvedge` | — |
| `infra_seg` | 40 | 192.168.40.0/24 | 192.168.40.1 | `tvinfra` | internal-only |
| `ai_seg` (pve-framework only) | 50 | 192.168.50.0/24 | 192.168.50.1 | `tvai` | — |
| *(`game_seg`, reserved, not live)* | 60 | 192.168.60.0/24 | — | — | — |
| `pentest_seg` | 70 | 192.168.70.0/24 | 192.168.70.1 | `tvpent` | internal-only |
| **`automation_seg` (new)** | **80** | **192.168.80.0/24** | **192.168.80.1** | **`tvauto`** | **zero internet, always** |
| **`research_seg` (new)** | **81** | **192.168.81.0/24** | **192.168.81.1** | **`tvresrc`** | **no internal infra; narrow named internet allowlist only** |

**VMIDs (resolved)**: following the live `VLAN×1000 + sequence` convention
used by every zone from `mgmt_seg` onward — `mcp-discovery-stack` (in
`automation_seg`) = **80010**, `mcp-utility-stack` (now in its own
`research_seg`, so it's *that* zone's first stack, not `automation_seg`'s
second) = **81010**.

**IP addressing, `pve-test-vm` vs. `pve` (resolved)**: this repo already has a
working convention for exactly this. `.env.pve-test-vm`'s own comment states
it directly — "last octet +100 vs pve to avoid collision on shared VLANs" —
and `pentagi-stack` is the live example (canonical `.10` reserved for `pve`,
`pve-test-vm` uses `.110`). Since each stack is now its own zone's first
(and, for now, only) host, both get the same `.10`/`.110` shape a single-stack
zone like `pentest_seg`/`edge_seg` already uses — no `.11` needed:

| Stack | Zone | Canonical (`pve`, later) | `pve-test-vm` (now) |
| --- | --- | --- | --- |
| `mcp-discovery-stack` | `automation_seg` | 192.168.80.10 | **192.168.80.110** |
| `mcp-utility-stack` | `research_seg` | 192.168.81.10 | **192.168.81.110** |

Reserve both canonical rows now: declare `LAB_IP_MCP_DISCOVERY=192.168.80.10`
and `LAB_IP_MCP_UTILITY=192.168.81.10` in `.env` today even though the `pve`
deploy is Phase 4/later work, the same way `lab_ip_pentagi` was reserved in
`.env` from the start rather than added only at production-promotion time —
this stops anything else from claiming those addresses first.

**Egress enforcement, simplified by the two-zone split**: each zone gets one
MikroTik-level policy applied to the whole subnet, no per-host rule needed.
`automation_seg` (192.168.80.0/24): deny all internet egress, full stop.
`research_seg` (192.168.81.0/24): deny all internal-infra-API access (no
route to Proxmox/MikroTik/NetBox), allow internet egress only to the
CVE-research adapter's actual upstream API destinations — decided once
Phase 3 names the chosen server.

Required connectivity is deliberately asymmetric:

- Agent clients may reach the shared MCP endpoint only through authenticated,
  internal access. It is not a public Traefik application by default.
- Each MCP container may reach only its owned target API and required internal
  logging/identity endpoints. Do not give one shared `infra admin` credential
  to every adapter.
- Default-deny internet egress applies to every MCP container. Any exception
  must be a named, reviewed dependency.
- The service should expose streamable HTTP only if a real multi-client need is
  established. Local `stdio` remains the default for developer tools.

The existing `ai-stack` rebuild may host n8n-backed approved workflows later,
but n8n is not the universal direct MCP endpoint and does not replace the
dedicated discovery boundary.

### Three authority tiers

| Tier | Location and lifetime | Credentials and authority |
| --- | --- | --- |
| Local developer tools | Local `stdio`; one agent session | GitHub read token; one disposable worktree; no infrastructure secrets |
| Shared discovery | `mcp-discovery-stack` in `automation_seg` / `mcp-utility-stack` in `research_seg` | Per-service read-only accounts/tokens; typed inspection only |
| Mutation execution | Short-lived, task-specific repo runner | Existing `with-secrets` or `with-secrets-prod*`; operator approval for production |

The shared discovery tier must not offer arbitrary shell, arbitrary HTTP fetch,
raw vendor API, guest command execution, or router command tools. When an
upstream server cannot make that exclusion credible, use it only for a local
lab evaluation or replace it with a small repository-owned façade.

### Adapter classes: internal discovery vs. external utility

Every adapter — local or shared-tier — falls into one of two classes. This is
a different axis from the authority tier above: tier says *where it lives and
who can call it*; class says *what it's allowed to reach*, which drives its
egress and credential policy independently.

| Class | Internal infra credentials? | Internet egress? | Examples |
| --- | --- | --- | --- |
| Internal discovery | Yes — dedicated read-only account/token for that system | No — internal network only, default-deny | Proxmox, MikroTik, NetBox, metrics/logs |
| External utility | No | Yes — narrow, named allowlist per adapter | GitHub, CVE/vulnerability research |
| Local-only | No | No | Filesystem |

An external-utility adapter never holds internal credentials, so a
compromised or misbehaving instance can only reach its own allowlisted public
API and log what it asked — it cannot pivot into Proxmox or MikroTik. That
containment is why external-utility adapters (GitHub, and a future
CVE-research adapter) can start their **local** evaluation in Phase 1
alongside GitHub, even though their eventual **shared-service** hosting is
still gated behind Phase 3 like everything else.

## Candidate server assessment

| System | Class | Candidate | Role and decision | Required constraints |
| --- | --- | --- | --- | --- |
| GitHub | External utility | [github/github-mcp-server](https://github.com/github/github-mcp-server) | **First local evaluation.** Official server for repository, issue, PR, and check inspection. | Local `stdio`; repository-scoped read-only token; explicit tool/toolset allowlist; enable read-only mode. |
| Filesystem | Local-only | [modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) | **Optional local evaluation.** It may be redundant for agents with native workspace access. | Local `stdio`; exactly one disposable task worktree; never the home directory, shared repo root, credential directories, or production mounts. |
| Proxmox | Internal discovery | [GethosTheWalrus/proxmox-mcp](https://github.com/GethosTheWalrus/proxmox-mcp) | **Lab evaluation only.** Its Proxmox coverage is useful for discovery but its broad management surface is unsuitable as the trusted production layer. | Dedicated read-only API token; `pve-test-vm` first; TLS verification enabled; no `proxmox_api_raw`, guest execution, storage download/upload, or lifecycle tools. |
| MikroTik | Internal discovery | [AliKarami/MikroMCP](https://github.com/AliKarami/MikroMCP) | **Lab evaluation only.** It has valuable typed diagnostics, but its 100+ tools include configuration, SSH, and router-originated network actions. | Dedicated RouterOS read-only user; API-only where possible; prohibit writes, `run_command`, `fetch_url`, package updates, file upload, and RouterOS container tools. |
| MikroTik | Internal discovery | [jeff-nasseri/mikrotik-mcp](https://github.com/jeff-nasseri/mikrotik-mcp) | **Not selected.** Its SSH-first setup is too close to giving an agent a router shell. | Reconsider only after a separate security review and a concrete gap. |
| CVE / vulnerability research | External utility | [mukul975/cve-mcp-server](https://github.com/mukul975/cve-mcp-server) — **already cloned locally at `/home/steve/git/cve-mcp-server`** | **Selected candidate, 2026-07-26** (see the dedicated review below the Upstream-server connectivity findings table). Research CVEs surfaced by vulnerability scanners (this repo already runs `snyk`/`sonar-scanner`, per CLAUDE.md Security Scanning), usable from an interactive workstation session or an unattended scanner-review workflow. Evaluate locally in Phase 1 alongside GitHub MCP; its target is shared-service hosting per the operator's confirmed multi-client need (Phase 3 note above), not just local use. | Local `stdio` confirmed (verified by running it — opens no port); needs either the `mcp-proxy` bridge or a small native-HTTP patch for shared hosting, see review below; no internal infra credentials; egress allowlist restricted to the CVE/advisory-source subset only, not all 21 sources the server supports; only configure `NVD_API_KEY`/`GITHUB_TOKEN` — leave every threat-intel key (`SHODAN_KEY`, `VIRUSTOTAL_KEY`, `ABUSEIPDB_KEY`, `GREYNOISE_API_KEY`, `URLSCAN_KEY`, `CIRCL_PDNS_*`) unset. |
| Graylog | Internal discovery | **Native to Graylog itself** — no external repo. `org.graylog.mcp.config.McpConfiguration`, Graylog 7.0+ | **Validated live on `pve-test-vm`, 2026-07-26.** Not a separate MCP server at all — a built-in feature of the Graylog server this repo already runs (`graylog-stack`). Confirmed directly: `POST /api/mcp` `initialize` succeeds with a dedicated token, returns `401` with none. | No new container needed. Config flag (`enable_remote_access`) + Graylog's own RBAC (built-in `MCP Server Access` role) + a dedicated `service_account: true` user (`mcp-discovery-svc`) with only that role plus `Reader`, and view-only sharing on `Default Stream`. **Vendor marks this beta, not recommended for production** — validated on `pve-test-vm` only so far, `pve` promotion not yet done. See dedicated review below for the `mgmt_seg` placement question this raises (Graylog lives in `mgmt_seg`, not `automation_seg`). |
| Grafana | Internal discovery | [grafana/mcp-grafana](https://github.com/grafana/mcp-grafana) | **Selected candidate, 2026-07-26** (see dedicated review below). Official Grafana Labs server — by far the most popular MCP server found in this whole evaluation (3200+ stars). Large feature set: dashboards, alerting, Prometheus/Loki/ClickHouse/etc. querying, incidents, OnCall. | Dedicated Grafana Service Account token; native `stdio`/`sse`/`streamable-http` transport, no bridge needed; `--disable-write` flag strips all create/update/delete tools; `admin` and most non-core datasource categories (`clickhouse`, `cloudwatch`, `athena`, `snowflake`, `elasticsearch`, `quickwit`, `graphite`, `influxdb`, `examples`, `runpanelquery`) are already disabled by default — leave them that way. |
| NetBox | Internal discovery | [netboxlabs/netbox-mcp-server](https://github.com/netboxlabs/netbox-mcp-server) | **Selected candidate, 2026-07-26.** Official NetBox Labs server. Deliberately minimal — 3 tools total (`get_objects`, `get_object_by_id`, `get_changelogs`), read-only by design, explicitly "hard to misuse." The changelog tool doubles as an audit-trail query, matching this plan's investigation use case directly. | Dedicated read-only NetBox API token; native `stdio`/HTTP transport (`TRANSPORT=http` env var, `/mcp` endpoint, no bridge needed). |
| VictoriaMetrics | Internal discovery | [VictoriaMetrics/mcp-victoriametrics](https://github.com/VictoriaMetrics/mcp-victoriametrics) | **Selected candidate, 2026-07-26.** Official VictoriaMetrics server, matches this repo's actual metrics backend (`monitoring-stack`). Inherently read-only — VictoriaMetrics itself has no dashboard/alert-CRUD surface the way Grafana does, so there's no equivalent write-tool category to disable. | Dedicated bearer token; native `stdio`/`sse`/`http` transport (`MCP_SERVER_MODE` env var), no bridge needed; `export` (bulk data dump) is already in the disabled-by-default `MCP_DISABLED_TOOLS` list — leave it there. |
| Workflows | Orchestration (not an adapter) | n8n, during the later `ai-stack` rebuild | **Deferred**, but likely home for the "reviews scanner findings on a schedule" use case above — an unattended workflow calling the CVE-research adapter as just another MCP client, not a bespoke integration. | Each workflow must retain target guards, approval checks, logs, and post-change verification. |

### Upstream-server connectivity findings

The following findings came from a source review of the Proxmox MCP 1.3.0
source and MikroMCP 1.8.0 source during planning. They are not a substitute
for pinning and reviewing the exact artifact used at implementation time.

| Server | Normal path | Explicit external or outbound paths |
| --- | --- | --- |
| Proxmox MCP | Its normal `stdio` server connects to the configured Proxmox API; no telemetry or update check was found in its own source. | `TOOL_ROUTING` loads FastEmbed's `BAAI/bge-small-en-v1.5` model and must be treated as requiring an initial model retrieval unless pre-cached. API tools can cause Proxmox or a guest to fetch URLs, contact ACME, or execute arbitrary guest commands. |
| MikroMCP | Its normal `serve` path connects to configured RouterOS REST/SSH/SFTP targets; no telemetry was found in the service path. | `mikromcp doctor` checks npm for updates. `update` invokes npm. Tool calls can make the router fetch an arbitrary URL, contact package-update servers, run diagnostics, or execute a guarded SSH command. |

### Transport: bridging stdio-only servers for shared access

Local `stdio` is the only transport a single Claude Code session needs. A
*shared* service reachable by multiple remote clients needs a network
transport instead — and the two named `mcp-discovery-stack` candidates
differ here in a way that changes what actually has to be built:

- **Proxmox MCP is stdio-only, confirmed from source** (`src/proxmox_mcp/
  server.py`, `proxmox-mcp-server` 1.3.0): `main()` calls
  `mcp.run(transport="stdio")` unconditionally — there is no HTTP/SSE mode,
  no `--transport` flag, and its `docker-compose.yml` exposes no port. It
  physically cannot be reached over a network as shipped.
- **MikroMCP natively supports remote access** (confirmed from its README):
  "stdio for desktop clients, Streamable HTTP and legacy SSE for remote or
  service-style clients," plus its own built-in "HTTP bearer auth, bcrypt
  token hashes, RBAC, router/tool restrictions" and "structured logs, audit
  logs" — it can run directly in HTTP mode inside `mcp-discovery-stack` with
  no extra component.

So `mcp-discovery-stack`'s compose needs **three** containers, not two: the
`proxmox-mcp` stdio process, a **stdio-to-HTTP bridge** in front of it (real,
actively-maintained candidate: [sparfenyuk/mcp-proxy](https://github.com/sparfenyuk/mcp-proxy),
which does exactly stdio↔Streamable-HTTP bridging — 2.6k stars, updated
2026-07-25, pin its exact version/digest per the Phase 0 review step same as
any other adapter), and `mikromcp` running its own native HTTP mode
directly. `mcp-utility-stack`'s chosen CVE-research candidate needs the same
check before assuming it can be reached remotely as-is — see the dedicated
review immediately below, which found the same gap `proxmox-mcp` has.

### CVE-research candidate review: `mukul975/cve-mcp-server`

Already cloned locally at `/home/steve/git/cve-mcp-server` (`origin` =
`github.com/mukul975/cve-mcp-server`, 1095 stars, Apache-2.0/MIT dual license
files present — confirm which actually applies before shipping — Python,
last updated 2026-07-25). Findings below came from reading the actual
source in that clone, not the README's marketing claims alone.

- **Transport, confirmed stdio-only** (verified by running it, not just
  reading source): `src/cve_mcp/server.py`'s `main()` calls bare `mcp.run()`,
  which defaults to `transport="stdio"` in the official MCP Python SDK.
  Running `.venv/bin/cve-mcp` directly opened **zero listening TCP ports**
  and only produced stdout log lines — including an **eager, unprompted
  startup call** to fetch CISA's KEV catalog before any tool is invoked, so
  `cisa.gov` needs to be in the egress allowlist from container boot, not
  just "when a tool runs." Same shape as `proxmox-mcp`'s confirmed-stdio-only
  case — budget for the same `mcp-proxy` bridge pattern in `mcp-utility-stack`
  (one extra container) unless the patch below is applied instead.
- **A native-HTTP patch is small and well-supported, confirmed from the
  installed SDK — candidate for a separate future project, not this repo's
  near-term delivery**: `.venv/lib/python3.14/site-packages/mcp/server/
  fastmcp/server.py` (the SDK this server already depends on) already
  implements `run(transport: Literal["stdio", "sse", "streamable-http"])`
  plus `host`/`port`/`streamable_http_path` constructor args and auth
  middleware scaffolding (`RequireAuthMiddleware`) — none of this needs to
  be built, only wired up. The patch is genuinely small:
  `FastMCP("cve-mcp", lifespan=app_lifespan, host="0.0.0.0", port=8000)` and
  `mcp.run(transport="streamable-http")` in place of the current bare calls,
  plus exposing the port instead of `stdin_open: true` in the Dockerfile.
  Making the transport env-var-driven would let one image serve both a local
  `stdio` Claude Code session and the shared HTTP service. This would remove
  `mcp-proxy` from `mcp-utility-stack` entirely (one container instead of
  two) — at the cost of maintaining a fork, unless upstreamed as a PR (the
  feature already exists unused in their own dependency, so it may well be
  accepted). **Operator intends to evaluate this as a separate project**
  (possibly its own maintained fork, outside this repo) rather than as part
  of the `mcp-stack` delivery phases here — if it ships, `mcp-utility-stack`
  still goes through the same containment model in this plan (own zone, own
  credentials, egress allowlist, audit logging) regardless of which upstream
  shape it lands on.
- **The local clone already has real, uncommitted work toward exactly this
  direction — not repo corruption, confirmed 2026-07-26**: `git status` in
  `/home/steve/git/cve-mcp-server` shows the checkout is 5 commits behind
  `origin/main` (local HEAD `809953e`, 2026-05-13; origin at `d666bac`,
  2026-06-22) with uncommitted modifications to `server.py`,
  `poc_checker.py`, `exploit_intel.py`, `report_generator.py`,
  `tests/test_tools.py`, `README.md`, `.env.example`, and `pyproject.toml`,
  plus two untracked files. This is deliberate prior work (file timestamps
  2026-05-19/20), not accidental changes:
  - A new `triage_cves_for_openwebui` MCP tool in `server.py` — a
    single-call CVE triage report "optimized for Open WebUI" (this repo's
    own `ai-services-stack` already runs OpenWebUI, per
    `docs/framework-ubuntu/local-ai-development.md`), explicitly still
    calling bare `mcp.run()` at the bottom — this WIP never touched the
    transport question above.
  - `src/cve_mcp/local_wrapper.py` (untracked, 186 lines) plus a
    `cve-local-wrapper` entry in `pyproject.toml`'s `[project.scripts]` — a
    CLI that runs core tools directly and summarizes with a **local Ollama
    model**, not Anthropic. `.env.example` gained matching
    `OLLAMA_BASE_URL`/`OLLAMA_MODEL` vars.
  - Broadened/deduped GitHub PoC-search queries in `poc_checker.py`/
    `exploit_intel.py` (more query variants, hint-word matching, dedup by
    repo ID) — a quality improvement to the existing PoC-search tool
    reviewed above, not a new capability.
  - `scripts/run-claude-mcp.sh` (untracked) — a launcher that sources
    `/srv/docker/ai/.env` and execs `cve_mcp.server` directly, implying an
    existing local AI Docker setup at `/srv/docker/ai` this was once wired
    into, separate from anything tracked in this repo.
  - None of this is committed anywhere (no branch, no stash) — it only
    exists in this working tree. Decide explicitly whether to commit,
    stash, or discard it before treating the clone as a clean base for
    either the `mcp-proxy`-bridge path or the native-HTTP-patch path above;
    this plan does not do that for you.
- **Breadth mismatch with the "narrow, named allowlist" principle**: the
  README advertises "27 tools, 21 data sources" — the source's `.env.example`
  confirms 21 real upstream integrations, not marketing rounding. Only about
  half fit the stated use case (CVE detail lookup for scanner findings): NVD,
  EPSS, CISA KEV, OSV.dev, GitHub Advisories, MITRE ATT&CK, Exploit-DB,
  Nuclei Templates, MSRC, Red Hat Security, Ubuntu Security. The rest is a
  general IP/malware/threat-intel OSINT toolkit — AbuseIPDB, GreyNoise,
  Shodan, VirusTotal, MalwareBazaar, ThreatFox, Ransomwhere, URLScan.io,
  CIRCL PDNS, GitHub Code Search — a different use case (network/IOC
  investigation) needing its own paid/rate-limited API keys. The source has
  no visible per-tool enable/disable flag, so **the firewall allowlist is
  the actual enforcement point**, not app config: only allowlist the
  CVE/advisory-cluster destinations in `research_seg`'s MikroTik policy, and
  deliberately leave `SHODAN_KEY`/`VIRUSTOTAL_KEY`/`ABUSEIPDB_KEY`/
  `GREYNOISE_API_KEY`/`URLSCAN_KEY`/`CIRCL_PDNS_*` unset — those tools then
  fail closed at both the app layer (no key) and the network layer (no
  route), reinforcing the same boundary two ways.
- **No arbitrary-fetch or code-execution tool found** — a real concern given
  the acceptance checklist requires ruling this out, so it was checked
  directly: `poc_checker.py`'s `search_poc_existence` only *searches*
  GitHub/Exploit-DB/Nuclei-templates for public PoC references (confidence
  score + links) — it never downloads or runs exploit code.
  `dependency_scan.py`'s `scan_dependencies_bulk` takes a caller-supplied
  `packages: list[dict]` argument (queries OSV.dev's batch API) — it does
  **not** read the local filesystem, despite the "dependency scan" name
  suggesting otherwise; worth double-checking this understanding stands once
  Phase 2 actually exercises the tool. `scan_repo_secrets` searches GitHub's
  public code-search API for potential leaked secrets matching a term — also
  not a local filesystem operation, but it's a *credential-exposure* search,
  not CVE research; **out of scope for the stated use case even though it's
  technically safe** — worth excluding from whatever tool allowlist Phase 2
  settles on, same reasoning as excluding the threat-intel cluster above.
- **Audit logging writes to a local file only, not stdout — a real gap
  against the repo's `syslog`-log-driver convention**: `audit.py` uses
  Python's `RotatingFileHandler` (`AUDIT_LOG_PATH`, defaults to
  `~/.cve-mcp/audit.log`, rotates at 50MB/5 backups) with no `StreamHandler`
  alongside it. Docker's `log-driver: syslog` (the mechanism this plan
  already settled on — see Audit requirements above) only captures
  stdout/stderr, so it will **not** pick this file up. Needs one of: bind-
  mount the audit log out of the container and have a separate log-shipping
  step tail it, or confirm whether `AUDIT_LOG_PATH` can be pointed at
  `/dev/stdout` (some Python logging setups tolerate this, some don't —
  test, don't assume), before relying on it for the Audit requirements above.
- **Needs persistent storage, unlike a purely stateless adapter**: `config.py`
  defaults `CACHE_DB_PATH` to a local SQLite file — this container needs a
  real volume/bind mount in its `stack.yaml`, not an ephemeral-only
  container, or the cache (and the audit log, per the point above) is lost
  on every restart.
- **A separate bundled script, not part of the MCP server itself**:
  `cve-local-wrapper` (`local_wrapper.py`) talks to a local Ollama endpoint
  for "deterministic summary generation." This repo already has its own
  local-AI stack (`docs/framework-ubuntu/`) — don't deploy this wrapper as
  part of `mcp-utility-stack`; it's a separate CLI tool bundled in the same
  repo, not a dependency of the MCP server tool surface.

Consequences:

- Do not enable Proxmox `TOOL_ROUTING` in the first evaluation. If it is ever
  needed, pre-cache and pin the embedding model in a controlled build, then
  prove the runtime container has no general internet egress.
- Do not use MikroMCP `doctor` as a health check and do not allow it to update
  itself from a running service.
- Installation and image/package retrieval are separate supply-chain events.
  Pin versions and digests, generate or record an SBOM, and test upgrades in a
  disposable environment before promotion.

### Internal-discovery candidates: Graylog, Grafana, NetBox, VictoriaMetrics

Researched 2026-07-26, in response to "check our other infra stack
components for well-supported MCP servers." All four are official/
vendor-maintained (confirmed via GitHub API: verified `Organization` account
type, not archived, license present, updated within days of this review) —
a different trust starting point than the third-party Proxmox/MikroTik
wrappers above.

**Graylog — already validated live, not just researched.** Covered in the
candidate table above; the rest of this entry is the one open design
question it raises. Graylog runs in `mgmt_seg`, not `automation_seg` —
design decision 5 explicitly keeps MCP infrastructure out of `mgmt_seg`
("that segment contains Authentik, step-ca, and observability... deserves
its own blast-radius boundary"). But there's no separate adapter *process*
here to relocate into `automation_seg` — the MCP endpoint is Graylog itself.
So the real decision is network policy, not placement: does a remote MCP
client reach `192.168.20.x:9000/api/mcp` directly across a `mgmt_seg`↔
`automation_seg`/client firewall hole (narrow, but real inbound access into
`mgmt_seg`), or does something in `automation_seg` proxy the connection so
`mgmt_seg` itself never accepts a connection from outside its own zone
(consistent with every other `mgmt_seg` boundary rule, at the cost of an
extra hop)? Not yet decided — flagged as a new open decision below.

**Grafana** (`grafana/mcp-grafana`): the most maturely-engineered server
reviewed in this whole plan. Concrete features worth relying on directly
rather than re-implementing at the network layer:
- `--disable-write` strips every create/update/delete tool (dashboards,
  alert rules) in one flag — the cleanest "make this read-only" mechanism
  found across every candidate so far, better than Proxmox/MikroTik/CVE-
  research which all needed credential-level or firewall-level containment
  as the *only* defense.
- Tool categories are opt-in via `--enabled-tools`: `admin`, `clickhouse`,
  `cloudwatch`, `athena`, `snowflake`, `elasticsearch`, `quickwit`,
  `graphite`, `influxdb`, `examples`, and `runpanelquery` are all disabled
  unless explicitly added — matches this plan's default-deny philosophy
  natively, no repository-owned façade needed.
- Native `stdio`/`sse`/`streamable-http` transport, with `Host`/`Origin`
  validation enforced on every HTTP route (`/sse`, `/mcp`, `/healthz`,
  `/metrics`) specifically to block DNS-rebinding attacks — a real security
  feature, not just a transport option.
- Auth via a dedicated Grafana **Service Account** token — Grafana's own
  RBAC applies underneath the tool layer, same defense-in-depth pattern as
  every other adapter's credential requirement in this plan.
- Still worth checking in Phase 2: whether `--disable-write` fully covers
  the Incidents and OnCall write paths (create/update incidents, manage
  schedules) the same way it covers dashboards/alerting, or whether those
  need their own explicit `--disable-*` flags too.

**NetBox** (`netboxlabs/netbox-mcp-server`): the simplest and safest
candidate found. Three tools only (`get_objects`, `get_object_by_id`,
`get_changelogs`), read-only by design with no write path to remove in the
first place, and the project's own stated design goal is "hard to misuse."
`get_changelogs` retrieves NetBox's audit trail (who changed what, when) —
a direct match for this plan's "faster investigation, better evidence"
purpose. Native `stdio`/HTTP transport (`TRANSPORT=http`, `/mcp` endpoint).
Auth via a dedicated read-only NetBox API token.

**VictoriaMetrics** (`VictoriaMetrics/mcp-victoriametrics`): matches this
repo's actual metrics backend directly (`monitoring-stack` runs
VictoriaMetrics, not raw Prometheus). Structurally read-only — VictoriaMetrics
itself has no dashboard/alert-config API surface the way Grafana does, so
there's nothing equivalent to `--disable-write` to reach for; the tool set
is inherently query/exploration only (PromQL queries, label/series
discovery, cardinality analysis, alerting-rule *inspection* not mutation).
`export` (bulk data dump — a potential large-response/exfiltration-shaped
tool, not a mutation risk) is already in the disabled-by-default
`MCP_DISABLED_TOOLS` list. Native `stdio`/`sse`/`http` transport via
`MCP_SERVER_MODE`. Auth via `VM_INSTANCE_BEARER_TOKEN`.

**Net effect on `mcp-discovery-stack`'s container count**: adding Grafana,
NetBox, and VictoriaMetrics brings the internal-discovery set to five
adapter containers (Proxmox, MikroTik, Grafana, NetBox, VictoriaMetrics)
plus the `mcp-proxy` bridge Proxmox needs — six containers in one LXC,
Graylog aside (native, no container). That's a larger single-LXC bundle
than any existing stack in this repo. Not a blocker for Phase 2 evaluation,
but worth re-examining at Phase 3/4 whether `mcp-discovery-stack` should
stay one LXC or split further once the real container count and resource
footprint are known from actually running them.

## Credentials, authentication, and logging

### Credentials

- Create distinct read-only identities for each integration. They must not
  reuse Terraform tokens, personal accounts, or existing operator secrets.
- **A real trap to avoid, confirmed 2026-07-26**: this repo already has
  generic read-only credentials for both target systems —
  `MIKROTIK_READONLY_USER`/`MIKROTIK_READONLY_PASSWORD` (`api-ro`) in
  `terraform/secrets.common.enc.yaml`, and a `PROXMOX_READONLY_TOKEN_ID`/
  `PROXMOX_READONLY_TOKEN_SECRET` pair used for workstation API checks per
  CLAUDE.md's Execution Guardrails. **Do not point either MCP adapter at
  these.** They're already read-only, which makes reusing them tempting, but
  doing so would merge the MCP audit trail with whatever else already
  depends on them and couple their revocation together — exactly what the
  "distinct identities" rule above exists to prevent. Create separate,
  newly-named credentials for the MCP adapters specifically (e.g. a new
  Proxmox API token, a new RouterOS user distinct from `api-ro`).
- For Proxmox, use a privilege-separated API token with the minimum read ACLs.
  Explicitly set certificate verification on; the reviewed third-party server
  defaults it off. **File placement**: `terraform/secrets.pve-test-vm.enc.yaml`
  (already exists, mirrors `secrets.pve.enc.yaml`/`secrets.pve-framework.enc.yaml`)
  — per CLAUDE.md's secrets split, a Proxmox API token is "structurally tied
  to that node's own Proxmox API identity," so it's per-node, not common.
- For MikroTik, create a dedicated read-only RouterOS user, distinct from the
  existing `api-ro`. Do not grant SSH, FTP, `sniff`, policy-change, package,
  or user-management permissions merely to satisfy optional MCP tools.
  **File placement**: `terraform/secrets.common.enc.yaml` — MikroTik is one
  shared router serving every zone/node in the lab, so its credential isn't
  tied to a single Proxmox node's identity the way the Proxmox token is.
- Store any shared-service secret through the repository's SOPS pattern and
  inject it at runtime. Never add it to tracked MCP client configuration,
  prompts, images, or worktrees.

### Client authentication

- Local `stdio` servers inherit the local agent session boundary and do not
  listen on a network port.
- A future remote endpoint needs authenticated internal access, a constrained
  client allowlist, and separate identities/roles for each caller. TLS is
  mandatory.
- Two caller shapes need distinct identity handling, matching the confirmed
  multi-client need (Phase 3 note above):
  - **Interactive** — an operator's Claude Code/VS Code session on the
    workstation. Reuse `step-ca-stack` (already deployed, `mgmt_seg`) to
    issue a short-lived per-operator client certificate for mTLS rather than
    inventing a new credential type. Authentik (already SSO for other
    stacks) is the fallback candidate if a browser-mediated token flow is
    preferred instead of a client cert.
  - **Automated/service** — an unattended workflow or CI job calling with no
    human present (e.g. the scanner-findings-review use case above). Needs
    its own step-ca-issued machine identity, scoped only to the adapters
    that workflow actually needs (e.g. CVE research, not Proxmox/MikroTik
    discovery). Never reuse an interactive operator's credential for a
    service caller, and never give a service identity broader adapter access
    than its one named job requires.
  - Reusing `step-ca`/Authentik for this means `mcp-stack` does not become a
    third identity system in the homelab — consistent with design decision 5
    (don't duplicate `mgmt_seg` responsibilities, just consume them).
- **Honesty check on the mTLS plan, 2026-07-26**: every existing use of
  `step-ca` in this repo (`proxy-stack`, `technitium-stack`, `monitoring-
  stack`, `dns-stack`) is as an ACME **server-certificate** issuer for
  Traefik-fronted HTTPS — there is no existing precedent anywhere in this
  repo for step-ca issuing **client** certificates for mTLS. This is
  genuinely new work for Phase 3 to design (likely a `step ca certificate`
  call against a JWK/X5C provisioner, plus something in front of each stack
  that actually verifies the client cert — none of `proxmox-mcp`, the
  `mcp-proxy` bridge, or MikroMCP do mTLS verification themselves). Weigh
  this against MikroMCP's own built-in HTTP bearer-token auth, which needs
  no new PKI work for that one adapter specifically — Phase 3 should decide
  whether to build client-cert mTLS uniformly across both stacks or accept a
  mixed model (mTLS at a front proxy for `proxmox-mcp`/the bridge, native
  bearer tokens for `mikromcp`) rather than assume the uniform answer is
  free just because `step-ca` already exists for a different purpose.
- Do not expose a general MCP endpoint through a public route simply because
  Traefik can proxy it.

### Audit requirements

Capture the MCP server name/version, caller identity, target identity, tool,
parameters redacted for secrets, response status, correlation ID, and the
associated repository task. Forward logs to the existing central logging
system. For a mutation runner, also capture the invoked repository command,
approval identifier, expected diff, and verification result.

**Mechanism, resolved 2026-07-26**: "the existing central logging system"
already has a concrete, near-universal answer in this repo — nearly every
Docker-based stack's playbook (`monitoring`, `authentik`, `harbor`,
`portainer`, `technitium`, `netbox`, `proxy`, `graylog` itself, `ci-runner`,
`portainer-agent`) sets `/etc/docker/daemon.json`'s `"log-driver": "syslog"`,
shipping every container's stdout/stderr to Graylog (which has
`rsyslog_inbound_enabled`). Use the same convention for both new stacks —
this is a solved problem, not a new one, as long as each adapter's own logs
already carry the required fields. `MikroMCP` explicitly advertises
"structured logs, audit logs" and correlation IDs as a built-in feature,
which lines up closely with what's required above. `proxmox-mcp`'s own
logging format is unconfirmed — check it during the Phase 2 lab evaluation,
and if it doesn't already emit structured, correlation-ID-bearing log lines,
budget for a thin wrapper around it (the `mcp-proxy` bridge is one candidate
place to add that, since every call already passes through it). Note
`pentagi-stack` deliberately used `"log-driver": "json-file"` instead of the
usual `syslog` — check its stated reason before assuming `syslog` is
automatically correct here too, though it's the right default to start from.

## Delivery plan

### Phase 0 — admission criteria and local safety baseline

No infrastructure changes.

1. Select an MCP-capable local client and test it with the existing local model
   endpoints.
2. Create a disposable agent worktree and a non-production MCP client config.
3. Review and pin exact upstream versions, source commit, image/package digest,
   license, dependencies, supported transport, and outbound network behavior.
4. Confirm that no current AI endpoint, personal browser profile, SSH agent,
   or credential directory is implicitly mounted into the agent environment.

Pass criteria: the client starts local MCP servers, discovers tools, and shows
the expected tool descriptions without access to homelab credentials.

### Phase 1 — GitHub and filesystem local tools

0. **Reference client: Claude Code**, since it is the operator's actual daily
   driver (used inside VS Code) and has native MCP support (`claude mcp add`,
   `.mcp.json`) — no separate agent host (Cline/Goose/OpenCode) or IDE
   extension is needed to reach the servers below. Register every server at
   `-s local` scope (personal `~/.claude.json`, this checkout only). Never use
   `-s project` (tracked `.mcp.json`) for a server that takes credentials —
   that would commit the token/secret to git. This resolves the open
   "reference host" decision previously listed at the end of this document.
1. Configure GitHub MCP as read-only with a repository-scoped token and a
   minimal tool allowlist.
2. If needed, configure Filesystem MCP for exactly one disposable worktree.
3. Test repository inspection, issue/PR/check retrieval, file search, and
   refusal outside the allowed worktree.

Pass criteria: a local agent can investigate a change without creating GitHub
objects or reading outside its assigned tree.

### Phase 2 — Proxmox and MikroTik discovery lab evaluation

1. Use `pve-test-vm` and a dedicated Proxmox read-only token.
2. Use a dedicated MikroTik read-only account and an egress policy allowing
   only the router's required API endpoint.
3. Start each candidate locally, list tools, and exercise only the agreed
   discovery set: nodes/guests/storage/network for Proxmox; interfaces,
   addresses, routes, firewall inspection, logs, and topology for MikroTik.
4. Prove denied writes, raw API, guest execution, router command, outbound
   fetch/update, and out-of-scope filesystem access fail as expected.
5. Capture packet/firewall evidence that normal runtime traffic stays within
   the declared target allowlist.

Pass criteria: structured discovery improves over the existing scripts without
new authority, unexplained egress, or secret exposure.

### Phase 3 — shared service design review

Only begin if Phase 2 passes and a real multi-client need exists.

**Multi-client need confirmed by operator, 2026-07-26**: the requirement is
multiple machines/agent hosts reaching one always-on service, not just
config reuse across local Claude Code sessions on one workstation (the
latter would need only `claude mcp add -s user`, no new infrastructure). The
remaining gate before starting this phase for real is Phase 2 passing —
i.e. the read-only discovery adapters proving reliable and useful on
`pve-test-vm` — not whether the demand exists.

1. Decide the exact hosting target, `automation_seg`/`research_seg`
   subnet/VLAN, service identity, remote transport, authentication model
   (mTLS via `step-ca`, per Client authentication above), certificate
   issuer, and central logging integration.
2. Define an adapter-by-adapter egress policy and a per-adapter secret model,
   including the external-utility class's named allowlists (e.g. the
   CVE-research adapter's actual upstream API once a server is chosen).
3. Decide whether each candidate is safely configurable or must be replaced by
   a repository-owned narrow adapter.
4. Produce a production mutation runbook that delegates to the existing
   wrappers rather than embedding write credentials in the MCP service.

Pass criteria: the network and secret design is specific enough for a
Terraform/Ansible implementation plan and production preflight.

### Phase 4 — build and validate `mcp-stack`

This is a future infrastructure change, not authorized by this plan alone.
Build order mirrors the real `pentest_seg`/`pentagi-stack` build exactly —
same shape, same file list, same order — since it's the closest live
precedent for "add a new zone + stack(s) on `pve-test-vm` first." Do **not**
use `terraform/lxc/scaffold-stack.sh`: the most recent real stack build
(`pentagi-stack`, 2026-07-26) bypassed it entirely (`docs/pentagi-stack/
plan.md` §0.3 — two of its five generation steps just write content verbatim,
and its own exemplar stack no longer exists in the tree) and hand-authored
files by copying `graylog-stack`'s shape instead. Do the same here.

1. **MikroTik VLAN 80 and VLAN 81 trunk tagging** — manual RouterOS CLI over
   SSH, same as done for `ai_seg`/`pentest_seg`. Verify each with
   `ping 192.168.80.1` and `ping 192.168.81.1` from the workstation — a
   router self-ping is not a reliable check on RouterOS.
2. `terraform/lxc/network/pve-test-vm.yaml` — add **two** zone blocks:
   `automation_seg`'s `attachments`/`zones`/`policies`, following
   `infra_seg`'s shape (internal-only, no edge/Traefik exposure), and
   `research_seg`'s, with a policy permitting egress only to the
   CVE-research adapter's named destinations once Phase 3 picks a server.
3. `terraform/lxc/variables.tf` — add one variable set per zone:
   `lab_ip_mcp_discovery`, `lab_gw_automation`, `lab_subnet_automation_cidr`
   for `automation_seg`; `lab_ip_mcp_utility`, `lab_gw_research`,
   `lab_subnet_research_cidr` for `research_seg` (all `type = string`,
   `default = ""`). Not automatic — confirmed each new zone needs its own
   hand-added variables, from the `pentest_seg` build.
4. `terraform/lxc/main.tf` — add the same six keys to
   `locals.stack_template_vars` so `templatefile()` can actually substitute
   them into each `stack.yaml`.
5. `./with-secrets terragrunt plan` against `pve-test-vm` (confirm targeting
   per the Execution Guardrails in CLAUDE.md first) — expect additive-only
   (`N to add, 0 to change, 0 to destroy`), matching CLAUDE.md's Terraform/
   SDN "additive only" validation tier, before applying anything.
6. Hand-author stack files for both stacks, following `graylog-stack`'s
   layout:
   - `terraform/lxc/stacks/mcp-discovery-stack/stack.yaml` — no `edge.yaml`;
     it should never get edge/Traefik exposure per the egress rules above.
   - `terraform/lxc/stacks/mcp-utility-stack/stack.yaml` — same, no edge
     exposure (its network path out is the narrow MikroTik allowlist above,
     not a Traefik route).
   - `STACK_CONTRACT.md` for each, covering every section
     `STACK_CONTRACT.template.md` requires (`Purpose`, `Network`, `Inputs`,
     `Provides`, `Dependencies` — required even if "None.", `Persistent
     State`, `What May Depend On This Stack`, `What Must Not Be Edited
     Casually`, `Playbook`, `Implementation Files`).
   - `deployment_tier: platform` for both — matches the documented
     `platform`/`apps` contract in `PLATFORM_CONTRACT.md`. Don't repeat
     `pentagi-stack`'s drift (`deployment_tier: ai`, outside the documented
     set, currently undetected only because it's excluded from the
     validator's stack list — see step 10).
   - Docker Compose templated inline via Jinja inside each Ansible playbook
     (not a static `docker-compose.yml`), same approach `pentagi-stack` uses
     — keeps credential/env substitution in one reviewable place.
     **`mcp-discovery-stack` needs three containers, not two** (see
     Transport section above): `proxmox-mcp` (stdio, no published port),
     the `mcp-proxy` stdio-to-HTTP bridge in front of it (this is what
     actually gets a network port), and `mikromcp` running its own native
     HTTP mode directly (no bridge needed). `mcp-utility-stack` stays a
     single container until Phase 3 confirms whether its chosen server
     needs the same bridging treatment.
7. `terraform/lxc/environments/pve-test-vm/mcp-discovery-stack/terragrunt.hcl`
   and the equivalent for `mcp-utility-stack` — standard ~13-line boilerplate
   (`include "root"` + `stack_name`/`stack_yaml_path`/`generated_dir`
   inputs); copy any existing stack's file and rename.
8. `terraform/lxc/ansible/playbooks/deploy-mcp-discovery-stack.yml` and
   `deploy-mcp-utility-stack.yml` — full deploy logic. Each must enforce this
   plan's Required connectivity rules directly (default-deny egress per
   adapter, no arbitrary-shell/fetch tools enabled, audit logging wired to
   central logs) — not just describe them in this document. Concretely:
   - `/etc/docker/daemon.json` → `"log-driver": "syslog"`, matching the
     convention nearly every other stack's playbook already sets (see Audit
     requirements above) — copy the exact task block from, e.g.,
     `deploy-monitoring-stack.yml` or `deploy-technitium-stack.yml`.
   - Read the new dedicated Proxmox token from
     `terraform/secrets.pve-test-vm.enc.yaml` and the new dedicated
     RouterOS user from `terraform/secrets.common.enc.yaml` (both distinct
     from the existing `PROXMOX_READONLY_TOKEN_*`/`MIKROTIK_READONLY_*`
     credentials — see Credentials above) via `lookup('env', ...)`, same
     pattern every other playbook already uses for secret injection.
9. `./with-secrets terragrunt apply` on `pve-test-vm`; confirm the resource
   count matches expectations (LXC + SDN zone/vnet/subnet + ansible inventory
   entry per stack — `pentest_seg`'s equivalent apply added 5 resources for
   one zone + one stack; expect roughly double here since this is two zones
   and two stacks, not one zone with two stacks).
10. Add `mcp-discovery-stack` and `mcp-utility-stack` to
    `validate-stack-metadata.py`'s hardcoded `ACTIVE_STACKS` tuple. This
    validator silently skips any stack not in that list — confirmed neither
    `pentagi-stack` nor any `net-*` stack is checked today. Don't let the new
    stacks fall into that same silent gap.
11. `.env.pve-test-vm` — add `LAB_IP_MCP_DISCOVERY=192.168.80.110` and
    `LAB_IP_MCP_UTILITY=192.168.81.110` (plus `LAB_GW_AUTOMATION`/
    `LAB_SUBNET_AUTOMATION_CIDR` and `LAB_GW_RESEARCH`/
    `LAB_SUBNET_RESEARCH_CIDR`). `.env` — reserve the canonical
    `LAB_IP_MCP_DISCOVERY=192.168.80.10` / `LAB_IP_MCP_UTILITY=192.168.81.10`
    now, ahead of the eventual `pve` promotion.
12. Zone-level MikroTik firewall policy per the Egress enforcement note
    above: one rule set for the whole `automation_seg` subnet (deny all
    internet), one for the whole `research_seg` subnet (deny internal-infra
    routes, allow only the CVE-research adapter's actual upstream API
    destinations once Phase 3 names the chosen server) — no per-host rule
    needed, unlike the rejected single-zone design.
13. Deploy only read-only adapters with default-deny egress and central logs
    wired up (per the Audit requirements section above).
14. Run failure, revocation, egress-denial, certificate, restart, and upgrade
    tests before promotion — including a deliberate attempt to reach the
    internet from `mcp-discovery-stack`'s IP to prove the deny rule holds,
    and a deliberate attempt to reach Proxmox/MikroTik APIs from
    `mcp-utility-stack`'s IP to prove it can't (no route/no credential
    either way).

**Known gotchas already hit once on this repo — don't rediscover them:**
- SDN zone/vnet names cap at 8 characters (`tvauto` fits by design).
- Any literal `${...}` inside a `.yaml` consumed by `templatefile()` —
  including inside comments or `policies:` `description:` prose strings —
  must be escaped as `$${...}`, or it silently breaks `terragrunt plan`
  repo-wide on a later, unrelated run, not just this stack's own file.
- Expect environment-specific bugs to resurface at the eventual `pve`
  promotion even after a clean `pve-test-vm` pass (`pentagi-stack` hit three:
  an apt-cacher-ng/node_exporter port conflict, a per-node MikroTik
  Traefik-IP rule, and a DNS-backend mismatch). Re-verify each Phase 4 pass
  criterion on `pve` specifically at promotion time — don't assume a
  `pve-test-vm` pass generalizes automatically.

Pass criteria: the service can be recovered, audited, and disabled without
affecting inference, identity, edge routing, or production mutation controls.

### Phase 5 — bounded mutations, if ever needed

Do not start with Terraform apply, router/firewall changes, guest lifecycle
control, or production service deployment.

Each proposed mutation must be a named, typed workflow backed by a repository
script/runbook, with a target guard, dry run or plan, explicit operator
approval, minimal credentials, verification, and rollback path. The mutation
runner is ephemeral and must not be promoted into a broad persistent MCP tool.

## Acceptance checklist

Before accepting any MCP integration, verify all of the following:

- [ ] Exact server/version/digest is pinned and source/dependency review is
      recorded in local `artifacts/`.
- [ ] Tool list contains only the intended authority or unwanted tools are
      independently denied by credential and network policy.
- [ ] Runtime egress is default-deny and observed traffic matches the declared
      allowlist.
- [ ] Credentials are dedicated, least-privileged, revocable, and absent from
      configuration files, prompts, logs, and client-visible responses.
- [ ] TLS verification is enabled for all vendor APIs and remote MCP transport.
- [ ] The server has a health, restart, disable, and upgrade procedure.
- [ ] Central logs contain the required audit fields without leaking secrets.
- [ ] The test includes prompt-injection-resistant operating guidance and
      proves dangerous/out-of-scope tools are unavailable by default.
- [ ] Any production mutation still routes through `with-secrets-prod*` and a
      task-specific explicit approval.

## Open decisions

- ~~Which local client becomes the reference host for the first evaluation?~~
  Resolved: Claude Code, `-s local` scope (see Phase 1, step 0).
- ~~Does Phase 2 demonstrate enough value to justify a shared remote
  service, rather than continuing with local `stdio` tools?~~ Partially
  resolved: the operator wants a shared remote service regardless (multiple
  machines/agent hosts, not just multiple sessions on one workstation) — see
  Phase 3 note above. What's still open is whether Phase 2's discovery
  adapters are good enough to be the thing that gets shared, or need
  replacing with narrower repository-owned adapters first (see the next
  bullet).
- ~~What is the final name and network allocation for `automation_seg`?~~
  Resolved, then revised same day: **two** zones, not one —
  `automation_seg` (VLAN 80, `192.168.80.0/24`, gw `192.168.80.1`, `tvauto`,
  zero internet) for `mcp-discovery-stack`, and `research_seg` (VLAN 81,
  `192.168.81.0/24`, gw `192.168.81.1`, `tvresrc`, narrow named internet
  allowlist) for `mcp-utility-stack` — see Placement and network model above
  for why a single shared zone was rejected.
- ~~Should the shared discovery service use upstream servers behind a
  restrictive proxy, or small repository-owned adapters that expose only the
  allowed tools?~~ Partially forced, not just stylistic: `proxmox-mcp` is
  confirmed stdio-only from source, so it needs a bridge (`mcp-proxy`) in
  front of it regardless of preference — see Transport section above. Still
  open: whether that bridge (or a small repo-owned wrapper behind it) should
  also enforce the tool allowlist, or whether relying on the upstream
  server's own config (env vars, no `proxmox_api_raw` calls made) is
  sufficient on its own.
- What authentication mechanism is appropriate for private remote MCP
  clients without turning the endpoint into another public application?
  Narrowed, not resolved: candidates are step-ca-issued client-cert mTLS
  (new PKI work, no existing precedent in this repo) or MikroMCP's own
  built-in HTTP bearer auth for that adapter specifically (see Client
  authentication's "Honesty check" above) — Phase 3 must pick one model,
  uniform or mixed.
- Which central log retention/redaction policy is sufficient for MCP tool
  parameters and outputs? (Mechanism is resolved — `syslog` log-driver to
  Graylog, per Audit requirements above — retention/redaction policy within
  Graylog is still open.)
- ~~Which specific CVE/vulnerability-research MCP server to use~~ Selected:
  `mukul975/cve-mcp-server`, already cloned locally — see the dedicated
  review under Transport above. Still open from that review: `mcp-proxy`
  bridge vs. the small native-HTTP patch (operator is considering the patch
  as a separate project, possibly its own fork — see review); what to do
  with the local clone's existing uncommitted work before treating it as a
  clean base either way; can `AUDIT_LOG_PATH` point at `/dev/stdout` for the
  `syslog` log-driver convention to pick it up, or does it need separate log
  shipping; and the final tool/source allowlist (excluding the threat-intel
  cluster and `scan_repo_secrets`, per that review).
- Client cert vs. Authentik token flow for interactive callers — pick one
  once Phase 3 design work starts, rather than building both.
- **New, 2026-07-26**: how does a remote MCP client reach Graylog's native
  `/api/mcp` in `mgmt_seg` without opening a direct inbound hole into that
  zone from outside it? Graylog itself is the MCP server here (see the
  dedicated review above), so there's no adapter process to relocate into
  `automation_seg` the way there is for Proxmox/MikroTik/Grafana/NetBox/
  VictoriaMetrics — this is a network-policy question, not a placement one.
- **New, 2026-07-26**: `mcp-discovery-stack` is now sized at five adapter
  containers plus the `mcp-proxy` bridge (six total) once Grafana/NetBox/
  VictoriaMetrics are added alongside Proxmox/MikroTik — larger than any
  existing single-LXC stack in this repo. Revisit whether it should stay one
  LXC once real resource usage is known from Phase 2, rather than assuming
  the original two-stack split is final.
