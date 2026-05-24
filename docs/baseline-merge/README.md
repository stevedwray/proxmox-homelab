# Baseline Merge Plan

## Purpose

This document tree defines the work needed to make
`baseline/teardown-validated` and `prod/pve-infra` effectively consistent.

The goal is not to erase all differences between the branches. The goal is to
make their core lifecycle logic and stack behavior match closely enough that:

- teardown/redeploy validation on `pve-test` is meaningful for future work
- new refactors can be developed on `pve-test` instead of directly on `pve`
- promotion from test to production becomes a controlled environment-difference
  problem rather than a logic-drift problem

## Plan Documents

- [Execution Plan](./plan.md)

## Why This Work Exists

Productionization work uncovered a set of changes that matter beyond
production-only operation:

- branch model changes
- environment targeting fixes
- stack day-2 behavior fixes
- production-aware wrappers and guardrails
- documentation updates that explain the new lifecycle model

Those changes now live on `prod/pve-infra`, but we do not yet have the same
behavioral baseline on `baseline/teardown-validated`.

Until that gap is closed, work on credential rotation and data preservation
would be riskier than it needs to be because `pve-test` would no longer be a
reliable stand-in for `pve`.

## Desired End State

After this work:

- `prod/pve-infra` remains the validated production promotion branch
- `baseline/teardown-validated` remains the validated teardown/redeploy branch
- the main differences between them are environment-specific variables,
  wrappers, approvals, and explicitly production-only handling
- stack lifecycle logic, deploy behavior, and relevant bug fixes are shared

This is a convergence target, not a permanent fork.

## Key Rule

The backport into `baseline/teardown-validated` should be selective but
behavior-driven.

That means:

- do not blindly merge all production-specific changes
- do backport the fixes and structure needed so `pve-test` exercises the same
  core code paths
- keep branch differences mostly in variables, environment manifests, and
  production-only safety handling

## Workstreams

### 1. Production Branch Curation

`prod/pve-infra` now exists as the production promotion branch and carries the
validated current state.

Rules for that branch:

- no session handoffs or evidence snapshots committed there
- production-targeted code and docs are allowed there
- future production work should come from short-lived child branches

### 2. Baseline Backport Stream

Create a short-lived branch from `baseline/teardown-validated` dedicated to the
convergence work.

Suggested branch shape:

```bash
git checkout baseline/teardown-validated
git pull --ff-only origin baseline/teardown-validated
git checkout -b work/baseline-convergence-01
```

The mission of that branch is:

- identify the productionization deltas that matter to teardown/redeploy and
  stack lifecycle behavior
- backport them cleanly to the baseline branch
- leave out changes that are purely production-local or should stay isolated to
  `pve`

### 3. Teardown Validation On `pve-test`

Once the backport branch carries the needed fixes, run the full teardown and
redeploy validation on `pve-test`.

That validation is the promotion gate for merging the convergence branch back
into `baseline/teardown-validated`.

### 4. Follow-On Refactor Work

Only after the convergence branch lands should the new credential-management
and data-preservation work begin on `pve-test`.

That gives both programs a more trustworthy base.

## Expected Areas To Compare

The comparison between `prod/pve-infra` and `baseline/teardown-validated`
should focus on:

- targeting and wrapper behavior
- stack deployment scripts and playbooks
- workflow and validation automation
- branch-model and operator-facing documentation
- any productionization fixes that change runtime behavior

It should not treat session handoffs, ignored evidence, or other local artifacts
as merge material.

## Acceptance Criteria For "Consistent Enough"

Before starting the next two refactors, we should be able to say:

- the same core lifecycle code paths are exercised on `pve-test` and `pve`
- environment-specific differences are explicit and intentional
- teardown/redeploy on `pve-test` passes with the backported code
- a future fix can usually be authored once and promoted to both branches with
  minimal translation

## Relationship To Other Refactors

This convergence work is the prerequisite platform stream for:

- [docs/credential-management-refactor/README.md](/home/steve/git/proxmox-homelab/docs/credential-management-refactor/README.md:1)
- [docs/data-preservation-refactor/README.md](/home/steve/git/proxmox-homelab/docs/data-preservation-refactor/README.md:1)

Those two should be treated as follow-on programs, not parallel guesses built
on branch drift.

## Suggested Delivery Sequence

1. Diff `prod/pve-infra` against `baseline/teardown-validated`.
2. Sort changes into:
   - required for behavioral consistency
   - production-only
   - docs-only but useful
3. Backport the required set on a short-lived convergence branch.
4. Run the teardown/redeploy gate on `pve-test`.
5. Merge the convergence branch into `baseline/teardown-validated`.
6. Start credential-management and data-preservation work from the refreshed
   baseline.
