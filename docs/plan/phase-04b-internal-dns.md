# Phase 04b — Internal DNS Authority

## Goal

Deploy and operationalize the authoritative DNS service for the internal
platform delegation. This service must be online before Phase 06 application
workloads are deployed, as Phase 04 services assume it exists for their
internal naming policy.

**This is a bridging phase** — it completes the Phase 04 prerequisite loop and enables Phase 06 to migrate Pi-hole as a pure ad-blocking DNS resolver (not as the only authoritative server).

## Live task docs

- [04b-core-services-02 — Deploy internal authoritative DNS server](tasks/04b-core-services-02-deploy-internal-dns.md)

## Current implementation status (2026-07-05)

- ✅ **COMPLETE** — Technitium is now the active authority path in both
  environments:
  - pve: `lab.gibbsgreatly.xyz` delegated by MikroTik to `192.168.20.15`
  - pve-test-vm: `test.gibbsgreatly.xyz` delegated by MikroTik to
    `192.168.20.115`
- ✅ Direct parity validation against CoreDNS passed before the production
  delegate repoint.
- ✅ Full teardown/redeploy validation passed on `pve-test-vm` with the
  Technitium-backed resolver path active.
- ✅ Technitium browser access and Authentik-backed OIDC login are working in
  both environments.
- CoreDNS remains deployed at `192.168.20.13` / `192.168.20.113` as a
  rollback target while MikroTik DNS forwarding is still manual.

## Technical approach

### Choice: Technitium vs. CoreDNS

| Aspect | Technitium | CoreDNS |
|---|---|---|
| Deployment | Docker image; UI + API built in | Bare binary; simple service shape |
| Configuration | Managed via API/UI; easier operator workflow | File-driven; more manual record management |
| OIDC / admin UX | Native OIDC support and web UI | No native auth/UI layer |
| DNS features | Recursive resolver plus built-in DNS admin features | Strong authority path, fewer operator conveniences |
| Resource footprint | Higher, but acceptable after sizing to 2 GB RAM | Lower |

**Decision:** Technitium is the durable target. CoreDNS was the initial
authority implementation, but Technitium replaced it as the active delegate
path once parity, browser routing, and Authentik integration were proven.

### Architecture

```text
Internal LXC (pve: 192.168.20.15, pve-test-vm: 192.168.20.115 in mgmt_seg)
  └── Technitium DNS Server running via Docker Compose
      └── Authoritative zone for lab.gibbsgreatly.xyz / test.gibbsgreatly.xyz
          ├── Shared platform A/NS/SOA records rendered for parity with CoreDNS
          ├── Ready to add app-stack records when Phase 06 deploys
          ├── Conditional recursion for non-lab queries (e.g., github.com)
          └── Browser-admin route via Traefik + Authentik OIDC

MikroTik (192.168.20.1 via VLAN)
  └── /ip dns static ... type=FWD forward-to=192.168.20.15   (pve)
  └── /ip dns static ... type=FWD forward-to=192.168.20.115  (pve-test-vm)

CoreDNS (192.168.20.13 / 192.168.20.113)
  └── Remains deployed only as the previous authority and rollback target
```

### Zone content

**lab.gibbsgreatly.xyz authoritative content** — Phase 04 records:

```
$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m

;; Phase 04 services
traefik         A   192.168.30.10          ; edge_seg proxy
authentik       A   192.168.20.10          ; mgmt_seg identity
step-ca         A   192.168.20.11          ; mgmt_seg PKI
monitoring      A   192.168.20.12          ; mgmt_seg observability

;; Phase 06 app services (added during Phase 06 migration)
; pihole       A   10.60.0.10          (added when Pi-hole migrates)
; arr          A   10.60.0.20          (added when arr stack migrates)
; jellyfin     A   10.60.0.30          (added when Jellyfin migrates)
```

### Upstreams

For non-lab queries (e.g., `dig github.com`), Technitium forwards to:

1. **Primary:** `192.168.20.1` (MikroTik mgmt_seg resolver) — ensures SDN recursion works
2. **Fallback:** System resolvers or explicit upstream (if MikroTik unavailable)

This preserves existing DNS behavior outside the lab zone.

---

## Durable outcome

- `technitium-stack` is the active internal DNS authority stack.
- `dns-stack` still exists as a rollback path, not the active authority.
- The parity contract now covers:
  - shared browser-routed A records via Traefik
  - direct/internal A records such as `authentik-int` and `step-ca`
  - authority records `NS`, `SOA`, `dns`, and `ns1`
  - recursive resolution for public names
- The authoritative identity intentionally stays `ns1.lab.gibbsgreatly.xyz`
  even after the backend changed from CoreDNS to Technitium.

---

## Deployment sequence that was validated

1. Bring up `technitium-stack` in parallel with `dns-stack` using a distinct
   VMID/IP (`20015`, `192.168.20.15` on pve; `192.168.20.115` on pve-test-vm).
2. Publish a bootstrap zone plus a parity view of the live internal zone.
3. Validate direct-query parity against CoreDNS before touching MikroTik.
4. Validate Traefik publication and Authentik OIDC login for the Technitium UI.
5. Repoint the MikroTik FWD rule in place to Technitium and flush DNS cache.
6. Re-run resolver-path checks through MikroTik from all relevant client paths.
7. Confirm rollback remains possible by keeping CoreDNS live in parallel.

---

## Acceptance criteria

- [x] `technitium-stack` (VMID 20015) running at `192.168.20.15` on pve and
      `192.168.20.115` on pve-test-vm
- [x] Technitium authority validation:
      `dig @192.168.20.15 +short traefik.lab.gibbsgreatly.xyz` returns `192.168.30.10`
- [x] Recursive validation:
      `dig @192.168.20.15 +short github.com` returns an IP
- [x] MikroTik forwarding rule active and repointed to Technitium in both
      environments
- [x] All SDN zones resolve lab-zone names via their gateway resolver:
  - `dig @192.168.10.1 +short traefik.lab.gibbsgreatly.xyz` → `192.168.30.10`
  - `dig @192.168.20.1 +short traefik.lab.gibbsgreatly.xyz` → `192.168.30.10`
  - `dig @192.168.30.1 +short traefik.lab.gibbsgreatly.xyz` → `192.168.30.10`
  - `dig @192.168.40.1 +short traefik.lab.gibbsgreatly.xyz` → `192.168.30.10`
- [x] Direct parity validation passed against CoreDNS before cutover
- [x] Non-lab queries still resolve through Technitium
- [x] Traefik/authentik/step-ca/monitoring services all resolve via internal names (no IP fallback)
- [x] Browser route `https://technitium.lab.gibbsgreatly.xyz` works
- [x] Authentik-backed OIDC login works for Technitium
- [x] Production cutover completed without requiring a full pve rebuild

---

## Phase 04b is complete when

- All Phase 04 services are reachable via `*.lab.gibbsgreatly.xyz` names
- MikroTik conditional forwarding is active and validated from all zones
- The direct parity runbook and production cutover packet are documented in
  `docs/dns-refactor/`
- CoreDNS is retained only as rollback context until the manual-forwarding
  dependency is retired

**Next phase unblocked:** Phase 06 application stack migration can proceed with Pi-hole as a pure app service, not as the authoritative DNS server.
