# PentAGI ↔ Greenbone (GVM) integration — scoping

**Status: implemented and deployed to production, 2026-08-03.** See
"Implementation status" near the end for what was actually built,
deployed, and validated, and what's still a known gap. Architecture
decided below; supersedes this file's earlier
"not implemented, explicitly deferred" pass (`plan.md` §7 and every
subsequent doc update up to 2026-08-01) — the gap analysis in the next
section is still accurate and preserved, but the "what would actually
need to change" section has been replaced with a decided shape, because
the situation changed since it was written: PentAGI's fork now has a real,
working precedent for exactly this kind of integration —
`triage_cve`/`search_cves`, wired directly into the Go backend against
`cve-mcp-server` on `mcp-utility-stack` (see
`docs/pentagi-stack/cve-mcp-integration-plan.md`, implemented and verified
live 2026-08-02). That precedent changes the recommended shape here
significantly — see "Decided architecture" below.

This file exists so the next pass doesn't have to re-derive the
architecture from scratch — it records what's actually true today about
both stacks, the one real gap that blocks integration, and the decided
plan for closing it.

## Why this is not just "point PentAGI at GVM's API"

The two stacks live in the same zone (`pentest_seg`, VLAN 70) but in
**separate LXCs, each with their own nested Docker daemon**. That matters
because of how each stack actually works internally:

- **GVM's GMP API is Unix-socket-only, not network-reachable.** `gvmd` in
  this stack's compose (`deploy-greenbone-stack.yml`) has no `ports:`
  mapping and no `--listen`/`--port` command override — it only exposes
  GMP over `gvmd_socket_vol`, a Docker named volume mounted into `gvmd`
  and the throwaway `gvm-tools` container *within `greenbone-stack`'s own
  Docker network*. Every GMP call this stack's own playbook makes (LDAP
  config, the Phase 4 test scan) works by bind-mounting that same socket
  volume into a `docker compose run gvm-tools ...` container running
  **on the same host, in the same Docker daemon**. There is currently no
  way to speak GMP to this stack from outside its own LXC — not from
  another container, not from another host on the same subnet. Confirmed
  by reading the compose definition directly (`gvmd` block has no `ports:`
  key at all, unlike `nginx`'s `0.0.0.0:443:443`/`0.0.0.0:9392:9392`).
- **PentAGI doesn't have a pluggable external-tool/MCP mechanism** (at
  least not one used or documented anywhere in `docs/pentagi-stack/`).
  Its real architecture (`docs/pentagi-stack/plan.md` §0) is: the
  `pentagi` container holds a mounted Docker socket into `pentagi-stack`'s
  *own* nested Docker daemon, and its built-in "terminal" tool spawns
  ephemeral sibling containers (`pentagi-terminal-*`) to actually run
  shell commands. Those worker containers are siblings within
  `pentagi-stack`'s Docker daemon — a completely different daemon than
  `greenbone-stack`'s. They can reach `greenbone-stack`'s **IP over the
  network** (same VLAN, no firewall rule currently blocks it — see
  below), but they cannot mount another LXC's Docker volumes or exec into
  another daemon's containers. Whatever GVM exposes has to be a real
  network listener for a PentAGI terminal-tool command to reach it at
  all.

So the `STACK_CONTRACT.md` line claiming PentAGI "can reach this stack's
GMP socket-backed API in-zone with no additional cross-zone firewall
rule" is aspirational/inaccurate as written — same-zone network reach and
socket-backed reach are different things. **The real gap is that gvmd
needs an actual TCP listener before any of that network reach matters.**
This file supersedes that line; `STACK_CONTRACT.md` should be corrected
to point here rather than repeat the claim.

## Decided architecture

The 2026-08-01 pass considered exposing raw GMP-over-TCP on `gvmd` and
having PentAGI's Go backend or Kali worker image speak the protocol
directly (either a real GMP XML client, or a baked-in Python CLI wrapper
invoked through the terminal tool). Both are now superseded by a cleaner
option that wasn't available at the time: **mirror the `cve-mcp-server`
integration exactly, one layer closer to `gvmd`.**

`cvemcp.go`/`triagecve.go`/`searchcves.go` proved the shape that works
well for this fork: a small, purpose-built network service holds the
real client/credential complexity server-side, and PentAGI's Go backend
talks to it over a trivial JSON/HTTP call — no raw protocol, no
credential inside an ephemeral worker container, no agent-composed
syntax to get wrong. GVM's real complexity is worse than CVE-MCP's
(GMP is a stateful, verbose legacy XML protocol, not JSON-RPC), which
makes this pattern even more valuable here, not less.

### The new component: `gvm-bridge`

A small custom service, **added as a new service inside
`greenbone-stack`'s own docker-compose stack** (not a new LXC) — it has
to live there because it needs to mount `gvmd_socket_vol`, the Docker
named volume `gvmd`'s Unix-socket-only GMP API is exposed on today. This
also means **raw GMP-over-TCP on `gvmd` is no longer needed at all** —
the earlier plan's Section 1 (`--listen=0.0.0.0 --port=9390`) is dropped;
the bridge talks to `gvmd` over the existing socket, in the same Docker
network, exactly like the playbook's own `gvm-tools` container already
does for LDAP setup and the Phase 4 test scan.

- **Implementation**: Python, using `python-gvm`'s `UnixSocketConnection`
  (the same library `gvm-tools`/`gvm-cli` are built on) against
  `gvmd_socket_vol`. A minimal HTTP framework (plain `http.server` or
  FastAPI — decide at implementation time, no strong reason either way
  for 3 endpoints) exposes:
  - `POST /scan/start` — body `{"target_ip": ..., "ports": [...]}`.
    Internally: `create_port_list` (scoped to the given ports, matching
    Phase 4's own pattern), `create_target` with
    **`alive_tests: Consider Alive` unconditionally** (not
    conditional on some "is this target ICMP-reachable" check — every
    target this integration will ever point at is inside `pentest_seg`'s
    deliberately-firewalled lab targets, so hardcoding the fix for the
    gotcha that already bit Phase 4 is strictly safer than risking the
    silent-zero-results failure mode by trying to be clever about when
    it's needed), `create_task` ("Full and fast" scan config, matching
    Phase 4), `start_task`. Returns `{"task_id": ...}`.
  - `GET /scan/status/{task_id}` — wraps `get_tasks(task_id=...)`,
    returns status/progress.
  - `GET /scan/results/{task_id}` — wraps **`get_results`, never
    `get_reports`** (the crash bug in `plan.md` §4 /
    `STACK_CONTRACT.md`). This is the enforcement mechanism for that
    gotcha: `get_reports` is simply never called by any code path in the
    bridge, so it can never surface as a footgun to an LLM composing
    calls, unlike a raw-GMP approach where the agent could reach for it
    directly.
- **Credential**: a dedicated `gvmd` user (e.g.
  `gvmd --create-user=pentagi-integration`), **not** `steve` (a real
  person's LDAP login) and **not** the SOPS `GREENBONE_ADMIN_PASSWORD`
  admin account. Scope its role to target/port-list/task creation and
  `get_results`/`get_tasks` — check `get_roles` on the live system for
  the closest built-in role, or define a custom one if none fits tightly
  enough. Password stored the same way `GREENBONE_ADMIN_PASSWORD` is —
  a new `GREENBONE_PENTAGI_PASSWORD` SOPS key — injected only into the
  bridge's own container environment. PentAGI's Go backend and its
  ephemeral worker containers never see this credential at all, matching
  how `cve-mcp-server` holds its own NVD/GitHub/etc. keys server-side.
- **Network exposure**: the bridge binds its HTTP port (e.g. `8010`) to
  the container's routable interface, reachable from `pentagi-stack`
  within `pentest_seg` — both stacks are already in the same zone, and
  the existing doc's own instruction still applies: **confirm live with
  a `nc -zv` test before assuming no new MikroTik rule is needed**, don't
  trust the zone's intent comment alone.
- **Source location — decided 2026-08-03: in-repo.** `gvm-bridge` lives
  inside `proxmox-homelab` (e.g. `terraform/lxc/ansible/files/gvm-bridge/`),
  copied onto the host by `deploy-greenbone-stack.yml` the same way
  `deploy-mcp-utility-stack.yml` copies `cve-mcp-server`'s source, but with
  no second git repo to maintain — there's no external upstream identity
  to preserve here, unlike `cve-mcp-server` (`mukul975/cve-mcp-server`).
- **Target-scope enforcement — decided 2026-08-03: no bridge-level
  allowlist.** `/scan/start` accepts whatever `target_ip` the caller
  passes; containment relies entirely on `pentest_seg`'s existing network
  reach (the bridge, like `gvmd`, can only reach hosts this zone's
  MikroTik policy already allows — the same containment model every other
  tool in this zone, including PentAGI's terminal tool, already relies on).
  No additional app-layer restriction.

### PentAGI side: three new tools, same shape as `triage_cve`/`search_cves`

- `start_gvm_scan`, `get_gvm_scan_status`, `get_gvm_scan_results` — new
  Go tools in `backend/pkg/tools/`, following `cvemcp.go`'s exact
  plumbing pattern (shared client/base struct, `IsAvailable()` gated on
  a new `GvmBridgeURL` config field, swallow downstream errors into a
  formatted result rather than a hard Go error). Since the bridge speaks
  plain JSON over HTTP (not MCP), the client is simpler than
  `cveMcpClient` — no SSE-frame parsing, no JSON-RPC envelope, just a
  `POST`/`GET` and a JSON body.
- Wired into the same 3 role-executor sites as `triage_cve`/`search_cves`
  (`GetAssistantExecutor`, `GetPentesterExecutor`, `GetSearcherExecutor`
  in `tools.go`) — same rationale, same non-touch of `GetEnricherExecutor`.
- **No new "collation" tool needed.** This directly answers the "is this
  workable" question that prompted this scoping pass: the user's proposed
  pipeline (scan → collect → if CVE found, send to `cve-mcp` → collate
  and use to guide the pentest) doesn't need to be hand-coded as a fixed
  Go-side pipeline. The pentester/searcher/assistant roles already have
  `triage_cve`/`search_cves` wired in from the earlier integration. Once
  they also have `start_gvm_scan`/`get_gvm_scan_status`/
  `get_gvm_scan_results`, the agent's own reasoning loop can chain them
  in exactly one turn's worth of tool calls: run the scan, read whatever
  CVE IDs show up in the results (Phase 4's real findings included named
  CVEs/GHSAs), call `triage_cve` on the interesting ones, and use both
  result sets to decide what to do next. This matches how Sploitus,
  SearXNG, and CVE-MCP are already just parallel tools available to the
  same role — the agent does the composition, not hard-coded Go logic.
- **Async handling**: `start_gvm_scan` returns immediately with a
  `task_id` (scans run for real minutes, per Phase 4 — exact duration for
  a "Full and fast" scan against a 2-port target wasn't recorded there
  and should be timed during implementation). The agent polls
  `get_gvm_scan_status` itself between other actions, the same way it
  already tolerates other slow operations — no blocking/long-poll needed
  in the tool call itself.

## Carrying over the two real GVM gotchas (unchanged, now enforced structurally)

Both documented in full in `plan.md` §4 and `STACK_CONTRACT.md`'s "What
Must Not Be Edited Casually", and both are now closed off at the bridge
level rather than left as agent-facing hazards:

- **`alive_tests: Consider Alive` is hardcoded into every
  `/scan/start` call** the bridge makes — not conditional, not something
  the calling agent has to remember to ask for. Closes the "scan finishes
  in ~30s with zero results that look like a clean scan" failure mode
  Phase 4 hit.
- **`get_reports` is never called by any bridge code path** — only
  `get_results`. Since the bridge is the only thing that ever speaks GMP
  on PentAGI's behalf, this fully removes the footgun rather than relying
  on a system-prompt instruction to avoid it.

## Open questions, not yet decided

- Whether GVM scan results should feed back into PentAGI's own reasoning
  loop automatically (now the default assumption, since the agent already
  has both toolsets once this lands) or whether a human-triggered,
  human-read path should also stay available as a fallback — leaning
  toward "automatic is fine, matches how CVE-MCP already works," but not
  formally decided.
- Whether the bridge's HTTP endpoint needs any auth at all given
  `mcp-utility-stack`'s explicit "no built-in auth, network-level access
  control only" precedent for `cve-mcp-server` — leaning toward the same
  posture here (MikroTik-level access control, no app-layer auth), since
  it's the same zone and same trust model, but worth confirming rather
  than assuming during implementation.

## Implementation status (2026-08-03)

Built and deployed as designed above:

- `gvm-bridge` (`terraform/lxc/ansible/files/gvm-bridge/`) added to
  `greenbone-stack`'s own compose, built in-repo, live on both
  `pve-test-vm` and production `pve`.
- Three new PentAGI Go tools (`start_gvm_scan`, `get_gvm_scan_status`,
  `get_gvm_scan_results`) wired into the `assistant`, `pentester`, and
  `searcher` executors, same shape as `triage_cve`/`search_cves`. Unit
  tests pass; `GVM_BRIDGE_URL` wired into `pentagi-stack`'s compose/`.env`.
- **Full end-to-end chain confirmed live**, via PentAGI's Assistant mode
  (`createAssistant`/`callAssistant`, `useAgents: false`) on
  `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`: `start_gvm_scan` (real task/report
  IDs against `harness-target`) → `get_gvm_scan_status` (polled through
  real `Requested`/`Queued` states) → `get_gvm_scan_results` (10 real
  findings — Redis 7.4.10 and Jetty 9.2.11 detected on port 8080, Apache
  Struts, missing security headers/cookie attributes) → `triage_cve`
  (called twice for real, for CVE-2015-2080 and CVE-2015-2081, both
  returning genuine structured risk assessments) → a coherent final
  natural-language summary with patch recommendations. This is the
  complete proof that the no-hard-coded-pipeline premise this integration
  rests on actually holds: the agent chained scan → results → CVE triage
  itself, from one instruction, using only its own tool-calling.
  (One minor, non-blocking observation: the model's own prose summary
  mislabeled CVE-2015-2081's risk tier, contradicting `triage_cve`'s own
  correct LOW/20.59 output — a synthesis quirk in the model's final
  write-up, not a data or tool-call problem.)

**Known reliability caveat, not a bug in this integration**: getting to
that successful run took multiple attempts. Under PentAGI's actual
production load (full system prompt, full tool roster, conversation
history), local models — including `Qwen3.6-35B` and, on earlier
attempts, `Qwen3-Coder-30B` itself — intermittently reason out the
*correct* call and arguments but emit them as plain text instead of a
real tool call, especially in the multi-agent `pentester`/subtask-
decomposition path. The simpler single-agent Assistant mode proved
markedly more reliable than the autonomous pentester/subtask path for
this. Confirmed via a clean, isolated request to the same backend that
the model/router combination can produce genuine `tool_calls` output
when the request is small — the unreliability scales with prompt/context
complexity, not a fixed model incapability.
This is a local-model capacity/reliability limit, not something to fix
in `gvm-bridge` or the Go tool-wiring.

**Two infra bugs found and fixed along the way, unrelated to the
integration design**:
- The `pentagi-integration` gvmd user went missing on production
  `greenbone-stack` at some point after initial creation (credential
  drift, same pattern as the `PENTAGI_HARBOR_ROBOT_PASSWORD` issue below)
  — recreated manually; the ansible task that creates it should be
  revisited to confirm it's actually idempotent against a user that
  exists with a stale/wrong password, not just against "user doesn't
  exist at all".
- `framework.gibbsgreatly.xyz`'s `llamacpp-router` (`--parallel 2`)
  broke structured tool-call generation model-agnostically — reverted to
  `--parallel 1`. The memlock ulimit fix (`ulimits: memlock: -1`,
  resolving the AMD Strix Halo APU's SVM-mapping/GPU-offload failure
  documented in `docs/framework-integration/`) is unrelated and stayed
  applied.

**Follow-up, not yet fixed**: `PENTAGI_HARBOR_ROBOT_PASSWORD` 401s
against production Harbor; pushes during this work used the
`HARBOR_ADMIN_PASSWORD` fallback instead. Needs reconciling, not just
rotating — see git history around 2026-08-02/03 for context.

### Deeper validation against Metasploitable2 (2026-08-03) — three real bugs found and fixed

The `harness-target` run above validated the pipeline shape, but
`harness-target`'s own findings never happened to carry a GVM-tagged CVE
(all severity 0.0 version/banner detections), so the `nvt/cve` extraction
path in `gvm-bridge`'s `/scan/results` was never actually exercised
end-to-end. Re-running the same validation against Metasploitable2
(`192.168.1.113`, well-documented CVEs, an existing authorized target
from earlier PentAGI harness work — see `docs/pentagi-stack/lessons-learned.md`)
surfaced three real, previously-invisible bugs in `app.py`, all now
fixed and confirmed live:

1. **Wrong task scoping.** `gmp.get_results(task_id=task_id, ...)` looks
   like it filters by task, but per python-gvm's own docstring `task_id`
   there only affects note/override handling — it did nothing to scope
   which results came back. Confirmed by reproducing it: a query for the
   Metasploitable2 task returned stale results from an unrelated
   `harness-target` task. Fixed with `filter_string=f"task_id={task_id}"`.
2. **Silent pagination truncation.** GMP defaults `get_results` to
   `rows=10`. The Metasploitable2 task had 72 raw results; every query
   was silently capped at the first 10, which happened to exclude the
   critical finding. Fixed by adding `rows=-1` to the filter string.
3. **Wrong CVE extraction XPath.** `r.findtext("nvt/cve")` was always
   `None` — that node doesn't exist in this GMP schema. The real CVE
   reference lives at `nvt/refs/ref[@type="cve"]`, with the CVE ID as
   that element's `id` attribute, confirmed by dumping the raw result XML
   for the critical finding. Fixed with an explicit `find()` + `.get("id")`.

All three were live on production `greenbone-stack` (`pve`) until fixed
in place (`docker compose build && up` against the same in-repo
`gvm-bridge/` source, then committed). Post-fix, `gvm-bridge` correctly
returned all 27 results for the Metasploitable2 task, including
`CVE-2011-2523` (the vsftpd 2.3.4 backdoor, CVSS 9.8) at both port 21/tcp
and 6200/tcp — and a fresh PentAGI Assistant run correctly called
`get_gvm_scan_results`, picked up that real CVE ID (not a model-recalled
one this time), called `triage_cve`, and got back a genuine HIGH-risk
assessment (69.59/100, EPSS 96.2%, patch within 72 hours), concluding
with an accurate natural-language summary. This is the clean, complete
confirmation that both the GVM-side detection and the CVE-MCP triage
path work correctly with real GVM-tagged data, not just model-recalled
CVE knowledge.

**One more infra gotcha found along the way, not yet fixed in code**:
PentAGI has a built-in guard that aborts an agent chain after a tool is
called 7 times consecutively with identical arguments — a sensible
anti-infinite-loop protection in general, but it structurally conflicts
with `get_gvm_scan_status`'s own documented usage pattern ("poll until
Done"), since a legitimately longer-running scan's poll calls look
identical every time. `harness-target`'s narrow 2-port scan finished
within ~2 polls and never tripped it; Metasploitable2's broader scan did,
aborting the assistant mid-poll. Workaround used during testing: instruct
the model to vary the poll call's free-text `message` argument each time
(e.g. an incrementing attempt count) so consecutive calls aren't
byte-identical. A real fix belongs in the PentAGI fork itself — either
exempt designated polling-style tools from this guard, or use a smarter
heuristic (e.g. only guard identical calls that also return identical
results) — not something to solve from the `gvm-bridge` side.

## Related documentation

- `docs/pentagi-stack/cve-mcp-integration-plan.md` — the direct
  architectural precedent this scoping pass mirrors: a small network
  service holding real client/credential complexity, PentAGI's Go backend
  talking to it over a trivial JSON call, wired into the same 3
  role-executor sites. Read this first — it's the template.
- `docs/greenbone-stack/plan.md` §4 — the two GVM gotchas in full detail,
  from this stack's own Phase 4 test scan.
- `docs/greenbone-stack/STACK_CONTRACT.md` — network/inputs/provides
  contract; needs a correction to its "What May Depend on This Stack"
  section once this integration is actually built (currently says
  "Nothing yet").
- `docs/pentagi-stack/plan.md` §0 — PentAGI's Docker-outside-of-Docker
  architecture (`pentagi` container + Docker-socket-spawned
  `pentagi-terminal-*` siblings), the actual constraint this file's
  analysis is built on.
- `docs/pentagi-stack/README.md` — Kali worker image details
  (`DOCKER_DEFAULT_IMAGE_FOR_PENTEST`, the Harbor-rewrite gotcha for
  images pulled outside that variable).
