# Inventory Model

## Direction

The shared inventory model should evolve from `stack.yaml`, not replace it immediately.

The goal is a higher-level stack contract that can drive:

- Terraform inputs
- Ansible inventory and variables
- generated publish artifacts
- validation metadata

## Source Of Truth Guidance

### Source Of Truth Inputs

- stack identity
- sizing and storage intent
- network attachment intent
- dependencies
- service profile
- validation profile
- maintenance policy

### Derived Artifacts

- Terraform vars or rendered inputs
- Ansible inventory
- Ansible vars artifacts
- generated DNS or ingress publish files
- rendered Proxmox-side network/firewall vars

Derived artifacts should not be hand-edited.

## Early Schema Themes

The shared contract will likely need sections for:

- `identity`
- `infrastructure`
- `network`
- `services`
- `maintenance`
- `validation`
- `integrations`

## Open Design Questions

- what remains per-stack vs environment-level
- what belongs in shared network intent rather than per-stack config
- how non-secret vars should be layered
- how to represent special-case behavior without overcomplicating the base schema
