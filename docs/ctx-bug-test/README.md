# ctx-bug-test (workspace)

A targeted bug hunt on Framework: Qwen3.8-Flash-Next (UD-Q4_K_XL) and
Laguna-S-2.1 (UD-Q4_K_M), each on the Nathanw llama.cpp fork and on
upstream llama.cpp (Vulkan), at `--ctx-size` 32k, 64k, 96k and 131k, with
the same GGUF and the same prompts. Looking for hallucination, repetition,
looping and loss of instruction following, and whether each comes from the
build or from the context size. See [plan.md](plan.md).

Status: **pilot regraded; batch confirmation pending** (2026-10-14). The operator settled
decisions D1–D7 on 2026-10-13; subsequent prompt-fit and Part B corrections
are incorporated in plan.md. The operator started the detached greedy-only
131072-context pilot at 00:08:06 UTC; its start gate passed. The run directory
is `/storage/artifacts/framework-ctx-bugs/20261014T000806Z` on Framework.

The operator completed catalogue deployment (ctx-08) on 2026-10-14:
all 16 required test IDs passed the guarded check, 52 catalogue entries
were written, and `qwen3-coder-next-upstream` was reloaded. The next step
is ctx-10c, the local small-batch catalogue variant. ctx-10b added suffix
and prompt-selection support with 62 tests passing. D8 is decided; the full
run still waits for the remaining preparation and D9 decision.

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

## Pilot (2026-10-14)

Run `20261014T000806Z` completed all four 131072-context cells: 24 greedy
requests plus Laguna Nathanw's saved S1 triggering probe. No request or
probe has `evidence_error`. Saved aliases, build identities, contexts and
single-slot settings match the matrix. Saved F hashes match the copied
prompts; both builds used 112,640 prompt tokens per model. `run.json`
records `restore_model` and `restored_model` as
`qwen3-coder-next-upstream`, with `restored_default: true`. Evidence is
saved locally under ignored `artifacts/pilot/`.

The run took 1 h 39 min (00:08:06–01:47:24 UTC), below the 2.5 h estimate.
Times below sum request wall times, excluding loads, fit checks, restoration
and the extra 26-second probe.

| Cell | Request time | Reviewed findings |
| --- | ---: | --- |
| Qwen Nathanw | 30.50 min | S1/S2/S3/S5 pass; S4 repetition/runaway; F dense-reasoning/runaway without an answer. |
| Qwen upstream | 37.28 min | Same S1/S4/F outcome; S2/S3 differ while passing; S5 passes. |
| Laguna Nathanw | 7.54 min | S1 hidden tokens/template leak; S2 hidden tokens/no answer; S3/F wrong count; S4 truncated at 2,048; S5 passes. |
| Laguna upstream | 17.62 min | S1/S2/S5 pass; S3 wrong count; S4 section 2 has 144 words; F HTTP 500 after 899 seconds with GPU timeout/reset. |

Qwen S1 answers `391, 12, 708` correctly on both builds; the detector
incorrectly rejects spaces around commas. Qwen F reasoning enumerates
unique log records until the cap. Its repetition flag is a compression-only
false positive: tail ratios 0.175/0.173 and no repeated eight-word shingle.
Its q1–q8 failures reflect no final answer, so needle retrieval is unmeasured.
Qwen S4 exhausts the reasoning budget while drafting/counting words. Its
shingle checks do fire (maximum counts 7/53), and upstream repeatedly
revises word counts. This is repetitive planning and budget exhaustion;
neither response triggered the exact-tail loop check.

Laguna Nathanw's S1 probe and short S1 each report 758 generated versus
342 visible tokens; S2 reports 309 versus 72. S1 exposes reasoning and
`</think>` in final content; S2 puts its attempted answer into reasoning and
leaves content empty. This matches the known fork failure, but saved replies
alone cannot identify hidden token IDs. S3–F do not meet the hidden-token
threshold: generated-minus-visible counts are 2, 282, 2 and 2; S4's
2,048/1,766 ratio is below 1.5. The six short requests keep the full fit reserve.

Laguna S3 gets q1–q7 right on both builds but gives quoted counts
`"13"`/`"11"` instead of numeric 6. Nathanw F gets q1–q7 right but gives
`"NOT IN LOG"` instead of numeric 72. Shared S3 counting failures do not
establish a build or context-size bug. Upstream F's empty response cannot
be graded for retrieval. Its kernel window contains the 01:34:29 fence
fallback expiry and 01:46:34 ring timeout, compute-queue reset and recovery.
The server remained healthy without restart; `crash` means request failure,
not server termination. Format/wrong-answer flags follow from that failure.
The GPU detector misses the early fence-expiry line but catches the reset.

Build divergence is informational: Qwen S2 differs in wording and S3 in
JSON spacing while both pass; Laguna S1/S2 differ because of fork failures,
S3 has different wrong counts, and S4 compares truncated short-form output
with full output. No absent-fact hallucination was found. S5 passes everywhere.

Recommendation after ctx-10a: confirm the GPU issue through the planned
small-batch run (ctx-10b–ctx-10d) before ctx-11. D1's fresh fork
candidate cell is recommended because the fork failure persists; preparation
and execution need separate approval, without promotion. No detector,
model or build was changed during review.

The operator must choose the full-run settings:

| Decision | Options |
| --- | --- |
| D8: Qwen/count task | a: retain prompts/default effort; b: remove F's count only; c: b plus reduced reasoning effort, subject to the correction below. |
| D9: Vulkan batches | a: defaults; b: batch 512/ubatch 128 for every cell; c: defaults but skip Laguna upstream F at 96k/131k. |

**D8 decided 2026-10-14: b.** Remove F's count question in a later prompt
change; keep S3's count and Qwen's default effort. The plan corrected option
c to medium/low because the saved templates map high to xhigh. No prompt or
reasoning-effort change was made in ctx-10a.

ctx-10a's fixes pass 58 tests. Regrading the saved evidence clears
both Qwen S1 false positives, changes both Qwen F repetition flags to
informational dense-reasoning, preserves S4 shingle repetition and adds the
early fence expiry to the GPU evidence. The original checkpoint is retained
as `results.pre-regrade.jsonl`. The operator confirmed successful Framework
regrade of all 24 requests and one probe on 2026-10-14. The table above
reflects the corrected classifications; timings and responses are unchanged.

Remaining work is written as steps ctx-10c to ctx-14 in
[plan.md](plan.md#execution-steps), with a status table. To continue, open
the `~/git/proxmox-homelab-ctx-bug-test` worktree in VS Code and tell Codex:

> Run the next step of docs/ctx-bug-test/plan.md.

Local steps run straight through. Steps on Framework post a preflight and
wait for "proceed" before running anything.

Related: [docs/llama-swap](../llama-swap/README.md) (the catalogue, builds
and entries this uses), [docs/model-params](../model-params/README.md)
(variants; the Laguna-on-fork token-14 finding; RULER),
[docs/framework-ubuntu](../framework-ubuntu/README.md).
