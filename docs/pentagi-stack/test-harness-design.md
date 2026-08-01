# PentAGI Automated Test Harness — Design Sketch

Status: **implemented and run repeatedly** — `scripts/pentagi-test-harness/`
(runner: `run_sequence.py`, config: `test_sequence.json`, usage:
`README.md`). See "Implementation notes" below for what changed from
this design during actual use, and `lessons-learned.md`'s "Laguna S 2.1
as adviser/solo model, autonomous test harness" section for the bugs
found and fixed along the way. This document otherwise remains the
original design rationale — see [harness-target.md](./harness-target.md)
for the dedicated Struts2 + Redis target on `pve-test-vm` it runs
against. The rest of this file documents a concrete plan for
scripting repeated PentAGI flow runs (varying model/config between runs)
instead of manually starting flows and polling status through the UI, as
this engagement has done throughout `lessons-learned.md`. Written up
because it's genuinely buildable — PentAGI's GraphQL API exposes flow
lifecycle control, confirmed by reading the resolver source directly
rather than guessing.

## Motivation

Every comparison run so far (Kali VM vs vanilla vs custom stack, the
reasoning-budget bump, the ctx-size fix, the mentor stop-streak limit) was
driven by hand: start a flow in the UI, repeatedly SSH in and query
`pgvector`/`pgvector-vanilla` via `psql` to check subtask status, eyeball
toolcall content, write findings into a markdown file. That doesn't scale
to "run N variants overnight and compare in the morning." A script can
own the repetitive parts — starting flows, waiting for completion,
swapping config, resetting the target, logging results — while a human
still reads the qualitative output (this is a judgment task, not something
to fully automate away).

## What already exists in PentAGI to build on

Confirmed by reading `backend/pkg/graph/schema.resolvers.go` and
`backend/pkg/graph/model/models_gen.go` directly (not assumed):

- **Auth**: `POST /auth/login` (REST, cookie-session based —
  `router.go:266`, `authGroup.POST("/login", authService.AuthLogin)`).
  A plain `curl -c cookiejar` login gets a session cookie usable for
  subsequent GraphQL calls.
- **Flow lifecycle mutations** (`schema.resolvers.go`):
  - `createFlow(modelProvider: String!, input: String!, resourceIds: [Int64!])`
    → `Flow` — this is the exact call the web UI itself makes when you
    type a prompt and hit start. `modelProvider` selects which configured
    provider/model to use (so a harness could alternate providers per run
    if multiple are registered, not just swap config files).
  - `stopFlow(flowId)`, `finishFlow(flowId)`, `deleteFlow(flowId)` —
    for aborting a run that's gone off the rails (e.g. hit the same
    "ignoring six stop verdicts for 4 hours" pattern we fixed for the
    fork) without waiting out the full 100-iteration cap.
- **Polling queries**: `flows`, `flow(flowId)`, `tasks(flowId)` return
  typed `Flow`/`Task`/`Subtask` objects with a plain `status: StatusType`
  enum field (`models_gen.go:199-207, 462-490`) — no need to shell out to
  `psql` from the harness; poll `tasks(flowId) { status subtasks { status
  title } }` on an interval instead. (The manual `psql` queries this
  session used remain useful for deep inspection of toolcall content —
  GraphQL doesn't expose individual toolcall args/results as cleanly as
  the raw `toolcalls` table did.)

## Proposed architecture

```
┌─────────────────┐     createFlow / poll status      ┌──────────────┐
│  driver script    │ ─────────────────────────────────▶│  PentAGI     │
│  (harness.py)     │ ◀───────────────────────────────── │  GraphQL API │
└────────┬─────────┘        Flow/Task/Subtask status     └──────────────┘
         │
         │ between runs:
         ├─▶ swap model/role config (custom.provider.yml, models-preset.ini)
         ├─▶ restart/reload affected containers
         ├─▶ reset target VM to clean snapshot
         └─▶ write per-run result file (config used + final status + notes)
```

### 1. Flow lifecycle (per run)

1. `POST /auth/login` with harness credentials → session cookie.
2. `mutation { createFlow(modelProvider: "...", input: "<prompt text>") { id } }`
   → capture `flowId`.
3. Poll `query { tasks(flowId: $id) { status subtasks { id status title } } }`
   on an interval (start at ~60s, back off to ~300s after the first few
   minutes — matches the cadence this session already used manually).
4. Stop condition: task `status` reaches `finished`/`failed`, **or** a
   watchdog timeout fires (see Known constraints below — a stuck run
   should be `stopFlow`'d rather than left to run indefinitely).
5. On completion, pull the full subtask list + a toolcall summary (via
   `psql` against the flow's own `pgvector`/`pgvector-vanilla` container,
   same queries used throughout this session) into the run's result file.

### 2. Config-swap mechanism (between runs)

Different levers depending on which stack is under test — confirmed from
this session's actual files, not assumed:

- **Custom (llama.cpp) stack, per-role model/sampling**: edit
  `/opt/pentagi/conf/custom.provider.yml` (role → model/temperature/
  max_tokens mapping). `custom.go`'s `DefaultProviderConfig` reads this
  file via `os.ReadFile` at provider construction time — **not hot
  reloaded**, so this requires restarting the `pentagi` container
  (`docker compose up -d --force-recreate pentagi` or equivalent) between
  runs that change it.
- **llama.cpp router itself, per-model serving params** (ctx-size,
  reasoning-budget, temperature floor): edit
  `/opt/llamacpp-docker/models-preset.ini`. Two reload paths, both
  already validated this session:
  - `GET /v1/models?reload=1` — hot-reloads only the models whose preset
    changed, no container restart needed (confirmed: reloading Qwen3.6
    left gpt-oss-120b untouched).
  - Router-level flags in `docker-compose.yml`'s own `command:` block
    (e.g. a global `--ctx-size`) **override** every per-model preset
    value (`common_preset::merge()`, "overwrite existing options") — if
    the harness ever needs to change something at that level, it needs
    `--force-recreate`, not just a config edit + reload hit.
- **Ollama-backed vanilla stack**: `OLLAMA_SERVER_MODEL`/
  `OLLAMA_SERVER_CONFIG_PATH` env vars — changing these needs a
  `pentagi-vanilla` container recreate, same as the custom stack's
  `LLM_SERVER_CONFIG_PATH`.
- **Model residency**: swapping which models are loaded at all (e.g.
  testing Laguna S 2.1 in place of gpt-oss-120b for `adviser`) uses the
  router's `POST /models/unload {"model": "<name>"}` to free one model
  before another needs the memory — already used this session to free
  ~81GB before standing up the vanilla instance.

### 3. Target reset (between runs)

**Resolved for the harness's default target.** A new dedicated target,
[`harness-target`](./harness-target.md) (Struts2 S2-045 + unauthenticated
Redis, `192.168.1.55` on `pve-test-vm`), was stood up specifically to
sidestep this problem rather than solve it for Metasploitable2: both its
services are either stateless per-request (Struts2's OGNL injection, as
long as the harness only ever sends read-only commands) or have zero
persistence by design (Redis, `--save "" --appendonly no`, no volume —
starts completely empty on every container restart). Verified live by
re-running the deploy twice in a row with no manual cleanup between runs
and confirming both services came back healthy with the evidence marker
still retrievable. This should be the harness's default target going
forward.

Metasploitable2 remains available for occasional/manual comparison runs
(as it was used earlier this engagement), but if it's ever wired into the
automated harness itself, the original open item still applies: it's
actually hosted on `pve` (production, VMID 120), not `pve-test-vm` —
confirmed via `docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md`'s
VMID inventory — so a reset story for it would need the full production
approval flow, not just a `qm rollback`.

### 4. Results logging

One file per run (`docs/pentagi-stack/artifacts/harness-runs/<flow_id>.md`
or similar, scratch/gitignored per the existing artifacts pattern), capturing:
- Config: which stack, which model(s) per role, temperature/ctx-size/
  reasoning-budget values, prompt text used
- Timestamps: start, end, wall-clock duration
- Final status per task/subtask, toolcall count per subtask
- Bug-pattern flags: did it hit the mislabeling pattern, the empty-args
  `done`, the ordering bug, a `reflector called too many times` crash,
  an unverified/rule-violating bare `done` — a simple checklist against
  the failure modes already catalogued in `lessons-learned.md`, so
  results are comparable across runs without re-deriving the taxonomy
  each time.
- A durable summary rolls up into `lessons-learned.md` once a batch of
  runs is done, same pattern as this session's manual comparisons.

### 5. Orchestration loop (driver script shape)

```
for variant in variants:
    apply_config(variant)               # edit + reload/restart as needed
    reset_target()                      # snapshot rollback
    flow_id = create_flow(variant.prompt, variant.provider)
    result = poll_until_done(flow_id, timeout=variant.timeout)
    write_result_file(variant, result)
sync: summarize_batch()                 # human reviews, folds into lessons-learned.md
```

Each iteration is independent and resumable — if the harness crashes
mid-batch, already-completed runs' result files are the record; no
in-memory state to lose.

## Known constraints (why this doesn't turn into unattended 24/7 testing)

- **Model cold-load time dominates**: gpt-oss-120b alone took ~60-90 min
  to cold-load earlier this session. Any variant that changes which
  models are resident, not just their sampling params, pays this cost
  every time — a batch of 5 such variants is realistically a multi-hour
  affair no matter how well the harness itself is written.
- **GPU/unified-memory ceiling**: framework.gibbsgreatly.xyz's OOM
  history this engagement (concurrent Qwen3.6 + gpt-oss-120b at
  ctx=65536 each) means the harness must track what's currently loaded
  and not blindly fire a variant that would double-load past the ceiling
  — `unload` the outgoing model before loading the incoming one, not
  after.
- **Mentor stop-streak limit affects run duration, not just outcome**:
  our fork's `EXECUTION_MONITOR_STOP_STREAK_LIMIT` (default 2) means a
  bad variant should fail fast now rather than the 4+ hour runaway seen
  pre-fix — good for harness throughput, but the vanilla/Ollama stack has
  no equivalent, so a bad vanilla-stack run can still eat its full
  wall-clock budget. Set a harness-level watchdog timeout regardless of
  which stack is under test; don't rely solely on PentAGI's own limits.
- **This is still an authorized-pentest-only target**: automating "run
  it more times" doesn't change scope — still only `192.168.1.113`, still
  the restrictions in the task prompt itself. No change in authorization
  posture from what's already been running manually.

## Open items before building (resolved)

1. ~~Confirm Metasploitable2's actual Proxmox node/VMID and snapshot
   rollback path (§3).~~ Moot — the harness runs exclusively against
   `harness-target` (stateless by design, §3), never Metasploitable2.
2. ~~Confirm whether `createFlow`'s `modelProvider` argument can select
   between already-configured providers.~~ Not needed in practice —
   every run so far has used a single `"custom"` provider and swapped
   which model(s) sit behind each role instead.
3. Harness auth: reuses the existing PentAGI admin account
   (`admin@pentagi.com`), password passed via `PENTAGI_ADMIN_PASSWORD`
   env var (SOPS-backed, `terraform/secrets.common.enc.yaml`), never
   written to the config file.
4. Polling transport: GraphQL only in the end (`tasks(flowId: ID!)` —
   note **`ID!`, not `Int64!`**, a real bug the first live test caught).
   `psql` against `pgvector` is still used for the post-run toolcall
   summary and any deep-dive investigation, exactly as anticipated.

## Implementation notes (2026-07-30 to 2026-08-01)

What actually shipped, and where it diverged from the design above:

- **`all_roles` mode, not anticipated in the original design**: beyond
  swapping just the `adviser` role, the runner supports pointing
  *every* role at one model (`swap_all_roles_to_model()`), used to test
  Laguna S 2.1 standalone across the whole flow rather than paired with
  Qwen3.6. This turned out to be the more interesting comparison in
  practice — see `lessons-learned.md` for the flow-25 (dual-model) vs
  flow-27/28-30 (Laguna-solo) results.
- **Memory-safety gate**: `check_memory()` (min free GiB threshold) plus
  `free_ollama_if_needed()` guard every Laguna-loading run, added after
  a real OOM this session traced to Ollama holding unrelated models
  resident indefinitely — not just llama.cpp's own state.
- **Watchdog is a hard stop, not just a design note**: `poll_flow()`
  calls `stopFlow` and returns whatever partial status exists once
  `watchdog_timeout_minutes` elapses, so a stuck run never blocks the
  rest of the sequence. Tuned down from 180 to 120 minutes after
  watching real runs — long enough for genuine multi-subtask progress,
  short enough that a stuck run doesn't eat the whole night alone.
- **Result files landed in the wrong place at first**: `RESULTS_DIR`
  originally assumed the script lived inside a git checkout
  (`<repo>/scripts/...`); since it's deployed standalone to
  `/opt/pentagi-test-harness/` on the `pentagi-stack` LXC, that resolved
  to `/` on the LXC's own filesystem. Fixed to a plain `results/`
  subdirectory next to the script, synced into
  `docs/pentagi-stack/artifacts/harness-runs/` manually after each
  batch.
- **`write_result_file` crashed for `all_roles` runs** (`KeyError:
  'qwen_ctx_size'`, since those configs have no separate Qwen3.6) —
  every `all_roles` run's result file silently failed to write until
  fixed; see `lessons-learned.md`.
- **Runs detached via `setsid nohup ... & disown` over SSH survive
  session/VS Code closure as intended** — confirmed across multiple
  multi-hour unattended sequences, including one that ran through a
  full overnight/next-morning gap.
