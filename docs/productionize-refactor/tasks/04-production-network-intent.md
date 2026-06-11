# Task 04: Production Network Intent

## Goal

Rewrite `terraform/lxc/network/pve.yaml` so production uses the same logical
VLAN-zone model as the active platform design.

## Objective

Replace the legacy/simple-zone production intent with a production manifest that
matches:

- `build_seg`
- `mgmt_seg`
- `edge_seg`
- `infra_seg`

and binds those zones to `vmbr0` VLAN-backed SDN attachments.

## Assumptions

- switch and host VLAN work on `vmbr0` are being handled outside this repo
- those changes must still be validated early

## Deliverables

- rewritten `terraform/lxc/network/pve.yaml`
- documented production VLAN IDs, subnets, gateways, and aliases
- explicit note of any router ACL or DNS-forwarding prerequisites

## Design Questions

- does production keep the current segmented address plan or adopt a variant
- how closely should production mirror `pve-test` naming and CIDRs
- what should the production DNS and gateway values be for each zone

## Files Likely Involved

- [terraform/lxc/network/pve.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve.yaml:1)
- [terraform/lxc/network/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve-test.yaml:1)
- [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)

## Dependencies

- task 02 for production variable model
- task 03 only loosely; storage and network can largely proceed in parallel

## Validation

- zones used by active stacks exist in the manifest
- manifest resolves through Terraform templating without missing variables
- attachment and gateway semantics match the intended production topology

## Risks

- introducing a second long-term network model
- mismatching zone names used by stack YAML files
- assuming router policy exists when it does not

## Suggested Branch

- `work/productionize-04-network-intent`
