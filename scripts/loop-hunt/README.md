# Loop hunt tools

lh-01 is built and its approved Framework scan completed: 12 chats,
14 assistant messages, zero hits; snapshot deletion was verified. See
[the plan](../../docs/loop-hunt/plan.md) for approvals and later steps.
Python stdlib only. Synthetic tests:

```bash
python3 -m unittest discover -s scripts/loop-hunt -p 'test_*.py' -v
```

`snapshot_sqlite.py SOURCE DESTINATION` opens SOURCE with `mode=ro`, uses
SQLite's online backup API (including committed WAL data), and checks the
snapshot with `PRAGMA integrity_check`. DESTINATION must not exist; it is
created mode 0600 and removed on failure. The backup has a 120-second time
limit, configurable with `--timeout`. It neither checkpoints nor writes the
source. Only the new snapshot is switched to DELETE journaling so no WAL
sidecars are needed; pre-existing destination sidecars are refused. Do not copy the running database with `cp`.

`scan_openwebui.py --db SNAPSHOT --out DIRECTORY` reads the snapshot with
`mode=ro`. It requires Open WebUI's `chat` table with `id` and `chat` JSON
columns. It scans every saved assistant message, including alternate history
branches; the duplicate active-path `messages` array is not counted twice.
Flat-array chats are supported as a fallback. Invalid JSON or unsupported
schemas stop the scan without publishing partial reports. Missing/cyclic
parent links produce an unknown history length, explicitly counted in the
summary.

The scanner imports the existing ctx-bugs detectors from the adjacent
`framework-ctx-bugs/` locally, or `detectors.py` copied beside it on Framework.
It calls the existing loop and repetition checks on content and separately
stored reasoning. Visible control/template markers are checked literally.
`hidden-token-string` means `〈|` was visible; chat text cannot prove an
invisible token flood. Compression/repetition flags are candidates for
review, not a semantic judge's conclusions.

`hits.jsonl` contains only flagged messages: chat/message identity, stored
model id and timestamp, estimated branch history tokens (including that
answer, chars/3.5 rounded up), flags, channel/check details, stored chat/message
`params` or `parameters` with their provenance, and one excerpt up to 400
characters near a detector hit. It does not merge or infer sampling defaults.
Full chats, titles and users are not exported. `summary.md` contains counts
by model, UTC month, estimated history-size bucket and flag, with assistant
message totals as denominators. Stdout prints counts only.

Outputs must be in a mode-0700 directory and are mode 0600. Existing outputs
are never overwritten. Keep the snapshot and reports on Framework; delete
the full snapshot after scanning, including on failure. The production
command in the plan uses a trap for that cleanup. Read-only source access
still requires permission to read private chats; execute the deployment/scan
only after the operator approves `loop-hunt-chat-scan`. Then return only the
summary and up to ten flagged excerpts for the operator's replay decision.
No scan contents enter git; only aggregate counts may be recorded there.

## Benchmark and agent transcripts (lh-01b)

The same entry point keeps Open WebUI as its default format and adds:

```bash
python3 scan_openwebui.py --format lm-eval --root /srv/eval-runner/results --out SCAN/eval
python3 scan_openwebui.py --format cse --root /srv/cyberseceval/runs --out SCAN/cse
python3 scan_openwebui.py --format deep-research --root DISCOVERED_SESSIONS --out SCAN/deep-research
```

Copy `scan_openwebui.py`, `transcript_scan.py`, `snapshot_sqlite.py` and
ctx-bugs `detectors.py` into SCAN/tools on each source host. Do not copy
transcripts off those hosts. Discovery must confirm directories and count transcript files first. The code's CSE path is `runs/<run>/responses.json`, rather than
the older contract's `results/` directory. Deep-research stores sessions under
its volume mounted at `/home/app/.deep-research-agent/sessions`; discover the
host path from that exact Docker mount. Reading the directory provides the
same session inventory as `--list-sessions` without importing the application
(which can initialize config or services). No model inference or agent run
is needed for discovery.

The lm_eval adapter scans raw `resps` generations, falling back to
`filtered_resps` only when raw responses are absent. It reads the nearest
`run.json` and the matching results file for recorded identity and settings.
It does not count the extracted answer twice. CSE scans response fields,
AI turns of operation logs, and attacker/victim dialogue turns; it excludes
judge responses, environment output and duplicate rendered transcripts.
Recorded served identities take precedence over requested model names.

Deep-research scans persisted UI text/reasoning events, pairing reasoning
and final text by agent source, and retains unmatched reasoning separately.
It excludes user prompts and tool results from detection and does not count
serialized agent_session copies again. Its history estimate is the UI event
prefix, not a reconstruction of each agent's actual request. A missing
historical model/build remains unknown; the current config or agent name
is never substituted as its identity. These UI segments are the available
response evidence, not a count of network requests.

Hits include recorded run/file/index pointers, model identity provenance,
optional build/alias, date, prompt-size estimate, whitelisted sampling/limit
settings and one excerpt of at most 400 characters. API keys and arbitrary
model_args are not included. Settings are not reconstructed from defaults.
`cap-exhausted` requires recorded length termination or completion-token
counts at a recorded cap, plus no final answer. Empty text or estimated
text length alone never establishes exhaustion. It is counted separately
from degeneration flags and is not itself a looping diagnosis. Summaries
also report missing model identities and missing cap evidence.

New transcript outputs have the same private permissions and exclusive
publication as chat scans. Unknown response schemas, bad JSON, escaped
metadata symlinks refuse a report rather than turning unreadable input into
a false zero-hit result. Missing source directories refuse scanning; an
existing empty directory produces an explicit no-evidence summary (zero
responses evaluated), not evidence that loops never occurred. The production
preflight in the plan must be approved as `loop-hunt-transcript-scan` before
any LXC discovery, code copying or scanning.
