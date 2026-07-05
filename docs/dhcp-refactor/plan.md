# DHCP Refactor — Plan

## Goal

Design a safe, staged migration path from MikroTik-managed client DHCP toward
Technitium-managed DHCP, while preserving working IPv4/IPv6 client networking
and supporting the expected move to a more VLAN-centric network.

## Planning principles

1. Treat IPv4 DHCP and IPv6 behavior as related but separate design problems.
2. Do not disturb the existing static-addressed Proxmox platform VLANs unless
   there is a separate explicit reason to do so.
3. Assume new client VLANs (for example WiFi and IoT) should be designed with
   clean DHCP ownership from the start.
4. Favor reversible transitions: relay, parallel validation, and explicit
   rollback over big-bang replacement.

## Target questions this workspace must answer

### DHCP ownership

- Should Technitium become the IPv4 DHCP server for the current default LAN?
- Should MikroTik stay in path as DHCP relay, or should clients receive DHCP
  directly from Technitium?
- Should different future client VLANs share one Technitium instance with
  multiple scopes, or should DHCP remain partly distributed?

### IPv6 ownership

- What exactly is MikroTik doing today for RA, DHCPv6, and prefix delegation?
- Which parts of that are replaceable, and which should remain on the router?
- Does Technitium have sufficient IPv6 support for the intended end state?
- Should IPv6 DNS advertisement remain ULA-based even if IPv4 DHCP moves?

### Segmentation

- Which future client VLANs need their own scopes first?
- How should WiFi and IoT onboarding work once those VLANs exist?
- Does the future design require relay on a per-VLAN basis?

## Non-goals for the first implementation phase

- migrating Proxmox SDN platform containers to DHCP
- changing WAN behavior
- replacing RouterOS prefix-delegation responsibilities before investigation
- bundling DHCP cutover with unrelated router cleanup

## Phases

## Phase 0 — Baseline inventory and fact gathering

Goal: produce a verified, durable baseline of the live router behavior before
designing any migration.

Tasks:

1. Inventory the live IPv4 DHCP configuration from the MikroTik:
   - DHCP servers
   - pools
   - networks
   - lease times
   - static leases
   - DHCP options and DNS settings handed to clients
2. Inventory the live IPv6 behavior from the MikroTik:
   - DHCPv6-PD client
   - delegated prefix handling
   - RA / ND settings
   - DHCPv6 server behavior
   - advertised DNS and any stable ULA assumptions
3. Record which current client populations are on `bridgeLocal` versus already
   segmented elsewhere.
4. Confirm whether any hidden dependencies still assume Pi-hole DNS addresses
   are handed out by DHCP on IPv4 or advertised on IPv6.

Deliverable:

- updated `current-state.md` with any newly discovered details that are still
  missing today

## Phase 1 — Target architecture decisions

Goal: settle the intended ownership model before touching config.

Decision points:

1. IPv4 DHCP target model:
   - direct Technitium service to clients
   - MikroTik relay to Technitium
   - hybrid
2. IPv6 target model:
   - RouterOS keeps RA / PD, Technitium handles none
   - RouterOS keeps RA / PD, Technitium adds limited DHCPv6 role
   - fuller Technitium role if technically justified and validated
3. VLAN growth model:
   - default LAN remains temporarily
   - WiFi gets dedicated VLAN
   - IoT gets dedicated VLAN
   - each new VLAN gets its own DHCP scope from day one

Deliverable:

- a short decision log added here or in a future `decisions.md` if the
  workspace grows enough to need one

## Phase 2 — Technitium DHCP capability validation

Goal: validate the server-side capability before production design hardens
around it.

Tasks:

1. Verify Technitium IPv4 DHCP scope and reservation model against the needs
   of the homelab.
2. Verify whether Technitium can cleanly support multiple client VLAN scopes.
3. Verify what Technitium can and cannot do for IPv6:
   - DHCPv6
   - prefix handling expectations
   - coexistence with RouterOS RA
4. Identify what still must remain on MikroTik even in the target state.

Deliverable:

- a capability summary stating "supported", "supported with caveats", or
  "keep on MikroTik" for each DHCP / IPv6 function

## Phase 3 — Migration design

Goal: turn the chosen model into a safe cutover design.

Tasks:

1. Define the first migration slice.
   Recommended default: IPv4 DHCP on the current default LAN first, without
   changing platform VLAN addressing.
2. Design relay versus direct-server changes.
3. Define static-lease migration procedure.
4. Define client-impact window and expected renewal behavior.
5. Define rollback to MikroTik as authoritative DHCP server.
6. Define validation checks:
   - new lease issue
   - static lease preservation
   - DNS settings delivered correctly
   - IPv6 still healthy

Deliverable:

- step-by-step cutover and rollback runbook

## Phase 4 — VLAN-centric expansion plan

Goal: connect the DHCP design to the broader network direction.

Tasks:

1. Identify first new client VLAN candidates:
   - WiFi
   - IoT
   - optional guest / media / other client classes
2. Define which scopes belong on Technitium from the start.
3. Define how inter-VLAN router policy and DHCP scope rollout interact.
4. Decide whether future VLAN adoption should happen before or after the first
   default-LAN DHCP migration.

Deliverable:

- recommended order for DHCP migration versus client VLAN rollout

## Known constraints

- Current DHCP usage is concentrated on `bridgeLocal`, not the Proxmox SDN
  stack VLANs.
- The router receives IPv6 network delegation directly from the ISP, so IPv6
  cannot be modeled as a pure internal-server concern.
- The current DNS migration already established Technitium as a stable service
  endpoint in `mgmt_seg`; DHCP planning should reuse that fact rather than
  re-open the DNS identity decision.

## Immediate next step

Perform a dedicated live-router investigation focused on:

1. IPv4 DHCP export and lease behavior
2. IPv6 PD / RA / DHCPv6 behavior
3. whether RouterOS is effectively doing SLAAC-first, DHCPv6-first, or mixed
   client provisioning on the LAN

That investigation should be captured into `artifacts/` first, then folded
back into `current-state.md`.
