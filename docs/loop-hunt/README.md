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

Status: **lh-01–01c complete; V1/V9 selected; lh-02–04 complete; deployed; lh-05 complete; lh-06 complete and reviewed; lh-07 running; prior evidence preserved**
(2026-10-16). Decisions D-L1 to D-L7 are settled. The corrected plan leaves
parallel unset and requires the pilot to confirm the expected shared-pool
slot layout through `/props` and `/slots`; a different layout stops the pilot.

The [scan tools](../../scripts/loop-hunt/README.md) pass all 83 tests,
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
enter git. The operator selected V1 and V9 for lh-07, as recorded below. A fresh lh-01d
capture remains optional for exact wire-level replay. Production tests have
not started; no production access occurred during lh-01c.

### Operator replay selection and endpoint provenance (2026-10-15)

| Example | Response date (UTC) | Endpoint port | Engine | Selection |
| --- | --- | --- | --- | --- |
| V1, reasoning loop (requested Flash-Next) | 2026-10-07 00:33:05.746 | 8080 | operator map: llama-swap; actual served model/build unknown | retain |
| V9, Qwen3-Coder-Next tool repeat | 2026-09-16 00:20:10.762 | 11434 | Ollama | retain |
| V4, Qwen3.6 malformed tool envelope | 2026-09-15 22:06:56.378 | 11434 | Ollama | exclude: not llama.cpp |
| V7, Qwen3.6 template loop | 2026-09-09 03:52:33.723 | unknown for this exact model; provider history 11434 | unverified, likely Ollama | exclude: llama.cpp not established |

The operator supplied the engine map: :8080 before 2026-10-07 is the
hand-run Nathanw fork; from that date it is llama-swap and the served
entry determines the build; :11434 is Ollama; :1234 is LM Studio.
Endpoint evidence comes from local VS Code configuration history, not wire
captures. V1's provider/model maps to :8080 in a preceding October 7 config.
Its saved name has no build suffix, and direct :8080 requests do not prove
which entry llama-swap had loaded. No build SHA is inferred. V4 and V9
have exact provider/model matches in September 15/16 configurations on
:11434. V7's exact model is absent from saved configs; its named provider
uses :11434 in bracketing August 23/September 15 snapshots. This is
provider-level evidence, not proof of that response's port or engine.

V2, V3, V5, V6 and V8 are dropped from the replay selection. The private
review-selection file now retains V1/V9 only; the original scan hit file
is preserved. No new excerpts were fetched. Copilot saves neither the
system prompt nor full tool schemas, so these lh-07 replays will be
**reconstructions**, not exact historical requests. Keep lh-01d available
for a future exact capture; do not change the VS Code URL automatically.

The requested lh-01b CSE scan and deep-research recovery already completed
in commits 23bce712/2a06001b. Their results above remain authoritative:
CSE 827 responses/18 candidates; deep 10919 segments/502 candidates, with
two invalid source files explicitly excluded. Eval outputs remain preserved.
No repeat production scan is needed to finish that work.

## Session harness (lh-02, 2026-10-15)

Initial local validation passed **69 loop-hunt and 96 ctx-bugs tests**.
The current loop-hunt suite passes **75 tests** after the scoring/reporting
regressions below. Deterministic session regeneration ran twice with
a clean tracked-fixture diff. Full stand-in runs completed C1/C2/C3/C4/C5:
22/48/28/46/62 saved requests respectively (C3 includes imported C1 records).
C2 used four concurrent workers; C3 recorded overflow refusals; C1's three
CK pairs identified warm-only loops; C4's clean answers had no flags.
C5 completed 30 synthetic tool calls plus a final answer at each output
budget, with no flags. Its system measured 12288 tokens; largest prompts
were 120829 at the 8192 budget and 112635 at 16384.

[Tool usage and limits](../../scripts/loop-hunt/README.md#multi-turn-sessions-lh-02)
describe the launcher, continuation, reconstruction/replay, offline regrade
and bounded watcher. Private synthetic reports remain under ignored
`artifacts/harness-stub-20261015/`. Positive cache evidence is required for
warm-only attribution; refusals and crashes are not model/content findings.
CK reloads reset all slot caches, including C2's peers; resets and subsequent
cache counts are recorded for the pilot review. Nominal near-limit CK labels
always retain actual prompt counts. Production access remains approval-gated.

## Catalogue and deployment (lh-03/04, 2026-10-15)

Complete under loop-hunt-deploy approval through the pve-tiny production
profile. Qwen sess131k/sess262k and GLM sess131k override only ctx_size;
all other catalogue settings are unchanged. JSON gates and all 42
llama-builds tests passed. Playbook: ok=15, changed=1, failed=0.

The existing fork previous b02cb35f2 was selected as candidate without
compilation. Normal guarded swap-config wrote 44 entries; all seven required
session/candidate IDs and installed config bytes matched the generator.
Candidate /props capture ran under the shared lock without inference, then
restored qwen3-coder-next-upstream / b11514-de7fa0a3c and released the lock.
Both harness folders were copied. The earlier lock/rewrite conflict and
approved recovery are recorded in [lh-04](plan.md#lh-04-deploy).

Private Framework expectations: `/storage/artifacts/loop-hunt/builds-20261015/`
(0700), with props-candidate.json, current.json and candidate.json (0600).
They retain full props and validate fork current 9e21f2e53, fork previous
b02cb35f2 and upstream de7fa0a3c. Full SHAs are in the plan.

V1's served model/build remain unknown after the inconclusive journal
lookup; its saved Flash-Next label identifies only the requested model.
V1 replay covers Qwen on all three builds and GLM upstream. V9 replay covers
Qwen on all three builds; its historical endpoint was Ollama. Both are
reconstructions; optional lh-01d remains available for exact capture.

## Pilot and scoring correction (lh-05, 2026-10-15)

**Passed:** fresh run `/storage/artifacts/loop-hunt/20261015T010713Z-pilot`,
32 requests (29 warm turns plus three cold comparisons), 74/74 recall
answers correct. Four slots each n_ctx 131072 matched the layout gate.
All measured prompt counts matched server counts; every warm request after
the first reused cache. No loop, repetition, runaway, GPU or evidence error.
Warm turns 11/12 failed only the requested question-line formatting.

| Nominal CK | Actual prompt tokens | Warm cached | Cold cached | Cold seconds | Comparison |
| --- | ---: | ---: | ---: | ---: | --- |
| 64k | 65673 | 61539 | 0 | 114.9 | clean |
| 96k | 98431 | 94325 | 0 | 163.2 | clean |
| 131k | 118897 | 114801 | 0 | 193.8 | clean |

Each warm/cold payload differed only in cache_prompt. The final valid turn
represents the nominal 131k checkpoint with the unchanged 8192-token answer
allowance; the next turn did not fit. The run took roughly 23 minutes.
Original model/build restored, lock free and upgrade timer active were
independently verified; watcher terminal poll confirmed completion.

Earlier attempts exposed a watcher launch race and recall/format conflation.
The corrected launch creates the directory first, awaits run metadata, then
verifies the watcher's first successful poll. Recall now extracts exact
values between Qn/reference markers independently of line layout, which
receives its own instruction-following flag. Regression tests include the
actual synthetic pilot answers. The interrupted 15-request run regraded to
35/35 correct facts; pre-fix results, report, manifest and raw grades were
preserved byte-for-byte under its regrade-backups. Full history and hashes
are in [lh-05](plan.md#lh-05-pilot).

## Matrix (lh-06, complete and reviewed)

All 20 queued jobs completed on 2026-10-16. Including the passed pilot,
there are 793 primary completed request records: 761 new matrix records
plus 32 pilot records. Imported C1 rows in C3 are counted once. Failed pilot
and C5 attempts, and the interrupted cold request, remain separate evidence.

The preserved regrade gives 1434/1434 correct facts in accepted responses.
HTTP refusals are excluded from factual-accuracy denominators. No exact
loop, runaway or hidden-token flood was detected. Semantic coherence and
semantic looping remain pending lh-08; perfect literal recall does not
establish either.

| Model/build | Condition | Recall | Findings | Warm/cold |
| --- | --- | ---: | --- | --- |
| Qwen fork current | C1, seeds 1/2 | 148/148 | two line-format flags in pilot | six clean pairs |
| Qwen fork previous | C1, seeds 1/2 | 148/148 | one reasoning-repetition candidate | six clean checkpoint pairs |
| Qwen upstream | C1, seeds 1/2 | 148/148 | none | six clean pairs |
| GLM upstream | C1, seeds 1/2 | 170/170 | 74 question-line format flags; one completed-request GPU warning | six matching format-failure pairs |
| Qwen fork current | C2 | 80/80 | 20 capacity refusals | four clean; four refused pairs |
| Qwen fork previous | C2 | 80/80 | one reasoning-repetition candidate; 20 capacity refusals | four clean; four refused pairs |
| Qwen upstream | C2 | 83/83 | 20 capacity refusals | four clean; five refused pairs |
| GLM upstream | C2 | 100/100 | 44 question-line format flags; 20 capacity refusals | four matching format-failure; four refused pairs |
| Qwen, each build | C3, new turns only | 5/5 each | four context-limit refusals each | one refused pair each |
| Qwen, each build | C5, both output budgets | — | all six tasks done; identical final file-tree hash; no detector flags | no cold comparison |
| Qwen fork current | C4, 262k | 154/154 | five question-line format flags | five clean pairs |
| Qwen fork previous | C4, 262k | 154/154 | one reasoning-repetition candidate | five clean checkpoint pairs |
| Qwen upstream | C4, 262k | 154/154 | three completed-request GPU-warning flags | four clean; one cold GPU-warning pair |

C2 crossed the shared pool at round 8 for the Qwen builds and round 10 for
GLM, then completed the four planned extra rounds. Every model/build
recorded 20 HTTP 500 context-capacity refusals. Cold requests at the same
per-session sizes succeeded. C3 produced HTTP 400 context-limit refusals.
No silent token truncation was observed in accepted responses.

The previous fork's three repetition flags are reasoning-shingle candidates,
at C1/C4 seed-1 turn 4 (16462 prompt tokens) and C2 seed-6 turn 1 (4141).
They are not three established independent bugs; C1/C4 revisit the same
early-session material. There was no answer-repetition flag or factual loss.
Question-line flags likewise do not establish semantic collapse. The first
C4 format flag on the current fork was at 45097 tokens; upstream's first
C4 kernel flag was at 147573. These are detector/rule observations, with
semantic collapse context deferred to judging.

### Cold prompt reading near 250k tokens

| Build | Prompt tokens | Prompt read seconds | Prompt tok/s | Total request seconds |
| --- | ---: | ---: | ---: | ---: |
| Fork current b10814-9e21f2e53 | 250078 | 410.923 | 608.577 | 420.602 |
| Fork previous b10710-b02cb35f2 | 250186 | 608.773 | 410.968 | 615.593 |
| Upstream b11514-de7fa0a3c | 250110 | 2025.209 | 123.498 | 2036.727 |

All three cold cache counts were zero and all three final answers were
clean. Each cold payload exactly matched its own warm payload except cache
use. Cross-build histories have slightly different model answers, so these
are observed rates, not a controlled isolation of the cause.

Upstream's original final cold request hit the 1800-second client timeout
while still advancing at 93%. Under the operator-approved policy, requests
above 200000 measured prompt tokens now get 7200 seconds; others retain
1800. Only that unfinished job resumed. Its 65 saved rows were byte-identical
before regrading; the successful cold request became row 66 and records
client_timeout 7200. The completed timing shows that the original timeout
was too short for this observed prefill. Client waits/timeouts are now
autonomous plumbing, with server settings and test content held fixed.

Seven distinct amdgpu fence-fallback timer warnings were retained: one in
GLM C1 seed 2 and six in upstream C4. Three upstream events occurred during
the original interrupted cold request and therefore are in pending kernel
evidence, not completed-response flags. The successful retried cold request
had no GPU flag. No GPU reset, driver change or service intervention was
performed. These observations do not prove the cause of the rate difference.

### Measurement review and preservation

All 20 jobs passed model/build, four full-context slots, fixture/dependency
hash, request-setting, token-count and cleanup checks. Accepted requests
had exact rendered/server token agreement and zero evidence-capture errors.
All cold requests had zero cache reuse. The original model/build, free run
lock and active upgrade timer were independently verified after the matrix.
The passed pilot's result hash is unchanged.

All 83 tests pass. Recall extraction now separates repeated TRIAGE prefixes
and commas immediately before labelled Qn/reference fields from literal
values, while retaining exact-value negative tests and separate line-format
grading. The preserved canonical regrade withdraws the old previous-fork
recall/hallucination claims and the old GLM C2 0/100 result. Request/response,
token, timing and evidence fingerprints remained identical; completion
timestamps were preserved. C5's earlier counting failures and approved
complete-tool-exchange fix remain recorded in the plan; both failed attempts
are untouched. The earlier fork C5 runs used the old growth probe, so their
actual measured peaks are retained rather than claiming identical histories.

Private evidence root: /storage/artifacts/loop-hunt/campaign-20261015/.
Each run has regrade-backups; before-timeout-resume-20261016 preserves the
65-row checkpoint, original source/identity and pending raw evidence.
Matrix-analysis-before.json records invariant evidence fingerprints, and
matrix-review-ready.json binds all 20 final result hashes. Replay release
requires the reviewed hashes; no transcript excerpts enter git.

## Replays (lh-07, running)

The hash-bound matrix gate was released after review commit 02281038.
The first replay, V1 on fork current, completed all six requests and
restored its baseline. Each had 58 prompt tokens and zero warm/cold cache.
Seed 1 has repetition flags in both modes, seed 2 is clean, and seed 3
exhausted the 8192-token cap in both modes (finish_reason length). These
are two flagged seed pairs, not four independent bugs. No exact-loop,
transport or evidence-capture flag was recorded. Requests took 198–336
seconds each; full model reloads add to the campaign wall time. Remaining
builds/targets must finish before cross-build attribution or final findings.
Cap exhaustion alone is not a semantic-loop diagnosis. No prompts or new
transcript excerpts are returned. The campaign continues automatically.

All four V1 targets subsequently completed and passed cleanup. Each has
repetition candidates; current fork and upstream also have cap-exhausted
responses. Thus the observed flags are not exclusive to the fork. Final
channel/seed analysis waits for all targets. The scheduled upgrade service
started after GLM cleanup and blocked V9's first launch before any request
or directory existed. After it finished naturally, original model/build,
free lock and active timer were verified. The first permitted launch retry
preserved/skipped all four V1 jobs and launched V9 fork current as
loop-hunt-20261016t070130z.service, with a verified new safety watcher.
The failure and retry are retained in campaign.json and its backup. No
upgrade service, server setting or test content was changed.

The separately approved continuation is staged; matrix review has passed:
`loop-hunt-replay-after-matrix-20261015.service`. Private state lives at
`/storage/artifacts/loop-hunt/replay-campaign-20261015/continuation.json`.
It requires all 20 matrix jobs complete, cleanup verified and the agent's
completed matrix review with matching result hashes, then installs
tested reporting/seed-metadata corrections and runs the seven selected
targets with seeds 1–3 and warm/cold comparisons. It stops at lh-08.
The scorer corrections were installed only after matrix completion.

Private replay inputs are verified at
`/storage/artifacts/loop-hunt/replay-inputs-20261015/` (0700, files 0600).
They retain the exact saved first-user prompts, source/date/engine provenance
and explicit missing-context metadata. No prompts or additional transcript
excerpts enter git. The exporter needed a tested tool-channel fix for V9.

V9's source has repeated tool invocations. Historical tool schemas and agent
execution are unavailable, so a clean completion cannot establish absence
of the original tool loop. Replay reports state this coverage limit and
avoid claiming a synthetic full-context run. Replay seed metadata records
the three seeds already used by the runner; requests remain unchanged.

The preserved matrix regrade includes the comparison-order correction: a refused
pair is not comparable even when its successful peer has a flag. Model
requests and server settings stayed fixed.
