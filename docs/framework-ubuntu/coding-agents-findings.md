# Ollama coding-agent bake-off findings

Run date: 2026-07-21. This is the Phase 0/Phase 1 decision record for the
operator-directed Ollama-only path.

## Decision

Use **OpenCode 1.18.4** as the primary daily coding agent on this workstation,
with **Goose** as the fallback for contained coding and operations tasks. Both
use `eval-qwen3-coder-30b-a3b:q4_k_m` on Ollama at
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
| Goose | **Fallback** | Passed Python regression (6/6) with native Ollama tooling. Its repeat Ansible run made no repair after its asynchronous CLI return, so it is suitable as a fallback but not the primary unattended agent. |
| Aider | Not suitable | Smoke passed, but the Python task ended 0/6 after it claimed it could not access the mounted worktree and overwrote the file speculatively. |
| Cline | Not runnable | Cline 3.0.46 displayed help/version but headless invocations exited before reaching Ollama, even after container CA repair. |
| OpenHands | Not runnable | The pulled 1.8 application image lacks the documented headless launcher; installing the separate current CLI (1.16.0) failed with a Python dependency conflict. No task run was fabricated. |

The full JSONL run ledger and Markdown task reports are retained under the
ignored documentation workspace:
`docs/framework-ubuntu/artifacts/coding-agents-20260721/`. `INSTALLS.md` in
that directory records every private installation, Docker image, and cleanup
command.

## Boundaries and remaining validation

- All edits were made in disposable `task/*` worktrees under `/tmp`; no agent
  wrote to `main` or `stable`, and no task contacted an infrastructure host.
- The Ansible task's local syntax gate was run. Its live `provision.sh`
  pve-test grade was intentionally not run as part of this workstation agent
  comparison, because that is an infrastructure deployment rather than a
  disposable-code validation.
- The Terraform task is not a pass or fail for any agent until the local
  provider handshake problem is repaired and the authored `terraform test`
  fixture can execute.
- Revisit Cline once its non-interactive CLI can actually start a session, and
  OpenHands once its published launcher/dependencies are mutually compatible.
