# Network Refactor

## Purpose

This directory is the planning and execution home for the network/provisioning
refactor that follows the preserved `refactor/productionize` checkpoint.

The immediate goal is not new service rollout. It is to correct the networking
and provisioning model so SDN-backed guests are reached and managed in the way
the platform actually intends:

- routed by the main router at L3
- not implicitly dependent on Proxmox acting as a jump host
- not dependent on ad hoc host-side route priming as a long-term design

## Why This Exists

The productionizing work proved that:

1. production env/storage/network parameterization is viable
2. `apt-cacher-stack` is a good first production canary candidate
3. the current Terraform/Ansible provisioning path assumes `ProxyJump` through
   the Proxmox host for SDN-backed guests
4. that assumption does not match the intended network design

See the preserved checkpoint:

- [checkpoint.md](/home/steve/git/proxmox-homelab/docs/network-refactor/checkpoint.md:1)

## Outcomes We Want

1. Operator workstations and approved clients reach guest subnets through the
   intended routed VLAN design.
2. Terraform-generated inventories do not need Proxmox to act as a general
   jump host for SDN-backed stack provisioning.
3. `prime_sdn_host_route` has been removed; only `ProxyJump` remains as an
   explicitly temporary compatibility shim.
4. The corrected model is validated on `pve-test` with at least one teardown +
   redeploy cycle before production canary progression resumes.

## Working Documents

- main planning doc:
  [plan.md](/home/steve/git/proxmox-homelab/docs/network-refactor/plan.md:1)
- target model:
  [target-model.md](/home/steve/git/proxmox-homelab/docs/network-refactor/target-model.md:1)
- migration mechanics decisions:
   [migration-mechanics.md](/home/steve/git/proxmox-homelab/docs/network-refactor/migration-mechanics.md:1)
- teardown validation gate:
  [validation-gate.md](/home/steve/git/proxmox-homelab/docs/network-refactor/validation-gate.md:1)
- session handoff:
  [handoff.md](/home/steve/git/proxmox-homelab/docs/network-refactor/handoff.md:1)

Add focused task docs under this directory as the plan becomes more concrete.
