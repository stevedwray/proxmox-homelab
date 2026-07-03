# DNS Refactor — Plan

Status: **Phase 0 decisions made 2026-07-03; Phase 1 scaffold in progress.**
Tasks 1, 3, 4 below are decided — see [decisions.md](./decisions.md). Task 2
(requirements enumeration) and task 5 (cutover procedure) are captured
below.

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
   3. On the MikroTik, disable (do not remove) the existing CoreDNS FWD
      rule: `/ip dns static disable [find where type=fwd && forward-to=192.168.20.113]`.
   4. Add the new FWD rule pointing at Technitium:
      `/ip dns static add name=test.gibbsgreatly.xyz match-subdomain=yes type=fwd forward-to=<technitium-ip> comment="technitium cutover 2026-07-03"`.
   5. Flush the MikroTik's DNS cache so stale CoreDNS answers don't mask a
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
   9. Remove the new FWD rule:
      `/ip dns static remove [find where forward-to=<technitium-ip>]`.
   10. Re-enable the original CoreDNS rule:
       `/ip dns static enable [find where type=fwd && forward-to=192.168.20.113]`.
   11. Flush the DNS cache again (`/ip dns cache flush`) and re-run step 6-8
       against CoreDNS to confirm rollback actually restored service before
       declaring the rehearsal failed.

   This procedure is written from the RouterOS command syntax documented
   elsewhere in this repo (`docs/design/network.md`'s TM-09 note) but has
   **not been executed or verified against the live hAP ax3** — MikroTik DNS
   forwarding config is manual/out-of-IaC (TM-09), so treat command syntax
   as a draft to confirm interactively during Phase 3, not a copy-paste
   script.

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
  firewall policy are scaffolded, but **not yet applied/rehearsed** —
  confirm `reconcile-edge.py`/`render-edge-traefik.py` render the
  `step-ca`-resolved route correctly once Technitium is actually deployed.
  Configure native OIDC SSO against Authentik manually per the
  [authentik integration guide](https://integrations.goauthentik.io/networking/technitium/)
  (create the OAuth2/OIDC provider+application in Authentik, then the SSO
  settings in Technitium's own console) — this is manual setup, not yet
  scripted like `deploy-authentik-stack.yml`'s Graylog LDAP automation.

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

## Phase 3 — Cutover rehearsal on `pve-test-vm`

- Execute the MikroTik forward-rule repoint procedure designed in Phase 0.
- Validate every explicit dependent (`proxy-stack`, `authentik-stack`, and
  any FQDN-based smoke test) resolves correctly through Technitium.
- Confirm rollback (repoint back to CoreDNS) actually works before
  considering this validated.

## Phase 4 — Full teardown/redeploy validation (required gate)

Per `CLAUDE.md`'s Validation Tiers table, this is a Terraform/network-class
change: **a full teardown cycle on `pve-test-vm` is the minimum bar**, not a
targeted `scripts/provision.sh --stack` pass. Use the harness described in
[docs/teardown-test/repeatable-test.md](../teardown-test/repeatable-test.md).
Do not promote to `stable` without this passing.

## Phase 5 — Promotion

- Promote `work/* → stable` once Phase 4 passes.
- `pve` (production) rollout only after explicit operator approval, per
  `CLAUDE.md`'s Production Credential Controls — this is a mutating,
  network-affecting production change and needs a preflight summary +
  approval before any `./with-secrets-prod` command runs.

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
  needs confirming against upstream docs while building the deploy playbook
  (task 2 above).
- Whether Technitium's zone-authority guard needs to be a custom script
  (diff proposed records against required bootstrap records pre-import) or
  whether Technitium has a native equivalent — Phase 2 task.
- Technitium's IPv6 DHCPv6-PD support level — relevant only to the
  out-of-scope future DHCP takeover, not this migration.
