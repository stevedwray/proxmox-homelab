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

2. **Surface genuine judgment calls to the operator -- don't default them
   silently.** Architecture shape (one stack or several), destructive vs.
   additive framing, zone/naming choices, which of several real options
   to use (a plugin, a library, a migration approach) -- these are the
   operator's calls, not yours to assume. Ask concretely, with the real
   tradeoffs you found in research, before finalizing the plan around a
   guess. This is different from step 4's `<<NEEDS OPERATOR INPUT>>`
   placeholders (a value with no safe default at all, like a storage
   size) -- this is about not silently picking an approach when the
   operator would reasonably want to weigh in.

3. **Create the workspace**, following
   `docs/workflow/documentation-workspaces.md`:
   ```
   docs/<workspace>/
     README.md      # durable entrypoint: what this is, current status
     plan.md         # the actual step-by-step plan
     artifacts/      # gitignored scratch -- not created unless needed
   ```

4. **Write `plan.md`** as an ordered list of step blocks following
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
   - **`frontier` is a todo, not a destination.** If a step still requires
     judgment, don't just tag it `frontier` and move on -- do that
     judgment now, yourself, and write the literal result into `change`.
     A step only stays genuinely `frontier`/manual if, after you've tried
     to resolve it: (a) it needs a value only knowable at execution time
     (and even then, prefer "run this exact command to fetch it, then
     substitute" over leaving the whole step open), (b) you've confirmed
     -- by checking, not assuming -- there's no scriptable/config-file
     path at all (a UI-only plugin, say), or (c) it's a first mutation of
     shared/production infrastructure where a human's own judgment in
     the moment matters more than a pre-written spec. Everything else
     graduates to `model_hint: local` once you've done the work of
     writing the literal content. A finished plan with most steps still
     `frontier` usually means the planning wasn't finished, not that the
     work was inherently unbounded.
   - **Verify a mechanism's real behavior by reading its actual
     implementation before calling it generic or reusable in a plan** --
     not by pattern-matching one similar-looking example. A shared
     script that looks config-driven from one example file can turn out
     to be a hardcoded per-case lookup underneath; only reading the code
     itself catches that. Getting this wrong sends a plan (and whoever
     executes it) down a path that looks fine and does nothing.
   - **Test any gate command you're not certain of**, don't just judge it
     plausible -- run it against a real matching and non-matching example
     before leaving it in the plan. A gate that looks reasonable but
     silently errors (a regex feature the local grep doesn't support, for
     instance) is worse than no gate at all, because it looks like
     coverage that isn't there.
   - Every step needs at least one `critical: true` gate that is a literal,
     runnable command with an expected result -- never "looks right."
   - Set `depends_on` honestly; don't let steps silently assume an earlier
     one landed.

5. **Write `README.md`** with a short status line (what this is, whether
   any steps are done yet) -- this is what a human or another session reads
   first, matching every other `docs/<workspace>/README.md` in this repo.

6. **Commit it.** `docs/**/*.md` changes trigger this repo's post-commit
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
