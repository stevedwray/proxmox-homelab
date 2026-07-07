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

Status: **complete**, using the existing `router/config/current-config.json`
live scrape (2026-07-03) rather than a fresh re-scrape — it already contains
the DHCP server/network/lease objects and full IPv6 (DHCPv6-PD/RA/ND) config
needed here. See `current-state.md`'s "Live scrape detail not previously
captured" section for the gap-fill (DNS handed out via the network's
`dns-server` field, not `dhcp-option`; `dynamic-lease-identifiers` setting;
the previously-unlabeled lease now fingerprints as `raspberrypi`).

Tasks:

1. ~~Inventory the live IPv4 DHCP configuration~~ — done, see above.
2. ~~Inventory the live IPv6 behavior~~ — done, see above.
3. ~~Record which current client populations are on `bridgeLocal`~~ — done:
   all 13 current leases (5 static, 8 dynamic) are on `bridgeLocal`; the SDN
   VLANs run no DHCP at all today.
4. ~~Confirm hidden Pi-hole DNS dependencies~~ — done: DHCP hands out
   `192.168.1.22` via the network object; IPv6 RA hands out `fd00::22`,
   `fd00::23` via `advertise-dns=yes`. Both are explicit, not hidden.
   Whether this stays pointed at the Pi-holes once Technitium is the DHCP
   server is no longer pending — decisions.md's Decision 3 settles it:
   DHCP-assigned DNS stays on the Pi-holes.

Deliverable: **done** — `current-state.md` updated 2026-07-05.

## Phase 1 — Target architecture decisions

Goal: settle the intended ownership model before touching config.

Status: **all four decision points are now settled** — see
[decisions.md](./decisions.md) Decisions 1–4. Decisions 1–2 were forced by
Technitium's technical capabilities; Decision 3 (2026-07-05) resolved the
remaining operator judgment calls: migrate `bridgeLocal` now (not after VLAN
segmentation), keep DHCP-assigned DNS on the Pi-holes, migrate all 5 static
leases in the first slice. Decision 4 (2026-07-05) settled the resiliency
approach after exploring (and rejecting, for now) a second Proxmox-independent
Technitium node.

Decision points:

1. **IPv4 DHCP target model — decided (decisions.md Decision 1): MikroTik
   relay to Technitium.** Direct/broadcast service from the existing
   container would require `network_mode: host` or macvlan, a deployment-shape
   departure this workspace rejected; relay reuses the same unicast-forward
   mechanism already proven by the DNS FWD-rule cutover.
2. **IPv6 target model — decided (decisions.md Decision 2): RouterOS keeps
   100% of RA/PD/DHCPv6.** Not a design trade-off — Technitium has no DHCPv6
   support at all today (open upstream feature request). Revisit only if
   Technitium ships DHCPv6.
3. **VLAN growth model — decided (decisions.md Decision 3):**
   `bridgeLocal` migrates first, before any WiFi/IoT VLAN segmentation
   exists; future VLANs add scopes to an already-proven relay setup.
4. **Resiliency approach — decided (decisions.md Decision 4):** single
   Technitium instance (a second, Proxmox-independent node was considered —
   Technitium's DNS clustering is real, but DHCP clustering isn't mature
   enough yet to make a second node actually redundant), long lease times to
   absorb brief Proxmox/Technitium outages for already-connected clients, and
   MikroTik's local `lan` DHCP server kept disabled-but-present indefinitely
   as a manual break-glass fallback for the narrow "new device, mid-outage"
   case that long leases can't cover.

Deliverable: **done** — decisions.md holds Decisions 1–4, all settled.

## Phase 2 — Technitium DHCP capability validation

Goal: validate the server-side capability before production design hardens
around it.

Status: **done — desk research and live validation both complete
(2026-07-05).** Research confirmed capability shape (multi-scope via relay
`giaddr` matching, per-scope reservations via REST API, no DHCPv6), and
Phase 3 Stage A then exercised every bit of it against a real, running
Technitium instance: scope creation, reservation honoring, relay `giaddr`
scope selection, and forward/reverse DNS-on-lease all confirmed live, not
just researched.

### Important correction (2026-07-05): the existing SDN VLANs are not a safe test bed for this

Earlier drafts of this plan assumed a live smoke test could reuse the
existing `mgmt_seg`/`bridgeLocal` addressing directly. That's wrong, and
worth recording clearly so it isn't repeated: per
[docs/design/network.md](../design/network.md) and
`terraform/lxc/network/pve-test-vm.yaml`'s header comment, `pve-test-vm`
does **not** have an isolated copy of these networks — it shares the exact
same physical MikroTik trunk, the exact same VLAN tags, and the **exact
same subnets** as production `pve` (e.g. `mgmt_seg` is `192.168.20.0/24` in
both environments simultaneously; containers are only distinguished by a
+100 last-octet offset convention, "to avoid collisions when both
environments are simultaneously attached to the MikroTik trunk" per that
file). `bridgeLocal` is the same story in the other direction: `pve-test-vm`
itself has a live presence *on* the real `bridgeLocal` (`192.168.1.41`) —
there is no separate test copy of the physical client LAN either.

Practical implication: standing up a DHCP scope on any of the 4 existing
SDN zones (`build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`) "for testing"
would mean handing out addresses on the same wire real production static
containers already live on — a real collision risk, not a safe sandbox.
And there is no way to rehearse the literal `bridgeLocal` cutover step in a
throwaway copy, because no such copy exists — see Phase 3 Stage E below for
how that's handled instead.

Tasks:

1. Verify Technitium IPv4 DHCP scope and reservation model against the needs
   of the homelab. *(confirmed live via Phase 3 Stage A — scope creation and
   reservation honoring both proven, not just desk-researched)*
2. Verify whether Technitium can cleanly support multiple client VLAN scopes.
   *(confirmed live: relay `giaddr` scope matching works correctly against a
   real scope on the throwaway VLAN)*
3. Verify what Technitium can and cannot do for IPv6 — **resolved without
   needing a live test: nothing, no DHCPv6 support exists.** RouterOS keeps
   the entire IPv6 role (decisions.md Decision 2).
4. Identify what still must remain on MikroTik even in the target state —
   IPv6 in full (Decision 2); DHCP relay duty for every client VLAN
   (Decision 1, MikroTik is always the on-segment relay, never fully
   disintermediated).

Deliverable: **done** — the live mechanism-proof test happened via Phase 3
Stage A (now fully complete, including the failure-mode checks), which
turned every desk-researched item above into an empirically verified one.

## Phase 3 — Migration design and staged rollout

Goal: turn the chosen model (decisions.md Decisions 1–4) into a concrete,
staged runbook — each stage has its own validation and its own rollback, so
a problem at any point is contained to that stage rather than requiring the
whole migration to be undone.

This is a major, live change to shared home-network infrastructure. The
stages below are ordered from **zero-risk / fully isolated** through to
**production-only / no rehearsal possible**, deliberately front-loading
everything that *can* be de-risked in `pve-test-vm` before the one step that
inherently can't be.

### Stage A — Isolated mechanism proof on a brand-new VLAN (`pve-test-vm` only)

Goal: prove relay → firewall → Technitium scope → reservation → DNS-on-lease
all work correctly, end to end, with **zero** risk to anything currently
running — not `mgmt_seg`, not `bridgeLocal`, nothing live.

**Status: core mechanism proven end-to-end (2026-07-05).** A real lease now
issues correctly: `dhclient -v eth0` on the disposable test client shows a
full `DHCPOFFER`/`DHCPACK`/`bound` sequence for the reserved address
`192.168.90.61`, with the correct gateway, DNS-server, and domain options,
plus confirmed working forward *and* reverse DNS. Getting here required
finding and fixing four separate bugs, none of which were about the relay
architecture itself — see `stage-a-execution.md` Issues 7–10 for the full
detail:
- Technitium defaulting an unspecified `leaseTimeDays` to `1` (silently
  turning the intended 10-minute test lease into ~1 day + 10 min)
- Technitium's Docker container never actually publishing `67:67/udp`
  (decisions.md Decision 1's "concrete change inventory" item 1, planned
  but never implemented)
- the MikroTik firewall rule allowing Technitium's DHCP reply existing but
  sitting *after* the catch-all input-chain drop rule, making it
  unreachable
- the throwaway VLAN's bridge trunk tagging being incomplete — VLAN 90 was
  never added to the trunk ports (`ether1`/`ether5`) the way VLANs
  10/20/30/40 explicitly were, so VLAN-90 traffic never crossed the
  physical trunk between the router and Proxmox at all

**Restart/renew and brief-outage recovery are also now done (2026-07-05)** —
see `stage-a-execution.md` Issues 11–12:
- restart Technitium mid-lease → client renews cleanly afterward, confirmed
  twice
- brief outage (Technitium stopped) → surfaced a second, identical-shaped
  bug to Issue 9: VLAN 90 had **no ICMP allow rule to the router at all**
  (every other VLAN has one), which broke `dhclient`'s own recorded-lease
  fallback logic (it pings the gateway as a sanity check before trusting a
  cached lease). Fixed the same way as Issue 9, correctly positioned before
  the catch-all drop this time.
- also found, while investigating: Technitium reports its own **Docker-internal
  IP** as the DHCP server-identifier (confirmed via `docker inspect` and an
  upstream GitHub discussion — a known limitation of Technitium's DHCP
  server behind normal Docker bridge networking, not something fixable via
  the documented API without reopening Decision 1's rejected
  `network_mode: host` trade-off). **Accepted, not blocking**: it means
  every client's renewal falls through to REBIND (broadcast, already
  proven working) instead of a clean unicast RENEW — a minor efficiency
  cost given Decision 4's long lease times, not a connectivity risk.

**The simulated-cutover renew/rebind check is also now done (2026-07-05)** —
`stage-a-execution.md`'s "Stage A's last validation check" section. A
temporary MikroTik-local `dhcp-server` was stood up on the throwaway VLAN,
the client got a lease from it, then the real cutover sequence was executed
(disable local server, enable relay — the exact two-part change Stage E's
packet will perform). Result: the client's stale, foreign lease was cleanly
`DHCPNAK`'d by Technitium (now the authority via the relay), and the client
immediately re-discovered and landed back on its correct reservation — no
hang, no manual intervention. Temporary MikroTik objects were all removed
afterward; the relay is confirmed as the final, permanent state.

**Stage A is now fully complete**: mechanism, restart/renew, outage
recovery, and simulated cutover are all validated end-to-end. The one
remaining item is Issue 12 (Technitium's Docker server-identifier
limitation) — accepted as a known, non-blocking cost, with a deferred idea
(run Technitium natively on the LXC instead of Docker) recorded in
decisions.md Decision 1 to revisit later rather than something blocking
Stage B.

Why a new VLAN and not an existing one: see Phase 2's correction above —
`mgmt_seg`/`build_seg`/`edge_seg`/`infra_seg` are shared live address space
with production `pve`, not an isolated sandbox. A **new VLAN tag that exists
nowhere today** is the only genuinely additive option — nothing currently
depends on it, so a mistake here can't break anything that currently works.

Steps:
1. Add one new SDN VLAN to `terraform/lxc/network/pve-test-vm.yaml` only
   (e.g. VLAN 90, `test_dhcp_seg`, `192.168.90.0/24`), following the existing
   `zone_type: vlan` pattern used by the 4 real zones — purely additive,
   `pve-test-vm`-only, not mirrored to `pve.yaml`.
2. Add the matching VLAN interface/gateway on the MikroTik (manual, TM-09 —
   same bucket as every other MikroTik change in this plan).
3. Add a Technitium DHCP scope on the `pve-test-vm` instance
   (`192.168.20.115`) for `192.168.90.0/24`.
4. Add one MikroTik relay entry: `interface=test_dhcp_seg
   dhcp-server=192.168.20.115 local-address=192.168.90.1`.
5. Add the MikroTik firewall input-chain rule identified in decisions.md
   Decision 1 (`input accept in=vlan20-mgmt ... allow mgmt_seg DHCP reply
   UDP to router`). Note: this rule is **not segment-specific** — Technitium's
   reply always originates from `mgmt_seg` regardless of which client VLAN
   asked, so proving this rule here proves it for `bridgeLocal` too; it does
   not need to be re-derived in Stage E.
6. Spin up one disposable test LXC (modeled on this repo's existing
   `test-lxc`/`test-docker` scratch-stack convention) attached to the new
   VLAN. **Correction (2026-07-05):** "configured for DHCP instead of a
   static IP" isn't actually achievable directly — the current
   Terraform/LXC pipeline is static-IP-first (see "Stage A implementation
   touchpoints" below), so in practice this means bootstrapping the client
   statically, then flipping it to DHCP in-guest afterward, once a
   reservation exists at that same address. See
   [stage-a-execution.md](./stage-a-execution.md) for the concrete sequence
   this turned into.
7. Add one reservation on the Technitium scope for that test container's MAC.

#### Stage A implementation touchpoints discovered in the repo (2026-07-05 scoping pass)

- **Network intent file:** `terraform/lxc/network/pve-test-vm.yaml` is where
  the new additive VLAN attachment/zone belongs. The existing file already
  models the 4 live SDN VLANs as `attachments:` plus `zones:`, so the
  throwaway DHCP test segment should follow that same pattern (new
  attachment, new zone, `pve-test-vm` only).
- **Zone-members index:** after adding a new zoned test stack, regenerate
  `terraform/lxc/network/pve-test-vm.zone-members.yaml` with:

  ```bash
  python3 terraform/lxc/generate-zone-members-index.py \
    --network-intent terraform/lxc/network/pve-test-vm.yaml \
    --output terraform/lxc/network/pve-test-vm.zone-members.yaml
  ```

- **Technitium placement:** `terraform/lxc/stacks/technitium-stack/stack.yaml`
  confirms the server remains on `mgmt_seg` (`${lab_ip_technitium}` /
  `192.168.20.115` in `pve-test-vm`), so Stage A's relay target does not
  require any stack relocation — only DHCP capability added to the existing
  Technitium host.
- **Important platform constraint:** the current Terraform LXC pipeline is
  **static-IP-first**. The reusable module
  `terraform/lxc/modules/lxc-docker-host/main.tf` always sets
  `initialization.ip_config.ipv4.address = var.ip_address`, and
  `stack.yaml` metadata assumes every stack declares a fixed `ip_address`.
  In other words, "spin up a disposable test LXC ... configured for DHCP"
  is **not expressible in the current stack abstraction as-is**.

  **Chosen Stage A approach (2026-07-05):** use a one-off workaround for the
  test client rather than extending the whole platform first. Create a
  temporary stack on the new VLAN with an initial static address purely so the
  guest can boot and be reached deterministically, then flip its guest
  interface to DHCP post-boot (via ad hoc Ansible or a manual guest change)
  before running the actual lease/reservation/renewal tests. This keeps Stage A
  focused on proving the DHCP mechanism, not broadening scope into a platform
  feature addition first.

- **Important execution correction from the first live pass (2026-07-05):**
  even after switching the generated inventory to `network.access_path:
  proxyjump_compat`, the normal "Ansible SSH into the guest" path still does
  not work for this throwaway VLAN. The workstation cannot route to
  `192.168.90.0/24`, and `pve-test-vm` itself is not directly attached to that
  VLAN either, so a ProxyJump through Proxmox still cannot open TCP/22 to the
  guest. The guest *is* healthy (`eth0` on `192.168.90.61`, `sshd` listening),
  but management has to happen via `pct exec` on the Proxmox host, not over
  the test VLAN. This is why Stage A now uses dedicated `...-via-pct.yml`
  helper playbooks instead of the earlier direct-SSH variant.

Validation (all must pass):
- the test container receives a lease from the new scope
- the reservation is honored (gets its reserved address, not a random pool
  address)
- the DNS-server option, **gateway/router option, lease time, and any
  domain-name/domain-search option** delivered all match what was
  configured on the scope — not just "an address was handed out." Check the
  client's actual received options (e.g. its lease file / `resolvectl
  status` / `ip addr`), not just that it's pingable.
- forward **and** reverse DNS both resolve for the leased address
  (decisions.md Decision 4's confirmed native A+PTR-on-lease behavior)
- **restart the Technitium container, then force the test client to renew**
  — confirm the client re-acquires the same lease cleanly across a server
  restart, not just on first contact
- **briefly stop Technitium (or block its port 67) and confirm the expected
  failure/recovery behavior** — a client mid-lease should keep working
  (nothing to prove there beyond "it doesn't crash"), and a client actively
  trying to renew during the outage should recover cleanly once Technitium
  is back, without getting stuck in a bad state
- **simulate the exact `bridgeLocal` cutover sequence in miniature**: run a
  normal MikroTik `/ip dhcp-server` on the throwaway VLAN first so the test
  client gets a MikroTik-issued lease, *then* disable that local server and
  enable the relay (the same sequence Stage E will perform for real), and
  observe what the client does — does its next renewal (unicast, to the
  old server address) fail and force a rebind/broadcast fallback, does it
  get a clean answer from Technitium at that point, or does the client end
  up stuck until the lease fully expires and it issues a fresh DISCOVER?
  This is the trickiest real edge case in the whole migration and the
  isolated VLAN is exactly where it's cheap to find out.
- nothing else on `mgmt_seg`, `bridgeLocal`, or any other zone shows any
  change in behavior

Rollback: trivial — remove the relay entry, the firewall rule, the
Technitium scope, the SDN VLAN, and the test container. Nothing else
references any of it, so this is cleanup, not incident recovery.

### Stage B0 — `network_mode: host` for `technitium-stack` (Decision 5)

**Status: complete and empirically validated (2026-07-06/07).** All 6
tasks below are done and confirmed live against `pve-test-vm`'s real
Stage A container.

**History**: a first live attempt accidentally deployed to **production**
instead of `pve-test-vm` (stale, non-environment-scoped `inventory.yml`),
requiring an emergency revert — see decisions.md Decision 5's incident
note. That was fixed two ways in the same session: (1) a
`scripts/provision.sh` guardrail (`assert_inventory_matches_env`) that now
hard-fails on this exact misdirection, and (2) correctly-scoped
`inventory.yml` files placed under
`terraform/lxc/environments/{pve,pve-test-vm}/technitium-stack/` as an
interim stopgap (not Terraform-generated — see
`docs/environment-isolation/` for the real fix, planned separately). With
both in place, a `--check` dry run then a real run correctly routed to
`pve-test-vm` (`192.168.20.115`), confirmed via the smoke test resolving
`test.gibbsgreatly.xyz` names.

Tasks:
1. `deploy-technitium-stack.yml`'s compose template: replace the `ports:`
   list (`53:53/udp`, `53:53/tcp`, `5380:5380/tcp`, `67:67/udp`) with
   `network_mode: host`. Nothing else in the compose file changes. **Done.**
2. `stack.yaml`'s `provides:` list and `STACK_CONTRACT.md`'s Provides table:
   add the `dhcp-server` (udp/67) entry. **Done.**
3. `STACK_CONTRACT.md`: add a short note explaining why this one stack uses
   `network_mode: host`, linking to Decision 5. **Done.**
4. `terraform/lxc/PLATFORM_CONTRACT.md`: add the one-line guardrail noting
   this is a documented per-stack exception, not a default. **Done.**
5. Apply against Stage A's existing throwaway instance (VLAN 90 /
   `test_dhcp_seg`). **Done (2026-07-06 22:15 UTC)** — confirmed via
   `docker inspect`: `NetworkMode=host`, correct `StartedAt`.
6. **Empirically re-validated — confirmed, not just re-asserted:**
   - Forced a fresh lease on the Stage A test client (CT 138): lease file
     shows `option dhcp-server-identifier 192.168.20.115` — Technitium's
     real `mgmt_seg` IP, not the old `172.19.x.x` Docker-internal address.
   - Confirmed direct reachability: `ping` from the test client to
     `192.168.20.115` succeeds (previously unreachable when the
     identifier was Docker-internal).
   - **Captured the actual T1 renewal packet via `tcpdump`** on the test
     client's `eth0`:
     ```
     192.168.90.61.68 > 192.168.20.115.67: BOOTP/DHCP, Request
     192.168.20.115.67 > 192.168.90.61.68: BOOTP/DHCP, Reply
     ```
     A direct **unicast** exchange (not broadcast to `255.255.255.255`),
     completing in ~1ms. This is the clean unicast RENEW that was
     previously impossible — **Issue 12 is genuinely closed**, not just
     configured differently.

Validation: Stage A's existing lease/DNS checks still pass after the
compose change, plus the new server-identifier/RENEW check above — all
confirmed.

Rollback: revert the compose template's `network_mode: host` back to the
explicit `ports:` list; no scope, relay, or firewall changes to undo.

### Stage B — DHCP configuration as code (declarative source of truth + backup/restore)

**Status: complete (2026-07-07).** All 5 steps below are done. The
original (2026-07-05) implementation only handled *existence*
(create-if-missing); reviewing it for this stage found a real gap —
`stage-a-execution.md` Issue 7's exact bug shape (a declared value change
silently never reaching an already-existing scope) could recur, since the
scope-create task's `when:` guard only fired on absence. Rewrote it to
diff the scope's live config against the declared values and reconcile
(`scopes/set`) whenever they differ, not just on first creation, and
converted the single hardcoded reservation into a declarative
`dhcp_reservations` list. Proven idempotent live against `pve-test-vm`'s
real Stage A scope twice (`changed=0` on the second run), including 5 fake
reservations shaped like the real `bridgeLocal` static leases per step 3.
See `docs/dhcp-refactor/decisions.md` Decision 6 (production lease time),
Decision 7 (standalone playbook), and the idempotency-proof note under
Decision 7 for full detail.

Goal: close the gap between "the container came back" and "the DHCP design
is reproducible." `STACK_CONTRACT.md` currently documents the
`technitium-config` Docker volume as holding DNS zone/config data only —
DHCP scopes, options, reservations, and reverse-zone settings have no
repo-owned definition today, and a full LXC destroy/recreate (which Stage C
below performs) **wipes that volume** — it is not preserved across a
teardown the way "the container came back" might suggest. Without this
stage, Stage C can only prove the container starts, not that DHCP
configuration survives a rebuild.

Design: mirror the pattern already proven for DNS zone data —
`technitium_generated_zone_src` is a repo-owned, deploy-time API-pushed hook
that `deploy-technitium-stack.yml` already applies idempotently on every
provision, rather than relying on volume persistence. DHCP needs the exact
same shape: a declarative, version-controlled definition (scope: network,
gateway, DNS-server option, lease time, reverse-zone settings, option list;
plus the reservation set) applied via Technitium's REST API on every deploy,
using the same query-then-add-if-missing idempotency pattern the zone
bootstrap already had to build (dns-refactor "Issues encountered" #6).

Steps:
1. **Done.** Declarative scope/options shape (`dhcp_scope_*` vars) and a
   `dhcp_reservations` list in `configure-technitium-dhcp-scope-via-api.yml`
   — reservations are one part of this same config-as-code surface, not a
   separate concern.
2. **Done.** Idempotent apply step exists as its own playbook — see
   Decision 7 for why it stays standalone rather than merging into
   `deploy-technitium-stack.yml`.
3. **Done.** Idempotency proven **against Stage A's throwaway scope**:
   applied twice, second run `changed=0`, using 5 fake reservations shaped
   like the real ones (`fake-argon-01` etc.) — confirmed via direct API
   read afterward, not just the Ansible recap.
4. **Done.** Decision 6 settles the real value (7 days), recorded as
   `dhcp_production_lease_days`/`_hours`/`_minutes` in the playbook —
   documentary only until Stage E builds real `bridgeLocal` scope
   management.
5. **Done.** `STACK_CONTRACT.md`'s Persistent State table now states
   explicitly that the Docker volume is not the source of truth for either
   DNS or DHCP config.

Validation: idempotent re-run produces no changes on the second pass —
**confirmed** (`changed=0`, all 6 reservations and the scope config itself
all reported no drift). Reservation correctness confirmed via direct API
read (`scopes/get` shows all 6 with correct hostname/MAC/IP). DNS
resolution wasn't checked for the 5 fakes — a reservation alone doesn't
trigger a DNS update, only an actual issued lease does (already proven for
the real test client in Stage A).

Rollback: n/a — this stage produces config-as-code and playbook changes,
not a live network change.

### Stage C — Full teardown/redeploy validation gate

**Status: prep in progress (2026-07-07); full execution not yet attempted
— deliberately scoped as a separate, explicitly-approved step.** A full
`cycle` run is a destroy/rebuild of `pve-test-vm`'s *entire* platform (11
stacks, foundation → edge → platform tiers), gated by the harness's own
formal approval-packet mechanism (backup evidence for step-ca, authentik,
harbor, netbox, monitoring, portainer; explicit outage window). That's a
materially bigger action than anything else done in the DHCP-refactor
workspace so far and needs its own deliberate go-ahead, not an implicit
one.

Prep work completed so far, found while running the harness's read-only
`plan` phase for the first time with `technitium-stack` in scope:
- `terraform/lxc/classify-storage-plan.py` had a pre-existing bug (never
  special-cased Terraform's `no-op` action) that made the harness's
  `plan` phase fail on the very first stack even with zero real changes
  proposed — fixed, with regression tests added (none existed before).
  This was blocking the harness for every stack, not just Technitium.
- `docs/teardown-test/inventory.md` never included `technitium-stack` at
  all — added it alongside `dns-stack` (both are actually deployed on
  `pve-test-vm`) to the in-scope list, stack table, deploy order, and
  destroy order.
- `.env` was missing the `lab_ip_technitium`/`TF_VAR_lab_ip_technitium`
  aliases every other stack has for template expansion — added, matching
  the existing pattern.

With these fixed, `scripts/teardown-deploy-test.sh plan` now resolves
cleanly end-to-end including `technitium-stack`. **Not yet done**: the
harness's smoke-test sweep (`final-validation` phase) doesn't yet have a
DHCP-specific check — Stage C's validation goal requires one: a DHCP lease
issued against the Stage A throwaway scope after a full destroy/recreate,
with scope/reservation config matching Stage B's declarative definition
exactly (not whatever happened to survive in the volume). Wiring that in,
and deciding whether `dhcp-test-client-01` also needs adding to the
teardown inventory so it gets destroyed/recreated as part of the same
cycle (rather than surviving untouched, which would make the DHCP check
less meaningful), is the next concrete prep task — not yet started.

Goal: per `CLAUDE.md`'s Validation Tiers table, this is a Terraform/network
class change — a full teardown cycle on `pve-test-vm` is required before
promotion to `stable`, not a targeted `--stack` pass. With Stage B's
declarative config-as-code in place, this stage can now actually prove what
it's meant to: that the DHCP design (published `67:67/udp`, `stack.yaml`'s
new `dhcp-server` provides entry, the Stage B scope/reservation
definitions) is **reproducible**, not merely that the container restarts.
Use the harness in
[docs/teardown-test/repeatable-test.md](../teardown-test/repeatable-test.md)
— still scoped to Stage A's throwaway VLAN, **not** `bridgeLocal`.

Validation: the harness's normal smoke-test sweep gains one more check — a
DHCP lease issued against the Stage A throwaway scope after a full
destroy/recreate, with the scope/reservation config matching Stage B's
declarative definition exactly (not whatever happened to survive in the
volume).

Rollback: standard teardown-test failure handling — do not promote to
`stable`; fix and rerun. No live-network impact either way, since this is
still confined to the throwaway VLAN.

### Stage D — Dynamic-lease policy for the 8 non-static clients

Goal: the plan so far only explicitly migrates the 5 static leases
(decisions.md Decision 3). `current-state.md` records 13 total current
leases — 5 static, **8 dynamic** — and nothing yet decides what happens to
those 8 during cutover. This is a real gap: dynamic clients will very
likely get a *different* address from Technitium's pool than whatever
MikroTik last gave them (Technitium has no visibility into MikroTik's
existing dynamic lease table), and that's probably fine for most of them,
but it needs to be an explicit, reviewed conclusion, not a silent side
effect discovered after cutover.

Tasks:
1. Audit the 8 current dynamic leases (`current-state.md`'s lease data —
   e.g. `HarmonyHub`, `iPhone`, and the other genuinely-dynamic entries;
   **not** `raspberrypi`, which is already one of the 5 static leases in
   Decision 3's fixed reservation set, not part of this dynamic-audit
   population) and decide, per device, whether IP churn is acceptable or
   whether it should be promoted to a reservation *before* cutover (added
   to Stage B's declarative reservation list) so it keeps the address
   anything might depend on.
2. Document the accepted-churn decision explicitly (even if the answer is
   "all 8 may freely get new addresses") so it's a reviewed conclusion, not
   an assumption.
3. Define the stale-record cleanup procedure for the rollback case: if
   Technitium has already issued leases (and, per Decision 4, created
   forward/reverse DNS records) for some dynamic clients before a rollback
   to MikroTik is triggered, those Technitium-side DNS records become
   stale. Define how they get cleaned up — a manual check-and-delete pass
   against Technitium's DNS zone as part of the rollback procedure (feeds
   into Stage E's rollback steps below), not left to rot.

Deliverable: a short, explicit dynamic-lease policy (which devices are
promoted to reservations, confirmation that churn for the rest is
acceptable, and the stale-DNS-record cleanup procedure) feeding directly
into Stage E's cutover packet.

Rollback: n/a — this stage is a decision/documentation task.

### Stage E — Formal `bridgeLocal` cutover packet (production-only, no rehearsal possible)

Goal: this is the one step Stage A–D cannot de-risk, because — per Phase 2's
correction — `bridgeLocal` is the single physical client LAN; `pve-test-vm`
has a presence *on* it rather than an isolated copy of it. There is no
throwaway version of your home network to rehearse against. All the risk
reduction has to come from careful preparation and instant rollback, not a
test environment.

Deliverable: a new file, `docs/dhcp-refactor/bridgelocal-cutover-packet.md`,
mirroring [docs/dns-refactor/production-cutover-packet.md](../dns-refactor/production-cutover-packet.md)'s
shape. It must contain:
- the exact `/ip dhcp-relay` add command for `bridgeLocal`
- confirmation the Decision-1 firewall rule is already in place (proven in
  Stage A, so likely nothing new here — verify, don't re-derive)
- the exact command to **disable, not remove**, the `lan` DHCP server
  (decisions.md Decision 4 — this is what makes rollback a re-enable, not a
  rebuild)
- Stage B's declarative scope definition (lease time, options, reverse
  zone) and full reservation set (5 static leases plus anything Stage D
  promoted from the dynamic set), applied to the real scope *before*
  cutover — not assembled afterward
- Stage D's dynamic-lease policy attached verbatim: which devices were
  promoted, and the explicit acknowledgment that the remaining dynamic
  clients are expected to receive new addresses
- **a pre-staged, tested out-of-band admin path**: not just "a wired
  laptop" but a specific device with a manually-configured static IP on
  `bridgeLocal`, verified reachable to the router's admin interface
  *before* the cutover window starts — this is what you use to fix things
  if DHCP itself is what's broken and nothing can pull an address
- a chosen low-risk time window (late night, few active devices, operator
  physically present with the out-of-band path already verified, not set up
  reactively after something goes wrong)
- an immediate post-cutover validation sequence that starts with **forcing
  a DHCP renew on one trusted device first** (e.g. the operator's own
  phone/laptop) — a controlled, immediate signal, rather than waiting to
  discover a problem only when a Pi-hole's lease happens to expire on its
  own
- **explicit rollback trigger thresholds**, stated as concrete conditions
  rather than "if something looks wrong" — for example: the forced-renew
  test device fails to get a lease within N minutes; any of the 5
  reservations comes up with the wrong address; DNS resolution breaks for
  any browser-routed or platform-internal name; any static-leased device
  (Pi-holes especially) fails to renew. Any one of these fires the
  rollback, no debugging in place on the live network first.
- the rollback steps themselves: re-enable `lan`, remove the relay entry,
  flush caches, re-validate against the pre-cutover checklist
- **a post-rollback cleanup checklist**, using Stage D's stale-record
  procedure: any forward/reverse DNS records Technitium created for clients
  during the failed cutover window need to be identified and removed from
  its zone, so a future retry doesn't start from a confusing, partially
  populated state
- the full validation checklist: lease issue, all reservations correct,
  DNS-server option still the Pi-holes, forward+reverse DNS, IPv6 unaffected

This packet gets written and reviewed once Stages A–D are green — it is a
planning deliverable for this phase, not something to draft with placeholder
values before there's a real scope/reservation set to put in it.

### Stage F — Soak period with a defined exit criterion

Goal: define how long the cut-over state (MikroTik's `lan` server disabled
but present, Technitium as sole DHCP authority) stays in "just cut over,
watching closely" status before it's considered fully settled — mirrors how
`dns-stack` stayed deployed as a warm rollback target for a defined period
after the DNS cutover rather than being decommissioned immediately.

Exit criteria (all must hold for a fixed window — at minimum 7 days, and at
least 2× the Stage B lease-time value so every device has renewed at least
once under normal conditions, not just received its first lease):
- zero lease failures observed (every renewal/rebind succeeds)
- all 5 (or more, per Stage D) reservations have renewed at least once and
  kept their assigned address
- no unexpected address churn beyond what Stage D's dynamic-lease policy
  already accepted as normal
- Pi-hole ad-blocking and DNS resolution behavior unchanged for every
  client (DHCP-assigned DNS is still the Pi-holes, per Decision 3)
- forward/reverse DNS records in Technitium match the live lease table —
  no orphaned or missing entries

If any criterion fails during the window, treat it as a rollback trigger
(Stage E's thresholds) rather than "wait and see" — the soak period is
for building confidence through observed evidence, not for absorbing known
problems.

Deliverable: step-by-step cutover and rollback runbook — Stages A–F above,
each independently validated and independently rollback-able, with only
Stage E carrying irreducible production risk.

## Phase 4 — VLAN-centric expansion plan

Goal: connect the DHCP design to the broader network direction.

Tasks:

1. Identify first new client VLAN candidates:
   - WiFi
   - IoT
   - optional guest / media / other client classes
2. Define which scopes belong on Technitium from the start.
3. Define how inter-VLAN router policy and DHCP scope rollout interact.
4. ~~Decide whether future VLAN adoption should happen before or after the
   first default-LAN DHCP migration~~ — **decided (decisions.md Decision 3):
   after.** `bridgeLocal` migrates first; this phase's VLAN candidates are
   scoped once that slice is validated in production, not before.

Deliverable:

- recommended order for DHCP migration versus client VLAN rollout: **settled
  as bridgeLocal-first**, this phase's remaining work is scope/rollout design
  for whichever VLAN is split out first (WiFi vs. IoT priority still open,
  but out of scope until Phase 3 is complete).

## Known constraints

- Current DHCP usage is concentrated on `bridgeLocal`, not the Proxmox SDN
  stack VLANs.
- The router receives IPv6 network delegation directly from the ISP, so IPv6
  cannot be modeled as a pure internal-server concern.
- The current DNS migration already established Technitium as a stable service
  endpoint in `mgmt_seg`; DHCP planning should reuse that fact rather than
  re-open the DNS identity decision.
- **`pve-test-vm` is not network-isolated from `pve`** (2026-07-05 finding —
  see Phase 2's correction above): the 4 existing SDN VLANs are the same
  physical VLANs/subnets as production, differentiated only by a per-container
  IP offset convention, and `bridgeLocal` has no test-environment copy at all
  — `pve-test-vm` sits directly on the real one. Any DHCP mechanism testing
  must use a dedicated new VLAN (Phase 3 Stage A), and the final `bridgeLocal`
  cutover (Stage E) is inherently a production-only action with no rehearsal
  environment — this is a property of there being one physical home network,
  not a gap in this plan.

## Immediate next step

**Stage A, Stage B0, and Stage B are all done.** Mechanism, restart/renew,
outage recovery, simulated cutover, `network_mode: host` (empirically
confirmed via a `tcpdump`-captured unicast RENEW), and now DHCP
config-as-code with real drift-reconciliation (not just existence-checking)
— all confirmed live on `pve-test-vm`'s throwaway VLAN, including a
second-run `changed=0` idempotency proof covering both the scope's own
config and a 6-entry reservation list. Getting Stage B0 applied safely
required routing around a stale-inventory bug that had earlier sent one
attempt to production by mistake (see Decision 5's incident note) — fixed
for this stack via a `scripts/provision.sh` guardrail plus correctly-scoped
manual `inventory.yml` files per environment; the proper structural fix is
tracked separately in `docs/environment-isolation/`.

The next task is **Stage C**: the full teardown/redeploy validation gate.
With Stage B's declarative config-as-code in place, this stage can now
actually prove the DHCP design survives a real destroy/recreate — not just
that the container restarts — using the harness in
`docs/teardown-test/repeatable-test.md`, still scoped to Stage A's
throwaway VLAN, not `bridgeLocal`. After that, Stage D (dynamic-lease
policy, still genuinely undecided — a real operator call) is what stands
between here and Stage E's production-only `bridgeLocal` cutover packet.
