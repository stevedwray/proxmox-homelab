# Executor Session Report: teardown-fastpath-01

**Session:** `teardown-fastpath-01`
**Branch:** `work/teardown-validate-post-netbox-sso-01`
**Issue:** `#172`
**Date:** 2026-05-02
**Goal:** Execute full teardown/redeploy test on pve-test with fast-path ceremony relaxation for tooling changes

---

## Session Metadata

| Field | Value |
|---|---|
| Session ID | `teardown-fastpath-01` |
| Branch | `work/teardown-validate-post-netbox-sso-01` |
| HEAD SHA at start | `028d37798cd8c633de43ffcefb84e5f1d7656dc7` |
| HEAD SHA at end | `6ca8cef` (commit: ordering fix) |
| Baseline anchor | `028d37798cd8c633de43ffcefb84e5f1d7656dc7` |
| Working tree | clean (after commits) |
| Target guard | **PASS** — pve-test |
| Lineage check | **PASS** — baseline is ancestor of HEAD |
| Open executor issues at start | none |

---

## Changes Made

### Committed

1. **[.github/agents/executor.agent.md](.github/agents/executor.agent.md)**
   _Commit:_ `c55d412`
   _Message:_ `chore: enable teardown fast-path harness preconditions (session teardown-fastpath-01) Refs #172`
   _Change:_ Added guidance for teardown fast-path branch behavior when operator explicitly requests rerun from current state.

2. **[.gitignore](.gitignore)**
   _Commit:_ `c55d412`
   _Message:_ Same as above
   _Change:_ Added `docs/sessions/evidence/` to ignored paths so evidence scratch does not dirty working tree.

3. **[.github/agents/architect.agent.md](.github/agents/architect.agent.md)**
   _Commit:_ `b6e1c75`
   _Message:_ `docs: architect guidance on homogeneous sessions and runnable gates (session teardown-fastpath-01)`
   _Change:_ Documented principle of keeping sessions homogeneous (separate meta/tooling work from infrastructure execution) and requiring gates to be runnable shell commands.

4. **[docs/teardown-test/inventory.md](docs/teardown-test/inventory.md)**
   _Commit:_ `6ca8cef`
   _Message:_ `fix: correct stage 3a deploy ordering—step-ca before proxy-stack (session teardown-fastpath-01) Refs #172`
   _Change:_ Reordered Stage 3a edge foundation from `dns -> proxy -> step-ca -> authentik` to `dns -> step-ca -> proxy -> authentik`.
   **Reason:** proxy-stack provisioning requires homelab root CA from step-ca; this dependency was introduced by Traefik + OIDC + proxy middleware wiring.

---

## Gate Results

### Pre-Execution Checks

| Check | Status | Evidence |
|---|---|---|
| **guard** | **PASS** | `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` returned exactly `pve-test` |
| **lineage** | **PASS** | `git merge-base --is-ancestor 028d37798cd8c633de43ffcefb84e5f1d7656dc7 HEAD` returned 0 |
| **branch** | **PASS** | `git rev-parse --abbrev-ref HEAD` returned `work/teardown-validate-post-netbox-sso-01` |
| **clean-tree** | **PASS** (after commits) | Working tree clean after committing fast-path and ordering fixes |

### Execution Gates

| Gate | Status | Notes |
|---|---|---|
| **destroy** | **PASS** | All 10 stacks (netbox, monitoring, authentik, step-ca, proxy, dns, ci-runner, harbor, apt-cacher, portainer) destroyed and verified absent |
| **deploy-foundation** | **PASS** — with workaround | apt-cacher, harbor (with `HARBOR_OIDC_ENABLED=false`), ci-runner all deployed and healthy |
| **deploy-edge** | **FAIL** | Stopped at proxy-stack provisioning due to Harbor HTTPS connectivity |
| **activate-edge** | **SKIP** | Not reached; blocked by deploy-edge failure |
| **deploy-platform** | **SKIP** | Not reached; blocked by deploy-edge failure |
| **final-validation** | **SKIP** | Not reached; blocked by deploy-edge failure |

---

## Blockers and Issues

### 1. **CRITICAL ORDERING: step-ca must precede proxy-stack** ✅ FIXED

**Status:** Fixed in commit `6ca8cef`
**Root Cause:** proxy-stack provisioning requires `/usr/local/share/ca-certificates/homelab-root.crt` (installed by step-ca provisioning). When proxy-stack was deployed before step-ca, provisioning failed with:
```
cat: /usr/local/share/ca-certificates/homelab-root.crt: No such file or directory
```

**Remediation:** Reordered Stage 3a: `step-ca` now deploys immediately after `dns-stack` and before `proxy-stack`.

**Evidence Path:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/provision-proxy-stack.log` (earlier attempts, before fix)

---

### 2. **BLOCKING ORDERING: Harbor HTTPS not ready during proxy-stack provisioning**

**Status:** Active blocker — prevents deploy-edge completion
**Root Cause:** proxy-stack tries to pull image `traefik:v3.1.6` from Harbor at `10.57.3.10:443` during provisioning. Harbor HTTPS connection is refused:
```
dial tcp 10.57.3.10:443: connection refused
```

Harbor was provisioned in Stage 1/2 (foundation) with `HARBOR_OIDC_ENABLED=false`, which may have skipped full initialization or left HTTPS listener not yet responsive when Stage 3a edge tries to use it.

**Possible Causes:**
- Harbor compose services still initializing SSL/TLS on HTTPS port 443
- Harbor-Authentik integration not yet published (OIDC was skipped in foundation phase)
- Timing issue: proxy-stack provisioning attempted before Harbor HTTPS fully ready

**Evidence Path:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/provision-proxy-stack.log`
Error output:
```
[ERROR]: Task failed: Module failed: Error when processing traefik:
Head "http://10.57.3.10/v2/dockerhub/library/traefik/manifests/v3.1.6":
Get "https://10.57.3.10/service/token?scope=repository%3Adockerhub%2Flibrary%2Ftraefik%3Apull&service=harbor-registry":
dial tcp 10.57.3.10:443: connection refused
```

**Remediation Options:**
1. Add explicit wait-for-harbor-https health check in deploy-edge before proxy-stack provisioning
2. Split Harbor provisioning into two phases: early (foundation + basic config), late (HTTPS + Authentik integration)
3. Add retry logic to proxy-stack provisioning with exponential backoff for image pull
4. Document Harbor HTTPS initialization timing and adjust inventory dependencies

---

### 3. **CASCADING EFFECT: Harbor OIDC reconciliation blocked foundation phase initially**

**Status:** Resolved in this session (worked around)
**Root Cause:** When `HARBOR_OIDC_ENABLED=true`, Harbor provisioning tries to reconcile Authentik OIDC client before Authentik routing is available. This blocks deploy-foundation on first run.

**Workaround Applied:** Ran deploy-foundation with `HARBOR_OIDC_ENABLED=false` to skip Authentik reconciliation during foundation phase. OIDC integration should be completed during activate-edge or platform phase when Authentik is up.

**Evidence Path:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/provision-harbor-stack.log` (first deploy-foundation attempt before workaround)

---

## Summary of Findings

### Newly Introduced Ordering Dependencies

This teardown test revealed **critical new ordering dependencies introduced by Traefik + OIDC + Authentik wiring**:

| Dependency | Stage | Details |
|---|---|---|
| step-ca → proxy-stack | Stage 3a edge | proxy needs homelab root CA bundle during provisioning |
| harbor-https → proxy-stack | Stage 3a edge | proxy needs Harbor HTTPS registry ready for image pull |
| authentik-stack → harbor-oidc | Stage 3a+b | Harbor OIDC reconciliation deferred until Authentik is routable |

The inventory dependency matrix (`depends_on` fields) in [docs/teardown-test/inventory.md](docs/teardown-test/inventory.md) did not capture provisioning-time (as opposed to runtime) ordering constraints. The harness resolver uses only `depends_on` ordering, not provisioning sequencing.

### Execution Progress

- ✅ **Destroy phase:** 100% complete, all 10 stacks removed, VMs verified absent
- ✅ **Foundation phase:** 100% complete (apt-cacher, harbor, ci-runner ready and healthy)
- ⏳ **Edge phase:** 40% complete (dns, step-ca ready; proxy blocked at provisioning)
- ❌ **Platform phase:** Not started (blocked by edge failure)
- ❌ **Validation phase:** Not started

---

## Recommendation

**Do not merge this branch into `baseline/teardown-validated` or `dev/pve-test` until:**

1. **Ordering blocker #2 is resolved:** Harbor HTTPS connectivity during proxy-stack provisioning must be guaranteed. Recommended fix is a wait-for-harbor-https task in proxy-stack provisioning playbook with timeout and retry logic.

2. **Ordering dependency documentation is updated:** Add provisioning-time constraints to inventory or harness, separate from runtime `depends_on` ordering.

3. **Full cycle re-run succeeds:** Rerun this session with ordering fixes applied. All gates must reach PASS status and final-validation must confirm live platform state.

The discovery of cascading ordering issues is valuable for refactoring the stack bootstrap sequence before production deployment. This session should be escalated to the architect for DoP review and reordering strategy.

---

## Evidence Artifacts

- **Teardown phase:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/destroy-*.log` (all PASS)
- **Foundation phase:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/deploy-*.log`, `provision-*.log` (apt-cacher, harbor, ci-runner PASS)
- **Edge provisioning failure:** `docs/teardown-test/evidence/20260502-fastpath-rerun-01/logs/provision-proxy-stack.log` (FAIL: Harbor HTTPS unreachable)
- **Session metadata:** `.git/ai/20260502-fastpath-rerun-01.approval.md` (approval packet used)
