# Stage A — Practical Execution Notes

This is the concrete execution companion to [plan.md](./plan.md)'s
"Stage A — Isolated mechanism proof on a brand-new VLAN". It is intentionally
short and only covers the next practical actions for the throwaway VLAN test.

## Chosen topology

- VLAN: `90`
- Zone name: `test_dhcp_seg`
- Subnet: `192.168.90.0/24`
- MikroTik gateway / relay `local-address`: `192.168.90.1`
- Technitium DHCP server (`pve-test-vm`): `192.168.20.115`
- Disposable client bootstrap IP: `192.168.90.61`

## Important execution rule

The disposable client boots **statically** first because the current Terraform
LXC path is static-IP-first. Before flipping the guest to DHCP, create the
Technitium reservation for the client's MAC using the **same address**
`192.168.90.61`.

That keeps the address stable across the DHCP flip: after reboot, the client
should still come back on `192.168.90.61`, but now as a DHCP lease rather
than a statically-configured guest address. This is about keeping validation
simple (the same known address to check for in lease/interface output), not
about SSH — routed SSH to the guest never worked at all (see Issues 2–5
below); management and validation are entirely via `pct exec` from
`pve-test-vm`, not guest SSH.

## Repo artifacts already prepared

- Network intent: [terraform/lxc/network/pve-test-vm.yaml](../../terraform/lxc/network/pve-test-vm.yaml)
- Zone-members index: [terraform/lxc/network/pve-test-vm.zone-members.yaml](../../terraform/lxc/network/pve-test-vm.zone-members.yaml)
- Disposable client stack: [terraform/lxc/stacks/dhcp-test-client-01/stack.yaml](../../terraform/lxc/stacks/dhcp-test-client-01/stack.yaml)
- DHCP flip helper: [terraform/lxc/ansible/playbooks/configure-dhcp-test-client-via-pct.yml](../../terraform/lxc/ansible/playbooks/configure-dhcp-test-client-via-pct.yml)
- DHCP validation helper: [terraform/lxc/ansible/playbooks/validate-dhcp-test-client-via-pct.yml](../../terraform/lxc/ansible/playbooks/validate-dhcp-test-client-via-pct.yml)

The disposable client stack is marked with `network.access_path:
proxyjump_compat`, which was the first attempted fix (route Ansible SSH via
the Proxmox host as a jump, rather than assuming the workstation has direct
routing into the throwaway VLAN). That didn't work either — the `pve-test-vm`
host itself has no routed path into `192.168.90.0/24`, so even a ProxyJump
can't open TCP/22 to the guest (see Issues 2–5 below). At this point
`proxyjump_compat` is mostly historical/debug context, not part of the
working Stage A control path: guest management and validation are entirely
via `pct exec` through Proxmox, with no SSH to the guest at all.

## Expected MikroTik-side objects

- VLAN interface: `vlan90-test-dhcp`
- IP: `192.168.90.1/24`
- DHCP relay interface: `vlan90-test-dhcp`
- DHCP relay target: `192.168.20.115`
- Firewall allow: UDP DHCP reply from `vlan20-mgmt` / Technitium to the router

## Progress so far

Completed:

- Added the additive Stage A VLAN and zone to
  `terraform/lxc/network/pve-test-vm.yaml`.
- Added the disposable client stack `dhcp-test-client-01` with bootstrap
  address `192.168.90.61`.
- Regenerated the `pve-test-vm` zone-members index with the new test segment.
- Confirmed the client container provisions successfully on `pve-test-vm`
  as CT `138`.
- Confirmed the guest boots cleanly with `eth0=192.168.90.61/24`,
  default route `192.168.90.1`, and `sshd` listening.
- Confirmed the MikroTik relay work is scoped to the throwaway VLAN rather
  than changing DHCP behavior for any other segment.
- Guest flip from static networking to DHCP (in-guest `/etc/network/interfaces`
  side) — done, but needed a second fix; see Issue 6 below.
- Diagnosed and fixed a Proxmox-level bug (Issue 6) that silently reverted
  the in-guest DHCP flip back to static on every `pct reboot`.
- Confirmed post-fix: `/etc/network/interfaces` persists as `iface eth0 inet
  dhcp` across a reboot, and `dhclient` is actively broadcasting
  `DHCPDISCOVER` on `eth0` (retrying with normal backoff) — client-side
  networking and the relay path to Technitium are both confirmed healthy.
- Built `configure-technitium-dhcp-scope-via-api.yml`, an idempotent
  playbook (same query-then-create-if-missing pattern as the DNS zone
  bootstrap flow) that creates the `test_dhcp_seg` scope
  (`192.168.90.50`–`192.168.90.99`), the forward zone
  (`dhcp-test.test.gibbsgreatly.xyz`) and reverse zone
  (`90.168.192.in-addr.arpa`), and the reservation for the test client's MAC
  at `192.168.90.61`. Ran it live and confirmed all four exist correctly via
  direct API queries.
- Found and fixed four bugs total while getting a real lease to actually
  issue — see Issues 7–10 below. All four are now fixed, both in the
  committed source and applied live on `pve-test-vm`.
- **A real lease now issues end-to-end.** `dhclient -v eth0` on the test
  client shows `DHCPOFFER of 192.168.90.61 from 192.168.90.1` →
  `DHCPACK of 192.168.90.61 from 192.168.90.1` → `bound to 192.168.90.61`.
  Confirmed via `ip addr`/`ip route`/`resolv.conf` on the guest: address
  `192.168.90.61/24` (`dynamic` flag, not static), default route
  `192.168.90.1`, domain/search `dhcp-test.test.gibbsgreatly.xyz`,
  nameserver `192.168.90.1` — all matching the scope's configured options.
- **Forward and reverse DNS both confirmed working**, not just configured:
  `dig @<technitium-ip> dhcp-test-client-01.dhcp-test.test.gibbsgreatly.xyz`
  returns `192.168.90.61`, and `dig @<technitium-ip> -x 192.168.90.61`
  returns `dhcp-test-client-01.dhcp-test.test.gibbsgreatly.xyz.` — the
  Decision 4 "reliable reverse DNS" capability is now empirically verified,
  not just researched.

Not done yet:

- Nothing — **Stage A is fully complete.** Restart/renew, brief-outage
  recovery, and the simulated-cutover renew/rebind check are all done too;
  see "Findings from the rest of Stage A's validation list" and "Stage A's
  last validation check" below. The one open item is Issue 12 (Technitium's
  Docker server-identifier limitation), which is accepted and deferred, not
  something blocking further work.

## Issues encountered

1. The current Terraform/LXC abstraction is static-IP-first.

   The stack module always provisions a fixed `ip_address`, so a "boot directly
   on DHCP" disposable client is not currently expressible in the normal stack
   metadata. The chosen workaround is still valid: bootstrap the client
   statically, then flip it in-guest after the reservation exists.

2. Direct Ansible SSH from the workstation to `192.168.90.61` does not work.

   This initially failed as `No route to host`, which showed the workstation
   cannot directly reach the throwaway VLAN.

3. Switching generated inventory to `ProxyJump` was necessary, but still not
   sufficient.

   After setting `network.access_path: proxyjump_compat`, the inventory
   correctly used `ProxyJump=root@pve-test-vm.gibbsgreatly.xyz`, but the SSH
   connection still failed (`Connection closed by UNKNOWN port 65535`). Manual
   checks showed the underlying reason: `pve-test-vm` itself does not have a
   routed path into `192.168.90.0/24`, so the jump host cannot open TCP/22 to
   the guest either.

4. The guest itself was not the problem.

   Manual `pct exec` inspection from `pve-test-vm` confirmed the container is
   running, `eth0` holds the expected static bootstrap address, the default
   route is present, and `sshd` is listening. The management path was wrong;
   the guest was healthy.

5. Stage A helper playbooks had to be reworked around `pct exec`.

   The durable correction is to manage and validate the client via Proxmox
   (`pct exec`, `pct reboot`) instead of relying on routed guest SSH.

6. The in-guest DHCP flip silently reverted to static on every reboot —
   root cause was at the Proxmox level, not the guest.

   First live attempt: `configure-dhcp-test-client-via-pct.yml` reported
   success (rewrote `/etc/network/interfaces` to `iface eth0 inet dhcp`,
   rebooted), but `validate-dhcp-test-client-via-pct.yml` immediately failed
   — the file was back to `inet static` with the original bootstrap address.

   Root cause, confirmed empirically (not guessed): `pct config 138`'s
   `net0:` line still had `ip=192.168.90.61/24,gw=192.168.90.1` — the
   container's Proxmox-level network config never stopped being static, only
   the in-guest file was edited. Proxmox re-templates
   `/etc/network/interfaces` directly into the container's filesystem at
   every container start/reboot whenever net0's `ip=` is a literal static
   address rather than the string `dhcp` — this happens host-side, before
   the guest's own init even runs (confirmed via `stat`: the interfaces
   file's mtime was a fraction of a second *before* the guest's own
   `systemd-journald` "Journal started" line for that boot). The `net0`
   field `host-managed=0` looked at first like it should have prevented
   this (per Proxmox's own docs, `host-managed` controls whether the *host*
   manages the interface's IP config) — but empirically, the static-`ip=`
   templating happens regardless of that flag; `host-managed` evidently
   governs something narrower and does not substitute for setting `ip=dhcp`
   itself.

   Fix: `configure-dhcp-test-client-via-pct.yml` now reads the container's
   current `net0:` line, strips `gw=...` and replaces `ip=<static>` with
   `ip=dhcp`, and applies it via `pct set` — *before* the reboot task, so
   Proxmox's own container-start logic stops reasserting the static config.
   Verified live: after this fix, `/etc/network/interfaces` persists as
   `inet dhcp` across a reboot, `net0:` shows `ip=dhcp` with `gw=` dropped,
   and `dhclient` is confirmed (via `journalctl`) actively broadcasting
   `DHCPDISCOVER` on `eth0`. No lease yet, but that's the separate,
   already-tracked "Technitium scope doesn't exist yet" blocker, not this
   bug recurring.

   **Correction to a claim made in this doc at the time**: it was assumed
   `dhclient`'s retry loop would keep trying indefinitely in the background,
   so a lease would appear on its own once the scope existed, with no further
   action needed. That's wrong — `dhclient` invoked via `ifupdown` gives up
   after a bounded number of attempts (observed: about 6 discovers over
   roughly a minute) and then exits, leaving the interface configured but
   addressless. Getting a lease after the scope/reservation exist requires a
   fresh trigger (`dhclient eth0`) or another reboot, not just waiting.

7. Technitium's DHCP scope defaulted to a ~1 day lease despite only setting
   `leaseTimeMinutes=10`.

   `configure-technitium-dhcp-scope-via-api.yml`'s first live run created
   the scope successfully, but `scopes/get` afterward showed
   `leaseTimeDays: 1` even though `leaseTimeDays` was never passed in the
   `scopes/set` call. Technitium defaults an unspecified `leaseTimeDays` to
   `1` on scope creation — the real lease was 1 day + 10 minutes, not the
   short test lease intended for observing renew/outage behavior quickly.

   Fix: the playbook now explicitly passes `leaseTimeDays=0` alongside
   `leaseTimeHours=0` and `leaseTimeMinutes=10`. Applied directly to the
   already-created live scope (the playbook's `when:` guard skips
   re-creating a scope that already exists, so the fix had to be pushed via
   a direct `scopes/set` call this one time) and confirmed via `scopes/get`:
   `leaseTimeDays: 0, leaseTimeHours: 0, leaseTimeMinutes: 10`.

8. Technitium's Docker container never actually published port `67/udp`.

   Even with a correctly configured, enabled scope and a working relay
   path, the test client's `dhclient` got "No DHCPOFFERS received" every
   time. `docker port technitium` on the live `pve-test-vm` instance showed
   only `53/tcp`, `53/udp`, and `5380/tcp` published — `67/udp` was missing.
   This is decisions.md Decision 1's "concrete change inventory" item 1
   (add `67:67/udp` to the compose ports), which was written down as a
   planned change but never actually implemented in
   `deploy-technitium-stack.yml`.

   Fix: added `"67:67/udp"` to the compose template in
   `deploy-technitium-stack.yml`, syntax-checked it, then applied the same
   change directly to the live container's `docker-compose.yml` and
   recreated it (`docker compose up -d --force-recreate`). Confirmed
   `docker port technitium` now lists `67/udp -> 0.0.0.0:67`, and confirmed
   the scope/zones/reservation all survived the recreate (they live in the
   `technitium-config` named volume, not the container's ephemeral
   filesystem).

9. The MikroTik firewall rule allowing Technitium's DHCP reply exists, but
   was unreachable — **fixed**.

   Even after fixes 7 and 8, `dhclient` still got no offer. Direct
   inspection of the router's REST API (`/rest/ip/firewall/filter`) showed
   the Decision-1 rule (`input accept in=vlan20-mgmt proto=udp dport=67 ...
   Stage A allow Technitium DHCP reply to router`) does exist — but it was
   appended at the very end of the rule list, **after** the catch-all
   `input drop — Drop all other unhandled input traffic` rule. RouterOS
   firewall rules evaluate top-to-bottom and stop at the first match, so
   the catch-all drop silently eats the reply before the chain ever reaches
   the specific allow rule below it.

   Fix: moved rule `*2D` ("Stage A allow Technitium DHCP reply to router")
   to sit immediately before rule `*1E` ("Drop all other unhandled input
   traffic"), matching where the other per-VLAN allow rules already sit:

   ```bash
   eval "$(./with-secrets env | grep -E '^MIKROTIK_(USER|PASSWORD)=' | sed 's/^/export /')"
   curl -sf -k -u "${MIKROTIK_USER}:${MIKROTIK_PASSWORD}" -X POST \
     -H "Content-Type: application/json" \
     -d '{"numbers": "*2D", "destination": "*1E"}' \
     "https://192.168.1.1/rest/ip/firewall/filter/move"
   ```

   Applied and confirmed live: rule `*2D` now sits at position 17 (right
   before `*1E` at position 18) in the `input` chain. This alone was not
   enough to get a lease — see Issue 10.

10. The throwaway VLAN's bridge trunk tagging was incomplete — **fixed,
    and this was the actual last blocker**.

    Even with fixes 7–9 all applied, `dhclient` still got zero response —
    not even a dropped/rejected packet, literally nothing: a `tcpdump -i
    eth0 port 67` run directly inside the Technitium container while
    triggering a fresh `DHCPDISCOVER` captured **zero packets**, meaning
    the client's broadcast wasn't reaching Technitium's interface at all.
    That ruled out the relay, the scope, the firewall, and Technitium
    itself — the problem had to be upstream, in how VLAN 90's traffic
    physically crosses the trunk between the router and Proxmox.

    Root cause, found by comparing `/interface bridge vlan print detail`
    across all 5 VLANs: VLANs 10/20/30/40 each have a **static** bridge-vlan
    entry tagging `bridgeLocal,ether1,ether5` (`ether1`/`ether5` being the
    physical trunk ports to Proxmox). VLAN 90 had only an auto-generated
    **dynamic** entry (`comment: "added by vlan on bridge"`) tagging
    `bridgeLocal` alone — created automatically when the `/interface vlan`
    object was added, but never extended to the trunk ports the way the
    other 4 VLANs explicitly were. That meant VLAN-90-tagged frames never
    actually crossed the physical trunk in either direction — not a relay,
    firewall, or Technitium problem at all, just an incomplete L2 setup
    from the start.

    Fix: added a new static bridge-vlan entry mirroring the working VLANs
    exactly, additive only — it does not reference or modify the `.id`s for
    VLANs 1/10/20/30/40:

    ```
    /interface bridge vlan add bridge=bridgeLocal vlan-ids=90 tagged=bridgeLocal,ether1,ether5 comment="Stage A DHCP test VLAN trunk tagging"
    ```

    Verified two ways before and after: a full snapshot diff of
    `/rest/interface/bridge/vlan` confirmed VLANs 1/10/20/30/40 are
    byte-for-byte unchanged, and VLAN 90's new entry shows
    `current-tagged: bridgeLocal,ether1,ether5` (previously `bridgeLocal`
    only).

    **This was the actual last blocker.** Immediately after this fix,
    `dhclient -v eth0` on the test client produced a full, successful
    negotiation: `DHCPOFFER of 192.168.90.61 from 192.168.90.1` →
    `DHCPACK of 192.168.90.61 from 192.168.90.1` → `bound`. Forward and
    reverse DNS both confirmed resolving correctly for the leased address
    immediately afterward.

## Findings from the rest of Stage A's validation list

With first-lease-issuance proven (Issues 7–10), the remaining plan.md Stage A
checks — restart/renew, brief-outage recovery, and simulated cutover — turned
up two more real findings.

11. VLAN 90 had no ICMP allow rule to the router at all — same class of bug
    as Issue 9, found while testing outage recovery.

    Testing brief-outage recovery (stop Technitium, confirm the client
    handles it gracefully) surfaced a confusing symptom: with Technitium
    down, `dhclient -1 -v eth0`'s fallback logic tried to ping the recorded
    lease's gateway (`192.168.90.1`) before deciding whether to keep using
    it — and got 100% packet loss, even though the router itself was
    confirmed reachable via its REST API the whole time. Comparing
    `/ip firewall filter print` against the other 4 VLANs showed why:
    VLANs 10/20/30/40 each have an explicit `input accept in=vlan<N>
    proto=icmp` rule; VLAN 90 had none at all. Any ICMP to the router from
    that segment — including `dhclient`'s own sanity-check ping — hit the
    catch-all `input drop` rule.

    Fix: added a new rule mirroring the existing per-VLAN pattern, then
    moved it before the catch-all drop (applying the Issue 9 lesson
    immediately this time, not after a second failed attempt):

    ```bash
    eval "$(./with-secrets env | grep -E '^MIKROTIK_(USER|PASSWORD)=' | sed 's/^/export /')"
    curl -sk -u "${MIKROTIK_USER}:${MIKROTIK_PASSWORD}" -X PUT \
      -H "Content-Type: application/json" \
      -d '{"chain": "input", "action": "accept", "in-interface": "vlan90-test-dhcp", "protocol": "icmp", "src-address": "192.168.90.0/24", "dst-address": "192.168.90.1", "comment": "Stage A allow test_dhcp_seg ICMP to router"}' \
      "https://192.168.1.1/rest/ip/firewall/filter"
    # then move it before the catch-all drop rule, same as Issue 9
    ```

    One mechanical note for future MikroTik REST work: creating a *new*
    firewall filter entry needs `PUT`, not `POST` — `POST` to
    `/rest/ip/firewall/filter` returns `{"detail":"no such command"}`. The
    `/rest/ip/firewall/filter/move` *action* endpoint is POST, as before;
    it's specifically the collection-create call that's PUT.

    With the rule in place and positioned correctly, the ping succeeded,
    and re-running the outage test showed the client correctly falling back
    to its recorded lease (`Trying recorded lease 192.168.90.61` → ping
    succeeds → `bound: immediate renewal`) instead of giving up and
    dropping its address — the resiliency behavior Decision 4's long-lease
    strategy actually depends on.

12. Technitium reports its own Docker-internal IP as the DHCP
    server-identifier, not its real address — a confirmed upstream
    limitation, not a config mistake here.

    The client's lease file (`/var/lib/dhcp/dhclient.leases`) recorded
    `option dhcp-server-identifier 172.19.0.2;` — and `docker inspect
    technitium` on `pve-test-vm` confirms `172.19.0.2` is exactly
    Technitium's address on its own internal `technitium-stack_default`
    Docker bridge network, not the LXC's real, externally-reachable IP
    (`192.168.20.115`). Confirmed via upstream discussion
    ([DnsServer#1654](https://github.com/TechnitiumSoftware/DnsServer/discussions/1654))
    that this is a known limitation of running Technitium's DHCP server
    behind Docker's normal bridge networking with port publishing: the
    server has no way to know its own externally-reachable address is
    different from what its own network stack reports, and there's no
    documented API parameter (checked `APIDOCS.md`'s full `scopes/set`
    parameter list) to override it. Upstream's own recommendation for
    correct DHCP server-identifier behavior is `network_mode: host` with no
    port mappings — exactly the deployment-shape change Decision 1
    deliberately rejected, for reasons that still hold.

    Practical impact, and why this isn't a blocker: per DHCP's own design
    (RFC 2131), a client's unicast RENEW at T1 targets whatever address is
    in `dhcp-server-identifier` — since that's the wrong, unreachable
    address here, T1 renewal will always silently fail, and every client
    will always fall through to REBIND at T2 (broadcast, which the relay
    correctly delivers, as already proven). This is a real, standards-compliant
    fallback path, not a failure — the practical cost is a slightly less
    "clean" renewal pattern (always REBIND, never RENEW) and a bit of
    wasted time between T1 and T2, not lost connectivity. Decision 4's
    long-lease-time strategy already absorbs this comfortably at real
    lease-time scales (T1/T2 being minutes apart out of a multi-day lease is
    immaterial). **Recorded as an accepted, known limitation for now** — not
    something to chase a fix for before Stage B via `network_mode: host`/macvlan.
    **Deferred, come back to this**: running Technitium as a native service
    directly on the LXC (no Docker) is a third option that would close this
    properly without reopening that trade-off — see decisions.md Decision 1's
    "Deferred" note.

## Stage A's last validation check: the simulated-cutover rebind test

This is the check that most directly rehearses `bridgeLocal`'s real cutover
sequence in miniature, and completes plan.md Stage A's validation list.

**Setup**: added a temporary MikroTik-local DHCP server on the throwaway
VLAN (`test_dhcp_seg_temp`, pool `192.168.90.150-199`, separate from
Technitium's `50-99` range), with the existing relay temporarily disabled
— reproducing the "before cutover" state of `bridgeLocal` today (MikroTik
serving DHCP directly, no relay).

**Sequence**:
1. Disabled relay, enabled temp local server. Client (fresh `dhclient`)
   correctly got NAK'd for its old Technitium-reserved address
   (`192.168.90.61` — the local server doesn't know about it), then
   obtained a fresh MikroTik-issued lease (`192.168.90.199`).
2. **The cutover itself**: disabled the temp local server, re-enabled the
   relay — the exact two-part change Stage E's real `bridgeLocal` packet
   will perform.
3. With the old MikroTik-issued lease still valid client-side, forced a
   renewal attempt. Result: `DHCPREQUEST for 192.168.90.199` (broadcast,
   the client's recorded address) → **`DHCPNAK from 192.168.90.1`**
   (Technitium, now the authority via the relay, correctly rejects the
   address it doesn't recognize) → immediate `DHCPDISCOVER` →
   `DHCPOFFER`/`DHCPACK of 192.168.90.61` (the client's actual Technitium
   reservation) → `bound`.

**Conclusion**: a client holding a stale, foreign (pre-cutover) lease
recovers cleanly and fast after the real cutover — one NAK, one immediate
re-discover, back on its correct address. No hang, no manual intervention,
no extended outage. This is a clean, positive result for the risk this test
existed to check.

Cleanup: temporary pool, network entry, and dhcp-server instance all
removed via `DELETE`; relay confirmed `disabled: false` as the final,
permanent state; client confirmed back on its normal reservation
(`192.168.90.61`) in a clean single-process state.

One more mechanical note for future MikroTik REST work: **updating an
existing entry needs `PATCH`**, not `PUT` (`PUT` is for creating new
entries in a collection, per Issue 11's note) — e.g.
`PATCH /rest/ip/dhcp-relay/*1` with `{"disabled": "true"}` to
enable/disable an existing relay or dhcp-server instance.

**Stage A is now fully validated end-to-end**: mechanism (Issues 7–10),
restart/renew and outage recovery (Issue 11), and the simulated-cutover
rebind check above. Remaining accepted, non-blocking finding: Issue 12
(Docker server-identifier), deferred per its own note above.

## Provision + flip sequence

1. Provision the disposable client stack so it boots at `192.168.90.61`.

   ```bash
   ./with-secrets terragrunt --working-dir terraform/lxc/stacks/dhcp-test-client-01 apply -auto-approve
   ```

2. Confirm the guest exists and is healthy on `pve-test-vm`.

   Important nuance from the first live pass: do **not** assume the
   workstation or `pve-test-vm` can SSH directly to `192.168.90.61`. The
   current reliable inspection path is via `pct exec` on the Proxmox host.

3. Capture the guest MAC address for the Technitium reservation.

   Because the Stage A client has a fixed `vmid` (`138`), the simplest
   retrieval path is from the Proxmox host after the container exists:

   ```bash
   ssh root@pve-test-vm.gibbsgreatly.xyz \
     "pct config 138 | sed -n 's/^net0: .*hwaddr=\\([^,]*\\).*/\\1/p'"
   ```

4. Create the Technitium scope for `192.168.90.0/24`.

5. Create the Technitium reservation for that MAC at `192.168.90.61`.

6. Flip the guest from static to DHCP and reboot it:

   ```bash
   ansible-playbook \
     -i terraform/lxc/stacks/dhcp-test-client-01/inventory.yml \
     -e dhcp_test_target_host=dhcp-test-client-01 \
     terraform/lxc/ansible/playbooks/configure-dhcp-test-client-via-pct.yml
   ```

7. After reboot, validate that the guest is still reachable at
   `192.168.90.61`, but now via a DHCP lease.

8. Run the structured client-side validation pass:

   ```bash
   ansible-playbook \
     -i terraform/lxc/stacks/dhcp-test-client-01/inventory.yml \
     -e dhcp_test_target_host=dhcp-test-client-01 \
     -e dhcp_test_validation_expected_ipv4=192.168.90.61 \
     -e dhcp_test_validation_expected_gateway=192.168.90.1 \
     -e 'dhcp_test_validation_expected_nameservers=["192.168.90.1"]' \
     terraform/lxc/ansible/playbooks/validate-dhcp-test-client-via-pct.yml
   ```

9. Run the rest of Stage A's validation checks from [plan.md](./plan.md):
   forward/reverse DNS, renew-after-restart, outage recovery, and simulated
   cutover behavior.
