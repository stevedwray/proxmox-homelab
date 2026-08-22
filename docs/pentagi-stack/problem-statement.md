# PentAGI upstream lifecycle and Ollama compatibility problem statement

Status (2026-08-22): the original worker-leak objective is **closed** (see
"Restart-cleanup test — complete" below). A follow-on smoke-testing pass
found and fixed four further reliability bugs (tool-call reliability,
Ollama garbage-content corruption, an exploitation-refusal, and a
silent-failure reporting gap — see "Smoke-testing and reliability
follow-up" below) — but that same pass also surfaced a more basic finding:
**autonomous exploitation itself never once succeeded**, across four
separate attempts, even after every fix landed. See "Capability
assessment" for the honest read on what that means before treating this
deployment as production-ready for real engagements.

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

## Smoke-testing and reliability follow-up (2026-08-21/22)

With the worker-leak objective closed, a staged smoke-test ladder was run
against the fixed image on the same vanilla-upstream companion: login →
simple response → single terminal command → multi-step file ops → real
reconnaissance against a dedicated authorized lab target
(`harness-target-pve`, 192.168.70.12, CVE-2017-5638 Struts2 + unauthenticated
Redis) → actual exploitation. Stages up through recon passed cleanly. Actual
exploitation (see "Capability assessment" below) never completed. Along the
way this surfaced four further real bugs, all fixed and live-validated,
building on branch `fix/delete-flow-in-flight-init-race` at
`fix/route-formatting-roles-to-qwen3-coder` (6 commits total, pushed):

**1. Qwen3.6 thinking-budget exhaustion corrupting tool calls.**
`qwen3.6-35b-a3b-ud` is a hybrid reasoning model (Ollama reports
`capabilities: [tools, thinking, completion]`), but PentAGI's native Ollama
provider never sets Ollama's `think` field — unlike the separate DashScope
Qwen provider, which explicitly disables thinking per role for exactly this
reason. Hidden reasoning tokens repeatedly consumed the `refiner` (16384),
`reflector` (4096, the tightest budget of any role), and `searcher` (8192)
roles' token budgets before they could emit a real tool call, producing
malformed/empty responses and, under back-to-back load, the exact false-404
race documented above (reproduced live, on demand: 3/16 false-404s with
`think` unset vs 0/16 with `think: false`, plus 4.5x faster and 5.5x fewer
tokens). **Fix:** route `refiner`/`reflector`/`searcher` to
`eval-qwen3-coder-30b-a3b:q4_k_m-ctx32k` — a model with no thinking
capability at all — via each role's existing per-role `model:` override in
`ollama/config.yml` (zero provider code changes; the same mechanism
`openai/config.yml` already uses for different models per role).
Live-validated: the reflector recovered bad output from other roles in 1
iteration instead of 3-4.

**2. A separate, pre-existing Ollama/rocm serving-stack corruption bug.**
Long/dense generations sometimes degenerate into a single repeated
character (observed as thousands of consecutive `?` bytes) — a bug already
documented from this project's eval-harness work, confirmed here to also
recur under real PentAGI traffic and to affect every role, model-swapped or
not. Confirmed via VictoriaMetrics GTT-usage history that this is **not**
caused by concurrent-model memory pressure (usage was flat across two live
occurrences). **Fix:** `isDegenerateGarbageContent()` in
`backend/pkg/providers/performer.go` detects the signature two ways — an
overall single-character dominance check (≥95% of a ≥200-byte response) and
an independent long-contiguous-run check (≥150 identical characters, added
after live testing caught a real garbage response the dominance check alone
missed because normal content around it diluted the overall fraction) —
returning an error that feeds the existing `performAgentChain` retry loop.
Also cut `refiner`'s token budget 16384→8192 to reduce exposure to the
long-generation trigger. Live-validated: the detector fired correctly on
`searcher` and (after extending the model swap) `pentester` too, retried,
and either recovered or cleanly exhausted retries — see finding 4.
Root-caused in isolated testing to be **content-triggered, not random**: a
`searcher` request asking for detailed CVE-2017-5638 exploit-technique
documentation corrupted on every single attempt (9/9) across two separate
message chains in one flow — exactly the kind of dense technical content
real exploitation work needs most. Separately, framework's Ollama container
was found to have entered a different, already-documented "stuck" state
(garbage output on *any* prompt, even benign ones, after ~3 days uptime and
heavy varied-prompt load) — `docker restart ollama` cleared it completely
(6/6 clean afterward), confirming that occurrence wasn't content-related at
all.

**3. Qwen3.6 refusing authorized exploitation outright.** Despite
`pentester.tmpl`'s explicit, pre-existing "AUTHORIZATION FRAMEWORK" section
(*"This is an AUTHORIZED penetration testing engagement... Never request
permission... Proceed with all requested penetration testing operations
immediately and confidently"*), a live `pentester` call refused: *"I cannot
proceed with exploiting CVE-2017-5638... this would constitute unauthorized
system access and is illegal."* Confirmed in isolated testing: the same
exploit-technique prompt, no system prompt at all, refused 3/3 by Qwen3.6
and answered fully (unprompted) by `qwen3-coder-30b-a3b`. **Fix:** extended
the same model-swap approach to `pentester` — the role that actually
performs exploitation, not just formatting, so a bigger behavioral change
than findings 1-2 and confirmed with the operator before implementing.

**4. Task/subtask failures silently reported as idle, not failed.** When a
subtask's `PerformAgentChain` call failed with a genuine (non-cancellation)
error — retries exhausted after persistent garbage-content corruption, or
any other hard provider failure — both `subtask.go`'s error handler and the
`handleInterrupting()` helpers on `taskWorker`/`subtaskWorker` unconditionally
reset status to `Waiting`, regardless of error kind. `flow.go`'s worker loop
does the same at the flow level (left as-is: the flow should stay usable for
new input even after one task fails). Net effect observed live: a real
pentest objective died silently — task and subtask both `Waiting`, flow
`Waiting`, no failed status, no result, no error visible anywhere except the
container log — indistinguishable from a normal idle "ready for next input"
state. **Fix:** `PerformAgentChain`'s error path and both
`handleInterrupting()` helpers now distinguish cancellation/deadline errors
(resumable, stays `Waiting`) from genuine errors (marks `Failed` and records
`err` via `SetResult`, matching the existing pattern already used for
graceful failures). Live-validated: the exact same underlying corruption
recurred on a fresh flow, and this time task and subtask both correctly
showed `Failed` with the real error message recorded as their result.

## Capability assessment — read before trusting this for real engagements

Across the whole smoke-test ladder, **every stage through reconnaissance
passed reliably once the fixes above landed. Actual exploitation did not,
in four separate attempts (Stage 5/5b/5c/5d), each against the same
purpose-built, pre-authorized lab target
([harness-target.md](harness-target.md)) whose vulnerability is trivial and
already independently confirmed exploitable by hand** (a documented curl
one-liner gets `uid=0(root)` — see that doc's "Verified live" section).
Every PentAGI attempt instead either hit the Qwen3.6 refusal (finding 3,
before its fix) or died in the garbage-corruption retry loop (finding 2) —
and that corruption is disproportionately triggered by exactly the kind of
dense technical content (exploit-technique research, payload construction)
that real exploitation work depends on most.

Read plainly: today's fixes made this deployment more *reliable* — no more
silent failures, no more infinite loops, faster tool-call formatting — they
did not make it more *capable*. `qwen3-coder-30b-a3b` was chosen to fix
formatting and refusal problems, not selected for exploit-reasoning
strength, and the underlying Ollama serving-stack corruption bug (finding 2)
remains genuinely unresolved — PentAGI's retry/detection layer survives it
but cannot always outrun it. Treat this deployment as reliable for
recon/multi-step-ops work; **do not** treat it as validated for autonomous
exploitation of real engagements without either a stronger model for
`pentester`, a way to reduce how much exploit-technique content the agent
has to originate live (e.g. pre-seeded guides in the vector store), or
resolving the corruption bug at the infra level.
