The pattern is real, but I’d think of it as **four different customization layers**, not one “agent code” system.

For the repo-specific rollout plan that applies these ideas to this homelab,
see [implementation-plan.md](implementation-plan.md).

## The standard repo layout

A good modern Copilot-aware repo usually looks like this:

```text
.github/
  copilot-instructions.md          # repo-wide, always-on guidance

  instructions/
    terraform.instructions.md      # conditional/path-specific rules
    ansible.instructions.md
    tests.instructions.md
    security.instructions.md

  prompts/
    plan-change.prompt.md          # reusable slash-command workflows
    validate-change.prompt.md
    review-pr.prompt.md

  agents/
    planner.agent.md               # specialized personas/tool sets
    implementer.agent.md
    reviewer.agent.md
    security-reviewer.agent.md

  skills/
    terraform-plan-review/
      SKILL.md
      scripts/
        summarize-plan.sh
    github-actions-debugging/
      SKILL.md
```

I do **not** see `.github/code` as a documented standard Copilot customization directory. The documented project-scoped locations are mainly `.github/copilot-instructions.md`, `.github/instructions`, `.github/prompts`, `.github/agents`, and `.github/skills`. VS Code’s docs also show this exact family of directories in the parent-repository discovery example. ([Visual Studio Code][1])

## Use each layer for a different job

### 1. `.github/copilot-instructions.md`: the repo operating manual

This should be the **short, always-on source of truth** for the repo. Use it for things that should affect almost every task: repo purpose, architecture, stack, coding conventions, build/test commands, “do not touch” areas, security rules, deployment assumptions, and validation gates. GitHub explicitly recommends repository-wide custom instructions for guidance on how Copilot should understand the project and build/test/validate changes. ([GitHub Docs][2])

For your kind of infra repos, I’d include things like:

```md
# Repository instructions

This repository manages Proxmox lab infrastructure using Terraform and Ansible.

## Golden rules
- Do not change production inventory unless the task explicitly says so.
- Prefer small, reviewable changes.
- Never commit secrets, tokens, host keys, passwords, or generated state files.
- Before editing, inspect the relevant README and existing patterns.
- After editing Terraform, run `terraform fmt` and the relevant `terraform validate`.
- After editing Ansible, run `ansible-lint` if available and check YAML formatting.

## Layout
- `terraform/` contains Proxmox resource definitions.
- `ansible/` contains provisioning roles and playbooks.
- `docs/` contains design decisions and accepted architecture.
- `.github/workflows/` defines CI validation.
```

Keep this fairly compact. GitHub’s own onboarding prompt says the file should not be task-specific and should capture build/validation steps, project layout, dependencies, and known gotchas that reduce failed agent attempts. ([GitHub Docs][2])

### 2. `.github/instructions/*.instructions.md`: conditional rules

Use these for rules that only apply to some paths or file types. VS Code applies these dynamically based on `applyTo` globs or task relevance, and the default workspace location is `.github/instructions`. ([Visual Studio Code][1])

Example:

```md
---
name: Terraform standards
description: Rules for Terraform infrastructure code
applyTo: "terraform/**/*.tf"
---

# Terraform standards

- Use explicit provider version constraints.
- Prefer variables over hardcoded environment-specific values.
- Do not modify remote state backend settings unless explicitly requested.
- Run `terraform fmt -recursive` after changes.
- Run `terraform validate` in the affected module.
```

This is better than stuffing every rule into `copilot-instructions.md`, because it keeps the global context lighter and avoids Terraform rules leaking into docs, Ansible, scripts, etc.

### 3. `.github/prompts/*.prompt.md`: repeatable slash commands

Prompt files are for **manual, reusable workflows**. They are invoked like slash commands and are not automatically applied like instructions. VS Code docs describe them as standalone Markdown files for common tasks, with `.prompt.md` extension and optional YAML frontmatter. ([Visual Studio Code][3])

Example:

```md
---
name: validate-change
description: Validate the current change using repo-standard checks
agent: agent
tools: ['search/codebase', 'runCommands']
---

Validate the current change.

1. Inspect changed files.
2. Identify the relevant validation commands from repo instructions, README files, and CI.
3. Run the narrowest safe validation first.
4. Report:
   - commands run
   - pass/fail result
   - errors
   - next recommended fix
```

Use prompts for things like `/plan-change`, `/validate-change`, `/review-pr`, `/debug-ci`, `/write-runbook`.

### 4. `.github/agents/*.agent.md`: specialized personas with tool boundaries

Custom agents are for persistent roles: planner, implementer, reviewer, security reviewer, migration specialist, etc. In VS Code they live in `.github/agents`, use `.agent.md`, and can specify description, name, tools, model, subagents, handoffs, and more. ([Visual Studio Code][4])

A strong pattern is to split **planning** from **editing**:

```md
---
name: Planner
description: Produce implementation plans without editing files
tools: ['search/codebase', 'search/usages']
model: ['Claude Sonnet 4.5', 'GPT-5.2']
handoffs:
  - label: Implement Plan
    agent: implementer
    prompt: Implement the plan above, keeping changes minimal and running validation.
    send: false
---

You are a planning agent.

Do not edit files.
Do not run destructive commands.
Produce:
1. current-state findings
2. proposed changes
3. files likely to change
4. validation commands
5. risks and rollback notes
```

Then an implementer:

```md
---
name: Implementer
description: Make minimal code changes and validate them
tools: ['search/codebase', 'edit', 'runCommands']
---

You are an implementation agent.

Follow repository instructions.
Make the smallest viable change.
Do not broaden scope.
After editing, run the relevant formatters and validation commands.
Summarize exactly what changed and what was validated.
```

For your workflow, I’d probably have:

```text
planner.agent.md           # read/search only; produces plans
implementer.agent.md       # edit + run commands
reviewer.agent.md          # review diffs, no edits unless asked
security-reviewer.agent.md # threat-model and secrets/supply-chain focus
docs-writer.agent.md       # update runbooks/design docs only
```

The `tools` field matters: omit it or use `*` and the agent gets broad access; set a small list and you create safer role boundaries. GitHub’s config reference says `tools: []` disables all tools, named tools restrict access, and unrecognized tools are ignored for compatibility. ([GitHub Docs][5])

### 5. `.github/skills/<skill>/SKILL.md`: portable capabilities

Skills are not personas. They are reusable task capabilities with instructions, scripts, and resources. GitHub says skills work with Copilot cloud agent, Copilot CLI, and VS Code agent mode; project skills can live under `.github/skills`, `.claude/skills`, or `.agents/skills`. ([GitHub Docs][6])

Use a skill when the workflow is more like “how to do this specialized operation” than “act as this role.”

Example:

```text
.github/skills/
  terraform-plan-review/
    SKILL.md
    scripts/
      summarize-plan.sh
```

```md
---
name: terraform-plan-review
description: Review Terraform plans for unintended infrastructure drift, destructive changes, and environment mistakes.
---

When reviewing a Terraform plan:

1. Identify creates, updates, deletes, and replacements.
2. Highlight any destructive operation.
3. Check whether the target workspace/environment matches the user's request.
4. Summarize risk by resource.
5. Recommend whether to proceed, modify, or abort.

Use `scripts/summarize-plan.sh` if a raw plan log is available.
```

Skills can include scripts/resources in the skill directory, and Copilot makes those files available alongside the skill instructions. GitHub warns that third-party skills are not verified and may contain prompt injections or malicious scripts, so inspect them before installing. ([GitHub Docs][6])

## The main design rule

Use the **least powerful customization** that solves the problem:

```text
Global rule?          -> copilot-instructions.md
Path/file rule?       -> .github/instructions/*.instructions.md
Repeatable task?      -> .github/prompts/*.prompt.md
Specialized persona?  -> .github/agents/*.agent.md
Reusable capability?  -> .github/skills/<name>/SKILL.md
External system/API?  -> MCP server, carefully scoped
```

This matches the direction of the current docs: start with project instructions, add targeted instruction files, automate repeated workflows with prompt files/MCP, then create custom agents and package reusable capabilities as skills. ([Visual Studio Code][7])

## Best-practice patterns

The best pattern is **plan → implement → validate → review**, with separate agents or prompts for each stage. Don’t make one mega-agent that plans, edits, reviews, deploys, and self-approves.

For infra/security work, I’d define agents with hard boundaries:

```text
Planner:       search/read only
Implementer:   edit + run local validation
Reviewer:      inspect diffs, no edits by default
Security:      inspect auth, secrets, supply chain, network exposure
Ops:           run non-destructive diagnostics
```

Avoid conflicting instructions. VS Code combines multiple instruction files when present, and “no specific order is guaranteed,” so don’t put “always use X” in one file and “never use X” in another. VS Code documents priority as personal instructions first, then repository instructions, then organization instructions, but within multiple project instruction files you should still design for clarity rather than relying on ordering. ([Visual Studio Code][1])

Keep instructions **operational**, not aspirational. “Be careful” is weak. “Before editing Terraform, run `terraform fmt -recursive`; after editing, run `terraform validate` in the affected module” is strong.

Don’t over-pin models. Agent frontmatter can specify a model, or a prioritized list of models in VS Code, but model availability and host behavior can still vary. Treat the UI/session model indicator and run diagnostics as more reliable than asking the agent “what model are you?” ([Visual Studio Code][4])

## What I’d do in your repos

For your Terraform/Ansible/Proxmox work, I’d start with only this:

```text
.github/
  copilot-instructions.md
  instructions/
    terraform.instructions.md
    ansible.instructions.md
    markdown-docs.instructions.md
  prompts/
    plan-change.prompt.md
    validate-change.prompt.md
  agents/
    planner.agent.md
    implementer.agent.md
    reviewer.agent.md
```

Then add skills only when you notice a repeated specialized workflow, for example:

```text
.github/skills/
  terraform-plan-review/
  ansible-role-validation/
  github-actions-failure-debugging/
  proxmox-lxc-template-workflow/
```

The key is to make Copilot behave less like “a clever autocomplete with repo access” and more like a constrained junior engineer who has a runbook, role boundaries, and explicit validation gates.

[1]: https://code.visualstudio.com/docs/copilot/customization/custom-instructions "Use custom instructions in VS Code"
[2]: https://docs.github.com/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot "Adding repository custom instructions for GitHub Copilot - GitHub Docs"
[3]: https://code.visualstudio.com/docs/copilot/customization/prompt-files "Use prompt files in VS Code"
[4]: https://code.visualstudio.com/docs/copilot/customization/custom-agents "Custom agents in VS Code"
[5]: https://docs.github.com/en/copilot/reference/custom-agents-configuration "Custom agents configuration - GitHub Docs"
[6]: https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills "Adding agent skills for GitHub Copilot - GitHub Docs"
[7]: https://code.visualstudio.com/docs/copilot/customization/overview "Customize AI in Visual Studio Code"
