# bridgeLocal DHCP Cutover Packet — MikroTik → Technitium

Status: **not yet executed.** This is the Stage E planning deliverable
(see [plan.md](./plan.md) Stage E), written now that Stages A–D are all
green. It mirrors the shape of
[docs/dns-refactor/production-cutover-packet.md](../dns-refactor/production-cutover-packet.md).

This is the one step in the whole DHCP-refactor workspace that is
inherently production-only, with no rehearsal environment possible —
`pve-test-vm` has a live presence *on* `bridgeLocal` rather than an
isolated copy of it (see `plan.md`'s "Known constraints"). All the risk
reduction here comes from careful preparation, a pre-staged rollback, and
explicit trigger thresholds — not from a test run.

## What this changes

- MikroTik `bridgeLocal`'s local `/ip dhcp-server lan` (currently the
  active DHCP authority for the flat LAN, `192.168.1.0/24`) gets
  **disabled, not removed**.
- A new `/ip dhcp-relay` entry on `bridgeLocal` forwards DHCP requests to
  Technitium's production instance (`192.168.20.15`).
- Technitium becomes the DHCP authority for `bridgeLocal`; MikroTik
  remains the on-segment relay only (decisions.md Decision 1).
- IPv6 is completely unaffected — RouterOS keeps 100% of RA/PD/DHCPv6
  (Decision 2). This packet only touches IPv4 DHCP.
- DHCP-assigned DNS stays pointed at the Pi-holes (Decision 3) — Technitium
  does not become the client-facing resolver.

## Pre-cutover checklist (complete all of these before opening the window)

### 1. Confirm the Decision-1 firewall rule is already in place

This rule was added to the real, physical MikroTik during Stage A (not
segment-specific — Technitium's reply always originates from `mgmt_seg`
regardless of which client VLAN asked, so Stage A's throwaway-VLAN proof
already covers `bridgeLocal`). **Verify it's still there; do not
re-derive or re-add it:**

```routeros
/ip firewall filter print where chain=input and dst-port=67
```

Expected: an `accept` rule allowing UDP/67 from `mgmt_seg` to the router,
positioned *before* the catch-all `input drop` rule. If this rule is
missing or misordered, stop — do not proceed with the relay cutover until
it's confirmed correct (Stage A's Issue 9/11 both trace back to exactly
this rule being absent or misordered).

### 2. Apply the real bridgeLocal scope to Technitium *before* cutover

Not the Stage A throwaway scope — a new scope for `192.168.1.0/24`. Use
`configure-technitium-dhcp-scope-via-api.yml` (Decision 7: stays
standalone from `deploy-technitium-stack.yml`), pointed at production,
with these declared values:

| Field | Value | Source |
|---|---|---|
| Subnet | `192.168.1.0/24` | current-state.md |
| Gateway/router option | `192.168.1.1` | current-state.md |
| Lease time | `leaseTimeDays=7, Hours=0, Minutes=0` | Decision 6 |
| DNS-server option | `192.168.1.22` | current-state.md (MikroTik hands out this single address today, not a two-entry list — replicate exactly, don't introduce a change in behavior beyond the migration itself) |
| Domain-name option | **open — decide before running**: MikroTik's own `add-dns-entries-suffix` is `"lan"`; using the same suffix for Technitium's scope keeps client-side behavior consistent, but this hasn't been explicitly decided anywhere in this workspace yet. Confirm before applying. |
| Reverse zone | **open — decide before running**, same reasoning as domain-name: needed for Decision 4's auto A+PTR behavior to work for `bridgeLocal` clients. |

Full reservation set — 5 static (Decision 3) + 3 promoted dynamic
(Decision 8) = 8 reservations:

| Host | Address | MAC |
|---|---|---|
| `argon-01` | `192.168.1.22` | `E4:5F:01:0A:56:E1` |
| `argon-02` | `192.168.1.23` | `E4:5F:01:F4:A4:88` |
| `garuda` | `192.168.1.104` | `10:7C:61:B6:A4:91` |
| `RBR350` | `192.168.1.110` | `34:98:B5:9D:56:0D` |
| `raspberrypi` | `192.168.1.28` | `88:A2:9E:57:E6:24` |
| `deb13` | `192.168.1.100` | `10:66:6A:40:A0:CF` |
| `LM-GM17D7CY` | `192.168.1.102` | `F4:28:9D:AB:2B:D1` |
| `Compute` | `192.168.1.101` | `4C:82:A9:BC:6D:CF` |

Everything else (`HarmonyHub`, `RV30_Max_Plus`, `iPhone`,
`Stephen-s-A56`, `BolorErlsiPhone` — Decision 8) gets no reservation and
is expected to receive a new address from Technitium's pool after
cutover. This is a reviewed, accepted outcome, not an oversight.

After applying, verify via the API directly (`dhcp/scopes/get`) that all
8 reservations and the scope config match this table exactly — the same
verification pattern already proven twice against the Stage A scope.

### 3. Pre-stage a tested out-of-band admin path

Not "a wired laptop" grabbed in the moment — a specific device with a
**manually-configured static IP** on `bridgeLocal` (not DHCP-dependent at
all, since DHCP itself is what might be broken), verified reachable to
the MikroTik's admin interface (`192.168.1.1`) *before* the cutover
window starts. This is what gets used to fix things if nothing can pull
an address at all. Prepare and test this physically before scheduling the
window — this packet can't do that part for you.

### 4. Choose a low-risk time window

Late night, few active devices, operator physically present, out-of-band
path already verified (not set up reactively after something goes wrong).

## Cutover

Two-part change, same session (relay is exclusive with the local server
per interface — decisions.md Decision 1):

```routeros
/ip dhcp-relay add interface=bridgeLocal dhcp-server=192.168.20.15 local-address=192.168.1.1 name=bridgeLocal-to-technitium
/ip dhcp-server set [find name=lan] disabled=yes
```

Note `disabled=yes`, not `remove` — this is what makes rollback a
re-enable, not a rebuild (Decision 4).

## Immediate post-cutover validation

Start with **forcing a DHCP renew on one trusted device first** (e.g. the
operator's own phone or laptop) — a controlled, immediate signal, rather
than waiting to discover a problem only when a Pi-hole's lease happens to
expire on its own.

Then the full validation checklist:

- [ ] forced-renew test device gets a lease within a few minutes
- [ ] all 8 reservations resolve to their declared address (spot-check via
      `dhcp/leases/list` on Technitium, or `ip addr` on a couple of the
      physical devices if convenient)
- [ ] DNS-server option handed out is still `192.168.1.22` (the Pi-hole),
      not Technitium
- [ ] forward + reverse DNS both resolve for at least one freshly-leased
      device (Decision 4's confirmed behavior)
- [ ] IPv6 unaffected: RA still advertises `fd00::22`/`fd00::23` as DNS,
      DHCPv6 (`LANIPv6DHCP`) still active, router still holds
      `fd00::1/64` on `bridgeLocal`
- [ ] no other VLAN (`mgmt_seg`, `build_seg`, `edge_seg`, `infra_seg`)
      shows any change in behavior

## Rollback trigger thresholds

Any one of these fires the rollback immediately — no debugging in place
on the live network first:

- the forced-renew test device fails to get a lease within 5 minutes
- any of the 8 reservations comes up with the wrong address
- DNS resolution breaks for any browser-routed or platform-internal name
- any static-leased device (Pi-holes especially) fails to renew
- IPv6 shows any behavior change at all

## Rollback

```routeros
/ip dhcp-server set [find name=lan] disabled=no
/ip dhcp-relay remove [find name=bridgeLocal-to-technitium]
/ip dns cache flush
```

Then re-run the client-path validation checklist above against
`192.168.1.1` to confirm service has actually returned to the
MikroTik-backed path — same pattern as the DNS-refactor rollback
procedure.

## Post-rollback cleanup checklist

Using Decision 8's stale-DNS-record cleanup procedure (decisions.md,
under Decision 8):

1. Before the rollback's first command runs, capture Technitium's
   `bridgeLocal` scope lease table (`dhcp/leases/list`) — this is the
   manifest of every hostname/address pair Technitium created DNS
   records for during the (now-ending) cutover window.
2. After rollback, delete the forward (A) and reverse (PTR) record for
   each entry in that manifest via `zones/records/delete`, using the
   `bridgeLocal` client zone name settled in the pre-cutover checklist
   above.
3. Verify: re-query the zone for each captured hostname and confirm no
   record remains.

Do not leave this for "later" — a future retry should start from a clean
zone, not a partially-populated one from the failed attempt.

## Soak period

Per plan.md Stage F: once this cutover holds clean, the soak period is at
least 7 days (and at least 2× the 7-day lease time, i.e. effectively the
same 7 days works out to one full lease cycle observed) with MikroTik's
`lan` server left disabled-but-present as the break-glass fallback. See
Stage F for the full exit criteria.
