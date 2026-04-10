# Homelab Build Plan — Phase Index

This directory contains per-phase planning documents for the greenfield rebuild of the proxmox-homelab. Each document is self-contained and intended to be used in a single AI-assisted work session.

## Phase sequence

Phases must be completed in order. Each phase lists its prerequisites explicitly.

| Phase | Document | Status | Gate |
|---|---|---|---|
| 00 | [Housekeeping](phase-00-housekeeping.md) | **Do first** | None |
| 01 | [CI Runner Deployment](phase-01-ci-runner-deployment.md) | After Phase 00 | Phase 00 complete |
| 02 | [Memory Upgrade (32 GB)](phase-02-memory-upgrade.md) | **Hard gate for Phase 04** | Phase 01 complete |
| 03 | [Code Quality & Bug Fixes](phase-03-code-quality.md) | Parallel with 01-02 | Phase 00 complete |
| 03b | [Harbor Setup: Trivy, Projects, Image Cache](phase-03b-harbor-setup.md) | **Before Phase 04** | Phase 00 complete |
| 03c | [Artifact Proxy (apt-cacher-ng + Terraform mirror)](phase-03c-artifact-proxy.md) | **Before Phase 04** | Phase 00 complete |
| 04 | [Core Shared Services](phase-04-core-shared-services.md) | After Phase 02 + 03b + 03c | Phase 02, 03b, and 03c complete |
| 05 | [Supply Chain Security](phase-05-supply-chain.md) | After Phase 04 | Phase 01, 03b, 04 complete |
| 06 | [Application Stack Migration](phase-06-app-stacks.md) | After Phase 05 | Phase 04, 05 complete |

## Architecture reference

See [docs/plans/GreenField.md](../plans/GreenField.md) for the full architecture rationale and technology selection.

## Repository conventions

- Branch from `dev/pve-test` for each phase or individual fix
- Short-lived branches follow the naming: `feat/<name>`, `fix/<name>`, `chore/<name>`
- Merge to `dev/pve-test`, never directly to `main`
- PR `dev/pve-test` → `main` only when the phase is stable and tested on pve-test
- Close GitHub issues with `Closes #N` in the commit message
- Run `gh issue close N --comment "..."` after each commit

## Key infrastructure addresses

| Service | IP | VMID |
|---|---|---|
| Harbor (registry) | `192.168.1.10` | 121 |
| NetBox (IPAM) | `192.168.1.30` | 119 |
| ci-runner-01 | `10.57.0.63` | 141 |
| apt-cacher-ng (Phase 03c) | `192.168.1.35` | 142 |
| Authentik (Phase 04) | `192.168.1.40` | 150 |
| Headscale (Phase 04) | `192.168.1.41` | 151 |
| step-ca (Phase 04) | `192.168.1.42` | 152 |
| Reverse proxy (Phase 04) | `192.168.1.43` | 153 |
| Monitoring (Phase 04) | `192.168.1.44` | 154 |
| Chainloop (Phase 05) | `192.168.1.45` | 155 |

## Open issues summary

| Issue | Phase | Priority |
|---|---|---|
| #66 CI runner deployment | 01 | Medium |
| #71 Pin GitHub Actions | 01 | Medium |
| #67 Bump pve-test to 32 GB | 02 | Medium — blocks Phase 04 |
| #35 SSL/TLS in proxmox_client.py | 03 | Critical |
| #48 MikroTik primary_ip4 bug | 03 | Medium |
| #28 Cognitive complexity | 03 | Critical |
| #49 gluetun-6881 duplicate | 03 | Low |
| #23 Shell function returns | 03 | Major |
| #26 Shell positional params | 03 | Major |
| #31 SSH options string | 03 | Minor |
| #75 harbor_installer var prefix | Deferred | Low |
| #27 _environ_get_and_map types | Deferred | Investigate first |
| #25 Nested ternary | Deferred | Major |
| #53 net-* teardown procedure | Deferred | Low |
