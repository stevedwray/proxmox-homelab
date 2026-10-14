# Loop hunt tools

The local part of lh-01 is built; no production scan has run. See
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
