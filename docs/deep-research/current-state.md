# Deep research: current state

Checked 2026-09-21. Originally gathered as a read-only inventory with no
service or infrastructure changes. That is no longer true as of the
incident below — this document now also records an actual outage caused by
Phase 0 validation work, plus real production changes made later the same
day (a new Traefik/DNS route) once the plan called for prototyping a
browser-based interface. See `plan.md` for the full narrative; this file
tracks current live state.

## Live state summary (2026-09-22, current)

- **Stage A LXC (VMID 50014) is decommissioned** — stopped and `pct
  destroy`ed 2026-09-22, once Stage B was live, healthy, and had run a
  real end-to-end query successfully. No data was migrated (operator's
  own call: nothing from Stage A's test sessions needed preserving).
  `192.168.50.13` no longer exists; do not reference it in new work.
- **Stage B is the only deployment now** — `deep-research`/
  `deep-research-files`, real Docker Compose services inside
  `ai-services-stack` (VMID 50013), non-root, Authentik `forwardAuth` on
  both routes, Graylog-bound logging. See Phase 4 in `plan.md` for the
  full design and the three real bugs found deploying it.
- Framework Nathanw endpoint: **up**, IaC-backed (Phase 0 complete).
- `ollama-reliability-proxy` **removed from `ai-services-stack` entirely**
  2026-09-22 — Ollama/Laguna isn't in active use on this platform anymore
  (Nathanw/llama.cpp has proven better performance/reliability here). Its
  broken healthcheck (dead Framework Ollama upstream) had been causing
  `openwebui` to need a manual restart after every redeploy touching the
  shared compose file; removing it fixed that at the root.
- Browser access: **`https://deep-research.lab.gibbsgreatly.xyz` and
  `https://deep-research-files.lab.gibbsgreatly.xyz` are both live**,
  behind real Authentik `forwardAuth` (confirmed live login round-trip,
  distinct OAuth `client_id` per route).
- **`deep-research-files` now renders real formatted reports**, not raw
  markdown text — Phase 1 of `docs/reporting-platform/plan.md`
  generalized it into the shared reports viewer (real markdown/table
  rendering, JSON pretty-printing, a project→run hierarchy), with
  `deep-research` as its first adopter. No change needed to
  `deep-research`'s own code — its existing output directory is wrapped
  as the `deep-research` project via a runtime symlink. See that plan's
  Phase 1 for two real bugs found deploying it.
- **Session persistence found already built into the vendored scaffold, just
  defaulted off** — `/new`, `/sessions`, `/resume`, `--list-sessions`,
  `--resume <id>` all exist in `engine/tui.py`/`app.py`. Flipped on
  (`enable_session_persistence: true`) in the live LXC config 2026-09-21.
- **Real bug found and fixed**: `web_search`/`fetch_url_to_workspace` calls
  hung for 1190-1260s (not just "slow DDGS") during a real operator-driven
  CVE/KEV query — `httpx`'s own `timeout=30` only bounds individual network
  I/O, not the whole `asyncio.to_thread()`-wrapped call, so a stuck DDGS
  backend or pathological-page parse (`BeautifulSoup`/`markitdown`) could
  hang indefinitely. Confirmed live via `ss -tnp` showing the query process
  at 40% CPU with every socket stuck in `CLOSE-WAIT` holding unread bytes —
  real CPU burn, zero forward progress. Fixed by wrapping both calls in
  `asyncio.wait_for()` (45s fetch / 30s search ceiling) in
  `tools/web.py` — a stuck call now fails gracefully instead of hanging the
  agent. Caveat: Python cannot forcibly kill the underlying OS thread, so a
  genuinely stuck thread may keep running in the background after the
  `wait_for` gives up; this stops the *agent* from hanging, it doesn't
  guarantee instant thread death.
- A real CVE/KEV query (CVE-2026-93957) completed successfully after the
  timeout fix — correct, well-cited, cross-referenced answer with gaps
  explicitly flagged; see `plan.md` Phase 5, point 4 for what it revealed
  about `cve-mcp` being a better-fitting tool for this query class than
  generic web search.
- **Known limitation**: the browser TUI session is not resilient to
  disconnection (closing the tab kills the in-progress query) — see
  `plan.md` Phase 5 for why. Use headless `--prompt --auto-approve` for
  anything that must survive a client disconnecting. Confirmed as a
  required Stage B design point (job model decoupled from the browser
  connection), not just a known quirk — see `plan.md` Phase 5, point 2.
- **`web_search` switched from DDGS to Tavily, 2026-09-22** — real,
  reproducible production incident: DDGS's `backend="auto"` routed
  through `search.yahoo.com`, which was erroring on every query, and the
  Searcher agent had no graceful fallback (blindly guessed URLs,
  exhausted its fetch/grep quotas, hard-aborted with "Agent trapped in
  loop"). Investigation ruled out every unauthenticated scraping
  alternative, confirmed live with five independent methods on this same
  network: DDGS itself, real headless-browser (Playwright/Chromium)
  scraping of both Bing and Brave via a recovered-but-still-broken
  `web-search-mcp` (see below), and raw HTTP fetches of both Bing and
  DuckDuckGo. All five failed the same way — not connectivity, not
  parsing bugs, but the search engines themselves either silently
  serving wrong/irrelevant results to unauthenticated automated traffic
  (Bing: real Playwright browser fetched a genuine 86KB page, and a
  plain `httpx` fetch of the same URL both returned articles about
  erectile dysfunction and Philippine prison policy for queries about a
  singer and an exact-phrase name) or explicitly CAPTCHA-gating it
  (DuckDuckGo's HTML endpoint literally serves "Unfortunately, bots use
  DuckDuckGo too... select all squares containing a duck"). Confirmed via
  a clean-room test of the genuinely unmodified upstream
  `kyuz0/local-agent-builder` scaffold (same `ddgs==9.16.0`, zero
  homelab modifications) that DDGS fails identically there too — this
  was never something Stage A/B modifications broke. Fixed by replacing
  `web_search`'s implementation in `tools/web.py` with a direct call to
  Tavily's search API (real authenticated API, free tier 1000
  searches/month, `TAVILY_API_KEY` in `secrets.common.enc.yaml`) —
  removes the `ddgs` dependency entirely. `web-search-mcp` (headless-
  browser search fronted by `mcpo`) was separately recovered from an
  unmerged, undocumented, drifted-out-of-sync branch during this
  investigation and is now properly tracked IaC wired into OpenWebUI,
  but is **not** used by `deep-research` — it has the same
  unauthenticated-scraping reliability problem Tavily was adopted to
  avoid. See `terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md`
  for its current status.
- **Real bug found deploying the Tavily switch, 2026-09-22: every code
  change to `deep-research` since Stage B's first deploy had been
  silently ignored at runtime.** The named volume backing config/session/
  workspace persistence was mounted at the whole `/home/app` home
  directory, not just `~/.deep-research-agent` — so the volume's content
  from the very first deploy shadowed every subsequent image rebuild's
  fresh `COPY src ./src` at container start. Confirmed live: the running
  container's `src/tools/web.py` was dated the day before, with none of
  that day's fixes (Tavily switch, earlier timeout fix, etc.) present.
  Fixed by narrowing the mount to exactly `~/.deep-research-agent` and
  renaming the volume (`ai-services-deep-research-config`, not the old
  `ai-services-deep-research-data`) since the old volume's content
  structure doesn't match the new, narrower mount point. See
  `STACK_CONTRACT.md`'s Persistent State table.
- **Real production hang, 2026-09-22: a live research session pegged the
  container at 99% CPU for 24+ minutes with the GPU/LLM completely idle,
  freezing the browser session.** `write_workspace_file` appeared stuck
  in the UI, but `docker top`/`py-spy`-adjacent investigation (26 threads,
  main thread state `R`/running, not blocked on I/O) showed a genuine
  CPU-bound spin, not a network wait. Root cause not confirmed — three
  separate reproduction attempts (single-page pathological parse,
  concurrent `markitdown` conversions on fresh instances, concurrent
  conversions on the exact shared-singleton pattern `utils/parsers.py`
  actually uses) all completed cleanly in isolation. This matches an
  already-documented residual risk from the 2026-09-21 timeout fix:
  `asyncio.wait_for()` can give up and let the agent move on, but Python
  cannot forcibly kill the underlying OS thread it spawned via
  `asyncio.to_thread()` — a zombie thread from an earlier abandoned
  `fetch_url_to_workspace`/markitdown call most likely kept running and
  starved the whole container of CPU. Fixed at the structural level
  regardless of the exact trigger: `fetch_url_to_workspace`'s blocking
  work now runs in a spawned (not forked — see `tools/web.py`'s
  `_MP_CONTEXT` comment for why fork is itself a deadlock risk here)
  subprocess via `multiprocessing`, which **can** be genuinely SIGTERM/
  SIGKILLed on timeout. Verified live: a simulated infinite-loop worker
  was force-killed in exactly the configured timeout window, confirmed
  dead via `process.is_alive()`. Also added a `faulthandler` SIGUSR1
  hook in `app.py` (`docker kill -s SIGUSR1 deep-research` dumps every
  thread's real stack trace to the container's logs) so a recurrence is
  instantly diagnosable instead of requiring another round of blind
  hypothesis testing.

## Incident, 2026-09-21: Framework host hang during Phase 0 validation

While validating the Phase 0 Ansible playbook
(`ansible/00-initial-setup/framework-desktop-llamacpp-nathanw-vulkan.yml`),
a "shadow" container was started on a different port to avoid colliding
with the live `qwen38-flash-next-q4` container's name/port. It loaded a
second full ~111GB copy of `Qwen3.8-Flash-Next-UD-Q4_K_XL` with `-ngl 99`
(all layers GPU-resident) while the live container — already holding its
own ~111GB resident copy — kept running. Combined demand (~222GB) exceeded
the host's 122GB total unified memory. The host hung (SSH timed out during
banner exchange) and required a hard reset by the operator.

**Post-reset state:** the host is back up with memory clear, but **neither
the shadow container nor the original live `qwen38-flash-next-q4` container
is running.** Both had `restart_policy: "no"`/`auto_remove: true` (an exact
reproduction of the live container's own pre-existing lack of supervision,
captured before this incident — see below), so neither came back
automatically after the reboot. The Framework inference endpoint this
entire deep-research plan depends on is therefore **currently down** and
needs to be manually brought back up before any further Stage A work.
Do not assume it is available without checking `/health` first.

The playbook has since been corrected with two pre-flight guards it should
have had from the start: it now refuses to start if the live container is
already running (unless doing a deliberate stop-first promote cutover), and
refuses to start unless `/proc/meminfo`'s `MemAvailable` clears a threshold
sized for this model's full resident footprint. Neither guard existed in
the version that caused the incident.

**Stage A scaffold built and first runs succeeded, 2026-09-21:** the Local
Agent Builder scaffold was vendored and customized into a three-tier
orchestrator/searcher/analyzer app at `/opt/deep-research-agent` inside the
LXC below. Cross-checking the skill's own `CHECKLIST.md` after the first
pass caught several real gaps (missing `agent_id` routing instructions in
prompts, missing concrete `delegate_tasks` JSON examples, missing the
fetch→capture→forward filename handoff from Searcher to Analyzer, an
unpruned RAG/shell tool surface) — all fixed before running anything.
`ddgs` was pinned to `9.16.0` rather than left unpinned as in the source
example. Two real end-to-end runs against the (now IaC-backed) Framework
endpoint both succeeded — see `plan.md` Phase 1 for the details and two
findings worth carrying into Phase 2: quotas in this scaffold are global
per tool name, not per-agent-instance as originally assumed, and the
DuckDuckGo bot-detection flakiness seen via raw `curl` earlier in this
document did not block the real `ddgs` client's actual queries.

**Stage A LXC created 2026-09-21:** VMID `50014`, hostname
`deep-research-stage-a`, `192.168.50.13` in `ai_seg`, unprivileged, 2
cores/2GB RAM/512MB swap/12GB rootfs, throwaway (not Terraform-managed, no
stack contract). Created manually per `plan.md` §2.1 since `pve-test-vm` is
not used. No firewall changes were needed — confirmed live: reaches
`framework.gibbsgreatly.xyz:8080/health` (200) and the public internet
(tested against `1.1.1.1`, 301) using `ai_seg`'s existing egress rules.

**Resolved, same day:** the corrected playbook was run in promote mode
(`framework_llamacpp_nathanw_container_name=qwen38-flash-next-q4`,
`..._port=8080`, `..._promote=true`), with the live container correctly
absent so no stop-first step was needed and the memory guard passing
against ~124GB available. It brought the endpoint back up and was
independently re-verified afterward: `curl /health` returned `{"status":
"ok"}`, and `/props` reported `n_ctx=262144`/`total_slots=4`, matching the
pre-incident recorded values exactly. `docker ps` on Framework confirmed
exactly one `qwen38-flash-next-q4` container running, no duplicates.
**Phase 0 of `plan.md` is complete** — the endpoint is up and now has a
reproducing, guarded Ansible playbook.

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

**Status as of 2026-09-21: back up, IaC-backed.** The table below was
originally captured before the incident above, and was independently
re-confirmed unchanged after the Phase 0 playbook brought the endpoint
back up (same `/health`/`/props` values).

The endpoint at `framework.gibbsgreatly.xyz:8080` reports:

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

### Live container configuration (captured 2026-09-21, read-only `docker inspect`)

This is the exact configuration Phase 0's Ansible playbook must reproduce.
Captured directly from the running container on `framework.gibbsgreatly.xyz`
via `docker ps`/`docker inspect qwen38-flash-next-q4` — no changes made.

| Field | Value |
|---|---|
| Container name | `qwen38-flash-next-q4` |
| Image | `ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan` |
| Image digest (pin target) | `sha256:2fe2c66f712d23ff51cc99227ea6ef65d06979ff8381860fead494ea00d350cb` |
| Image label `org.opencontainers.image.version` | `24.04` (this is the bundled Mesa/Ubuntu base label, not a fork release tag — do not confuse with the `v0.7.6.1` fork version cited in the old reference playbook; the live image was never confirmed to be that version) |
| Command | `llama-server -m /models/qwen3.8-flash-next-q4/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf -ngl 99 -fa 1 --host 0.0.0.0 --port 8080 --load-mode mmap --no-host --no-repack --fit off` |
| Bind mount | `/mnt/nvme2/models-gguf` (host) → `/models` (container), rw |
| Model files present | 4-shard GGUF under `/mnt/nvme2/models-gguf/qwen3.8-flash-next-q4/UD-Q4_K_XL/`, confirmed on disk (~111 GB total across shards) |
| Devices | `/dev/dri` only, `rwm` — no `/dev/kfd`/video/render groups. Confirms the old reference playbook's Vulkan-not-HIP comment. |
| Port | `8080/tcp` → host `8080`, bridge network |
| Log driver | `syslog`, `syslog-address: tcp://127.0.0.1:10514`, `syslog-format: rfc5424`, tag `docker-{{.Name}}` — **not** the `json-file` driver other stacks in this repo default to; a rebuild that silently reverts to `json-file` changes where these logs land |
| Restart policy | `"no"`, `AutoRemove: true` |
| Env | Only `PATH=/opt/strix-halo-llamacpp/vulkan:...` — no other env vars set |
| Created / last (re)started | Created 2026-09-17T19:55:31Z; last started 2026-09-19T20:26:34Z (a gap between these — it was manually restarted at least once) |

Two things this capture leaves unresolved and Phase 0 must not guess at:

1. **No `--ctx-size`/`-c` or `--parallel`/`-np` flag appears in the running
   command**, yet the live `/props` endpoint reports `n_ctx: 262144` and
   `total_slots: 4`. These are therefore either compiled-in defaults of this
   specific fork/build, or defaults derived from the model's own GGUF
   metadata (`n_ctx_train` is also 262144, matching) — not something visible
   in the container's own invocation. A reproduction that adds explicit
   `-c 262144 -np 4` flags is not proven equivalent to the live behavior
   until the rebuilt container is confirmed to report the same `/props`
   output; do not assume the flags are redundant just because the numbers
   match today.
2. **No systemd unit, cron job, or user-service was found supervising this
   container** (`systemctl list-units --all`, `crontab -l`, and
   `systemctl --user` all came back empty for anything llama/qwen/nathanw/
   strix-related). Combined with `RestartPolicy: "no"` and `AutoRemove:
   true`, the live service has **no automatic recovery on crash or host
   reboot** — it was started by hand and stays up only until someone
   restarts it. Phase 0's playbook should preserve this exact behavior
   first (per the instruction to match the known-good config), then treat
   adding real supervision as a separate, explicitly-flagged improvement
   decision — not something to silently fix while "just" writing the IaC.

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
- ~~The live Nathanw llama.cpp deployment has no reproducing IaC.~~
  **RESOLVED 2026-09-21** — `ansible/00-initial-setup/framework-desktop-llamacpp-nathanw-vulkan.yml`
  now reproduces the live configuration (image pinned by digest, exact
  command flags, bind mount, device, syslog log driver, no
  supervision/auto-remove matching the original), with pre-flight guards
  against the double-load failure mode that caused the same-day host-hang
  incident above. `ansible/00-initial-setup/framework-desktop-llamacpp-nathanw.yml`
  (the older, unrelated, explicitly-not-wired-up file for a different port/
  model/build, written for CyberSecEval) is unaffected and still not to be
  confused with this one.
- **DDGS/DuckDuckGo reachability from this network is unresolved, not
  confirmed-broken.** The 2026-08-02 finding above (SearXNG's `duckduckgo`/
  `duckduckgo web` engines hit a hard TCP timeout, reproduced from a separate
  workstation, confirmed at the router level) did not reproduce identically
  on a fresh check from the workstation on 2026-09-21: two back-to-back
  `curl` requests to `html.duckduckgo.com` returned HTTP 202 and then HTTP
  400 within seconds of each other — active, inconsistent bot-detection
  behavior, not a clean timeout. Neither result should be trusted as current
  without re-testing from the actual runtime environment (the Stage A
  throwaway LXC on `pve`, per `plan.md`) using the same client (`ddgs`) Stage A
  will actually use — a `curl` GET does not reproduce what the `ddgs` Python
  package's own request shape and backend selection will see.
