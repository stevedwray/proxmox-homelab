# Phase 04b — Internal DNS Authority

## Goal

Deploy the authoritative DNS server for the internal `lab.gibbsgreatly.xyz` delegation. This service must be online before Phase 06 application workloads are deployed, as Phase 04 services assume it exists for their internal naming policy.

**This is a bridging phase** — it completes the Phase 04 prerequisite loop and enables Phase 06 to migrate Pi-hole as a pure ad-blocking DNS resolver (not as the only authoritative server).

## Live task docs

- [04b-core-services-02 — Deploy internal authoritative DNS server](tasks/04b-core-services-02-deploy-internal-dns.md)

## Current implementation status (2026-04-18)

- Lightweight DNS implementation (CoreDNS or Dnsmasq) not yet deployed
- MikroTik conditional forwarding configured but pointing to non-existent server
- Phase 04 services relying on temporary static A records per `lab.gibbsgreatly.xyz` entry

## Technical approach

### Choice: CoreDNS vs. Dnsmasq

| Aspect | CoreDNS | Dnsmasq |
|---|---|---|
| Deployment | Single binary; container-friendly | Lightweight; well-tested |
| Configuration | Plugin-based; file or API-driven | dhcp.conf style; simple |
| ACME integration | Feasible via plugin | Feasible via scripting |
| Resource footprint | ~50 MB memory | ~10 MB memory |
| Maintenance burden | Lower (fewer configs) | Higher (more manual) |

**Recommendation:** CoreDNS — simpler forward-to-authority model, lower operational overhead.

### Architecture

```text
Internal LXC (10.57.1.13 in mgmt_seg)
  └── CoreDNS running as systemd service
      └── Zone file or REST API for lab.gibbsgreatly.xyz authority
          ├── Static A records for Phase 04 services (traefik, authentik, step-ca, monitoring)
          ├── Ready to add app-stack records when Phase 06 deploys
          └── Conditional forward to upstream for non-lab queries (e.g., github.com)

MikroTik (10.57.1.1 via VLAN)
  └── /ip dns static add regexp="(^|\\.)lab\\.gibbsgreatly\\.xyz$" type=FWD forward-to=10.57.1.13
```

### Zone content

**lab.gibbsgreatly.xyz zone file** — Phase 04 records:

```
$ORIGIN lab.gibbsgreatly.xyz.
$TTL 5m

;; Phase 04 services
traefik         A   10.57.2.10          ; edge_seg proxy
authentik       A   10.57.1.10          ; mgmt_seg identity
step-ca         A   10.57.1.11          ; mgmt_seg PKI
monitoring      A   10.57.1.12          ; mgmt_seg observability

;; Phase 06 app services (added during Phase 06 migration)
; pihole       A   10.60.0.10          (added when Pi-hole migrates)
; arr          A   10.60.0.20          (added when arr stack migrates)
; jellyfin     A   10.60.0.30          (added when Jellyfin migrates)
```

### Upstreams

For non-lab queries (e.g., `dig github.com`), CoreDNS forwards to:

1. **Primary:** `10.57.1.1` (MikroTik mgmt_seg resolver) — ensures SDN recursion works
2. **Fallback:** System resolvers or explicit upstream (if MikroTik unavailable)

This preserves existing DNS behavior outside the lab zone.

---

## Prerequisites

- Phase 04 (Authentik, Traefik, step-ca, Monitoring) all running and stable
- CoreDNS binary or container image ready (from Harbor or system package)
- `lab.gibbsgreatly.xyz` zone file prepared with Phase 04 records
- MikroTik API access for conditional forwarding rule (admin credentials required)

---

## Deployment sequence

1. Create LXC `dns-stack` at `10.57.1.13` in `mgmt_seg`
2. Install CoreDNS; write zone file
3. Start CoreDNS; validate authority responses
4. Update MikroTik `/ip dns static` to forward `lab.gibbsgreatly.xyz` to `10.57.1.13`
5. Validate resolution from all SDN zones
6. Add monitoring/alerting for DNS failures
7. Document zone update procedure for Phase 06 app stack onboarding

---

## Acceptance criteria

- [ ] LXC `dns-stack` (VMID 151) running at `10.57.1.13`
- [ ] CoreDNS service healthy: `systemctl is-active coredns` returns `active`
- [ ] Authority validation: `dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz` returns `10.57.2.10`
- [ ] Upstream validation: `dig @10.57.1.13 +short github.com` returns an IP (recursion works)
- [ ] MikroTik forwarding rule active: `ip dns static print` shows FWD entry for `lab.gibbsgreatly.xyz`
- [ ] All SDN zones resolve lab-zone names via their gateway resolver:
  - `dig @10.57.0.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
  - `dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
  - `dig @10.57.2.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
  - `dig @10.57.3.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
- [ ] Non-lab queries still resolve: `dig @10.57.1.13 +short github.com` returns an IP
- [ ] Traefik/authentik/step-ca/monitoring services all resolve via internal names (no IP fallback)
- [ ] No OOM or resource issues on pve-test host

---

## Phase 04b is complete when

- All Phase 04 services are reachable via `*.lab.gibbsgreatly.xyz` names with step-ca trust
- MikroTik conditional forwarding is active and validated from all zones
- Zone update procedure is documented and tested with at least one Phase 06 app-stack dry-run entry
- Monitoring/alerting for DNS failures is configured (alert if CoreDNS down or MikroTik forwarding fails)

**Next phase unblocked:** Phase 06 application stack migration can proceed with Pi-hole as a pure app service, not as the authoritative DNS server.
