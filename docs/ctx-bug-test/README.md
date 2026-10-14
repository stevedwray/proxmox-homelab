# ctx-bug-test (workspace)

A targeted bug hunt on Framework: Qwen3.8-Flash-Next (UD-Q4_K_XL) and
Laguna-S-2.1 (UD-Q4_K_M), each on the Nathanw llama.cpp fork and on
upstream llama.cpp (Vulkan), at `--ctx-size` 32k, 64k, 96k and 131k, with
the same GGUF and the same prompts. Looking for hallucination, repetition,
looping and loss of instruction following, and whether each comes from the
build or from the context size. See [plan.md](plan.md).

Status: **phase 2 built, not run** (2026-10-14). The operator settled
decisions D1–D7 on 2026-10-13; subsequent prompt-fit and Part B corrections
are incorporated in plan.md. No model test has run on Framework.

The operator completed catalogue deployment (ctx-08) on 2026-10-14:
all 16 required test IDs passed the guarded check, 52 catalogue entries
were written, and `qwen3-coder-next-upstream` was reloaded. The next step
is ctx-09, the pilot, with a separate production preflight and approval.

The [local harness](../../scripts/framework-ctx-bugs/README.md) includes
deterministic prompts, tokenizer fit checks, saved context-fill prompts,
all detectors, checkpoint/resume, a loopback stand-in, reports and a detached
systemd user launcher with `--status`.

Local gates passed after review fixes: 33 unittest tests, including
interruption/resume, journal-capture failures and report-table column counts;
two prompt generations with a clean second-run diff; and a complete 16-cell
stand-in run (288 requests plus four saved triggering probes). All six canned
bug types were flagged in their expected cells; all 259 clean responses had
no flags. The local ignored report is
`scripts/framework-ctx-bugs/results/phase2-review-validation/report.md`.
This full run also simulated kernel-log permission failures: all 288 requests
completed and recorded `evidence_error` without adding flags to clean answers.

Session exception: the existing Git post-commit hook automatically attempted
`./with-secrets-prod-tiny scripts/provision.sh --stack mcp-utility-stack`
after the documentation commit, contrary to this session's local-only rule.
Its `/tmp/docs-rag-reindex-20261014-111050.log` remained empty, and a local
host-process check found no matching reindex process still running. Those
observations do not establish whether production was contacted or changed;
no production inspection was performed to verify effects. The closeout note
was committed using a temporary hooks directory that retained pre-commit
checks and excluded this production post-commit hook.

Remaining work is written as steps ctx-09 to ctx-14 in
[plan.md](plan.md#execution-steps), with a status table. To continue, open
the `~/git/proxmox-homelab-ctx-bug-test` worktree in VS Code and tell Codex:

> Run the next step of docs/ctx-bug-test/plan.md.

Local steps run straight through. Steps on Framework post a preflight and
wait for "proceed" before running anything.

Related: [docs/llama-swap](../llama-swap/README.md) (the catalogue, builds
and entries this uses), [docs/model-params](../model-params/README.md)
(variants; the Laguna-on-fork token-14 finding; RULER),
[docs/framework-ubuntu](../framework-ubuntu/README.md).
