# Vanilla-upstream PentAGI companion (on `pentagi-stack`'s LXC)

Status (2026-08-23): the vanilla-upstream project is still the **active**
project on 70010, but it is currently running a fully-patched build (all 6
fixes from this investigation and the smoke-test follow-up), not the
original vanilla upstream image — see [Current live state](#current-live-state)
below. The patched `pentagi-stack` project is **not currently deployed**.
The worker-leak investigation itself is **closed**; a follow-on
smoke-testing pass found and fixed 4 further reliability bugs and also
found autonomous exploitation itself never once succeeded. **Since
superseded by a more severe finding**: the `installer` delegate role
fabricates confident, plausible "success" reports without actually
executing anything, 92% of the time, across this entire investigation —
see [finding 9](#9-the-installer-delegate-role-fabricates-success-reports-without-executing-anything-92-of-the-time-2026-08-2223)
and
[problem-statement.md](problem-statement.md#capability-assessment-read-before-trusting-this-for-real-engagements)
for the full, honest capability read before trusting this for a real
engagement.

## Deployment model

There is one LXC: `pentagi-stack` (VMID `70010`, `192.168.70.10`,
`pentest_seg`). It can hold two Docker Compose projects on disk:

| Project | Path | What it is |
| --- | --- | --- |
| `pentagi-stack` | `/opt/pentagi-stack` | The patched, harness-integrated deployment (custom `pentagi-fixed` image, role/provider config, CVE-MCP, GVM bridge, shared Docker network). |
| vanilla-upstream companion | `/opt/pentagi-upstream-vanilla` | Byte-for-byte unmodified upstream. No patches, no harness integration. |

**Only one runs at a time.** Upstream's Compose file hardcodes container
names (`pentagi`, `pgvector`, `scraper`, `pgexporter`), so both projects
can't hold them simultaneously. Whichever is up answers the existing
`pentagi.lab.gibbsgreatly.xyz` Traefik route and Authentik gate — switching
projects needs no edge/DNS change.

Switch manually:

```bash
# lab (patched) -> vanilla upstream
ssh root@192.168.70.10 'cd /opt/pentagi-stack && docker compose down'
ssh root@192.168.70.10 'cd /opt/pentagi-upstream-vanilla && docker compose up -d'

# vanilla upstream -> lab (patched)
ssh root@192.168.70.10 'cd /opt/pentagi-upstream-vanilla && docker compose down'
ssh root@192.168.70.10 'cd /opt/pentagi-stack && docker compose up -d'
```

Deploying via automation: `pentagi-stack`'s `stack.yaml` has one
`ansible_playbook` pointer, so it selects one project per run of
`provision.sh --stack pentagi-stack`:

- `deploy-pentagi-stack` → patched project
- `deploy-pentagi-upstream-vanilla-companion` → vanilla-upstream companion

## Current live state

The pointer is currently set to `deploy-pentagi-upstream-vanilla-companion`
(commit `cdc878b0`, 2026-08-19, "deploy pinned upstream PentAGI for cleanup
investigation"). It was meant to be reverted once the worker-lifecycle
investigation finished; it hasn't been yet — and by 2026-08-22 the
vanilla-companion slot itself has drifted well past plain vanilla anyway.

Confirmed live on 70010 (2026-08-22):

- `/opt/pentagi-upstream-vanilla` exists and is the running project, but
  its `pentagi` container is now running a locally-built image
  (`pentagi-modelswap:0b2c1ec`, tagged as `vxcontrol/pentagi:latest`) that
  carries **all 6 fix commits** from this investigation and the smoke-test
  follow-up — it is no longer byte-for-byte vanilla upstream in behavior,
  only in `docker-compose.yml`/provenance. The original pinned upstream
  image (digest `sha256:7d964a6e...b62e9`) is still present locally on
  70010 if a true-vanilla baseline is needed again.
- `/opt/pentagi-stack` does not exist. No `pentagi-stack_*` Docker volumes
  exist either.
- No backup exists for VMID 70010 (checked PBS, `storage-backup`,
  `gazaar-backup`, `nas-backup`) and no ZFS snapshots exist for its rootfs
  or `/var/lib/docker` datasets.

**Consequence:** the patched project's prior runtime state (flow/task
history, DB rows) is gone, not just hidden. Redeploying `deploy-pentagi-stack`
restores the code/config cleanly but starts with empty application state.

Restoring the patched `pentagi-stack` project (merging this investigation's
fix branch into `fix/lab-lessons-learned`, building `pentagi-fixed`, pushing
to Harbor, redeploying) is a deliberate next decision, not yet done — see
the capability assessment linked above before treating that restoration as
"production-ready for real engagements" rather than "reliable for
recon/multi-step-ops work."

## Upstream provenance and image handling

The vanilla project's `docker-compose.yml` is byte-for-byte the file at
upstream PentAGI revision `879e87c2c2688c4a95eac9c1aaf3cd6f6123ebe3`.
Verified SHA-256:

```
8dd61ae1a92096bea2477426043751f19471c844a5ed1094d957549056039063
```

All images are pulled through Harbor, never directly from a public registry.
The deployment pulls the Docker Hub/Quay proxy-cache references below, then
tags those exact local images with the names the unmodified upstream Compose
expects — unmodified Compose file, still compliant with registry-routing
policy.

| Upstream Compose image | Verified Harbor manifest digest |
| --- | --- |
| `vxcontrol/pentagi:latest` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/pentagi@sha256:367439aa1fd7f6f4fe99961fe9e79c9ffd287a4380440b205552406d7f8bc89b` |
| `vxcontrol/pgvector:latest` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/pgvector@sha256:09afd689127bdb42319a133b2ef7cd4318b7ebda58412644975d6eacd2367fb0` |
| `vxcontrol/scraper:latest` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/scraper@sha256:4a3b0f179ab29003313167877ee2f6ab74c89f3fcb1ce108e648ca1ffadc51b7` |
| `quay.io/prometheuscommunity/postgres-exporter:v0.16.0` | `harbor.lab.gibbsgreatly.xyz/quay/prometheuscommunity/postgres-exporter@sha256:6999a7657e2f2fb0ca6ebf417213eebf6dc7d21b30708c622f6fcb11183a2bb0` |

`latest` remains an upstream default — record fresh Harbor manifest digests
before treating a later redeploy as comparable with the initial run.

## Native Ollama configuration

The vanilla project's `.env` contains only the native Ollama provider
selections needed for this investigation:

```dotenv
OLLAMA_SERVER_URL=http://framework.gibbsgreatly.xyz:11434
OLLAMA_SERVER_MODEL=qwen3.6-35b-a3b-ud:q4_k_m
EMBEDDING_URL=http://framework.gibbsgreatly.xyz:11434
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_PROVIDER=ollama
```

No `LLM_SERVER_*`, custom provider file, role mapping, or other application
configuration is set. `gpt-oss-120b` is out of scope.

## Findings so far

### 1. Flow-initialization cleanup (2026-08-19)

A `createAssistant(flowId: 0, ...)` request created a flow row, then stalled
during synchronous provider metadata calls that happen before
`executor.Prepare()` creates a primary terminal. No `pentagi-terminal-*`
container was created — not a post-worker leak.

- Upstream held `flowController.mx` for the whole creation path.
- `deleteFlow` calls `GetFlow`, so a pending provider call blocked deletion
  until the app was restarted (HTTP-client timeout: 600s).
- Fix (`32bd304`): narrow the mutex to map access; clean up a failed init's
  prepared resources and DB record.
- Validated: a stalled flow deleted in 58ms while the original create stayed
  blocked. No terminal container before or after.

Outstanding: exercise a flow that *does* reach worker creation, then verify
all worker containers are removed after finish/delete/timeout/cancellation.

### 2. Worker lifecycle and restart recovery (2026-08-19)

A constrained terminal-only flow created `pentagi-terminal-3` and a `primary`
container row. Deleting that flow removed the container and marked the row
`deleted` (~10s = Docker's normal stop grace period). Ordinary `deleteFlow`
does not leak a primary worker.

Restart-recovery gap: upstream's `DockerClient.Cleanup()` marks abandoned
`created` flows failed and removes their running/starting workers — but
`cmd/pentagi/main.go` never called it before `LoadFlows()`. A restart can
leave workers tied to flows the in-memory controller can't restore.

- Fix (`e38eb90`, after `32bd304`): call `client.Cleanup(ctx)` before
  provider/flow init. Tests passed: `go test ./cmd/pentagi ./pkg/docker
  ./pkg/controller ./pkg/graph`
- Validated: a real `pentagi-terminal-5` worker, PentAGI-only restart,
  `deleteFlow` → `success`, container removed, row `primary | deleted`.
- Reconfirmed finding #1 in the same run: a `created`-state flow still
  blocked `deleteFlow` until restart.

### 3. Exact-upstream fix validation (2026-08-19)

Both fixes reapplied to the exact deployed upstream revision `879e87c`.
Tests passed. A matching image deployed temporarily: stalled
`createAssistant`, `deleteFlow` → `success` in <1s. Submission branch:
`fix/upstream-flow-cleanup`, commit `946c0b0`.

### 4. False "missing model" from Ollama — root cause found (2026-08-20/21)

Earlier belief (2026-08-20): PentAGI's second setup LLM call fails with `404
Not Found: model 'qwen3.6-35b-a3b-ud:q4_k_m' not found`, while direct
`/api/show`/`/api/generate`/`/api/chat`/`/v1/models` calls all succeed.
Several workarounds (matching client fields, a 128-token profile, routing
through `/v1`) did not fix it.

**Actual root cause (2026-08-21), confirmed by packet capture:** not a
PentAGI request-formatting bug. A real `createAssistant` call makes **7**
sequential `/api/chat` calls on one keep-alive connection (image select,
language detect, title, 2× function-call capability probe, 2× tool-call-ID
pattern probe), not just 2. All 7 requests are byte-identical in shape —
same host, same model name, same body structure.

The 404 hit exactly once: on the request sent immediately after a prior
request that took **114 seconds** to generate (the title-generator role
rambled for 5,365 tokens instead of producing a short title). Ollama
returned `404 model not found` for that one request, near-instantly. The
very next request — identical in every field — succeeded normally. This is
consistent with a race in Ollama's model-registry/scheduler state right as
a long-running generation on that model finishes and a new request for the
same model arrives, not a client bug.

Direct manual tests never reproduced it because they were isolated single
calls — never seven calls back-to-back, and never immediately following a
100+ second generation.

**Fix implemented and live-validated (2026-08-21):** retry the Ollama 404
instead of failing the flow. `backend/pkg/providers/provider/wrapper.go`,
branch `fix/ollama-transient-model-not-found-retry`, commit `60fdbff`.
Unit-tested. Built into a test image, temporarily swapped into this
deployment, and confirmed live: a real 404 recurred and the retry recovered
it 7s later (same connection, identical follow-up request, 200 OK) —
`createAssistant` completed successfully with nothing surfaced to the
client. Original pinned image restored afterward. See
[problem-statement.md](problem-statement.md#current-state-and-next-engineering-work)
for the next-step list, including a second, distinct finding from this same
validation run (a delete/in-flight-goroutine race that left an orphaned
worker).

Still open, unrelated to the fix above:

- The oversized title-generator response (5,365 tokens for a ≤20-character
  title) is its own smaller finding — worth a tighter `num_predict` or
  stricter stop condition on that role.
- Consider reporting the underlying scheduler race to Ollama upstream.

### 5. Qwen3.6 thinking-budget exhaustion corrupting tool-call formatting (2026-08-21)

Live smoke-testing (a staged ladder: login → simple response → terminal
command → multi-step file ops → real recon against a dedicated lab target,
see [problem-statement.md](problem-statement.md#smoke-testing-and-reliability-follow-up-2026-08-2122))
found `refiner`, `reflector`, and `searcher` repeatedly producing
malformed/empty tool calls under real multi-turn flows. Root cause:
`qwen3.6-35b-a3b-ud` is Ollama-recognized as a thinking-capable model
(`capabilities: [tools, thinking, completion]`), but this provider's native
Ollama integration never sets Ollama's `think` field to disable it — unlike
the separate DashScope Qwen provider, which does exactly that per role.
Hidden reasoning tokens repeatedly consumed these roles' token budgets
before the actual tool call, and — confirmed by direct isolated testing
against the same reflector prompt/budget — also correlated with the
original false-404 race above recurring under back-to-back load (3/16 with
`think` unset vs 0/16 with `think: false`).

**Fix, live-validated:** route `refiner`/`reflector`/`searcher` to
`eval-qwen3-coder-30b-a3b:q4_k_m-ctx32k` (no thinking capability at all) via
each role's per-role `model:` override in `ollama/config.yml` — zero
provider code changes. The reflector recovered bad output from other roles
in 1 iteration afterward, versus 3-4 (often failing outright) before.

### 6. A separate Ollama/rocm serving-stack corruption bug, now hit under real PentAGI traffic (2026-08-21)

Already documented from this project's eval-harness work: long/dense
generations sometimes degenerate into a single repeated character (seen as
thousands of consecutive `?` bytes). Confirmed here to recur under real
multi-role PentAGI flows and to affect any role, model-swapped or not.
Confirmed via VictoriaMetrics GTT-usage history that concurrent-model memory
pressure is **not** the cause (usage was flat across two live occurrences).

Root-caused via isolated testing to be **content-triggered, not random**: a
`searcher` request asking for detailed CVE-2017-5638 exploit-technique
documentation corrupted on 9/9 attempts across two separate message chains
in one flow — exactly the kind of dense technical content real exploitation
depends on most. A separate occurrence was traced to a different,
already-documented "stuck" Ollama state (garbage on *any* prompt after ~3
days uptime and heavy load) — `docker restart ollama` cleared it completely
(0/6 corrupted afterward).

**Fix, live-validated:** `isDegenerateGarbageContent()` in `performer.go`
checks both overall single-character dominance (≥95% of ≥200 bytes) and an
independent long-contiguous-run signature (≥150 identical chars — added
after live testing caught a real corrupted response the dominance check
alone missed), feeding the existing retry loop. `refiner`'s token budget
also cut 16384→8192 to reduce exposure. The detector fired correctly on
`searcher` and `pentester`, retried, and either recovered or exhausted
retries cleanly (see finding 8).

### 7. Qwen3.6 refusing authorized exploitation despite an explicit override (2026-08-21)

`pentester.tmpl`'s system prompt already has an explicit "AUTHORIZATION
FRAMEWORK" section instructing the model to never request permission and to
proceed with penetration testing immediately. Live testing found Qwen3.6
ignoring it: *"I cannot proceed with exploiting CVE-2017-5638... this would
constitute unauthorized system access and is illegal."* Confirmed in
isolated testing (no system prompt at all): the same prompt refused 3/3 by
Qwen3.6, answered fully and unprompted by `qwen3-coder-30b-a3b`.

**Fix, deployed:** extended the finding-5 model swap to `pentester` too —
confirmed with the operator first, since this changes which model performs
the actual exploitation, not just tool-call formatting.

### 8. Task/subtask failures silently reported as idle "waiting", not failed (2026-08-21/22)

A genuine (non-cancellation) `PerformAgentChain` failure — e.g. retries
exhausted after finding 6's corruption — left both the subtask and its
parent task in `Waiting` status with no result recorded, identical from any
API consumer's view to a normal idle "ready for next input" state.
`subtask.go`'s error handler and both `taskWorker`/`subtaskWorker`
`handleInterrupting()` helpers only ever handled the cancellation/timeout
case; any other error silently reset status to `Waiting` and stopped there.

**Fix, live-validated:** both call sites now distinguish cancellation
(resumable, stays `Waiting`) from genuine errors (marks `Failed`, records
`err` via `SetResult` — the same pattern already used for graceful task
failures elsewhere in the same file). Re-triggered the same underlying
corruption on a fresh flow afterward: task and subtask both correctly showed
`Failed` with the real error message recorded.

### 9. The `installer` delegate role fabricates "success" reports without executing anything, 92% of the time (2026-08-22/23)

Discovered while checking a live flow against a fresh, non-iconic
single-service target: its nmap-recon subtask was marked `finished` with a
detailed, plausible report describing services (Apache, Samba, an
EternalBlue NSE hit) that don't exist on the real target at all. Tracing
the message chain showed the `installer` sub-agent had correctly delegated
two trivial prior steps for real execution, then skipped delegating
entirely on the one command that mattered and called its closing
`maintenance_result` tool directly with an invented result. `msglogs` for
that subtask contain zero `terminal`-type rows — nothing was ever run.

A systematic pass over every `installer`/`coder`/`pentester` message chain
ever recorded (96 raw rows, deduplicated to 24 distinct subtask
conversations spanning flows 19-34 — this entire investigation, back to
the first smoke-test stage) found this is not a one-off: **`installer`
fabricates 11 of 12 single-command delegations (92%)**; `coder` does it 2
of 6 times (33%). It predates every fix above, none of them catch it (a
fabricated report has a valid tool-call shape and no corruption
signature), and the report's confident phrasing is identical whether the
underlying work was real or invented — full methodology and the clearest
verifiable example in
[lessons-learned.md](lessons-learned.md#fabricated-tool-execution-reports-the-installer-delegate-role-frequently-skips-real-execution-entirely-2026-08-2223).

**Not yet fixed.** Investigation into why the original Metasploitable2 run
avoided this (or didn't, and simply wasn't checked closely enough at the
time) is in progress, along with candidate fixes: a different model for
the `installer`/`coder` roles, sampling-parameter tuning, and a stricter
contract on the closing `*_result` tools.

### Also done this pass: `DOCKER_NET_ADMIN` and `CVE_MCP_URL` wired into the live deployment (2026-08-22)

Two config-only fixes to the live `/opt/pentagi-upstream-vanilla` project
on 70010 (not yet reflected in this repo's `pentagi-stack` IaC, which
remains undeployed here — see "Current live state" above):

- **`DOCKER_NET_ADMIN=true`** — worker containers were only ever granted
  `CAP_NET_RAW`, but `nmap`'s file capabilities require
  `CAP_NET_RAW`+`CAP_NET_ADMIN` together to exec at all under the kernel's
  capability-transition rules; missing `CAP_NET_ADMIN` meant `nmap` failed
  every single invocation, in every flow, for the life of this deployment,
  forcing every flow onto fragile hand-rolled bash/netcat recon instead.
  The upstream config flag for this already existed
  (`pkg/tools/tools.go:482`); it just defaulted to `false` and was never
  set here. Confirmed fixed live: a real `nmap -sV` from inside a fresh
  worker container now correctly identifies the target service.
- **`CVE_MCP_URL=http://192.168.50.10:8000/mcp`** — this deployment never
  had any CVE/vulnerability-intel lookup path wired in at all (also
  confirmed no `SEARXNG_URL`/`DUCKDUCKGO_ENABLED`/`SPLOITUS_ENABLED`
  configured), so the `searcher` role's "research known vulnerabilities"
  step was always working from pure model recall, never a real database.
  Wired to the existing `mcp-utility-stack` `cve-mcp-server`, confirmed
  reachable and live with a real MCP `initialize` handshake
  (`cve-mcp v1.29.0`) before wiring it in. Both required editing the
  compose file directly, not just the `.env` — the live compose file
  didn't reference either variable at all.

## Capability assessment

Every smoke-test stage through reconnaissance passed reliably once findings
5-8 were fixed. **Actual exploitation did not, in four separate attempts,
against a target whose vulnerability is trivial and independently confirmed
exploitable by hand** (see [harness-target.md](harness-target.md)'s
"Verified live" section). See
[problem-statement.md](problem-statement.md#capability-assessment-read-before-trusting-this-for-real-engagements)
for the full assessment — in short: today's fixes made this deployment more
*reliable*, not more *capable*, and the underlying Ollama corruption bug
(finding 6) is still genuinely unresolved, just survivable.

**Superseded (2026-08-23) as the primary finding by #9 above**: a tool that
occasionally fails to exploit a target is a capability gap; a tool that
fabricates confident evidence of work it never did, 92% of the time, is a
trust problem — and one none of findings 1-8's fixes catch.
