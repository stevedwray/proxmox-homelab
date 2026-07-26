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
   for one agent session, rather than as network services.
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
Local agent / IDE (disposable worktree)
  ├─ GitHub MCP, read-only, local stdio
  └─ Filesystem MCP, one worktree only, local stdio

                         later, private internal connection
                                      │
                                      ▼
                         mcp-stack (automation_seg)
                    ┌─────────────────────────────────┐
                    │ Proxmox discovery adapter        │
                    │ MikroTik discovery adapter       │
                    │ NetBox / metrics / logs adapters │
                    │ audit and request logs           │
                    └─────────────────────────────────┘
                       │                   │
              narrowly allowed        narrowly allowed
                       │                   │
                  Proxmox API       RouterOS REST / SSH

Mutation request → disposable repo runner → existing approved script/wrapper
```

### Placement and network model

The permanent shared service, if warranted, is a new `mcp-stack` workload in a
new **automation/control-plane segment** (tentative name: `automation_seg`).
The segment must be created using the same explicit SDN/MikroTik policy model
as the existing zones; this is a network structural change and therefore needs
the full validation tier applicable at the time.

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
| Shared discovery | `mcp-stack` in `automation_seg` | Per-service read-only accounts/tokens; typed inspection only |
| Mutation execution | Short-lived, task-specific repo runner | Existing `with-secrets` or `with-secrets-prod*`; operator approval for production |

The shared discovery tier must not offer arbitrary shell, arbitrary HTTP fetch,
raw vendor API, guest command execution, or router command tools. When an
upstream server cannot make that exclusion credible, use it only for a local
lab evaluation or replace it with a small repository-owned façade.

## Candidate server assessment

| System | Candidate | Role and decision | Required constraints |
| --- | --- | --- | --- |
| GitHub | [github/github-mcp-server](https://github.com/github/github-mcp-server) | **First local evaluation.** Official server for repository, issue, PR, and check inspection. | Local `stdio`; repository-scoped read-only token; explicit tool/toolset allowlist; enable read-only mode. |
| Filesystem | [modelcontextprotocol/server-filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) | **Optional local evaluation.** It may be redundant for agents with native workspace access. | Local `stdio`; exactly one disposable task worktree; never the home directory, shared repo root, credential directories, or production mounts. |
| Proxmox | [GethosTheWalrus/proxmox-mcp](https://github.com/GethosTheWalrus/proxmox-mcp) | **Lab evaluation only.** Its Proxmox coverage is useful for discovery but its broad management surface is unsuitable as the trusted production layer. | Dedicated read-only API token; `pve-test-vm` first; TLS verification enabled; no `proxmox_api_raw`, guest execution, storage download/upload, or lifecycle tools. |
| MikroTik | [AliKarami/MikroMCP](https://github.com/AliKarami/MikroMCP) | **Lab evaluation only.** It has valuable typed diagnostics, but its 100+ tools include configuration, SSH, and router-originated network actions. | Dedicated RouterOS read-only user; API-only where possible; prohibit writes, `run_command`, `fetch_url`, package updates, file upload, and RouterOS container tools. |
| MikroTik | [jeff-nasseri/mikrotik-mcp](https://github.com/jeff-nasseri/mikrotik-mcp) | **Not selected.** Its SSH-first setup is too close to giving an agent a router shell. | Reconsider only after a separate security review and a concrete gap. |
| Workflows | n8n, during the later `ai-stack` rebuild | **Deferred.** Suitable for approved, named workflows rather than free-form infrastructure control. | Each workflow must retain target guards, approval checks, logs, and post-change verification. |

### Upstream-server connectivity findings

The following findings came from a source review of the Proxmox MCP 1.3.0
source and MikroMCP 1.8.0 source during planning. They are not a substitute
for pinning and reviewing the exact artifact used at implementation time.

| Server | Normal path | Explicit external or outbound paths |
| --- | --- | --- |
| Proxmox MCP | Its normal `stdio` server connects to the configured Proxmox API; no telemetry or update check was found in its own source. | `TOOL_ROUTING` loads FastEmbed's `BAAI/bge-small-en-v1.5` model and must be treated as requiring an initial model retrieval unless pre-cached. API tools can cause Proxmox or a guest to fetch URLs, contact ACME, or execute arbitrary guest commands. |
| MikroMCP | Its normal `serve` path connects to configured RouterOS REST/SSH/SFTP targets; no telemetry was found in the service path. | `mikromcp doctor` checks npm for updates. `update` invokes npm. Tool calls can make the router fetch an arbitrary URL, contact package-update servers, run diagnostics, or execute a guarded SSH command. |

Consequences:

- Do not enable Proxmox `TOOL_ROUTING` in the first evaluation. If it is ever
  needed, pre-cache and pin the embedding model in a controlled build, then
  prove the runtime container has no general internet egress.
- Do not use MikroMCP `doctor` as a health check and do not allow it to update
  itself from a running service.
- Installation and image/package retrieval are separate supply-chain events.
  Pin versions and digests, generate or record an SBOM, and test upgrades in a
  disposable environment before promotion.

## Credentials, authentication, and logging

### Credentials

- Create distinct read-only identities for each integration. They must not
  reuse Terraform tokens, personal accounts, or existing operator secrets.
- For Proxmox, use a privilege-separated API token with the minimum read ACLs.
  Explicitly set certificate verification on; the reviewed third-party server
  defaults it off.
- For MikroTik, create a dedicated read-only RouterOS user. Do not grant SSH,
  FTP, `sniff`, policy-change, package, or user-management permissions merely
  to satisfy optional MCP tools.
- Store any shared-service secret through the repository's SOPS pattern and
  inject it at runtime. Never add it to tracked MCP client configuration,
  prompts, images, or worktrees.

### Client authentication

- Local `stdio` servers inherit the local agent session boundary and do not
  listen on a network port.
- A future remote endpoint needs authenticated internal access, a constrained
  client allowlist, and separate identities/roles for each caller. TLS is
  mandatory.
- Do not expose a general MCP endpoint through a public route simply because
  Traefik can proxy it.

### Audit requirements

Capture the MCP server name/version, caller identity, target identity, tool,
parameters redacted for secrets, response status, correlation ID, and the
associated repository task. Forward logs to the existing central logging
system. For a mutation runner, also capture the invoked repository command,
approval identifier, expected diff, and verification result.

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

1. Decide the exact hosting target, `automation_seg` subnet/VLAN, service
   identity, remote transport, authentication model, certificate issuer, and
   central logging integration.
2. Define an adapter-by-adapter egress policy and a per-adapter secret model.
3. Decide whether each candidate is safely configurable or must be replaced by
   a repository-owned narrow adapter.
4. Produce a production mutation runbook that delegates to the existing
   wrappers rather than embedding write credentials in the MCP service.

Pass criteria: the network and secret design is specific enough for a
Terraform/Ansible implementation plan and production preflight.

### Phase 4 — build and validate `mcp-stack`

This is a future infrastructure change, not authorized by this plan alone.

1. Implement the new segment and workload on `pve-test-vm` first.
2. Apply the validation tier for the SDN/firewall change, including the
   required teardown cycle when modifying existing network policy.
3. Deploy only read-only adapters with default-deny egress and central logs.
4. Run failure, revocation, egress-denial, certificate, restart, and upgrade
   tests before promotion.

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

- Which local client becomes the reference host for the first evaluation?
- Does Phase 2 demonstrate enough value to justify a shared remote service,
  rather than continuing with local `stdio` tools?
- What is the final name and network allocation for `automation_seg`?
- Should the shared discovery service use upstream servers behind a restrictive
  proxy, or small repository-owned adapters that expose only the allowed tools?
- What authentication mechanism is appropriate for private remote MCP clients
  without turning the endpoint into another public application?
- Which central log retention/redaction policy is sufficient for MCP tool
  parameters and outputs?
