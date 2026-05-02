# Architect Handoff: Session teardown-fastpath-01

**Prepared for:** Architect review and DoP approval
**Session:** teardown-fastpath-01
**Issue:** #172
**Date:** 2026-05-02
**Status:** Ready for review — pve-test is clean (0 containers); ordering issues partially resolved

---

## Executive Summary

Executor successfully validated teardown and foundation deployment phases of the platform stack. **Destroy completed 100%; foundation deployed 100%; edge deployment blocked by newly discovered Harbor HTTPS timing dependency.**

**Critical Finding:** Traefik + OIDC + Authentik integration introduces cascading stage-ordering dependencies not captured in current inventory model:
- ✅ **FIXED:** step-ca must precede proxy-stack for CA bundle provisioning
- ⏳ **BLOCKER:** Harbor HTTPS must be ready during proxy-stack provisioning (connection refused at 10.57.3.10:443)

**Recommendation:** Before advancing to production deployment, architecture must address Harbor HTTPS initialization timing or refactor bootstrap sequencing.

---

## Session Deliverables

### Commits (5 total)

| SHA | Message | Impact |
|---|---|---|
| `c55d412` | chore: enable teardown fast-path harness preconditions | Metadata: executor behavior, gitignore |
| `b6e1c75` | docs: architect guidance on homogeneous sessions | Metadata: guidance on session separation |
| `6ca8cef` | **fix: correct stage 3a deploy ordering** | **OPERATIONAL:** step-ca before proxy-stack |
| `d566557` | docs: session report for teardown-fastpath-01 | Evidence: full execution details |
| `f604d60` | docs: architect handoff summary | This document |

### Key Artifacts

- **Session Report:** [docs/sessions/session-teardown-fastpath-01-report.md](docs/sessions/session-teardown-fastpath-01-report.md) — Full gate results, blockers, ordering findings
- **Inventory Update:** [docs/teardown-test/inventory.md](docs/teardown-test/inventory.md) — Stage 3a order corrected
- **Approval Packet:** `.git/ai/20260502-fastpath-rerun-01.approval.md` — Teardown authorization metadata
- **Teardown Evidence:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/` — Full log archive

---

## Execution Summary

### Phase Results

| Phase | Status | Details |
|---|---|---|
| **Target Guard** | ✅ PASS | pve-test confirmed |
| **Destroy** | ✅ PASS | 10 stacks removed, VMs verified absent (VMID status checks clean) |
| **Deploy Foundation** | ✅ PASS | apt-cacher, harbor (OIDC disabled), ci-runner healthy |
| **Deploy Edge** | ❌ FAIL | Blocked at proxy-stack provisioning phase |
| **Activate Edge** | ⏸ SKIP | Not reached (blocked by edge failure) |
| **Deploy Platform** | ⏸ SKIP | Not reached (blocked by edge failure) |
| **Final Validation** | ⏸ SKIP | Not reached (blocked by edge failure) |

### Current Infrastructure State

**pve-test:** ✅ CLEAN — `pct list` returns empty (verified 2026-05-02T06:18:39Z)
All stacks torn down and Terraform state reconciled. No orphaned resources detected.

---

## Ordering Bugs Discovered

### Bug #1: step-ca Must Precede proxy-stack ✅ FIXED

**Symptom:**
```
cat: /usr/local/share/ca-certificates/homelab-root.crt: No such file or directory
```

**Root Cause:** proxy-stack provisioning attempts to build combined CA bundle for lego before step-ca has installed the homelab root CA certificate.

**Fix Applied:** Reordered Stage 3a from `dns → proxy → step-ca → authentik` to `dns → step-ca → proxy → authentik`

**Commit:** `6ca8cef`

**Evidence Path:** `docs/teardown-test/inventory.md` (Approved Deploy Order section)

---

### Bug #2: Harbor HTTPS Not Ready During proxy-stack Provisioning ⏳ BLOCKING

**Symptom:**
```
[ERROR]: Task failed: Module failed: Error when processing traefik:
Head "http://10.57.3.10/v2/dockerhub/library/traefik/manifests/v3.1.6":
Get "https://10.57.3.10/service/token?scope=repository%3Adockerhub%2Flibrary%2Ftraefik%3Apull&service=harbor-registry":
dial tcp 10.57.3.10:443: connection refused
```

**Root Cause:** proxy-stack attempts image pull from Harbor HTTPS (`10.57.3.10:443`) during provisioning (Stage 3a), but Harbor was deployed in Stage 1/2 with `HARBOR_OIDC_ENABLED=false` and HTTPS listener is not fully responsive.

**Impact:** Blocks completion of edge deployment and all subsequent stages.

**Evidence Path:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/provision-proxy-stack.log`

---

## Root Cause Analysis: Cascading Dependencies

The discovery of these ordering issues reveals a fundamental architectural problem introduced by **Traefik + OIDC + Authentik middleware wiring**:

### Before (Simpler Stages)
- Foundation stacks (apt-cacher, harbor, ci-runner) had minimal interdependencies
- Edge stacks (dns, proxy, step-ca, authentik) depended on foundation but not on each other during provisioning
- Runtime dependencies were handled by reconciliation (activate-edge) after deploy

### After (Traefik/OIDC Everywhere)
- Traefik requires system CA bundle during provisioning (step-ca dependency) ← NEW
- Traefik pulls images from Harbor HTTPS during provisioning (Harbor timing dependency) ← NEW
- Harbor OIDC reconciliation requires Authentik routing during provisioning (Authentik timing dependency) ← NEW
- Proxy middleware (Authentik forwardAuth) requires both Harbor and Authentik ready ← CROSS-STAGE

### Current Inventory Model Limitation
The inventory `depends_on` field captures **runtime** dependencies but not **provisioning-time** sequencing constraints. The harness deploy order resolver follows `depends_on`, which is insufficient for stages with shared infrastructure interdependencies.

---

## Workarounds Applied in This Session

| Workaround | Reason | Status |
|---|---|---|
| `HARBOR_OIDC_ENABLED=false` during foundation | Harbor OIDC reconciliation fails before Authentik is routable | Temporary (should be re-enabled during activate-edge) |
| Reorder Stage 3a: step-ca before proxy | CA bundle needed during proxy provisioning | Permanent fix applied |

---

## Options for Resolving Bug #2 (Harbor HTTPS Timing)

### Option A: Wait-for-Harbor-HTTPS in proxy-stack provisioning (RECOMMENDED)

**Implementation:** Add pre-flight task to `deploy-proxy-stack.yml` that polls Harbor HTTPS readiness before provisioning.

```yaml
- name: Wait for Harbor HTTPS to be ready
  uri:
    url: https://10.57.3.10/health
    method: HEAD
    validate_certs: false
    follow_redirects: no
  retries: 30
  delay: 5
  register: harbor_https_check
  until: harbor_https_check.status in [200, 401, 403, 404]
```

**Pros:**
- Minimal code change; isolated to proxy playbook
- Maintains current stage ordering
- Robust to transient delays in Harbor startup

**Cons:**
- Increases proxy provisioning time by up to 150s (30 retries × 5s delay)

---

### Option B: Split Harbor Provisioning into Two Phases

**Implementation:**
1. **Foundation phase:** Deploy Harbor, basic proxy configuration (HTTP only), ci-runner
2. **Activation phase:** Harbor OIDC reconciliation, Harbor HTTPS cert injection, proxy restart with HTTPS routes

**Pros:**
- Decouples foundation from HTTPS timing
- Allows platform stacks to deploy on HTTP-only Harbor if needed
- Cleaner dependency graph

**Cons:**
- More complex provisioning workflow
- Requires new activation tasks for Harbor HTTPS/OIDC
- Higher refactoring effort

---

### Option C: Refactor Bootstrap Sequencing to Waterfall

**Implementation:** Run stages truly sequentially with activation and health checks between each:
1. Stage 1/2: foundation (all containers stable)
2. **Checkpoint:** health-check-foundation (all services HTTP/ports responsive)
3. Stage 3a: edge (all containers stable)
4. **Checkpoint:** health-check-edge (DNS, Traefik, CA, Authentik all ready)
5. **Activation:** reconcile + publish edge routes
6. Stage 3b: platform (all containers stable)

**Pros:**
- Eliminates most ordering surprises
- Clear handoff points for validation
- Easier to debug bottlenecks

**Cons:**
- Significantly longer overall deployment time
- Requires rearchitecting the deploy harness
- May not scale if new stacks have complex dependencies

---

## Recommendations for Architect

### Immediate Actions (Before Next Teardown/Deploy Test)

1. **Apply Option A (wait-for-Harbor-HTTPS)** to `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
   - Low-risk, high-confidence fix
   - Unblocks this session's test
   - Can be validated in quick re-run

2. **Document provisioning-time constraints** in inventory or harness
   - Add `provisioning_depends_on` field to inventory if going forward with Stage 3a order
   - Or document in deployment runbook

3. **Re-run teardown-fastpath-01 cycle** with Option A applied
   - Validate destroy + foundation + edge + platform phases complete
   - Confirm final-validation passes

### Medium-term (Before Production Deployment)

4. **Conduct architecture review** on Traefik/OIDC middleware sequencing
   - Evaluate whether bootstrap stages are sustainable with more stacks added
   - Decide between Option A (incremental), Option B (split Harbor), or Option C (refactor)

5. **Update deploy runbook** with new ordering constraints and timing expectations
   - Communicate 3–5 minute startup delays during edge provisioning (if Option A applied)

### Optional (Post-Deployment)

6. Consider moving to **declarative orchestration** (Helm, Kustomize) if managing stage interdependencies becomes unsustainable

---

## Evidence Archive

All logs and evidence are available at:
```
docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/
```

Key logs:
- `destroy-*.log` — Individual destroy operations (all PASS)
- `provision-*.log` — Provisioning output (foundation PASS, proxy FAIL)
- `provision-proxy-stack.log` — Detailed error trace for Bug #2

---

## Next Steps for Executor

1. Implement Option A (wait-for-Harbor-HTTPS) in proxy-stack playbook
2. Re-run `./with-secrets bash scripts/teardown-deploy-test.sh cycle --stamp 20260502-fastpath-rerun-02 ...` to validate full cycle
3. If all phases PASS, prepare handoff to production deployment

---

## Approval Gate

**Ready for architect review:** YES ✅

This branch (`work/teardown-validate-post-netbox-sso-01`) is ready for architect to:
- Review findings and recommendations
- Approve Option A, B, or C for Harbor HTTPS resolution
- Decide go/no-go for production deployment

**Do NOT merge to `baseline/teardown-validated` or `dev/pve-test` until:** Architect approves remediation strategy and confirms Option A (or chosen alternative) has been implemented and tested.
