# Phase 07 — Runtime Security and Secrets Management

## Status

**Placeholder — not yet planned. Requires Phase 06 complete.**

## Goal

Extend the platform with runtime-level security controls and centralised secret brokering
that are out of scope for the current platform build but form the natural next layer after
application stacks are stable.

This phase covers three capability areas that the GreenField design identified but deferred:

1. **OpenBao** — runtime secret distribution, dynamic credentials, leasing, and rotation
2. **Falco** — kernel-level runtime detection for Linux hosts and containers
3. **CrowdSec** — behaviour-based network blocking for edge-exposed services and SSH ingress

## Why these are deferred

All three capabilities require a stable application layer to be useful:

- OpenBao needs services to consume secrets before there is value in a secret broker
- Falco policy needs a known-good baseline of container behaviour to tune against
- CrowdSec needs live traffic to learn from and actual exposed endpoints to protect

Deploying them before Phase 06 (app stacks) would produce a platform that monitors and
protects nothing meaningful.

## Related GreenField sections

- GreenField §6 — Secrets and configuration (OpenBao)
- GreenField §9 — Runtime security and detection (Falco, CrowdSec)

---

## Part A — OpenBao (runtime secrets and dynamic credentials)

**Prerequisite:** SOPS + age covers Git-stored secrets. Add OpenBao only when centrally
brokered secrets, leasing, rotation, or dynamic credentials are genuinely needed.

Candidate use cases:
- Dynamic database credentials for application stacks
- Short-lived SSH certificates issued by step-ca via OpenBao SSH secrets engine
- Secret leasing with automatic revocation when a container restarts

Intended network placement: `mgmt_seg`, alongside Authentik and step-ca.

---

## Part B — Falco (container and host runtime detection)

**Prerequisite:** Application stacks stable and running; a baseline traffic profile exists.

Falco monitors kernel system calls and applies rules for suspicious container or host
behaviour: unexpected process spawns, privileged operations, network connections outside
expected ranges, and file access violations.

Intended deployment: one Falco instance per Docker host running application workloads.
Alert output targets the Phase 04 monitoring stack (Loki/Grafana).

---

## Part C — CrowdSec (network-level behaviour-based blocking)

**Prerequisite:** Phase 04 Traefik reverse proxy running; application stacks exposed.

CrowdSec is best suited to edge and SSH entry points. Deploy a CrowdSec agent on:
- The Traefik LXC (edge_seg) — to parse access logs and feed the Traefik bouncer
- Any SSH-accessible host in mgmt_seg

The Phase 04 monitoring stack can ingest CrowdSec metrics as an additional Loki source.

---

## Acceptance Criteria

To be defined when this phase is planned.

## Out of Scope

- Chainloop / supply-chain attestation (descoped permanently — see Phase 05 notes)
- Full SIEM / Security Onion deployment (separate greenfield concern outside this plan)
- WAF (open-appsec or similar) — evaluate alongside CrowdSec if external exposure grows
