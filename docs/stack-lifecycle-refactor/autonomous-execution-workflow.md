# Plan-Driven Autonomous Execution Workflow

## Goal

Replace the current chat-driven architect/executor handoff loop with a simpler
workflow that:

- front-loads planning
- treats the plan as the durable source of truth
- lets execution agents advance through planned steps with minimal operator input
- escalates only for real technical blockers, approvals, or contradictions

The operator should not need to route every session manually.

---

## Diagnosis

The current workflow is failing for structural reasons:

- too many machine-readable handoff artifacts
- bidirectional handoff state (`to-executor` and `to-architect`)
- too much free-form file generation by agents
- too much session-to-session state reconstruction
- too many opportunities for stale content to survive into the next run

The problem is not that role separation is inherently wrong.
The problem is that the protocol between roles is too complicated.

---

## Design Principles

1. The plan is the primary source of truth.
2. Execution steps are derived from the plan, not improvised from prior chat.
3. Reports are append-only evidence of what happened.
4. The operator is involved only for exceptions.
5. Outbound machine contracts should be deterministic and validated.
6. Inbound review should prefer reports over a second machine handoff file.

---

## Recommended Roles

### 1. Planner

Used at the start of a program or whenever the plan itself must change.

Responsibilities:

- produce the staged execution plan
- define step boundaries
- define exit criteria
- define escalation rules
- classify which steps are:
  - autonomous
  - approval-gated
  - escalation-required on failure

### 2. Executor

Used for the actual work.

Responsibilities:

- load the current step packet
- perform the bounded step
- validate the step
- write the step report
- update step status
- either advance to the next step or emit a blocker

### 3. Architect

Optional and narrower than today.

Recommended use:

- only for plan changes, decomposition changes, or blocker triage
- not for every normal successful executor step

In the simplified model, architect is no longer the mandatory destination after
every executor run.

---

## Artifact Model

### Durable Program State

Use a small set of stable files:

#### `docs/stack-lifecycle-refactor/execution-plan.md`

Human-readable master plan:

- program goal
- stages
- step descriptions
- validation model
- escalation points

#### `.git/ai/plan-state.yaml`

Machine-readable current program state:

- current stage
- current step id
- step statuses
- blocked / ready / complete
- last successful report path

This is the only long-lived machine state file.

### Step Artifacts

#### `.git/ai/current-step.spec.yaml`

Agent-authored source spec for the next executor run.

#### `.git/ai/current-step.yaml`

Rendered, validated machine contract for executor.

#### `.git/ai/reports/<step-id>.md`

Executor report for the step.

#### `.git/ai/blocker.yaml`

Only created when execution cannot continue autonomously.

This replaces the current `handoff-to-architect.yaml` pattern.

---

## State Machine

Each step has one of these statuses:

- `pending`
- `ready`
- `in_progress`
- `blocked`
- `complete`
- `skipped`

Allowed transitions:

- `pending -> ready`
- `ready -> in_progress`
- `in_progress -> complete`
- `in_progress -> blocked`
- `blocked -> ready`
- `ready -> skipped`

The executor should never invent new stages or statuses.

---

## Core Workflow

### Phase A: Initial Planning

1. Planner reads the refactor docs.
2. Planner writes:
   - `execution-plan.md`
   - `plan-state.yaml`
3. The first executable step is marked `ready`.

### Phase B: Step Preparation

1. A preparation agent or script reads `plan-state.yaml`.
2. It selects the single next `ready` step.
3. It writes:
   - `.git/ai/current-step.spec.yaml`
4. It renders and validates:
   - `.git/ai/current-step.yaml`

### Phase C: Execution

1. Executor loads `.git/ai/current-step.yaml`.
2. Executor performs the step.
3. Executor writes:
   - report file
   - updated `plan-state.yaml`
4. If the step succeeded:
   - mark current step `complete`
   - mark the next eligible step `ready`
5. If the step failed:
   - mark current step `blocked`
   - write `.git/ai/blocker.yaml`

### Phase D: Exception Handling

Only when blocked:

1. Architect or planner reviews:
   - `blocker.yaml`
   - the step report
   - current docs/state
2. They either:
   - resolve the blocker and mark the step `ready`, or
   - revise the plan

The operator is only needed if:

- approval is missing
- the plan is ambiguous
- the technical blocker requires a policy decision

---

## What To Remove

The redesigned workflow should remove:

- `.git/ai/handoff-to-architect.yaml`
- architect review after every successful executor session
- free-form “what next?” routing by executor
- repeated reconstruction of truth from multiple handoff files

Executor should report against the known current step, not invent a return
contract back to architect after every run.

---

## Step Packet Schema

The executor packet should be small and stable.

Recommended top-level fields:

```yaml
step:
  id: "slr-04-closeout-01"
  stage: "4"
  type: "closeout"     # bootstrap | main_work | closeout | promote | validate
  title: "Close out Stage 4 bounded contract changes"
  branch: "task/slr-04-exemplar-scaffolding"

goal:
  summary: "Commit and push the bounded Stage 4 changes."

scope:
  allowed_paths: []
  forbidden_actions: []

refs:
  base_branch: "refactor/stack-lifecycle"
  baseline_sha: ""
  starting_sha: ""

env:
  target_guard_cmd: "git rev-parse --abbrev-ref HEAD"
  target_guard_expect: "task/slr-04-exemplar-scaffolding"
  approvals_required: false

gates:
  - id: ""
    cmd: ""
    expect: ""
    critical: true

report:
  path: ".git/ai/reports/slr-04-closeout-01.md"

plan_state:
  path: ".git/ai/plan-state.yaml"
```

This is intentionally smaller than the current handoff structure.

---

## Blocker Contract

When autonomous execution cannot continue:

```yaml
step_id: "slr-04-closeout-01"
status: "blocked"
blocker_type: "technical"   # technical | approval | ambiguity | contradiction
summary: ""
details: ""
report_path: ".git/ai/reports/slr-04-closeout-01.md"
requires:
  - "planner review"
```

That is enough to restart the reasoning loop without requiring a second full
handoff contract.

---

## Validation Strategy

Validation should happen in two places:

### 1. Packet Validation

Before executor runs:

- validate `current-step.yaml`
- reject malformed or incomplete step packets

### 2. State Validation

After executor runs:

- validate `plan-state.yaml`
- confirm exactly one current step moved state
- confirm the report path exists

This means:

- packet validator replaces most current handoff policing
- state validator replaces most current “did the flow drift?” policing

---

## Operator Experience

### Normal Case

The operator should only:

1. approve the overall plan
2. launch the next executor run
3. review blockers only when one exists

### Exceptional Case

The operator is asked only for:

- destructive approval
- policy choice
- plan correction
- unexpected technical blocker

This is the intended low-touch mode.

---

## Suggested Migration

### Option A: Clean Break

Recommended if the current workflow is not trusted.

1. Reset workflow instructions to a simpler baseline.
2. Retire the current handoff-to-architect model.
3. Introduce:
   - `execution-plan.md`
   - `plan-state.yaml`
   - `current-step.spec.yaml`
   - `current-step.yaml`
   - `reports/`
   - `blocker.yaml`

### Option B: Transitional Layer

If a clean break is too disruptive:

1. Keep `handoff-to-executor.yaml` temporarily.
2. Stop using `handoff-to-architect.yaml`.
3. Treat the executor report as the only return artifact.
4. Gradually move to `current-step.yaml`.

Option A is preferable if you are willing to reset the workflow.

---

## Recommended Next Move

If the branch can be reset and the current AI workflow changes are not worth
keeping, the best next step is:

1. reset the branch to the beginning of `refactor/stack-lifecycle`
2. preserve only the high-level refactor docs that are still useful
3. implement the new workflow skeleton first:
   - plan file
   - plan-state file
   - step packet template
   - packet validator
   - blocker contract
4. only then resume Stage 1+ refactor execution

That gives the refactor a stable operating system before more implementation
work is delegated to agents.
