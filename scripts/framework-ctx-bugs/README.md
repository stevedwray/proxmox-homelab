# Framework context bug harness

Phase 2 is local code and synthetic validation only. The real Framework test
has **not run**. See [the plan](../../docs/ctx-bug-test/plan.md) for D1–D7,
production approvals, and the remaining phases.

The Python harness is stdlib only except `redis` for the production run lock.
`framework_lock.py` is an unchanged copy of the shared Framework lock. Dry runs
use a local file lock and do not import Redis, inspect host processes/kernel
logs, or read production credentials. The stub binds only to loopback; dry
runs refuse remote URLs and servers without its explicit marker.

## Local gates

```bash
python3 -m unittest discover -s scripts/framework-ctx-bugs -p 'test_*.py' -v
python3 scripts/framework-ctx-bugs/gen_prompts.py
python3 scripts/framework-ctx-bugs/gen_prompts.py
git diff --exit-code scripts/framework-ctx-bugs/prompts
```

For a full 16-cell stand-in run, in separate local terminals:

```bash
python3 scripts/framework-ctx-bugs/stub_server.py --port 18080
```

```bash
scripts/framework-ctx-bugs/run.sh --foreground --dry-run \
  --base-url http://127.0.0.1:18080 \
  --results-root scripts/framework-ctx-bugs/results
```

This produces 288 completed requests: 12 full cells × 22 and four Laguna fork
short cells × six. Four triggering S1 probes are also saved, separately from
the six short requests. Clean responses have no flags. The Qwen fork 32k cell
contains a greedy S1 reasoning loop, greedy S2 reasoning repetition, sampled
S3 seed 1 absent-fact hallucination, greedy S4 runaway, and sampled S5 seed 2
template leak. All four Laguna fork cells replay the hidden token flood.
`--clean` on the stub disables all injections. It also supports
`--delay-request N --delay-seconds S` for interruption experiments.
`--kernel-log-error` simulates a failed kernel journal command: completions
continue, with the failure recorded in every affected `evidence_error`.

## Prompts and fit

`gen_prompts.py` creates S1–S5 JSON message arrays and `F-template.json` from
seed 4471, with checksums, expected answers, needle record/character positions
and conservative character-count estimates in `prompts/manifest.json`.
S3 has 200 equal-width records. S5 has eight user turns and seven fixed
assistant turns. The 3.0-characters-per-token estimate is only a development
check; it is not a tokenizer claim.

Before sending any completion in a cell, the harness renders each message
array using `/apply-template`, then calls `/tokenize` on the rendered prompt,
including template special tokens and the generation prefix. Every S prompt
must satisfy `prompt_tokens + 16384 + 2048 <= ctx_size`, even in short form.
No raw-text estimate substitutes for this gate.

F uses its own fixed-seed log. Each candidate length relocates S3's five
needle records to 5/25/50/75/95% of the log and recomputes the critical-host
count. No filler contains either absent fact. The harness searches the record
count and adds inert audit padding to land exactly on 14,336 / 47,104 / 79,872 /
112,640 rendered prompt tokens. It refuses a cell if it cannot reach the exact
target. Saved F bytes, SHA-256, needle positions, expected answers and actual
token count are stored in the run's `prompts/` and `run.json`. The second build
reuses the saved bytes and verifies the token count again.

## Later production runs

These commands document later phases; they require the repository's production
preflight and approval flow. They were not executed during phase 2.

Phase 1 must record exact build expectations in an operator-owned JSON file:

```json
{
  "nathanw": {"name": "<current build directory>", "sha": "<full commit SHA>", "build_info": "<expected /props value>", "props": {}},
  "upstream": {"name": "<current build directory>", "sha": "<full commit SHA>", "build_info": "<expected /props value>", "props": {}}
}
```

Read-only commands on Framework for that later inspection include
`llama-builds status --json --no-fetch`,
`cat /storage/llama-builds/fork/current/build.json`,
`cat /storage/llama-builds/upstream/current/build.json`, and each current
`bin/llama-server --version`. The build JSON's `version` can describe the
compiler rather than the server's `/props` build identity, so the harness
requires an explicit expected `build_info` rather than guessing from it.
It checks names and SHAs against local build JSON before taking the shared
lock and checks alias, context, build identity and slots after every load.

Before the pilot, save one complete real `/props` response from each build
under that build's `props` key in this builds JSON (replace the empty objects
above). Confirm that the responses contain the fields read by `check_props()`:
`model_alias`, `n_ctx` or `default_generation_settings.n_ctx`, `total_slots`,
and `build_info`. Check that aliases/context values are in the expected
locations, that there is one slot, and that the top-level expected
`build_info` exactly matches the response's value and JSON type. Retain the
raw responses in the builds JSON, which is copied into `run.json`. If the
real schema differs, resolve that mismatch before starting the pilot.

After catalogue deployment and production approval, the detached pilot is:

```bash
./run.sh --builds-json /path/to/build-expectations.json --sizes 131072 --greedy-only
./run.sh --status
```

Omit `--sizes` and `--greedy-only` for the full matrix. Live defaults are
llama-server `http://127.0.0.1:8080`, llama-swap `http://127.0.0.1:8099`, API
key file `/etc/llamacpp/api-key`, Redis config `/etc/llama-builds/backends.json`,
and results root `/storage/artifacts/framework-ctx-bugs`. `redis` must already
be available in the Python environment used by the service. Live evidence
uses `/proc` for server identity and `sudo -n journalctl` for kernel and
llama-swap system-unit logs. Kernel capture is bounded from just before each
completion request to just after it (`-k --since @<epoch> --until @<epoch>
--no-pager -o short-iso`); only that window is appended once to `dmesg.txt`.
Capture or identity failures are recorded in `evidence_error` without aborting
completions. Cell logs use `-u llama-swap.service --since <cell start>
--no-pager`; a failed capture is written into the cell log and the run continues.
The launcher follows the existing benchmark's `systemd-run --user`
pattern and enables user lingering if needed. Use `--foreground` when desired.

Sampled runs send the values in the single `SAMPLING` constant in
`ctx_bugs.py`; server defaults cannot override them. Qwen uses D3's thinking
recipe. Laguna uses Poolside's published recommendation (temperature 0.7,
top_p 0.95), with top_k 20 and disabled min_p from its base checkpoint's
shipped config. Pinned sources are recorded beside the constant and in each
run's metadata. The 16,384-token cap applies to normal requests. A Laguna fork
S1 greedy that shows a hidden-token flood is retained as a triggering probe,
then the cell runs six greedy requests at 2,048 tokens. All fit checks retain
the full 16,384-token reserve.

To run D1's extra candidate cell later, choose the size explicitly and supply
expectations matching `fork/candidate`:

```bash
./run.sh --candidate --models laguna-s-2.1 --builds nathanw --sizes 32768 \
  --builds-json /path/to/candidate-expectations.json
```

This does not build or promote a candidate. To reproduce one cell with three
new sampled seeds, use a new run directory and select that cell:

```bash
./run.sh --models qwen3.8-flash-next-q4 --builds upstream --sizes 65536 \
  --extra-seeds 4 5 6 --builds-json /path/to/build-expectations.json
```

## Checkpoints and outputs

Each completed request is fsynced to `results.jsonl` and saved under
`raw/<cell>/<prompt>-<run>.json`. Errors are completed attempts with `crash`
flags; a process interrupted during a request leaves that request pending.
A partial final JSONL append is discarded on resume. A complete malformed
record or changed settings, code hashes, build expectations or prompt hashes
refuses resume. A local checkpoint lock prevents concurrent writers.

Resume with the same arguments and an explicit directory:

```bash
./run.sh --run-dir /storage/artifacts/framework-ctx-bugs/<timestamp> \
  --builds-json /path/to/build-expectations.json
./run.sh --status --run-dir /storage/artifacts/framework-ctx-bugs/<timestamp>
```

Other outputs are `run.json`, `progress.json`, `run.log`, `prompts/`, `logs/`
(llama-swap's server journal per cell), `dmesg.txt`, `findings.json` and
`report.md`. The report lists flags by cell/request, first differing characters
for divergences, F accuracy, server tok/s and wall time. Comparisons discovered
later are persisted back to JSONL and raw files. Build divergence is information
only; incomplete sampled comparisons do not establish build bugs. Unattributed
flags require three more seeds, and F degradation on both builds is a model
limit. The optional cloud judge is outside this harness.

The shared Redis lock is acquired before any model load, renewed during the
run, checked before requests, and released on exit. Success, failure and
handled interruption reload the model captured from `/props` before the run
(`restore_model` in `run.json`) before releasing the lock. Resume preserves
that saved model. If :8080 did not answer, or the saved model is a context-test
entry ending in `-ctx32k`, `-ctx64k`, `-ctx96k` or `-ctx131k`, restoration uses
`glm-5.3-flash-upstream`. `restored_model` records the alias actually restored;
the existing `restored_default` boolean indicates successful restoration.
If restoration fails, the run is marked failed with the restore error. A lost
lock stops further model changes. An uncatchable kill cannot run cleanup;
the lock TTL expires and a later approved resume restores the saved model on exit.
