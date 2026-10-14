# ctx-bug-test (workspace)

A targeted bug hunt on Framework: Qwen3.8-Flash-Next (UD-Q4_K_XL) and
Laguna-S-2.1 (UD-Q4_K_M), each on the Nathanw llama.cpp fork and on
upstream llama.cpp (Vulkan), at `--ctx-size` 32k, 64k, 96k and 131k, with
the same GGUF and the same prompts. Looking for hallucination, repetition,
looping and loss of instruction following, and whether each comes from the
build or from the context size. See [plan.md](plan.md).

Status: **full run regraded and written up; cleanup awaiting approval** (2026-10-15). The operator settled
decisions D1–D7 on 2026-10-13; subsequent prompt-fit and Part B corrections
are incorporated in plan.md. The operator started the detached greedy-only
131072-context pilot at 00:08:06 UTC; its start gate passed. The run directory
is `/storage/artifacts/framework-ctx-bugs/20261014T000806Z` on Framework.

The operator completed catalogue deployment (ctx-08) on 2026-10-14:
all 16 required test IDs passed the guarded check, 52 catalogue entries
were written, and `qwen3-coder-next-upstream` was reloaded. Local preparation
ctx-10b/ctx-10c/ctx-10e and the ctx-10d confirmation are complete. D9=b is deployed and
verified. The fresh full-run retry started at 07:17:22 UTC on 2026-10-14 under
`/storage/artifacts/framework-ctx-bugs/20261014T071722Z`; its start gate passed.
Attempt 1 failed when daily upgrades restarted llama-swap. The completed retry
restored its previous model, and `apt-daily-upgrade.timer` was restored and
verified active. No automatic infrastructure recovery was needed. The local
harness now passes 93 tests, including budget-aware attribution, saved probe
comparisons and counting identical context outputs once.

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

**D8 decided and implemented 2026-10-14: b.** F now has seven questions;
S3 keeps its count and Qwen keeps its default effort. The plan corrected option
c to medium/low because the saved templates map high to xhigh. No prompt or
reasoning-effort change was made in ctx-10a.

ctx-10a's fixes pass 58 tests. Regrading the saved evidence clears
both Qwen S1 false positives, changes both Qwen F repetition flags to
informational dense-reasoning, preserves S4 shingle repetition and adds the
early fence expiry to the GPU evidence. The original checkpoint is retained
as `results.pre-regrade.jsonl`. The operator confirmed successful Framework
regrade of all 24 requests and one probe on 2026-10-14. The table above
reflects the corrected classifications; timings and responses are unchanged.

## Small-batch confirmation (2026-10-14)

ctx-10d run `20261014T041054Z` completed its one greedy F request on
`laguna-s-2.1-upstream-ctx131k-b512` (batch 512/ubatch 128). Its raw answer
matches all seven expected answers. There are no flags, request errors or
evidence errors; the captured kernel window has no entries and the server
identity is unchanged. The run restored `qwen3-coder-next-upstream`.
Saved prompt hash and alias/build/context/slot checks pass. The tokenizer
count is 112,640; server timing reports 112,641 prompt tokens, a one-token
discrepancy retained in the raw evidence. Local evidence is in ignored
`artifacts/batch-confirm/`.

| Measurement | Original pilot Laguna upstream F | ctx-10d |
| --- | --- | --- |
| Hang/request outcome | GPU timeout/reset; HTTP 500 | No hang or request error observed |
| Request wall time | 899.192 s | 782.128 s |
| Prompt throughput | Unavailable: failed response has no timings | 144.576 tok/s |

The full confirmation run took about 15 min 08 s. Its accuracy is 7/7;
the pilot had eight questions, so accuracy is not compared. Removing the
count question also changed the prompt, which prevents attributing success
solely to smaller batches. This is one successful run, not a guarantee for
other sizes, models or seeds. A production-catalogue change remains a
separate task.

D9 options considered before ctx-11:

| Option | Effect |
| --- | --- |
| a. Keep defaults | Tests production settings; another long-context GPU hang remains possible. |
| b. Batch 512/ubatch 128 for every test cell | Keeps paired cells comparable using the setting that succeeded here; may slow prompt processing and requires a new local catalogue change plus approved deployment. |
| c. Defaults, skip Laguna upstream F at 96k/131k | Avoids those known-risk requests but leaves a context-fill coverage gap. |

D9=b was subsequently selected by the operator and verified deployed in
ctx-10g on 2026-10-14. All required test entries use batch 512/ubatch 128;
the final count gate returned 24 flagged entries including HIP variants and
zero redundant ctx131k-b512 entries. The 52-entry generated config already
matched exactly; verification needed no write or model reload. The playbook
passed with failed=0 and changed=0. The first full run failed after a daily-upgrade service restart; the fresh
07:17:22 UTC retry is running. Results are pending.

## Full run (reviewed 2026-10-15)

Run `20261014T071722Z` completed all 16 cells: 288 requests and four saved
Laguna fork triggering probes. It ran from 20:17 NZDT on 14 October to
07:17 NZDT on 15 October (11 h 00 min), below the 20–24 h estimate.
No crash, GPU error, evidence error or infrastructure recovery occurred.
All raw records match JSONL, all saved prompt hashes/fit checks and
build/alias/slot identities pass, and request swap identities are unchanged.
`qwen3-coder-next-upstream` was restored successfully. The agent restored
`apt-daily-upgrade.timer` and verified it active immediately after observing
completion; the watcher had not yet reached its next scheduled poll.

Evidence is copied locally to ignored `artifacts/full/`. The completed
Framework run was regraded offline in place under ctx-11a at
`/storage/artifacts/framework-ctx-bugs/20261014T071722Z/`.

| Cell | Requests | Request minutes | Outcome |
| --- | ---: | ---: | --- |
| qwen3.8-flash-next-q4-nathanw-ctx32k | 22 | 60.13 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-upstream-ctx32k | 22 | 54.08 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-nathanw-ctx64k | 22 | 63.02 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-upstream-ctx64k | 22 | 59.62 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-nathanw-ctx96k | 22 | 66.32 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-upstream-ctx96k | 22 | 66.41 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-nathanw-ctx131k | 22 | 69.81 | S3 representation/repetition flags; all S4 capped; F passes |
| qwen3.8-flash-next-q4-upstream-ctx131k | 22 | 74.07 | S3 representation/repetition flags; all S4 capped; F passes |
| laguna-s-2.1-nathanw-ctx32k | 6 | 3.50 | S1/S2 hidden tokens; S3 count absent; short S4 capped; F passes |
| laguna-s-2.1-upstream-ctx32k | 22 | 14.22 | S3 counting/representation errors; S4 short sections/path shingle; F passes |
| laguna-s-2.1-nathanw-ctx64k | 6 | 5.54 | S1/S2 hidden tokens; S3 count absent; short S4 capped; F passes |
| laguna-s-2.1-upstream-ctx64k | 22 | 19.77 | S3 counting/representation errors; S4 short sections/path shingle; F passes |
| laguna-s-2.1-nathanw-ctx96k | 6 | 8.16 | S1/S2 hidden tokens; S3 count absent; short S4 capped; F passes |
| laguna-s-2.1-upstream-ctx96k | 22 | 27.23 | S3 counting/representation errors; S4 short sections/path shingle; F passes |
| laguna-s-2.1-nathanw-ctx131k | 6 | 11.36 | S1/S2 hidden tokens; S3 count absent; short S4 capped; F passes |
| laguna-s-2.1-upstream-ctx131k | 22 | 36.74 | S3 counting/representation errors; S4 short sections/path shingle; F passes |

Request minutes exclude model loads, prompt construction and restoration.

For every S1–S5 prompt/run on each build, **both answer and reasoning are
byte-identical across all four contexts**, including sampled runs. No
context-size divergence is observed in this matrix. This does not establish
behavior for other prompts, quantizations, build versions or context sizes.

All 28 F responses score 7/7 (196/196 answers): five relocated needles and
both absent facts. F prompts meet each exact tokenizer target and paired
builds use the same bytes per model/size. There is no observed retrieval
degradation or absent-fact hallucination. Laguna server usage reports one
more prompt token than /tokenize at each F size, as in the earlier batch
confirmation; the recorded fit gate uses /tokenize and this discrepancy
is retained in evidence. The original eight-question pilot F is not an
accuracy comparator.

Qwen S4 exhausts 16,384 tokens on all 32 responses: 24 have no final answer
and eight have a partial runbook. Reasoning drafts/recounts the runbook and
repeats shingles; no exact-tail loop is flagged. This is a budget/output
failure on both builds and all sizes. S1/S2/S5 pass on both Qwen builds.

Qwen S3 counts the six matching records correctly, but Nathanw seed 2 and
upstream seed 3 return the quoted string `"6"`. Their `wrong:q8` flags are
strict numeric-type failures, not incorrect arithmetic. Nathanw seed 1
repeats the instruction phrase "JSON list of eight answers in question
order" four times in reasoning while giving a correct final answer; its
repetition flag meets the mechanical threshold but does not show a stuck
model. These outcomes are identical at every context size.

Laguna Nathanw S1 has 758 generated versus 342 visible tokens and exposes
`</think>` plus reasoning in content; S2 has 289 versus 51 tokens but returns
valid JSON/END. This is consistent with the known fork hidden-token/parser
failure; aggregate evidence does not identify hidden token IDs. All four
saved full-budget S1 probes show the same failure before short mode begins.
Upstream S1/S2 pass. Laguna S3 answers all needles/absent facts correctly,
but Nathanw gives `NOT IN LOG` for the count. Upstream gives `"11"` greedily,
8 on seed 2, and `"6"` on seed 3 (seed 1 gives numeric 6). Some failures
are counting errors and some representation errors. S5 passes everywhere.

Laguna upstream S4 has 12 sections and its end marker, but at least one
section is below 150 words on every seed (e.g. greedy section 2: 143).
Seed 2 repeats the tokenized package path `/opt/maple/packages/maple-release-2.3.0.tar.gz`
four times. This trips the shingle detector without a repeated sentence or
stuck generation. Fork S4 is cut off by its 2,048-token short-mode budget.

### Attribution and candidate inventory (ctx-11a)

The offline regrade compares all six sampling fields, including token budget,
and includes the saved full-budget S1 probes as attribution evidence only.
The 288 checkpoint requests remain separate from the four probes. The first
checkpoint is preserved as `results.pre-regrade.jsonl` on Framework.

There are **31 findings**, each covering all four sizes (32768, 65536, 98304,
131072). Identical answers **and reasoning** across sizes count once. A
repeated greedy seed/run, including its full-budget probe, is one independent
sample. Sample counts describe the runs checked, not the number with a flag;
flags on one response can describe the same failure.

| Model | Build | Prompt | Automated label | Flags | Findings | Independent samples per finding |
| --- | --- | --- | --- | --- | ---: | ---: |
| qwen3.8-flash-next-q4 | nathanw | S3 | needs three more seeds | repetition, wrong:q8 | 2 | 4 |
| qwen3.8-flash-next-q4 | upstream | S3 | needs three more seeds | wrong:q8 | 1 | 4 |
| qwen3.8-flash-next-q4 | nathanw | S4 | needs three more seeds | if-fail:end-marker, if-fail:sections, if-fail:titles, if-fail:word-counts, no-answer, repetition, runaway | 7 | 4 |
| qwen3.8-flash-next-q4 | upstream | S4 | needs three more seeds | if-fail:end-marker, if-fail:sections, if-fail:titles, if-fail:word-counts, no-answer, repetition, runaway | 7 | 4 |
| laguna-s-2.1 | nathanw | S1 | build bug | hidden-tokens, if-fail:only-numbers, template-leak, wrong:sanity | 4 | 1 |
| laguna-s-2.1 | nathanw | S2 | not attributable (different budgets) | hidden-tokens | 1 | 1 |
| laguna-s-2.1 | nathanw | S3 | not attributable (different budgets) | wrong:q8 | 1 | 1 |
| laguna-s-2.1 | upstream | S3 | not attributable (different budgets) | wrong:q8 | 1 | 4 |
| laguna-s-2.1 | nathanw | S4 | not attributable (different budgets) | if-fail:end-marker, if-fail:sections, if-fail:titles, if-fail:word-counts, runaway | 5 | 1 |
| laguna-s-2.1 | upstream | S4 | not attributable (different budgets) | if-fail:word-counts, repetition | 2 | 4 |

The four build-bug findings are Laguna fork S1, backed by full-budget probes
matched to upstream greedy settings. S2/S4 remain observed failures, but their
2,048-versus-16,384 budgets cannot establish build causality. The same caution
applies to Laguna S3. All ten budget-confounded findings are labelled
`not attributable (different budgets)`. The seventeen other findings retain
the automated `needs three more seeds` suggestion; **D11 skips those runs**.
There are no context-size bug findings. Build divergence and dense reasoning
remain informational.

### Findings by bug type (ctx-13)

Every row below applies to all four tested sizes. Raw paths are relative to
`/storage/artifacts/framework-ctx-bugs/20261014T071722Z/raw/` on Framework;
`ctx32k` is the representative copy because S1–S5 output bytes match at every
size. Builds tested: Nathanw b10814-9e21f2e53 and upstream b11514-de7fa0a3c.

| Type | Model / build | Prompt and flag | Evidence / excerpt | Raw response |
| --- | --- | --- | --- | --- |
| Wrong given fact / count | Laguna / Nathanw | S3 `wrong:q8` | `"NOT IN LOG"` for six matching records; needles and absent facts correct. Budget-confounded build attribution. | `laguna-s-2.1-nathanw-ctx32k/S3-greedy.json` |
| Wrong given fact / count | Laguna / upstream | S3 `wrong:q8` | Seed 2 returns `8`, expected numeric 6; greedy returns `"11"`. | `laguna-s-2.1-upstream-ctx32k/S3-seed2.json` |
| Representation failure | Qwen / both | S3 `wrong:q8` | Quoted `"6"` instead of numeric 6 (Nathanw seed 2, upstream seed 3); arithmetic correct. | `qwen3.8-flash-next-q4-nathanw-ctx32k/S3-seed2.json`; `qwen3.8-flash-next-q4-upstream-ctx32k/S3-seed3.json` |
| Repetition | Qwen / Nathanw | S3 `repetition` | "JSON list of eight answers in question order" occurs four times in reasoning; final answer correct. | `qwen3.8-flash-next-q4-nathanw-ctx32k/S3-seed1.json` |
| Repetition / budget exhaustion / instruction loss | Qwen / both | S4 `repetition`, `runaway`, `no-answer`, `if-fail:*` | 32/32 hit 16,384; 24 empty final answers, eight partial runbooks. Reasoning drafts and counts section words. | `qwen3.8-flash-next-q4-nathanw-ctx32k/S4-greedy.json`; `qwen3.8-flash-next-q4-upstream-ctx32k/S4-greedy.json` |
| Hidden-token/parser build bug | Laguna / Nathanw | S1 `hidden-tokens`, `template-leak`, `if-fail:only-numbers`, `wrong:sanity` | Full-budget probe: 758 generated / 342 visible; final content starts "I need to solve this problem step by step" and exposes `</think>`. Upstream matched greedy passes. | `laguna-s-2.1-nathanw-ctx32k/S1-probe.json` |
| Hidden tokens | Laguna / Nathanw | S2 `hidden-tokens` | 289 generated / 51 visible, valid JSON and END; short/full build attribution unavailable. | `laguna-s-2.1-nathanw-ctx32k/S2-greedy.json` |
| Instruction loss / budget exhaustion | Laguna / Nathanw | S4 `runaway`, `if-fail:*` | Cut off at the deliberately reduced 2,048-token cap. | `laguna-s-2.1-nathanw-ctx32k/S4-greedy.json` |
| Instruction loss / path shingle | Laguna / upstream | S4 `if-fail:word-counts`, `repetition` | Greedy section 2 has 143 words, minimum 150; seed 2 repeats `/opt/maple/packages/maple-release-2.3.0.tar.gz` four times. | `laguna-s-2.1-upstream-ctx32k/S4-greedy.json`; `laguna-s-2.1-upstream-ctx32k/S4-seed2.json` |

No response invents either absent fact, and no exact-tail loop is detected.
The observed S4 cap exhaustion and S1 hidden tokens are the relevant runaway
symptoms. Aggregate hidden-token counts do not prove which token IDs occurred.
The instruction failures above do not grow with context size; all S5
conversation/reference checks pass. These observations establish neither a
new context-size bug nor a need to change model context defaults.

### Part B fill accuracy

Each entry is correct answers / questions at that size, aggregating the
listed runs. All use seven-question F prompts. Paired builds have identical
prompt bytes, with relocated needles and exact tokenizer targets 14,336 /
47,104 / 79,872 / 112,640. The eight-question pilot cannot be compared for
accuracy; its hang, wall time and prompt tok/s remain useful evidence.

| Model | Build | Runs per size | 32768 | 65536 | 98304 | 131072 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Qwen | Nathanw | greedy + seed 1 | 14/14 | 14/14 | 14/14 | 14/14 |
| Qwen | upstream | greedy + seed 1 | 14/14 | 14/14 | 14/14 | 14/14 |
| Laguna | Nathanw | short greedy | 7/7 | 7/7 | 7/7 | 7/7 |
| Laguna | upstream | greedy + seed 1 | 14/14 | 14/14 | 14/14 | 14/14 |

F totals **196/196**, with no retrieval degradation. Short-mode fork F is
observational, not a controlled comparison of equal completion budgets.

### Prepared catalogue cleanup (ctx-14)

These changes are prepared in the local models.json only; production cleanup
has not run and awaits `ctx-bug-cleanup` approval.
Both tested models' `variants` return to `[]`, removing all 24 generated
context-test entries including HIP variants. Remove Laguna's `fork` backend
again; its two Vulkan/HIP upstream backends remain. Preserve the existing
wildcard Qwen status and add explicit statuses for the tested builds. All
four tested status records get `checked: 2026-10-15`.

| Model | Status key | Proposed status | Reason |
| --- | --- | --- | --- |
| qwen3.8-flash-next-q4 | nathanw | works | Context test: S1/S2/S5 and F pass; S3 numeric-type failures; S4 exhausts 16384 tokens on both builds (docs/ctx-bug-test). |
| qwen3.8-flash-next-q4 | upstream | works | Context test: S1/S2/S5 and F pass; S3 numeric-type failures; S4 exhausts 16384 tokens on both builds (docs/ctx-bug-test). |
| laguna-s-2.1 | nathanw | broken | Matched full-budget S1 probes expose reasoning/template and hidden tokens on b10814 at all four sizes (docs/ctx-bug-test). |
| laguna-s-2.1 | upstream | works | F 7/7 through 131k with batch 512/128 and parallel 1; S3 count and S4 length failures; default-batch pilot GPU timeout (docs/ctx-bug-test). |

These statuses summarize the tested configuration and limitations; the
ordinary entries keep their existing settings, and HIP was not tested.
No new build, candidate promotion or production batch/default-model change
is proposed. D1's candidate follow-up remains outside the completed matrix.
Only ctx-14 deployment remains and requires its named production cleanup
approval. The local JSON/scope gate passes, all 42 llama-builds tests and
93 harness tests pass, shell syntax and playbook syntax pass. A local render
with stand-in build links produces 27 entries instead of 52, removes all
24 context variants plus Laguna fork, and preserves every retained server
command. The cleanup guard passes ten tests covering changed/unchanged
configs and refusals. No production cleanup access has occurred.

Known production issue found by this test (not fixed here, D10): Ubuntu's
daily `apt-daily-upgrade` runs needrestart, which restarts
`llama-swap.service` when a library that llama-server maps is upgraded
(2026-10-14 06:32 UTC: libx11). That kills the loaded model and nothing
reloads it (the preload runs only at boot). Fix later, for example a
needrestart exclusion for llama-swap in `framework-desktop-llama-swap.yml`.

Related: [docs/llama-swap](../llama-swap/README.md) (the catalogue, builds
and entries this uses), [docs/model-params](../model-params/README.md)
(variants; the Laguna-on-fork token-14 finding; RULER),
[docs/framework-ubuntu](../framework-ubuntu/README.md).
