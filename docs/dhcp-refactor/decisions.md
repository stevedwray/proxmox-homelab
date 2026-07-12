# DHCP Refactor — Decisions

Durable design decisions for the MikroTik → Technitium DHCP migration, in the
format used by [docs/dns-refactor/decisions.md](../dns-refactor/decisions.md):
one `## Decision N: Title` per settled choice, with context and the actual
decision. Add entries here as Phase 1 (see [plan.md](./plan.md)) resolves each
open question — do not record something here until it's actually decided.

## Decision 1: IPv4 model is relay-only, not direct-broadcast

Context: Technitium's DHCP server needs a decision on how it receives client
DHCP traffic. `technitium-stack` already exists as a Docker container on
`mgmt_seg` (`192.168.20.x`), a routed, statically-addressed platform VLAN —
it is not on `bridgeLocal` or any future client VLAN's L2 segment. Native
DHCP discovery relies on L2 broadcast, which does not cross VLANs/routed
segments. Upstream Technitium discussion confirms that receiving broadcast
DHCP inside Docker requires `network_mode: host` (binds to privileged ports,
loses container network isolation, can't disambiguate multiple host IPs) or
a macvlan interface (host can no longer reach the container at all) — both a
significant deployment-shape departure from every other stack in this repo's
`docker_base`/platform-tier pattern.

Decision: MikroTik remains the on-segment DHCP relay agent for every client
VLAN (`bridgeLocal` today, future WiFi/IoT VLANs later); it forwards
(unicasts, via `giaddr`) DHCP requests to Technitium's existing stable
`mgmt_seg` IP. Technitium never needs a presence on the client L2 segments
itself, and its container keeps its current bridge networking — no macvlan,
no host networking mode.

Rationale: this is the same unicast-relay mechanism already proven for the
DNS FWD-rule cutover (MikroTik forwarding to a single Technitium IP), keeps
`technitium-stack`'s Docker deployment shape consistent with every other
platform-tier stack, and matches standard DHCP relay design (relay sets
`giaddr` to its own on-segment interface address; the server selects the
scope whose subnet contains that `giaddr` — this is how every DHCP relay
implementation, including Technitium's, selects the right scope for a
relayed request). It also means the relay/multi-scope model scales cleanly
to future client VLANs: one relay rule per VLAN pointed at the same
Technitium IP, one Technitium scope per VLAN.

### Known cost of this decision, confirmed live (2026-07-05)

Standard Docker bridge networking (kept per this decision) means Technitium
reports its own **Docker-internal IP** as the DHCP server-identifier
(confirmed via live testing — see `stage-a-execution.md` Issue 12 — and
matches a known upstream limitation,
[DnsServer#1654](https://github.com/TechnitiumSoftware/DnsServer/discussions/1654)),
not its real, externally-reachable address. Effect: every client's unicast
RENEW at T1 targets an unreachable address and silently fails, so every
renewal falls through to broadcast REBIND at T2 instead. This is a real,
standards-compliant fallback (not a connectivity failure) and was accepted
as a minor efficiency cost rather than revisiting this decision — fixing it
properly would mean adopting `network_mode: host` or macvlan, exactly the
trade-off this decision rejected, for the same reasons.

**Resolved by Decision 5 (2026-07-07):** the "native service on the LXC"
option below was explored as one alternative, but the workspace settled on
a narrower fix — `network_mode: host` for the existing container, scoped
specifically to `technitium-stack` — rather than dropping Docker for the
whole stack. See Decision 5 for the reasoning and guardrail. The text below
is kept as the historical record of what was considered at the time.

There is a third option beyond "accept the cost" or "`network_mode:
host`/macvlan" that was considered — running Technitium as a **native
service directly on the LXC** (no Docker at all), the same way
`dns-stack`/CoreDNS runs today (bare binary under systemd, per
`dns-stack`'s original `STACK_CONTRACT.md`). That would remove the Docker
bridge/NAT layer entirely, so Technitium's DHCP server would see and report
the LXC's own real, externally-reachable IP as the server-identifier —
closing Issue 12 properly instead of just accepting it. It wasn't chosen:
it would mean abandoning Docker Compose/Harbor-pull lifecycle for the
*whole* stack (DNS included), a bigger and harder-to-reverse change than
Issue 12 justifies, when `network_mode: host` closes the same gap with a
one-line, easily-reversible compose change. See Decision 5.

### Concrete change inventory (2026-07-05, grounded in live repo/router state; networking line superseded 2026-07-07)

- **`deploy-technitium-stack.yml`'s Compose template** publishes `53:53/udp`,
  `53:53/tcp`, `5380:5380/tcp` today — add `67:67/udp` the same way.
  ~~No `network_mode`/macvlan change needed, confirming the reasoning
  above.~~ **Superseded by Decision 5**: the container now uses
  `network_mode: host`, which makes explicit port publishing moot (all
  ports bind directly on the LXC's real interface) — the `67:67/udp`
  requirement itself still holds, it's just expressed differently in the
  compose file. `stack.yaml`'s `provides:` list and `STACK_CONTRACT.md`'s
  Provides table need a new `dhcp-server` (udp/67) entry alongside the
  existing `dns-authority`/`dns-authority-udp` entries.
- **New MikroTik firewall requirement, not previously documented anywhere in
  this repo:** the live filter-chain scrape
  (`router/config/current-config.json`) shows the router's `input` chain has
  explicit per-VLAN allow rules for ICMP/DNS-UDP/DNS-TCP from each SDN VLAN
  to the router itself, ending in a catch-all `input drop`. A relayed DHCP
  reply from Technitium is addressed back to the router's own interface IP
  (the relay's `giaddr`) — an input-chain packet, sourced from `vlan20-mgmt`,
  for which no allow rule exists today. Without a new rule mirroring the
  existing DNS ones (`input accept in=vlan20-mgmt ... allow mgmt_seg DHCP
  reply UDP to router`), the reply is silently dropped by the catch-all.
  This is manual RouterOS config, same TM-09 bucket as the DNS FWD rule.
- **DHCP relay is exclusive with the local DHCP server per interface** —
  unlike the DNS FWD-rule cutover (which could dual-run CoreDNS and
  Technitium indefinitely), `bridgeLocal` can't run both `/ip dhcp-server
  lan` and `/ip dhcp-relay` for the same clients at once. The cutover step
  itself is: add the `/ip dhcp-relay` entry (`interface=bridgeLocal
  dhcp-server=<technitium-ip> local-address=192.168.1.1`) and disable (not
  delete) the `lan` server in the same change. There is no safe parallel-run
  window on `bridgeLocal` itself — this is why Phase 2's live smoke test
  should prove the relay mechanism on a disposable scope/segment first.
- **New provisioning automation needed**: a scope-create + reservation-create
  pass against Technitium's REST API (exact endpoint shape still to confirm
  live — Phase 2 task), reusing the query-then-add-if-missing idempotency
  pattern the DNS zone-bootstrap flow already had to build (dns-refactor
  "Issues encountered" #6).
- **Persistent state**: DHCP scope/reservation/lease data will live in the
  same `technitium-config` Docker volume as DNS zone data — a volume loss or
  redeploy now risks both, not just DNS. `STACK_CONTRACT.md`'s Persistent
  State table needs a note to this effect once implementation starts.

## Decision 2: IPv6 (RA / prefix delegation / DHCPv6) stays on MikroTik indefinitely

Context: Technitium does not implement DHCPv6 today — it's an open, unimplemented
upstream feature request ([DnsServer#265](https://github.com/TechnitiumSoftware/DnsServer/issues/265)),
tracked by the Technitium team as "planned for a later major release." MikroTik
today owns the full IPv6 chain on `bridgeLocal`: DHCPv6-PD client on the WAN
side, prefix delegation into `default-pool`, router advertisement (ND,
`advertise-dns=yes`), and its own DHCPv6 server (`LANIPv6DHCP`,
`address-pool=static-only`).

Decision: RouterOS keeps 100% of the IPv6 role — RA, prefix delegation, and
DHCPv6 — for as long as Technitium lacks DHCPv6 support. This is not a
temporary bridge step to be revisited soon; it's a hard capability gate.
Revisit only if/when Technitium ships DHCPv6, and re-run this decision as a
new one rather than assuming today's rationale still holds.

Rationale: there is no fallback design to evaluate — Technitium literally
cannot terminate DHCPv6 or act as a PD relay today. Attempting to split RA
from DHCPv6 (e.g., RouterOS keeps RA, Technitium takes DHCPv6) is also not
possible without DHCPv6 support to begin with. IPv4 DHCP migration and IPv6
ownership are therefore fully decoupled: nothing in the IPv4 relay model above
requires or blocks any IPv6 change.

## Decision 3: First-slice scope — bridgeLocal now, Pi-holes stay the DHCP-assigned resolver, all 5 static leases migrate

Context: three genuine operator judgment calls, not resolved by research —
migration sequencing relative to future VLAN segmentation, whether
DHCP-assigned DNS should move off the Pi-holes now that Technitium is a
capable DNS+DHCP product, and how much of the static reservation set to
carry into the first migration slice.

Decision:
- **Migrate `bridgeLocal` IPv4 DHCP to Technitium now**, before any WiFi/IoT
  VLAN segmentation exists. Future client VLANs add scopes to an
  already-proven relay setup rather than deferring all Technitium DHCP
  experience until segmentation is designed.
- **DHCP-assigned DNS stays pointed at the Pi-holes** (`192.168.1.22` /
  `192.168.1.23`). Technitium's DNS role remains scoped to
  `mgmt_seg`/platform-zone authority (per the DNS refactor workspace) and
  does not take over client-LAN ad-blocking resolution — that would be new,
  unevaluated scope (blocklist parity, etc.), not a like-for-like swap.
- **All 5 current static leases migrate in the first slice**: `argon-01`
  (`192.168.1.22`), `argon-02` (`192.168.1.23`), `garuda` (`192.168.1.104`),
  `RBR350` (`192.168.1.110`), and the previously-unlabeled `raspberrypi`
  lease (`192.168.1.28`) — label it during migration rather than deferring
  it further.

Rationale: validating the relay model against the simplest real topology
first (one segment, one scope) mirrors how the DNS cutover validated on a
bootstrap zone before expanding to full parity. Keeping DNS/DHCP concerns
separate avoids scope creep into ad-blocking-policy territory this workspace
never set out to touch. Full reservation parity from day one avoids a
second migration pass over the same static-lease set later.

## Decision 4: Resiliency approach — single Technitium instance, long lease times, MikroTik kept as a break-glass fallback

Context: relay-based DHCP (Decision 1) introduces a dependency that didn't
exist before — client-LAN DHCP now depends on the Proxmox host and
`technitium-stack` being up, not just the router. Two ways to address that
were explored: (a) run a second, independent Technitium instance off
Proxmox entirely (e.g. on a Raspberry Pi) for redundancy, or (b) accept a
single instance and shrink the blast radius of an outage instead.

**Technitium clustering research (2026-07-05):** Technitium does have a real
clustering feature (introduced 2025) — primary/secondary nodes, automatic
zone sync via catalog zones, single admin console, manual promotion if the
primary dies. This works for **DNS**. It explicitly does **not** cover the
DHCP server — Technitium's own documentation lists DHCP clustering as a
known gap, "planned for a later major release" alongside a bigger DHCP
rewrite. A documented community workaround (two independent instances with
identically-configured scopes, using "Offer Delay Time" to make one
preferred) exists, but has a known defect: the non-preferred instance can't
write lease-driven DNS updates back to its own zone copy — meaning the one
DHCP/DNS-consistency benefit motivating a second node breaks specifically in
the failover scenario redundancy is meant to cover. A second instance
physically attached to `bridgeLocal`'s L2 (e.g. a Pi) would also avoid
needing relay for that specific segment — but that benefit doesn't extend
to any VLAN the second instance isn't also directly attached to, so it
doesn't generalize as segmentation grows.

Decision:
- **Single Technitium instance remains the DHCP authority** for all subnets
  (relayed via MikroTik per Decision 1). A second, Proxmox-independent
  Technitium node is not being stood up now — DHCP clustering isn't mature
  enough yet to make that node actually redundant rather than just a second
  single point of failure with extra moving parts. Revisit if/when
  Technitium's DHCP clustering ships.
- **Lease times move substantially longer than today's 30m** — this
  network's `/24` is nowhere near address exhaustion (13 leases total), so
  there's no real cost to long leases, and it directly shrinks the window in
  which a Technitium/Proxmox outage is visible: already-connected clients
  keep operating on their existing lease and only need the server again at
  renewal (~50%/87.5% of lease time), not immediately. This does **not**
  help a brand-new device joining mid-outage — that's an accepted, narrow
  residual risk, not something being engineered around.
- **MikroTik's local `lan` DHCP server stays present but disabled
  indefinitely** (not removed) as a manual break-glass fallback — if
  Technitium is ever down when a new device genuinely needs an address
  immediately, it can be re-enabled by hand for the few minutes that takes,
  rather than being decommissioned once cutover succeeds.

Rationale: a second Technitium node would add real operational cost (a
second box to patch/back up, likely outside this repo's Ansible/Terraform
automation entirely, same category as the router itself) without buying
real DHCP redundancy today, since clustering doesn't cover DHCP yet — it
would only relocate the single point of failure, not remove it. Long lease
times are a well-understood, low-cost mitigation that directly targets the
actual risk (brief Proxmox unavailability) without adding new
infrastructure. Keeping MikroTik's DHCP server disabled-but-present costs
nothing and directly covers the one residual scenario (new device,
mid-outage) that lease time can't.

### Confirmed benefit: reliable forward + reverse DNS from DHCP leases

Verified via Technitium's own documentation, not assumed: when Technitium
itself is the DHCP server (true here, since MikroTik only relays) and the
DHCP domain name option plus a reverse zone are configured, Technitium
automatically creates **both** the forward (A) and reverse (PTR) DNS record
for a client the moment it's leased an address — natively, with no separate
script or DDNS bridge needed. (A third-party MikroTik-to-Technitium bridge
script exists for people trying to bolt this onto an *external* DHCP server,
but that's not this design, since Technitium is the DHCP server itself.)
This makes "every device on the network resolves both ways" a real,
low-effort property of this design, not aspirational.

## Decision 5: `network_mode: host` for `technitium-stack`'s container — narrow, DHCP-only exception

Context: Decision 1 accepted, as a known cost, that Technitium's Docker
bridge networking means it reports its own Docker-internal IP
(`172.19.0.2`) as the DHCP server-identifier instead of its real,
externally-reachable LXC address (confirmed live, `stage-a-execution.md`
Issue 12). Effect: every client's unicast RENEW at T1 targets an
unreachable address and silently fails, always falling through to broadcast
REBIND at T2 instead. Not a connectivity risk (REBIND is proven working),
but not clean either. Revisiting this cost, two fixes were compared:
dropping Docker entirely for a native LXC install (Decision 1's "deferred"
option), versus keeping the container but switching its Docker networking
mode.

Re-examining Decision 1's original reasons for rejecting `network_mode:
host` against this stack's *actual* topology (not the general case):
- "Binds to privileged ports" — ports 53 and 67 are already exposed via
  explicit `ports:` publishing today; host networking doesn't newly expose
  anything.
- "Loses container network isolation" — from what? This LXC runs exactly
  one container. There is no sibling container on `technitium-stack` for
  isolation to matter against.
- "Can't disambiguate multiple host IPs" — doesn't apply; the LXC has
  exactly one NIC, on `mgmt_seg`.

All three original objections were written as general platform-consistency
reasoning, not as concrete risks specific to this stack — and they don't
hold up once checked against `technitium-stack`'s real, single-interface,
single-container shape.

Decision: `technitium-stack`'s Technitium container switches from bridge
networking + explicit port publishing to `network_mode: host`. This is a
**narrow, single-stack exception**, not a new default:
- Every other Docker-based stack in this repo (`docker_base` /
  `deployment_tier: platform` and `apps` alike) keeps standard bridge
  networking with explicit port publishing. `network_mode: host` is not
  authorized for any other stack without its own documented decision
  following this same reasoning — a stack needs a concrete, checked
  justification (like Technitium's DHCP server-identifier requirement), not
  "it's simpler," to adopt it.
- `terraform/lxc/PLATFORM_CONTRACT.md` gets a one-line guardrail pointing
  back here, so a future stack author doesn't copy this as if it were an
  established pattern.
- `technitium-stack/STACK_CONTRACT.md` gets an explicit note on *why* this
  one stack deviates from the rest of the platform-tier convention.

Rationale: this closes Issue 12 properly (Technitium binds directly to the
LXC's real interface, so it reports its actual reachable IP as
server-identifier, and RENEW at T1 will succeed instead of always failing
over to REBIND) with a one-line, easily-reversible compose change —
`network_mode: host` in place of the `ports:` list — rather than the much
larger step of dropping Docker/Harbor-pull/Compose lifecycle for the whole
stack (Decision 1's "native LXC" option). It keeps `technitium-config`'s
Docker volume, the Harbor image-pull path, and every other stack's
established Docker Compose lifecycle unchanged. The isolation/multi-IP
concerns that justified rejecting this option in the abstract (Decision 1)
don't actually describe a risk this specific stack has.

Concrete implementation (tracked as a plan.md Stage B task, not yet
applied):
- `deploy-technitium-stack.yml`'s compose template: replace the `ports:`
  list (`53:53/udp`, `53:53/tcp`, `5380:5380/tcp`, `67:67/udp`) with
  `network_mode: host`. No other compose fields change — the
  `technitium-config` named volume, environment file, and image reference
  are unaffected.
- `stack.yaml`'s `provides:` list and `STACK_CONTRACT.md`'s Provides table
  still need the new `dhcp-server` (udp/67) entry — host networking doesn't
  remove that requirement, it just changes how the port gets exposed.
- `STACK_CONTRACT.md` gains a short note explaining the host-networking
  deviation and linking back to this decision.
- Re-run Stage A's live validation after this change, specifically
  re-checking the DHCP lease's `dhcp-server-identifier` value now reports
  the real `mgmt_seg` IP (not a Docker-internal address) and that a real
  unicast RENEW at T1 succeeds — this is an empirical claim, not something
  to assume true just because the network path is now direct.
- Traefik's route to Technitium's admin UI (`technitium.${LAB_DOMAIN}` via
  `edge.yaml`) and the `edge_seg → mgmt_seg tcp/5380` firewall policy are
  both unaffected — they already target the LXC's real IP:5380 directly;
  host networking doesn't change what's listening on that port or from
  where it's reachable.

### Incident (2026-07-06): first deploy attempt landed on production, not `pve-test-vm`

While attempting to apply this decision to `pve-test-vm` via
`PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack
technitium-stack --target-env pve-test-vm`, the deploy actually landed on
**production** instead. Root cause: `terraform/lxc/stacks/technitium-stack/`
has never been migrated to the per-environment Terragrunt layout (no
`terraform/lxc/environments/pve-test-vm/technitium-stack/` directory
exists), so `scripts/provision.sh` fell back to the single, non-environment-
scoped `terraform/lxc/stacks/technitium-stack/inventory.yml` — which still
held connection details (`ansible_host: 192.168.20.15`,
`pve_host: pve.gibbsgreatly.xyz`) from whenever Terraform was last applied
for `pve`. Setting `PVE_ENV=pve-test-vm` correctly selected
`.env.pve-test-vm`'s variable *values*, but did nothing to correct *which
host* Ansible actually connected to — **`--target-env` does not verify the
inventory it's about to use actually matches the named environment.**

Consequence: production's Technitium container was recreated with
`network_mode: host` (undoing that required a proper revert via
`./with-secrets-prod`, executed with operator approval), and — separately —
the same run's env-derived values (`DNS_SERVER_DOMAIN=tech.test.gibbsgreatly.xyz`,
`.env.pve-test-vm`'s dev `TECHNITIUM_ADMIN_PASSWORD`) got baked into
production's container definition, which correlates with a subsequent
production incident: Technitium's Authentik OIDC login broke ("Failed to
reach SSO provider"). Both were fixed by an explicit, approved
`./with-secrets-prod` redeploy restoring production's correct environment
and reverting the network mode change. Zone data was never at risk (it
lives in the `technitium-config` Docker volume, untouched by either
redeploy), and `pve-test-vm`'s own Technitium container was **never actually
touched** by any of this — Stage A's real test instance is unaffected, but
also means Decision 5 is still **completely unvalidated** in practice.

**Before attempting this again**: either give `technitium-stack` a proper
`environments/pve-test-vm/technitium-stack/` Terragrunt layout (matching
whatever other stacks already migrated to that pattern use), or manually
verify `terraform/lxc/stacks/technitium-stack/inventory.yml`'s
`ansible_host`/`pve_host` fields match the intended target environment
immediately before running `scripts/provision.sh` — do not trust
`--target-env` alone to guarantee this. This is a repo-wide gap (affects
any stack not yet on the per-environment layout), not specific to
Technitium or DHCP — worth raising separately from this workspace.

**Resolution (2026-07-06/07, same session):** two fixes applied before
retrying. (1) `scripts/provision.sh` now hard-fails via
`assert_inventory_matches_env()` if a stack's inventory `pve_host` doesn't
match `PVE_ENV`, for stacks with an SDN `network:` zone. (2) Correctly-
scoped `inventory.yml` files were manually placed under
`terraform/lxc/environments/{pve,pve-test-vm}/technitium-stack/` —
hand-written, not Terraform-generated, an interim stopgap only. With both
in place, a `--check` dry run then a real run correctly resolved to
`environments/pve-test-vm/technitium-stack/inventory.yml` and reached
`pve-test-vm` (`192.168.20.115`), confirmed via the smoke test resolving
`test.gibbsgreatly.xyz` names. `network_mode: host` is now live on the
actual Stage A test container (`docker inspect` confirms
`NetworkMode=host`), and the fix is empirically validated: a forced lease
renewal shows `dhcp-server-identifier: 192.168.20.115` (Technitium's real
IP), and a `tcpdump` capture of the T1 renewal shows a direct **unicast**
exchange (`192.168.90.61.68 > 192.168.20.115.67`, not broadcast) —
confirming the clean RENEW that was previously impossible. **Issue 12 is
genuinely closed for this instance.**

The real structural fix (giving `technitium-stack` a proper per-environment
Terragrunt layout, replacing both the guardrail and the manual stopgap
files) is intentionally scoped out as its own task — see
[docs/environment-isolation/](../environment-isolation/), opened
2026-07-07.

## Decision 6: Production lease time — 7 days

Context: Decision 4 settled the *strategy* (lease times move "substantially
longer than today's 30m") but never picked a concrete number. Stage B's
plan.md step 4 asks for this to be folded in as a declarative config-as-code
parameter.

Decision: the real `bridgeLocal` scope (Stage E, not yet built) will use
`leaseTimeDays=7, leaseTimeHours=0, leaseTimeMinutes=0`. Recorded now in
`configure-technitium-dhcp-scope-via-api.yml` as
`dhcp_production_lease_days`/`_hours`/`_minutes` — documentary only today,
since no `bridgeLocal` scope-management task exists before Stage E, but
this removes an open TBD from that future work.

Rationale: the current network (13 leases total on a `/24`) is nowhere
near address exhaustion, so there's no cost to a long lease. Seven days is
long enough that even a multi-hour Proxmox/Technitium outage never affects
an already-connected client (Decision 4's actual goal), while still being
short enough that a device that's genuinely gone (replaced, decommissioned)
frees its address within a human-reasonable timeframe rather than tying it
up indefinitely. Revisit if real-world experience after Stage E suggests a
different value; this is a config value, not a structural commitment.

## Decision 7: `configure-technitium-dhcp-scope-via-api.yml` stays a standalone playbook

Context: `docs/dhcp-refactor/README.md`'s "Immediate next step" flagged an
open question — should this playbook merge into
`deploy-technitium-stack.yml`'s main flow, or stay separate?

Decision: stays standalone for now.

Rationale: `deploy-technitium-stack.yml` is the stable, already-cut-over-to-
production DNS deploy path; folding a still-evolving, currently test-VLAN-
only DHCP concern into it would couple that stable path to work that isn't
done yet (Stage D's dynamic-lease policy is still undecided, and Stage E's
real `bridgeLocal` scope doesn't exist). Revisit this once Stage E's real
scope management is designed — at that point there may be a real argument
for folding DHCP scope reconciliation into the main deploy flow the same
way DNS zone bootstrap already is, but that's a decision for Stage E, not
now.

### Idempotency proof (2026-07-07): scope reconciliation + reservation list, both confirmed live

Rewrote the playbook to close a real gap found while reviewing it for
Stage B: the original version's scope-create task only fired on absence
(`when: name not in [...]`), so a declared value change after the scope
already existed would silently never reach the live scope on a re-run —
exactly `stage-a-execution.md` Issue 7's bug shape, which had needed a
one-off manual API call to fix in place. The rewritten version reads the
scope's current config, diffs it against the declared values (subnet,
lease time, domain), and calls `scopes/set` whenever any field differs —
not just on first creation.

Also converted the single hardcoded test-client reservation into a
declarative `dhcp_reservations` list, and added 5 fake reservations shaped
like the real `bridgeLocal` static leases (`fake-argon-01`, `fake-argon-02`,
`fake-garuda`, `fake-rbr350`, `fake-raspberrypi`, using locally-administered
`02:xx` MACs that can never collide with a real device) — proving the
list/loop mechanism handles more than one reservation before Stage E ever
points this shape at a real scope, per plan.md Stage B step 3's explicit
ask.

Ran live against `pve-test-vm`'s real Stage A scope twice:
- **First run**: scope config already matched declared values (no drift —
  `skipping` on the reconcile task), the 5 fake reservations were newly
  added, the real test client's reservation was already present.
- **Second run**: `changed=0` across the board — scope reconcile skipped
  (no drift), all 6 reservations skipped (all already present). Confirmed
  via direct API read afterward: `scopes/get` shows all 6 reservations with
  correct hostname/MAC/IP, and `leaseTimeDays/Hours/Minutes: 0 0 10`
  matching the declared test values exactly.

DNS resolution wasn't checked for the 5 fake reservations — a reservation
alone doesn't trigger Technitium's dynamic DNS update, only an actual
issued lease does (already proven separately for the real test client in
Stage A). That's expected, not a gap.

## Deferred: multi-instance DHCP resiliency (come back to later)

Not a decision — deliberately parked, so the idea and the supporting
research aren't lost between now and whenever it's revisited. Decision 4
above settled on a single Technitium instance for the first migration; this
section documents a real way to do better, found after Decision 4 was
written, which changes that trade-off if/when a second box is on the table.

**The mechanism (verified against RouterOS's actual behavior, not assumed):**
`/ip dhcp-relay`'s `dhcp-server` field accepts a comma-separated list of
addresses, e.g. `dhcp-server=192.168.20.15,192.168.1.50`. RouterOS does
**not** pick one as primary — it forwards every DHCP request to **all**
listed servers simultaneously, and the client uses whichever offer arrives
first. This means two independent Technitium instances (e.g. the existing
Proxmox one plus a second instance on a Raspberry Pi, physically on
`bridgeLocal` or elsewhere) can both be relay targets, giving real
redundancy — if one is down, the other still answers — without needing
Technitium's own DHCP clustering at all.

To make behavior deterministic (one instance normally preferred, rather than
a race that could land DNS updates on either instance unpredictably), pair
this with Technitium's per-scope **"Offer Delay Time"** setting: give the
preferred instance a short delay (default) and the standby a longer one, so
the standby only answers when the preferred instance doesn't.

**Why this is deferred rather than adopted now:**
- The two scopes still don't sync automatically — Technitium's clustering
  covers DNS zone data, not DHCP scope/reservation config, so both instances'
  DHCP config would need to be maintained by hand (or a small sync script).
- The DNS-consistency gap from Decision 4's clustering research still
  applies here: if the standby instance is also a DNS-cluster secondary,
  secondaries are read-only followers of the primary's zone data — exactly
  why a secondary can't write its own DHCP-driven DNS updates into that zone.
  So in the specific window the standby is the one issuing leases, the
  "device joins → DNS just works" property degrades until the preferred
  instance is back.
- It's still a second box to patch, back up, and monitor — real ongoing
  cost, not a one-time setup task.

**Revisit this when:** the single-instance + long-lease-time + break-glass
MikroTik approach (Decision 4) has been lived with for a while and the
Proxmox-dependency risk still feels worth addressing, or when Technitium
ships native DHCP clustering (removing the two caveats above). If revisited,
this supersedes Decision 4's "single instance" choice — write a new decision
rather than editing Decision 4 in place.

## Format

```markdown
## Decision N: Title

Context: why this needed a decision, what constraint or trade-off forced it.

Decision: the actual choice, stated as a fact, not a discussion.

Rationale: why this option over the alternatives considered.
```

## Pending (tracked in plan.md's Phase 3 stages)

- ~~`network_mode: host` switch~~ (Decision 5, plan.md Stage B0) — **done
  and empirically validated (2026-07-06/07)**, including a `tcpdump`-
  confirmed unicast RENEW against the real `pve-test-vm` instance.
- ~~DHCP configuration as code~~ (plan.md Stage B) — **done (2026-07-07)**:
  `configure-technitium-dhcp-scope-via-api.yml` now reconciles scope drift
  (not just existence) and handles a declarative reservation list, proven
  idempotent (`changed=0` on a second run) against the real `pve-test-vm`
  scope, including 5 fake reservations shaped like the real `bridgeLocal`
  static leases. `STACK_CONTRACT.md`'s Persistent State table is updated.
  See Decision 6 (production lease time) and Decision 7 (standalone
  playbook) above.
- ~~Teardown-test harness prep~~ and ~~the destructive `cycle` run
  itself~~ (plan.md Stage C) — **fully done (2026-07-12)**. Prep
  (2026-07-07): fixed a pre-existing `classify-storage-plan.py` bug that
  misclassified every Terraform no-op as blocked (affected every stack, not
  just this one), added `technitium-stack` to the teardown inventory and
  `.env` template aliases, and wired both a DHCP scope reconcile (into
  deploy) and a lease-correctness check into the stack's own validation.
  `dhcp-test-client-01` deliberately stays out of the platform inventory
  (workspace-local fixture, not a platform dependency). The destructive
  full 12-stack `cycle` run (2026-07-12, explicit operator approval given)
  found five real bugs on its first attempt — none DHCP-specific, all
  platform bootstrap-ordering/Ansible variable-scoping issues a genuine
  cold full-cycle run was the first thing to ever exercise: `technitium-
  stack`'s image pull routed through Harbor before Harbor/Traefik existed
  in the deploy order; the DHCP lease check raced `dhclient`'s backoff
  instead of forcing a deterministic renewal; the harness's nameserver-list
  `-e` argument never actually produced a list; `authentik-stack`'s Harbor
  pre-pull gating trusted a TCP:80 check that doesn't prove authenticated
  registry access; and a role-vars shadowing bug in `deploy-harbor-
  stack.yml` defeated the guard against permanently blocking Harbor's OIDC
  auth-mode migration. All five fixed and validated live (see
  `plan.md`'s Stage C section for detail and commit references). A second,
  completely fresh full cycle then passed clean end to end — first time
  ever with `technitium-stack` included.
- **Dynamic-lease policy** (plan.md Stage D): `current-state.md` records 13
  total current leases — 5 static (covered by Decision 3) and **8
  dynamic**, which this plan hasn't yet addressed. Needs an explicit,
  reviewed decision on which (if any) of the 8 get promoted to reservations
  before cutover, and a defined stale-DNS-record cleanup procedure for the
  rollback case (Technitium may have already registered forward/reverse DNS
  entries for dynamic clients before a rollback is triggered). Not yet
  decided — this is a genuine operator call, not something to resolve
  unilaterally in this doc.
- Cutover/rollback mechanics for the relay repoint itself (add DHCP relay
  config item on MikroTik pointed at Technitium vs. disabling the local
  `lan` server) — now has a concrete stage (plan.md Stage E) with explicit
  rollback trigger thresholds and a post-rollback cleanup checklist, but the
  actual packet (`bridgelocal-cutover-packet.md`) isn't written yet — it's
  a Stage E deliverable, gated on Stages A–D being green.
- ~~Renewal/rebind behavior across the cutover moment itself~~ — **done.**
  The simulated-cutover test (plan.md Stage A, `stage-a-execution.md`'s
  "Stage A's last validation check") rehearsed exactly this: a client with
  an existing MikroTik-issued lease, after MikroTik is switched to
  relay-only, gets cleanly `DHCPNAK`'d and immediately re-acquires its
  correct lease. No hang, no manual intervention required.
