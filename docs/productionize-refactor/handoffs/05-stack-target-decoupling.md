# Handoff 05: Stack Target Decoupling

## Objective

Remove `pve-test` hardcoding from the active platform stack definitions so the
environment can choose the target node.

## Branch

- `work/productionize-05-stack-decoupling`

## Primary Source

- [Task 05: Stack Target Decoupling](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/05-stack-target-decoupling.md:1)

## Scope

In scope:

- active platform stack YAML cleanup
- target-selection documentation updates

Out of scope:

- production credential controls
- production storage manifest creation
- production network intent rewrite

## Files To Read First

- [docs/productionize-refactor/tasks/05-stack-target-decoupling.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/05-stack-target-decoupling.md:1)
- [terraform/lxc/main.tf](/home/steve/git/proxmox-homelab/terraform/lxc/main.tf:1)
- active stack YAML files under `terraform/lxc/stacks/`

## Files Most Likely To Change

- `terraform/lxc/stacks/*/stack.yaml`
- productionize docs if the target-selection rules need clarification

## Constraints

- keep service intent in the stack files
- remove environment lock-in, not useful metadata
- do not silently break `pve-test`

## Done When

- active platform stacks are no longer hardcoded to `pve-test`
- docs explain how the environment now determines the target

## Target Selection Rule

- `./with-secrets` remains the default-safe wrapper and sets the development target
- `./with-secrets-prod` sets the production target under its existing approval controls
- active stacks should not pin `proxmox_node`; shared Terraform resolves storage and network manifests from the selected environment

## Validation

- stack metadata still renders correctly
- network zone metadata is preserved
- the change does not depend on guessing hidden environment behavior

## Suggested Copilot Brief

```text
Work on Task 05 in docs/productionize-refactor/tasks/05-stack-target-decoupling.md.
Remove the active platform stacks' hardcoded pve-test node pins so environment selection can choose pve-test or pve.
Preserve VMIDs, sizing, and network zone intent.
Do not broaden the work into storage or network manifest design.
Document the new target-selection behavior clearly.
```
