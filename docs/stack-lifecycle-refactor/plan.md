# Plan

## Goal

Refactor stack lifecycle management so that:

- Terraform owns day-1 infrastructure and Proxmox-side state
- Ansible owns day-2 managed state inside containers
- `stack.yaml` evolves into the shared contract for both layers

## Branching Model

- Long-lived program branch: `refactor/stack-lifecycle`
- Each stage is implemented on a short-lived branch cut from `refactor/stack-lifecycle`
- When a stage is validated, merge it back into `refactor/stack-lifecycle`
- Repeat until the refactor branch is ready for a full teardown/redeploy validation cycle
- Final promotion target: `baseline/teardown-validated`

`dev/pve-test` is not part of this workflow.

## Scope

### In Scope

- ownership boundary definition
- shared stack contract design
- inventory and generated artifact model
- day-1 / day-2 operator workflow
- drift policy
- validation model
- staged adoption by exemplar stacks

### Out of Scope For Initial Stages

- broad directory reorganization unless justified
- full redesign of all special-case stacks at once
- replacing every existing playbook before the target model is proven

## Delivery Strategy

- Keep stages narrow, reviewable, and validated.
- Prefer documentation and design before broad code movement.
- Do not reorganize directories early unless it directly reduces risk or confusion.
- Prove the model on exemplar stacks before extending it broadly.
- Keep `refactor/stack-lifecycle` in a usable state for the next stage branch.

## Staged Roadmap

### Stage 0: Program Setup

Suggested branch:

- `task/slr-00-program-setup`

Goals:

- establish the dedicated document tree
- capture initial decisions, assumptions, and open questions
- define the staged branch workflow for the refactor program

Deliverables:

- `docs/stack-lifecycle-refactor/` scaffold
- initial decision record
- initial roadmap
- initial handoff file

Exit criteria:

- future sessions have a stable place to start
- the branch model is documented
- the next design stage is clearly defined

Status:

- complete

### Stage 1: Shared Contract Draft

Suggested branch:

- `task/slr-01-shared-contract-draft`

Goals:

- audit the current implemented contract before proposing extensions
- draft the next-generation `stack.yaml` contract
- define which fields are shared source of truth
- define which artifacts are derived for Terraform and Ansible
- define how environment-level network intent relates to per-stack config

Deliverables:

- audit of the current contract surface in:
  - `terraform/lxc/PLATFORM_CONTRACT.md`
  - relevant per-stack `STACK_CONTRACT.md` files
  - Per-stack contract links:
    - [terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md](terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/authentik-stack/STACK_CONTRACT.md](terraform/lxc/stacks/authentik-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md](terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md](terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md](terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md](terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md)
- first-pass shared contract proposal
- documented generated-vs-authoritative boundaries
- documented treatment of stack metadata, network intent, and derived artifacts

Exit criteria:

- current contract coverage and gaps are explicit
- enough contract shape exists to guide implementation
- special-case extension sections are identified
- unresolved schema questions are explicit and limited

Notes:

- no large code movement in this stage
- this is the primary kickoff stage for the refactor
- do not draft from first principles without first reconciling with the current implemented contract

### Stage 2: Workflow And Validation Design

Suggested branch:

- `task/slr-02-workflow-and-validation`

Goals:

- define operator workflows for infra-only, config-only, and coordinated changes
- define the approved post-Terraform day-2 reconcile path
- define drift handling expectations for managed, observed, and adoptable areas
- define mandatory validation gates for each change class

Deliverables:

- workflow specification
- validation policy
- drift policy with first-pass operational rules

Exit criteria:

- the safe path is explicit
- approval points are defined
- validation requirements are clear enough to use during exemplar implementation

### Stage 3: Exemplar Selection And Implementation Scope

Suggested branch:

- `task/slr-03-exemplar-scope`

Goals:

- choose the first exemplar pair
- define what will and will not change in the exemplar stage
- identify stack-specific risks and dependencies

Deliverables:

- final exemplar selection
- per-exemplar scope notes
- implementation constraints and non-goals

Exit criteria:

- the first implementation slice is small enough to execute
- the first exemplar pair is agreed
- the expected validation evidence is defined

### Stage 4: Exemplar Scaffolding

Suggested branch:

- `task/slr-04-exemplar-scaffolding`

Goals:

- add the minimum shared scaffolding needed to support the target model
- avoid broad playbook rewrites beyond what the exemplars require
- preserve existing deployment behavior where practical

Possible implementation areas:

- shared contract parsing and rendering
- generated inventory or vars handoff changes
- day-2 reconcile entrypoint adjustments
- approval-aware post-infra reconcile path

Deliverables:

- minimal code scaffolding for the exemplars
- updated operator entrypoints as needed
- documentation aligned with the new flow

Exit criteria:

- exemplar stacks can use the intended day-1/day-2 structure
- infra changes do not implicitly destroy day-2 configuration state
- the scaffolding is stable enough for validation

Status:

- complete

Implementation note:

- Stage 4 introduced a bounded day-2 reconcile entrypoint for the exemplar pair only: `scripts/reconcile-exemplar-stacks.sh`

### Stage 5: Exemplar Validation And Adjustment

Suggested branch:

- `task/slr-05-exemplar-validation`

Goals:

- validate the exemplar implementation end to end
- capture gaps, friction, and edge cases
- adjust the shared model based on real usage

Deliverables:

- validation notes
- identified follow-up work
- updated decisions where necessary

Exit criteria:

- exemplar workflow is repeatable
- rerun behavior is acceptable
- remaining problems are specific rather than structural

### Stage 6: Clean Platform Stack Rollout

Suggested branch pattern:

- `task/slr-06-rollout-<stack-or-group>`

Goals:

- extend the model to additional lower-complexity platform stacks
- reduce duplicate patterns and sharpen the shared contract

Candidate early rollout targets:

- `apt-cacher-stack`
- `harbor-stack`

Deliverables:

- migrated clean-stack set
- refined shared patterns
- updated validation expectations where needed

Exit criteria:

- the model works for more than the first exemplar pair
- common patterns are clear
- remaining exceptions are better isolated

### Stage 7: Special-Case Strategy And Migration

Suggested branch pattern:

- `task/slr-07-special-case-<stack-or-theme>`

Goals:

- handle interconnected stacks deliberately rather than forcing them into a simplistic pattern
- decide which exceptions become capability flags and which remain stack-specific

Priority special-case themes:

- DNS and generated zone publication
- ingress and edge publication
- trust distribution
- identity/bootstrap integrations
- external registration lifecycles

Likely stacks:

- `dns-stack`
- `proxy-stack`
- `step-ca-stack`
- `authentik-stack`
- `monitoring-stack`
- `ci-runner-01`
- `portainer-stack`

Exit criteria:

- each special-case stack has an explicit treatment
- exceptions are documented and justified
- the shared model remains coherent

### Stage 8: Branch-Wide Reconciliation And Hardening

Suggested branch:

- `task/slr-08-branch-hardening`

Goals:

- review consistency across migrated stacks
- tighten documentation, validation, and operator workflows
- resolve remaining branch-level rough edges before final validation

Deliverables:

- cleaned-up docs
- resolved cross-stage issues
- branch-wide validation checklist

Exit criteria:

- `refactor/stack-lifecycle` is internally coherent
- the remaining work is validation-oriented rather than design-oriented

### Stage 9: Promotion Readiness

Suggested branch:

- `task/slr-09-promotion-readiness`

Goals:

- run the full validation sequence expected for eventual promotion
- prove the refactor branch can satisfy the `baseline/teardown-validated` gate

Required validation themes:

- full teardown
- infrastructure redeploy
- stack reconcile/deploy
- required service and integration checks

Exit criteria:

- promotion evidence is complete
- remaining issues are either resolved or explicitly accepted
- `refactor/stack-lifecycle` is ready for merge to `baseline/teardown-validated`

## Proposed First Exemplars

### Selected First Pair

- `apt-cacher-stack`
- `harbor-stack`

Why:

- useful
- less cross-stack coupling than identity, DNS, trust, or ingress stacks
- avoids using a stack already identified as a current special case

### Deferred Candidate

- `netbox-stack`

Why deferred:

- richer compose/bootstrap behavior
- already classified as a special case needing explicit treatment

## Exit Criteria For The First Exemplar Stage

- shared contract fields are documented
- the operator workflow is documented
- the exemplar stacks can be reconciled through the intended day-2 path
- validation expectations are documented and repeatable
- open issues are captured for the next stage

## Kickoff Recommendation

Kick off the refactor with:

- `task/slr-01-shared-contract-draft`

This stage should:

- audit `terraform/lxc/PLATFORM_CONTRACT.md` and relevant stack contract files
- finalize the first draft of the shared `stack.yaml` contract
- define the generated artifact model
- confirm how the new contract extends rather than conflicts with the existing one
- avoid broad implementation changes until the contract is stable enough

Recommended immediate sequence:

1. Audit the existing contract documents and current contract surface.
2. Record gaps, overlaps, and conflicts.
3. Draft the shared contract extensions and structure.
4. Record unresolved schema questions.
5. Define the validation gates the exemplar stage must satisfy.
6. Then move into implementation scaffolding.
