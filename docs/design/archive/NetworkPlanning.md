# Network Planning

> **Decision (2026):** The implemented network model is **Option 2 (Proxmox SDN)**
> using **VLAN zones** (not Simple zones). The MikroTik router owns all gateway IPs
> and performs all L3 routing between zones. Proxmox is a pure L2 switch with no
> routing or SNAT. See `terraform/lxc/network/pve-test.yaml` and
> `docs/reference/sdn-segment-routing.md` for the implemented zone layout.
> DNS follows the same boundary: each SDN zone should use the MikroTik on its
> zone-local gateway IP as the resolver entry point. For example, `mgmt_seg`
> clients use `10.57.1.1`, which serves split DNS for `gibbsgreatly.xyz` and
> forwards public lookups via DoH.

Decision refinement (2026-04-18): DNS is split by responsibility. The MikroTik
remains the resolver entry point for all SDN clients using zone gateway IPs.
Internal platform service authority is delegated to `lab.gibbsgreatly.xyz` on a
dedicated internal DNS server via conditional forwarding. Public ingress names
remain under `gibbsgreatly.xyz`.

## What the network stage is trying to achieve

This stage is not mainly about “making VLANs.” It is about creating a **stable network contract** that your current and future LXCs/VMs can sit on top of, while Proxmox remains the control point for segmentation. Proxmox VE gives you the pieces for this through VLAN-aware Linux bridges, the integrated firewall, cluster-level security groups, and SDN constructs such as zones, VNets, and subnets. ([Proxmox Virtual Environment][1])

The outputs of the network stage should be:

* named zones for workload classes
* explicit allowed paths between zones
* a migration path from the current flat-ish layout to the new one
* a design that dev can mirror at smaller scale
* minimal need to move or redesign existing data storage just to improve security

## Principles for your network stage

I’d set these rules first:

* **Preserve service placement assumptions where possible.** Do not redesign storage or app mount structure just to fit a new network.
* **Default deny east-west traffic.** Allow only the flows a service actually needs.
* **Internet exposure only through an edge tier.**
* **Management plane stays separate from app traffic.**
* **Preserve DNS role separation.** Keep MikroTik as the client resolver entry point,
  delegate internal platform authority to `lab.gibbsgreatly.xyz`, and keep public ingress
  names under `gibbsgreatly.xyz`.
* **Dev mirrors the logical network shape of prod, but with fewer guests and smaller address ranges.**

That fits well with Proxmox’s model, because you can apply filtering at datacenter, node, VM, and container level, and re-use common rules via security groups. ([Proxmox Virtual Environment][2])

---

# The network-stage outline

## Stage N1 — Discovery and traffic inventory

Before changing anything, document:

* current bridges and VLAN usage
* current subnets
* which LXCs/VMs talk to what
* which services are public, internal-only, or admin-only
* which services need storage access, DNS, auth, monitoring, backup, or internet egress

This becomes the **network contract inventory** for migration. In practice, the point is to avoid breaking existing workloads that already map cleanly to your ZFS-backed service layout.

### Deliverables

* current-state network diagram
* dependency table per service
* proposed zone membership per service
* list of “must preserve” IPs/DNS names if any

## Stage N2 — Define the zone model

Create the logical zones first, even if they are not all separate VLANs on day one.

My suggested target zones:

* **mgmt** — Proxmox UI/API, PBS, NetBox, Harbor, CI runner, Authentik, step-ca
* **internal-apps** — Jellyfin, arr stack, internal dashboards, utility apps
* **public-edge** — reverse proxy only
* **game-services** — Minecraft and other game servers
* **security-lab** — Security Onion, scanners, Wazuh, related tooling
* **client-admin / VPN** — trusted operator access path
* **storage-backup** — optional dedicated backup/storage network if justified

This matches how Proxmox SDN separates networking with zones, VNets, and subnets, while the firewall gives you the enforcement layer. ([Proxmox Virtual Environment][1])

### DNS authority model

* Public ingress hostnames stay under `gibbsgreatly.xyz`.
* Internal shared-platform hostnames use `lab.gibbsgreatly.xyz`.
* SDN clients keep using zone-local MikroTik gateway IPs for DNS.
* MikroTik conditionally forwards `lab.gibbsgreatly.xyz` to an internal DNS server authoritative for that zone.
* Internal zone hostnames are for platform identity and service-to-service usage, not default public browser entry.

### Deliverables

* zone list
* allowed-flow matrix
* initial IP plan
* DNS naming convention

## Stage N3 — Pick the implementation pattern

This is where the main design choice happens. There are three good options.

---

# Option 1 — Simple VLAN-aware bridge model

## What it is

Use a **single VLAN-aware Proxmox bridge** on the host uplink, then attach each VM/LXC NIC with the appropriate VLAN tag. Proxmox documents VLAN awareness on Linux bridges specifically for this style, where guests are attached to one bridge and assigned tags individually. ([Proxmox Virtual Environment][3])

## Shape

* one main trunk bridge on Proxmox
* VLANs for mgmt, apps, edge, games, security
* routing/firewalling done by your router/firewall and/or Proxmox guest firewalls
* no heavy SDN dependency at first

## Why it fits you

* closest to traditional homelab practice
* easiest to reason about
* easiest to map onto existing services
* easiest migration path from a flatter current network
* dev can mirror this very easily

## Downsides

* less elegant for fully code-defined virtual networking inside Proxmox
* policy may end up split between router/firewall and Proxmox
* more manual coordination if many VLANs evolve over time

## Best fit

This is the **best low-risk starting option** if you want to move carefully and preserve what already works.

### Rollout plan

1. Define VLAN IDs and subnets.
2. Make the Proxmox bridge VLAN-aware.
3. Assign a test LXC/VM to each target zone.
4. Apply Proxmox firewall rules/security groups.
5. Migrate existing services zone by zone.

---

# Option 2 — Proxmox SDN-centric model

## What it is

Use Proxmox SDN as the primary abstraction: define **zones, VNets, and subnets** in Proxmox, then attach guests to those virtual networks rather than managing everything as raw bridge/VLAN plumbing. Proxmox’s SDN docs describe zones as separate network areas, with VNets and subnets inside them. ([Proxmox Virtual Environment][1])

## Shape

* SDN zones representing mgmt, apps, edge, games, security
* VNets per segment
* firewall policy tied to segment intent
* optional SNAT/DHCP patterns where useful

## Why it fits you

* more platform-like
* more aligned with your “internal platform” objective
* clearer long-term codification
* nice for dev/prod parity because the network object model is reusable

## Downsides

* more moving parts up front
* steeper learning/debugging path
* can be overkill if your physical network is still simple
* not ideal if the immediate goal is minimal disruption

## Best fit

Use this if you want the network to become a **first-class managed platform layer** early rather than later.

### Rollout plan

1. Define zones/VNets in dev first.
2. Mirror them in prod naming.
3. Attach only new platform services to SDN first.
4. Keep legacy services on existing networking temporarily.
5. Gradually migrate existing services once rules are proven.
7. Introduce internal DNS authority for `lab.gibbsgreatly.xyz` and configure MikroTik conditional forwarding while keeping MikroTik as first-hop resolver for all clients.

---

# Option 3 — Hybrid migration model

## What it is

Use **VLAN-aware bridges as the transport**, but model the target state in a way that can later become SDN-backed. In other words, start operationally simple, but keep the names, zones, firewall groups, IP plan, and service boundaries aligned with a future SDN model.

## Shape

* today: VLAN-aware bridge + tagged guests
* policy: Proxmox firewall security groups + router/firewall rules
* later: optional migration of some segments into SDN VNets

## Why it fits you

* lowest migration risk
* preserves existing service layout best
* lets dev/prod use the same logical zones now
* keeps future SDN adoption open without forcing it immediately

## Downsides

* not as “pure” as a clean SDN-first design
* some duplicate thinking during transition

## Best fit

This is the option I’d recommend for you.

It matches your goals:

* keep working data/service structure
* build dev as a scaled model of prod
* avoid redoing what already works
* still move toward a real platform design

---

# My recommended zone design options

Below are three concrete zone sets, from leanest to strongest.

## Design A — Minimal segmentation

### Zones

* mgmt
* internal-apps
* public-edge
* security-lab

### Good for

* fastest implementation
* least service movement
* easiest first dev build

### Tradeoff

Games, DNS, and some utility workloads may end up lumped into internal-apps longer than ideal.

## Design B — Balanced segmentation

### Zones

* mgmt
* internal-apps
* public-edge
* game-services
* security-lab
* admin-vpn

### Good for

* strong enough for your lab
* clearer separation for internet-facing game workloads
* clean access path for admin traffic

### Tradeoff

A little more routing/firewall work, but still manageable.

## Design C — Strict segmentation

### Zones

* mgmt
* storage-backup
* internal-apps
* dns-core
* public-edge
* game-services
* security-lab
* admin-vpn

### Good for

* strongest blast-radius control
* best long-term platform posture
* best for detailed policy and documentation

### Tradeoff

More complexity, more ACLs, more chances to overbuild too early.

### My view

For you, I would start with **Design B**, and leave room to grow into parts of C later.

---

# Recommended traffic policy shape

## DNS policy shape

* Public ingress: `service.gibbsgreatly.xyz` via Traefik.
* Internal platform identity: `service.lab.gibbsgreatly.xyz`.
* Internal names use step-ca trust from day one on managed hosts.
* Direct container IP access is test-only and break-glass.
* DoH migration away from MikroTik is deferred until internal DNS authority is stable.

Regardless of option, I’d make the initial policy look like this:

## Always allowed

* admin-vpn → mgmt
* mgmt → all managed zones for admin/automation/monitoring as needed
* internal-apps → DNS, auth, reverse proxy backends as required
* public-edge → only the specific internal backends it proxies
* backup/monitoring flows where explicitly needed

## Usually denied

* internal-apps → mgmt
* game-services → mgmt
* public-edge → mgmt
* internal-apps ↔ security-lab unless explicitly justified
* arbitrary zone-to-zone east-west traffic

That approach is directly aligned with using Proxmox firewalling as the enforcement layer for guests and with reusable security groups for common rule sets. ([Proxmox Virtual Environment][2])

---

# How dev should mirror prod

Because you want dev to replicate prod structure at smaller scale, I would mirror:

* the **same zone names**
* the **same service classes**
* the **same intended flows**
* similar firewall groups
* similar naming for bridges/VNets

But reduce:

* number of guests
* address space size
* bandwidth expectations
* storage volume sizes

So dev might have one small service per zone, while prod has many.

---

# Practical network-stage plan

## Path 1 — Conservative rollout

Best if you want the least disruption.

1. Document current traffic and services.
2. Define target zones and VLAN IDs.
3. Build those zones first in nested dev.
4. Prove firewall rules with demo services.
5. In prod, introduce new VLAN-backed zones without moving old services yet.
6. Migrate one service class at a time.

## Path 2 — Platform-first rollout

Best if you want a clean new foundation quickly.

1. Build target zones/VNets in dev using SDN.
2. Deploy Harbor, CI, Authentik, NetBox, monitoring into mgmt first.
3. Stand up edge separately.
4. Move only newly rebuilt app stacks into the new zones.
5. Leave legacy services on old networking until replaced.

## Path 3 — Parallel migration

Best if you want steady progress while keeping existing workloads alive.

1. Keep current network intact.
2. Add new segmented zones alongside it.
3. Put all new platform services into the new zones.
4. Gradually re-home existing services only when each is rebuilt or touched.
5. Retire the old flat segment last.

---

# What I recommend

I’d use:

* **Implementation model:** **Option 3, hybrid**
* **Zone set:** **Design B, balanced segmentation**
* **Execution path:** **Path 3, parallel migration**

That gives you:

* the safest route for preserving current working services
* a dev environment that still meaningfully mirrors prod
* enough segmentation to materially improve security
* a clean path to stricter policy later
* no forced redesign of the data/ZFS side just to improve the network

## The exact first network-stage milestones I’d set

### Milestone 1

Define and document:

* zone names
* VLAN IDs
* subnets
* service-to-zone mapping
* allowed-flow matrix

### Milestone 2

Build the same logical zones in nested dev.

### Milestone 3

Create Proxmox firewall security groups for:

* management services
* reverse proxy backends
* app servers
* game servers
* monitoring/backup agents

### Milestone 4

Deploy one test app through:

* edge zone
* app zone
* management/monitoring visibility
* backup coverage

### Milestone 5

Introduce the same zone structure into prod alongside the existing network, then migrate service classes one by one.

### Milestone 6

* Stand up internal DNS service authoritative for `lab.gibbsgreatly.xyz` (Phase 04b deployment).
* Configure MikroTik conditional forwarding for `lab.gibbsgreatly.xyz`.
* Validate resolution from `build_seg`, `mgmt_seg`, `edge_seg`, and `infra_seg` clients.
* Onboard first platform names: `traefik.lab.gibbsgreatly.xyz`, `authentik.lab.gibbsgreatly.xyz`, `grafana.lab.gibbsgreatly.xyz`, `step-ca.lab.gibbsgreatly.xyz`.
* Confirm internal TLS trust paths with step-ca for internal names.

## Architecture note - internal DNS zone strategy

Status: Proposed

Date: 2026-04-18

### Context

The shared platform is designed to be rebuild-safe on bare-slate Proxmox. DNS currently
uses MikroTik as resolver entry point. Public ingress must remain stable. Internal platform
identity needs a dedicated authority model.

### Decision

* Public ingress names remain under `gibbsgreatly.xyz`.
* Internal shared-platform names use `lab.gibbsgreatly.xyz`.
* MikroTik remains first-hop resolver for SDN clients.
* MikroTik conditionally forwards `lab.gibbsgreatly.xyz` to an internal authoritative DNS server.
* Internal names use step-ca trust by default on managed hosts.
* DoH recursion migration to internal DNS is deferred.

### DNS roles

* MikroTik: resolver entry point for clients, conditional forwarding for `lab.gibbsgreatly.xyz`,
  transitional static records and current recursive path.
* Internal DNS server: authoritative source of truth for `lab.gibbsgreatly.xyz`.
* Public DNS path: continues handling public ingress naming and existing ACME DNS-01 workflows.

### Naming rules

* Public/operator ingress endpoints: `service.gibbsgreatly.xyz`.
* Internal platform identity endpoints: `service.lab.gibbsgreatly.xyz`.
* Internal names are not default public browser entry points.

### Certificate rules

* Public ingress names follow existing public trust flow.
* Internal `lab.gibbsgreatly.xyz` names use step-ca trust from day one.
* Direct container IP access is test/bootstrap only.

### MikroTik automation boundaries

In scope now:

* Conditional forwarding for `lab.gibbsgreatly.xyz`.
* DNS listener/firewall prerequisites required for zone resolution.
* Minimal transitional static records when necessary.

Out of scope now:

* Full replacement of MikroTik recursive DNS behavior.
* Immediate DoH migration to internal DNS.

### Consequences

This model preserves stable client behavior, improves platform reproducibility, and allows
DNS authority evolution without reworking client resolver conventions in each VLAN.

If you want, the next step can be a **concrete proposed zone/VLAN/subnet matrix** tailored to your homelab workloads.

[1]: https://pve.proxmox.com/pve-docs-9-beta/chapter-pvesdn.html?utm_source=chatgpt.com "Software-Defined Network"
[2]: https://pve.proxmox.com/wiki/Firewall?utm_source=chatgpt.com "Firewall"
[3]: https://pve.proxmox.com/wiki/Network_Configuration?utm_source=chatgpt.com "Network Configuration"
