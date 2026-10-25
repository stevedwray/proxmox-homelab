# Independent observability on the Argon Pis

## Status

**Checked live 2026-10-26.** The native Icinga 2 HA pair is live on both Pis
(argon-01 config master), with mutual TLS and peer-only TCP 5665. All six
Stage 2 core-check groups are enabled: router, DNS, pve, metrics, internal
services and OCI. The initial Redis audit found **14/14 hosts and 31/31 core
services OK**, with results from both Pis updated within two minutes. After
the monitoring-health expansion, Icinga DB reports **14 hosts and 34 services,
all 34 services hard-state OK**.
The OCI SSH probe remains off pending a separately authorised key and pinned
host key; Discord/Telegram notifications remain off pending three dedicated
OpenBao values. The operator waived Stage 2 fault drills for this rollout.
See [runbook.md](runbook.md) §§2.4–2.5 for live evidence and rollback copies.

SmokePing probes and six target RRDs are live. Its browser redirect, filter
URL and static assets were repaired on 2026-10-26 (§4.4 of the runbook);
the operator's Authentik browser retry is still pending. Icinga Web 2 is live
at `https://icinga.lab.gibbsgreatly.xyz`,
served directly by argon-01 with its own Let's Encrypt certificate and native
login. The Pis have forward and reverse DNS (`argon-0N.gibbsgreatly.xyz`, one
PTR each). The original SmokePing smoke checks missed the browser failure;
the expanded `scripts/icinga-observer-smoke.sh base dns smokeping web` suite
passes after repair, including redirect and asset checks. The role's scoped
preview reported `changed=0` on 2026-10-26. The observer itself
uses native packages and systemd, with no Docker or OCI mutation.

The Icinga Web dashboard grouping was deployed on argon-01 on 2026-10-26.
Its **Core services** dashboard has sections for
observer health, network and DNS, compute, monitoring and logs, internal
platform, and the public edge. The same six categories are native Icinga host
and service groups, so they can also filter the normal Icinga DB Web lists.
This only changes presentation and group metadata; check commands, intervals,
dependencies, and notifications are unchanged. An authenticated dashboard
request returned HTTP 200 with all six sections; the scoped role preview
reported `changed=0` after deployment.

**Monitoring health deployed 2026-10-26:** Grafana is monitored as
`grafana!api-health`, with VictoriaMetrics and Graylog also checked. The
authenticated dashboard opens on **Monitoring health**, showing those checks
first, followed by the Icinga peer and three new Argon checks: Icinga Web's
login endpoint, local Icinga Web/DB support units, and SmokePing's CGI. All
three new checks returned OK, the complete smoke suite passed, and the scoped
preview reported `changed=0`. These UI checks are separate from Icinga's core
checker. Stage 3 Discord/Telegram notifications remain off until their
dedicated secrets are provided.

## Decision

Deploy Icinga 2 as an HA pair on `argon-01` and `argon-02` for core control-plane checks and direct notifications. Use OCI/Pangolin purely as an external target; it is not a dead-man receiver or a monitoring control-plane host.

Run native Icinga 2 under systemd, not Docker. This intentionally avoids depending on Docker, Portainer, image pulls, or writable container layers for the observer itself. The existing Portainer Agent remains for other Pi workloads.

Checks and notifications must not depend on Icinga Web, Icinga DB, Redis, Director, or a database: they add stateful dependencies to the service whose purpose is to remain useful when the main monitoring stack is impaired. The core checker runs from Git-managed Icinga configuration without these services. **Revised 2026-10-25 (operator):** Stage 5 added Icinga Web 2 + Icinga DB on `argon-01` as a strictly non-critical consumer, served directly (not via Traefik, no Authentik) with its own Let's Encrypt certificate and native login. Director is still out.

## Failure-domain rationale

| Component | Independent of `pve` | Independent of home router/power/ISP |
|---|---:|---:|
| `argon-01` + `argon-02` | Yes | No |
| OCI/Pangolin | Yes | Yes |

The Pis cover a Proxmox or monitoring-stack failure. OCI supplies an Internet-side reference point and latency history. This plan deliberately does not try to diagnose the exact cause of a whole-home loss.

## Target topology

```text
OCI/Pangolin: public edge target
             ^ active probes from the Pis
             |
argon-01: Icinga master A <--- mutual TLS ---> Icinga master B: argon-02
             |                                      |
             +----------- LAN / MikroTik -----------+
                                |
                pve, Grafana/VM, Graylog, DNS, CA
```

The Pi pair shares one Icinga master zone. TCP 5665 is allowed only between the two Pi addresses. Icinga HA load-balances checks and notifications, so a surviving Pi takes over rather than both generating duplicate pages.

## Core check scope

| Target | Protocol-aware check | Why it matters |
|---|---|---|
| Icinga peer | ICMP, TCP 5665, API/status, service, time, disk | observer failure and HA proof |
| MikroTik | ICMP plus DNS recursion | LAN gateway/root cause |
| Technitium `.15` + `.17` | UDP/TCP queries for internal and public names | local resolver availability |
| `pve` | ICMP and API response on TLS port 8006 (expected unauthenticated 401) | production compute plane |
| VictoriaMetrics | `/health` | metrics store |
| Grafana | `/api/health` | dashboard and alert evaluator |
| Graylog | TCP 514 plus `/api/system/lbstatus` | log ingress and log platform |
| OpenBao | TLS `/v1/sys/health`, unsealed | secrets control plane |
| step-ca | ACME directory | certificate issuance |
| Traefik | TCP 443 (no unauthenticated health endpoint configured) | internal ingress reachability |
| Portainer | `/api/system/status` | container management |

Harbor, Authentik, NetBox, Nextcloud, and application stacks are deliberately out of phase 1 unless they directly support the alert path. Grafana remains the broad application and hardware monitor.

## Dependencies and notifications

- Model MikroTik as a parent dependency, avoiding a downstream alert storm when it fails.
- Require two failed results for ordinary APIs, with a separately chosen shorter rule for a missing Icinga peer. Always send recovery notifications.
- Stage 3 will send Icinga notifications to a dedicated Discord webhook and a second Telegram bot using three operator-written OpenBao values. Grafana, Graylog, and VictoriaMetrics are evidence sources, never notification prerequisites.
- Prove problem and recovery delivery when Stage 3 is enabled. Stage 2 fault drills were waived for this rollout, so notification suppression and failover are not yet demonstrated.

## OCI and Internet references

OCI is an external target, not a third Icinga master. A stretched Icinga zone would make a WAN partition a cluster incident and unnecessarily extend home monitoring trust into OCI.

The Pis actively check OCI's public Pangolin endpoint, certificate and public DNS. The SSH check is defined but disabled until a Pi-local key is authorised on OCI and its host key is pinned; no OCI-side change was made for Stage 2.

Do not deploy the custom OCI alert relay, a heartbeat receiver, an OCI Icinga cluster member, or a SmokePing service on OCI in this scope. Do not expose the Icinga API through Pangolin, and do not reuse the Newt tunnel for monitoring. There is no new OCI-to-home firewall rule, home port forward, or OCI reachability to a home VLAN.

From each Pi, compare independent categories: a resolver from two operators (for example `1.1.1.1` and `9.9.9.9`), Discord HTTPS, Telegram HTTPS, OCI/Pangolin HTTPS, and each local Technitium node. Interpret the resulting matrix instead of treating two public IPs as proof that the Internet is healthy.

## SmokePing

SmokePing is a diagnostic companion, not the primary alerting system. It is valuable for latency, jitter, packet-loss, and path trends, but does not provide Icinga's dependency model, acknowledgement, escalation, or notification control plane.

Run one local SmokePing instance on `argon-01`. Probe MikroTik, both Technitium nodes, OCI/Pangolin, and the two external resolvers. This gives the required home-to-OCI latency/loss record with no new OCI service, firewall rule, or control-plane dependency. Add a second probe only when a concrete reverse-path question justifies it.

## Staged delivery

### Stage 0 — preflight

- Confirm the existing OCI public endpoint, Pangolin certificate name, and home-source SSH policy; no new OCI firewall rule is planned.
- Inventory each Tier-1 endpoint, auth/CA needs, and firewall path; use existing health endpoints only.
- Allocate Pi FQDNs, static IPs, Icinga certificates, OpenBao entries, and least-privilege accounts.
- Document the dependency graph, notification matrix, severity, timeout, retries, owner, and rollback for every check.

**Gate:** no broad admin credential, no new public management endpoint, and every notification has a recovery path.

### Stage 1 — Pi HA base

- Install Icinga 2 and check plugins natively on both Pis from Debian's repositories. Native Debian packages are deliberately **not** pinned: they stay current through unattended-upgrades (operator decision 2026-10-25; pinning is for containers).
- Configure master-zone mutual TLS, checker, notification, API, logging, and systemd hardening; limit TCP 5665 to the pair.
- Add peer/self checks only. Drill a cluster disconnect, one-Pi reboot, Icinga restart, and notification failover without touching `pve`.

**Gate:** exactly one notification for a single-Pi fault; the surviving peer continues checks; recovery arrives; no duplicate notification.

### Stage 2 — core checks

- **Deployed:** router/DNS, `pve`, VictoriaMetrics/Grafana/Graylog,
  OpenBao/step-ca/Traefik/Portainer, and OCI public HTTPS/certificate/DNS.
- **Deployed:** MikroTik parent dependencies and ordinary-check retry rules.
- **Deferred:** OCI SSH until its separate identity and pinned host key exist.
- **Waived for this rollout:** controlled fault and recovery drills. Suppression
  and notification delivery remain unproven until Stage 3.

**Verification:** all 14 hosts and 31 services OK in Icinga's current Redis
state on 2026-10-26; the scoped default preview had no changes and the full
smoke suite passes. See [runbook.md](runbook.md) §2.5.

### Stage 3 — notification proof

- **Pending operator input:** write a dedicated Discord webhook, Telegram bot
  token and chat ID to `services/icinga-observer` in OpenBao. The notification
  source exists but is disabled by default.
- Configure direct Discord/Telegram notifications and verify destination
  reachability and delivery.
- Forward Icinga logs to Graylog as evidence only, never as a prerequisite.
- Prove that a Grafana or VictoriaMetrics outage is notified by Icinga even though Grafana cannot alert itself.

### Stage 4 — local SmokePing against OCI

- Deploy one local SmokePing instance on `argon-01`; add OCI/Pangolin and external targets.
- Prove the latency/loss graphs distinguish local gateway, resolver, and OCI-edge faults.

**Gate:** useful latency/loss history exists for the home-to-OCI path without any new OCI service or exposure.

### Stage 5 — Icinga Web 2 + Icinga DB (operator decision 2026-10-25)

- Add Icinga Web/DB on `argon-01` as a non-critical consumer, never required for checks or notifications. See [runbook.md](runbook.md) Stage 5.

## Acceptance and residual risk

- Both Pis run checks and the cluster reconnects after a peer service restart;
  full reboot/failover and duplicate-notification drills remain open.
- `pve`, Grafana and VictoriaMetrics are checked from outside the monitoring
  stack; outage notification delivery remains a Stage 3 proof.
- OCI/Pangolin HTTPS, certificate and public DNS are checked; SSH policy
  detection remains deferred.
- SmokePing stores home-to-OCI latency/loss history without exposing a home
  service to the Internet.
- This does not replace Grafana alerting, hardware metrics, Graylog, Wazuh, or backup monitoring.
- Technitium already has a `pve-tiny` cluster secondary; this plan does not move DNS to a Pi or revive Pi-hole.
