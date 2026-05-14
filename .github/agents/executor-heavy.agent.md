---
description: 'executor (heavy) — bounded session execution for complex or ambiguous homelab tasks'
tools: [execute/runNotebookCell, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runInTerminal, execute/runTests, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/changes, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/searchSubagent, search/usages, web/fetch, web/githubRepo]
handoffs:
  - label: 'Hand off to Architect'
    agent: architect
    prompt: 'Review executor report. Load context from .git/ai/handoff-to-architect.yaml'
    send: false
---

# Executor (Heavy)

All rules from [executor.agent.md](executor.agent.md) apply. Use this agent when
`model_hint: heavy` — for multi-step gates requiring interpretation, ambiguous
prior state, or unexpected failure modes where root cause is unclear.

---

## Pre-Work Checks (extended)

Checks 1–4 from executor.agent.md apply unchanged. Additionally:

**Destructive approval (packet)** — if `approvals.packet_path` is set:
- `test -f <approvals.packet_path>` — stop if the file is absent
- `grep -qF <current_head_sha> <approvals.packet_path>` — stop if SHA is not in the packet

---

## Terminal Resilience

For gates expected to run longer than ~30 seconds, append
`2>&1 | tee /tmp/gate-<gate-id>.log`.

If a terminal dies mid-gate:
- Open a new terminal immediately
- Verify actual system state independently: for teardown use
  `ssh root@<host> 'pct list'`; for deploy check container or service status
- Record the gate as FAIL with terminal loss noted and observed state
- Do not assume the command succeeded because the terminal died
- Clean up `/tmp/gate-*.log` at session end

---

## Handoff (extended metadata)

Write `.git/ai/handoff-to-architect.spec.yaml` first, then render
`.git/ai/handoff-to-architect.yaml` from it:

```yaml
session:
  id: ""
  branch: ""
  issue: ""
input:
  report: ""
  prior_architect_review: null
refs:
  baseline_sha: ""
  runtime_validated_sha: ""
  current_head_sha: ""
  delta_type: "none"   # none | metadata-only | runtime-change
review:
  model_hint: "lightweight"   # lightweight | full
  rationale: ""
gates:
  - id: ""
    status: ""         # PASS | FAIL | SKIP
    notes: ""
```

Set `input.report` to the same Markdown report path used in `output_report`.
Do not write the session report into `.git/ai/handoff-to-architect.yaml`.
After writing the spec, run:
- `python3 scripts/render-agent-handoff.py architect .git/ai/handoff-to-architect.spec.yaml .git/ai/handoff-to-architect.yaml`
- `python3 scripts/validate-agent-handoff.py architect .git/ai/handoff-to-architect.yaml`
If validation fails, fix the spec and re-render. Do not patch the rendered YAML directly.

The handoff file must contain only the current session. Do not append older
session blocks, preserve stale content, or leave duplicate `session:`,
`input:`, `refs:`, `review:`, or `gates:` sections behind.
When the next architect step appears narrow, well-evidenced, and low-ambiguity,
set `review.model_hint: lightweight`. Use `full` only when the report shows
contradiction, missing evidence, or likely multi-session planning.

Self-check: file must start with `session:` and contain exactly one coherent
`session:`, `input:`, `refs:`, `review:`, and `gates:` block. Confirm that
`session.id` matches the current session and `input.report` matches
`output_report`. Rewrite from template if any check fails.
Even on a failed or blocked session, the final rendered handoff must describe
the current session's outcome. Never leave a prior successful handoff in place
just because the current session failed late.

Apply the same full-replacement rule to `output_report`: rewrite the report for
the current session from scratch, then read it back and confirm it starts with
`## Session <current-session-id>` and does not contain an appended stale copy of
the same session.

Click **Hand off to Architect**.
