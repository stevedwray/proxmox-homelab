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

Status: **lh-01, lh-01b and lh-01c complete; operator replay selection pending**
(2026-10-15). Decisions D-L1 to D-L7 are settled. The corrected plan leaves
parallel unset and requires the pilot to confirm the expected shared-pool
slot layout through `/props` and `/slots`; a different layout stops the pilot.

The [scan tools](../../scripts/loop-hunt/README.md) pass all 48 tests,
including a read-only online backup of committed WAL-only rows and a snapshot
integrity check. Under explicit `loop-hunt-chat-scan` approval the tools were
copied to Framework and the live database was opened read-only for backup.
The snapshot passed integrity_check; scanning it found **12 chats, 14
assistant messages and zero hits**. No history parent links were broken.
All 14 assistant messages are from **2026-07** and estimate **<32k tokens**.

| Stored model id | Assistant messages | Flagged messages |
| --- | ---: | ---: |
| command-r-35b-dark-horror-v2-d_au:q4_k_s | 4 | 0 |
| l3.1-moe-6x8b-dark-rs-dantes-peak-hrr-r1-uncen-36b:q4_k_m-imat | 7 | 0 |
| l3.2-8x4b-moe-v2-dark-champion-inst-21b-uncen-ablit-d_au:q4_k_m | 1 | 0 |
| llama-3.3-70b-instruct:q3_k_m | 2 | 0 |

There are no saved Qwen Q4/Q2 or GLM assistant messages in this database.
This scan therefore provides neither examples nor client sampling settings
for the target models; it does not disprove the reported real-use loops.
No hit excerpts exist. Only aggregate counts from the scan are recorded here.

Framework artifacts remain at
`/storage/artifacts/loop-hunt/chat-scan-20261014/` (Framework's date):
`summary.md` and an empty `hits.jsonl`, both private. The full snapshot and
all snapshot sidecars were deleted, and deletion plus output permissions
were verified read-only. No live DB writes, model loads/inference or service
changes occurred; no chats or stored request parameters were copied locally.

The operator confirmed server-default sampling (no sampling fields in
requests) and Q2 exclusion. Replay remains pending: loops were observed in
**VS Code Copilot agent mode and benchmark harnesses**, so lh-01b scans
benchmark/deep-research transcripts before the later local Copilot scan.

lh-01b's lm_eval, CyberSecEval and deep-research adapters are built and tested.
They keep recorded model/build/settings provenance, avoid duplicate extracted
or judge responses, and count evidence-backed cap exhaustion separately
from looping candidates. Missing identity/cap evidence is reported explicitly.
Only source-host hit files contain bounded excerpts and whitelisted settings;
no full prompts/transcripts or API keys are exported. The code's CSE path
is `/srv/cyberseceval/runs/<run>/responses.json`.

The operator approved `loop-hunt-transcript-scan` and its recovery on
2026-10-15, including independent CSE scanning, usage finish-reason counts,
a schema-only deep-research diagnostic, a tested parser fix and a deep-only
retry. No inference, model/service changes or source-transcript writes occurred.

## Transcript scan (lh-01b, 2026-10-15)

| Source | Files | Response segments | Flagged candidates | Exact-loop flags | Repetition flags |
| --- | ---: | ---: | ---: | ---: | ---: |
| Eval | 43 | 5,571 | 75 | 3 | 71 |
| CyberSecEval | 78 | 827 | 18 | 1 | 18 |
| Deep-research | 34 (32 readable) | 10,919 | 502 | 501 | 502 |

Flags overlap; they are not independent bugs. The eval's other four flags
are template leaks. Eval has 70 repeated-shingle candidates and one
compression-only candidate; compression alone was not used to select examples.
Deep counts are saved UI response segments, not measured API-call counts.

The deep-research failure was two files with invalid JSON at scan time;
all readable files matched the expected UI-event schema. A synthetic fixture
reproduces the failure. The fix records unreadable file pointers privately
and continues through readable sessions, with explicit coverage gaps.
No transcript text or settings were returned by the diagnostic. Missing
event dates use the recorded session timestamp. All 34 local tests pass.

### Counts by recorded model/entry

| Source | Recorded model/entry | Responses | Candidates |
| --- | --- | ---: | ---: |
| Eval | eval-gemma4-26b:q4-ctx32k | 1,177 | 35 |
| Eval | eval-gemma4-26b-a4b-qat:q4_0-ctx32k | 937 | 14 |
| Eval | eval-laguna-s2-1:q4_k_m-ctx131k | 937 | 6 |
| Eval | eval-qwen3-coder-30b-a3b:q4_k_m-ctx32k | 541 | 11 |
| Eval | eval-qwen36-35b-a3b:q4_k_m-ctx32k | 937 | 5 |
| Eval | eval-qwen3.8-27b:q4_k_m-ctx32k | 937 | 0 |
| Eval | glm-5.3-flash | 69 | 0 |
| Eval | glm-5.3-flash-candidate | 3 | 0 |
| Eval | glm-5.3-flash-hip | 3 | 0 |
| Eval | laguna-s-2.1-heretic-nathanw | 3 | 1 |
| Eval | laguna-s-2.1-nathanw | 3 | 3 |
| Eval | qwen3.8-flash-next | 3 | 0 |
| Eval | qwen3.8-flash-next-candidate | 3 | 0 |
| Eval | qwen3.8-flash-next-hip | 3 | 0 |
| Eval | qwen3.8-flash-next-upstream | 3 | 0 |
| Eval | selftest-mock | 12 | 0 |
| CyberSecEval | Qwen3.8-Flash-Next UD-Q4_K_XL (recorded GGUF request path) | 112 | 5 |
| CyberSecEval | glm-5.3-flash | 277 | 13 |
| CyberSecEval | unknown | 438 | 0 |
| Deep-research | unknown (not recorded) | 10,919 | 502 |

The three eval exact-loop flags are all on the historical Qwen3-Coder-30B
entry; one other response on that entry repeats an eight-word shingle 105
times. Those historical entries do not record a llama.cpp build or llama-swap
alias. They are evidence of repetition, not proof about the current Flash-Next
model or the Nathanw build. Reviewed examples also show false-positive
shingles in ordinary structured maths/explanation text.

CSE's one exact-loop candidate is GLM-generated repetitive code; its repeated
regex structures do not by themselves establish a runaway generation.
Deep-research has one clear repeated-question reasoning candidate with no
recorded model/build identity. Of its 502 candidates, 500 have excerpts
consisting of a single repeated character, of unknown origin; keep those
separate from ordinary model-degeneration evidence. The remaining two are
one reasoning loop and one other shingle candidate. No build-specific
conclusion follows from these transcripts alone.

### Counts by month (UTC)

| Source | Month | Responses | Candidates |
| --- | --- | ---: | ---: |
| Eval | 2026-08 | 5,466 | 71 |
| Eval | 2026-10 | 105 | 4 |
| CyberSecEval | 2026-09 | 221 | 6 |
| CyberSecEval | 2026-10 | 604 | 12 |
| CyberSecEval | unknown | 2 | 0 |
| Deep-research | 2026-09 | 10,579 | 500 |
| Deep-research | 2026-10 | 340 | 2 |

CSE's producer dates live in meta.json/manifest.json. A metadata-only audit
recovered those dates without rerunning detectors or changing original
flags/excerpts; the original report's unknown dates are superseded by the
audit. Unknown historical model identities remain unknown.

### Cap evidence and preserved results

CSE has **18 logged calls in three usage files**, all from October: eight
recorded Qwen request-model calls and ten judge calls. All finish reasons
are `stop`, so **zero cap-exhausted calls among those 18**. These logs do
not cover all 827 transcript responses and contain no response IDs;
no positional join or inference of uncapped historical responses is made.
Eval and deep-research lack per-response finish/token evidence, so their
zero cap flags mean unknown exhaustion, not proof that caps were never hit.

Both original eval report hashes match before/after recovery. Reports and
hit files remain on their source hosts, with mode-0700 directories and
mode-0600 files. ai-services-stack's retained eval is `eval/` and its final
deep report is `deep-research-complete/` under
`/srv/eval-runner/loop-hunt-scan-20261015/`. CSE retains its original report
plus metadata/usage audits in
`/srv/cyberseceval/loop-hunt-scan-20261015/cse/`.

Exactly ten bounded excerpts were returned to the operator: seven from eval,
one CSE and two deep-research. No further excerpts were fetched. No excerpts,
source-file/message identifiers, settings or full transcripts enter git;
only counts and aggregate conclusions are recorded here. Replay selection
was pending before lh-01c; its local results follow below.

## Local Copilot scan (lh-01c, 2026-10-15)

The actual local layout uses workspace `chatSessions/*.jsonl` journals,
plus JSON/JSONL empty-window sessions. The adapter replays VS Code's
ObjectMutationLog operations into final session states; it does not count
streaming updates as separate responses. The protocol was checked against
the installed VS Code workbench source. All 48 synthetic-fixture tests pass,
including journal replay, partial tails, credential redaction, detector
positives/negatives and exact tool-argument matching. No production access,
model inference, client configuration changes or source-session writes occurred.

### Current Framework client limits

| Model ID | URL | maxInputTokens | maxOutputTokens | Tool calling | Thinking flag |
| --- | --- | ---: | ---: | --- | --- |
| qwen3.8-flash-next | http://framework.gibbsgreatly.xyz:8080/v1/chat/completions | 120000 | 8192 | true | absent |

This is the current allowlisted client configuration, not historical request
parameters. It supersedes the old 6144/2048 reference for planning C5's
client-limit comparison: **8192 versus 16384** output tokens. Record
**FND-client-limits as a candidate**, since 8192 is below the earlier test's
16384-token budget; it is not proof of cap exhaustion or a loop's cause.
No credential fields or values are exported.

### Coverage and counts

Read **5002 files/sessions, 24366 requests and 24067 responses**. All files
were readable; no partial journal tails were encountered. There were
**1465 mechanical candidates**. Flags overlap. Compression-only reasoning
adds 331 informational flags and does not by itself make a candidate.
Of 366403 recorded tool invocations, 215534 lack parseable saved arguments
(58.8%); exact tool-repeat coverage is therefore incomplete.

| Recorded request model ID | Responses | Candidates |
| --- | ---: | ---: |
| anthropic/Anthropic/claude-opus-4-6 | 84 | 0 |
| anthropic/Anthropic/claude-sonnet-4-6 | 66 | 0 |
| copilot/auto | 15265 | 1005 |
| copilot/claude-opus-4.6 | 432 | 0 |
| copilot/claude-sonnet-4.6 | 2771 | 138 |
| copilot/gpt-5-mini | 3555 | 125 |
| copilot/gpt-5.1-codex | 6 | 0 |
| copilot/gpt-5.3-codex | 308 | 5 |
| copilot/gpt-5.4 | 1292 | 84 |
| customendpoint/Framework Ollama/eval-gemma4-26b:q4-ctx128k | 8 | 7 |
| customendpoint/Framework Ollama/eval-gemma4-26b:q4-ctx32k | 2 | 2 |
| customendpoint/Framework Ollama/eval-qwen3-coder-next:q4_k_m-ctx256k | 6 | 0 |
| customendpoint/Framework Ollama/eval-qwen3.8-27b:ud-q4kxl-ctx128k | 2 | 0 |
| customendpoint/Framework Ollama/eval-qwen36-35b-a3b:q4_k_m-ctx128k | 6 | 1 |
| customendpoint/Framework Ollama/eval-qwen36-35b-a3b:q4_k_m-ctx32k | 1 | 1 |
| customendpoint/Framework Ollama/laguna-s-2.1:q4_k_m-ctx131k | 86 | 9 |
| customendpoint/Framework Ollama/laguna-s2.1-q8-ctx131k | 11 | 2 |
| customendpoint/Framework Ollama/qwen3-coder-next-q4km-ctx256k | 11 | 1 |
| customendpoint/Framework Ollama/qwen3.6-35b-a3b-q4km-ctx128k | 7 | 4 |
| customendpoint/Framework Ollama/qwen3.8-27b-q4kxl-ctx128k | 17 | 6 |
| customendpoint/Framework llama.cpp/Laguna-S-2.1-UD-Q4_K_M-00001-of-00003 | 12 | 4 |
| customendpoint/Framework/Llama-3.3-70B-Instruct-Q4_K_M | 4 | 2 |
| customendpoint/Framework/Qwen3 Coder 30B (Q4_K_M) | 1 | 1 |
| customendpoint/Framework/Qwen3.6-35B-A3B-UD-Q4_K_M | 5 | 3 |
| customendpoint/Framework/qwen3-coder-30b-phase6 | 28 | 13 |
| customendpoint/Nathanw strix-halo-llamacpp/glm-5.3-flash | 2 | 2 |
| customendpoint/Nathanw strix-halo-llamacpp/qwen3.8-flash-next | 9 | 6 |
| customendpoint/Nathanw strix-halo-llamacpp/qwen3.8-flash-next-q4 | 1 | 1 |
| customendpoint/Ollama (Framework)/eval-qwen3-coder-30b-a3b:q4_k_m | 3 | 1 |
| deepseek/deepseek-v4-flash | 6 | 6 |
| deepseek/deepseek-v4-pro | 12 | 12 |
| oaicopilot/deepseek-v4-flash::deepseek-v4-flash-anthropic | 6 | 6 |
| oaicopilot/deepseek-v4-pro | 12 | 12 |
| ollama/Ollama/deepseek-v3.1:671b-cloud | 6 | 6 |
| ollama/Ollama/qwen2.5-coder:14b | 24 | 0 |

| Month (UTC) | Responses | Candidates |
| --- | ---: | ---: |
| 2026-03 | 150 | 5 |
| 2026-04 | 9103 | 421 |
| 2026-05 | 13194 | 896 |
| 2026-06 | 1196 | 67 |
| 2026-07 | 53 | 24 |
| 2026-08 | 291 | 19 |
| 2026-09 | 72 | 28 |
| 2026-10 | 8 | 5 |

| Flag | Responses |
| --- | ---: |
| cut-off | 559 |
| dense-reasoning | 331 |
| loop | 36 |
| repetition | 859 |
| template-leak | 2 |
| tool-call-in-content | 1 |
| tool-malformed | 1 |
| tool-repeat | 64 |

### Review and replay decision

The saved Nathanw-labelled Flash-Next endpoints account for **10 responses,
7 candidates**: one exact reasoning loop, two other repetition candidates
and four cut-off responses. The exact-loop excerpt visibly repeats a short
self-referential reasoning phrase. The other two excerpts discuss alternative
Ansible backup strategies; repeated shingles alone do not confirm that those
responses degenerated. GLM has **2 responses, both cut off**, with no loop
flag. Saved provider labels are not verified served build identities: these
files establish neither a build SHA nor an engine-specific cause.

Nine bounded examples were reviewed: three Flash-Next reasoning candidates,
a malformed Qwen3.6 tool envelope, a Llama3 answer loop, a Qwen3.8-27B
reasoning loop, a Qwen3.6 literal-think/template loop, and two exact terminal
tool-repeat candidates (Laguna and Qwen3-Coder-Next). The latter have streaks
of 26 and 155 identical saved command arguments; repeated tool execution
can still be legitimate polling/retries, so these are not engine diagnoses.
No additional excerpts were fetched. The 559 cut-off flags include recorded
cancellations/incomplete responses and are not a count of exhausted budgets.

Full Copilot system prompts, tool schemas, wire requests and historical caps
are not reconstructed from these journals. Current client limits cannot be
attributed retrospectively. `copilot/auto` does not identify its underlying
model. History estimates count saved user/answer text only. The scan read
live journals, not an atomic snapshot of all sessions.

Private results remain only in the ignored
`artifacts/vscode-scan-20261015/`: summaries, client limits, hits, unreadable
audit and nine-example review selection. The directory is 0700 and files
0600; no excerpts, session identifiers, workspace names or source chats
enter git. The operator must pick sessions for lh-07; recommend the
Flash-Next exact-loop example V1 first. A fresh lh-01d capture is optional
if exact wire-level replay is wanted. lh-02 and production tests have not
started; no production access occurred during lh-01c.
