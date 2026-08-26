---
name: implement-step
description: Execute exactly one step from an existing plan.md, validate it, and stop
agent: Repo Tools
tools: ['edit', 'read', 'search', 'execute', 'docs-rag/*']
---

# implement-step

Use this to execute **one named step** from a plan doc already written by
`plan-change`. This is the prompt meant for the local model, working in
Repo Tools mode. It deliberately does not do any open-ended reasoning --
that already happened when the plan was written. Every step block you
are given is, by construction, meant for you to execute as-is -- the
frontier model that wrote the plan already resolved anything that
needed judgment or a human/operator action into either literal content
in `change`, or plain prose in the plan doc outside any step block.
Everything you need is in the step block itself (`change`, `scope`,
`gates`) -- you don't need to read anything else to understand what
those mean.

You will be told which plan and which step id to run, e.g.:
"Run implement-step against docs/<workspace>/plan.md, step <workspace>-01-<slug>."

## What to do, in order

1. **Fetch the plan.** Use `get_document` on the named `plan.md` (or
   `search_docs` if you don't have the exact path) and find the step block
   matching the given id. If two differently-worded searches don't find it,
   stop and say so -- don't keep retrying with further reworded queries.

2. **Check `depends_on`.** If any listed step isn't done yet (check the
   workspace's `README.md` status, or ask), stop and say so -- do not do
   the dependency yourself and do not skip ahead.

3. **If you believe this exact step already ran** (including in an
   earlier turn of this same conversation), don't act on that memory --
   verify it for real, right now, with an actual tool call (read the
   file, run the gate) before saying anything about current state.
   Memory of a previous turn is not a substitute for checking; the repo
   can change between turns for reasons you don't know about. If your
   fresh check confirms it's already done, say that -- but only after
   actually checking this turn, never before.

4. **Do exactly the `change` described** -- nothing broader. Use the
   exact path(s) `change` names, character for character -- don't
   substitute a different path even if it seems like a reasonable place
   for this kind of file. Touch only paths under `scope.allowed_paths`.
   Do not do anything listed under `scope.forbidden_actions`.

5. **Run every gate's `cmd` string exactly as written, byte for byte** --
   never adjust it to point at wherever you actually put something.
   The gate's job is to catch a mismatch between what `change` asked for
   and what you actually did; adapting the gate to fit your own result
   defeats that -- it turns a real deviation into a fake pass. If the
   literal gate command fails, that's real information: it means what
   you did doesn't match `change`, not that the gate needs fixing.
   Record the actual output, not a paraphrase.

6. **Make an actual edit to the workspace's `README.md` now** (same
   directory as the plan.md) -- use your file-edit tool on it, the same
   way you just edited files for the step itself. This is a real file
   change, not something to only describe in your chat reply. Under
   that file's `## Step status` (or similar) section, replace this
   step's line with a short, durable record of what happened:
   - which step you ran
   - the exact edit you made (file + diff summary)
   - each gate's command and its actual result (pass/fail)
   - if every `critical: true` gate passed: mark the step done
   - if any `critical: true` gate failed: say so plainly, leave the
     change in place, and do not retry with a different approach on
     your own
   This file edit is what the frontier model reads later to review the
   step -- it has to survive after this chat session ends, so writing
   it only in your chat reply does not count as having done this.

7. **Then report the same thing in chat, and stop.** One invocation of
   this prompt is one step. If you finish and there's an obvious next
   step, name it and wait -- don't chain into it.

## What not to do

- Don't improvise beyond what `change` says, even if you can see a
  "better" way -- that judgment call belongs in `plan-change`, not here.
  This includes file paths: use the exact one named, not a nearby one
  that seems reasonable.
- Don't skip a failing gate and report success anyway.
- Don't edit a gate's `cmd` to match wherever you actually put
  something. Run the literal string from the plan; if it fails, that
  failure is the signal that something drifted from `change`.
- Don't touch files outside `scope.allowed_paths`.
- Don't run anything under `scope.forbidden_actions`, even if a gate seems
  to need it -- stop and say the step's scope looks wrong instead.
- Don't keep reformulating the same search/lookup and retrying it hoping
  for a better result. Two tries at most, then stop and say what you
  couldn't find -- an open-ended retry loop is worse than reporting early.
- Don't consider the hand-back done because you described it in your
  chat reply. It requires an actual edit to the workspace's `README.md`
  -- the same kind of tool call you used for the step's own `change`.
- Don't state a file's contents, a gate's result, or anything else about
  current repo state based on memory of an earlier turn, even in this
  same conversation, without a fresh tool call this turn to back it up.
