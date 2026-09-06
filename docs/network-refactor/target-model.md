# Network Refactor Target Model

## Purpose

This document states the target access and provisioning model that the
refactor should implement. Future sessions should treat this as the default
contract and only deviate if live evidence forces a correction.

## Core Network Contract

1. The MikroTik is the sole L3 gateway for every SDN VLAN subnet.
2. Proxmox provides VLAN-aware L2 switching only.
3. Proxmox hosts do not carry subnet-local `.254` gateway-style addresses on
   SDN VNets as part of the normal operating model.
4. Inter-zone routing and east-west policy are enforced at the MikroTik.
5. SDN guest workloads should be reachable from approved admin clients through
   the routed VLAN design, not by using Proxmox as a default jump host.

Reference architecture:

- [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)
- [docs/reference/sdn-segment-routing.md](/home/steve/git/proxmox-homelab/docs/reference/sdn-segment-routing.md:1)

## Administrative Access Contract

The intended administrative path for `pve-test-vm` is:

1. operator workstation on LAN `192.168.1.0/24`
2. MikroTik routes to the destination VLAN subnet
3. guest answers directly on its assigned zone IP, currently
   `192.168.<vlan-id>.x` on `pve-test-vm`

Implications:

1. generated Ansible inventories for SDN-backed guests should target the guest
   IP directly
2. direct SSH from the workstation is the default success path to prove
3. Proxmox is not the Ansible automation origin in the target model
4. `ProxyJump` through Proxmox is a temporary compatibility exception only
5. any future bastion design should be explicit and separate from Proxmox

## Subnet Reachability Expectations

The operator workstation on LAN `192.168.1.0/24` is the approved admin source
for SSH, Ansible automation, and service validation. It must be able to reach
these guest subnets through the MikroTik:

1. `build_seg` at `192.168.10.0/24` (gateway `192.168.10.1`, VLAN 10)
2. `mgmt_seg` at `192.168.20.0/24` (gateway `192.168.20.1`, VLAN 20)
3. `edge_seg` at `192.168.30.0/24` (gateway `192.168.30.1`, VLAN 30)
4. `infra_seg` at `192.168.40.0/24` (gateway `192.168.40.1`, VLAN 40)

This does not imply all application ports are open from LAN. It does mean the
network path exists, and selective SSH or validation traffic can be allowed by
policy.

## DNS Contract

1. Each SDN-attached LXC uses its zone gateway on MikroTik as its resolver.
2. `lab.gibbsgreatly.xyz` is delegated behind MikroTik to internal authority.
3. DNS validation must prove the guest sees working resolution through the zone
   gateway path, not just that a public resolver works.

## Current Manual Prerequisites

These remain out of band for now and must be present before direct-SSH
provisioning is considered valid:

1. MikroTik VLAN interfaces for each SDN zone
2. MikroTik gateway IPs for each zone
3. MikroTik DNS behavior for public lookups and delegated internal names
4. MikroTik firewall rules that allow the expected admin and cross-zone traffic

Specific RouterOS commands for items 1–2 and DNS baseline setup are documented
in `terraform/lxc/network/pve-test-vm.yaml` under the "MikroTik one-time setup"
header. That file is the authoritative reference for what must be done manually
before a `pve-test-vm` direct-SSH provisioning pass.

## Temporary Exceptions

The following patterns are active in the repo today but are not part of the
target model. Neither should be extended to new stacks.

| Exception | Location | Retirement condition |
|---|---|---|
| `ProxyJump=root@<pve_host>` | `terraform/lxc/templates/inventory.tpl` | Remove once direct SSH from the workstation is validated end-to-end on `pve-test-vm` |

`ProxyJump` is the accepted temporary escape hatch during migration. It must
remain explicitly labeled and must be removed before the validation gate passes.

`prime_sdn_host_route` has been removed in Session 5. The target model no
longer treats host-side route priming as a supported compatibility path.

For the exact current call chain, trigger conditions, and short-term control
knobs behind these exceptions, use
[implementation-inventory.md](/home/steve/git/proxmox-homelab/docs/network-refactor/implementation-inventory.md:1).

## Migration Principles

1. Prefer direct-SSH proof before removing compatibility shims.
2. Do not reintroduce host-side route priming as a compatibility path.
3. Make exceptions explicit, time-bounded, and easy to delete.
4. Keep `pve-test-vm` as the proving ground before reusing the pattern on `pve`.

## Evidence Requirements

To claim the target model is working for a stack, capture:

1. route reachability from the workstation to the guest IP
2. successful SSH without `ProxyJump`
3. guest-side DNS success via the zone gateway
4. service health appropriate to that stack type

## Non-Goals

These are explicitly out of scope for this refactor:

1. Proxmox acting as a routing or NAT transit point for any SDN subnet.
2. Host-side `.254` bridge addresses as a permanent provisioning pattern.
3. A dedicated bastion host (deferred to a future phase; workstation is the
   origin for now).
4. MikroTik IaC automation (tracked separately as TM-09; MikroTik configuration
   remains manual for this refactor).
5. Any production (`pve`) environment changes before `pve-test-vm` validation is
   complete and the teardown gate is passed.
