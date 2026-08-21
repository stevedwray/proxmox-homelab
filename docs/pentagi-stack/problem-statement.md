# PentAGI upstream lifecycle and Ollama compatibility problem statement

Status (2026-08-21): **objective closed.** Both real worker-leak paths found
during this investigation are fixed and live-validated — see "Restart-cleanup
test — complete" below.

## Objective

Establish whether unmodified upstream PentAGI leaks its per-flow Docker worker
containers, and produce the smallest upstream-safe fixes. Testing is performed
on the vanilla-upstream companion project deployed on `pentagi-stack`'s own
LXC (CT 70010, `192.168.70.10`) — see
[upstream-control.md](upstream-control.md) for the deployment model.

## Confirmed lifecycle defects

### 1. A stalled flow initialization blocks its own deletion

`createAssistant(flowId: 0, ...)` persists a `flows` row before it completes
provider setup. In upstream revision `879e87c`, `flowController.mx` was held
through that blocking initialization path. `deleteFlow` calls `GetFlow`, so it
waited on the same mutex until the provider request ended (normally governed by
the 600-second HTTP timeout) or the service was restarted.

This is not a worker-container leak in the reproduction: initialization stopped
before `executor.Prepare()`, so no `pentagi-terminal-*` container existed.
Nevertheless it left an unusable `created` flow and made cleanup appear stuck.

**Validated fix:** narrow the mutex to accesses to the in-memory flow map. The
exact-upstream test image deleted a deliberately stalled flow in under one
second (a subsequent controlled run measured 8 ms), while the create request
remained pending. The flow was soft-deleted and no worker container was
created.

### 2. Restart cleanup existed but was not invoked

Upstream implements `DockerClient.Cleanup()`: it marks abandoned `created`
flows failed and removes running/starting worker containers for states that
cannot safely be resumed. `cmd/pentagi/main.go` did not call it before
`LoadFlows()`. A service restart could therefore leave an orphaned worker in
Docker and a flow state that the controller did not restore.

**Validated code change:** invoke `client.Cleanup(ctx)` during startup before
provider and flow restoration. Focused Go tests passed. Full live restart
validation with a newly created worker remains blocked by the provider issue
below.

## Provider blocker encountered during live worker testing — resolved

The vanilla-upstream companion is configured for Framework Ollama:

```dotenv
OLLAMA_SERVER_URL=http://framework.gibbsgreatly.xyz:11434
OLLAMA_SERVER_MODEL=qwen3.6-35b-a3b-ud:q4_k_m
EMBEDDING_MODEL=nomic-embed-text
```

The model is visible in `/api/tags`, loaded in `/api/ps`, and succeeds when
called directly through `/api/show`, `/api/generate`, `/api/chat`, and
`/v1/models`.

A real `createAssistant` call intermittently failed one of its setup LLM
calls with:

```text
404 Not Found: model 'qwen3.6-35b-a3b-ud:q4_k_m' not found
```

**Root cause, confirmed by packet capture (2026-08-21):** not a request bug.
`createAssistant` makes 7 sequential `/api/chat` calls on one connection, not
2. All 7 are identically shaped. The 404 landed exactly once — on the request
sent right after a prior request that took 114 seconds to generate (a
runaway 5,365-token response from the title-generator role). The next,
identical request succeeded immediately after. This matches a transient race
in Ollama's model scheduler around a long generation finishing, not a
PentAGI/langchaingo client defect. Full detail:
[upstream-control.md](upstream-control.md#4-false-missing-model-from-ollama--root-cause-found-2026-08-2021).

Table below is the (now-explained) trail of workaround attempts before the
capture — none of them addressed the real cause, which is why none worked:

| Attempt | Result |
| --- | --- |
| Direct Ollama metadata, generate, and chat requests | Succeeded with the configured model. |
| Matching the bundled client's empty `format` field, sampling settings, and 128-token limit | Direct Ollama call still succeeded; not the cause. |
| Temporary 128-token PentAGI Ollama role profile | Failure became faster but still returned the same false 404. |
| PentAGI `custom` provider through Ollama's OpenAI-compatible `/v1` API | Same false 404 during setup. |
| Restart PentAGI after each failed/stalled attempt | Cleared the in-flight request; no worker remained. |
| Delete only failed/stalled test flows | Succeeded immediately; all test flows were soft-deleted. |

During this work, upstream Compose also auto-created missing
`example.custom.provider.yml` and `example.ollama.provider.yml` bind-mount
targets as directories. The deployment must ensure these targets exist as
regular files before Compose starts — a separate, unrelated fix.

## Current state and next engineering work

No active test flows or `pentagi-terminal-*` workers remain. The two
lifecycle fixes are source-tested and the stalled-delete fix is live-tested.

**Fix implemented and live-validated (2026-08-21):**
`classifyRetryableError`/`isOllamaTransientModelNotFoundError` in
`backend/pkg/providers/provider/wrapper.go` — retries a 404 "model not
found" from the Ollama provider specifically (2s delay, reuses the existing
10-attempt cap shared with the 429/too-many-requests retry), instead of
failing the flow. Unit-tested; `go test ./cmd/pentagi ./pkg/docker
./pkg/controller ./pkg/graph ./pkg/providers/...` all pass. Branch
`fix/ollama-transient-model-not-found-retry`, commit `60fdbff`, on top of
`e38eb90`/`32bd304`.

Live validation: built a test image, temporarily swapped it into the
vanilla-upstream companion, ran `createAssistant` twice with tcpdump
capturing traffic. Run 2 hit the race again — a genuine 404 at 22:58:14,
same shape as before — and the retry fired: an identical follow-up request
succeeded 7 seconds later (2s configured delay + Ollama's own reload time).
The flow completed end-to-end with **no error surfaced to the client** in
either run. Full detail:
[upstream-control.md](upstream-control.md#4-false-missing-model-from-ollama--root-cause-found-2026-08-2021).

**Second finding, fixed and live-validated the same day:** a soft-`deleteFlow`
call against a flow whose `createAssistant` init goroutine was still in
flight (flow 12, pre-dating this fix) left a real orphaned
`pentagi-terminal-12` worker running — the goroutine wasn't cancelled by the
delete, so it completed independently and created a primary worker *after*
the flow was already marked deleted. Root cause: a flow only gets added to
the controller's live map once its (potentially multi-minute) provider setup
already succeeded, so `deleteFlow`'s `GetFlow` lookup can't see it while
setup is still running — the existing `32bd304` mutex fix made `deleteFlow`
return fast, but never cancelled the in-flight init.

**Fix:** `backend/pkg/controller/{flow,flows}.go` +
`pkg/graph/schema.resolvers.go`, branch
`fix/delete-flow-in-flight-init-race`, commit `8322b44`, on top of the
Ollama retry fix. Adds a `pending` registry (flowID → cancel func) populated
as soon as the flow's DB row/ID exists but before the slow setup runs;
`deleteFlow` now cancels it when `GetFlow` reports not-found. Focused tests
added; full suite passes.

Live-validated by deliberately racing it: triggered `createAssistant`, grabbed
the new flow's ID within ~1s, called `deleteFlow` while it was still
`status: created`. Result: the setup call failed with `context canceled`,
the client got a clean GraphQL error instead of a hang, **zero**
`pentagi-terminal-*` containers were created, and the flow's `containers`
row count was 0. Confirmed this exact scenario (flow 12) is no longer
reproducible. Known remaining edge case: doesn't close the much smaller
window between the flow's own long-lived context being created and
`initialized = true` inside `NewFlowWorker`, since `executor.Prepare()`
there runs on a separate context — not Ollama-bound, so far lower risk.

## Restart-cleanup test — complete (2026-08-21)

The original objective's last open item: does a real worker survive a
PentAGI restart cleanly, without leaking? Ran on the consolidated
fix image (both fixes above).

Deliberately raced a restart against a flow's own worker creation:
triggered `createAssistant`, polled `docker ps` for `pentagi-terminal-*`
to appear, restarted `pentagi` the instant it did. The race landed even
tighter than planned — flow 17 had just reached `waiting` and its
container (`pentagi-terminal-17`) was about a second old, not yet settled,
when the restart hit.

Result: PentAGI caught `SIGTERM` gracefully; on the new process's startup,
`DockerClient.Cleanup()` found the container, removed it
(`"removing container and associated resources"` → `"container removed"`),
and marked the flow `failed`. Final state: **zero** `pentagi-terminal-*`
containers, container row `deleted`. No manual intervention needed.

This confirms the `e38eb90` startup-`Cleanup()` fix handles a real worker
container across a restart with no leak, even in a tighter race than the
original test plan called for.

**Original objective status: closed.** Unmodified upstream leaks a worker
under two conditions, both now fixed and live-validated: (1) a
`deleteFlow` racing an in-flight `createAssistant` init (`8322b44`), and
(2) a restart landing before `Cleanup()` ran at startup — upstream already
had `Cleanup()`, it just was never called (`e38eb90`, now confirmed live).

Remaining, smaller items — none blocking:

1. Tighten the title-generator role's `num_predict`/stop condition — 5,365
   tokens for a ≤20-character title is what created the timing window the
   Ollama race needs.
2. Consider reporting the underlying Ollama scheduler race upstream.

No DB cleanup is actually needed: every investigation-era flow row except
`17` already has `deleted_at` set (`deleteFlow` was called on each). Their
`status` column just still shows whatever it was at the moment of deletion
(`created`/`waiting`) — `deleteFlow` only ever sets `deleted_at`, it never
rewrites `status`, so that field is a frozen snapshot, not a live indicator.
Flow `17` (from the restart-cleanup test) has no `deleted_at` because it was
never user-deleted — `Cleanup()` marked it `failed` instead, its correct,
documented behavior for a flow that can't be resumed after a restart. Any
flow-list query filtering on `deleted_at IS NULL` (the normal soft-delete
pattern) already treats all of this correctly with zero code changes needed.
