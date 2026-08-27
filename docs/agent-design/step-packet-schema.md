# Step Packet Schema (plan-doc weight class)

This is the deliverable `implementation-plan.md`'s Phase 2 promised and never
wrote. It answers Decision 2 in that doc's "Decisions to Make Before
Implementation" section: **the old planner/architect/executor pattern and
`.git/ai`'s YAML state machine stay reserved for large staged infra programs
(teardown/redeploy cycles, multi-week refactors). Normal-sized work — a new
stack, a feature, a fix spanning a few files — uses the lighter step shape
documented here, embedded directly in a plain `docs/<workspace>/plan.md`.**

## Why two weight classes, not one

`.git/ai/current-step.spec.yaml` is real and working, but it carries things a
new-stack-sized task doesn't need: branch/SHA tracking, `plan_state.path`,
`approvals_required`, a dedicated render script, a dedicated report directory.
Forcing that machinery onto "add an Immich stack" is exactly the kind of
scope-mismatch this repo's own CLAUDE.md warns against elsewhere (match
validation depth to actual risk, not maximum ceremony by default).

What's worth keeping from it is the one idea that actually matters for
handing work to a local model: **a step is only safe to execute unsupervised
if "done" is a literal, runnable check — not a judgment call.** That's the
`gates` shape below, carried over almost unchanged.

## The step block

Each step in a `plan.md` is a fenced YAML block, human-readable, git-diffable,
and fetchable by any agent via `get_document` — no separate render step
required, unlike the `.git/ai` machinery.

```yaml
id: immich-01-compose-service          # <workspace>-NN-slug, stable once written
title: Add Immich compose service definition
depends_on: []                         # ids of steps that must land first

change: >
  One to three sentences, imperative, naming the exact file(s) and the exact
  edit. Not "improve the compose file" -- "add an `immich-server` service
  block to terraform/lxc/stacks/immich-stack/docker-compose.yml.j2 exposing
  port 2283, matching the volume-mount pattern openwebui already uses in
  ai-services-stack for its data directory."

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run -- validation only in this step"

gates:
  - id: syntax-check
    cmd: "docker compose -f terraform/lxc/stacks/immich-stack/docker-compose.yml.j2 config"
    expect: "exit 0"
    critical: true
```

Field notes:

- **`id`** — prefix with the workspace name so ids stay globally unique
  across plans (`immich-01-...`, not `01-...`).
- **Give every step its own markdown heading directly above its fenced
  YAML block** (e.g. `### immich-01-compose-service`) -- not only the
  ones needing an operator go-ahead. `docs-rag-mcp` chunks a plan.md by
  heading, and `implement-step` fetches one step via `search_docs`
  (returning just that step's chunk) rather than the whole document.
  Steps left without their own heading get lumped into one oversized
  chunk with their un-headed neighbors, which `implement-step` then has
  to page through by hand -- found for real, not theoretically: exactly
  this sent the local model into a genuine 3.8M-token stall trying to
  locate one step inside a whole fetched plan.md
  (2026-08-27, `docs/agent-design/graylog-integration-test/`).
- **There is no `model_hint` field.** This is a one-model process: the
  frontier model plans, the local model executes, full stop. Every step
  block in a plan.md is unconditionally local-model work by construction
  -- the frontier model resolves all judgment before writing the step,
  never after. Anything that isn't actually executable by the local
  model (an operator running a command directly, a browser-only UI
  procedure, a human verification a script can't perform) is never
  written as a step block at all -- it's plain prose in the plan doc
  instead, outside the fenced YAML, so there's nothing for the local
  model to misinterpret as something to attempt.
- **`change`** — must name exact files and an exact edit. If you can't
  write this in three sentences without hedging, the step is still too big
  — split it.
- **`scope`** — reused verbatim from `current-step.spec.yaml`'s shape.
  This is what keeps a model from wandering into unrelated files or,
  worse, running a deploy when the step only asked for an edit.
- **`gates`** — reused verbatim from `current-step.spec.yaml`'s shape
  (`id`/`cmd`/`expect`/`critical`). A gate must be something a human or a
  script can run and get an unambiguous pass/fail from — never "looks
  right." `critical: false` gates may fail without blocking the step;
  `critical: true` gates must pass.
- **No `report.path`, `plan_state.path`, `branch`, or `refs`.** Those are
  `.git/ai`-specific bookkeeping for staged programs with their own
  approval-packet lifecycle (see `docs/workflow/branch-model.md` and
  `docs/agent-design/implementation-plan.md`'s Phase 6). A plan.md step
  doesn't need them; the plan.md itself and normal commits are the record.

## Two content strategies for `change` -- a real, already-validated lesson

`docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md` ran this
exact pattern for real with a different local-model tool-loop, but the
same "bounded local execution of a frontier-authored spec" idea, and
found a specific, repeatable failure mode worth designing around
directly:

- For content whose **schema is entirely repo-specific** (`stack.yaml`,
  `STACK_CONTRACT.md` facts, an Ansible playbook's task structure), a local
  model asked to "model this on an existing example" pattern-matches
  generic shape instead of transcribing the actual fields -- it invented a
  non-existent nested `network:` block, dropped required fields, etc. **The
  fix: give the step literal, exact content to transcribe, not a file to
  model on.** There's no competing public pattern for the model to fall
  back to, so copying it exactly is a correctness win, not a shortcut.
- For content with a **strong public-training-data pattern** (a Docker
  Compose file for a well-known image), literal transcription isn't always
  practical, but pure instructions aren't reliable either -- the model's
  prior about "what a docker-compose.yml for X looks like" can win out over
  what the step actually asked for. **The fix: explicit positive and
  negative constraints** -- exactly which image tag, which env vars are
  required, which optional-looking things are deliberately forbidden for
  this pass (see that doc's `compose_requirements`/`compose_forbidden`
  split for the concrete shape).

When writing a step's `change`, decide which of these two it is and write
accordingly -- don't default to prose instructions and hope.

## Reuse `scaffold-stack.sh` for new stacks specifically -- but not as a step block

Adding a brand new stack is common enough that it already has a dedicated,
validated tool: `terraform/lxc/scaffold-stack.sh <stack-name>`, driven by a
`stack-request.yaml` (see `terraform/lxc/stacks/stack-request.example.yaml`)
and gated by a validator between each of its five narrow, single-file
sub-agent steps (`terraform/lxc/README.md`'s "Scaffolding a new stack with a
local coding agent" section). For a new-stack plan, prefer this over
hand-written file-edit steps:

- **One real step block**: research the real facts (zone/IP, resources,
  what the compose file actually needs) and author `stack-request.yaml`,
  applying the literal-vs-constrained distinction above field by field.
- **Running `scaffold-stack.sh <stack-name>` itself is not a step block at
  all -- it's plain prose, an operator instruction sitting outside the
  fenced YAML.** Found for real, not theoretically: it internally depends
  on a separate tool the local model's execution loop doesn't have --
  writing it as a step the local model could pick up sent that loop
  looking for something outside its own environment. Before recommending
  *any* existing script as a step, check what it actually invokes
  underneath; don't assume a script is plain, self-contained shell work
  just because it looks like one from its name. And when something turns
  out not to be local-model work, just write the plain instruction as
  prose -- don't explain what it was almost written as a step instead.
  That explanation is the thing you're trying to keep out of the local
  model's context in the first place.

## When to escalate to `.git/ai` instead

Use the heavy machinery instead of this one when a task genuinely needs:
multi-week staged execution with resumable state across sessions, an
approval-packet trail for production mutation, or branch/SHA-pinned
reproducibility. A new stack, a bug fix, a refactor confined to a handful of
files is not that — use plan.md steps.

## How this is consumed

This is a one-model-plans, one-model-executes loop, not a mixed-tier
system:

- The frontier model writes the plan using
  `.github/prompts/plan-change.prompt.md` -- every step block it writes is
  already, unconditionally, local-model work.
- The local model runs one step at a time using
  `.github/prompts/implement-step.prompt.md`, which enforces: do only the
  named step, touch only `scope.allowed_paths`, run every gate, then
  write a **hand-back** -- a real, durable record of what happened (the
  edit made, each gate's actual result) into the workspace's `README.md`,
  not just a chat reply that disappears with the session -- and stop.
  Never chain into the next step on its own.
- The frontier model reads that hand-back before authoring or approving
  the next step -- especially anything touching real user data or
  shared/production config, no matter how mechanical the step looked on
  paper. The hand-back is what makes that review possible without
  re-deriving what happened from scratch.

See `docs/agent-design/implementation-plan.md` for how this fits the wider
agent architecture, and `docs/workflow/documentation-workspaces.md` for the
`docs/<workspace>/` layout this lives in.
