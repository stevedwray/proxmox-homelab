# Codex Agent Docs

These files are Codex-specific role guides for this repository.

They exist separately from `.github/agents/`, which is currently used by Copilot.
Do not modify the Copilot agent files just to make Codex behave differently.

## How To Use

When you want Codex to adopt one of these roles for a task, invoke it explicitly
in the prompt, for example:

- `Use .codex-agents/executor.md for this task.`
- `Use .codex-agents/architect.md to review the latest executor report.`
- `Use .codex-agents/planner.md to decompose this into sessions.`

These files are guidance, not a native runtime registration mechanism. Codex
will follow them when asked, subject to higher-priority runtime and safety rules.

## Design Goals

- Preserve the existing `.git/ai/` handoff and report workflow
- Avoid cross-tool drift with Copilot-owned files under `.github/agents/`
- Keep repository-wide policy in `AGENTS.md`
- Keep Codex role behavior in a separate, explicit location

## Current Session Files

The role docs assume the existing handoff/report conventions in `.git/ai/`,
including:

- `.git/ai/handoff-to-executor.yaml`
- `.git/ai/handoff-to-architect.yaml`
- `.git/ai/handoff-to-planner.yaml`
- `.git/ai/session-<NN>.yaml`
- `.git/ai/sessions/<id>-report.md`

## Notes

- `.codex` already exists in this repository as a file, so this repo uses
  `.codex-agents/` instead of `.codex/agents/`.
- If the Copilot and Codex role docs diverge, treat `AGENTS.md` plus the current
  user request as the source of truth for repo-wide behavior.
