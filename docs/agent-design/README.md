# agent-design (planning workspace)

Status: **live, working methodology.** Answers "how do I turn a big,
open-ended question into work a local model can actually
execute" -- validated end-to-end on a real task, not just designed, and
separately validated against a battery of small, contained,
proxy-observed tests exercising the real failure modes (retry loops,
gate failures, dependency gating, no-chaining). One model plans
(frontier), one model executes (local) -- there is no third tier and no
per-step judgment call for the executor to make. See
`docs/media-stack-lab/` for the worked example.

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
   docs/media-stack-lab/plan.md, step media-lab-01-stack-request"). It
   fetches the plan itself via `get_document` -- committing to `docs/`
   triggers this repo's auto-reindex hook, so there's no copy-pasting
   content into chat. `.github/prompts/implement-step.prompt.md` is what
   governs its behavior: do exactly the named step, run its gates, write
   a hand-back into the workspace's `README.md`, stop. One invocation,
   one step -- it does not chain into the next one.

3. **Read the hand-back before the next step runs -- and be ready to
   write it yourself if it's missing.** The local model's `README.md`
   update is meant to be a real, durable record of what happened, but in
   practice it's unreliable on longer or more eventful steps (several
   tool calls, a self-correction along the way): the step itself lands
   correctly, gates genuinely pass, the chat reply describes it all
   accurately -- and the README simply never gets edited. Three
   different prompt-wording fixes for this were tried and each still
   missed it at least once. Don't treat a missing hand-back as blocking
   -- verify the step's actual real-world result yourself (read the
   file, re-run the gate, whatever's appropriate) and write the record
   in. This is now the expected way the loop actually runs, not a rare
   exception to watch for.

## The three files that make this work

| File | Role |
|---|---|
| [step-packet-schema.md](step-packet-schema.md) | The step shape itself (`id`/`change`/`scope`/`gates` -- no tiering field, every step block is unconditionally local-model work), why it's a lighter weight class than `.git/ai`'s YAML state machine, and the literal-vs-constrained content lesson from the Minecraft exemplar |
| [`.github/prompts/plan-change.prompt.md`](../../.github/prompts/plan-change.prompt.md) | The frontier-model side: research → ask the operator about genuine judgment calls → write bounded, gated steps (anything needing a human becomes plain prose, not a step block) → commit → read each hand-back before advancing |
| [`.github/prompts/implement-step.prompt.md`](../../.github/prompts/implement-step.prompt.md) | The local-model side: fetch one step, execute exactly what's written, run gates, write a hand-back into the workspace's `README.md`, stop |

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

## Worked examples

- `docs/media-stack-lab/` -- a real plan (replace legacy `media-stack`
  with Jellyfin+Immich, Authentik SSO, watch-history migration) taken
  through two full passes: the first described decisions rather than
  resolving them, leaving most steps unbounded; the second rewrote
  every step with literal content, leaving only two genuinely
  operator-only actions (running `scaffold-stack.sh`, a UI-only
  Jellyfin plugin install) as plain prose rather than step blocks. Read
  both the plan and its git history for the concrete before/after.
- `docs/agent-design/lxc-provision-test/` -- deploying a real LXC and
  configuring a service on it via Ansible, end to end. First pass found
  two real gaps (a missing pair of steps, an imprecise gate); a full
  teardown and fresh second pass then ran clean start to finish, no
  frontier intervention needed anywhere in execution. See
  `validation-methodology.md` for the general process this established
  for proving out a new capability class.
