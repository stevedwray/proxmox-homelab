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

Status: **lh-01 local tools built; Framework scan awaiting approval**
(2026-10-15). Decisions D-L1 to D-L7 are settled. The corrected plan leaves
parallel unset and requires the pilot to confirm the expected shared-pool
slot layout through `/props` and `/slots`; a different layout stops the pilot.

The [scan tools](../../scripts/loop-hunt/README.md) pass all 17 tests,
including a read-only online backup of committed WAL-only rows and a snapshot
integrity check. The scanner handles history branches, clean/looping chats,
visible control markers, stored parameters and private output permissions.
It writes only flagged excerpts plus aggregate summaries. No Framework
access or real-chat scan has occurred. Next: approve `loop-hunt-chat-scan`
using the preflight and exact commands in [plan.md](plan.md#lh-01-chat-scan).
After the scan, the operator chooses replay chats and settles sampling/Q2
from the evidence before lh-02 starts. Only counts from the scan enter git.

To run it, open the `~/git/proxmox-homelab-ctx-bug-test` worktree in VS
Code, `git pull --ff-only`, and tell Codex:

> Continue docs/loop-hunt/plan.md.
