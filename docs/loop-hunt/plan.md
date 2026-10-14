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

This plan tests the conditions that test left out, which are where real use
differs:

| Not covered by ctx-bug-test | Covered here |
|---|---|
| Long multi-turn sessions | Sessions that grow turn by turn to 131k (and 262k) |
| Prompt cache reuse (`cache_prompt`) | On, as clients use it, with a cold replay to compare |
| Parallel slots | 4 slots, 4 concurrent sessions (production default) |
| Context overflow | Sessions that run past `--ctx-size` |
| Older fork build | Fork `previous` (`20261008-b02cb35f2`, before the 10-08 Vulkan FA NaN fixes) |
| Real conversations | Scan Open WebUI history for real loops and replay them |
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
| lh-01-chat-scan | local, then Framework (read-only source) | `loop-hunt-chat-scan` | done 2026-10-15 (12 chats, 14 assistant messages, 0 hits; operator choices pending) |
| lh-01b-transcript-scan | local, then production LXCs (read-only) | `loop-hunt-transcript-scan` | todo |
| lh-02-session-harness | local | — | todo |
| lh-03-catalogue | local | — | todo |
| lh-04-deploy | Framework (production) | `loop-hunt-deploy` | todo |
| lh-05-pilot | Framework (production) | `loop-hunt-pilot` | todo |
| lh-06-matrix | Framework (production) | `loop-hunt-matrix` | todo |
| lh-07-replay-real | Framework (production) | `loop-hunt-replay` | todo (only if lh-01 found loops) |
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

Operator decision pending as required by lh-01: recommendation is no real
chat replay, D-L3 server-default sampling (no sampling fields in requests),
and Q2 excluded under D-L5. Stop and record the answer before lh-02.


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
  cse-controller `results/` (terraform/lxc/stacks/cse-controller/STACK_CONTRACT.md);
  deep-research sessions (terraform/lxc/ansible/files/deep-research-agent/README.md,
  `--list-sessions`). Reach each host the way its existing docs do;
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
none). If there are no loop hits anywhere, ask the operator where the
loops were seen (e.g. VS Code/Copilot sessions, which keep no server-side
transcript) before continuing.

Result: —

#### lh-02-session-harness

```yaml
id: lh-02-session-harness
title: Multi-turn session runner with warm/cold replay
depends_on: [lh-01b-transcript-scan]
runs_on: local
change: >
  Add scripts/loop-hunt/gen_sessions.py (deterministic synthetic sessions
  as in this plan's "The synthetic session"; seeds 1-6; writes
  scripts/loop-hunt/sessions/ plus manifest.json with hashes and planted
  answers) and scripts/loop-hunt/session_bugs.py, reusing
  framework-ctx-bugs (Client, detectors, framework_lock, readiness waits,
  infrastructure-failure handling, checkpoint/resume, restore, regrade).
  session_bugs.py runs one condition per invocation:
  --condition C1|C2|C3|C4 --entry <llama-swap id> --sessions <seed ...>
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

Result: —

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

Result: —

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
  builds with write_build_expectations.py (props for the candidate taken
  from the first pilot load). Out of scope: promotion, rollback, other
  models, OpenBao.
commands:
  - "./with-secrets-prod-tiny ansible-inventory -i ansible/inventory/inventory.yml --graph framework && echo SECRETS-OK"
  - "TASK_APPROVAL=loop-hunt-deploy ./with-secrets-prod-tiny ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-llama-builds.yml"
  - "ssh steve@framework.gibbsgreatly.xyz 'llama-builds status --no-fetch'"
  - "ssh steve@framework.gibbsgreatly.xyz 'llama-builds build fork b02cb35f2'"
  - "ssh steve@framework.gibbsgreatly.xyz 'llama-builds swap-config --dry-run | grep -c sess'"
  - "rsync -a --exclude results/ --exclude __pycache__/ scripts/framework-ctx-bugs/ steve@framework.gibbsgreatly.xyz:framework-ctx-bugs/ && rsync -a --exclude __pycache__/ scripts/loop-hunt/ steve@framework.gibbsgreatly.xyz:loop-hunt/"
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

Result: —

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

#### lh-07-replay-real

Only for chats the operator picked in lh-01. Export each chat's messages
up to the looping turn (on Framework only), then `session_bugs.py
--replay` on fork current, fork previous and upstream (and GLM if the
chat was GLM), warm and cold, 3 seeds. This is the framework's
"save → restart → reload → repeat". Approval `loop-hunt-replay`.

Result: —

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
