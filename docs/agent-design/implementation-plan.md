# AI Agent System Implementation Plan

## Purpose

Design a practical, safe, and incremental AI agent system for this repository.
The system should support:

- coding and refactoring
- code review and security review
- planning and architecture work
- Terraform and Ansible execution
- Proxmox operations via API and SSH
- Linux host diagnostics and controlled remediation
- MikroTik diagnostics and reconciliation
- future TP-Link Omada diagnostics and reconciliation

This plan assumes GitHub Copilot customizations are the primary distribution
mechanism, with local IDE and CLI usage as the first-class operating mode.

For the companion validation strategy, see [testing-plan.md](testing-plan.md).

---

## Current State Review

The repository already has strong foundations for agentized work:

- `AGENTS.md` and `.github/copilot-instructions.md` contain meaningful operating
  policy, branch rules, scan gates, and credential handling.
- `docs/stack-lifecycle-refactor/` already models plan-driven execution, bounded
  roles, deterministic handoff artifacts, and validation scripts.
- `scripts/render-current-step.py`, `scripts/validate-current-step.py`,
  `scripts/update-plan-state.py`, and related validators are reusable building
  blocks for multi-step agent orchestration.
- `scripts/provision.sh`, `scripts/teardown-deploy-test.sh`, and
  `terraform/lxc/reconcile-edge.py` already encode dry-run-first and evidence
  capture patterns that agents should follow.
- There is existing code for Proxmox and MikroTik integration under
  `terraform/lxc/stacks/netbox-stack/integrations/`.

Important gaps:

- `.github/agents/` and `.github/instructions/` are currently empty in the
  working tree even though deleted historical versions exist in git history.
- There is no active `.github/prompts/` or `.github/skills/` structure yet.
- There is no current MCP server configuration for Proxmox, MikroTik, Linux
  SSH, or Omada.
- Omada support does not meaningfully exist in the repo today.
- Historical agent files were tightly coupled to the stack-lifecycle refactor
  and should not be restored verbatim as the general solution.

---

## What Current GitHub Copilot Supports

The current official model is:

1. Repository instructions for always-on policy.
2. Path-specific instruction files for conditional rules.
3. Prompt files for reusable one-shot workflows.
4. Custom agents for persistent roles with tool restrictions.
5. Skills for reusable, multi-file capabilities with scripts/resources.
6. MCP servers for external tools and data sources.
7. Hooks for automated checks during cloud-agent execution.

Design constraints from the current docs:

- Custom agents are Markdown agent profiles with YAML frontmatter and can define
  prompt, tools, and MCP access.
- VS Code supports handoffs and subagent-style role composition.
- GitHub.com cloud agent does not currently honor every IDE-only property; in
  particular, `handoffs` are not the primary portability target.
- Skills are the right place for task-specific operational logic that should not
  always sit in the main prompt.
- MCP is the right abstraction for external systems, but the configuration model
  differs slightly between GitHub.com cloud agent and VS Code.
- Hooks are useful for enforcing scans and validation, but only for GitHub cloud
  agent workflows.

Implication for this repo:

- Build the system so it works well in VS Code and Copilot CLI first.
- Keep GitHub.com cloud-agent support as a compatible subset, not the main
  orchestration surface.
- Do not make the design depend on GitHub.com-only behavior or VS Code-only
  behavior without an explicit fallback.

---

## Design Principles

1. Default to read-only discovery before mutation.
2. Separate planning, execution, review, and approval roles.
3. Reuse repository scripts instead of teaching agents to improvise shell
   sequences.
4. Keep credentials in `with-secrets`, SOPS, or repository/agent secret stores,
   never in prompts.
5. Prefer deterministic artifacts and validators over free-form handoff text.
6. Capture evidence and reports as part of the workflow, not as an afterthought.
7. Make destructive actions require an explicit approval gate.
8. Scope tools per agent by least privilege.
9. Support local operator-led sessions first; expand to autonomous cloud runs
   only after the local workflow is stable.

---

## Recommended Architecture

### Layer 1: Always-On Policy

Keep using:

- `AGENTS.md`
- `.github/copilot-instructions.md`

Refine them so they stay short and stable:

- repo purpose
- branch and promotion model
- `with-secrets` and `pve-test` target guardrails
- required validation commands
- do-not-do rules

### Layer 2: Path-Specific Instructions

Add:

```text
.github/instructions/
  terraform.instructions.md
  ansible.instructions.md
  shell-python.instructions.md
  docs.instructions.md
  networking.instructions.md
  validation.instructions.md
```

Suggested responsibilities:

- `terraform.instructions.md`
  - `applyTo: "terraform/**/*.tf,terraform/**/*.hcl,terraform/**/*.yaml"`
  - terragrunt/tofu validation expectations
  - stack metadata and generated-file rules
- `ansible.instructions.md`
  - `applyTo: "ansible/**/*.yml,terraform/lxc/ansible/**/*.yml"`
  - `-u root` reminder for inline inventories
  - check mode and idempotence expectations
- `shell-python.instructions.md`
  - `applyTo: "scripts/**/*.sh,scripts/**/*.py,terraform/**/*.py"`
  - safe subprocess handling, logging, CLI behavior
- `docs.instructions.md`
  - `applyTo: "docs/**/*.md,.github/**/*.md"`
  - documentation style, references, and evidence handling
- `networking.instructions.md`
  - `applyTo: "ansible/**/*mikrotik*.yml,terraform/lxc/stacks/netbox-stack/integrations/**/*.py"`
  - read-only-first networking rule set
  - require diff/verify steps before writes
- `validation.instructions.md`
  - `applyTo: "**"`
  - narrow reminder to run the smallest relevant validation and report exact
    commands and outcomes

### Layer 3: Prompt Files

Add:

```text
.github/prompts/
  plan-change.prompt.md
  implement-change.prompt.md
  validate-change.prompt.md
  review-change.prompt.md
  diagnose-runtime.prompt.md
  run-teardown-cycle.prompt.md
  reconcile-edge.prompt.md
```

Use prompt files for repeatable workflows, not personas.

Examples:

- `plan-change`: inspect docs/code/CI and produce a bounded implementation plan
- `validate-change`: determine and run the minimum safe repo validations
- `diagnose-runtime`: gather evidence from logs, health checks, and dry-run
  commands without mutating state
- `run-teardown-cycle`: wrap the existing teardown/redeploy workflow with report
  expectations and stop points

### Layer 4: Custom Agents

Add a small core set first:

```text
.github/agents/
  planner.agent.md
  architect.agent.md
  implementer.agent.md
  reviewer.agent.md
  security-reviewer.agent.md
  ops-diagnostics.agent.md
```

Then add domain agents:

```text
.github/agents/
  terraform.agent.md
  ansible.agent.md
  proxmox-operator.agent.md
  mikrotik-operator.agent.md
  linux-operator.agent.md
  omada-operator.agent.md
  docs-writer.agent.md
```

Role boundaries:

- `planner`
  - read/search only
  - owns task decomposition, validation plans, risk notes
- `architect`
  - read/search + doc edits
  - owns design changes, plan repairs, blocker triage
- `implementer`
  - edit + safe local validation
  - owns bounded code and doc changes
- `reviewer`
  - diff inspection only
  - finds regressions, missing tests, unclear assumptions
- `security-reviewer`
  - review-only
  - focuses on secrets, authn/authz, network exposure, supply chain
- `ops-diagnostics`
  - read-only commands and health checks
  - never applies infra changes
- `terraform`
  - limited to Terraform/Terragrunt planning and apply workflows
  - uses repo scripts and target guards
- `ansible`
  - limited to playbook validation, check mode, and bounded apply workflows
- `proxmox-operator`
  - API and SSH discovery first
  - mutation only through approved runbooks/scripts
- `mikrotik-operator`
  - REST discovery first
  - changes only through reviewed playbooks or narrowly scoped tools
- `linux-operator`
  - host/container diagnostics, service checks, log review, bounded fixes
- `omada-operator`
  - initially read-only until a reliable client/tool layer exists

### Layer 5: Skills

Use skills for operational capabilities that need instructions plus helper
scripts:

```text
.github/skills/
  terraform-plan-review/
  ansible-checkmode-validation/
  proxmox-discovery/
  mikrotik-discovery/
  mikrotik-reconcile/
  edge-reconcile/
  teardown-cycle/
  ci-failure-triage/
  docs-evidence-closeout/
  omada-discovery/
```

The first skill set should be read-only or dry-run-centric.

### Layer 6: MCP Servers

Introduce MCP only when the workflow is stable enough to deserve a dedicated
tool interface.

Recommended MCP domains:

- `proxmox`
  - nodes, containers, VMs, storage, networks, status
  - later: safe lifecycle actions behind approval
- `mikrotik`
  - interfaces, VLANs, bridges, addresses, firewall rules, routes
  - later: staged reconcile operations
- `linux-ssh`
  - systemd status, logs, process checks, file inspection, health commands
- `omada`
  - devices, ports, VLANs, client inventory, config diff
- `repo-ops`
  - wrappers around approved repo scripts with structured input/output

For VS Code/local use, prefer sandboxed local MCP servers where possible.
For GitHub.com cloud agent, use repository MCP config only after the local
server contract is proven.

### Layer 7: Hooks

Use `.github/hooks/` only after the agent set is stable.

Initial candidates:

- pre-edit or pre-commit style checks for formatting/linting
- post-task validation summaries
- security scan reminders for Terraform or Python/shell/YAML changes

Hooks should enforce narrow checks, not run full teardown cycles automatically.

---

## Orchestration Model

This repository should not use a single mega-agent.

Use this lifecycle:

1. Intake
   - operator or issue selects a prompt or agent
2. Planning
   - planner produces the bounded plan, files-in-scope, validations, and risks
3. Readiness
   - diagnostics agent confirms branch, target, credentials, and environment
4. Execution
   - implementer or domain operator performs the bounded work
5. Validation
   - validation prompt or domain agent runs the minimum safe checks
6. Review
   - reviewer and, when needed, security-reviewer assess the change
7. Closeout
   - docs/evidence update, commit guidance, and merge recommendation

### Reuse of Existing `.git/ai` Workflow

The repo already has a useful execution-state design in:

- `.git/ai/plan-state.yaml`
- `.git/ai/current-step.spec.yaml`
- `.git/ai/current-step.yaml`
- `.git/ai/blocker.yaml`

Recommendation:

- keep this model for long multi-step refactors, teardown programs, and staged
  rollout work
- do not force it onto every small coding task

In practice:

- small tasks: prompt file + one agent + normal validation
- medium tasks: planner -> implementer -> reviewer
- large operational programs: planner + `.git/ai` state + executor/operator
  packets + blocker handling

---

## External System Strategy

### Proxmox

Current assets:

- SSH-based scripts under `scripts/`
- Proxmox REST client code under
  `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py`

Plan:

1. Standardize discovery actions first.
2. Wrap frequent read-only tasks in a skill or MCP tool.
3. Route mutations through repo scripts or explicit Terraform/Ansible flows.
4. Require target guard verification before any apply/destroy action.

Safe initial toolset:

- list nodes
- list LXCs/VMs
- fetch container config/status
- inspect storage/network state
- verify container existence after apply/destroy

Later mutating actions:

- bounded start/stop/restart
- snapshot/info capture
- only after clear approval semantics exist

### MikroTik

Current assets:

- RouterOS REST client code
- multiple Ansible reconciliation playbooks

Plan:

1. Treat current Python and Ansible logic as the source of truth.
2. Create a read-only discovery skill before a mutating operator agent.
3. Require proposed diff plus verification plan before any write.
4. Prefer playbook-driven reconciliation over ad hoc API writes.

Safe initial toolset:

- fetch bridge/VLAN/address/firewall state
- compare current state to expected lab topology
- produce drift report

Later mutating actions:

- patch specific interfaces or addresses
- only when backed by reviewed playbooks and evidence capture

### TP-Link Omada

Current state:

- no meaningful implementation support in the repository today

Plan:

1. Add an Omada discovery skill first.
2. Build or adopt a small client wrapper with a very limited scope:
   - controller login
   - devices
   - ports
   - VLAN/profile inventory
3. Keep the first Omada agent read-only.
4. Only after drift reporting is trustworthy should you add controlled writes.

This should be a later phase than Proxmox and MikroTik.

### Linux Hosts and Containers

Plan:

1. Start with diagnostics and health checks.
2. Reuse Ansible where possible for remediation.
3. Limit shell-based mutation to bounded, reviewable commands.
4. Capture service checks and logs into evidence directories when the task is
   operational rather than purely coding.

Safe initial toolset:

- `systemctl` state
- log tailing
- file inspection
- disk/memory/network checks
- container health endpoints

---

## Security Model

### Core Rules

- Read-only by default.
- No broad shell access for every agent.
- No direct secret material in prompts, docs, or committed configuration.
- `./with-secrets` remains the standard wrapper for secret-bearing workflows.
- Mutation against infrastructure requires:
  - target verification
  - bounded scope
  - validation plan
  - evidence capture

### Required Approval Boundaries

Always require explicit operator approval for:

- `terragrunt apply`
- `terragrunt destroy`
- destructive Proxmox actions
- RouterOS or Omada config mutation
- changes outside `pve-test`
- any workflow that can affect production `pve`

### Least-Privilege Tooling

Recommended progression:

1. read-only prompts and agents
2. edit-only repo agents
3. repo command wrappers
4. sandboxed MCP tools
5. approved mutation tools for specific domains

Do not start by giving every agent unrestricted terminal access to network
devices.

---

## Recommended Deliverables

### Phase 0: Decide the Operating Surface

Goal: standardize where the system is expected to work first.

Deliverables:

- decision note in `docs/agent-design/`
- statement that VS Code/Copilot CLI is the primary surface
- statement that GitHub.com cloud agent is a compatible subset

### Phase 1: Restore the Copilot Customization Skeleton

Goal: create the file structure without turning on unsafe automation.

Deliverables:

- `.github/instructions/*.instructions.md`
- `.github/prompts/*.prompt.md`
- `.github/agents/` with the six core agents
- `docs/agent-design/agent-catalog.md`

Definition of done:

- agents are discoverable
- prompts run
- no mutation-only agents exist yet

### Phase 2: Normalize the Planning and Handoff Model

Goal: connect general project work to the existing bounded execution model.

Deliverables:

- `docs/agent-design/orchestration-model.md`
- `docs/agent-design/step-packet-schema.md`
- decision on when to use `.git/ai` state vs normal chat/prompt flow
- refresh of old planner/executor/architect concepts in repo-neutral language

Definition of done:

- large work can be packetized consistently
- small work is not burdened by heavyweight state files

### Phase 3: Build Read-Only Skills

Goal: make discovery reliable before mutation.

Deliverables:

- `.github/skills/proxmox-discovery/`
- `.github/skills/mikrotik-discovery/`
- `.github/skills/terraform-plan-review/`
- `.github/skills/ansible-checkmode-validation/`
- `.github/skills/ci-failure-triage/`

Definition of done:

- agents can answer operational questions from structured tooling
- no live infra mutation is required for common diagnostics

### Phase 4: Add Controlled Repo Execution Agents

Goal: enable bounded implementation and validation.

Deliverables:

- `implementer.agent.md`
- `terraform.agent.md`
- `ansible.agent.md`
- `ops-diagnostics.agent.md`
- prompt files for validate/review/diagnose workflows

Definition of done:

- agent can code and validate within the repo
- destructive infra changes still remain outside normal agent autonomy

### Phase 5: Introduce External MCP Servers

Goal: move from prompt knowledge to structured operational tools.

Deliverables:

- local MCP server for Proxmox discovery
- local MCP server for MikroTik discovery
- local MCP server for Linux diagnostics
- repo or workspace MCP configuration docs
- sandbox guidance for local MCP use

Definition of done:

- common discovery actions no longer depend on brittle shell parsing

### Phase 6: Add Safe Mutation Paths

Goal: support guarded live operations.

Deliverables:

- `proxmox-operator.agent.md`
- `mikrotik-operator.agent.md`
- `linux-operator.agent.md`
- mutation-capable skills or MCP tools with explicit guardrails
- `docs/agent-design/approval-gates.md`

Definition of done:

- all mutating actions have a diff/apply/verify/report pattern
- the operator can clearly see stop points

### Phase 7: Add Omada Support

Goal: close the network control-plane gap.

Deliverables:

- `.github/skills/omada-discovery/`
- `omada-operator.agent.md`
- small Omada client/tool layer
- drift-report workflow before write workflow

Definition of done:

- agents can inspect Omada state safely
- config mutation remains opt-in and bounded

### Phase 8: Cloud-Agent and Hook Hardening

Goal: make GitHub.com automation safer and more useful.

Deliverables:

- `.github/hooks/*.json`
- cloud-agent compatibility notes
- repo MCP config for GitHub cloud agent where appropriate
- optional Copilot Spaces guidance for architecture/runbook context

Definition of done:

- cloud runs enforce lightweight checks
- the team knows which workflows belong in local IDE vs GitHub.com

---

## Initial Agent Catalog

This is the recommended first version.

| Agent | Primary job | Tools | Writes? | Live infra? |
|---|---|---|---|---|
| `planner` | break work into bounded steps | read/search | docs only | no |
| `architect` | design, tradeoffs, blocker triage | read/search/edit | docs only | no |
| `implementer` | repo changes | read/search/edit/run limited commands | yes | no |
| `reviewer` | code review | read/search/diff | no | no |
| `security-reviewer` | security review | read/search/diff | no | no |
| `ops-diagnostics` | health checks and evidence gathering | read/run read-only commands | no | read-only |
| `terraform` | plans and targeted validation | repo commands | yes | plan first |
| `ansible` | syntax, check mode, targeted runs | repo commands | yes | controlled |
| `proxmox-operator` | Proxmox diagnostics and guarded actions | MCP/API/SSH wrappers | limited | yes |
| `mikrotik-operator` | RouterOS diagnostics and guarded actions | MCP/API/playbook wrappers | limited | yes |
| `linux-operator` | Linux service diagnostics/remediation | SSH/Ansible wrappers | limited | yes |
| `omada-operator` | Omada discovery first, later guarded changes | MCP/client wrappers | later | later |

---

## File Layout Target

```text
docs/agent-design/
  agent-design.md
  implementation-plan.md
  agent-catalog.md
  orchestration-model.md
  approval-gates.md
  step-packet-schema.md
  mcp-architecture.md
  rollout-checklist.md

.github/
  copilot-instructions.md
  instructions/
    terraform.instructions.md
    ansible.instructions.md
    shell-python.instructions.md
    docs.instructions.md
    networking.instructions.md
    validation.instructions.md
  prompts/
    plan-change.prompt.md
    implement-change.prompt.md
    validate-change.prompt.md
    review-change.prompt.md
    diagnose-runtime.prompt.md
  agents/
    planner.agent.md
    architect.agent.md
    implementer.agent.md
    reviewer.agent.md
    security-reviewer.agent.md
    ops-diagnostics.agent.md
    terraform.agent.md
    ansible.agent.md
    proxmox-operator.agent.md
    mikrotik-operator.agent.md
    linux-operator.agent.md
    omada-operator.agent.md
  skills/
    terraform-plan-review/
    ansible-checkmode-validation/
    proxmox-discovery/
    mikrotik-discovery/
    edge-reconcile/
    teardown-cycle/
    ci-failure-triage/
    omada-discovery/
  hooks/
    validation.json
```

---

## Recommended First Milestone

If you want the fastest path to usable value, implement only this first:

1. Create the core instruction files.
2. Create `planner`, `implementer`, `reviewer`, and `ops-diagnostics`.
3. Create prompt files for planning, validation, and runtime diagnosis.
4. Create read-only skills for Proxmox and MikroTik discovery.
5. Document when to use the existing `.git/ai` step-packet model.

That gives you:

- safer coding help
- better review discipline
- reusable operational diagnostics
- a real path to infra-aware agents

without yet trusting agents to mutate routers or hypervisors.

---

## Decisions to Make Before Implementation

1. Is VS Code/Copilot CLI the official first target surface?
2. Do you want the old planner/executor/architect pattern revived as a general
   repo workflow, or kept only for large staged programs?
3. Should live infrastructure mutation be allowed from agents in Phase 1-4, or
   delayed until MCP and approval gates are in place?
4. Do you want Omada in the first wave, or explicitly defer it until Proxmox and
   MikroTik are stable?
5. Do you want GitHub.com cloud agent to be a first-class surface, or only a
   later compatibility target?

My recommendation:

- yes to VS Code/Copilot CLI first
- keep `.git/ai` for larger staged programs only
- delay live network-device mutation until after read-only skills and approval
  gates exist
- defer Omada to a later phase
- treat GitHub.com cloud agent as secondary for now

---

## References

- GitHub Docs: About custom agents
  https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-custom-agents
- GitHub Docs: Custom agents configuration
  https://docs.github.com/en/copilot/reference/custom-agents-configuration
- GitHub Docs: Customize Copilot for your project
  https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-copilot-overview
- GitHub Docs: Adding agent skills for GitHub Copilot
  https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills
- GitHub Docs: Connect agents to external tools
  https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/extend-cloud-agent-with-mcp
- GitHub Docs: Customize agent workflows with hooks
  https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/use-hooks
- GitHub Docs: Using GitHub Copilot Spaces
  https://docs.github.com/en/copilot/how-tos/provide-context/use-copilot-spaces/use-copilot-spaces
- VS Code Docs: Use custom instructions
  https://code.visualstudio.com/docs/copilot/customization/custom-instructions
- VS Code Docs: Custom agents
  https://code.visualstudio.com/docs/copilot/customization/custom-agents
- VS Code Docs: Prompt files
  https://code.visualstudio.com/docs/copilot/customization/prompt-files
- VS Code Docs: MCP servers
  https://code.visualstudio.com/docs/copilot/customization/mcp-servers
