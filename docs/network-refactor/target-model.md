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

The intended administrative path for `pve-test` is:

1. operator workstation on LAN `192.168.1.0/24`
2. MikroTik routes to the destination VLAN subnet
3. guest answers directly on its assigned `10.57.x.x` address

Implications:

1. generated Ansible inventories for SDN-backed guests should target the guest
   IP directly
2. direct SSH from the workstation is the default success path to prove
3. `ProxyJump` through Proxmox is a temporary compatibility exception only
4. any future bastion design should be explicit and separate from Proxmox

## Subnet Reachability Expectations

Approved admin clients should be able to reach these guest subnets via the
router:

1. `build_seg` at `10.57.0.0/24`
2. `mgmt_seg` at `10.57.1.0/24`
3. `edge_seg` at `10.57.2.0/24`
4. `infra_seg` at `10.57.3.0/24`

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

## Migration Principles

1. Prefer direct-SSH proof before removing compatibility shims.
2. Remove `prime_sdn_host_route` only after the router path is verified.
3. Make exceptions explicit, time-bounded, and easy to delete.
4. Keep `pve-test` as the proving ground before reusing the pattern on `pve`.

## Evidence Requirements

To claim the target model is working for a stack, capture:

1. route reachability from the workstation to the guest IP
2. successful SSH without `ProxyJump`
3. guest-side DNS success via the zone gateway
4. service health appropriate to that stack type
