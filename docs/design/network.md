# Network Design

Settled network architecture for the proxmox-homelab. The decision-making history is in
`docs/design/archive/NetworkPlanning.md`.

## Model

Proxmox SDN **VLAN zones**. The MikroTik acts as the sole L3 gateway for all SDN zones.
Proxmox is a pure L2 switch — no routing, no NAT, no gateway IPs on the Proxmox host.

All inter-zone and internet-bound traffic flows through the MikroTik. Zone isolation is
enforced by MikroTik firewall ACLs, not by Proxmox. The Proxmox VNet firewall is available
for per-container inbound filtering but has a known cross-zone rule generation bug (see
[Known gaps](#known-gaps)).

## Zones

| Zone | Internal name | VLAN ID | Subnet | Gateway | Purpose |
|---|---|---|---|---|---|
| build_seg | `tvsegc` | 10 | `10.57.0.0/24` | `10.57.0.1` | CI runner — isolated build environment |
| mgmt_seg | `tvmgmt` | 20 | `10.57.1.0/24` | `10.57.1.1` | Management plane — Portainer, Authentik, step-ca, monitoring, CoreDNS |
| edge_seg | `tvedge` | 30 | `10.57.2.0/24` | `10.57.2.1` | Public ingress — Traefik only |
| infra_seg | `tvinfra` | 40 | `10.57.3.0/24` | `10.57.3.1` | Infrastructure services — Harbor, apt-cacher, NetBox |

Future zones (Phase 06+): `app_seg`, `game_seg`.

## Container IP allocation

| Container | Zone | IP | VMID | Phase |
|---|---|---|---|---|
| ci-runner-01 | `build_seg` | `10.57.0.63` | 141 | 01 |
| Portainer | `mgmt_seg` | `10.57.1.20` | 120 | 00b |
| Authentik | `mgmt_seg` | `10.57.1.10` | 150 | 04 |
| step-ca | `mgmt_seg` | `10.57.1.11` | 152 | 04 |
| Monitoring | `mgmt_seg` | `10.57.1.12` | 154 | 04 |
| CoreDNS | `mgmt_seg` | `10.57.1.13` | 151 | 04b |
| Traefik | `edge_seg` | `10.57.2.10` | 153 | 04 |
| Harbor | `infra_seg` | `10.57.3.10` | 121 | 03b |
| apt-cacher-ng | `infra_seg` | `10.57.3.11` | 142 | 03c |
| NetBox | `infra_seg` | `10.57.3.12` | 143 | 03b |

## Cross-zone traffic policy

Enforced at MikroTik. Defined in `terraform/lxc/network/pve-test.yaml`.

| From | To | Allowed | Purpose |
|---|---|---|---|
| All zones | `infra_seg` | tcp/80, 443, 3142 | Harbor image pulls, apt-cacher apt proxy |
| `edge_seg` | `mgmt_seg` | tcp/9000 | Traefik → Authentik forward-auth |
| `mgmt_seg` | `edge_seg` | tcp/80 | step-ca ACME httpChallenge callback |
| `build_seg` | `infra_seg` | tcp/80, 443 | CI runner → Harbor, apt-cacher |
| `build_seg` | Internet | tcp/443 (GitHub, package registries only) | CI runner outbound (SEC-01) |
| All other cross-zone | — | Deny | Default deny east-west |

**Note:** MikroTik ACL rules are currently applied manually. There is no IaC for MikroTik
configuration (TM-09). A full pve-test rebuild requires manual MikroTik reconfiguration.

## DNS

Two-tier model:

1. **MikroTik** (`10.57.x.1` on each zone) is the DNS entry point for all SDN clients.
   Each zone's gateway IP is the resolver that containers use. The MikroTik handles public
   name resolution and conditionally forwards the internal zone.

2. **CoreDNS** (`10.57.1.13`) holds authority for `lab.gibbsgreatly.xyz`. MikroTik
   conditionally forwards queries matching `lab.gibbsgreatly.xyz` to CoreDNS via a FWD
   rule. All other queries are resolved by MikroTik directly (public DNS via DoH upstream).

### Name spaces

| Namespace | Resolver | Used for |
|---|---|---|
| `gibbsgreatly.xyz` | Cloudflare public DNS | Public ingress — browser-facing Traefik routes |
| `lab.gibbsgreatly.xyz` | CoreDNS (authoritative) | Internal platform identity — service-to-service, managed host access |

### DNS configuration per LXC

Each LXC's `/etc/resolv.conf` points to its zone's MikroTik gateway IP:

| Zone | DNS server in resolv.conf |
|---|---|
| `build_seg` | `10.57.0.1` |
| `mgmt_seg` | `10.57.1.1` |
| `edge_seg` | `10.57.2.1` |
| `infra_seg` | `10.57.3.1` |

The `lxc_base` Ansible role writes the correct resolver based on the `dns_server` variable
in each stack's `stack.yaml`. All `stack.yaml` files must set `dns_server` explicitly — do
not rely on the LXC template default.

## TLS

Dual-resolver model in Traefik:

| Resolver | CA | Challenge | Used for |
|---|---|---|---|
| `letsencrypt` | Let's Encrypt | DNS-01 via Cloudflare | All browser-facing routes — wildcard `*.gibbsgreatly.xyz` |
| `step-ca` | Homelab internal CA | ACME httpChallenge | Internal management plane, service-to-service |

The homelab root CA (`certs/homelab-root.crt`) is distributed only to managed service hosts.
It is never distributed to browsers or end-user devices. Browser connections always use
Let's Encrypt certs.

**Dev passes use LE staging CA.** Switch to production only when promoting to `pve`.
The staging issuer shows `(STAGING) Let's Encrypt` in browsers — this is expected.

## Known gaps

| Gap | Ref | Description |
|---|---|---|
| MikroTik has no IaC | TM-09 | All ACL rules, VLAN config, and DNS forwarding rules are applied manually. A pve-test rebuild requires manual MikroTik reconfiguration. |
| VNet firewall cross-zone rule bug | — | `vnet_policy_candidates` in `terraform/lxc/main.tf:86-95` requires both `from` and `to` to match the current container's VNet, making cross-zone ACCEPT rules impossible to generate. Proxmox VNet firewall is disabled for dev passes. |
| SDN VLAN zone Terraform support | — | `configure-network-sdn-vnet.yml` handles Simple zones only. VLAN zones are applied by `ansible/00-initial-setup/proxmox-sdn-setup.yml` until this is fixed. |
| `dns_server` contract coverage | — | Explicit `dns_server` is now set in stack metadata and validated from generated inventories; future stacks should continue to use the zone or bridge gateway explicitly. |
