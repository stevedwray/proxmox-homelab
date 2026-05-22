# Task 05: Stack Target Decoupling

## Goal

Remove embedded `pve-test` target pins from the active platform stacks so they
can follow the selected environment instead of a hardcoded node.

## Objective

Make the stack catalog describe service intent, not environment lock-in.

## Current Status

The branch-local implementation work for this task appears substantially in
place after the network-refactor merge-forward:

- active platform `stack.yaml` files no longer appear to carry
  `proxmox_node: pve-test`
- target selection is now expected to flow through environment overlays and the
  selected `network/<proxmox_node>.yaml` and `storage/<proxmox_node>.yaml`

Treat this task as a closeout verification step unless new evidence shows an
active stack still embeds `pve-test` targeting.

## Deliverables

- active platform stacks no longer require `proxmox_node: pve-test`
- target resolution is driven by environment selection and manifests
- docs clearly describe how a stack is aimed at `pve-test` vs `pve`

## Active Stacks In Scope

- `authentik-stack`
- `step-ca-stack`
- `monitoring-stack`
- `dns-stack`
- `portainer-stack`
- `proxy-stack`
- `harbor-stack`
- `apt-cacher-stack`
- `netbox-stack`
- `ci-runner-01`

## Design Rule

Keep in the stack file:

- VMID
- sizing
- service role
- network zone

Move out of the stack file:

- environment-specific target node assumptions

Target selection after this task:

- wrappers and env overlays set `TF_VAR_proxmox_node`
- Terraform resolves `storage/<proxmox_node>.yaml` and `network/<proxmox_node>.yaml`
- the same active stack definition should render against either `pve-test` or `pve`

## Files Likely Involved

- `terraform/lxc/stacks/*/stack.yaml`
- [terraform/lxc/main.tf](/home/steve/git/proxmox-homelab/terraform/lxc/main.tf:1)
- related docs under `docs/productionize-refactor/`

## Dependencies

- task 02 environment model
- task 04 network intent should be close enough to final shape before broad
  retargeting

## Validation

- inventories still render correctly for `pve-test`
- inventories can render correctly for `pve`
- no stack loses required network zone information
- no stack ends up ambiguously targeted

## Risks

- removing pins too early before good env guardrails exist
- silently changing behavior for existing `pve-test` workflows
- missing secondary docs or scripts that still assume embedded `pve-test`

## Suggested Branch

- `work/productionize-05-stack-decoupling`
