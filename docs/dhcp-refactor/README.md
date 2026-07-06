# DHCP Refactor — MikroTik to Technitium Planning

## Purpose

Plan the future migration of DHCP responsibilities away from the MikroTik and
toward Technitium, while preserving the current working LAN and accounting for
the likely move to a more VLAN-centric client network.

This workspace is intentionally separate from `docs/dns-refactor/`. The DNS
cutover is complete; DHCP migration is a distinct router, client, and IPv6
validation surface.

## Status

Planning opened on 2026-07-05. Phases 0 and 1 are complete —
[decisions.md](./decisions.md) holds four settled decisions: IPv4 DHCP is
relay-based (MikroTik relays to Technitium; Technitium stays off client L2
segments), IPv6/DHCPv6 stays on MikroTik indefinitely (no Technitium support
exists yet), `bridgeLocal` migrates first with all 5 static leases and
DHCP-assigned DNS staying on the Pi-holes, and resiliency is a single
Technitium instance plus long lease times plus a MikroTik break-glass
fallback (a real multi-instance redundancy mechanism was found and is
recorded as a deferred "come back to later" option, not adopted yet).

[plan.md](./plan.md)'s Phase 3 is now a fully staged, step-by-step runbook
(Stages A–F), each with its own validation and rollback. The key finding
shaping that structure: `pve-test-vm` is **not** network-isolated from
production — it shares the same physical VLANs/subnets and the same
physical `bridgeLocal`, so mechanism testing needs a brand-new, dedicated
VLAN (Stage A), and the final `bridgeLocal` cutover (Stage E) is inherently
a production-only action with no rehearsal environment possible.

An independent review (2026-07-05) found the plan was still missing
statefulness handling: a declarative, repo-owned source of truth for DHCP
scope/reservation config (the `technitium-config` Docker volume doesn't
survive a teardown, and nothing analogous to DNS's zone-bootstrap hook
existed for DHCP), an explicit policy for the network's 8 dynamic (non-static)
leases, and failure-mode validation (restart/renew, brief outage, and
renewing a pre-cutover MikroTik-issued lease) beyond first-time lease
issuance. **Status as of end of day 2026-07-05**: the failure-mode
validation is now fully done (see Stage A below), config-as-code (Stage B)
has a working first implementation proven live, and the dynamic-lease
policy (Stage D) is still genuinely undecided — an operator call, not
something to resolve unilaterally in this doc.

Stage A has also moved from pure planning into early execution. The additive
test VLAN (`test_dhcp_seg`, VLAN 90, `192.168.90.0/24`) and disposable client
stack (`dhcp-test-client-01`, bootstrap `192.168.90.61`) are now defined in
the repo, and the MikroTik-side VLAN / relay prerequisites have been applied.
The practical blocker discovered during execution: neither the workstation nor
the `pve-test-vm` host has routed SSH reachability into the throwaway VLAN, so
the initial "flip the guest via normal Ansible SSH" approach was wrong in
practice. Stage A's helper playbooks were therefore reworked to use `pct exec`
through Proxmox instead. The guest's in-guest DHCP flip is now done and
confirmed persistent across a reboot — that required a second fix, since
Proxmox's own container-start network templating was silently reverting the
guest back to static on every `pct reboot` (see
[stage-a-execution.md](./stage-a-execution.md)'s Issue 6).

**Stage A's core mechanism is now proven end-to-end (2026-07-05).** A real
lease issues correctly for the reserved address `192.168.90.61`, with the
right gateway/DNS/domain options and confirmed forward + reverse DNS.
Getting there required finding and fixing three more bugs beyond the
in-guest flip — none about the relay design itself, all about incomplete
setup: Technitium silently defaulting an unspecified lease time to ~1 day,
Technitium's Docker container never actually publishing `67:67/udp`
(decisions.md Decision 1 called for this but it was never implemented), and
a MikroTik firewall rule that existed but sat after a catch-all drop, plus
(the actual last blocker) the throwaway VLAN never being added to the
physical trunk ports the way the other 4 VLANs were — so its traffic never
crossed the trunk between the router and Proxmox at all. Full detail in
`stage-a-execution.md` Issues 7–10.

**Restart/renew and brief-outage recovery are also confirmed (2026-07-05)** —
`stage-a-execution.md` Issues 11–12. Found a second missing-firewall-rule bug
identical in shape to Issue 9 (VLAN 90 had no ICMP allow rule at all, which
broke `dhclient`'s own outage-fallback logic), now fixed the same way. Also
found and accepted a real upstream limitation: Technitium reports its
Docker-internal IP as the DHCP server-identifier, so renewals always fall
through to broadcast REBIND rather than a clean unicast RENEW — not a
connectivity risk, just a minor efficiency cost. Recorded as a deferred item
to revisit (running Technitium natively on the LXC instead of Docker would
close it properly) rather than something to fix now by reopening Decision
1's rejected `network_mode: host` trade-off.

**Stage A is now fully complete (2026-07-05)**, including the last check:
the simulated-cutover rebind test. Stood up a temporary MikroTik-local DHCP
server on the throwaway VLAN, got the client a lease from it, then executed
the real two-part cutover (disable local server, enable relay). The
client's stale lease was cleanly `DHCPNAK`'d and it immediately recovered
its correct reservation — no hang, no manual fix needed. This was the one
check that directly rehearses `bridgeLocal`'s real cutover sequence, and it
passed cleanly.

**Stage B0 is also now complete (2026-07-06/07)**: `network_mode: host`
(Decision 5) closes the Docker server-identifier limitation noted above
properly, rather than just accepting it. Getting there required routing
around a same-session production-deploy incident (see decisions.md
Decision 5's incident note; real structural fix tracked separately in
[docs/environment-isolation/](../environment-isolation/)). Empirically
confirmed via a `tcpdump` capture of the actual T1 renewal: a direct
**unicast** exchange with Technitium's real IP
(`192.168.90.61.68 > 192.168.20.115.67`), not the previous broadcast
REBIND fallback. Next up: Stage B (formalizing the DHCP config as
declarative code) and Stage C (the full teardown/redeploy gate).

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
| `decisions.md` | ADR-style log of Technitium-DHCP-specific design decisions, as they're made |
| `artifacts/` | local-only, git-ignored scratch notes, command output, evidence |

## Read these first

1. This file
2. [current-state.md](./current-state.md)
3. [decisions.md](./decisions.md)
4. [plan.md](./plan.md)
5. [router/README.md](../../router/README.md)
6. [router/desired-config.md](../../router/desired-config.md)
7. [docs/design/network.md](../design/network.md)
8. [docs/dns-refactor/decisions.md](../dns-refactor/decisions.md)

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
