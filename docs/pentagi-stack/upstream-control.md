# Vanilla-upstream PentAGI companion (on `pentagi-stack`'s LXC)

Status (2026-08-21): the vanilla-upstream project is the **active** project.
The patched `pentagi-stack` project is **not currently deployed** — see
[Current live state](#current-live-state) below. The worker-leak
investigation itself is **closed** — both real leak paths found here are
fixed and live-validated; see
[problem-statement.md](problem-statement.md#restart-cleanup-test--complete-2026-08-21).

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
investigation finished; it hasn't been yet.

Confirmed live on 70010 (2026-08-21):

- `/opt/pentagi-upstream-vanilla` exists and is the running project.
- `/opt/pentagi-stack` does not exist. No `pentagi-stack_*` Docker volumes
  exist either.
- No backup exists for VMID 70010 (checked PBS, `storage-backup`,
  `gazaar-backup`, `nas-backup`) and no ZFS snapshots exist for its rootfs
  or `/var/lib/docker` datasets.

**Consequence:** the patched project's prior runtime state (flow/task
history, DB rows) is gone, not just hidden. Redeploying `deploy-pentagi-stack`
restores the code/config cleanly but starts with empty application state.

Restoring the patched project is deliberately **on hold** — the operator
wants the Ollama investigation below to continue on the current vanilla
deployment first.

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
