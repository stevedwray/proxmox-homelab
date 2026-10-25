# Independent observability on the Argon Pis

## Status

**Revised 2026-10-25; Stage 0 implementation artifacts (playbook +
`icinga_observer` role) created and read-only preflight findings recorded
in [runbook.md](runbook.md) §0.4. No Icinga, firewall, router, OCI, or
notification change has been made on either Pi or anywhere else.**

This plan adds an independent observer for the current monitoring and notification path. It does not replace VictoriaMetrics, Grafana, Graylog, Wazuh, or their alert rules.

## Decision

Deploy Icinga 2 as an HA pair on `argon-01` and `argon-02` for core control-plane checks and direct notifications. Use OCI/Pangolin purely as an external target; it is not a dead-man receiver or a monitoring control-plane host.

Run native Icinga 2 under systemd, not Docker. This intentionally avoids depending on Docker, Portainer, image pulls, or writable container layers for the observer itself. The existing Portainer Agent remains for other Pi workloads.

Do not start with Icinga Web, Icinga DB, Redis, Director, or a database. They add stateful dependencies to the service whose purpose is to remain useful when the main monitoring stack is impaired. Phase 1 uses the Icinga API, CLI, Git-managed configuration, and notification commands.

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
| `pve` | ICMP, TCP 8006, API health | production compute plane |
| VictoriaMetrics | `/health` | metrics store |
| Grafana | `/api/health` | dashboard and alert evaluator |
| Graylog | TCP 514 plus `/api/system/lbstatus` | log ingress and log platform |
| OpenBao | TLS `/v1/sys/health`, unsealed | secrets control plane |
| step-ca | ACME directory | certificate issuance |
| Traefik | documented health endpoint | internal ingress |
| Portainer | `/api/system/status` | container management |

Harbor, Authentik, NetBox, Nextcloud, and application stacks are deliberately out of phase 1 unless they directly support the alert path. Grafana remains the broad application and hardware monitor.

## Dependencies and notifications

- Model MikroTik as a parent dependency, avoiding a downstream alert storm when it fails.
- Require two failed results for ordinary APIs, with a separately chosen shorter rule for a missing Icinga peer. Always send recovery notifications.
- Send critical Icinga notifications directly to existing Discord and Telegram destinations with narrowly scoped OpenBao credentials. Grafana, Graylog, and VictoriaMetrics are evidence sources, never notification prerequisites.
- Schedule controlled drills. A notification route that has never delivered a real test is not accepted.

## OCI and Internet references

OCI is an external target, not a third Icinga master. A stretched Icinga zone would make a WAN partition a cluster incident and unnecessarily extend home monitoring trust into OCI.

The Pis actively check OCI's public Pangolin endpoint, certificate, public DNS, and SSH from the already-permitted home source. This tests the path that actually exists, including the OCI firewall policy.

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

- Install pinned Icinga 2 and check plugins natively on both Pis.
- Configure master-zone mutual TLS, checker, notification, API, logging, and systemd hardening; limit TCP 5665 to the pair.
- Add peer/self checks only. Drill a cluster disconnect, one-Pi reboot, Icinga restart, and notification failover without touching `pve`.

**Gate:** exactly one notification for a single-Pi fault; the surviving peer continues checks; recovery arrives; no duplicate notification.

### Stage 2 — core checks

- Add router/DNS, then `pve`, then VictoriaMetrics/Grafana/Graylog, then OpenBao/step-ca/Traefik/Portainer.
- Add dependencies and thresholds before enabling notifications.
- Test one controlled fault at a time and prove suppression plus recovery.

**Gate:** an Icinga alert describes a root cause rather than every symptom.

### Stage 3 — notification proof

- Configure direct Discord/Telegram notifications and destination-health checks.
- Forward Icinga logs to Graylog as evidence only, never as a prerequisite.
- Prove that a Grafana or VictoriaMetrics outage is notified by Icinga even though Grafana cannot alert itself.

### Stage 4 — local SmokePing against OCI

- Deploy one local SmokePing instance on `argon-01`; add OCI/Pangolin and external targets.
- Prove the latency/loss graphs distinguish local gateway, resolver, and OCI-edge faults.

**Gate:** useful latency/loss history exists for the home-to-OCI path without any new OCI service or exposure.

### Stage 5 — optional additions

- Add Icinga Web/DB only if API/CLI operation proves insufficient; it is a non-critical consumer, never required for checks or notifications.

## Acceptance and residual risk

- Either Pi can fail without losing core checks or producing duplicate pages.
- A `pve` or monitoring-stack outage is detected by the surviving Pi while Grafana/VictoriaMetrics are unavailable.
- OCI/Pangolin and its home-source SSH policy are detected locally while direct notifications remain possible.
- SmokePing stores home-to-OCI latency/loss history without exposing a home service to the Internet.
- This does not replace Grafana alerting, hardware metrics, Graylog, Wazuh, or backup monitoring.
- Technitium already has a `pve-tiny` cluster secondary; this plan does not move DNS to a Pi or revive Pi-hole.
