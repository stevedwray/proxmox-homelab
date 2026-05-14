# Stack Lifecycle Refactor Execution Plan

## Program Goal

Refactor stack lifecycle management so that:

- Terraform owns day-1 infrastructure and Proxmox-side state
- Ansible owns day-2 managed state inside containers
- `stack.yaml` evolves into the shared contract for both layers

This plan is the durable source of truth for autonomous execution.

## Operating Model

- `execution-plan.md` defines the staged roadmap and step intent
- `.git/ai/plan-state.yaml` tracks the machine-readable current step state
- `.git/ai/current-step.spec.yaml` is the authoring source for the next executor packet
- `.git/ai/current-step.yaml` is the rendered machine contract the executor runs
- `.git/ai/reports/<step-id>.md` captures execution evidence
- `.git/ai/blocker.yaml` exists only when execution cannot continue autonomously

The operator should only be involved for:

- destructive approval
- genuine technical blockers
- plan ambiguity or contradiction
- explicit plan changes

## Reset Assumption

This workflow assumes the program can be resumed from the beginning of
`refactor/stack-lifecycle` with the existing document tree retained as planning
context, but with prior AI handoff artifacts treated as disposable.

## Stages

### Stage 0: Program Setup

Status:

- treated as complete once the workflow skeleton and document tree exist

Outcome:

- planning and execution scaffolding exists

### Stage 1: Shared Contract Draft

Step ids:

- `slr-01-contract-audit`
- `slr-01-shared-contract-draft`

Goals:

- audit the current implemented contract
- draft the next-generation shared stack contract
- identify gaps, overlaps, and derived artifacts

Deliverables:

- contract audit notes
- shared contract draft
- explicit authoritative vs derived boundaries

### Stage 2: Workflow And Validation Design

Step ids:

- `slr-02-workflow-spec`
- `slr-02-validation-policy`
- `slr-02-drift-policy`

Goals:

- define operator workflows
- define validation gates
- define drift handling classes and operational rules

### Stage 3: Exemplar Selection And Scope

Step ids:

- `slr-03-exemplar-selection`
- `slr-03-scope-notes`

Goals:

- pick the first exemplar pair
- bound the implementation slice
- document explicit non-goals

### Stage 4: Exemplar Scaffolding

Step ids:

- `slr-04-scaffolding-main-work`
- `slr-04-scaffolding-closeout`

Goals:

- implement only the minimum shared scaffolding needed for the exemplar model
- keep behavior stable
- avoid broad code movement

### Stage 5: Exemplar Validation And Adjustment

Step ids:

- `slr-05-validation-run`
- `slr-05-adjustments`

Goals:

- validate the exemplar flow end to end
- capture friction and gaps
- adjust the model based on real usage

### Stage 6: Clean Platform Stack Rollout

Step ids:

- `slr-06-rollout-apt-cacher`
- `slr-06-rollout-harbor`

Goals:

- roll the model out to lower-complexity stacks
- refine shared patterns

### Stage 7: Special-Case Strategy And Migration

Step ids:

- `slr-07-special-case-strategy`

Goals:

- define how exceptional stacks migrate
- document safe deviation patterns

## Step Rules

Every step must declare:

- one step id
- one stage number
- one step type:
  - `bootstrap`
  - `main_work`
  - `closeout`
  - `promote`
  - `validate`
- one branch expectation
- a bounded path/action scope
- concrete validation gates
- a report path

## Escalation Rules

Execution should stop and emit `.git/ai/blocker.yaml` only when:

- a critical gate fails and the fix is outside the current step scope
- a required approval is missing
- the current plan is ambiguous or contradictory
- the branch/runtime state is unsafe to continue from

Normal successful execution should not route back through architect after every
step.
