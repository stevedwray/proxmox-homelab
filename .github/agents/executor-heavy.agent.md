---
description: 'executor (heavy) — runs complex or ambiguous current-step packets'
tools: [execute/runNotebookCell, execute/getTerminalOutput, execute/killTerminal, execute/sendToTerminal, execute/runTask, execute/createAndRunTask, execute/runInTerminal, execute/runTests, read/getNotebookSummary, read/problems, read/readFile, read/viewImage, read/readNotebookCellOutput, read/terminalSelection, read/terminalLastCommand, read/getTaskOutput, edit/createDirectory, edit/createFile, edit/createJupyterNotebook, edit/editFiles, edit/editNotebook, edit/rename, search/changes, search/codebase, search/fileSearch, search/listDirectory, search/textSearch, search/searchSubagent, search/usages, web/fetch, web/githubRepo]
handoffs:
  - label: 'Escalate Blocker'
    agent: architect
    prompt: 'Review blocker. Load context from .git/ai/blocker.yaml'
    send: false
---

# Executor (Heavy)

All rules from [executor.agent.md](executor.agent.md) apply.

Use this agent when:

- `model_hint: heavy`
- branch/bootstrap semantics are non-trivial
- closeout or promotion work involves multiple risky git operations
- a prior lightweight run hit a real technical blocker

Additional rule:

- For long-running gates, preserve durable logs with `tee` under
  `.git/ai/reports/` or a step-local evidence directory when the packet allows it.
