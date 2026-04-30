---
applyTo: '**'
---

# Custom Agent Behaviour (HOMELAB GenAI SDLC)

When handling agent and skill requests:

1. If the user asks for an agent/persona without naming one, list available agents from the discovery instructions and ask which to use.
2. If the user names an agent directly, load that agent's definition from `.github/agents/` first.
3. If no matching agent file exists in `.github/agents/`, fall back to `_bmad/bmm/agents/`.
4. If the selected agent references tasks or data files, resolve them from `_bmad/bmm/tasks/` and `_bmad/bmm/data/`.
5. Load `_bmad/bmm/config.yaml` before executing any agent workflow to resolve `{output_folder}` and `{user_name}`.
6. Do not invent agents, commands, or dependencies not present in repository files.

---

## Base Copilot Skill Routing (no persona required)

The following skills can be invoked directly without activating a specific agent persona.

### Jira Ticket Creation — `jira-tickets-cli`

Skill definition: `.github/skills/jira-tickets-cli/SKILL.md`

- When a user asks to create Jira tickets from decomposed stories:
  1. Check that `{output_folder}/decomposed-stories.md` exists.
  2. Run a dry run first and show output: `node .genai/tools/cli.js jira:tickets --dry-run --project-key <KEY>`
  3. Confirm with the user before proceeding to live run.
  4. Ask the user which auth mode to use: `pat` (Atlassian Cloud — email + API token) or `pat-bearer` (Jira Data Center/Server — Bearer token).
  5. Live run: `node .genai/tools/cli.js jira:tickets --integration cli --auth-mode <MODE> --secure-auth --no-dry-run --project-key <KEY>`
- Prompt for any missing details: project key, auth mode, auth credentials.
- Prefer `node .genai/tools/cli.js` over `npm run` script variants unless the user asks otherwise.

### Confluence Publish — `confluence-pages-cli`

Skill definition: `.github/skills/confluence-pages-cli/SKILL.md`

- When a user asks to publish a markdown file to Confluence:
  1. Ask whether they have the parent page ID, or want to search by title / ServiceNow ID.
  2. Run dry run first: `node .genai/tools/cli.js confluence:publish --dry-run --input <path>`
  3. Confirm before live publish.
  4. Preferred live command: `node .genai/tools/cli.js confluence:publish --no-dry-run`
- Ask the user which auth mode to use: `pat` (email + API token) or `basic` (email + password, for Confluence Server/Data Center).
- Prompt for any missing details: input markdown, parent resolution method, space key, auth mode.
- For minimal interactive runs use: `node .genai/tools/cli.js confluence:publish --no-dry-run` (prompts for missing inputs).

### Confluence Pull — `confluence-pages-pull-cli`

Skill definition: `.github/skills/confluence-pages-pull-cli/SKILL.md`

- When a user asks to pull or export a Confluence page to local markdown:
  1. Ask whether they have the page link/ID, a ServiceNow ID, or project keywords.
  2. Ask the user which auth mode to use: `pat` (email + API token) or `basic` (email + password, for Confluence Server/Data Center).
  3. Run: `node .genai/tools/cli.js confluence:pull` (interactive) or with flags pre-filled.
  4. Present each candidate (title, ID, preview) and ask for confirmation before export.
- Preferred interactive command: `node .genai/tools/cli.js confluence:pull`

---

## Scope Rules

- Keep work inside this repository unless user explicitly asks otherwise.
- Follow repository conventions in existing agent and configuration files.
- Do not commit secrets; instruct users to use environment variables or `--secure-auth` prompts.
