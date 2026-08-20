# PentAGI upstream lifecycle and Ollama compatibility problem statement

## Objective

Establish whether unmodified upstream PentAGI leaks its per-flow Docker worker
containers, and produce the smallest upstream-safe fixes. Testing is performed
on the disposable upstream control in production CT 70010 (`192.168.70.10`).

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

## Provider blocker encountered during live worker testing

The control is configured for Framework Ollama:

```dotenv
OLLAMA_SERVER_URL=http://framework.gibbsgreatly.xyz:11434
OLLAMA_SERVER_MODEL=qwen3.6-35b-a3b-ud:q4_k_m
EMBEDDING_MODEL=nomic-embed-text
```

The model is visible in `/api/tags`, loaded in `/api/ps`, and succeeds when
called directly through all of:

- `/api/show`;
- `/api/generate`;
- `/api/chat`; and
- `/v1/models`.

However, a real PentAGI `createAssistant` call consistently creates a flow row
then fails during the second setup LLM call (`failed to get language`) with:

```text
404 Not Found: model 'qwen3.6-35b-a3b-ud:q4_k_m' not found
```

The first setup call (Docker-image selection) completes, which makes this more
than a simple connectivity, DNS, or missing-model issue. A retry can instead
remain pending before worker preparation. Both outcomes occur before a primary
worker exists.

## Fixes and workarounds attempted

| Attempt | Result |
| --- | --- |
| Direct Ollama metadata, generate, and chat requests | Succeeded with the configured model. |
| Matching the bundled client's empty `format` field, sampling settings, and 128-token limit | Direct Ollama call still succeeded; not the cause. |
| Temporary 128-token PentAGI Ollama role profile | Failure became faster but still returned the same false 404. |
| PentAGI `custom` provider through Ollama's OpenAI-compatible `/v1` API | Same false 404 during the first setup LLM call. |
| Restart PentAGI after each failed/stalled attempt | Cleared the in-flight request; no worker remained. |
| Delete only failed/stalled test flows | Succeeded immediately; all test flows were soft-deleted. |

During this work, upstream Compose also auto-created missing
`example.custom.provider.yml` and `example.ollama.provider.yml` bind-mount
targets as directories. The deployment must ensure these targets exist as
regular files before Compose starts; this avoids a broken configuration mount,
but it does not resolve the false model-not-found response.

## Current state and next engineering work

CT 70010 has no active test flows or `pentagi-terminal-*` workers, and normal
native-Ollama provider selection has been restored. The cleanup fixes are
source-tested and the stalled-delete fix is live-tested. Restart cleanup of a
real worker remains unvalidated only because PentAGI cannot complete provider
initialization with this Ollama runtime.

The next task is to recreate the exact upstream source worktree and build a
focused local reproduction using PentAGI's pinned `langchaingo`
`v0.1.14-update.5` client. Capture the two consecutive requests it makes to
Ollama, compare them with the successful direct requests, and patch or upgrade
the client only once the differing request field is identified. Rebuild the
exact-upstream cleanup test image, validate one real worker, then execute the
restart-cleanup test.
