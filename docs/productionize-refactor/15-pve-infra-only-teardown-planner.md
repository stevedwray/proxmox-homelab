# pve Infra-Only Teardown Planner

## Goal

Define the first safe implementation slice for a `pve` infra-only teardown
planner that can produce a high-confidence dry-run summary without touching any
unrelated guest, VM, or storage on `pve`.

This document is deliberately planner-first. It does not authorize live
destroy execution.

The current planner implementation remains advisory and read-only. It is a
preflight evidence tool, not a production destroy authority.

## Why The Existing Harness Is Not Enough

The current harness, [scripts/teardown-deploy-test.sh](/home/steve/git/proxmox-homelab/scripts/teardown-deploy-test.sh:1),
is a `pve-test` rehearsal tool with these assumptions baked in:

- inventory path fixed to `docs/teardown-test/inventory.md`
- wrapper path fixed to `./with-secrets`
- target node expectation defaults to `pve-test`
- mutating phases (`destroy`, `deploy-*`, `cycle`) are part of the same script
  surface as read-only phases

Those defaults are reasonable for a disposable rehearsal environment, but they
are not strict enough for production.

## Scope

The planner described here applies only to the infra-only inventory frozen in:

- [pve-infra-teardown-inventory.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-infra-teardown-inventory.md:1)

It must not expand scope to:

- validation stacks
- `test-*` stacks
- `pve-test`
- unrelated legacy guests on `pve`
- host-level storage/network administration

## Required Planner Outputs

The future dry-run planner must produce a summary that answers these questions:

1. What exact stacks and VMIDs are in scope?
2. What exact CTs and VMs currently exist on `pve` but are explicitly out of
   scope?
3. What is the candidate destroy order?
4. For each in-scope stack, what does `terragrunt plan -destroy` propose?
5. Does any stack plan reference a target node other than `pve`?
6. Does any stack plan propose changes outside the stack directory being
   inspected?
7. What storage backends or mounted volumes appear stack-owned versus shared?
8. What blockers exist that should stop any future destructive approval packet?

## Recommended First Implementation Slice

Implement a read-only planner first, not a destroy harness.

Recommended form:

- add a new script such as `scripts/plan-pve-infra-teardown.sh`
- support read-only phases only:
  - `source-preflight`
  - `platform-status`
  - `plan`
  - `summary`

Reasons to prefer a new read-only script first:

- it avoids accidental reuse of `destroy` or `cycle` paths meant for `pve-test`
- it allows tighter production-specific output without widening the execution
  surface
- it can later share parsing code with the `pve-test` harness once the
  production rules are proven

## Suggested Inputs

- inventory source:
  `docs/productionize-refactor/pve-infra-teardown-inventory.md`
- credential wrapper:
  `./with-secrets-prod`
- target guard:
  `TF_VAR_proxmox_node=pve`
- evidence root:
  `docs/productionize-refactor/evidence/pve-infra-teardown-plan-<stamp>/`

## Suggested Read-Only Phase Design

### 1. `source-preflight`

Prove the source model is internally consistent.

Checks:

- every inventory stack has a `stack.yaml`
- VMID and IP in inventory match `stack.yaml`
- destroy order only references in-scope stacks
- no stack in scope has `enabled: false`
- if `ci-runner-01` is in scope, operator GitHub CLI auth preflight passes
  (`gh auth status`)

### 2. `platform-status`

Capture current out-of-scope safety context from `pve`.

Checks:

- `pct list`
- `qm list`
- `pvesm status`
- optional summary grouping:
  - in-scope VMIDs found
  - out-of-scope VMIDs found
  - missing expected in-scope VMIDs

### 3. `plan`

Run a stack-local destroy dry run for each in-scope stack.

Suggested command shape:

```bash
./with-secrets-prod terragrunt plan -destroy --working-dir terraform/lxc/stacks/<stack> -no-color
```

Required planner interpretation:

- confirm `target_node = pve`
- flag any reference to a VMID outside the inventory freeze
- flag any proposed destroy outside the current stack directory
- capture the per-stack resource summary in evidence

### 4. `summary`

Produce a human-readable approval packet draft containing:

- scope table
- explicit exclusions
- live out-of-scope guest list
- per-stack destroy-plan result
- any blockers or unknowns
- a final verdict:
  - `SAFE TO REVIEW FURTHER`
  - or `BLOCKED`

## OIDC Input Ownership And Precedence

For this planner/advisory pass, treat ownership and precedence for the audited
OIDC tuning inputs as follows:

1. Grafana OAuth tuning keys are non-secret environment overlay values.
   - keys: `GRAFANA_OAUTH_SCOPES`, `GRAFANA_OAUTH_ROLE_ATTRIBUTE_PATH`
   - canonical review owner for `pve`: `.env.pve`
   - if these keys are absent from `.env.pve`, playbook defaults are expected;
     record that as a parity review item rather than assuming full parity

2. Harbor `HARBOR_OIDC_PRIMARY_AUTH_MODE` is a non-secret runtime tuning value.
   - canonical review owner for `pve`: `.env.pve`
   - if a value is also present in `terraform/secrets.pve.enc.yaml`, treat this
     as precedence ambiguity and flag for operator review before teardown

## Guardrails For A Later Mutating Phase

Do not add a production destroy executor until the planner can already prove:

1. only in-scope VMIDs appear in all destroy plans
2. target guard is always `pve`
3. out-of-scope guests are enumerated explicitly in the summary
4. shared storage impact is summarized
5. the operator has a reviewed approval packet, not just raw logs

If a later destructive executor is added, it should likely remain a separate
script or subcommand with stricter approval requirements than the current
`pve-test` harness.

## Immediate Follow-On Work

1. Build the read-only planner script using the inventory freeze above.
2. Reuse only the safe parser pieces from `scripts/teardown-deploy-test.sh`
   such as inventory parsing and logging patterns.
3. Keep all production execution read-only until the planner summary is proven
   trustworthy on real `pve` state.

## Done When

- the inventory freeze exists for `pve` infra-only scope
- the planner design is explicit about exclusions and required outputs
- the next implementation session can write the read-only planner script
  without re-deriving the production safety model
