# Project Observations

Running notes and observations collected during the greenfield rebuild. Not actionable —
these are reflections for future reference when revisiting decisions, patterns, or problems.

---

## General

<!-- Add observations that apply across phases here -->

---

## Phase 00b — pve-test Management Bootstrap

1. Portainer runs in its own dedicated LXC container. Originally expected that basic
   management services might be co-located in a single "management" container, but the
   pattern here is one service per LXC throughout the project.

2. The Portainer LXC connects directly to `vmbr0` (the physical LAN bridge) rather than
   being placed in any SDN-managed zone. It sits outside the segmented network topology
   created by the project's SDN code — it is a flat LAN citizen, not an SDN tenant.

   This is a pragmatic trade-off rather than a deliberate architectural decision. Portainer
   *could* live in an SDN zone (e.g. `mgmt_seg`) — the existing egress routing automation
   used for `build_seg` would handle LAN reachability. The two complications that drive the
   flat placement:
   - Portainer agents in other zones need a routed path back to the server. Achievable with
     the existing SDN automation, but requires additional routing rules.
   - Bootstrap ordering: the SDN zone must exist before Portainer can be deployed, but
     Portainer is what bootstraps everything else. This chicken-and-egg dependency needs
     careful resolution.

   The consequence is that the management plane (Portainer, NetBox, Harbor) is reachable
   from anything on `192.168.1.0/24` with no SDN policy enforcement in front of it —
   SDN isolation applies to application workloads but not to the management plane itself.
   Stricter access control for Portainer would need to come from Traefik + Authentik
   forward-auth (Phase 04), not from network segmentation.

---

## Phase 01 — CI Runner Deployment

<!-- Observations from deploying ci-runner-01, runner registration, SDN bootstrapping -->

---

## Phase 02 — Memory Upgrade

<!-- Observations from the pve-test VM resize -->

---

## Phase 03 — Code Quality and Bug Fixes

<!-- Observations from shell script maintainability, NetBox integration refactoring, SSL acknowledgement -->

---

## Phase 03b — Harbor Setup

<!-- Observations from Harbor configuration, Trivy, proxy caches, robot accounts -->

---

## Phase 03c — Artifact Proxy

<!-- Observations from apt-cacher-ng and Terraform provider mirror -->

---

## Phase 04 — Core Shared Services

<!-- Observations from Authentik, Headscale, step-ca, Traefik, Monitoring deployments -->

---

## Phase 05 — Supply Chain Security

<!-- Observations from Trivy CI integration, Syft, Cosign, Chainloop -->

---

## Phase 06 — Application Stack Migration

<!-- Observations from migrating arr stack, Jellyfin, Pi-hole, game services -->

---

## Tooling and Workflow

<!-- Observations about the AI-assisted workflow, Codex, Copilot, branching patterns, scan gates -->

---

## Patterns and Conventions

<!-- Observations about what stack patterns worked well, what was awkward, what to carry forward -->

---

## Things to Revisit

<!-- Decisions made under time pressure that deserve a second look later -->

