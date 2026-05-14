---
applyTo: '**'
---

# Custom Agent Behavior

When handling agent requests in this repository:

1. Resolve agent discovery from `.github/instructions/custom-agents-discovery.instructions.md`.
2. Load the selected agent definition from `.github/agents/` before following any role-specific workflow.
3. Treat `AGENTS.md` and `.github/copilot-instructions.md` as the repository-wide operating policy for branch usage, validation, scanning, credentials, and merge rules.
4. Treat `.git/ai/*.yaml` files as the handoff/report contract for architect, executor, and planner flows.
5. Do not invent personas, commands, handoff schemas, or dependency paths that do not exist in repository files.

Interaction model for this repository:

- `architect` and `planner` may ask the user for missing context, approval, or permission boundaries.
- `architect` and `planner` should focus on design, scope, decomposition, completion criteria, and concise operator-facing output rather than live command execution.
- `architect` and `planner` should prefer positive workflow instructions: define the intended sequence, completion criteria, and handoff boundary rather than relying mainly on prohibitions.
- `architect` and `planner` should prefer concrete handoff contracts: repo-root file paths in gates, real values or `null` in required fields, explicit discovery gates instead of symbolic placeholders, and no assumption that bootstrap is already satisfied unless the handoff/report chain proves it.
- handoff generation should use a spec-render-validate flow rather than free-form editing of the final machine contract:
  - write `.spec.yaml`
  - render `.yaml` with `scripts/render-agent-handoff.py`
  - validate `.yaml` with `scripts/validate-agent-handoff.py`
  - if validation fails, fix the spec and re-render; do not patch the rendered YAML directly
- when `architect` or `planner` writes a `.git/ai/*.yaml` handoff, it should fully replace the spec file, render the machine contract, and confirm it is a single coherent YAML document rather than mixed old/new content.
- executor handoffs should contain exactly one session only. Do not emit multiple candidate sessions, stale tails, or blended old/new gate blocks into a single `.git/ai/handoff-to-executor.yaml`.
- executor handoffs should use `session.issue: null` when there is no issue value yet; do not use empty strings for unknown issue fields.
- for bootstrap/setup sessions, architect/planner should make it explicit that the executor is allowed to start on a different branch and establish the target branch during the session before the final target guard is enforced.
- architect/planner should choose one coherent branch-start pattern per executor handoff: either start on the target branch from the beginning, or explicitly start on another branch and switch before the decisive target guard. Do not mix both patterns in one session contract.
- for explicit start-elsewhere-then-switch sessions, `session.branch` should name the starting branch, while `env.target_guard_expect` may name the later decisive branch only if the handoff clearly says the switch happens in-session before that guard is enforced.
- machine-readable detail belongs in `.git/ai/*.yaml` and session reports, not in verbose chat dumps. In chat, prefer a short verdict, short blocker summary, and the path of any written handoff/report file.
- `executor` and `executor-heavy` should execute the bounded handoff without asking the user follow-up questions.
- `executor` and `executor-heavy` own live repo inspection, git commands, validation commands, and evidence capture unless the handoff says otherwise.
- for bootstrap/setup sessions, executors should treat an initial target-guard mismatch as informational when later in-scope gates are clearly responsible for creating, checking out, or verifying the target branch.
- executors should also treat an initial target-guard mismatch as informational for explicit start-elsewhere-then-switch sessions when the handoff clearly declares the starting branch and later target branch.
- when an executor finishes all in-scope gates, it should stop after writing the report and `.git/ai/handoff-to-architect.yaml` rather than asking the operator what to do next.
- executors should not offer optional follow-on actions after completion, including PR suggestions, opening links, merge suggestions, or extra out-of-scope verification.
- if an executor discovers a missing approval, missing privilege, or unresolved ambiguity, it should report back through `.git/ai/handoff-to-architect.yaml` instead of asking the user directly.
- if an executor session fails or stops after partially completing work, it must still overwrite `.git/ai/handoff-to-architect.spec.yaml` and the rendered `.git/ai/handoff-to-architect.yaml` with the current session result; never leave a stale prior-success handoff in place.
- if a gate validates report text or evidence-path citations, the executor should update the report before that gate runs and rerun the gate after the update if needed.
- executors may include a lightweight architect review recommendation in `.git/ai/handoff-to-architect.yaml` when the next architect step is narrow, well-evidenced, and low-ambiguity; this is only a hint for operator model choice, not a workflow decision.
- when an executor writes `.git/ai/handoff-to-architect.yaml`, it should write `.git/ai/handoff-to-architect.spec.yaml`, render the final file, and confirm it contains only the current session rather than concatenated stale blocks.
- architect/planner should recommend or accept `lightweight` review only for evidence review and narrow docs-only scoping. Any branch-bootstrap design, commit/push closeout design, shell-gate repair, or ambiguous next-step planning should be treated as `full` model work.
- closeout-handoff authoring is especially strict: gate names, commands, and expectations must still align after the file is written, and stale duplicate tails from earlier handoffs are not acceptable.
- executor handoffs should not use blank `expect` fields or suppress failure with `|| true` in gate commands. If success is exit-code based, say so explicitly in `expect`.
- main-work executor handoffs should not combine file authoring with `git commit` or `git push` in one gate, and should not sneak closeout work into an implementation session.
- executor handoffs should use real repo paths in `boundary` and gate commands; do not invent shortened path aliases that do not match the repository.
- architect/planner should avoid pinning an exact starting `HEAD` in executor gates unless that exact commit is truly required and evidenced by the latest relevant report. For most metadata-only continuation work, record current HEAD as evidence and validate ancestry/branch intent instead of blocking on a stale tip SHA.

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
