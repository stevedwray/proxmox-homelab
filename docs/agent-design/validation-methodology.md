# Validating a new capability class

This is the process for proving out `plan-change`/`implement-step` on a
task class it hasn't been tried on yet -- not "does it work once," but
building real confidence the way `docs/lxc-provision-test/` did for
"provision an LXC and configure it via Ansible." Read that workspace's
git history for the concrete blow-by-blow this process is drawn from.

## The ladder: don't start with the real task

Test small, isolated tool capabilities before combining them into a
real multi-step task. `docs/agent-design/README.md`'s own history did
this: single-tool smoke tests (create a file, edit a file, run a
terminal command, search docs) before ever running a real multi-step
plan. Each one either passed cleanly or found something -- an unbounded
retry loop, capped; a hand-back never written, fixed -- before that
class of problem could compound inside a real task. Skipping straight
to the real task means a failure gives you no way to tell which of
several moving parts caused it.

## Observability: watch the actual exchange, not just the outcome

If the local model runs through an `ollama-reliability-proxy` (or
similar), tail its logs during every test:

```
ssh root@<proxy-host> docker logs -f ollama-reliability-proxy
```

Real exchange logging (model, the tools it called with what arguments,
its own reply) turns "it seemed to work" into "here is the exact tool
call sequence, and here is what it actually wrote." Several real bugs
this process has found (repeat-loops, wrong file paths, a gate silently
passing on a skip) were only visible by reading the actual sequence,
not by trusting the final chat summary. Independently verify the real
result too (read the file, check the actual infrastructure state) --
don't take the model's own report as ground truth, even when it sounds
confident and detailed.

## Pick a genuinely disposable target

For anything that creates real infrastructure, use the smallest,
cheapest, most obviously-throwaway instance of the task class: one
container, no persistent data, nothing else depending on it, a VMID/IP
picked from a range that's easy to confirm free (and confirmed free
for real, via a literal step, not assumed). `smoketest-stack` (a single
disposable nginx container) is the model to copy for infra-creation
tests specifically.

## Gate the first real mutation behind an explicit go-ahead

Every step before the task's first genuine infrastructure mutation
should be pure text/read-only -- zero risk. The step that actually
creates something real gets marked, in the plan's own prose, as
requiring the operator to say specifically to proceed with *that*
step, not just "the previous step's gate passed." This isn't
decoration: tested for real, the local model correctly held out for
that explicit phrase rather than treating a generic "run implement-step
against step X" as sufficient authorization on its own.

## When something goes wrong: diagnose which kind of gap it is

Two different things look similar from the outside (the local model
"got stuck" or "didn't do the right thing") but need completely
different fixes:

- **A plan gap** -- the step's `change` or `gates` don't actually
  reflect the real mechanism (a missing prerequisite step, a gate that
  can't distinguish success from a graceful no-op). This is frontier
  work: read the actual source of whatever's being run, find a real
  working example to verify against, fix the plan. No amount of
  rewording `implement-step.prompt.md` fixes a plan that's genuinely
  incomplete -- the local-provision-test found this directly:
  `provision.sh` exits 0 even when it silently skips a stack, so the
  original bare-exit-code gate would always pass regardless of whether
  anything real happened. The fix was a tighter gate, not a smarter
  executor.
- **An executor reliability gap** -- the plan is genuinely correct and
  bounded, but the local model still does the wrong thing (wanders
  investigating instead of running the literal command it was given,
  states something about repo state from memory instead of checking).
  This is `implement-step.prompt.md` wording work. Test the fix in a
  **fresh chat session** every time -- a persistent session can go on
  using the *old* copy of the prompt it read at the start, so a fix
  that looks like it "didn't work" may just never have been loaded.

**Know when to stop chasing wording and build in a compensating
check instead.** The hand-back-skip pattern (a step's real result is
correct, its chat reply is accurate, but the `README.md` edit itself
never lands) survived three different wording fixes across this
process before being accepted as a persistent characteristic rather
than a bug to fully eliminate. The compensating practice --
`plan-change.prompt.md` now says to treat a missing hand-back exactly
like a wrong one, verify the real result independently, and write it
in -- worked every single time it was tried. Two or three real attempts
at a wording fix is a reasonable bar before switching to "build the
review in" instead of "keep trying to prevent it."

## Confirm a fix with a full teardown and fresh retry

A fix isn't confirmed by reasoning about it -- it's confirmed by
tearing the real infrastructure down, resetting every generated file
and the workspace's step-status tracking to a genuinely clean slate,
and running the entire corrected plan again from step one. That's the
only way to know the plan (not just the specific step that previously
failed) actually holds together end to end. This process's own second
pass at `lxc-provision-test` is the concrete example: clean run,
top to bottom, no frontier intervention anywhere in execution --
real confirmation the two fixes from the first pass were sufficient,
not just plausible.

## Specific durable lessons from this exercise

- **Never let the local model anywhere near a tool that shells out to
  a different agent CLI** (this repo's concrete case:
  `scaffold-stack.sh` uses OpenCode internally). When that tool's own
  sub-agent fails silently, the frontier model authors the output
  directly instead -- find a real existing example of the same file
  type first (`terraform/lxc/stacks/harness-target/` in this case),
  and verify against its actual content rather than assumed shape;
  an initial guess at the environment-level `terragrunt.hcl`'s exact
  fields was wrong until checked against the real file.
- **Test every gate you write against a real sample of both the
  passing and failing case**, not just "looks plausible" -- this
  caught both the wrong initial guess at `terragrunt.hcl`'s content
  (a `diff`-based gate would have failed immediately) and confirmed
  the tightened `provision.sh` skip-detection gate against real
  `SKIP` and real success output before it ever reached the local
  model.
- **A command that reports success without doing the real work**
  (`provision.sh`'s graceful skip) is a category worth checking for
  specifically in any tool a plan wraps -- exit code alone is not
  proof of the intended effect.
