# DHCP Refactor — MikroTik to Technitium Planning

## Purpose

Plan the future migration of DHCP responsibilities away from the MikroTik and
toward Technitium, while preserving the current working LAN and accounting for
the likely move to a more VLAN-centric client network.

This workspace is intentionally separate from `docs/dns-refactor/`. The DNS
cutover is complete; DHCP migration is a distinct router, client, and IPv6
validation surface.

## Status

Planning opened on 2026-07-05.

Current understanding:

- IPv4 DHCP today is primarily on the flat LAN `bridgeLocal`
  (`192.168.1.0/24`) on the MikroTik.
- Most DHCP clients are still on the default LAN / default VLAN.
- The network direction is toward more client VLANs over time, including
  separate WiFi / IoT segmentation.
- IPv6 is not a simple "replace DHCP with Technitium" problem:
  RouterOS currently receives IPv6 delegation directly from the ISP and is
  already handling router advertisement and DHCPv6-related functions on the
  LAN.

That means this workspace must treat IPv4 DHCP migration and IPv6 behavior as
related but not identical problems.

## Workspace layout

This follows the repo-wide pattern in
[docs/workflow/documentation-workspaces.md](../workflow/documentation-workspaces.md):

| File | Purpose |
|---|---|
| `README.md` | entry point, scope, reading order |
| `current-state.md` | durable baseline of live MikroTik DHCP and IPv6 handling |
| `plan.md` | phased migration and investigation plan |
| `artifacts/` | local-only, git-ignored scratch notes, command output, evidence |

## Read these first

1. This file
2. [current-state.md](./current-state.md)
3. [plan.md](./plan.md)
4. [router/README.md](../../router/README.md)
5. [router/desired-config.md](../../router/desired-config.md)
6. [docs/design/network.md](../design/network.md)
7. [docs/dns-refactor/decisions.md](../dns-refactor/decisions.md)

## Scope

In scope:

- inventory the current MikroTik IPv4 DHCP setup
- inventory the current MikroTik IPv6 RA / DHCPv6-PD / DHCPv6 behavior
- define how Technitium could take over IPv4 DHCP
- define how future client VLANs should obtain DHCP
- decide what should stay on MikroTik versus move to Technitium
- design safe cutover and rollback procedures

Out of scope for the first planning pass:

- immediate production router mutation
- replacing IPv6 behavior before its current model is fully understood
- changing SDN container addressing, which remains static and Terraform-owned

## Closeout target

This workspace is complete when it produces:

- a verified current-state baseline
- a clear target architecture for IPv4 DHCP and client VLAN growth
- an explicit decision on IPv6 ownership boundaries
- a staged execution plan with rollback points
