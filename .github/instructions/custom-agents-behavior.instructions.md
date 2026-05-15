---
applyTo: '**'
---

# Custom Agent Behavior

When handling agent requests in this repository:

1. Resolve agent discovery from `.github/instructions/custom-agents-discovery.instructions.md`.
2. Load the selected agent definition from `.github/agents/` before following any role-specific workflow.
3. Treat `AGENTS.md` and `.github/copilot-instructions.md` as the repository-wide operating policy for branch usage, validation, scanning, credentials, and merge rules.
4. Treat `docs/stack-lifecycle-refactor/execution-plan.md` as the human source of truth for the refactor workflow.
5. Treat `.git/ai/plan-state.yaml` as the machine source of truth for current execution state.
6. Do not invent personas, commands, packet schemas, or dependency paths that do not exist in repository files.

Interaction model for this repository:

- `planner` owns the long-lived plan and machine state.
- `executor` owns normal step execution.
- `architect` is used only for blocker triage or plan changes.
- successful executor runs should update the report and `plan-state.yaml`, then stop.
- normal successful executor runs should not route back through architect.
- the current executor packet is `.git/ai/current-step.yaml`.
- the packet authoring source is `.git/ai/current-step.spec.yaml`.
- planner should choose from explicit step templates instead of inventing packet structure:
  - `docs/stack-lifecycle-refactor/templates/step-bootstrap.spec.yaml`
  - `docs/stack-lifecycle-refactor/templates/step-main-work.spec.yaml`
  - `docs/stack-lifecycle-refactor/templates/step-closeout.spec.yaml`
  - `docs/stack-lifecycle-refactor/templates/step-validate.spec.yaml`
- plan and packet generation should use deterministic render/validate scripts:
  - `python3 scripts/render-current-step.py`
  - `python3 scripts/validate-current-step.py`
  - `python3 scripts/validate-plan-state.py`
- blockers should be reported through `.git/ai/blocker.yaml`, not a second success-handoff file.
- machine-readable detail belongs in `plan-state.yaml`, `current-step.yaml`, `reports/`, and `blocker.yaml`; chat should stay short.

## Scope Rules

- Keep work inside this repository unless the user explicitly asks otherwise.
- Prefer the registered agents in `.github/agents/` over ad hoc personas.
- Follow the branch model and promotion gates from `AGENTS.md`.
- Use `./with-secrets <command>` where repository policy requires it.
- Do not commit secrets; keep credentials in the existing SOPS and `with-secrets` workflow.

## Fallback Behavior

- If a requested agent id does not exist, say so plainly and offer the registered agents.
- If a handoff file is missing required keys, report the exact missing keys instead of guessing.
- If Copilot guidance conflicts with `AGENTS.md`, follow `AGENTS.md` and the current task.
