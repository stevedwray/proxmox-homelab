---
name: plan-change
description: Turn a big, open-ended question into a bounded step-by-step plan doc a local model can execute
agent: agent
tools: ['edit', 'read', 'search', 'execute']
---

# plan-change

Use this for a big, open-ended question -- "what would be involved in adding
X", a new stack, a cross-cutting refactor -- where answering well requires
reasoning across multiple stacks, conventions, and docs. This prompt is for a
strong/frontier model. Don't run this from Laguna or another small local
model: the whole point is that the open-ended reasoning happens once, here,
so later execution doesn't have to repeat it.

## What to do

1. **Research first.** Use `search_docs`/`get_document` (docs-rag-mcp) if
   available, or native search/read, to find the real, current conventions
   that apply: existing `STACK_CONTRACT.md` patterns, network zone
   placement, Traefik/Authentik/storage implications, anything this repo
   has already decided that the new work must follow. Don't invent
   conventions the repo doesn't already have.

2. **Create the workspace**, following
   `docs/workflow/documentation-workspaces.md`:
   ```
   docs/<workspace>/
     README.md      # durable entrypoint: what this is, current status
     plan.md         # the actual step-by-step plan
     artifacts/      # gitignored scratch -- not created unless needed
   ```

3. **Write `plan.md`** as an ordered list of step blocks following
   `docs/agent-design/step-packet-schema.md` exactly. For each step:
   - Name exact file(s) and an exact edit in `change` -- three sentences,
     no hedging. If you can't, the step is still too big: split it.
   - For repo-schema-specific content (a `stack.yaml`, a `STACK_CONTRACT.md`,
     an Ansible playbook's structure), write the **literal exact content**
     into `change`, not "model this on file X" -- see the schema doc's
     "Two content strategies" section for why the latter reliably fails.
     For content with a strong public-training-data shape (a Compose file
     for a well-known image), write explicit positive **and** negative
     constraints instead of literal content or bare instructions.
   - If the task is **adding a new stack**, don't hand-write file-edit
     steps for the five boilerplate files at all -- there's already a
     validated tool for that. Write one `frontier` step that authors
     `stack-request.yaml` (applying the literal-vs-constrained rule per
     field) and one `local` step that runs
     `terraform/lxc/scaffold-stack.sh <stack-name>`.
   - Set `model_hint: local` if the step is genuinely bounded enough for
     Laguna (or another small local model) to execute unsupervised --
     single-file-or-few-file, mechanical, no open design judgment left to
     make. Set `model_hint: frontier` if the step still requires cross-file
     reasoning, an architectural call, or anything this plan doc can't
     fully pin down.
   - Every step needs at least one `critical: true` gate that is a literal,
     runnable command with an expected result -- never "looks right."
   - Set `depends_on` honestly; don't let steps silently assume an earlier
     one landed.

4. **Write `README.md`** with a short status line (what this is, whether
   any steps are done yet) -- this is what a human or another session reads
   first, matching every other `docs/<workspace>/README.md` in this repo.

5. **Commit it.** `docs/**/*.md` changes trigger this repo's post-commit
   auto-reindex hook, so once committed, docs-rag-mcp picks it up and any
   agent with that MCP tool (including Laguna in Repo Tools mode) can
   `search_docs`/`get_document` it directly -- no pasting content into
   chat required.

## What not to do

- Don't write vague steps ("improve X", "wire up Y properly") -- if a step
  needs judgment to interpret, it's not bounded enough yet.
- Don't reach for `.git/ai`'s heavier YAML state machine for normal-sized
  work -- see `step-packet-schema.md`'s "When to escalate" section. That's
  for large staged infra programs, not this.
- Don't mark a step `model_hint: local` just to make the plan look more
  automatable. Be honest about which steps still need real judgment.
