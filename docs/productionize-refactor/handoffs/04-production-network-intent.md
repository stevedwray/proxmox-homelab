# Handoff 04: Production Network Intent

## Objective

Rewrite the production network intent so `pve` matches the active VLAN-zone
design.

## Branch

- `work/productionize-04-network-intent`

## Primary Source

- [Task 04: Production Network Intent](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/04-production-network-intent.md:1)

## Scope

In scope:

- rewrite `terraform/lxc/network/pve.yaml`
- align production zone names with active stack usage
- document required production VLAN and gateway semantics

Out of scope:

- service migration
- credential-control changes
- large Terraform code changes unless the manifest requires minor support edits

## Files To Read First

- [terraform/lxc/network/pve.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve.yaml:1)
- [terraform/lxc/network/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve-test.yaml:1)
- [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)
- [docs/productionize-refactor/tasks/04-production-network-intent.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/04-production-network-intent.md:1)

## Files Most Likely To Change

- `terraform/lxc/network/pve.yaml`
- productionize docs if assumptions need clarifying

## Constraints

- use `vmbr0`
- follow the active logical model: `build_seg`, `mgmt_seg`, `edge_seg`,
  `infra_seg`
- keep host/switch VLAN work as an external prerequisite, but make validation
  needs explicit

## Done When

- `pve.yaml` uses the active zone model instead of the legacy simple-zone model
- production attachments and gateways are coherent
- the doc set makes it clear what still depends on router and VLAN readiness

## Validation

- manifest zone names match current stack expectations
- manifest shape matches current network-intent consumption in Terraform

## Suggested Copilot Brief

```text
Work on Task 04 in docs/productionize-refactor/tasks/04-production-network-intent.md.
Rewrite terraform/lxc/network/pve.yaml to match the active VLAN-zone design used by the platform stacks.
Use vmbr0 as the production trunk path.
Do not expand into service migration or credential controls.
Keep the assumptions and remaining prerequisites explicit in the docs.
```
