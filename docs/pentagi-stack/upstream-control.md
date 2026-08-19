# Upstream PentAGI control environment

Status: deployed and healthy on `pve` as of 2026-08-19. This is the control
plane for comparing the locally patched PentAGI deployment with an unmodified
upstream deployment. It is an experimental environment, not a user-facing
service and not a replacement for `pentagi-stack`.

## Purpose and comparison boundary

`pentagi-upstream-control` establishes the upstream baseline for the controlled
model and behaviour tests in [model-ab-test-plan.md](./model-ab-test-plan.md).
It must be compared with the patched stack using the same fixed prompt, target,
model endpoint, and test stage. A result is not attributable to the PentAGI
code/configuration if any of those other variables differ.

The control intentionally has none of the patched stack's additions:

- no private `pentagi-fixed` image;
- no custom role or provider YAML;
- no harness-specific browser/tool guardrails;
- no execution-monitor tuning, search integration, CVE-MCP, GVM bridge, or
  shared Docker network;
- no shared database, named volume, or Docker daemon.

It does use the lab's normal base-LXC operations roles (metrics, logging, CA
trust, Docker) and Harbor proxy cache. Those are host-operating requirements,
not PentAGI application customisation.

## Deployed topology

| Item | Value |
| --- | --- |
| Proxmox node | `pve` |
| LXC | `70013` (`pentagi-upstream-control`) |
| Address / zone | `192.168.70.13/24`, `pentest_seg` (VLAN 70) |
| Resources | 2 vCPU, 8 GiB RAM, 2 GiB swap, 30 GiB rootfs, dedicated 50 GiB `/var/lib/docker` mount |
| Compose directory | `/opt/pentagi-upstream-control` |
| Listener | `https://127.0.0.1:8443` inside the LXC only; no Traefik route or public DNS record |
| Supporting services | upstream `pgvector`, `scraper`, and `pgexporter` services |

The upstream Compose names (`pentagi`, `pgvector`, `scraper`, and
`pgexporter`) are safe because this is a separate LXC. Do not co-locate this
Compose project with `pentagi-stack`: its fixed container and network names
would collide.

## Upstream provenance and image handling

The deployed `docker-compose.yml` is byte-for-byte the file at upstream
PentAGI revision `879e87c2c2688c4a95eac9c1aaf3cd6f6123ebe3`.
Its verified SHA-256 is:

```
8dd61ae1a92096bea2477426043751f19471c844a5ed1094d957549056039063
```

All images are pulled through Harbor, never directly from a public registry.
The deployment pulls the Docker Hub/Quay proxy-cache references below, then
tags those exact local images with the names the unmodified upstream Compose
expects. This retains an unmodified Compose file while complying with the
lab's registry-routing policy.

| Upstream Compose image | Verified Harbor manifest digest |
| --- | --- |
| `vxcontrol/pentagi:latest` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/pentagi@sha256:367439aa1fd7f6f4fe99961fe9e79c9ffd287a4380440b205552406d7f8bc89b` |
| `vxcontrol/pgvector:latest` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/pgvector@sha256:09afd689127bdb42319a133b2ef7cd4318b7ebda58412644975d6eacd2367fb0` |
| `vxcontrol/scraper:latest` | `harbor.lab.gibbsgreatly.xyz/dockerhub/vxcontrol/scraper@sha256:4a3b0f179ab29003313167877ee2f6ab74c89f3fcb1ce108e648ca1ffadc51b7` |
| `quay.io/prometheuscommunity/postgres-exporter:v0.16.0` | `harbor.lab.gibbsgreatly.xyz/quay/prometheuscommunity/postgres-exporter@sha256:6999a7657e2f2fb0ca6ebf417213eebf6dc7d21b30708c622f6fcb11183a2bb0` |

`latest` remains an upstream default, so record fresh Harbor manifest digests
before treating a later redeploy as comparable with the initial control run.

## Native Ollama configuration

The control's `.env` contains only the native Ollama provider selections
needed for this experiment:

```dotenv
OLLAMA_SERVER_URL=http://framework.gibbsgreatly.xyz:11434
OLLAMA_SERVER_MODEL=qwen3.6-35b-a3b-ud:q4_k_m
EMBEDDING_URL=http://framework.gibbsgreatly.xyz:11434
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_PROVIDER=ollama
```

No `LLM_SERVER_*`, custom provider file, role mapping, or other application
configuration is set. `gpt-oss-120b` is out of scope for this environment.

## Verification and operations

Initial deployment validation on 2026-08-19 confirmed:

- `pentagi`, `scraper`, and `pgexporter` were running; `pgvector` was healthy;
- `https://127.0.0.1:8443/` returned HTTP `200` from inside the LXC;
- the deployed Compose SHA-256 matched the upstream object above exactly;
- the control LXC could see both `qwen3.6-35b-a3b-ud:q4_k_m` and
  `nomic-embed-text` from Framework Ollama's `/api/tags` endpoint.

For an approved production reconciliation, use the normal PVE wrapper:

```bash
TASK_APPROVAL=pentagi-v210-upgrade \
  ./with-secrets-prod scripts/provision.sh \
  --target-env pve --stack pentagi-upstream-control
```

Treat the control as disposable experimental state. Do not point it at targets
outside the explicit scope in the A/B plan, and do not use it to bypass the
patched stack's safety controls in an otherwise uncontrolled run.

## Flow-initialization cleanup finding (2026-08-19)

The clean upstream deployment was reproduced on CT 70010 with the native
Ollama configuration above. A `createAssistant(flowId: 0, ...)` request
created a flow row, then stalled during the synchronous provider metadata
calls that happen before `executor.Prepare()` creates a primary terminal.
Consequently, this reproduction created **no** `pentagi-terminal-*` container;
it is not evidence of a post-worker container leak.

Upstream held `flowController.mx` for the whole creation path. Since
`deleteFlow` calls `GetFlow`, a pending provider call prevented deletion of
the newly created flow until the application was restarted. The configured
HTTP-client timeout is 600 seconds, so this can present as a long-running
cleanup failure.

The local fork fix `32bd304` narrows the controller mutex to map access and
cleans up a failed initialization's prepared resources and database record.
Its focused Go tests passed. A temporary image built from that commit was
used only to test the stalled-flow path: deleting the pending flow returned
`success` in 58 ms while the original create request remained blocked. No
terminal container existed before or after that deletion. CT 70010 was then
restored to the pinned upstream image, and the temporary registry login and
test session files were removed.

The outstanding investigation is therefore the distinct reported issue:
exercise a flow that successfully reaches worker creation, then verify that
all worker containers are removed after finish, delete, timeout, and request
cancellation.

## Worker lifecycle and restart recovery finding (2026-08-19)

A constrained terminal-only flow on the unmodified upstream control created
`pentagi-terminal-3` and a corresponding `primary` container row. Deleting
that flow removed the Docker container and marked its row `deleted`; the
approximately ten-second deletion time was Docker's normal stop grace period.
Thus the ordinary in-process `deleteFlow` path does not leak a primary worker.

Source inspection then identified the restart-recovery gap. Upstream already
has `DockerClient.Cleanup()`, which marks abandoned `created` flows failed and
removes their running or starting worker containers. However,
`cmd/pentagi/main.go` created the Docker client and immediately restored active
flows with `LoadFlows()` without ever calling `Cleanup()`. A restart can
therefore leave workers associated with flows that cannot be restored in the
in-memory controller.

The local fork now calls `client.Cleanup(ctx)` before provider and flow
initialization (commit `e38eb90`, following the earlier lock/failed-init fix
`32bd304`). Focused tests passed:

```text
go test ./cmd/pentagi ./pkg/docker ./pkg/controller ./pkg/graph
```

The restart/delete reproduction was subsequently completed with a short-lived
operator-created API token (not retained). A terminal-only flow created the
real `pentagi-terminal-5` worker. After a PentAGI-only restart, `deleteFlow`
returned `success`, removed the Docker container, and left its database row as
`primary | deleted`. Thus a `waiting` flow restored by `LoadFlows()` cleans up
correctly on explicit deletion.

The same run reconfirmed the distinct stalled-creation failure: a flow was
persisted in `created` state while the upstream controller held its global
mutex during provider setup; `deleteFlow` timed out until PentAGI was
restarted. The local fork fix `32bd304` addresses that lock and failed-init
cleanup path. The startup-recovery patch `e38eb90` remains the defensive fix
for workers belonging to flow states that cannot be restored after a restart.

CT 70010 was restored to its unchanged upstream model configuration; it has
no `pentagi-terminal-*` container, temporary provider config, test session,
or locally stored API token.
