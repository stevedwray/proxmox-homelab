# Branch Sanitization Evaluation Checklist

## Purpose

This plan defines how to evaluate the remaining candidate branches against the
current `baseline/teardown-validated` state without polluting the baseline
branch or its working tree.

Baseline takes absolute precedence. No branch under evaluation is assumed to be
correct. A candidate branch must prove value on top of the current baseline
state through isolated replay and branch-class-appropriate regression testing
before any part of it is considered for retention.

## Baseline Protection Rules

1. Treat `baseline/teardown-validated` as read-only.
2. Do not check out candidate branches in the baseline worktree.
3. Do not merge candidate branches directly into baseline for evaluation.
4. Use a fresh throwaway worktree for every evaluation branch.
5. Replay changes onto a new branch cut from the current baseline HEAD.
6. Delete the throwaway worktree and evaluation branch immediately if a branch
   fails validation or proves unnecessary.

## Preflight Checklist

Before replaying any candidate branch:

1. Confirm the baseline worktree is clean with `git status --short`.
2. Record the baseline commit SHA.
3. Compare the candidate against baseline and `dev/pve-test` to see whether the
   functional delta already exists elsewhere.
4. Classify the branch into one of the branch classes below.
5. If the branch is bundled, define the smallest slice that can be replayed
   cleanly on top of baseline.
6. Select only the gates for that branch class.

## Branch Classes

Use the smallest class that accurately describes the change:

1. `stack-contract` - stack metadata, classification, or contract coverage
2. `harness` - teardown harness, shell wrapper, approval-packet, or CLI flow
3. `sdn-smoke` - SDN harness, reconcile helper, or network smoke validation
4. `stack-deploy` - deploy playbooks or targeted stack bootstrap fixes
5. `bundled` - mixed changes that must be decomposed before retention

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
6. Run the cheapest branch-class gate first, then expand only if it still looks
   like a retain candidate.

If any shared gate fails, stop the evaluation and discard the candidate until it
is narrowed or fixed.

## Gate Matrix

Use this matrix after the shared gates. Do not run every gate for every branch.

| Branch class | Required gates |
|---|---|
| `stack-contract` | `python3 -m unittest terraform/lxc/test_stack_classification.py`, verify changed `stack.yaml` files parse cleanly, `./scripts/teardown-deploy-test.sh plan`, `./scripts/teardown-deploy-test.sh source-preflight` |
| `harness` | `./scripts/teardown-deploy-test.sh --help`, `./scripts/teardown-deploy-test.sh plan`, `./scripts/teardown-deploy-test.sh status --stamp <known-stamp>`, negative tests for missing and malformed `--approval-packet`, `./scripts/teardown-deploy-test.sh approval-preflight --require-clean`, `./scripts/teardown-deploy-test.sh final-validation` |
| `sdn-smoke` | syntax-check changed Ansible playbooks, `bash -n terraform/lxc/validate-sdn-basic.sh`, `./with-secrets terraform/lxc/validate-sdn-basic.sh validate`, then only if the branch still looks unique, `./with-secrets terraform/lxc/validate-sdn-basic.sh cycle` and baseline preflight checks before and after the cycle |
| `stack-deploy` | syntax-check changed playbooks, validate changed Python reconcile/discovery scripts, `./scripts/teardown-deploy-test.sh source-preflight`, `./scripts/teardown-deploy-test.sh live-preflight`, targeted checks for affected stacks, targeted edge reconcile validation, `./scripts/teardown-deploy-test.sh final-validation` |
| `bundled` | extract a narrower slice first, then apply the gates for the slice's class instead of the whole bundle |

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

## Branch-by-Branch Classification

| Candidate branch | Class | Notes |
|---|---|---|
| `task/stack-contract-tidyup-01` | `stack-contract` | Narrow contract/classification update; good candidate for early replay |
| `task/teardown-harness-hardening-01` | `harness` | Focused CLI and validation hardening; should stay on the harness gate path |
| `task/34-basic-sdn-reset` | `sdn-smoke` | SDN smoke harness and playbook support; validate the harness first, then only run the cycle if needed |
| `work/pve-test-teardown-cycle-194-03` | `stack-deploy` | Single-file deploy/playbook tweak; use targeted stack-deploy gates, not a full multi-stack sweep unless the diff grows |
| `exec/teardown-deploy-validate` | `bundled` | Must be decomposed into slices before any retention decision |

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

## GitHub Copilot Prompt Pack

The current repo-level Copilot setup is still fairly thin. In this working
tree, `.github/copilot-instructions.md` is present, but `.github/agents/` and
`.github/instructions/` are effectively empty. That means Copilot will behave
better here if each prompt is explicit about:

- the baseline protection rules
- the exact branch or commit under evaluation
- the exact gates to run
- when to stop instead of improvising

The raw branch-versus-baseline diffs are also noisy because some candidate
branches are far behind the current baseline tip. Prefer prompts that tell
Copilot to reason from unique commits and narrow replay slices, not from the
full branch diff.

### Current Candidate Reality Check

Use these current facts when steering Copilot:

- `task/stack-contract-tidyup-01` has one unique commit on top of baseline:
  `b5caf14`
- `task/teardown-harness-hardening-01` has one unique commit on top of
  baseline: `055b8ec`
- `task/34-basic-sdn-reset` carries one likely retainable functional commit:
  `7d8d9a6`, plus older docs/report commits that should not be replayed unless
  they prove necessary
- `work/pve-test-teardown-cycle-194-03` currently has seven unique commits on
  top of baseline, so do not treat it as a one-commit branch without checking
  first:
  `4349057`, `a2e8adc`, `5d69e13`, `e7a7e39`, `fb35a73`, `8dcbe07`, `2a1340e`
- `exec/teardown-deploy-validate` is bundled and must be decomposed before any
  replay attempt

### How To Use These Prompts

1. Paste one prompt at a time into Copilot Chat or Copilot Agent.
2. Wait for it to finish before moving to the next prompt.
3. If Copilot starts broadening scope, stop it and use one of the correction
   prompts at the end of this section.
4. Keep all branch evaluation work in throwaway worktrees, never in the
   baseline worktree.

### Prompt 0: Load Context Only

```text
You are helping with the branch sanitization workflow in
/home/steve/git/proxmox-homelab.

Read only these files first:
- AGENTS.md
- .github/copilot-instructions.md
- docs/branch-sanitization/README.md

Do not modify any files yet.
Do not check out any candidate branch in the baseline worktree.

Summarize:
1. the baseline protection rules
2. the candidate branches
3. the branch classes
4. the shared regression gates
5. the stop conditions

Then tell me which branch should be evaluated first and why.
```

### Prompt 1: Preflight The Baseline Worktree

```text
Stay in /home/steve/git/proxmox-homelab and do a read-only preflight before any
branch replay.

Run:
- git status --short
- git rev-parse baseline/teardown-validated
- git branch --list 'task/*' 'work/*' 'exec/*' 'baseline/*' 'dev/*'

Do not modify anything.
Report the exact outputs and flag any blocker to starting branch evaluation.
```

### Prompt 2: Evaluate `task/stack-contract-tidyup-01`

```text
Evaluate only the stack-contract candidate branch
`task/stack-contract-tidyup-01`.

Rules:
- Treat `baseline/teardown-validated` as read-only.
- Use a fresh throwaway worktree.
- Replay only commit `b5caf14` onto a new branch from the current baseline
  tip.
- Do not replay the whole branch if Copilot sees a noisy diff.
- Stop if replay requires broad invasive conflict resolution.

Use:
- worktree path: .worktrees/eval-stack-contract-tidyup-01
- eval branch: eval/stack-contract-tidyup-01

After replay, run the smallest relevant gates for the `stack-contract` class:
- git status --short
- python3 -m unittest terraform/lxc/test_stack_classification.py
- verify the changed stack.yaml files parse cleanly
- ./scripts/teardown-deploy-test.sh plan
- ./scripts/teardown-deploy-test.sh source-preflight

Capture:
- baseline SHA
- replay method
- commands run
- pass/fail verdict
- retain/delete recommendation

If a gate fails, stop and explain exactly where it failed.
```

### Prompt 3: Evaluate `task/teardown-harness-hardening-01`

```text
Evaluate only the harness candidate branch
`task/teardown-harness-hardening-01`.

Rules:
- Treat `baseline/teardown-validated` as read-only.
- Use a fresh throwaway worktree.
- Replay only commit `055b8ec` onto a new branch from the current baseline
  tip.
- Do not broaden scope beyond this harness slice.
- Stop if replay requires broad invasive conflict resolution.

Use:
- worktree path: .worktrees/eval-teardown-harness-hardening-01
- eval branch: eval/teardown-harness-hardening-01

After replay, run the shared gates that apply and then the harness gates:
- git status --short
- bash -n scripts/teardown-deploy-test.sh
- shellcheck scripts/teardown-deploy-test.sh if shellcheck is available
- ./scripts/teardown-deploy-test.sh --help
- ./scripts/teardown-deploy-test.sh plan
- negative test for missing --approval-packet
- negative test for malformed --approval-packet
- ./scripts/teardown-deploy-test.sh approval-preflight --require-clean
- ./scripts/teardown-deploy-test.sh final-validation

If `status --stamp <known-stamp>` needs a real stamp and none is available,
stop and ask me for the stamp instead of inventing one.

Capture:
- baseline SHA
- replay method
- commands run
- pass/fail verdict
- retain/delete recommendation
```

### Prompt 4: Evaluate `task/34-basic-sdn-reset`

```text
Evaluate the `sdn-smoke` candidate branch `task/34-basic-sdn-reset`, but do not
replay the whole branch blindly.

Start by confirming the unique commit history and then narrow replay to the
functional SDN smoke harness commit `7d8d9a6` unless a dependency proves
otherwise.

Rules:
- Treat `baseline/teardown-validated` as read-only.
- Use a fresh throwaway worktree.
- Prefer replaying only commit `7d8d9a6`.
- Ignore older docs/report commits unless they are required for the functional
  slice.
- Before any credentialed command, verify:
  ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
  and stop unless it returns `pve-test`.

Use:
- worktree path: .worktrees/eval-basic-sdn-reset
- eval branch: eval/basic-sdn-reset

Run the smallest relevant gates first:
- git status --short
- ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/validate-sdn-basic.yml
- bash -n terraform/lxc/validate-sdn-basic.sh
- ./with-secrets terraform/lxc/validate-sdn-basic.sh validate

Only if the slice still looks unique and healthy after those checks, consider:
- ./with-secrets terraform/lxc/validate-sdn-basic.sh cycle

Capture:
- whether the slice was cleanly isolated to `7d8d9a6`
- baseline SHA
- replay method
- commands run
- pass/fail verdict
- retain/delete recommendation
```

### Prompt 5: Decompose `work/pve-test-teardown-cycle-194-03`

```text
Do not evaluate `work/pve-test-teardown-cycle-194-03` as a single branch yet.
It currently has seven unique commits on top of baseline:

- 4349057
- a2e8adc
- 5d69e13
- e7a7e39
- fb35a73
- 8dcbe07
- 2a1340e

I want a decomposition pass first.

Tasks:
1. Inspect those seven commits and group them into the smallest sensible slices.
2. Identify whether the branch really contains:
   - a `lab-domain parameterization` slice
   - a `stack-deploy` env/export slice
   - a tiny `netbox indentation fix` slice
3. Recommend which slice, if any, should be replayed first on top of baseline.
4. Tell me the exact cherry-pick order for that slice only.

Rules:
- Do not create a worktree yet unless you first present the slice plan.
- Do not recommend replaying the whole branch unless you can justify why the
  seven commits are inseparable.
- Call out any docs-only or already-superseded commits.

Return a short table with:
- commit or commit range
- intended slice name
- branch class
- likely keep/delete status
- reason
```

### Prompt 6: Decompose `exec/teardown-deploy-validate`

```text
Do not evaluate `exec/teardown-deploy-validate` as a whole branch.
Treat it as bundled until proven otherwise.

Tasks:
1. Inspect the branch's unique commits against baseline.
2. Separate docs-only changes from functional changes.
3. Identify the smallest functional slices worth considering for replay.
4. Map each slice to one of these classes:
   - stack-contract
   - harness
   - sdn-smoke
   - stack-deploy
   - bundled
5. Recommend which slices should be:
   - retained
   - extracted as a subset
   - deleted

Rules:
- Do not create an evaluation worktree yet.
- Do not recommend replaying the entire branch.
- If a slice overlaps work already covered by `task/34-basic-sdn-reset`,
  `task/teardown-harness-hardening-01`, or
  `task/stack-contract-tidyup-01`, call that out explicitly.

Return a table with:
- commit or commit range
- files touched
- proposed slice name
- branch class
- retain/extract/delete recommendation
- reason
```

### Prompt 7: Write The Evidence Summary

```text
Using the branch sanitization checklist, draft a concise evidence summary for
the branch we just evaluated.

Include:
- baseline SHA
- evaluation branch name
- replay method
- exact commands run
- pass/fail verdict
- recommended disposition: retain, extract subset, or delete
- any follow-up blocker or open question

Do not invent results. If a command was skipped, say it was skipped and why.
```

### Correction Prompt: If Copilot Tries To Use The Baseline Worktree

```text
Stop. Do not check out or replay candidate work in the baseline worktree.
Return to the branch sanitization rules and create a fresh throwaway worktree
from `baseline/teardown-validated` instead.
```

### Correction Prompt: If Copilot Starts Using Full Branch Diffs

```text
Stop. The full branch diff is misleading because this branch is drifted.
Reframe the evaluation around unique commits and the smallest replayable slice
on top of the current baseline HEAD.
```

### Correction Prompt: If Copilot Broadens Scope

```text
Stop. Stay inside the current candidate branch and its branch-class gate set.
Do not mix in unrelated cleanup, refactors, or adjacent docs work.
```
