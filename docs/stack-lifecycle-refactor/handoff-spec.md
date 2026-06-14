# Agent Handoff Rework

## Problem

Free-form agent-written YAML has been too fragile:

- stale blocks get appended into the next handoff
- malformed YAML slips through
- closeout and main-work sessions get blended together
- machine-readable files become hard to trust

The fix is to stop treating `.git/ai/handoff-to-*.yaml` as free-form authoring
targets.

## New Flow

1. Architect or executor writes a small **spec** file.
2. A local renderer turns the spec into canonical machine-readable YAML.
3. A validator checks the rendered YAML before the next handoff is used.
4. Only the rendered YAML is used by the next agent.

## Files

- Spec inputs:
  - `.git/ai/handoff-to-executor.spec.yaml`
  - `.git/ai/handoff-to-architect.spec.yaml`
- Rendered machine contracts:
  - `.git/ai/handoff-to-executor.yaml`
  - `.git/ai/handoff-to-architect.yaml`
- Tools:
  - `scripts/render-agent-handoff.py`
  - `scripts/validate-agent-handoff.py`

## Commands

Executor handoff:

```bash
python3 scripts/render-agent-handoff.py executor \
  .git/ai/handoff-to-executor.spec.yaml \
  .git/ai/handoff-to-executor.yaml
python3 scripts/validate-agent-handoff.py executor \
  .git/ai/handoff-to-executor.yaml
```

Architect handoff:

```bash
python3 scripts/render-agent-handoff.py architect \
  .git/ai/handoff-to-architect.spec.yaml \
  .git/ai/handoff-to-architect.yaml
python3 scripts/validate-agent-handoff.py architect \
  .git/ai/handoff-to-architect.yaml
```

## Design Rules

- The spec file may be agent-authored.
- The rendered YAML should never be edited by hand.
- Validation is required before handoff.
- A failed validation means the agent must fix the spec, not patch the rendered YAML.

## Session Types

Executor specs must declare `session.type` as one of:

- `bootstrap`
- `main_work`
- `closeout`
- `promote`
- `evidence`

This makes the session intent explicit even when the gates are still custom.

## Why This Is Better

- canonical key ordering
- duplicate-key detection
- single-document enforcement
- hard failure on empty `expect`, `|| true`, and malformed sections
- smaller authoring target for agents
- cleaner separation between human reasoning and machine contract output
