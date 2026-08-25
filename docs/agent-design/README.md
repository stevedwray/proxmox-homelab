# agent-design (planning workspace)

Status: **live, working methodology.** Answers "how do I turn a big,
open-ended question into work a local model can actually
execute" -- validated end-to-end on a real task, not just designed. See
`docs/media-stack-v2/` for the worked example: 8 real steps, 7 of them
literal enough to hand to a local model unsupervised.

## How to use this, starting from nothing

**You have a big question** -- "what would it take to add X", a new
stack, a cross-cutting change.

1. **Ask a strong/frontier model** (this session, if you're in Claude
   Code -- just describe the task; or in VS Code Copilot, switch to a
   frontier model and run `/plan-change`). Point it at
   `.github/prompts/plan-change.prompt.md` if it doesn't already know
   the process -- that file *is* the instructions: research this repo's
   real conventions, surface genuine judgment calls to you rather than
   default them silently, then write `docs/<workspace>/plan.md` as a
   list of bounded steps following `step-packet-schema.md`'s shape,
   converting every step's judgment into literal file content or exact
   commands before calling it done -- not leaving it as "figure this out
   at execution time."

2. **Once the plan is committed**, switch to your local model (VS Code Copilot,
   `Repo Tools` agent mode) and run `/implement-step`, naming the plan
   and the step id (e.g. "run implement-step against
   docs/media-stack-v2/plan.md, step media-v2-02-scaffold"). It fetches
   the plan itself via `get_document` -- committing to `docs/` triggers
   this repo's auto-reindex hook, so there's no copy-pasting content
   into chat. `.github/prompts/implement-step.prompt.md` is what governs
   its behavior: do exactly the named step, run its gates, report, stop.
   One invocation, one step -- it does not chain into the next one.

3. **Review each step's result before the next one runs.** Especially
   anything touching real user data or shared/production config, no
   matter how mechanical the step looked on paper.

## The three files that make this work

| File | Role |
|---|---|
| [step-packet-schema.md](step-packet-schema.md) | The step shape itself (`id`/`model_hint`/`change`/`scope`/`gates`), why it's a lighter weight class than `.git/ai`'s YAML state machine, and the literal-vs-constrained content lesson from the Minecraft exemplar |
| [`.github/prompts/plan-change.prompt.md`](../../.github/prompts/plan-change.prompt.md) | The frontier-model side: research → ask the operator about genuine judgment calls → write bounded, gated steps → commit |
| [`.github/prompts/implement-step.prompt.md`](../../.github/prompts/implement-step.prompt.md) | The local-model side: fetch one step, execute exactly what's written, run gates, report, stop |

## Why this exists

`implementation-plan.md` (this workspace's older, broader design doc)
sketched a full agent architecture -- planner/architect/implementer/
reviewer personas, MCP servers, hooks -- most of which was never built.
This narrower slice is the part that actually got finished and proven:
not a new persona system, but a repeatable process for splitting
judgment (frontier, done once) from execution (local, done repeatedly,
safely, because the judgment is already resolved into literal content).
See `implementation-plan.md`'s Phase 2 for how this fits the wider plan,
and `docs/coding-stack/` for the original problem this was built to
solve -- getting a local model (via VS Code Copilot) to be
genuinely useful against this repo, not just technically wired up.

## Worked example

`docs/media-stack-v2/` -- a real plan (replace legacy `media-stack` with
Jellyfin+Immich, Authentik SSO, watch-history migration) taken through
two full passes: the first had 7 of 8 steps still requiring a frontier
model because it described decisions rather than resolving them; the
second rewrote every step with literal content, dropping that to 1 of 8
(and that one only because the mechanism it depends on -- a Jellyfin
plugin -- is genuinely UI-only, confirmed by checking, not assumed).
Read both the plan and its git history for the concrete before/after.
