# Current State — MikroTik DHCP and IPv6 Baseline

This is the durable baseline the DHCP refactor must account for. It is sourced
from [router/README.md](../../router/README.md),
[router/desired-config.md](../../router/desired-config.md), and the live REST
scrape at [router/config/current-config.json](../../router/config/current-config.json),
all refreshed against the hAP ax3 on 2026-07-03.

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
| Static leases | 5 total (4 named + 1 previously unlabeled, since identified as `raspberrypi` — see "Live scrape detail" below) |

Known static leases documented in `router/desired-config.md`:

| Host | Address | Notes |
|---|---|---|
| `argon-01` | `192.168.1.22` | Pi-hole primary |
| `argon-02` | `192.168.1.23` | Pi-hole secondary |
| `garuda` | `192.168.1.104` | workstation |
| `RBR350` | `192.168.1.110` | network device |
| `raspberrypi` | `192.168.1.28` | previously unlabeled in router docs; identified via live lease scrape (see "Live scrape detail" below) — still not labeled with a hostname/comment on the router itself |

## What currently gets DHCP

The current DHCP population is primarily the flat LAN:

- wired LAN clients on `bridgeLocal`
- WiFi clients bridged into `bridgeLocal`
- devices that have not yet been segmented into dedicated VLANs

This matches the current operator expectation: most DHCP-managed devices are
still on the default LAN today, but this is expected to change as WiFi / IoT /
other client classes move toward their own VLANs.

### Live lease population captured in the 2026-07-03 scrape

Static leases (5):

| Host | Address | Status at scrape |
|---|---|---|
| `argon-01` | `192.168.1.22` | `bound` |
| `argon-02` | `192.168.1.23` | `bound` |
| `garuda` | `192.168.1.104` | `bound` |
| `RBR350` | `192.168.1.110` | `waiting` |
| `raspberrypi` | `192.168.1.28` | `bound` |

Dynamic leases (8):

| Host | Address |
|---|---|
| `HarmonyHub` | `192.168.1.106` |
| `iPhone` | `192.168.1.114` |
| `Stephen-s-A56` | `192.168.1.108` |
| `RV30_Max_Plus` | `192.168.1.177` |
| `BolorErlsiPhone` | `192.168.1.103` |
| `deb13` | `192.168.1.100` |
| `LM-GM17D7CY` | `192.168.1.102` |
| `Compute` | `192.168.1.101` |

Practical implication: Stage D's "dynamic-lease policy" work is not abstract;
it is specifically reviewing these 8 devices to decide whether any should be
promoted into the reservation set before the real cutover.

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

## Confirmed Technitium DHCP capability (2026-07-05 research)

Recorded in full, with rationale, in [decisions.md](./decisions.md) (Decisions
1–2). Summary of the facts that settled those decisions:

- **No DHCPv6 support in Technitium today.** Open upstream feature request
  ([DnsServer#265](https://github.com/TechnitiumSoftware/DnsServer/issues/265)),
  "planned for a later major release." This removes any ambiguity about
  IPv6 scope for this workspace: RouterOS keeps 100% of RA/PD/DHCPv6 for as
  long as this holds.
- **IPv4 DHCP relay is supported and is the standard mechanism** for serving
  multiple networks from one Technitium instance — scopes are matched to a
  relayed request by the relay's `giaddr`, the same standard mechanism every
  DHCP relay implementation uses. This fits `technitium-stack`'s existing
  placement on `mgmt_seg` (routed, not on any client L2 segment).
- **Direct (non-relayed) broadcast DHCP from the existing container is not a
  good fit.** Technitium's Docker image needs `network_mode: host` or a
  macvlan interface to receive L2 broadcast traffic directly, both of which
  are a deployment-shape departure from `technitium-stack`'s current bridge
  networking and every other platform-tier stack in this repo. Relay avoids
  that entirely.
- **Reservations/static leases are supported per-scope via the REST API**;
  no built-in bulk MikroTik-lease import tool exists upstream, but
  third-party scripts already do CSV-based reservation import against the
  API, confirming the API shape is workable for a migration script.

## Live scrape detail not previously captured

From `router/config/current-config.json` (scraped 2026-07-03, still the
current baseline as of this review):

- The `lan` DHCP network object hands out DNS via its `dns-server` field
  (`192.168.1.22`, the primary Pi-hole) — **not** via a generic
  `dhcp-option` entry; the network's `dhcp-option` field is empty. This
  question is now settled, not open: decisions.md's Decision 3 keeps
  DHCP-assigned DNS pointed at the Pi-holes rather than switching it to
  Technitium — these are functionally different resolvers today, not
  interchangeable, and this doc previously (incorrectly) described that
  choice as still pending.
- `dynamic-lease-identifiers: client-mac,client-id` is set on the `lan`
  server — relevant if Technitium's dynamic lease matching needs an
  equivalent setting to avoid duplicate leases for the same client.
- Lease data confirms the "unlabeled device" from `desired-config.md` is
  reachable and fingerprints as `host-name: raspberrypi` (`192.168.1.28`,
  MAC `88:A2:9E:57:E6:24`) — still not identified/labeled on the router
  itself, but no longer a total unknown.
