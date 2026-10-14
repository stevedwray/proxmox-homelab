# loop-hunt (workspace)

Follow-up to [docs/ctx-bug-test](../ctx-bug-test/README.md). That test
found no looping and no fork-vs-upstream difference for Qwen3.8-Flash-Next
under clean conditions (fresh context per request, one slot, no cache), so
the looping seen in real use (GLM-5.3-Flash and Qwen3.8-Flash-Next) was not
reproduced. This plan tests the real-use conditions it left out: long
multi-turn sessions, prompt-cache reuse, 4 parallel slots, context
overflow, 262k context, the fork's older build, real Open WebUI chats, and
a blind judge for semantic looping and context echoing. See
[plan.md](plan.md).

Status: **planned 2026-10-15, not started.** Decisions D-L1 to D-L7 in
plan.md wait on the operator.

To run it, open the `~/git/proxmox-homelab-ctx-bug-test` worktree in VS
Code, `git pull --ff-only`, and tell Codex:

> Continue docs/loop-hunt/plan.md.
