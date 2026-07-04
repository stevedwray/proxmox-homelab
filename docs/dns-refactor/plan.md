# DNS Refactor — Plan

Status: **Phase 0 decisions made, Phase 1 bring-up completed, Phase 2
direct-query parity completed, Phase 3 router-path rehearsal completed, and
Phase 4 teardown/redeploy validation completed on 2026-07-04. Production
parallel bring-up on `pve` is also now complete.** Technitium is live on
`pve-test-vm` at `192.168.20.115`,
serving the bootstrap zone `tech.test.gibbsgreatly.xyz`, answering recursive
queries, exposed through Traefik at `technitium.test.gibbsgreatly.xyz`, using
native OIDC against Authentik, and now serving the live `test.gibbsgreatly.xyz`
router path in `pve-test-vm` via the MikroTik delegate rule. CoreDNS remains
live as the rollback target. On `pve`, `technitium-stack` is now deployed at
`192.168.20.15`, serving direct-query parity for `lab.gibbsgreatly.xyz`,
while production clients still resolve through the CoreDNS-backed MikroTik
path. No production cutover has been attempted.

Tasks 1, 3, 4 below are decided — see [decisions.md](./decisions.md). Task 2
(requirements enumeration) and task 5 (cutover procedure) are captured
below.

## Progress snapshot — 2026-07-04

Completed:
- `technitium-stack` scaffolded and deployed independently of `dns-stack`.
- Permanent `LAB_IP_TECHNITIUM` identity chosen and exercised on
  `pve-test-vm`: `192.168.20.115`.
- Permanent `LAB_IP_TECHNITIUM` identity also exercised on `pve`:
  `192.168.20.15`.
- Bootstrap zone chosen and working: `tech.test.gibbsgreatly.xyz`.
- Direct smoke tests green against Technitium:
  `step-ca.tech.test.gibbsgreatly.xyz` resolves internally and external-name
  recursion (`github.com`) succeeds.
- Traefik/CoreDNS edge integration working for
  `technitium.test.gibbsgreatly.xyz`.
- Native OIDC SSO against Authentik working end-to-end.
- MikroTik `test-zone-delegate` rehearsal completed successfully on
  `pve-test-vm`: router-path queries now resolve through Technitium.
- Production parallel bring-up completed successfully:
  `technitium.lab.gibbsgreatly.xyz` is reachable, OIDC login works, and the
  production provision smoke test now verifies direct-query parity for the
  key `lab.gibbsgreatly.xyz` names while leaving the active delegate alone.

Not yet done:
- Final successful production parity packet comparing CoreDNS and
  Technitium answer sets record-by-record.
- Manual production MikroTik cutover packet and execution window.

## Issues encountered during Phase 1 and how they were resolved

1. Harbor image pull targeted the wrong protocol/path and failed during the
   first compose start.
   Resolution: corrected Harbor environment targeting so Technitium pulled
   successfully in `pve-test-vm`.
2. Authentik edge discovery/reconcile defaulted to the lab URL instead of the
   environment-specific Authentik FQDN.
   Resolution: patched the Authentik edge tooling to derive its default URL
   from `LAB_FQDN_AUTHENTIK`.
3. Technitium could not validate or reach the OIDC provider reliably at first.
   Resolution: built a combined CA bundle for the Technitium container and
   mounted it as `SSL_CERT_FILE`.
4. Technitium could not resolve `authentik-int.test.gibbsgreatly.xyz` while it
   only owned the bootstrap zone.
   Resolution: created a conditional forwarder for `${LAB_DOMAIN}` back to the
   current CoreDNS authority during bootstrap.
5. Authentik internal direct TLS was only available on `:9443`, while the OIDC
   metadata led Technitium to `443`.
   Resolution: exposed Authentik direct TLS on standard `443` as well and
   moved Technitium's default OIDC authority to the standard HTTPS URL.
6. Technitium record publication was not idempotent: re-adding existing A
   records returned API-level errors.
   Resolution: query current records first and only add missing A records.
7. The first parity-zone renderer draft preserved CoreDNS authority identity
   (`ns1 -> LAB_IP_DNS`) instead of re-pointing the zone at Technitium.
   Resolution: the Technitium renderer now injects `dns` and `ns1` records
   for `LAB_IP_TECHNITIUM`, so direct queries exercise Technitium as the
   authoritative server for the parity zone.
8. The first production parity-zone publish pass failed in Ansible because
   the bootstrap-zone publication loop iterated over registered query result
   objects, but the URI template still referenced `item.name` / `item.ip`
   instead of `item.item.name` / `item.item.ip`.
   Resolution: corrected the loop variable references so production
   bootstrap/parity publication is now idempotent and provision passes on
   `pve`.
9. The first formal production parity pass showed that Technitium's parity
   zone kept its default root authority metadata
   (`NS=tech.lab.gibbsgreatly.xyz`, `SOA.primaryNameServer=tech.lab...`)
   instead of matching CoreDNS's `ns1.lab.gibbsgreatly.xyz`.
   Resolution: update the Technitium parity-zone publisher to reconcile the
   root `NS` and `SOA` records explicitly, not just the A records. This fix
   is now validated on `pve-test-vm`; production still needs reprovision +
   parity rerun.

## Phase 0 — Requirements and design capture

Goal: turn "replace CoreDNS with Technitium" into a concrete, reviewable
design before touching any infrastructure.

Tasks:

1. **Decided** — see [decisions.md](./decisions.md) Decision 1: unified
   DNS+DHCP path, web UI/API manageability, built-in DoH/DoT/DNSSEC.
2. Enumerate what [current-state.md](./current-state.md)'s contract requires
   any replacement to provide:
   - Authoritative zone for `lab.gibbsgreatly.xyz` (pve) /
     `test.gibbsgreatly.xyz` (pve-test-vm), serving A records for every core
     platform stack (`LAB_IP_DNS`, `LAB_IP_PROXY`, `LAB_IP_AUTHENTIK`,
     `LAB_IP_STEP_CA`, `LAB_IP_MONITORING`, `LAB_IP_PORTAINER`,
     `LAB_IP_HARBOR`, `LAB_IP_NETBOX`).
   - Recursive resolution for external names (with the same public-fallback
     behavior CoreDNS's post-deploy probe relies on).
   - A safe zone-publish flow with an authority-record guard equivalent to
     CoreDNS's stage → `named-checkzone` → assert (SOA/NS/`ns1` A record) →
     promote sequence — Technitium manages zones via its own API/DB rather
     than flat files, so the guard needs to be an API-driven pre-publish
     check (e.g. a script that diffs proposed records against required
     bootstrap records before calling Technitium's zone-import API), not a
     file-level check.
   - An integration point equivalent to `coredns_generated_zone_src` — a
     hook the provisioning-refactor DNS-ownership reconciler
     (`docs/provisioning-refactor/tasks/02-dns-ownership-transition.md`,
     `tasks/08-coredns-renderer.md`) can write to instead of the seed
     template. For Technitium this likely means a generated zone-file import
     via its REST API (`/api/zones/import`) rather than a file copy — needs
     confirming against Technitium's API docs in Phase 1.
   - Port 53 UDP+TCP for both authority and recursion, matching CoreDNS's
     `Provides` table.
3. **Decided** — see [decisions.md](./decisions.md) Decision 2: Docker
   Compose deployment, Harbor-proxied image, `portainer_agent: false`
   (platform tier).
4. **Decided** — see [decisions.md](./decisions.md) Decision 3: new VMID
   (`20015`) / new `mgmt_seg` IP (`LAB_IP_TECHNITIUM`), parity window before
   cutover, permanent identity (not a throwaway parity-only address).
5. MikroTik cutover procedure (repoint the `lab.gibbsgreatly.xyz` /
   `test.gibbsgreatly.xyz` FWD rule from CoreDNS to Technitium):

   **Pre-check (Phase 3 rehearsal, `pve-test-vm` only):**
   1. Confirm Technitium is answering authoritatively and recursively at its
      own IP: `dig @<technitium-ip> traefik.test.gibbsgreatly.xyz` and
      `dig @<technitium-ip> github.com` both return records (Phase 1/2 gate,
      must already be green before this step).
   2. Record the current FWD rule so it can be restored verbatim:
      `/ip dns static print detail where type=fwd`.

   **Cutover:**
   3. On the MikroTik, repoint the existing CoreDNS FWD rule in place. In the
      live `pve-test-vm` rehearsal, the delegate already existed as `.id *53`,
      so `add` failed with "entry already exists" and the correct command was:
      `/ip dns static set *53 forward-to=<technitium-ip>`.
      If a future environment does not already have a matching delegate, add a
      new rule instead.
   4. Flush the MikroTik's DNS cache so stale CoreDNS answers don't mask a
      broken cutover: `/ip dns cache flush`.

   **Post-cutover validation (must all pass before calling this rehearsal
   successful):**
   6. From a client on `mgmt_seg`/`infra_seg` (not directly querying either
      DNS server): resolve `traefik.test.gibbsgreatly.xyz` and confirm it
      returns the same IP CoreDNS used to return.
   7. Run every explicit dependent's smoke test (`proxy-stack`,
      `authentik-stack`, and any stack whose smoke test resolves an FQDN —
      see current-state.md's "Explicit dependents").
   8. Confirm external-name recursion still works end-to-end through the
      MikroTik → Technitium path (`dig <client-resolver> github.com`).

   **Rollback (if any post-cutover check fails):**
   9. Restore the original delegate target. In the 2026-07-04 rehearsal that
      meant:
      `/ip dns static set *53 forward-to=192.168.20.113`.
      If a future environment used an added temporary rule instead of an
      in-place change, remove that temporary rule and restore the original.
   10. Flush the DNS cache again (`/ip dns cache flush`) and re-run step 6-8
       against CoreDNS to confirm rollback actually restored service before
       declaring the rehearsal failed.

   This procedure is written from the RouterOS command syntax documented
   elsewhere in this repo (`docs/design/network.md`'s TM-09 note) but has
   was verified against the live hAP ax3 on 2026-07-04 for `pve-test-vm`.
   MikroTik DNS forwarding config remains manual/out-of-IaC (TM-09), so the
   exact rule ID and whether `set` vs `add` is required still needs checking
   interactively per environment.

## Phase 1 — Build `technitium-stack` (scaffold, no cutover)

- Draft `terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md` mirroring
  the structure of `dns-stack/STACK_CONTRACT.md` (Purpose, Network, Inputs,
  Provides, Dependencies, Persistent State, Generated Artifacts, What May
  Depend On This, What Must Not Be Edited Casually, Playbook, Notes).
- Add `stack.yaml`, Ansible playbook (`deploy-technitium-stack` or similar),
  and `smoke-test.sh` following the pattern in
  [terraform/lxc/PLATFORM_CONTRACT.md](../../terraform/lxc/PLATFORM_CONTRACT.md).
- Deploy on a **new** VMID/IP on `pve-test-vm`, dual-running alongside the
  existing `dns-stack` — do not touch the live MikroTik forward rule yet.
- Initial bring-up should use a separate Technitium-only bootstrap zone
  (`TECHNITIUM_BOOTSTRAP_ZONE`, default `tech.${LAB_DOMAIN}`; for
  `pve-test-vm`, `tech.test.gibbsgreatly.xyz`) so Technitium can function
  alongside CoreDNS without claiming the live platform zone.
- Validate authority and recursion directly against Technitium's IP (`dig
  @<technitium-ip>`), independent of the MikroTik forward path and against
  the bootstrap zone first.
- Admin console/API exposure and auth (see
  [decisions.md](./decisions.md) Decision 4, added 2026-07-03):
  `technitium-stack/edge.yaml` and the `edge_seg → mgmt_seg tcp/5380`
  firewall policy are now applied and validated in `pve-test-vm`.
  Native OIDC SSO against Authentik is also automated:
  `reconcile-edge.py` should own the Authentik provider/application, and
  `deploy-technitium-stack.yml` should push the Technitium-side SSO
  settings through the admin API.

Phase 1 status as of 2026-07-03: **complete for bootstrap bring-up**.

## Phase 2 — Parity validation

- Confirm the seed zone (or reconciler-generated zone) renders correctly in
  Technitium with the same records `dns-stack` currently serves.
- Confirm whatever replaces `coredns_generated_zone_src` works with the
  provisioning-refactor DNS-ownership reconciler
  (`docs/provisioning-refactor/tasks/02-dns-ownership-transition.md`,
  `tasks/08-coredns-renderer.md`) — or design its Technitium equivalent.
- Confirm Technitium's zone-authority guard behavior (or build an
  equivalent guard) so a bad zone push can't silently drop SOA/NS records,
  matching the safety property the current stage→validate→assert→promote
  flow provides.

Phase 2 progress as of 2026-07-03:
- `scripts/provision.sh --stack technitium-stack` now regenerates a
  Technitium-specific parity-zone payload from the same seed zone and
  validated EdgeManifests used by the CoreDNS renderer.
- `deploy-technitium-stack.yml` now keeps the bootstrap zone and, in
  parallel, publishes a direct-query parity zone for `test.gibbsgreatly.xyz`.
- Direct queries against `192.168.20.115` now return expected answers for:
  `traefik.test.gibbsgreatly.xyz -> 192.168.30.110`,
  `ns1.test.gibbsgreatly.xyz -> 192.168.20.115`,
  `github.com -> non-empty recursive answer`,
  plus additional spot checks for `authentik`, `harbor`, `netbox`,
  `portainer`, `step-ca`, and `authentik-int`.
- `technitium-stack/smoke-test.sh` now delegates to a checked-in
  `verify-parity.sh` matrix so every provision pass asserts the same direct
  parity set before any MikroTik rehearsal: browser-routed names must return
  `LAB_IP_PROXY`, direct/internal names must return their service IPs, the
  bootstrap zone still answers, and public recursion stays live.

Phase 2 status: **complete.**

Immediate next practical steps:
1. Preserve the checked-in direct-query parity verifier and rerun it on each
   reprovision so the direct authority view stays boringly stable.
2. Capture the successful router-path rehearsal in docs and treat the next
   validation bar as the full teardown/redeploy gate, not more exploratory
   parity work.
3. During the full gate, validate resolver-path parity again through the
   router and run the explicit dependent smoke checks (`proxy-stack`,
   `authentik-stack`, and any other FQDN-based check).
4. Only after the full gate passes should we prepare a production (`pve`)
   cutover packet.

## Phase 3 — Cutover rehearsal on `pve-test-vm`

- Execute the MikroTik forward-rule repoint procedure designed in Phase 0.
- Validate every explicit dependent (`proxy-stack`, `authentik-stack`, and
  any FQDN-based smoke test) resolves correctly through Technitium.
- Confirm rollback (repoint back to CoreDNS) actually works before
  considering this validated.

Phase 3 status as of 2026-07-04: **successful resolver-path rehearsal**.

Observed live results through MikroTik `192.168.1.1` after repointing
`test-zone-delegate` from CoreDNS to Technitium:
- `ns1.test.gibbsgreatly.xyz -> 192.168.20.115`
- `traefik.test.gibbsgreatly.xyz -> 192.168.30.110`
- `authentik.test.gibbsgreatly.xyz -> 192.168.30.110`
- `harbor.test.gibbsgreatly.xyz -> 192.168.30.110`
- `netbox.test.gibbsgreatly.xyz -> 192.168.30.110`
- `portainer.test.gibbsgreatly.xyz -> 192.168.30.110`
- `step-ca.test.gibbsgreatly.xyz -> 192.168.20.111`
- `authentik-int.test.gibbsgreatly.xyz -> 192.168.20.110`
- `github.com -> non-empty recursive answer`

Important operator note from the rehearsal:
- The existing RouterOS FWD rule already owned the regexp
  `(^|\\.)test\\.gibbsgreatly\\.xyz$`, so adding a second rule failed with
  `failure: entry already exists`.
- The correct live mutation was:
  `/ip dns static set *53 forward-to=192.168.20.115`
  followed by `/ip dns cache flush`.
- Rollback is the inverse:
  `/ip dns static set *53 forward-to=192.168.20.113`
  followed by `/ip dns cache flush`.

## Phase 4 — Full teardown/redeploy validation (required gate)

Per `CLAUDE.md`'s Validation Tiers table, this is a Terraform/network-class
change: **a full teardown cycle on `pve-test-vm` is the minimum bar**, not a
targeted `scripts/provision.sh --stack` pass. Use the harness described in
[docs/teardown-test/repeatable-test.md](../teardown-test/repeatable-test.md).
Do not promote to `stable` without this passing.

Phase 4 status as of 2026-07-04: **passed**.

Evidence:
- Harness stamp: `20260703-220525`
- Final summary:
  [docs/teardown-test/artifacts/evidence/20260703-220525/summary-final-validation.md](../teardown-test/artifacts/evidence/20260703-220525/summary-final-validation.md)

Observed outcome:
- Full destroy/recreate and reprovision completed successfully.
- Delegated and authoritative DNS checks passed for the routed services.
- `final-reconcile-edge-dry-run` passed.
- Browser validation after the gate confirmed the main routed services were
  healthy.

## Phase 5 — Promotion

- Promote `work/* → stable` now that Phase 4 has passed.
- `pve` (production) rollout only after explicit operator approval, per
  `CLAUDE.md`'s Production Credential Controls — this is a mutating,
  network-affecting production change and needs a preflight summary +
  approval before any `./with-secrets-prod` command runs.

Immediate next practical work in this phase:
1. Update the tracked docs that still describe `dns-stack` / CoreDNS as the
   only active `pve-test-vm` path where needed.
2. Prepare the production cutover packet:
   exact MikroTik delegate mutation for `lab.gibbsgreatly.xyz`,
   rollback command, expected resolver checks, and explicit smoke list.
3. Decide whether the existing `pve-test-vm` router delegate should remain
   pointed at Technitium while production prep continues, or be reverted to
   CoreDNS for a stricter rollback posture.

### Incremental `pve` integration plan (no full platform teardown)

The production move should be an additive deploy plus a controlled router
delegate switch, not a rebuild of the whole platform.

1. Deploy `technitium-stack` into `pve` alongside the existing
   `dns-stack`, using its permanent `mgmt_seg` identity.
2. Bring up the same bootstrap capabilities already proven in
   `pve-test-vm`: Traefik route, Authentik integration, recursion, and
   direct authority for the Technitium bootstrap zone.
3. Load the real `lab.gibbsgreatly.xyz` records into Technitium while
   CoreDNS remains the active authority for clients.
4. Run a formal parity verification pass by direct query against both
   CoreDNS and Technitium for:
   - browser-routed names (`authentik`, `grafana`, `harbor`, `netbox`,
     `portainer`, `traefik`)
   - direct/internal names (`authentik-int`, `step-ca`, `ns1`)
   - public recursion
   - SOA / NS / authority identity
5. Prepare a manually reviewed MikroTik cutover packet for
   `lab.gibbsgreatly.xyz`:
   - exact `set` or `add` command for the delegate rule
   - cache flush command
   - immediate rollback command back to CoreDNS
   - post-cutover validation command list
   - clear abort / rollback criteria
6. Execute a short cutover window:
   repoint MikroTik from CoreDNS to Technitium, flush cache, then run the
   smoke list and browser checks immediately.
7. Leave `dns-stack` deployed as warm rollback state for a defined soak
   period before decommission planning begins.

Current conclusion:
- `pve-test-vm` has already proven the full technical pattern, including the
  router-path rehearsal and teardown/redeploy gate.
- `pve` now has a healthy parallel Technitium deployment serving direct-query
  parity answers.
- The next production prerequisite is a formal `lab.gibbsgreatly.xyz`
  parity-verification packet plus a manually reviewed MikroTik cutover
  packet, not another destructive environment rebuild.

### Production parallel bring-up checklist

Goal: deploy `technitium-stack` into `pve` as a parallel service only. This
step must not mutate the MikroTik delegate rule for `lab.gibbsgreatly.xyz`.

Identity and sizing baseline:
- IP: `192.168.20.15` (`LAB_IP_TECHNITIUM` in `.env.pve`)
- VMID: `20015`
- CPU / memory / storage:
  1 core / 2048 MB RAM / 1024 MB swap / 12 GB rootfs / 6 GB Docker storage

Preflight:
1. Confirm `.env.pve` still carries the intended Technitium IP
   (`LAB_IP_TECHNITIUM=192.168.20.15`).
2. Confirm required secrets exist in SOPS for the production environment:
   `TECHNITIUM_ADMIN_PASSWORD` and `TECHNITIUM_OIDC_CLIENT_SECRET`.
3. Confirm no MikroTik DNS delegate change is included in this step.

Bring-up:
4. Deploy `technitium-stack` into `pve` alongside `dns-stack`.
5. Provision the stack and let the playbook configure:
   - bootstrap zone
   - recursive resolution
   - Traefik route
   - native OIDC against Authentik

Immediate validation:
6. Query Technitium directly by IP for:
   - bootstrap-zone authority
   - external recursion
7. Confirm browser/API reachability for
   `https://technitium.lab.gibbsgreatly.xyz`.
8. Confirm Authentik-backed login works.
9. Confirm the existing `lab.gibbsgreatly.xyz` client path is still served by
   CoreDNS via MikroTik and has not changed.

Observed outcome:
- `ALLOW_PVE=true ./with-secrets-prod scripts/provision.sh --stack technitium-stack --target-env pve`
  now passes.
- Production smoke tests verify direct-query parity for:
  `technitium`, `traefik`, `authentik`, `harbor`, `netbox`, `portainer`,
  `dns`, `ns1`, `authentik-int`, `step-ca`, `step-ca.tech.lab.gibbsgreatly.xyz`,
  and public recursion (`github.com`).
- Browser reachability and OIDC-backed login for
  `https://technitium.lab.gibbsgreatly.xyz` were confirmed manually.

Exit criteria for this step:
- `technitium-stack` is healthy in `pve`
- direct queries against Technitium pass
- browser route and OIDC login pass
- no MikroTik mutation has been performed
- production clients are still on the CoreDNS-backed resolver path

Status: **complete**.

### Immediate next production work

1. Produce a formal parity-verification packet for `lab.gibbsgreatly.xyz`
   comparing direct answers from CoreDNS (`192.168.20.13`) and Technitium
   (`192.168.20.15`) for:
   - browser-routed names
   - direct/internal names
   - shared authority identity (`SOA`, `NS`)
   - Technitium cutover-target authority records (`dns`, `ns1` ->
     `192.168.20.15`)
   - recursive external lookups
   Packet path:
   [docs/dns-refactor/production-cutover-packet.md](./production-cutover-packet.md)
2. Prepare a manually reviewed MikroTik cutover packet for
   `lab.gibbsgreatly.xyz`:
   - exact existing delegate inspection command
   - exact `set` or `add` command
   - cache flush command
   - immediate rollback command
   - post-cutover validation sequence
3. Execute the production delegate cutover only after the parity packet is
   green and the router mutation is explicitly approved.

## Phase 6 — Decommission and doc closeout

- Remove `dns-stack` once Technitium is validated on `pve` and the operator
  confirms no rollback is needed.
- Update `docs/design/network.md`'s DNS section, rewrite
  `docs/plan/phase-04b-internal-dns.md` for Technitium (or replace it),
  update `docs/teardown-test/inventory.md`'s deploy/destroy order and
  service list.
- Fold this workspace's durable conclusions into those tracked docs, then
  archive or delete `docs/dns-refactor/` per the workspace closeout pattern.

## Future: DHCP takeover from MikroTik (explicitly out of scope here)

Operator has stated the end goal: Technitium eventually replaces MikroTik as
the DHCP server, not just the DNS authority. This section exists so Phase
0-6 decisions above don't accidentally close off that path — it is **not**
a task list for this workspace to execute.

**Scope clarification:** MikroTik's only current DHCP server is `lan` on
`bridgeLocal` — the flat physical LAN (`192.168.1.0/24`, WiFi + physical
devices), documented in
[router/desired-config.md](../../router/desired-config.md). This is a
separate network domain from the SDN container VLANs
(`build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`) this workspace targets, which
are statically addressed via Terraform and run no DHCP at all today. DHCP
takeover is therefore a `router/`-domain change (the physical hAP), not an
extension of `technitium-stack`'s container-platform role.

**Why current-workspace decisions don't need to block on this:** DHCP is a
broadcast/link-local protocol, but MikroTik can run as a DHCP relay on
`bridgeLocal` (RouterOS supports this natively), forwarding via unicast to a
single Technitium IP — the same mechanism already used for the DNS FWD rule.
Technitium does **not** need to be multi-homed across VLANs for this to
work. That means:

- Give Technitium a stable, long-term `mgmt_seg` IP as its identity from the
  start — not a throwaway address that only exists for the parity window and
  would need to move again before DHCP relay is configured against it.
- Don't shrink `technitium-stack`'s sizing below `dns-stack`'s current
  allocation (1 core / 1024 MB RAM / 8 GB rootfs) — a DHCP lease DB and scope
  config need at least as much headroom.
- Live observation in `pve-test-vm` showed Technitium already running well
  into swap on the smaller baseline and consuming close to 1 GB of boot-disk
  space. Before `pve` bring-up, the default stack sizing was raised to
  1 core / 2048 MB RAM / 1024 MB swap / 12 GB rootfs with 6 GB Docker
  storage so production starts with more breathing room.
- Keep `STACK_CONTRACT.md`/`stack.yaml` inputs extensible — don't hardcode a
  DNS-only shape that would need a rewrite to add `dhcp_scopes` /
  `dhcp_static_leases` later.

**Data to preserve before any future cutover** (inventory now, so it isn't
lost): `router/desired-config.md`'s 4 static leases (Pi-holes at `.22`/`.23`,
`garuda` workstation, `RBR350`), the `dhcp-pool` range
(`192.168.1.100`–`.199`), and the IPv6 RA/DHCPv6-PD config (`advertise-dns`
pointing at the Pi-holes' ULA addresses). Confirm Technitium's IPv6 DHCPv6
support before committing — RouterOS RA/DHCPv6-PD duties may need to stay on
MikroTik indefinitely if Technitium's IPv6 support is partial.

**Blocker to resolve before designing this phase for real:**
`router/README.md` and `router/desired-config.md` described the SDN VLAN
subnets using the legacy `10.57.x.x` scheme; `docs/design/network.md` and
this workspace's `current-state.md` use the current `192.168.<vlan>.x`
scheme. Commit `372e26ae` updated 33 container-platform docs but did not
touch `router/`. **Likely resolved as of 2026-07-03** — uncommitted
`router/` changes in the working tree at the time this plan was written
show a fresh REST-API re-scrape confirming the live hAP ax3 uses the current
`192.168.<vlan>.x` scheme, matching `docs/design/network.md`. That work is
outside this workspace's scope (it's a `router/`-doc reconciliation, not a
DNS-migration change) — confirm it has been committed on its own branch
before relying on it here.

When DNS migration reaches Phase 5/6, open a separate workspace (e.g.
`docs/dhcp-refactor/`) for this rather than folding it into this one's
closeout — physical-router relay reconfig, static-lease migration, and the
IPv6 compatibility check are their own validation surface and shouldn't
block this workspace's promotion.

## Open questions

All Phase 0 questions are resolved — see [decisions.md](./decisions.md).
Remaining open items now live in Phase 1+:

- Technitium's zone-import API shape (`/api/zones/import` or equivalent) —
  still needs confirming against upstream docs while building the parity
  workflow (task 2 above).
- Whether Technitium's zone-authority guard needs to be a custom script
  (diff proposed records against required bootstrap records pre-import) or
  whether Technitium has a native equivalent — Phase 2 task.
- Technitium's IPv6 DHCPv6-PD support level — relevant only to the
  out-of-scope future DHCP takeover, not this migration.
