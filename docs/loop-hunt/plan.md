# Loop hunt: reproduce real-use looping on Framework

Planned 2026-10-15. lh-01 chat scan completed under approval on 2026-10-15;
no model test has run. Operator choices are pending before lh-02.

## Why

The context-size test (`docs/ctx-bug-test/`) found no looping, no
context-size bugs and no fork-vs-upstream difference for Qwen3.8-Flash-Next
under clean conditions: one request at a time, prompt cache off, fresh
context every request, prompts that always fit, outputs up to 16k. The
looping the operator saw in real use (GLM-5.3-Flash and Qwen3.8-Flash-Next,
attributed to the Nathanw engine) was **not reproduced**.

**Where the loops were seen (operator, 2026-10-15): VS Code (Copilot
agent mode against Framework) and the benchmark harnesses.** VS Code adds
two things nothing here tested yet: tool calling (a large system prompt
and tool schemas every turn, tool calls parsed by llama.cpp's
chat-template/tool parser, which differs between the fork b10814 and
upstream b11514), and Copilot's own client limits
(`~/.config/Code/User/chatLanguageModels.json`; last recorded at 6144
input / 2048 output tokens, docs/framework-ip-and-port/README.md). The
lh-01c local check on 2026-10-15 instead found **120000 input / 8192 output**
for `qwen3.8-flash-next`, with tool calling enabled and no explicit thinking
flag. C5 must compare that current 8192 output limit against 16384. A small
output cap could cut off reasoning and trigger client retries; the current
configuration alone does not establish any historical request budget or
prove that this caused a loop. The 84-tool
tool-calling sweep only ever ran on LM Studio
(docs/framework-ubuntu/local-ai-development.md), never llama.cpp.

This plan tests the conditions that test left out, which are where real use
differs:

| Not covered by ctx-bug-test | Covered here |
|---|---|
| Long multi-turn sessions | Sessions that grow turn by turn to 131k (and 262k) |
| Prompt cache reuse (`cache_prompt`) | On, as clients use it, with a cold replay to compare |
| Parallel slots | 4 slots, 4 concurrent sessions (production default) |
| Context overflow | Sessions that run past `--ctx-size` |
| Older fork build | Fork `previous` (`20261008-b02cb35f2`, before the 10-08 Vulkan FA NaN fixes) |
| Real conversations | Scan Open WebUI, benchmark and VS Code Copilot transcripts for real loops and replay them |
| Tool calling (agent mode) | C5: Copilot-style agent sessions with tool schemas; a capture proxy records real VS Code sessions for exact replay |
| Client limits | VS Code's `maxInputTokens`/`maxOutputTokens` read and tested as a cause |
| Semantic looping, context echoing | Blind judge pass |

Method follows the operator's "Large-Context Open-Weight Model Evaluation
Framework" (2026-10-15): differential engine testing with identical
controls, the stability-investigation method (save context, restart,
reload, repeat), degeneration categories, coherence-collapse context, and
findings in its FND format with a Context Integrity Score.

**The key test.** For a session that degenerates, regenerate the same turn
from the same history two ways: **warm** (the server's cached state, as in
real use) and **cold** (fresh slot, `cache_prompt: false`, after a model
reload). Degeneration only when warm points at a runtime/KV-cache bug;
degeneration in both points at the model or the content. Outputs may differ
byte for byte either way (llama.cpp is not batch-invariant), so the
comparison is on the degeneration flags, not bytes.

## Reused from ctx-bug-test

Everything in `scripts/framework-ctx-bugs/`: detectors (loop, repetition,
dense-reasoning, hidden-tokens, template-leak, GPU-error), the stdlib
Redis lock, `/props` identity checks, llama-swap readiness waits and
infrastructure-failure handling, checkpoint/resume, regrade, `run.sh`, the
overnight watcher, the D10 upgrade-timer pause, `guarded_swap_config.sh`,
and the build-expectations helper. Agent rules are the same as
`docs/ctx-bug-test/plan.md` "Rules for the agent" (rules 1–8, including the
production-hook-free commit and stop points), plus the operator's standing
instruction to work autonomously and stop only for approvals, decisions and
errors.

**Current operator override (2026-10-15):** fix local measurement/scoring
bugs autonomously with regression tests; preserve old evidence before
regrading and record corrections in Result. Launch/plumbing permits up to
two retries per run after verified cleanup. Use code when plan paths/fields
contradict it. Stop for changes to measured models, builds, conditions,
sizes, sampling, settings or prompts; production changes outside loop-hunt;
the same failure after two fixes; failed cleanup; or reaching lh-08/lh-10.
These instructions supersede the earlier blanket failed-gate stop and
one-retry rules. Matrix (both batches) and the seven selected replay targets
have separate named approvals; their prerequisite pilot review has passed.
Production wrappers, named task scopes and per-run timer/model/lock cleanup
still apply. No broader production approval is implied.

## The matrix

| | |
|---|---|
| Builds | fork `current` (20261008-9e21f2e53, b10814), fork `previous` (20261008-b02cb35f2, served as the fork **candidate** for this test), upstream `current` (20261008-de7fa0a3c, b11514). Recheck with `llama-builds status` first; if any link moved, stop and ask |
| Models | `qwen3.8-flash-next-q4` on all three builds. `glm-5.3-flash` on upstream only (the fork has no glm5next arch), D-L4. Laguna is out (fork broken, upstream clean) |
| Server settings | Production-like: catalogue settings, **default batch sizes, `--parallel` not set, prompt cache on** (D-L2). With `--parallel` unset llama.cpp picks 4 slots sharing **one unified KV pool**, so a single conversation can use the whole context and concurrent ones compete for it. ctx-bug-test phase 1 saw this on the live `qwen3-coder-next-upstream` entry (`total_slots` 4, per-slot `n_ctx` 131072). Variants `sess131k` (ctx 131072) and `sess262k` (ctx 262144, Qwen only), neither setting `parallel` |
| Sampling | D-L3 |
| Per-turn cap | `max_tokens 8192` per assistant turn; hitting it is a `runaway` finding |

Conditions per build:

| Id | What | Why |
|---|---|---|
| C1 | One session to ~131k, cache on | Long history + cache reuse |
| C2 | Four concurrent sessions (different seeds/content) sharing the 131k pool: each grows to ~32k (pool nearly full), then all keep going for 4 more turns past the point where the pool runs out | Slot/KV sharing and pool exhaustion under load, like deep-research. Records what the server does when the pool is full (errors, cache eviction and recompute, context shift) |
| C3 | C1's session continued 3 turns past `n_ctx` | Overflow / context-shift behaviour |
| C4 | One session to ~262k on `sess262k` (Qwen only) | The size Qwen used to serve at |
| C5 | Copilot-style agent session: a ~12k-token system prompt plus 40 tool schemas (the captured real ones from lh-01d if available, else synthetic ones shaped like Copilot's: read_file, grep_search, run_in_terminal, replace_string_in_file, ...); the harness executes fake tools that return synthetic files/output; a coding task that needs ~30 tool calls; streaming on; grows to ~131k. Run twice: with the operator's real VS Code output limit (from lh-01c) and with 16384 | Agent loops: the same tool call repeated, malformed tool calls, reasoning leaking into content or tool arguments, cut-off answers followed by retries |
| CK | Warm-vs-cold replay at 64k, 96k and 131k in C1 (and 196k/262k in C4); in C2 at 16k, 32k and at the first turn after the pool runs out | Runtime vs model |

Two seeds for C1, one C2 group, C3 once, C4 once per build.

## The synthetic session

Generated deterministically (seeded) like ctx-bug-test's prompts, so every
build gets the same user turns. An agent-style incident investigation:

- Turn 1 (system + user) sets rules that must hold every turn: start each
  reply with `[TRIAGE]`, end with `ref: INC-<n>`, no bullet points, answer
  only from the provided material, say `NOT PROVIDED` otherwise.
- Every later user turn appends one ~6k-token tool output (logs, config
  diffs, ticket text; synthetic, with planted facts) and asks 2–3 questions:
  one about this turn's material, one about material from an earlier turn
  (spread across early/middle/late history), sometimes one about something
  never provided.
- The history sent back each turn holds the user turns and the model's
  **answers only**, without reasoning (what Open WebUI and the deep-research
  agent send).
- About 20 turns reach ~131k; ~40 reach ~262k.

Per turn the harness records: prompt tokens, cached tokens (`timings`),
generated tokens, tok/s, every ctx-bug-test detector, rule checks,
recall answers, and a turn-to-turn similarity score (how much of this
answer repeats earlier answers: context echoing / semantic looping
precursor). The report draws each session's flags against context tokens:
the framework's "coherence collapse context".

## Time

From ctx-bug-test (Qwen prompt ~600 tok/s on defaults, generation ~25
tok/s): a cached turn reads ~6k new tokens (~10 s) and writes up to 8k
(usually far fewer). Roughly 1–1.5 h per 131k session, 2.5–3 h at 262k,
C2 ~3 h for the group. Per Qwen build ≈ 7–8 h; three builds ≈ 22 h; GLM
(slower) ≈ 6 h; total about 28–30 h, run as **two nights**. Pilot first:
one C1 session on fork `current`, about 1.5 h.

## Decisions (operator, 2026-10-15: all as recommended)

| # | Question | Decision |
|---|---|---|
| D-L1 | Scan Open WebUI's chat history on Framework for real loops? It reads private chats; only flagged excerpts are shown to you, nothing leaves Framework until you approve | **Yes.** Real examples are the most direct evidence |
| D-L2 | Server settings | **Production-like** (default batches, parallel unset: default 4 slots with a unified KV pool, cache on). Risk: a long first prefill can hit the known Vulkan hang; recorded as a finding, the run continues |
| D-L3 | Sampling | **What real clients send**, taken from the Open WebUI history in lh-01 if present; otherwise llama-server's defaults for that entry (no sampling in the request). Recorded per run |
| D-L4 | Include GLM-5.3 (upstream only) | **Yes, C1 and C2.** It was part of the original complaint; it can only be compared with itself (warm vs cold, short vs long), not with the fork |
| D-L5 | Include the Q2 Qwen | **Only if lh-01 finds real loops on it** |
| D-L6 | Judge for semantic looping / context echoing | **Cloud judge, blind**, using the existing manual procedure in `docs/framework-ubuntu/benchmarks.md` §5 (operator uploads batches) |
| D-L7 | 262k sessions (C4) | **Yes**, one per Qwen build |

## Execution steps

Same agent rules as ctx-bug-test. Operator prompt:

> Continue docs/loop-hunt/plan.md.

### Status

| Step | Runs on | Approval | Status |
|---|---|---|---|
| lh-00-decisions | operator | — | done 2026-10-15 (all seven as recommended) |
| lh-01-chat-scan | local, then Framework (read-only source) | `loop-hunt-chat-scan` | done 2026-10-15 (12 chats, 14 assistant messages, 0 hits; server-default sampling/Q2 exclusion settled) |
| lh-01b-transcript-scan | local, then production LXCs (read-only sources) | `loop-hunt-transcript-scan` | done 2026-10-15 (CSE and deep recovery complete; all sources reported; eval preserved; 2 unreadable deep files) |
| lh-01c-vscode-transcripts | local (operator's workstation) | — | done 2026-10-15 (5002 sessions, 24067 responses, 1465 candidates; V1/V9 selected) |
| lh-01d-capture-proxy | local (operator's workstation) | — | deferred, available for exact capture (V1/V9 reconstructions selected) |
| lh-02-session-harness | local | — | done 2026-10-15 (69 + 96 tests; deterministic fixtures; C1–C5 full stub runs) |
| lh-03-catalogue | local | — | done 2026-10-15 (only two models' variants; JSON gate and 42 generator tests pass) |
| lh-04-deploy | Framework (production) | `loop-hunt-deploy` | done 2026-10-15; guarded rewrite, tools and all three build identities verified |
| lh-05-pilot | Framework (production) | `loop-hunt-pilot` | done 2026-10-15; 32 requests, 74/74 recall, three clean CK pairs; cleanup verified |
| lh-06-matrix | Framework (production) | `loop-hunt-matrix` | running 2026-10-15; 20 remaining jobs queued, two batches |
| lh-07-replay-real | Framework (production) | `loop-hunt-replay` | queued 2026-10-15; seven targets, waiting for completed matrix and cleanup |
| lh-08-judge | local + operator | — | todo |
| lh-09-writeup | local | — | todo |
| lh-10-cleanup | Framework (production) | `loop-hunt-cleanup` | todo |

#### lh-00-decisions

Done 2026-10-15: the operator chose the recommended answer for all seven
(chat scan yes; production-like settings; client sampling; GLM single +
concurrent; Q2 only if the scan finds loops on it; blind manual cloud
judge; 262k one session per Qwen build).

#### lh-01-chat-scan

```yaml
id: lh-01-chat-scan
title: Find real loops in Open WebUI history (D-L1)
depends_on: [lh-00-decisions]
runs_on: framework
approval: loop-hunt-chat-scan
change: >
  Add scripts/loop-hunt/snapshot_sqlite.py: opens the live database
  read-only (sqlite3 URI file:<path>?mode=ro) and writes a consistent
  snapshot with SQLite's online backup API (Connection.backup), which
  includes committed WAL content; then runs PRAGMA integrity_check on the
  snapshot and exits non-zero unless it says ok. Never `cp` a live
  SQLite database (it can miss WAL data or copy a torn state).
  Add scripts/loop-hunt/scan_openwebui.py (stdlib only; uses
  scripts/framework-ctx-bugs/detectors.py). It opens the SNAPSHOT
  read-only, walks every chat's messages, and for each
  assistant message runs loop(), repetition() and the hidden-token /
  template-leak string checks, and estimates the conversation's token
  length up to that message (chars/3.5). Output, written only on
  Framework under /storage/artifacts/loop-hunt/chat-scan-<date>/:
  hits.jsonl (chat id, message index, model id as stored, timestamp,
  estimated history tokens, flags, the request parameters Open WebUI
  stored, a 400-character excerpt around the repeat) and summary.md
  (counts by model id, by month, by history size bucket). Full chats are
  never copied anywhere else. Tests use a small fixture database with a
  looping chat and a clean chat.
scope:
  allowed_paths:
    - scripts/loop-hunt/
    - docs/loop-hunt/
preflight: >
  Target: steve@framework.gibbsgreatly.xyz, Open WebUI history. Read-only
  access to the live chat database via SQLite backup, then a scan of the
  snapshot only. Mutating only the installed scanner files in ~/loop-hunt/
  and the dedicated /storage/artifacts/loop-hunt/ directory (0700, steve),
  with mode-0600 outputs in chat-scan-<Framework date>/. The full snapshot
  is deleted by an EXIT trap on success or failure. Return summary counts
  and at most ten flagged 400-character excerpts with chat/message IDs;
  do not return stored parameters or full chats. Keep hits.jsonl on Framework.
  Out of scope: model loads/inference, service changes, live DB writes,
  other artifact directories, full-chat exports and cloud uploads.
commands:
  - "rsync -a --exclude __pycache__/ scripts/loop-hunt/ scripts/framework-ctx-bugs/detectors.py steve@framework.gibbsgreatly.xyz:loop-hunt/"
  - |
    ssh steve@framework.gibbsgreatly.xyz 'bash -se' <<'REMOTE'
    D=/storage/artifacts/loop-hunt/chat-scan-$(date +%Y%m%d)
    sudo -n install -d -m 0700 -o steve -g steve /storage/artifacts/loop-hunt
    install -d -m 0700 "$D"
    trap 'rm -f "$D/webui.db.copy" "$D/webui.db.copy-wal" "$D/webui.db.copy-shm" "$D/webui.db.copy-journal"' EXIT
    sudo -n python3 ~/loop-hunt/snapshot_sqlite.py /mnt/container-storage/openwebui-data/webui.db "$D/webui.db.copy"
    sudo -n chown steve: "$D/webui.db.copy"
    python3 ~/loop-hunt/scan_openwebui.py --db "$D/webui.db.copy" --out "$D"
    cat "$D/summary.md"
    python3 - "$D/hits.jsonl" <<'PYTHON'
    import itertools
    import json
    import sys
    fields = ('chat_id', 'message_index', 'message_id', 'model_id', 'estimated_history_tokens', 'flags', 'excerpt')
    with open(sys.argv[1]) as source:
        for line in itertools.islice(source, 10):
            hit = json.loads(line)
            print(json.dumps({field: hit[field] for field in fields}, ensure_ascii=False))
    PYTHON
    REMOTE

gates:
  - id: tests
    cmd: "python3 -m unittest discover -s scripts/loop-hunt -p 'test_*.py'"
    expect: "exit 0, including a snapshot test against a WAL-mode fixture with uncommitted-to-main-file (WAL-only) rows: the snapshot contains them and integrity_check is ok"
    critical: true
  - id: summary
    cmd: "(second command)"
    expect: "summary.md printed; if webui.db is not at that path, stop and report what is in /mnt/container-storage/openwebui-data/"
    critical: true
```

Then show the operator summary.md and up to 10 hit excerpts, and stop. The
operator picks which chats (if any) to replay in lh-07 and whether D-L3/D-L5
change. Record the answer. Delete `webui.db.copy` after the scan; keep
hits.jsonl. Nothing from the scan goes into git except counts.

Result: done 2026-10-15 under explicit `loop-hunt-chat-scan` approval.
Local preparation passed before Framework access. All 17 tests pass, including committed
WAL-only rows, integrity checks, read-only connections, failure cleanup,
exclusive/private output files, clean and looping chats, alternate branches,
broken links, literal markers and a 400-character excerpt limit. Both CLI
help commands pass. The source is not checkpointed or written. The new snapshot uses DELETE
journaling so it is self-contained; stale snapshot sidecars are refused. The scanner
uses saved history parent links and does not double count Open WebUI's flat
active-path copy. Literal hidden-token strings are distinguished from
invisible token floods, which chat text cannot prove. Stored parameters
retain chat/message provenance instead of inferred sampling defaults.
The production command prepares only its dedicated artifact directory and
uses an EXIT trap to delete the full snapshot even if scanning fails;
summary and up to ten excerpts are returned only after explicit approval.
The approved commands then ran sequentially on Framework. Online backup
printed `SNAPSHOT-OK` with integrity_check ok. The scanner printed
`SCAN-OK: 12 chats; 14 assistant messages; 0 hits` and summary.md; no hit
excerpts exist. All assistant messages are from 2026-07 and estimate <32k
history tokens, with zero broken/cyclic history links. Counts by stored model
are in README; there are no target Qwen Q4/Q2 or GLM assistant messages.
No target-model client sampling can be derived from this history, and zero
hits do not refute the original looping complaint.

The EXIT trap deleted the full snapshot and sidecars. A subsequent read-only
check confirmed their absence and private permissions on the retained
summary.md and empty hits.jsonl in
`/storage/artifacts/loop-hunt/chat-scan-20261014/` (Framework date).
No live DB writes, model loads/inference or service changes occurred. No
chat excerpts or stored parameters were returned or copied locally; only
aggregate counts are recorded in git. No later step has run.

Operator decisions (2026-10-15): D-L3 server-default sampling (no sampling
fields in requests) and Q2 excluded under D-L5 are confirmed. Replay is not
skipped: complete lh-01b and then the added VS Code investigation first.


#### lh-01b-transcript-scan

lh-01 found no Qwen or GLM chats in Open WebUI (12 chats, July, other
models, zero hits), so the operator's loops happened elsewhere. Operator
decisions after lh-01 (2026-10-15): sampling = server defaults (D-L3);
Q2 stays excluded (D-L5); real-chat replay waits for this scan.

```yaml
id: lh-01b-transcript-scan
title: Scan benchmark and agent transcripts for real Qwen/GLM loops
depends_on: [lh-01-chat-scan]
runs_on: production LXCs (read-only)
approval: loop-hunt-transcript-scan
change: >
  Extend scripts/loop-hunt/scan_openwebui.py into a general scanner
  (keep the Open WebUI mode) with adapters for: (a) lm_eval
  samples_*.jsonl (model response = resps/filtered_resps; model id and
  run settings from the run's results/run.json next to it);
  (b) CyberSecEval response JSON on cse-controller; (c) deep-research
  saved sessions (JSON). For each response run loop(), repetition(),
  the hidden-token/template-leak string checks and a new
  `cap-exhausted` check (response or reasoning ends at the run's token
  cap with no final answer), and record model id, build/alias if
  recorded, date, run id, prompt size estimate and settings. Same
  privacy rules as lh-01 (outputs 0600 on the host they were read on;
  only counts and up to 10 excerpts are shown). Tests with one fixture
  per adapter.
  Discovery first, read-only, and stop if a location differs:
  ai-services-stack `/srv/eval-runner/results/` (docs/eval-runner/README.md);
  cse-controller `/srv/cyberseceval/runs/<run>/responses.json` (written by
  terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py);
  deep-research sessions (terraform/lxc/ansible/files/deep-research-agent/README.md,
  `--list-sessions`). Where the repo's code and its docs disagree on a
  path, the code wins: use the code's path and note it in the Result,
  no need to stop. Reach each host the way its existing docs do;
  write nothing outside a new `loop-hunt-scan-<date>/` directory there.
scope:
  allowed_paths:
    - scripts/loop-hunt/
    - docs/loop-hunt/
gates:
  - id: tests
    cmd: "python3 -m unittest discover -s scripts/loop-hunt -p 'test_*.py'"
    expect: "exit 0"
    critical: true
```

Report per source: responses scanned, hits by model and month, and
separately `cap-exhausted` counts (budget exhaustion, not looping). Show
up to 10 excerpts and stop: the operator picks replays for lh-07 (or
none). If benchmark sources have no loop hits, record that absence. The operator
has already identified VS Code Copilot agent mode as the other source; the
local client transcripts are covered by lh-01c. Do not ask where again.

Local preparation (2026-10-15): the general entry point and three adapters
are built. All 29 tests pass, preserving the 17 Open WebUI/snapshot tests
and adding fixtures for every adapter, clean negatives, cap evidence,
actual-vs-requested identity, raw/extracted deduplication, agent-source
pairing, unknown metadata, private output, failure cleanup and escaped
metadata refusal. No lh-01b production discovery or scan has run.

Preflight for `loop-hunt-transcript-scan` (operator approved 2026-10-15;
initial execution stopped at the deep-research failure; operator-authorized
recovery completed below):

- Targets: production LXCs `ai-services-stack` (`root@192.168.50.11`)
  and `cse-controller` (`root@192.168.100.70`), both on pve-tiny. Use
  `with-secrets-prod-tiny` with this task approval, as their existing docs do.
- Read-only discovery and source reads: eval `samples_*.jsonl` under
  `/srv/eval-runner/results/`; CSE `responses.json` under
  `/srv/cyberseceval/runs/`; deep-research sessions from its Docker mount
  at `/home/app/.deep-research-agent`. Only mount metadata and directory
  counts are printed during discovery, never Docker environment/config.
  Use the producer code's paths where old docs differ. A missing/different
  location stops the step before any scan or source relocation.
- Writes: only new mode-0700 `/srv/eval-runner/loop-hunt-scan-20261015/`
  and `/srv/cyberseceval/loop-hunt-scan-20261015/`, with tools in `tools/`
  and mode-0600 reports in source-specific subdirectories. Existing scan
  directories/reports are not reused or overwritten.
- Return counts by source/model/month, separate cap-exhausted counts, and
  **at most ten excerpts total across all sources**, each <=400 characters.
  Source transcripts and full hit/settings files stay on their source hosts.
- Out of scope: inference, model switching, agents/tasks, deployments,
  service changes, source-transcript writes/copies, Docker config changes,
  cloud uploads, other directories, VS Code history (lh-01c is later).

Exact commands, sequential with inspection/stop at every failed gate:

```bash
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny ssh root@192.168.50.11 'python3 -' <<'PYTHON'
import json
from pathlib import Path
import subprocess
print('Host:', Path('/etc/hostname').read_text().strip())
root = Path('/srv/eval-runner/results')
assert root.is_dir(), 'eval root differs; stop'
print('eval root:', root, 'sample files:', sum(1 for _ in root.rglob('samples_*.jsonl')))
mounts = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .Mounts}}', 'deep-research'], text=True))
matches = [m for m in mounts if m.get('Destination') == '/home/app/.deep-research-agent']
assert len(matches) == 1, 'deep-research mount differs; stop'
sessions = Path(matches[0]['Source'])/'sessions'
assert sessions.is_dir(), 'deep-research sessions directory differs; stop'
print('deep-research sessions:', sessions, 'session files:', sum(1 for _ in sessions.glob('session_*.json')))
PYTHON
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny ssh root@192.168.100.70 'python3 -' <<'PYTHON'
from pathlib import Path
print('Host:', Path('/etc/hostname').read_text().strip())
root = Path('/srv/cyberseceval/runs')
assert root.is_dir(), 'CSE runs root differs; stop'
print('CSE root:', root, 'response files:', sum(1 for _ in root.rglob('responses.json')))
PYTHON
```

Inspect both discoveries: the host names must be the intended LXCs and the
paths must match the producer code. If an existing source directory has no
files, report it as unavailable response evidence (zero responses evaluated),
not as proof of no loops. Do not search other paths without review. Missing
or different source locations stop the step. After discovery passes:

```bash
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny ssh root@192.168.50.11 'umask 077; D=/srv/eval-runner/loop-hunt-scan-20261015; test ! -e "$D" && mkdir "$D" && mkdir "$D/tools"'
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny ssh root@192.168.100.70 'umask 077; D=/srv/cyberseceval/loop-hunt-scan-20261015; test ! -e "$D" && mkdir "$D" && mkdir "$D/tools"'
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny rsync -a scripts/loop-hunt/scan_openwebui.py scripts/loop-hunt/transcript_scan.py scripts/loop-hunt/snapshot_sqlite.py scripts/framework-ctx-bugs/detectors.py root@192.168.50.11:/srv/eval-runner/loop-hunt-scan-20261015/tools/
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny rsync -a scripts/loop-hunt/scan_openwebui.py scripts/loop-hunt/transcript_scan.py scripts/loop-hunt/snapshot_sqlite.py scripts/framework-ctx-bugs/detectors.py root@192.168.100.70:/srv/cyberseceval/loop-hunt-scan-20261015/tools/
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny ssh root@192.168.50.11 'bash -se' <<'REMOTE'
D=/srv/eval-runner/loop-hunt-scan-20261015
export PYTHONDONTWRITEBYTECODE=1
python3 "$D/tools/scan_openwebui.py" --format lm-eval --root /srv/eval-runner/results --out "$D/eval"
S=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/home/app/.deep-research-agent"}}{{.Source}}{{end}}{{end}}' deep-research)
test -n "$S" && test -d "$S/sessions"
python3 "$D/tools/scan_openwebui.py" --format deep-research --root "$S/sessions" --out "$D/deep-research"
cat "$D/eval/summary.md" "$D/deep-research/summary.md"
REMOTE
TASK_APPROVAL=loop-hunt-transcript-scan ./with-secrets-prod-tiny ssh root@192.168.100.70 'bash -se' <<'REMOTE'
D=/srv/cyberseceval/loop-hunt-scan-20261015
export PYTHONDONTWRITEBYTECODE=1
python3 "$D/tools/scan_openwebui.py" --format cse --root /srv/cyberseceval/runs --out "$D/cse"
cat "$D/cse/summary.md"
REMOTE
```

Only after summaries pass, read bounded excerpts from the retained hits on
the source hosts, with one combined ten-excerpt budget. Print only source,
file/index/run pointer, model, flags, estimated prompt tokens and excerpt;
never print prompts or stored settings. Verify output permissions and exact
source paths without copying full transcripts. Then stop for replay choices.
The operator has already identified VS Code Copilot agent mode as the other
source of loops; do not ask where they were seen again if benchmarks have
no exact-loop hits. Record that absence and keep lh-01c as the next step.

Initial result: partial, stopped 2026-10-15 after a failed scan command, under the
operator's explicit `loop-hunt-transcript-scan` approval. Both read-only
discovery gates passed: intended LXC hostnames, 43 eval sample files, 34
deep-research session files and 78 CSE response files. The deep-research
session volume resolves to
`/var/lib/docker/volumes/ai-services-deep-research-config/_data/sessions`.
Private scan directories and scanner files were installed on both LXCs,
strictly inside the two approved loop-hunt-scan-20261015 directories.

The eval adapter completed: **43 files, 5,571 responses, 75 flagged responses,
0 evidence-backed cap-exhausted flags**. These are mechanical candidates,
not 75 confirmed loops; the model/month/flag breakdown has not been read.
Its outputs remain on ai-services-stack in
`/srv/eval-runner/loop-hunt-scan-20261015/eval/`.

The following deep-research scan exited 1 with the generic input-schema/JSON/
permissions error before publishing a new report. Its precise cause is not
yet established. The enclosing `bash -se` stopped immediately, so neither
summary was printed, no excerpts were returned, and the later CSE scan did
not run. No post-failure production commands, transcript exports, model
loads/inference or service changes were performed. Later steps remain pending.

Required next action for operator review: a read-only, schema-only diagnostic
on the failed deep-research input (failing file pointer, exception class and
JSON key/type structure only; no prompt/response text or settings), followed
by a local adapter fix with a synthetic regression fixture if needed. Preserve
the completed eval outputs; do not rerun the directory-creation commands or
overwrite them. Rerun the failed/remaining scans only after the operator
resolves this stop. No proposed diagnostic has run yet.


Recovery result: done 2026-10-15 under the same task scope, explicitly
approved by the operator. The operator authorized independent CSE scanning,
usage.jsonl finish reasons, a schema-only deep diagnostic, a tested adapter
fix, a deep-only retry and one combined report with at most ten excerpts.

- CSE: 78 files, 827 response segments, 18 candidates (1 loop, 18 repetition).
  usage.jsonl contains only 18 logged calls across 3 files, all finish_reason
  `stop`; zero cap-exhausted calls in that logged subset. Usage has no
  response IDs and includes judges/retries, so no positional response join
  was made. This does not prove all historical responses avoided the cap.
- Deep diagnostic: 2 invalid-JSON files; readable files match the expected
  UI-event schema. Only keys/types, exception classes and file pointers
  were returned by the diagnostic, never transcript text. The synthetic
  incomplete-session regression fixture reproduces the failure.
- Deep retry: 34 files, 32 readable, 10,919 response segments, 502 candidates
  (501 loop, 502 repetition). Invalid files are explicitly excluded with
  coverage counts and a private unreadable.jsonl audit. Missing historical
  model/build identities remain unknown. Session timestamps fill missing
  event dates. The final dated report is in deep-research-complete/;
  the first recovered pass is retained separately in deep-research/.
- Eval was never rerun or rewritten. Both original hits/report hashes match
  before/after. Its 75 candidates include 70 shingle hits, 1 compression-only
  hit and 4 template leaks; all 3 exact loops are historical Qwen3-Coder-30B.
  A further answer on that entry has an eight-word shingle occurring 105 times.
- Metadata-only CSE audit recovered dates from the producer's meta.json and
  manifest.json, preserving all 18 original flags/excerpts without detector
  reruns. Aggregate model/month counts and usage evidence are in README.
- The large deep group has 500 single-character-only excerpt hits of unknown
  origin, separate from one clear repeated-question reasoning candidate and
  one other shingle candidate. Reviewed CSE regex code and some eval maths
  examples are not sufficient evidence of degeneration. No build attribution
  is established by these transcripts alone.
- Recovery code commit: `23bce712`. All 34 local tests pass, including the malformed-session regression,
  finish-reason aggregation, metadata provenance and session-date fallback.
  Only approved scan directories were written. Report directory/file
  permissions were verified private; no inference, services or source
  transcripts were changed.
- Exactly 10 excerpts were returned (7 eval, 1 CSE, 2 deep), prioritizing
  exact loops and repeated shingles. No excerpts or private source pointers
  enter git. All source transcripts/hit files stay on their source hosts.

Replay selections remain for the operator; lh-01c is the next investigation.

#### lh-01c-vscode-transcripts

Runs on the operator's workstation, where this Codex session runs; no
production access. VS Code keeps Copilot chat sessions locally.

```yaml
id: lh-01c-vscode-transcripts
title: Scan VS Code Copilot chat sessions and read the client limits
depends_on: [lh-01b-transcript-scan]
runs_on: local
change: >
  Add a Copilot adapter to scripts/loop-hunt/scan_openwebui.py for VS
  Code chat session files: ~/.config/Code/User/workspaceStorage/*/chatSessions/*.json
  and ~/.config/Code/User/globalStorage/emptyWindowChatSessions/*.json
  (if the layout differs, use what is there and note it). Per response
  record: model id, date, workspace (hashed), request count in the
  session, approximate history size, and flags: loop, repetition,
  template-leak (including literal <think>, </think> or reasoning text in
  content), cut-off answers, and `tool-repeat` (the same tool with the
  same arguments 3 or more times in a row) and `tool-malformed`
  (unparseable tool-call text in content). Also read
  ~/.config/Code/User/chatLanguageModels.json and record, per Framework
  model entry, url, model id, maxInputTokens, maxOutputTokens and any
  tool/thinking flags (no API keys: never print or store the key field).
  Outputs only under docs/loop-hunt/artifacts/vscode-scan-<date>/ (git
  ignored, 0600). Tests with fixture session files.
scope:
  allowed_paths:
    - scripts/loop-hunt/
    - docs/loop-hunt/
  forbidden_actions:
    - "Copying session files anywhere else, or printing API keys"
gates:
  - id: tests
    cmd: "python3 -m unittest discover -s scripts/loop-hunt -p 'test_*.py'"
    expect: "exit 0"
    critical: true
```

Show the operator: the client limits table, counts by model/month/flag,
and up to 10 excerpts; the operator picks sessions to replay in lh-07.
If maxOutputTokens for a reasoning model is far below what its
reasoning needs, record that as finding candidate FND-client-limits.

Result (2026-10-15): **complete; V1/V9 selected**.
Actual layout: workspace `chatSessions/*.jsonl` mutation journals plus
JSON/JSONL empty-window sessions. The tested adapter replays kinds 0–3
(snapshot, set, array truncate/append, unset), following the installed
VS Code workbench implementation. Final session states are scanned once;
streaming deltas and superseded JSON snapshots are not extra responses.
All **48 tests pass**. Local read-only scan: **5002 sessions, 24366 requests,
24067 responses, 1465 candidates; zero unreadable files/partial tails**.
Flags: 36 loop, 859 repetition, 2 template-leak, 559 cut-off, 64 tool-repeat,
1 tool-malformed, 1 tool-call-in-content; 331 dense-reasoning informational.
Flags overlap. Missing saved arguments on 215534 of 366403 tool invocations
limit exact tool-repeat detection.

The current Framework client entry is `qwen3.8-flash-next`, URL
`http://framework.gibbsgreatly.xyz:8080/v1/chat/completions`, input **120000**,
output **8192**, toolCalling true, no explicit thinking flag. C5 compares
**8192 versus 16384**, not the older documented 2048 cap. FND-client-limits
remains a candidate, not a historical-cap or causal finding.

Flash-Next has 10 saved responses / 7 candidates across its two Nathanw-labelled
endpoint names: one exact reasoning loop, two other shingle candidates and
four cut-offs. GLM has 2 cut-off responses and no loop flag. No served build
SHA is recorded; saved endpoint labels do not prove engine identity. Nine
bounded examples were reviewed; recommend the Flash-Next exact-loop V1 for
lh-07. Other shingle/tool-repeat flags still need semantic review. Cut-off
flags include cancellations/errors, not proven budget exhaustion. Full
system/tool schemas and historical wire requests cannot be reconstructed.

All model/month/flag counts and aggregate conclusions are in
[README.md](README.md#local-copilot-scan-lh-01c-2026-10-15). Private artifacts
remain only in ignored `artifacts/vscode-scan-20261015/` (0700 directory,
0600 files); no keys, excerpts or source identifiers enter git. No source
writes, configuration changes, inference or production access occurred.
Operator selection (2026-10-15): retain V1 (2026-10-07 00:33 UTC, :8080,
llama-swap; served entry/build unknown) and V9 (2026-09-16 00:20 UTC,
:11434, Ollama). Historical client configuration supplies the ports; these
are not wire captures. V4 (2026-09-15 22:06 UTC) used :11434/Ollama and
fails the llama.cpp-only condition. V7 (2026-09-09 03:52 UTC) has no exact
model/port record; its provider's bracketing configs use :11434, so llama.cpp
is not established and it is excluded. No build inferred from a provider
label or unsuffixed model name. Drop V2/V3/V5/V6/V8. Private replay selection
now contains V1/V9 only. See README for provenance and precise timestamps.

Operator engine map: :8080 before 2026-10-07 = hand-run Nathanw fork;
from 2026-10-07 = llama-swap, build determined by the served entry;
:11434 = Ollama; :1234 = LM Studio. Missing served entry/build stays unknown.
Copilot replay is a reconstruction: the system prompt and tool schemas are
absent. Keep optional lh-01d available for exact capture; defer it now and
continue lh-02 without modifying the client. The requested lh-01b CSE scan
and deep-research fix/retry already completed (23bce712/2a06001b); preserve
those reports and do not rerun eval or the completed scans.


#### lh-01d-capture-proxy

Optional, and only if lh-01c finds too little to replay. A recording
proxy on the workstation captures the exact requests VS Code sends
(system prompt, tool schemas, history, sampling, limits) and the
streamed replies, so a real loop can be replayed byte for byte on each
build.

```yaml
id: lh-01d-capture-proxy
title: Recording proxy for VS Code -> Framework
depends_on: [lh-01c-vscode-transcripts]
runs_on: local
change: >
  Add scripts/loop-hunt/capture_proxy.py (stdlib): listens on
  127.0.0.1:8090, forwards /v1/* to the URL VS Code uses today (from
  chatLanguageModels.json), passes streaming (SSE) through unchanged, and
  appends each exchange (request JSON with the Authorization header
  removed, the reassembled response, timings, model, finish_reason) to
  docs/loop-hunt/artifacts/capture/<date>.jsonl (0600). README section:
  how the operator points one chatLanguageModels.json entry's url at
  http://127.0.0.1:8090/v1 for a work session and back afterwards.
  Tests: a fake upstream with streaming and tool calls; the capture
  contains no Authorization header.
scope:
  allowed_paths:
    - scripts/loop-hunt/
gates:
  - id: tests
    cmd: "python3 -m unittest discover -s scripts/loop-hunt -p 'test_*.py'"
    expect: "exit 0"
    critical: true
```

The operator then works normally in VS Code through the proxy until a
loop happens, and tells Codex the time; that exchange is replayed in
lh-07 on fork current, fork previous and upstream (warm and cold).

Result: —

#### lh-02-session-harness

```yaml
id: lh-02-session-harness
title: Multi-turn session runner with warm/cold replay
depends_on: [lh-01c-vscode-transcripts]
runs_on: local
change: >
  Add scripts/loop-hunt/gen_sessions.py (deterministic synthetic sessions
  as in this plan's "The synthetic session"; seeds 1-6; writes
  scripts/loop-hunt/sessions/ plus manifest.json with hashes and planted
  answers) and scripts/loop-hunt/session_bugs.py, reusing
  framework-ctx-bugs (Client, detectors, framework_lock, readiness waits,
  infrastructure-failure handling, checkpoint/resume, restore, regrade).
  session_bugs.py runs one condition per invocation:
  --condition C1|C2|C3|C4|C5 --entry <llama-swap id> --sessions <seed ...>
  [--replay <chat.json>]. Turn loop: send the full history (user turns +
  the model's answers without reasoning) with cache_prompt true and the
  sampling from D-L3; record per-turn metrics listed in the plan;
  checkpoint after each turn. C2 runs its sessions concurrently (one
  thread each, id_slot unset, all sharing the unified pool). C3 continues past n_ctx
  and records exactly what the server does (HTTP error, truncation or
  context shift: compare prompt_tokens and timings). CK at 64k/96k/131k:
  after the warm turn, reload the entry through llama-swap (unload +
  load), send the identical request with cache_prompt false, record both
  and compare flags. --replay takes an exported real chat and
  regenerates its looping turn warm (turn by turn from the start) and
  cold, 3 seeds each. Report: per session, flags and recall vs context
  tokens; the first turn where any degeneration flag appears ("collapse
  context"); warm-vs-cold table; per-turn timing.
  Also: allow ctx_bugs.py's --candidate for any model/build (today it is
  limited to Laguna x nathanw), and give write_build_expectations.py a
  --link current|candidate option per label, so the fork candidate
  (previous build) gets its own expectations.
  C5 (agent session): send `tools` with the schemas, stream the reply,
  parse tool calls from the server's response (and also scan content for
  tool-call text the server failed to parse), execute fake tools from a
  deterministic file tree, and continue until the task's done-check or
  60 tool calls. Extra flags: tool-repeat, tool-malformed,
  reasoning-in-content, reasoning-in-arguments, cut-off-then-retry.
  The harness must not require one slot (ctx-bug-test's check_props did):
  record total_slots and each slot's n_ctx from /props and /slots, and
  refuse a cell only if /props shows a context smaller than the variant's
  ctx_size.
  The stub server gains multi-turn, cached_tokens, 4 slots sharing one
  KV pool (with a configurable full-pool behaviour), an n_ctx
  limit with a configurable overflow behaviour, and a mode that starts
  looping only when warm (to prove CK detects it).
scope:
  allowed_paths:
    - scripts/loop-hunt/
    - scripts/framework-ctx-bugs/
gates:
  - id: tests
    cmd: "python3 -m unittest discover -s scripts/loop-hunt -p 'test_*.py' && python3 -m unittest discover -s scripts/framework-ctx-bugs -p 'test_*.py'"
    expect: "exit 0, including: a stub warm-only loop is classified 'runtime (warm only)'; a stub loop present warm and cold is 'model/content'; resume after an interrupted turn repeats that turn only; C2 uses 4 slots concurrently; C3 records the stub's overflow behaviour"
    critical: true
  - id: deterministic
    cmd: "python3 scripts/loop-hunt/gen_sessions.py && python3 scripts/loop-hunt/gen_sessions.py && git diff --exit-code -- scripts/loop-hunt/sessions"
    expect: "exit 0"
    critical: true
```

Result (2026-10-15): **built locally, not run on Framework**. Generator,
checkpointed runner, session-aware stand-in, synthetic tools, launcher and
bounded watcher adapter are built. Candidate expectations support
`--link nathanw=candidate`; ctx-bugs permits candidates for either supported
model/build without applying Laguna's short budget to Qwen.

Both test gates pass: **69 loop-hunt tests, 96 ctx-bugs tests**. The sandbox
blocks socket creation, so loopback fixture tests ran with local socket access;
no production endpoint/credentials were used. Generator ran twice after its
fixture commit with `git diff --exit-code -- scripts/loop-hunt/sessions` clean.
Six seeds have 64 available deterministic turns (headroom past 262k); the
runner ends by measured context, not the assumed turn count.

Full CLI stand-in evidence in ignored `artifacts/harness-stub-20261015/`:

| Condition | Saved requests | CK pairs | Evidence |
| --- | ---: | ---: | --- |
| C1 | 22 | 3 | warm-only loops classified runtime; one concurrent request |
| C2 | 48 | 8 | four concurrent workers, shared-pool refusals, four turns after crossing |
| C3 | 28 including imported C1 | 4 | continued C1 text; three warm overflow refusals and a cold refusal |
| C4 | 46 | 5 | context up to 252628 rendered tokens; clean responses unflagged |
| C5 | 62 | — | 30 fake tool calls + final answer per budget; both done checks pass; no flags |

C5 system text measured 12288 tokens. Largest C5 prompts were 120829
(8192 output budget) and 112635 (16384), with 2048 margin. Tools never
execute real commands or access real files. Visible tool-call tokens count
as visible output, avoiding false hidden-token floods. Template rendering
that ignores tools refuses C5 measurement.

C1/C4 use a final valid near-limit turn for the nominal 131k/262k CK, always
recording actual tokens (the full C1 stub reached 117164 prompt tokens).
C3 requires `--continue-from` a completed matching C1 checkpoint; it does
not claim cache continuity after a reload/resume. In C2 all workers finish
before CK; reloads discard all slot caches and are explicitly recorded.
Later cached tokens are measured, not presumed. Warm-only attribution
requires positive recorded cache reuse; HTTP refusals/crashes are not
labelled model/content failures. Pilot must review cache-reset effects.

Transport/SSE interruption stays pending; C2 checkpoints completed peers
before stopping for a failed peer. Offline regrade preserves saved evidence
and refuses running/locked runs. Reports retain actual/rendered/server tokens,
cached tokens, timings, rules/recall, similarity, collapse context and CK.
Launcher/watch adapter are built but no units, timer commands or model loads
were executed. Production deployment remains behind lh-04 approval.


#### lh-03-catalogue

```yaml
id: lh-03-catalogue
title: Session test variants (repo only)
depends_on: [lh-02-session-harness]
runs_on: local
change: >
  In ansible/00-initial-setup/files/llama-swap/models.json set "variants"
  of qwen3.8-flash-next-q4 to
  [{"suffix": "sess131k", "label": "loop hunt 131k", "settings": {"ctx_size": 131072}},
   {"suffix": "sess262k", "label": "loop hunt 262k", "settings": {"ctx_size": 262144}}]
  and of glm-5.3-flash (only if D-L4 = yes) to the sess131k entry only.
  No batch overrides and no `parallel` (D-L2: production leaves both at
  llama.cpp's defaults). Change nothing else.
scope:
  allowed_paths:
    - ansible/00-initial-setup/files/llama-swap/models.json
gates:
  - id: json
    cmd: "python3 -c \"import json;m={x['id']:x for x in json.load(open('ansible/00-initial-setup/files/llama-swap/models.json'))['models']};assert [v['suffix'] for v in m['qwen3.8-flash-next-q4']['variants']]==['sess131k','sess262k'];print('ok')\""
    expect: "ok"
    critical: true
  - id: llama-builds-tests
    cmd: "python3 -m unittest discover -s ansible/00-initial-setup/files/llama-builds -p 'test_*.py'"
    expect: "exit 0"
    critical: true
```

Result (2026-10-15): **repo-only complete, not deployed**. Qwen has
sess131k/sess262k and GLM sess131k, with ctx_size as the sole variant
setting. No parallel/batch/sampling/default/status changes. Parsed JSON
comparison verified the rest of the catalogue is unchanged. Both JSON
assertions pass; all **42 llama-builds tests pass** (the fake Redis test
requires local socket permission). Only the two variants arrays changed.


#### lh-04-deploy

```yaml
id: lh-04-deploy
title: Deploy variants, serve fork previous as candidate, install harness
depends_on: [lh-03-catalogue]
runs_on: framework
approval: loop-hunt-deploy
preflight: >
  Framework (production). (1) secrets check; (2) llama-builds playbook
  installs models.json; (3) `llama-builds status` (read-only; stop if any
  current link differs from the matrix); (4) `llama-builds build fork
  b02cb35f2` - already built, so it only points fork/candidate at
  20261008-b02cb35f2 and rewrites llama-swap's config (reload: the loaded
  model stops 1-2 min and reloads); no promotion; (5) guarded check that
  the session entries exist, including the -nathanw-candidate-sess131k
  ones; (6) copy both harness folders; (7) build expectations for three
  builds with write_build_expectations.py (candidate props captured under
  the run lock without inference, restoring the previous model afterwards).
  Out of scope: promotion, rollback, other models, OpenBao.
commands:
  - "./with-secrets-prod-tiny ansible-inventory -i ansible/inventory/inventory.yml --graph framework && echo SECRETS-OK"
  - "TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-llama-builds.yml"
  - "TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ssh steve@framework.gibbsgreatly.xyz 'llama-builds status --no-fetch'"
  - "TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ssh steve@framework.gibbsgreatly.xyz 'test -f /storage/llama-builds/fork/20261008-b02cb35f2/build.json && test -x /storage/llama-builds/fork/20261008-b02cb35f2/bin/llama-server && llama-builds build fork b02cb35f2'"
  - "TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ssh steve@framework.gibbsgreatly.xyz 'llama-builds swap-config --dry-run | grep -c sess'"
  - "TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny rsync -a --exclude results/ --exclude __pycache__/ scripts/framework-ctx-bugs/ steve@framework.gibbsgreatly.xyz:framework-ctx-bugs/ && TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny rsync -a --exclude __pycache__/ scripts/loop-hunt/ steve@framework.gibbsgreatly.xyz:loop-hunt/"
gates:
  - id: secrets
    cmd: "(command 1)"
    expect: "SECRETS-OK and the framework host"
    critical: true
  - id: playbook
    cmd: "(command 2)"
    expect: "failed=0"
    critical: true
  - id: builds-unchanged
    cmd: "(command 3)"
    expect: "fork current 20261008-9e21f2e53, upstream current 20261008-de7fa0a3c"
    critical: true
  - id: candidate
    cmd: "(command 4)"
    expect: "'fork: b02cb35f2 is already built (20261008-b02cb35f2); candidate -> 20261008-b02cb35f2' (no compile); then llama-swap's config is rewritten and the loaded model comes back. If it starts compiling, the old build dir is gone: stop and report"
    critical: true
```

Preflight clarification **operator approved** (2026-10-15):
step (7) needs candidate build expectations, but the pilot below only loads
fork current; candidate props cannot come from that pilot. Proposed addition
to `loop-hunt-deploy`: one temporary candidate identity load under the shared
run lock, capture /props without inference, restore the previously loaded
model, and generate separate current/candidate expectation files. The operator explicitly approved this identity-capture scope; the first
attempt stopped before it at the candidate rewrite gate. The
original phase-1 current-build props are reused only if build links still
match; helper validation refuses mismatches.

Approved identity-capture command (after code copy, before any pilot):

```bash
TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ssh steve@framework.gibbsgreatly.xyz 'python3 -' <<'PYTHON'
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home()/'framework-ctx-bugs'))
from ctx_bugs import Client
from resp_client import RespRedis
import framework_lock as lock
from write_build_expectations import build_expectations, write_new

builds_root = Path('/storage/llama-builds')
candidate = json.loads((builds_root/'fork/candidate/build.json').read_text())
assert candidate['name'] == '20261008-b02cb35f2'
assert candidate['sha'].startswith('b02cb35f2')
output = Path('/storage/artifacts/loop-hunt/builds-20261015')
output.mkdir(mode=0o700, parents=True, exist_ok=False)
cfg = json.loads(Path('/etc/llama-builds/backends.json').read_text())['publish']
redis = RespRedis(cfg['host'], cfg.get('port',6379), cfg.get('db',1),
                  Path(cfg['password_file']).read_text().strip())
job = 'loop-hunt-build-expectations-20261015'
assert lock.acquire(redis, job, 'loop-hunt', 'build-identities', max_wait=0), 'Framework lock busy'
with lock.held(redis, job):
    client = Client('http://127.0.0.1:8080', 'http://127.0.0.1:8099',
                    api_key=Path('/etc/llamacpp/api-key').read_text().strip())
    before = client.call('/props')
    restore = before['model_alias']
    assert isinstance(restore,str) and restore
    try:
        client.load('qwen3.8-flash-next-q4-nathanw-candidate-sess131k')
        props = client.call('/props')
        assert props['model_alias'] == 'qwen3.8-flash-next-q4-nathanw-candidate-sess131k'
        write_new(output/'props-candidate.json', props)
    finally:
        client.load(restore)
        restored = client.call('/props')
        assert (restored['model_alias'],restored['build_info']) == (restore,before['build_info'])
    shared = ['upstream='+str(Path.home()/'props-upstream.json')]
    current = build_expectations(['nathanw='+str(Path.home()/'props-fork.json')]+shared, builds_root)
    previous = build_expectations(['nathanw='+str(output/'props-candidate.json')]+shared,
                                  builds_root, ['nathanw=candidate'])
    write_new(output/'current.json', current)
    write_new(output/'candidate.json', previous)
print('BUILD-EXPECTATIONS-OK; previous model restored; no inference')
PYTHON
```

The deployment also needs an exact-ID config check, rather than treating
`grep -c sess` as proof that the required entries exist: require Qwen's
nathanw/current, nathanw/candidate and upstream entries at both sizes, plus
GLM upstream sess131k. Use the installed generator's read-only functions,
as the existing ctx guard does, and compare generated bytes to installed
config before trusting an unchanged preview. Check the prior build directory
before `llama-builds build`; a missing build stops before compilation.
Proposed replacement for count-only command 5, under the same approved
scope (after the candidate command has regenerated config):

```bash
TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ssh steve@framework.gibbsgreatly.xyz 'python3 -' <<'PYTHON'
import runpy
import shutil
from pathlib import Path
functions = runpy.run_path(shutil.which('llama-builds'))
cfg = functions['load_config']()
entries = functions['swap_entries'](cfg, functions['load_catalog'](cfg))
required = {f'qwen3.8-flash-next-q4-{build}-sess{size}'
            for build in ('nathanw','nathanw-candidate','upstream')
            for size in ('131k','262k')}
required.add('glm-5.3-flash-upstream-sess131k')
actual = {entry for entry,_ in entries}
assert required <= actual, 'missing session entries: '+repr(sorted(required-actual))
expected = functions['render_swap'](cfg, entries).encode()
assert Path(functions['swap_cfg'](cfg)['config']).read_bytes() == expected, 'installed config differs'
print('SESSION-CONFIG-OK: all 7 required entries; installed config matches generator')
PYTHON
```

The fork candidate link is global: its generator also exposes candidate menu
entries for other fork-backed catalogue models. No ordinary model settings
change and only Qwen's candidate is loaded for the proposed identity capture;
Q2/HIP/other-model inference remains out of scope. All production commands
use the pve-tiny wrapper and this task approval. No production command has
run at the time this preflight was written. The operator subsequently
approved `loop-hunt-deploy`, including the locked identity capture; partial
execution is recorded below.

Result (2026-10-15): **partial; stopped at a failed gate, not deployed
completely**. The operator approved loop-hunt-deploy including the temporary
candidate identity load under the run lock and restoration of the previous
model. The operator also requested a read-only V1 journal lookup first.

- V1: Framework journal query for 2026-10-07 00:15–00:45, units llama-swap
  and nathanw-llamacpp, produced zero matching model/alias/build/start lines.
  The same window without units, filtered for llama-server, also yielded
  zero matches. This is inconclusive, not proof of inactivity. V1's requested
  model is Flash-Next; its actual served model/build remain unknown. Direct
  llama-server ignores the request's model choice and serves what is loaded.
- Secrets/inventory passed: the framework group contains the intended host.
- Playbook passed: Framework ok=15, changed=1, failed=0. Only the installed
  model catalogue changed. Output is private in ignored
  artifacts/deploy-20261015/playbook.log.
- Build status matched: fork current 20261008-9e21f2e53, upstream current
  20261008-de7fa0a3c (HIP also de7fa0a3c). No promotion occurred.
- The prior fork's build.json and binary existed, with b02cb35f2 identity.
  Candidate selection ran under an added shared run lock and returned
  `fork: b02cb35f2 is already built (20261008-b02cb35f2); candidate ->
  20261008-b02cb35f2`. No compilation ran. The added lock was released.
- **The required config rewrite/reload was not confirmed.** Only the
  candidate-selection line was printed. The wrapper captured stderr but
  failed to forward it, so the exact caught error was not retained. Local
  code inspection establishes that swap_config refuses a changed config
  whenever any framework:run-lock exists, including this agent's added lock.
  That added lock conflicts with the built-in guard and is the likely cause.
  The agent should have read this guard before wrapping the build command.
- Under reused rule 7, no later production command ran: no config validation,
  code copy, candidate identity load, build-expectations generation, pilot,
  inference or timer change. Installed config/loaded-model state after the
  attempted rewrite has not been rechecked and must not be claimed verified.

Recovery needs an operator instruction to resume this failed gate, not a new
blanket production approval. Keep the existing task scope. **Do not use
--force or hold an external Redis run lock around swap-config.** Its own
benchmark-lock guard must remain active. After preview validation, call
normal `llama-builds swap-config` outside the added lock, retain stdout AND
stderr, verify exact installed bytes/required IDs and restored prior model,
then continue code copy and the already-approved locked identity capture.
Do not repeat the successful playbook/build-selection steps or compile.

Recovery command (operator approved execution on 2026-10-15):

```bash
TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ssh steve@framework.gibbsgreatly.xyz 'PYTHONDONTWRITEBYTECODE=1 python3 -u -' <<'PYTHON'
import runpy
import shutil
import subprocess
from pathlib import Path
import sys
sys.path.insert(0,str(Path.home()/'framework-ctx-bugs'))
from ctx_bugs import Client
functions = runpy.run_path(shutil.which('llama-builds'))
cfg = functions['load_config']()
entries = functions['swap_entries'](cfg, functions['load_catalog'](cfg))
required = {f'qwen3.8-flash-next-q4-{build}-sess{size}'
            for build in ('nathanw','nathanw-candidate','upstream')
            for size in ('131k','262k')}
required.add('glm-5.3-flash-upstream-sess131k')
assert required <= {entry for entry,_ in entries}, 'required session entries missing'
expected = functions['render_swap'](cfg, entries).encode()
client = Client('http://127.0.0.1:8080','http://127.0.0.1:8099',
                api_key=Path('/etc/llamacpp/api-key').read_text().strip())
before = client.call('/props')
result = subprocess.run(['llama-builds','swap-config'],capture_output=True,text=True)
print(result.stdout,flush=True)
if result.stderr:
    print(result.stderr,file=sys.stderr,flush=True)
assert result.returncode == 0, 'swap-config failed; stop'
assert Path(functions['swap_cfg'](cfg)['config']).read_bytes() == expected, 'installed config differs'
after = client.call('/props')
assert (after['model_alias'],after['build_info']) == (before['model_alias'],before['build_info']), 'previous model not restored'
print('SESSION-CONFIG-OK; all 7 IDs; installed bytes verified; previous model restored')
PYTHON
```


Recovery result (2026-10-15): **lh-04 complete** under the operator's
explicit resume instruction and existing loop-hunt-deploy approval.

- Read-only Redis GET found framework:run-lock free immediately; no key
  was modified/deleted and no wait was needed.
- Normal guarded `llama-builds swap-config` ran without an external lock
  or --force. It wrote 44 entries. All seven required session/candidate IDs
  exist and installed config bytes exactly match the generator.
- Both rewrite and identity capture restored `qwen3-coder-next-upstream`,
  with unchanged build_info `b11514-de7fa0a3c`.
- Both harness directories were copied successfully. Candidate /props
  capture ran under the shared run lock without inference, recording
  `b10710-b02cb35f2`. The lock was confirmed free after release.
- Private files on Framework: `/storage/artifacts/loop-hunt/builds-20261015/`
  (0700), containing `props-candidate.json`, `current.json` and
  `candidate.json` (each 0600). Current expectations validate the saved
  current-build props against the current links; candidate expectations
  validate the new candidate props against its candidate link. Both include
  upstream's saved full props.

| Engine | Build name | Full SHA | build_info |
| --- | --- | --- | --- |
| Fork current | 20261008-9e21f2e53 | 9e21f2e5329c697a46fd790c0eb172d1ee2f0923 | b10814-9e21f2e53 |
| Fork previous | 20261008-b02cb35f2 | b02cb35f20afb6b1a09b059b5e95120684e7a0c8 | b10710-b02cb35f2 |
| Upstream | 20261008-de7fa0a3c | de7fa0a3c6a2e1b4cd9f22eb8d6bf5b12dbdb63b | b11514-de7fa0a3c |

No compilation, promotion, inference, pilot or timer operation ran. The
successful playbook/candidate-selection steps were not repeated. V1's
served identity remains unknown; lh-07 now records the operator's four
replay targets. Next: separate loop-hunt-pilot approval for lh-05 below.


#### lh-05-pilot

One C1 session (seed 1) on `qwen3.8-flash-next-q4-nathanw-sess131k`, with
the D10 timer pause and restore, detached like ctx-bug-test's runs. Then
first confirm the slot layout from real `/props` and `/slots`: the expected
default is four slots, each reporting the full variant context, with a shared
KV pool. Record the responses; if the layout differs, stop and report before
continuing the pilot. Then review: per-turn flags, cached-token counts (proves the cache is used),
timing against the plan's estimate, warm/cold CK pairs, and whether any
turn degenerates. Fix the harness (new local step) before lh-06 if the
review finds a measuring problem. Approval `loop-hunt-pilot`.

Result: —

Pilot preflight (approved 2026-10-15; launched below):

- Target: Framework through the pve-tiny production wrapper; task
  `loop-hunt-pilot`. Mutating: temporarily pause the upgrade timer, start
  detached harness/watcher units, load/reload the named test entry, and
  write run artifacts. No catalogue/build/link changes.
- Scope: C1 only, seed 1, Qwen fork current
  `qwen3.8-flash-next-q4-nathanw-sess131k`; server-default sampling,
  8192-token answers, warm/cold checks near 64k/96k/131k. Approximately
  1.5 hours; actual turn count and prompt lengths are measured.
- Read-only gates: intended host; current build expectations still match;
  run lock free; `apt-daily-upgrade.service` inactive. Never stop an active
  upgrade. The runner takes the run lock and saves `/props` and `/slots`;
  require four slots each reporting n_ctx 131072 before any inference.
  A layout mismatch stops and is reported, not adjusted automatically.
- Under `TASK_APPROVAL=loop-hunt-pilot ./with-secrets-prod-tiny ssh
  steve@framework.gibbsgreatly.xyz`, pause with
  `sudo -n systemctl stop apt-daily-upgrade.timer`, verify service/timer
  both inactive, then launch:

  ```bash
  ~/loop-hunt/run.sh --condition C1 --sessions 1 \
    --entry qwen3.8-flash-next-q4-nathanw-sess131k \
    --builds-json /storage/artifacts/loop-hunt/builds-20261015/current.json
  ```

- Attach a detached user unit running
  `python3 ~/loop-hunt/watch_run.py --run-dir RUN_DIR --run-unit RUN_UNIT
  --builds-json /storage/artifacts/loop-hunt/builds-20261015/current.json`
  using the exact directory/unit from this launch. The existing watcher
  permits at most one narrowly defined swap-infrastructure resume; no
  service restarts, prompt edits or broader retries. If launch/attachment
  fails, restore the timer immediately and report the failed gate.
- Cleanup: harness restores the original model; watcher starts
  `apt-daily-upgrade.timer` on completion/failure and verifies it active.
  Independently verify model restoration, lock release and timer activity.
  Review real slot layout, cached-token evidence, timings, flags and every
  warm/cold pair before requesting the matrix approval.
- Out of scope: matrix, private-chat replay, proxy capture, other models,
  package upgrades, compilation, promotion and unrelated production work.

Pilot launch (2026-10-15): operator approved loop-hunt-pilot. Host,
all three pinned build links, free run lock, journal permissions, inactive
upgrade service and active timer passed preflight. Timer paused, detached
run `loop-hunt-20261014t233240z.service` launched; artifacts on Framework:
`/storage/artifacts/loop-hunt/20261014T233240Z-pilot`. Detached watcher
`loop-hunt-pilot-watch-20261014t233240z.service` initially appeared active
but exited immediately; see the failed launch gate below. Slot-layout and
measuring review did not run; do not claim pilot passed.

Operator conditional approvals (2026-10-15): loop-hunt-matrix covers lh-06
both nights, and loop-hunt-replay covers lh-07 V1 on its four recorded
targets and V9 on Qwen's three llama.cpp builds. These become executable
only if pilot review finds no measuring problem and no harness fix is
needed. If the pilot needs a harness fix or slot layout differs, stop and
ask. Every run retains D10 timer pause/restore, bounded watcher and model
restoration. Approval does not extend to unrelated deployments or fixes.

Pilot startup failed gate (2026-10-15): the detached watcher exited with
FileNotFoundError opening the run directory's `.watcher-lock`. The launch
command started it before the harness created that directory; a momentary
systemd active state was insufficient proof of successful attachment. This
was the agent's launch-order error, not a model failure. No harness source
was changed. Conditional matrix/replay execution is held pending a successful
pilot and measuring review.

Mandatory cleanup: upgrade timer was immediately started and verified active;
SIGINT was sent only to this pilot's main process. The harness logged the
interruption before inference/slot-layout capture and began restoring
`qwen3-coder-next-upstream`. Final checks passed: status interrupted, zero completed requests, no slot
layout recorded, restored_default true, `/props` confirms
`qwen3-coder-next-upstream` / `b11514-de7fa0a3c`, Redis run lock free,
upgrade timer active. No matrix/replay run started.

Proposed launch correction for operator review: exclusively pre-create the
private run directory (0700), launch the harness with that exact --run-dir,
wait for its run.json/progress.json while verifying the run unit is active,
then attach the watcher. Verify watcher.json exists and reports its first
successful poll, in addition to checking the watcher unit stays active.
If any gate fails, restore the timer and gracefully interrupt this run for
model restoration. Do not resume the failed launch or start another run
until the operator resolves this stop point (reused rule 7).

Operator resume and standing exception (2026-10-15): resume lh-05 with
corrected launch ordering. For the rest of loop-hunt, a launch/setup failure
before any request completes may receive one autonomous launch-mechanics
fix/retry only after model restoration, free lock and active upgrade timer
are verified. Record the failure/retry in the step's Result. Stop and ask if
the retry also fails, any request completed, or the fix changes measurement.
This exception overrides the blanket failed-gate stop only within that scope.
Slot-layout differences and measuring/harness problems still stop for input.

Result update (2026-10-15): approved corrected launch succeeded. New private
run directory was created 0700 before launching the harness; run.json and
progress.json appeared before watcher attachment. Watcher first successful
poll confirmed running/zero requests and its unit active. Framework run:
`/storage/artifacts/loop-hunt/20261015T003810Z-pilot`; harness unit
`loop-hunt-20261015t003810z.service`; watcher unit
`loop-hunt-pilot-watch-20261015t003810z.service`. Upgrade timer paused;
watcher owns restoration. No harness code or measured settings changed.
Pilot slot-layout gate passed: total_slots 4, each /slots n_ctx 131072.
First five requests completed cleanly with matching rendered/server token
counts, positive cache reuse and no evidence errors. Full measuring review
and warm/cold checkpoints remain pending.

Pilot measuring review stop (2026-10-15): corrected launch/watcher and
slot-layout gates passed (four slots each n_ctx 131072). Initial measured
prompt tokens matched usage.prompt_tokens and warm cache reuse was positive;
no infrastructure/evidence errors occurred in the reviewed requests.
However, turns 11 and 12 expose recall/format conflation: the model returned
all correct route values (and NOT PROVIDED for turn 12) with Q1/Q2/Q3 on
one line. The prompt asks one line per question, so this is an instruction
format violation. The grader's newline-bound regex instead absorbs later
answers/reference into Q1 and reports Q2/Q3 absent, marking correct facts as
wrong recall. It has no separate one-line-per-question format check.
Recall and instruction-following measurements therefore need correction;
no semantic recall loss is established by these two responses.

Per operator instruction, pilot was interrupted and matrix/replay held.
Timer was immediately restarted active; SIGINT targeted only this pilot.
No harness code, prompts, settings or saved grades were changed. The setup
retry exception does not apply: requests completed and the proposed fix
changes measurement. Proposed for operator decision: bound recall extraction
by explicit Qn/reference markers even on one line, retain exact expected
value matching, and grade line layout separately as instruction failure.
Add regression coverage for the saved synthetic response shapes, then
regrade existing evidence and rerun the pilot after approval.
Final cleanup verified: status interrupted, 15 completed warm requests
(turns 1–15), two flagged responses (11/12), no CK reached. Original
`qwen3-coder-next-upstream` / `b11514-de7fa0a3c` confirmed by /props,
restored_default true, lock free and upgrade timer active. The watcher was
stopped after this independent cleanup verification; pilot units inactive.
No matrix/replay started. Existing raw responses remain available for
regression/regrading; no pilot success or recall-collapse claim is made.

Operator correction/standing autonomy (2026-10-15): approved separating
recall extraction from line-format grading, regression tests from the real
pilot answers, regrading the 15 saved requests while retaining pre-fix
results, and rerunning the same pilot. Separate named matrix/replay tasks
remain conditionally approved after a successful measuring review.
For the rest of loop-hunt, local measurement/scoring bugs may be fixed with
a regression test and saved evidence regraded with old results retained;
record each correction in Result. Launch/plumbing permits up to two retries
per run with cleanup verified. Where plan paths/fields contradict code,
use code. This supersedes the earlier one-retry/blanket gate-stop rules.
Stop only for changes to measured models/builds/conditions/sizes/sampling/
settings/prompts, production changes outside loop-hunt, the same failure
persisting after two fixes, failed cleanup checks, or reaching lh-08/lh-10.

Result, scoring correction (2026-10-15): recall extraction now uses explicit
Qn/reference boundaries independent of line breaks, retains exact expected
matching and refuses ambiguous duplicate labels. question_lines separately
flags non-separated/missing/duplicate/extra question labels. Real pilot
turns 11/12 now pass recall and fail only question_lines in regression tests.
All 74 loop-hunt tests pass. Every regrade creates an exclusive timestamped
backup of results/manifest/report/raw grades, with backup/source/scorer hashes
recorded in run.json. No prompts, model/build settings or sampling changed.
Framework code update, preserved regrade and pilot rerun follow below.

Result, preserved regrade (2026-10-15): all 15 saved requests regraded,
35/35 factual answers correct. Only turns 11/12 flag if-fail:question_lines;
all other responses are clean. Original evidence preserved byte-for-byte in
Framework run `20261015T003810Z-pilot/regrade-backups/1792026392385125497`;
original results SHA-256
`b9de05fdb5dca82c614449670084c4b757328b21eda12fed2b3f89db194cecba`.
Corrected tools copied only to ~/loop-hunt. Fresh unchanged-settings pilot:
`/storage/artifacts/loop-hunt/20261015T010713Z-pilot`, harness unit
`loop-hunt-20261015t010713z.service`, watcher
`loop-hunt-pilot-watch-20261015t010713z.service`. Review pending.

Result, fresh pilot (2026-10-15): **complete; no further measuring problem**.
32 requests (29 warm turns, three cold CK requests), 74/74 factual answers
correct. Only warm turns 11/12 fail question_lines; no loop, repetition,
runaway, GPU or evidence error. All measured prompt counts equal server
usage; every warm request after the first reuses cache. All three cold
requests report cache_n 0. Warm/cold payload equality except cache_prompt
verified and classifications clean at actual 65673 / 98431 / 118897 prompt
tokens. The final valid turn is the nominal 131k CK under the unchanged
8192-token answer allowance; the next turn would not fit. Cold wall times:
114.9 / 163.2 / 193.8 seconds. Four slots each n_ctx 131072 verified.
The fresh pilot took roughly 23 minutes, below the initial estimate.
Full review remains on Framework in the run's pilot-review.json; results
SHA-256 `2a74be1114ff34b1de100ea9784df31ca7834afc1e90fca0f87451fb56d42dfc`.
Original qwen3-coder-next-upstream / b11514-de7fa0a3c restored, lock free,
upgrade timer active; watcher terminal poll confirms completion. Conditional
matrix/replay approvals are now satisfied; continue without another approval.

#### lh-06-matrix

All remaining conditions in "The matrix", ordered fork current, fork
previous (candidate), upstream, then GLM; C4 last. Two overnight runs;
the watcher supervises; D10 timer pause and restore for each. Review
into a "Matrix" section of the README: per condition the collapse
context (or "none"), warm/cold classification of every degeneration,
overflow behaviour per build, and fork-current vs fork-previous vs
upstream differences under identical conditions. Approval
`loop-hunt-matrix` (covers both nights).

Result: —

Matrix preflight prepared while pilot runs (2026-10-15; execution remains
conditional on its measuring review): Framework / pve-tiny production,
`loop-hunt-matrix`, mutating only loop-hunt artifact files, detached run/
watcher units, model loads/reloads and D10 timer pause/restore. Pinned
builds, default server/sampling settings and synthetic prompts unchanged.

Remaining jobs (pilot supplies fork-current C1 seed 1):

| Batch | Model/build | Jobs |
| --- | --- | --- |
| 1 | Qwen fork current | C1 seed 2; C2 seeds 3/4/5/6; C3 seed 1 continuing the completed fresh pilot; C5 seed 1, both approved output caps |
| 1 | Qwen fork previous | C1 seeds 1 and 2 as separate runs; C2 seeds 3/4/5/6; C3 continuing its C1 seed 1; C5 seed 1, both caps |
| 2 | Qwen upstream | Same C1/C2/C3/C5 jobs as fork previous |
| 2 | GLM upstream | C1 seeds 1 and 2 separately; C2 seeds 3/4/5/6 |
| 2, last | Qwen all three builds | C4 seed 1 once per build, sess262k |

Twenty remaining matrix runs, sequential in two consecutive batches; the
night grouping is organisational, not a pause between jobs. Each gets its own private run
directory, normal harness invocation and detached watcher. Between every
run, verify original model/build restored, Redis lock free and upgrade timer
active before allowing the next one. Never hold the lock in the orchestrator;
the harness owns it. Recheck all three pinned build links per job. C3 paths
resolve only to completed matching C1 runs. No unrelated service restart,
package upgrade, build promotion, private replay or judge work in this task.

The transient command orchestrator and exact job arguments live in ignored
`artifacts/campaign-20261015/` (matrix-jobs.json, campaign.py). Four local
fake-command lifecycle tests verify launch order, C1 continuation resolution,
failed launch cleanup and failed watcher cleanup. It leaves harness payloads
and grading untouched. After the pilot passes, copy only those two files to
`/storage/artifacts/loop-hunt/campaign-20261015/` and launch, through
`TASK_APPROVAL=loop-hunt-matrix ./with-secrets-prod-tiny ssh
steve@framework.gibbsgreatly.xyz`:

```bash
systemd-run --user --unit loop-hunt-matrix-campaign-20261015 --collect \
  python3 -u /storage/artifacts/loop-hunt/campaign-20261015/campaign.py \
  /storage/artifacts/loop-hunt/campaign-20261015/matrix-jobs.json
```

Its campaign.json and user journal record each run path, cleanup and flags.
It cannot grant approvals, change settings, or automatically broaden a failed
job. Supervise its results and apply only the operator's scoped retry rules.

Result, matrix launch (2026-10-15): approved campaign launched as detached
`loop-hunt-matrix-campaign-20261015.service`, invocation
`7b189720a49e4586b377733dbbf409a8`. State/logs and all job directories live
under `/storage/artifacts/loop-hunt/campaign-20261015/`; campaign.json records
each job path, unit and cleanup, with immutable job-file hash. It verifies
the passed pilot review/results hash before execution. Model settings,
prompts and budgets unchanged; job-level watchers and cleanup remain in force.
First run (fork-current-C1-seed2) and its watcher first poll verified.
Status uses `~/loop-hunt/run.sh --status --results-root
/storage/artifacts/loop-hunt/campaign-20261015`; default root still selects
a top-level pilot, so use this campaign root. Supervision/review still
running; do not mark the matrix complete yet.

Matrix Result update (2026-10-15): first queued job, fork-current C1
seed 2, completed 32 requests with 74/74 recall, zero flags/evidence errors
and exact prompt/server token counts. Three clean warm/cold pairs at
65657/98447/118974 tokens; watcher complete and original model, free lock,
active timer verified. Together with the pilot, C1 covers both seeds:
64 requests, 148/148 recall, six clean CK pairs, only the pilot's two
line-format failures. C2 is now running four concurrent sessions; remaining
jobs continue under the approved campaign. Aggregate table is in README.

Matrix Result, C2 in progress (2026-10-15): read-only /slots observation
at 02:10:57 UTC confirmed all four slots is_processing true, each n_ctx
131072, alias qwen3.8-flash-next-q4-nathanw-sess131k and build
b10814-9e21f2e53. Observation saved privately in its run's
slot-observations.jsonl (0600). First four ~16k warm/cold pairs are clean.
At turn 8 the four prompt counts sum to 131275; all four warm requests
returned HTTP 500, message Context size has been exceeded. /health remained
healthy, with no evidence errors. The matching cold ~32k request succeeded;
comparison is not comparable (request refused), not a looping finding.
The harness continues the planned capacity test and four extra turns with
settings unchanged. Full C2 review remains pending.

Matrix scoring correction queued (2026-10-15): source review against the
real C2 refusal shape found that classify checked one-sided flags before
request errors. If the successful peer had a formatting/degeneration flag,
a refused request could be labelled warm-only/cold-only instead of not
comparable. Error handling now precedes those comparisons, with a regression
covering both directions using the real refusal and pilot-format shapes.
All 75 loop-hunt tests pass. Actual requests/settings are unchanged. Keep
the active matrix harness fixed; at the completed-review boundary, preserve
pre-fix results and regrade saved evidence with the corrected classifier,
then refresh the staged replay version/hashes before releasing the review
gate. Clean-peer refusal pairs already recorded correctly remain unchanged.

Matrix Result update (2026-10-15, 04:52 UTC): seven queued jobs completed,
all with verified model/lock/timer cleanup, zero evidence errors and exact
rendered/server prompt counts on accepted requests. Fork-current C2:
56 requests, 80/80 accepted-response facts, four clean CK pairs and four
refused pairs; all 20 warm requests on rounds 8–12 returned HTTP 500 after
the shared pool filled at 131275 summed prompt tokens. Fork-current C3
adds six requests beyond the imported pilot: 5/5 accepted-response facts,
four HTTP 400 context-limit refusals, final prompt 139235 tokens. Its
refused CK is not comparable. Fork-current C5 completed 20 requests across
both budgets with no flags. Fork-previous C1 seeds 1/2: recall 55/74 and
73/74, respectively; seed 1 has one repetition flag and two absent-fact
hallucination flags. Its six CK pairs are three clean, two cold-only and
one model/content. Fork-previous C2: 75/80 accepted-response facts, one
repetition flag, 20 capacity refusals; pool crossing 131287, four concurrent
request windows, three clean/one cold-only/four refused CK pairs. These
are preliminary detector findings, not yet blind-judged or build-specific
conclusions. C3 imported rows are excluded from these added-request totals.
Fork-previous C3 is now running; review and supervision continue.

Matrix Result update (2026-10-15, 06:53 UTC): eleven jobs complete.
Fork-previous C3 added six requests beyond C1: 4/5 accepted-response facts,
one wrong:q1 and four HTTP 400 context-limit refusals. Fork-previous C5
completed 27 requests across both budgets, no flags. Upstream C1 seeds 1/2
each completed 32 requests, 74/74 facts and three clean CK pairs, no flags.
All eleven jobs have verified cleanup, zero evidence errors and exact
prompt/server token counts on accepted requests. The two previous-build
repetition flags are reasoning-channel eight-word shingles repeated four
and five times; final answers were not flagged. Blind judging is pending.

Launch retry 1 for upstream-C2: restoring the timer between jobs allowed
apt-daily-upgrade.service to start at 06:47:46. The next job's preflight
stopped with upgrade active before creating its directory or sending any
request. The service finished at 06:48:17. Read-only checks confirmed
qwen3-coder-next-upstream / b11514-de7fa0a3c restored, Redis lock free,
timer active, upgrade service inactive and preceding watchers complete.
Under the operator's launch/plumbing retry authorization, preserved
campaign.before-upgrade-retry-1.json and recorded launch_retries in the
campaign state, then relaunched the unchanged controller. At 06:53:28,
upstream-C2 is running as loop-hunt-20261015t065254z.service, watcher
loop-hunt-20261015t065254z-watch.service attached with successful first
poll, timer paused and no campaign failure. No harness, build, model,
prompt or sampling changes. Replays remain gated on the full matrix review.

Matrix Result update (2026-10-16 NZDT; observation 2026-10-15 17:00 UTC):
thirteen jobs complete. Upstream C2 completed 57 requests, 83/83 accepted
facts, 20 HTTP 500 capacity refusals, four clean CK pairs and five refused
pairs (seed 6 crosses its 32768-token checkpoint on turn 9). Upstream C3
adds six requests beyond imported C1: 5/5 accepted facts and four HTTP 400
context-limit refusals. Both have zero evidence errors and verified cleanup.

Upstream C5 stopped after one clean saved list_dir request at 08:14 UTC.
The next intermediate /apply-template token-count probe ended in the
assistant tool call with add_generation_prompt true. The upstream journal
records HTTP 400: Cannot continue an assistant message that contains tool
calls. The failure preceded the next inference request. Independently
verified restored qwen3-coder-next-upstream / b11514-de7fa0a3c, free Redis
lock, active upgrade timer, restored_default true. No retry has been made;
failed run and its saved record remain intact at upstream-C5.

Prepared a local measurement-probe correction: set add_generation_prompt
false for partial histories ending in assistant tool calls, including the
bare-template tools-support check. Normal user/tool-ended inference counts
remain true; messages are not mutated. Regression recreates the observed
rejection and checks both probes plus normal tool-result continuation.
All 76 loop-hunt tests pass. Not deployed: changing this count may change
C5's generated audit-filler lengths. Applying it and restarting upstream C5
needs operator approval under the explicit prompt-change stop rule. Matrix
and replay continuation remain paused pending that decision. Existing saved
evidence and all completed jobs are preserved; no production changes outside
read-only diagnosis were made during this status check.

C5 correction/retry Result (2026-10-16 NZDT): explicit operator approval
received to apply the counting fix, rerun C5 and continue. Before deployment,
verified original model/build restored, lock free, upgrade timer active and
upgrade service inactive. Preserved the failed directory and its one saved
record untouched; backed up the active harness and campaign state. Applied
only the count-method correction to the existing matrix harness (SHA-256
6f96952fa83c55f3172af8527f90253ea0d55416b3c3049fde14230a2d77b771).
Queued classification/seed/report corrections remain deferred to the matrix
review boundary. Relaunched upstream C5 at 17:06:23 UTC in
upstream-C5-attempt2, unit loop-hunt-20261015t170623z.service; watcher
loop-hunt-20261015t170623z-watch.service first successful poll verified.
Controller retry_directories records the fresh path without changing the
immutable job definitions. Five lifecycle tests include failed-evidence
preservation; 76 harness tests passed. This is C5 retry 1.

Refreshed waiting replay staging and cutover hashes, retaining the full
matrix-review gate and preserving previous staging. Waiting continuation
invocation 71336c29649747ada663ffa7cab1a9e1; staged latest tested harness
SHA-256 81b48cb76cdd1e588870e19cd2f8fc567e50c5b40850141f1e89a7e9d96c35b6.
No replay inference has started. Continue matrix supervision, then preserved
regrades/review, seven replay jobs, and stop at lh-08 as already instructed.

C5 retry 1 failed (2026-10-16 NZDT): one clean saved request, then the same
HTTP 400 in the intermediate probe. The first regression incorrectly assumed
add_generation_prompt false disables assistant prefill. Read the pinned
upstream source directly from /storage/llama-builds/src at de7fa0a3c:
server-common.cpp:1370-1386 automatically enables prefill for a trailing
assistant regardless of that flag; tool calls then cause the rejection.
The stricter stand-in reproduces this rule, and the new end-to-end C5
regression failed before the second correction.

Second correction: restore the ordinary count-method behavior and count the
actual tool result before audit filler in session_tools.run_agent. This
avoids unfinished assistant histories and includes result overhead in the
growth estimate. No placeholder result or changed inference-history payload
is introduced. Both generation-flag rejection cases have regression coverage;
77 tests pass. A full local C5 trial completed 62 requests, both budgets,
30 tool calls each, both synthetic tasks done, zero flags/evidence errors.
Committed as 5097df97. Operator's explicit C5-fix approval and two-fix rule
cover this correction; a repeat after this fix requires stopping.

Verified retry-1 model restoration and free lock; restored upgrade timer
while the stopped harness awaited its watcher's terminal poll. At 17:16:24
UTC the watcher recorded needs-attention with timer active; the supervisor
then exited. Rechecked inactive upgrade service, active timer, exact restored
model/build and free lock before retry 2. Preserved both failed directories
and source/state snapshots. At 17:17 UTC launched upstream-C5-attempt3;
retry_directories and launch_retries record the second permitted attempt.
Active session_bugs.py is restored to the original matrix baseline; only
session_tools.py carries the growth-probe fix, SHA-256
782755a71d816514257d7dd002ae50c73a5e18f188869e2ea87bb444f95ce732.
Queued scorer fixes remain deferred; no other measurement settings change.
Replay staging refreshed again with the correct active baseline hash and
latest tested full harness (9813d08ba737f07c395fe9b14ea0ea6ba6f251006d6b20791431317a5a2a023b),
waiting invocation e43bd4c7011445549ad0921237258f27. Matrix-review gate retained.

Queued scoring/report corrections (2026-10-16 NZDT; active run unchanged):
regrade previously rewrote progress.updated with analysis time, inflating
elapsed-run summaries. save(update_progress=False) now preserves completion
progress on regrade, and progress.json joins the automatic pre-regrade
backup. Regression verifies byte-identical progress before/after repeated
regrades. Committed 22aeb11f; deferred to the closed-matrix review boundary.

Saved previous-build recall review found another extractor boundary error:
answers repeat [TRIAGE] before subsequent Qn and ref labels. The prefix was
included in the preceding answer, falsely marking exact facts wrong and
NOT PROVIDED hallucinated. Exact saved synthetic turns 1/24/27 regress this;
markers/reference boundaries now consume the optional prefix. Real wrong
literals, missing/duplicate labels, extra prose and line-format checks retain
their existing behavior. All 78 tests pass. Read-only in-memory rescoring of
the thirteen completed jobs changes previous-build C1 seed 1 from 55/74 to
74/74, seed 2 from 73/74 to 74/74, C2 from 75/80 to 80/80, and new C3 from
4/5 to 5/5. No recall flags remain in those jobs. Other jobs unchanged.
The earlier preliminary recall/hallucination findings are withdrawn; the
two reasoning-channel repetition flags remain. Canonical results, reports,
raw files and active source are untouched; preserve/regrade at matrix review
and recompute affected CK classifications before releasing replays.

Post-matrix analysis staging Result (2026-10-16 NZDT): helper measurement
checks passed on all thirteen completed jobs: exact approved identity,
slot layout, request fields/budgets/seeds, cache flags, rendered/server
tokens, cold-cache isolation, warm/cold payload equality, evidence and
cleanup. Four fault-injection tests cover acceptance/refusal/semantic flags
and rejection of measuring faults; two fingerprint tests distinguish grade
metadata from immutable request/response/token/timing evidence.

Staged private analyze_after_matrix.py, matrix_audit.py and review_matrix.py
under the existing campaign root, launched as
loop-hunt-matrix-analysis-20261015.service, invocation
ac74d2d6b07e470ba001b8831d6313c2. Verified matrix-analysis.json stage
waiting-for-matrix. It waits for all twenty jobs and inactive supervisor,
then verifies cleanup/identity/measurements, preserves the active source,
installs the tested scorer, automatically backs up and regrades each closed
run, and requires identical request/response/token/timing fingerprints.
It preserves the original campaign summary, refreshes its aggregate flags
and writes matrix-review-ready.json. It cannot send inference or create the
matrix-review.json replay-release marker; that still follows agent review
and the required docs update. Source/staging remains fixed during live runs.
Latest staged scorer is be9d79e1, SHA-256
5c9f65bf551131659fe2202f291108de7d5ac744f94a81bf4484129f3c37fdff;
waiting replay continuation invocation 9f6fbb30b23d4615849cc82485a54316.
At 17:37 UTC, upstream C5 retry 2 has 22 saved clean requests: 8192-budget
run complete, 16384-budget in progress. All old attempts remain untouched.

C5 retry 2 Result (2026-10-16 NZDT, verified 17:47 UTC): completed 31
requests with zero flags/evidence errors and exact rendered/server tokens.
Both synthetic tasks done; final file-tree SHA matches the full clean stub
(2b86e828e8aa1270e47134f3a5f2c453fe69bbd2868141e34e97de6f31699643).
8192 cap: 39 calls, peak prompt 121743; 16384 cap: 38 calls, peak 113406.
Original model restored, lock free, upgrade timer active and watcher complete
were verified by the supervisor before advancing. All failed attempts remain
preserved at their original paths. Fourteen matrix jobs now complete;
GLM upstream C1 seed 1 started as loop-hunt-20261015t174710z.service, with
its watcher attached. Saved-result regrades remain queued after all twenty.

#### lh-07-replay-real

V1's actual served model/build are unknown: the journal check in lh-04
was inconclusive. Operator decision (2026-10-15): replay its reconstruction
against Qwen on fork current, fork previous and upstream, and GLM on
upstream. Compare reproduction behaviour without assigning historical
model/build blame. V9 remains selected; Copilot system prompts and tool
schemas are missing, so keep lh-01d available for exact capture.

Only for chats the operator picked in lh-01. Export each chat's messages
up to the looping turn (on Framework only), then `session_bugs.py
--replay` on fork current, fork previous and upstream (and GLM if the
chat was GLM), warm and cold, 3 seeds. This is the framework's
"save → restart → reload → repeat". Approval `loop-hunt-replay`.

Result: —

Replay preparation result (2026-10-15; inference not started): selected
V1/V9 both point to the first user request of their saved sessions. Private
exports preserve the exact saved user text (27 / 310 characters), not the
historical assistant response. No invented system prompt or tool schemas.
Local exporter initially checked V9's tool-channel excerpt against answer
text; fixed channel selection with a synthetic regression test. Source
pointer, date and selected evidence all verified without returning more
excerpts. No source file changed. Full export provenance and SHA-256 remain
in ignored artifacts/replay-exports-20261015-v2; no prompt text enters git.
Under loop-hunt-replay approval, both inputs were copied to Framework
`/storage/artifacts/loop-hunt/replay-inputs-20261015/` (0700, files 0600),
with exact hash/permission checks. Inference waits for the matrix step.

V9's historical hit is repeated tool invocation, from Ollama. Its missing
tool schemas/execution history are not reconstructed by a prompt-only replay;
record that coverage limit explicitly. A non-looping completion cannot
establish absence of the original agent tool loop. V1's served model/build
remain unknown. Both are reconstructions; lh-01d remains available for exact
capture. These limitations do not add invented schemas or tool behaviour to the
saved user messages. Models, sampling and conditions remain as planned.
A reporting-only correction labels replay coverage separately from the
synthetic full-context condition and explains missing historical tool
execution. Extended end-to-end regression passes in the 74-test suite.
Deploy it at the replay boundary, after the active matrix version finishes;
no mid-run harness replacement or prompt/request changes.

Replay continuation preflight/result (2026-10-15): under the separately
approved loop-hunt-replay task, staged private scripts/config at
`/storage/artifacts/loop-hunt/replay-campaign-20261015/` and started
`loop-hunt-replay-after-matrix-20261015.service` (invocation
`aca946d34f894ded9b0f74f9c4b4cb09`). Verified waiting-for-matrix state;
no replay inference yet and active matrix harness unchanged.

The continuation requires matrix status complete, exactly 20 completed jobs,
all cleanup verified, each run complete/restored, free lock and active timer.
It additionally waits for matrix-review.json, written only after the agent
finishes the required matrix review/README update: status reviewed; no
unaddressed measuring problem, matching jobs_sha256 and a results_sha256
map covering all 20 jobs. Every reviewed results hash must still match.
The waiting unit was restarted to apply this gate before any replay request;
requires_matrix_review true was verified, with the matrix unaffected.
It verifies immutable matrix-job and replay-input hashes. At that boundary
only, it preserves the existing loop-hunt harness source and atomically
installs the tested reporting/metadata corrections. No other production
code/config changes. Replay seed metadata now records the already-used
seeds 1–3; actual request seeds/budgets unchanged (74 regression tests pass).
Nine local boundary tests reject early/partial/unclean matrix completion,
require the completed agent review and check the seven targets. Commands are transient orchestration
in ignored artifacts/replay-campaign-20261015, not model-generated code.

Replay jobs: V1 on Qwen current/previous/upstream plus GLM upstream; V9 on
Qwen current/previous/upstream, each with seeds 1–3 and warm/cold comparison.
Each uses the same supervised launcher, build checks, D10 timer pause/restore
and original-model/lock cleanup. The waiting unit launches them automatically
after the matrix, then records `lh-08-reached; awaiting operator` and takes
no judge/writeup/production-cleanup action. continuation.json and campaign.json
on Framework retain progress. Observe and fix only within operator scope.

#### lh-08-judge

Build a blind corpus (model/build/condition replaced by opaque ids) of
every assistant turn from lh-05..07 into
`docs/loop-hunt/artifacts/judge/` with a judging guide that scores, per
turn: phrase looping, semantic looping and context echoing
(none/mild/moderate/severe), coherence 0–5, instruction following 0–5.
The operator runs the cloud judge per `docs/framework-ubuntu/benchmarks.md`
§5 and drops the JSONL results back; the agent joins them to the ids.

Result: —

#### lh-09-writeup

`docs/loop-hunt/README.md`: findings in the framework's FND format
(environment, observation, evidence, impact, confidence, suspected
cause, workaround), a CIS per build × condition (recall × coherence ×
non-repetition, 0–1000), the collapse-context table, and a plain answer
to: "Does the Nathanw fork loop where upstream doesn't, and if so, under
which condition and since which build?" Update the model list statuses
as a drafted table for lh-10.

Result: —

#### lh-10-cleanup

Approval `loop-hunt-cleanup`: variants back to `[]`; statuses from
lh-09; `llama-builds build fork 9e21f2e53` (points the candidate back at
current, so the candidate entries disappear); playbook; guarded write;
check that only the ordinary entries remain and the loaded model is back.

Result: —

## Out of scope

- Fixing anything in the fork or upstream (bug reports are drafted in
  lh-09 only if a build-specific finding holds).
- Speed tuning; HIP; Ollama, LM Studio, vLLM (the framework lists them;
  possible later with the same session harness).
- The needrestart production issue (ctx-bug-test D10), except pausing the
  upgrade timer during runs.
