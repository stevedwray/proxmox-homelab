# Current State — MikroTik DHCP and IPv6 Baseline

This is the durable baseline the DHCP refactor must account for. It is sourced
from [router/README.md](../../router/README.md) and
[router/desired-config.md](../../router/desired-config.md), both refreshed
against the live hAP ax3 on 2026-07-03.

## Summary

- The MikroTik hAP ax3 is the active DHCP server for the default LAN on
  `bridgeLocal`.
- The platform SDN VLANs used by Proxmox containers are statically addressed;
  they do not currently use DHCP at all.
- IPv6 on the LAN already depends on RouterOS obtaining delegated space from
  the ISP and advertising it locally.
- DNS and DHCP are coupled today only at the client-LAN edge, not inside the
  Proxmox SDN container environment.

## IPv4 DHCP

| Field | Current value |
|---|---|
| DHCP server | `lan` |
| Interface | `bridgeLocal` |
| Subnet | `192.168.1.0/24` |
| Gateway | `192.168.1.1` |
| Pool | `192.168.1.100` - `192.168.1.200` |
| Lease time | `30m` |
| Static leases | 5 known + 1 unlabeled device noted in router docs |

Known static leases documented in `router/desired-config.md`:

| Host | Address | Notes |
|---|---|---|
| `argon-01` | `192.168.1.22` | Pi-hole primary |
| `argon-02` | `192.168.1.23` | Pi-hole secondary |
| `garuda` | `192.168.1.104` | workstation |
| `RBR350` | `192.168.1.110` | network device |
| unlabeled device | `192.168.1.28` | still needs identification / labeling |

## What currently gets DHCP

The current DHCP population is primarily the flat LAN:

- wired LAN clients on `bridgeLocal`
- WiFi clients bridged into `bridgeLocal`
- devices that have not yet been segmented into dedicated VLANs

This matches the current operator expectation: most DHCP-managed devices are
still on the default LAN today, but this is expected to change as WiFi / IoT /
other client classes move toward their own VLANs.

## SDN VLANs and the non-DHCP platform

These VLANs already exist on the MikroTik and in the Proxmox design:

| VLAN | Subnet | Current address model |
|---|---|---|
| `build_seg` | `192.168.10.0/24` | static Terraform-managed |
| `mgmt_seg` | `192.168.20.0/24` | static Terraform-managed |
| `edge_seg` | `192.168.30.0/24` | static Terraform-managed |
| `infra_seg` | `192.168.40.0/24` | static Terraform-managed |

Important constraint: the DHCP refactor should not assume these existing
container VLANs need DHCP. The first DHCP migration target is the client LAN
side, not the platform stack addressing model.

## IPv6

The live router docs show that IPv6 today is already a layered RouterOS
responsibility, not just a DHCP toggle:

| Function | Current owner |
|---|---|
| upstream IPv6 acquisition | MikroTik DHCPv6-PD client on `vlan1-wan` |
| delegated prefix pool | MikroTik `default-pool` |
| LAN prefix assignment | MikroTik `from-pool` on `bridgeLocal` |
| router advertisement | MikroTik ND / RA on `bridgeLocal` |
| advertised DNS | MikroTik RA advertises Pi-hole ULA DNS addresses |
| DHCPv6 server | MikroTik `LANIPv6DHCP` on `bridgeLocal` |

Current IPv6 details called out in `router/desired-config.md`:

- ISP-facing DHCPv6-PD client requests address + prefix on `vlan1-wan`
- delegated /56 feeds `default-pool`
- LAN uses a /64 from that pool on `bridgeLocal`
- ND on `bridgeLocal` has `advertise-dns=yes`
- RA DNS points at Pi-hole ULAs: `fd00::22`, `fd00::23`
- Router also has `fd00::1/64` on `bridgeLocal`

## Why IPv6 needs explicit investigation

The refactor cannot assume "Technitium replaces MikroTik DHCP" means the same
thing for IPv6 as for IPv4.

Open uncertainties include:

- whether client IPv6 addressing is primarily SLAAC + RA, DHCPv6, or a mix
- whether Technitium can or should replace RouterOS for DHCPv6 duties
- whether RouterOS must remain the RA / prefix-delegation owner even if
  Technitium takes over IPv4 DHCP
- whether advertised DNS should stay pinned to stable ULA targets during any
  migration

## Initial implications for planning

- IPv4 DHCP migration can likely be staged independently.
- IPv6 should be investigated before any "single cutover" story is written.
- Future client VLANs should be planned with DHCP scope ownership from the
  start rather than retrofitted after segmentation.
- MikroTik may remain in the path as a relay and/or as the IPv6 control point
  even if Technitium becomes the main IPv4 DHCP server.
