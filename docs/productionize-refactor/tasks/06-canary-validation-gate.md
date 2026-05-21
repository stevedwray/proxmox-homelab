# Task 06: Canary Validation Gate

## Goal

Prove that production networking and environment targeting work on `pve` before
moving a higher-value real service.

## Objective

Create a canary workflow that validates:

- VLAN transport on `vmbr0`
- gateway reachability
- DNS behavior
- expected cross-segment reachability
- compatibility with services that still remain on `pve-test`

## Deliverables

- canary runbook
- defined validation commands
- success/failure criteria
- documented first canary target

## Candidate Canary Targets

Best lowest-risk options:

- disposable test LXC
- `apt-cacher-stack`

Avoid as first canaries:

- `harbor-stack`
- `authentik-stack`
- `proxy-stack`

## Validation Matrix

The canary should verify at least:

- container gets the intended IP address
- container gets the intended gateway
- container can reach the VLAN gateway
- container can resolve via the intended DNS path
- container can reach one expected dependency
- container does not require special-case routing surprises

## Files Likely Involved

- `terraform/lxc/network/pve.yaml`
- potentially a disposable stack definition or a chosen low-risk stack
- docs in this refactor directory

## Dependencies

- task 03 storage manifest
- task 04 network intent
- task 05 stack decoupling
- task 01 controls if production credentials are used during the validation

## Validation

- one target on `pve` works end-to-end on the intended VLAN path
- evidence is collected and documented
- any failures are categorized as host/network, manifest, or stack-level issues

## Risks

- choosing a canary that is too central or stateful
- validating only host reachability and not real service behavior
- skipping the canary and discovering network flaws during a real migration

## Suggested Branch

- `work/productionize-06-canary-validation`
