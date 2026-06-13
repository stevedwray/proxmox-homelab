# Phase Document Review — Staleness and Relevance Assessment

**Date:** 2026-05-22
**Reviewed by:** Copilot Analysis
**Baseline:** `baseline/teardown-validated` with recent VMID schema and storage refactor

---

## Executive Summary

The phase documents provide a structured deployment roadmap for the greenfield rebuild. **Most are still relevant** for understanding the platform architecture and deployment order. However, there are key documents that have been superseded by newer designs, and several that are explicitly historical.

**Key findings:**
- Phases 00a–04b are active and generally aligned with current implementation
- Phase 04c is **legacy context only** — active work moved to `docs/provisioning-refactor/`
- Phase 05–06 are relevant but contain some stale or incomplete task references
- Phase 07 is a **placeholder** with no concrete planning yet
- Phase 02 is **historical** and should not be referenced
- Phase 03 (Code Quality) remains valid but is tracked in GitHub issues rather than as a deployment phase
- `pve-production-readiness.md` identifies real gaps but is pre-implementation planning

---

## Document-by-Document Assessment

### ✅ Phase 00a — Proxmox Host Bootstrap Alignment

**Status:** Active and relevant

**Why it's still needed:**
- Defines the minimum host bootstrap requirements for pve-test
- Classifies Ansible playbooks as active, needs redesign, or historical
- Documents SDN setup, template building, and firewall backend enablement

**Current alignment:**
- Matches the active bare-metal pve-test model
- `ansible/00-initial-setup/` and `ansible/01-base-system/` automation is in use
- SDN VLAN zones are deployed via these playbooks

**Action:**
- Keep as-is; refer for host bootstrap validation
- Link from Phase 00c and Phase 00b task docs for context

---

### ✅ Phase 00b — pve-test Management Bootstrap

**Status:** Active and completed

**Why it's still needed:**
- Documents the isolation of pve-test from production Portainer dependency
- Establishes the greenfield model

**Current alignment:**
- Acceptance criteria marked complete (2026-04-16)
- Portainer running at 10.57.1.20 on mgmt_seg
- `.env.pve-test` exports correct TF_VAR_portainer_server_ip

**Action:**
- Keep as reference documentation
- Link from Portainer-related task docs

---

### ✅ Phase 00c — Bootstrap Sequence (Stage 1 → Stage 2)

**Status:** Active and relevant

**Why it's still needed:**
- Documents the two-stage bootstrap model resolving the circular dependency
- Defines Stage 1 temporary containers and Stage 2 permanent containers
- Explains security control progression

**Current alignment:**
- The overall model is sound and matches current implementation
- Stage 1 and Stage 2 containers follow this pattern
- Recent session (deploy-watch-01) successfully executed all stages

**Action:**
- Keep as the conceptual foundation
- Update task doc links if any have been renamed or reorganized
- Reference in Phase 04 prerequisites

---

### ✅ Phase 01 — CI Runner Deployment

**Status:** Active and completed

**Why it's still needed:**
- Restores self-hosted runner capability after greenfield rebuild
- Documents GitHub Actions pinning strategy
- Explains self-hosted validation and future build-pipeline path

**Current alignment:**
- ci-runner-01 deployed to pve-test at 10.57.0.63 in build_seg
- Runner is online with labels `self-hosted`, `pve-test`, `build`
- Action pins remain hardened to immutable SHAs

**Action:**
- Keep as reference for self-hosted runner maintenance
- Reference in GitHub Actions security and CI/CD docs

---

### ⚠️ Phase 02 — Memory Upgrade

**Status:** HISTORICAL — should not be used

**Why it's stale:**
- Was written for a **nested-VM model** of pve-test running inside a parent Proxmox host
- Current project uses **bare-metal pve-test laptop**
- `qm set` workflow no longer applies
- Document itself recommends treating it as historical only

**Action:**
- **Mark explicitly as "DO NOT USE"** in README.md or at the top of phase documents
- If capacity issues arise again, create a new task doc for bare-metal pve-test (not a memory upgrade — possibly a storage expansion or host replacement decision)
- Do not reference in any deployment sequence

---

### ✅ Phase 03 — Code Quality and Bug Fixes

**Status:** Active but treated as parallel work, not a deployment phase

**Why it's still needed:**
- Lists GitHub issues for maintainability improvements in shell scripts and Python integration code
- References SonarCloud rules and test isolation work
- Provides guidance for code quality debt paydown

**Current alignment:**
- Issue #189 (test isolation) was recently fixed (commit c5260bf)
- Many other issues remain open and are being tracked in GitHub Issues
- The phase should be reframed: these are not deployment blockers but ongoing quality improvements

**Action:**
- Move this from the "deployment phase sequence" to a separate "code quality and maintainability" section
- Link GitHub issues directly in README.md or docs/plan/README.md
- Do not gate deployment phases on Phase 03 completion

---

### ✅ Phase 03b — Harbor Setup

**Status:** Active and completed

**Why it's still needed:**
- Documents Harbor post-deployment configuration (proxy caches, robot account, Trivy, GC schedule)
- Defines the bridge between Harbor deployment and Phase 04 consumption

**Current alignment:**
- Harbor deployed to pve-test at 10.57.3.10
- Proxy caches configured for dockerhub, ghcr, quay, lscr
- CI robot account active (robot$ci-runner)
- Trivy scanner enabled and nightly schedule active
- Task docs reference this correctly

**Action:**
- Keep as-is
- Ensure task doc links are not stale

---

### ✅ Phase 03c — Artifact Proxy

**Status:** Active and relevant

**Why it's still needed:**
- Documents apt-cacher-ng deployment
- Defines Terraform provider mirror path
- Documents ci-runner follow-up configuration

**Current alignment:**
- apt-cacher-ng deployed at 10.57.3.11
- LXC base role includes `/etc/apt/apt.conf.d/01proxy` configuration
- Terraform mirror path defined at `terraform/terraform-providers/`

**Action:**
- Keep as-is
- Verify task doc references and acceptance criteria are current

---

### ✅ Phase 03d — Secrets Delivery Hardening

**Status:** Active (Stage 0 workstation-only task)

**Why it's still needed:**
- Documents the migration from `.env` + `sync-secrets.sh` to `./with-secrets` + SOPS
- Eliminates plaintext `.env` file from operator workflow
- Centralizes secrets in `terraform/secrets.enc.yaml`

**Current alignment:**
- SOPS age key at `~/.config/sops/age/keys.txt` is the workstation prerequisite
- `with-secrets` wrapper is merged and active
- All deployment commands use `./with-secrets` for secret injection
- `.env` approach is no longer part of the workflow (memory notes confirm this)

**Action:**
- Keep as reference for understanding the current secret delivery model
- Link from operator onboarding docs
- Phase 03d is merged and active on `baseline/teardown-validated`

---

### ✅ Phase 04 — Core Shared Services

**Status:** Active and mostly deployed

**Why it's still needed:**
- Documents deployment order: Authentik → Traefik → step-ca → Monitoring
- Explains dual certificate strategy (Let's Encrypt + internal CA)
- Defines prerequisite SDN zones and MikroTik configuration

**Current alignment:**
- Authentik running at 10.57.1.10
- Traefik running at 10.57.2.10
- step-ca running at 10.57.1.11
- Monitoring (VictoriaMetrics + Grafana + Loki) running at 10.57.1.12
- Deploy-watch-01 session validated all stacks successfully
- Task docs are linked and appear to be current

**Action:**
- Keep as-is
- Update any task doc references if names have changed
- Reference from Phase 06 prerequisites

---

### ✅ Phase 04b — Internal DNS Authority

**Status:** Active and completed

**Why it's still needed:**
- Documents CoreDNS deployment as authoritative server for `lab.gibbsgreatly.xyz`
- Explains DNS forward chain: CoreDNS ← MikroTik ← LXC containers
- Defines zone content and upstream forwarding

**Current alignment:**
- Completion gate marked as complete (2026-04-18)
- CoreDNS deployed at 10.57.1.13 (VMID 151)
- MikroTik FWD rule active for lab zone delegation
- VictoriaMetrics scraping CoreDNS metrics

**Action:**
- Keep as-is
- Reference from Phase 04c refactor docs as the existing baseline

---

### ⚠️ Phase 04c — Stack-Owned Ingress, Auth, and DNS

**Status:** LEGACY CONTEXT — active work moved to `docs/provisioning-refactor/`

**Why it's stale:**
- The document itself states: "The active refactor plan has moved to `docs/provisioning-refactor/`"
- Refers to legacy apex-style routing (`*.gibbsgreatly.xyz`) instead of current `*.lab.gibbsgreatly.xyz`
- Workstreams (04c-01 through 04c-06) are not the current execution model

**Current alignment:**
- The provisioning-refactor directory contains updated decisions and task order
- Stack-owned edge manifest model is more current than the Phase 04c design

**Action:**
- Mark this document as "LEGACY CONTEXT — see `docs/provisioning-refactor/` for active work"
- Add a prominent note at the top redirecting readers
- Do not reference in deployment sequence; use provisioning-refactor docs instead

---

### ⚠️ Phase 05 — Supply Chain Security

**Status:** Relevant but with placeholder task references

**Why it's partially stale:**
- Part A (Trivy CI scanning) and Part B (Syft SBOM generation) contain example code that may need updating
- CI runner follow-up and GitHub Actions secret references assume a specific workflow state
- SBOM generation and signing details are partially incomplete

**Current alignment:**
- Harbor Trivy scanning is active (Phase 03b complete)
- CI runner is deployed with GitHub Actions integration (Phase 01 complete)
- The overall goal (secure supply chain) is sound and necessary before Phase 06

**Action:**
- Review task doc references and update example code if it conflicts with current CI structure
- Verify GitHub Actions secrets are documented correctly in the workflow
- Consider splitting Part B into a separate task doc
- Mark incomplete sections with `[TODO]` or `[WIP]`

---

### ✅ Phase 06 — Application Stack Migration

**Status:** Relevant but requires discovery-first approach

**Why it's still needed:**
- Documents the approach for migrating application workloads (Pi-hole, arr, Jellyfin, etc.)
- Defines segmentation target (app_seg, game_seg)
- Recommends parallel deployment plus cutover for existing services

**Current alignment:**
- The platform foundation (Phase 04, 04b, 04c foundation) is ready
- Application services are not yet migrated
- The document recommends discovery of current production state first

**Gaps identified:**
- Table for "Current state of application workloads" is marked as "discovery required"
- Pi-hole, arr, Jellyfin, and game services are not yet defined in Terraform stacks
- NetBox is deployed (Phase 03b) but not application stacks

**Action:**
- Keep as the deployment sequence for application migration
- **Action item:** Run discovery on pve-test to populate "Current state of application workloads" table
- Create task docs for each application migration (Pi-hole first as critical DNS resolver)
- Verify app_seg and game_seg zone definitions are added to Proxmox SDN or documented as manual prerequisites

---

### ⚠️ Phase 07 — Runtime Security and Secrets Management

**Status:** PLACEHOLDER — not yet planned

**Why it's a placeholder:**
- Document explicitly states "Placeholder — not yet planned. Requires Phase 06 complete."
- OpenBao, Falco, and CrowdSec are deferred until application layer is stable
- No acceptance criteria, task docs, or implementation details

**Why it's still relevant:**
- Correctly identifies the three capability areas (OpenBao, Falco, CrowdSec)
- Explains deferral reasoning (need stable app layer first)
- Will be needed after Phase 06

**Action:**
- Move to a "future-phases" or "placeholder-phases" directory or section
- Update when Phase 06 is complete and Phase 07 planning begins
- Reference from architectural docs as a future capability roadmap

---

## Standalone Documents (Not Phase Sequence)

### ✅ `pve-production-readiness.md`

**Status:** Pre-implementation planning — identifies real gaps

**Why it's relevant:**
- Documents storage, network, VMID, and IP collision inventory
- Proposes environment-specific parameterization strategy
- Recommends workstream order for production rollout

**Current alignment:**
- Storage findings are accurate (infrastructure-containers, storage-containers exist on pve)
- Network findings are accurate (VLAN readiness is a prerequisite)
- VMID and IP collision analysis is thorough and current
- Workstreams are a reasonable next-steps plan

**Gaps:**
- `.env.pve` overlay is not yet created
- `terraform/lxc/storage/pve.yaml` does not exist
- `terraform/lxc/network/pve.yaml` needs rewrite (currently uses simple zones, not VLAN zones)
- Production stack environment pinning (proxmox_node: pve) not yet addressed

**Action:**
- Keep as the production rollout roadmap
- Create tracking issues or task docs for each workstream
- Mark as "Pre-implementation — do not attempt before Phase 06 is stable on pve-test"

---

### ✅ `development-status.md`

**Status:** Active — tracks rebuild confidence per component

**Why it's valuable:**
- Provides honest gap analysis for each platform service
- Separates "deployed" from "rebuild-safe"
- Identifies secrets management, integration, and automation gaps

**Current alignment:**
- As of deploy-watch-01, all 10 infrastructure stacks passed gates
- Detailed gap analysis for Traefik (secrets, LE cert persistence, Authentik outpost automation)
- Detailed gap analysis for Authentik (secrets, initial setup, Terraform provider automation)
- Detailed gap analysis for Monitoring (depends on Authentik OIDC provider)
- Detailed gap analysis for step-ca (CA rebuild invalidates issued certs; retroactive trust not enforced)

**Action:**
- Update after each major deployment pass or refactor
- Link from operational runbooks as the source of truth for known limitations
- Track Terraform provider automation gaps as issues/tasks

---

## Documentation Gaps and Recommendations

### Missing or Needed Documents

1. **Production environment setup guide** — How to prepare pve host for the first segmented VLAN deployment
2. **Day 2 operations runbook** — Covers routine changes to deployed services (cf. next-session.md suggests apt-cacher-stack as first Day 2 exercise)
3. **Incident response playbook** — What to do if a platform service fails mid-deployment
4. **Secrets rotation guide** — How to rotate Proxmox token, Authentik secret, Cloudflare token, etc.
5. **Failover and recovery procedures** — Step-by-step recovery for pve-test from storage or network failure

### Stale Cross-References

- Phase documents refer to `.env.template` which is now deprecated in favor of SOPS
- Some task docs may reference `.env` directly instead of `./with-secrets`
- Old references to `sync-secrets.sh` should be removed
- References to `Nginx Proxy Manager` should be cleaned up (no longer a platform component)

---

## Revised Phase Sequence Recommendation

**For new operators or fresh deployments, reference:**

1. Phase 00a — Host Bootstrap (prerequisite)
2. Phase 03d — Secrets Setup (Stage 0, one-time)
3. Phase 00b — pve-test Management Bootstrap
4. Phase 00c — Two-Stage Bootstrap (Stage 1 and Stage 2)
5. Phase 01 — CI Runner
6. Phase 03b — Harbor Configuration
7. Phase 03c — Artifact Proxy
8. Phase 04 → 04b → [provisioning-refactor for 04c] → Phase 05
9. Phase 06 — Application Migration (discovery-first)
10. Phase 07 — Runtime Security (future placeholder)

**Skip:** Phase 02 (historical, bare-metal only)

---

## Summary Table

| Phase | Status | Relevance | Action |
|---|---|---|---|
| 00a | ✅ Active | High | Keep; link from task docs |
| 00b | ✅ Complete | High | Keep as reference |
| 00c | ✅ Active | High | Keep; reference in 04+ |
| 01 | ✅ Complete | High | Keep; reference from CI docs |
| 02 | ❌ Historical | None | Remove from sequence; mark "do not use" |
| 03 | ✅ Parallel | Medium | Reframe as code quality work, not deployment phase |
| 03b | ✅ Complete | High | Keep as-is |
| 03c | ✅ Complete | High | Keep; verify task links |
| 03d | ✅ Active | High | Keep; link from onboarding |
| 04 | ✅ Active | High | Keep; update task links if needed |
| 04b | ✅ Complete | High | Keep; reference from Phase 06 |
| 04c | ⚠️ Legacy | Low | Mark "see provisioning-refactor/"; redirect |
| 05 | ✅ Relevant | Medium | Review task example code; mark TODOs |
| 06 | ✅ Relevant | High | Update with app discovery results |
| 07 | ⚠️ Placeholder | Low | Move to "future-phases"; plan after Phase 06 |
| pve-prod-ready | ⚠️ Pre-impl | Medium | Keep; create workstream issues |
| development-status | ✅ Active | High | Update after deployments; use for runbooks |

---

## Recommended Next Steps

1. **Update Phase 02 marker** — Add "DO NOT USE" notice at the top; this is bare-metal only
2. **Redirect Phase 04c** — Add a prominent notice pointing to `docs/provisioning-refactor/`
3. **Reframe Phase 03** — Move to code quality / maintainability section; do not gate deployments
4. **Create production workstream issues** — One GitHub issue per workstream in pve-production-readiness.md
5. **Create Phase 06 discovery task** — Document current app state on pve-test before migration planning
6. **Update development-status.md** — Refresh after next full platform deployment cycle
7. **Create Day 2 operations guide** — Use next-session.md guidance to build the first Day 2 playbook (apt-cacher-stack)
