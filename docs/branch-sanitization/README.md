# Branch Sanitization Evaluation Plan

## Purpose

This plan defines how to evaluate the remaining candidate branches against the
current `baseline/teardown-validated` state without polluting the baseline
branch or its working tree.

Baseline takes absolute precedence. No branch under evaluation is assumed to be
correct. A candidate branch must prove value on top of the current baseline
state through isolated replay and rigorous regression testing before any part of
it is considered for retention.

## Baseline Protection Rules

1. Treat `baseline/teardown-validated` as read-only.
2. Do not check out candidate branches in the baseline worktree.
3. Do not merge candidate branches directly into baseline for evaluation.
4. Use a fresh throwaway worktree for every evaluation branch.
5. Replay changes onto a new branch cut from the current baseline HEAD.
6. Delete the throwaway worktree and evaluation branch immediately if a branch
   fails validation or proves unnecessary.

## Evaluation Workflow

For every candidate branch:

1. Create an isolated worktree from the current baseline tip.
2. Replay the candidate branch onto that new branch.
3. Run the required regression gates for that branch class.
4. Record evidence and a keep/delete recommendation.
5. If the replay is bad, discard the worktree.
6. If the replay is good, prepare a clean baseline-based retention path.

Example workflow:

```bash
git worktree add .worktrees/eval-task-name -b eval/task-name baseline/teardown-validated
cd .worktrees/eval-task-name
git cherry-pick <candidate-commit-or-range>
```

If the branch is too bundled for clean replay, do not test it as-is. Extract the
functional slice into a new baseline-based evaluation branch first.

## Shared Regression Gates

Every evaluated branch must pass these common checks before any branch-specific
testing:

1. `git status --short`
2. `bash -n` for every changed shell script
3. `shellcheck` for every changed shell script where applicable
4. `ansible-playbook --syntax-check` for every changed playbook
5. `python3 -m unittest terraform/lxc/test_stack_classification.py` if any
   `stack.yaml`, contract, or classification behavior changes
6. `./scripts/teardown-deploy-test.sh plan`
7. `./scripts/teardown-deploy-test.sh source-preflight`
8. `./scripts/teardown-deploy-test.sh live-preflight`

If any shared gate fails, stop the evaluation and discard the candidate until it
is narrowed or fixed.

## Evidence Requirements

For each evaluated branch, capture:

- baseline commit SHA used for the replay
- evaluation branch name
- replay method (`cherry-pick`, manual extraction, or slice branch)
- exact commands run
- command outputs or log paths
- pass/fail verdict
- recommended disposition: `retain`, `extract subset`, or `delete`

Store evidence under a timestamped ignored directory or a tracked summary doc,
but do not commit bulky logs to baseline unless explicitly approved.

## Candidate Branches

The remaining functional branches are:

- `task/stack-contract-tidyup-01`
- `task/teardown-harness-hardening-01`
- `task/34-basic-sdn-reset`
- `work/pve-test-teardown-cycle-194-03`
- `exec/teardown-deploy-validate`

The branch `worktree-fix-approval-passthrough` is not part of the functional
evaluation set. It is prompt/policy-only and can be removed after its linked
worktree is cleaned up.

## Evaluation Order

Evaluate from lowest-risk to highest-risk:

1. `task/stack-contract-tidyup-01`
2. `task/teardown-harness-hardening-01`
3. `task/34-basic-sdn-reset`
4. `work/pve-test-teardown-cycle-194-03`
5. `exec/teardown-deploy-validate`

This order keeps the early passes narrow and helps us decide whether later
branches still contain unique functional value.

## Branch-Specific Regression Plan

### 1. `task/stack-contract-tidyup-01`

Functional intent:

- close the `dns_server` stack contract gap
- update stack definitions and classification coverage

Replay expectation:

- should cherry-pick cleanly or with minimal conflict resolution

Required regression:

1. `python3 -m unittest terraform/lxc/test_stack_classification.py`
2. verify changed `stack.yaml` files still parse cleanly
3. `./scripts/teardown-deploy-test.sh plan`
4. `./scripts/teardown-deploy-test.sh source-preflight`

Promotion bar:

- all stack classification tests pass
- no regression in contract-driven planning/preflight behavior

### 2. `task/teardown-harness-hardening-01`

Functional intent:

- harden approval-packet validation in `scripts/teardown-deploy-test.sh`

Replay expectation:

- should replay as a focused harness change

Required regression:

1. `bash -n scripts/teardown-deploy-test.sh`
2. `shellcheck scripts/teardown-deploy-test.sh`
3. `./scripts/teardown-deploy-test.sh --help`
4. `./scripts/teardown-deploy-test.sh plan`
5. `./scripts/teardown-deploy-test.sh status --stamp <known-stamp>`
6. negative tests for missing and malformed `--approval-packet`
7. `./scripts/teardown-deploy-test.sh approval-preflight --require-clean`
8. `./scripts/teardown-deploy-test.sh final-validation`

Promotion bar:

- no harness regressions in non-destructive flows
- invalid approval packets fail early and clearly

### 3. `task/34-basic-sdn-reset`

Functional intent:

- add a basic SDN smoke harness
- add targeted build/VLAN reconcile support

Replay expectation:

- may require careful conflict handling if nearby SDN files have moved

Required regression:

1. syntax-check changed Ansible playbooks
2. `bash -n terraform/lxc/validate-sdn-basic.sh`
3. `./with-secrets terraform/lxc/validate-sdn-basic.sh validate`
4. if safe and isolated, `./with-secrets terraform/lxc/validate-sdn-basic.sh cycle`
5. confirm `terraform/lxc/network/pve-test.yaml` remains consistent with
   current baseline assumptions
6. run baseline preflight checks before and after the SDN smoke cycle

Promotion bar:

- smoke harness works cleanly from a baseline-based replay
- apply/validate/destroy path leaves no unexpected residual state

### 4. `work/pve-test-teardown-cycle-194-03`

Functional intent:

- parameterize lab domain/base-domain handling
- adjust deploy playbooks and edge reconciliation behavior
- fix NetBox/AuthentiK-related deployment and validation issues

Replay expectation:

- likely to touch many active files and may need manual conflict resolution

Required regression:

1. syntax-check all changed playbooks
2. validate changed Python reconcile/discovery scripts
3. `./scripts/teardown-deploy-test.sh source-preflight`
4. `./scripts/teardown-deploy-test.sh live-preflight`
5. targeted check/live reconcile for affected stacks:
   - `authentik-stack`
   - `dns-stack`
   - `monitoring-stack`
   - `netbox-stack`
   - `portainer-stack`
6. targeted edge reconcile validation for:
   - `terraform/lxc/discover-authentik-edge.py`
   - `terraform/lxc/reconcile-authentik-edge.py`
   - `terraform/lxc/reconcile-edge.py`
7. `./scripts/teardown-deploy-test.sh final-validation`
8. if all earlier gates pass and operator approval is available, a full
   teardown/redeploy cycle in the evaluation worktree context

Promotion bar:

- no regressions across the affected deploy/reconcile flows
- domain parameterization works with current baseline topology
- full validation remains green

### 5. `exec/teardown-deploy-validate`

Functional intent:

- mixed bundle containing teardown helpers, SDN harness work, MikroTik changes,
  router material, and support scripts

Replay expectation:

- do not evaluate as one branch unless forced

Required approach:

1. decompose the branch into functional slices first
2. map each slice to one of the cleaner branch themes above
3. replay only the slice being tested onto a new baseline-based evaluation branch

Provisional slices to extract:

- SDN harness slice
- MikroTik reconcile slice
- teardown helper slice
- router subtree slice

Promotion bar:

- no bundled evaluation
- only retained if a slice proves unique functional value beyond the cleaner
  surviving branches

## Stop Conditions

Stop evaluation immediately if:

- replay requires broad invasive conflict resolution that obscures authorship
- a shared regression gate fails
- a candidate branch introduces drift into the evaluation environment that is
  not cleanly reversible
- the candidate’s functional delta is already present in a cleaner evaluated
  branch
- the candidate proves to be documentation-only or workflow-only after replay

## Expected Outcomes

Each branch should end in one of three states:

- `retain`: replayed cleanly, passed regression, worth preserving
- `extract subset`: bundled branch contains value, but only a narrower slice
  should survive
- `delete`: no unique functional value or failed regression on top of baseline

The final result of this process should be a small set of baseline-based,
well-tested retained changes and the removal of all stale or redundant branches.
