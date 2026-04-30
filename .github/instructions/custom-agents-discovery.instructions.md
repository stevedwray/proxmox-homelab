---
applyTo: '**'
---

# Custom Agent Discovery (HOMELAB GenAI SDLC)

This workspace uses HOMELAB GenAI SDLC custom agents.

When a user asks for an agent, mode, or persona, discover definitions from:

- `.github/agents/*.agent.md` (primary source — pre-built GitHub Copilot format)
- `_bmad/bmm/agents/*.md` (source of truth — full agent definitions)
- `_bmad/bmm/config.yaml` (workspace config — user name, output folder, language)

Treat these files as the authoritative source of agent IDs, role definitions, commands, and activation behaviour.

Available agents in this repository:

| Agent ID | Persona | Role |
|---|---|---|
| `homelab-master` | HOMELAB Master | Workflow orchestration, task execution, knowledge custodian |
| `homelab-analyst` | Aroha | Business analyst, market research, requirements elicitation |
| `homelab-architect` | Rawiri | Architecture design, DoaP creation, tech stack validation |
| `homelab-dev` | James | Story execution, TDD, code implementation, Jira ticket creation |
| `homelab-pm` | John | PRD creation, stakeholder alignment, requirements discovery |
| `homelab-qa` | Quinn | Test automation, API testing, E2E testing, coverage analysis |
| `homelab-quick-flow-solo-dev` | Barry | Rapid spec creation, lean implementation |
| `homelab-security-assistant` | Manaia | CPS 234 design review, security checklists |
| `homelab-sm` | Bob | Sprint planning, agile ceremonies, Jira tickets, Confluence |
| `homelab-tech-writer` | Paige | Documentation, Mermaid diagrams, standards compliance |
| `homelab-ux-designer` | Sally | User research, interaction design, UI patterns |
