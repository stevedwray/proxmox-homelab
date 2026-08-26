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
strong/frontier model. Don't run this from the local model this plan is meant
for (whichever one -- there is no assumption it's any specific named model):
the whole point is that the open-ended reasoning happens once, here, so later
execution doesn't have to repeat it.

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
   `docs/agent-design/step-packet-schema.md` exactly. This is a
   one-model-plans, one-model-executes process -- there is no tiering
   field on a step. Every step block you write is, by construction,
   unconditionally meant for the local model to execute as-is. That
   means the judgment has to be finished *here*, not partially done and
   handed off:
   - Name exact file(s) and an exact edit in `change` -- three sentences,
     no hedging. If you can't, the step is still too big: split it.
   - For repo-schema-specific content (a `stack.yaml`, a `STACK_CONTRACT.md`,
     an Ansible playbook's structure), write the **literal exact content**
     into `change`, not "model this on file X" -- see the schema doc's
     "Two content strategies" section for why the latter reliably fails.
     For content with a strong public-training-data shape (a Compose file
     for a well-known image), write explicit positive **and** negative
     constraints instead of literal content or bare instructions.
   - If the task is **adding a new stack**, `terraform/lxc/scaffold-stack.sh`
     is a validated tool for the five boilerplate files -- but check what
     it actually invokes underneath before writing a step around it (this
     one turned out to depend on something the local model's execution
     loop doesn't have, found for real, not theoretically). Write the
     real step block that authors `stack-request.yaml` (applying the
     literal-vs-constrained rule per field) as usual, but running
     `scaffold-stack.sh` itself is never a step block at all -- write it
     as plain prose in the plan doc, an instruction for the operator to
     run directly, same weight class as `terragrunt apply`/`provision.sh`.
     Don't explain in that prose why it isn't a step; that explanation is
     exactly the kind of thing to keep out of the local model's context,
     not put in the one document it fetches to execute every other step
     in the plan.
   - **If a step still requires judgment, don't write it as a step block
     and hope** -- do that judgment now, yourself, and write the literal
     result into `change`. A step only belongs outside the step-block
     format entirely -- written as plain prose instead -- if, after
     you've tried to resolve it: (a) it needs a value only knowable at
     execution time (and even then, prefer "run this exact command to
     fetch it, then substitute" over leaving the whole thing open), (b)
     you've confirmed -- by checking, not assuming -- there's no
     scriptable/config-file path at all (a UI-only plugin, say), or (c)
     it's a first mutation of shared/production infrastructure where a
     human's own judgment in the moment matters more than a pre-written
     spec. Everything else gets written as a real step block once you've
     done the work of writing the literal content. A finished plan with
     several judgment calls still unresolved usually means the planning
     wasn't finished, not that the work was inherently unbounded.
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
     one landed -- including a prerequisite that was written as prose
     rather than a step block. It's still a real dependency other steps
     can be gated on.

5. **Write `README.md`** with a short status line (what this is, whether
   any steps are done yet) -- this is what a human or another session reads
   first, matching every other `docs/<workspace>/README.md` in this repo.
   This file is also where the local model writes its hand-back after
   each step it runs (see `implement-step.prompt.md`) -- read it before
   authoring or approving the next step, don't just trust that a chat
   reply from an earlier session described what actually happened.

6. **Commit it.** `docs/**/*.md` changes trigger this repo's post-commit
   auto-reindex hook, so once committed, docs-rag-mcp picks it up and any
   agent with that MCP tool (including the local model in Repo Tools
   mode) can `search_docs`/`get_document` it directly -- no pasting
   content into chat required.

7. **After the local model runs a step, read its hand-back before doing
   anything else.** That's the `README.md` update `implement-step`
   writes -- the actual edit made and the actual gate results, not a
   summary of what should have happened. If a critical gate failed,
   don't author or approve the next step until that's resolved. If the
   hand-back looks wrong or incomplete for what the step asked for, say
   so rather than assuming the local model's own report was accurate.

## What not to do

- Don't write vague steps ("improve X", "wire up Y properly") -- if a step
  needs judgment to interpret, it's not bounded enough yet.
- Don't reach for `.git/ai`'s heavier YAML state machine for normal-sized
  work -- see `step-packet-schema.md`'s "When to escalate" section. That's
  for large staged infra programs, not this.
- Don't write something as a step block just to make the plan look more
  automatable when it's actually an operator/manual action. Be honest
  about which things still need a human, and write those as plain prose
  instead, outside any fenced YAML.
- Don't hand the local model a step whose underlying script invokes a
  different agent tool as a subprocess -- found for real, not
  theoretically. Before recommending any existing script as a step,
  check what it actually shells out to; if it depends on something
  outside the executing loop's own environment, write it as a plain
  prose instruction for the operator instead, not a step block. Don't
  name or explain the other tool in that instruction -- that's exactly
  the kind of detail that sends a model looking for it, and the step
  content is the one thing the local model actually reads.
