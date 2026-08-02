# Ollama coding-agent bake-off findings

Run date: 2026-07-21. This is the Phase 0/Phase 1 decision record for the
operator-directed Ollama-only path.

## Decision

Use **OpenCode 1.18.4** as the primary daily coding agent on this workstation,
with **Aider 0.86.2** as the preferred fallback/control client. Both use
`eval-qwen3-coder-30b-a3b:q4_k_m` on Ollama at
`http://192.168.1.8:11434` (OpenCode uses `/v1`). Each successful client was
given a 180,000-input, 24,000-output budget; the live Ollama model confirmed a
262,144-token context window.

This supersedes the original Phase 0 runtime ordering at the operator's
direction: llama.cpp and LM Studio were stopped, and the bake-off continued
against Ollama only. The workstation, rather than Framework, hosts the agent
clients; Framework is inference-only over the LAN.

## Phase 0 prerequisite

The unchanged 84-tool replay harness passed **15/15** direct repetitions
against Ollama: every repetition produced a valid structured `create_file`
tool call, with no validation or transport failures. This is the required
re-verification that had previously existed only for LM Studio. The attempted
llama.cpp sweep never completed because its endpoint became unavailable; it
is not used for this decision.

## Phase 1 results

| Framework | Result | Task evidence and decision |
| --- | --- | --- |
| OpenCode | **Primary** | Passed Python regression (6/6), Ansible syntax repair, ShellCheck repair, and two simultaneous disposable-worktree sessions. It also read a full large repository document and authored Terraform test coverage; the final Terraform gate was blocked by the local `bpg/proxmox` provider before test execution. |
| Cline | Revalidate before use | A corrected supported JSON/headless setup previously passed its Ollama smoke (7,427 input / 7 output tokens in 9.9 seconds) and the Python regression (6/6), but the current headless-container path exits before creating a session even after Cline-generated provider setup. |
| Aider | **Preferred fallback** | A normal Git-enabled disposable clone with its explicit `OLLAMA_API_BASE` passed the Python regression (6/6), a seeded real Ansible-role syntax repair, and a seeded ShellCheck repair. Its large-document Terraform-test run failed because it wrote the fixture under a duplicated nested path, leaving the real module with zero discovered tests. The earlier 0/6 Python run was a harness failure, not a client verdict. |
| OpenHands | Python-only candidate | The official `uv` installation route produced OpenHands CLI 1.16.0; it passed the Python regression (6/6) in its isolated Docker execution container, but failed the seeded Ansible role repair by leaving invalid YAML. Its documented nested-sandbox volume wiring still needs a separate integration check. |
| Goose | Secondary candidate | Passed Python regression (6/6) with native Ollama tooling, but its repeat Ansible run made no repair after its asynchronous CLI return. |

The full JSONL run ledger and Markdown task reports are retained under the
ignored documentation workspace:
`docs/framework-ubuntu/artifacts/coding-agents-20260721/`. `INSTALLS.md` in
that directory records every private installation, Docker image, and cleanup
command.

## Boundaries and remaining validation

- All edits were made in disposable `task/*` worktrees under `/tmp`; no agent
  wrote to `main` or `stable`, and no task contacted an infrastructure host.
- The Ansible live grade passed after creating the explicit disposable
  `docker-socket-proxy-test` LXC on `pve-test-vm`: the idempotent second
  provision run reported 20 OK, 0 failed, and 0 unreachable. Terraform then
  destroyed exactly that LXC, its generated inventory, and its epoch marker.
- The Terraform task is not a pass or fail for any agent until the local
  provider handshake problem is repaired and the authored `terraform test`
  fixture can execute. It was independently reproduced with Terraform 1.15.8
  and the locked `bpg/proxmox` 0.100.0 provider in a disposable clone.
- Aider now has Ansible and ShellCheck coverage, but its large-document
  Terraform-test authoring failed before the known provider-handshake gate.
- Cline's current headless container path regressed: even a Cline-generated
  Ollama provider configuration exits before a session is created. Reproduce
  and repair that client/runtime issue before giving it broader task coverage.
- Run the Ansible, ShellCheck, large-document, and parallel-worktree tasks
  through OpenHands and Cline once Cline's runtime is repaired. Resolve the
  OpenHands nested-sandbox volume behavior before granting it routine
  Docker-socket access.
