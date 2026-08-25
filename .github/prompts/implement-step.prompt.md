---
name: implement-step
description: Execute exactly one step from an existing plan.md, validate it, and stop
agent: Repo Tools
tools: ['edit', 'read', 'search', 'execute', 'docs-rag/*']
---

# implement-step

Use this to execute **one named step** from a plan doc already written by
`plan-change` (see `docs/agent-design/step-packet-schema.md` for the step
shape). This is the prompt meant for the local model, working in
Repo Tools mode. It deliberately does not do any open-ended reasoning --
that already happened when the plan was written.

You will be told which plan and which step id to run, e.g.:
"Run implement-step against docs/immich-stack/plan.md, step immich-01-compose-service."

## What to do, in order

1. **Fetch the plan.** Use `get_document` on the named `plan.md` (or
   `search_docs` if you don't have the exact path) and find the step block
   matching the given id.

2. **Check `depends_on`.** If any listed step isn't done yet (check the
   workspace's `README.md` status, or ask), stop and say so -- do not do
   the dependency yourself and do not skip ahead.

3. **Check `model_hint`.** If it's `manual`, stop immediately and say
   this step is for the operator to run themselves -- do not attempt the
   `change` at all, even if it looks simple. If it's `frontier`, stop
   and say this step needs a stronger model than you -- don't attempt it
   either.

4. **Do exactly the `change` described** -- nothing broader. Touch only
   paths under `scope.allowed_paths`. Do not do anything listed under
   `scope.forbidden_actions`.

5. **Run every gate** listed for the step, in order, exactly as written.
   Record the actual output, not a paraphrase.

6. **Report, then stop:**
   - which step you ran
   - the exact edit you made (file + diff summary)
   - each gate's command and its actual result (pass/fail)
   - if every `critical: true` gate passed: say the step is done
   - if any `critical: true` gate failed: say so plainly, leave the change
     in place for a human to look at, and do not retry with a different
     approach on your own

7. **Do not continue to the next step.** One invocation of this prompt is
   one step. If you finish and there's an obvious next step, name it and
   wait -- don't chain into it.

## What not to do

- Don't improvise beyond what `change` says, even if you can see a
  "better" way -- that judgment call belongs in `plan-change`, not here.
- Don't skip a failing gate and report success anyway.
- Don't touch files outside `scope.allowed_paths`.
- Don't run anything under `scope.forbidden_actions`, even if a gate seems
  to need it -- stop and say the step's scope looks wrong instead.
