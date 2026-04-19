# Task 03 Cutover Semantics: Integration Summary

## Overview

Task 03 defines the safety contract for migrating browser routes from **legacy central Traefik config** to **stack-owned manifests** without creating duplicate host rules that cause deployment failures.

## The Problem Being Solved

### Legacy Model
- All per-service routes (Authentik, Harbor, Grafana, Portainer, NetBox, Traefik dashboard) are defined in **central Traefik config file**
- Central config acts as the single source of truth for browser routing

### New Model
- Each stack owns an `edge.yaml` manifest at `terraform/lxc/stacks/<stack>/edge.yaml`
- Renderer generates per-stack Traefik dynamic config files
- These replace per-service central route definitions

### The Collision Risk
During migration, the **same hostname exists in both places**:
- Legacy central route: `authentik.lab.gibbsgreatly.xyz`
- Generated stack route: `authentik.lab.gibbsgreatly.xyz`

This creates a duplicate host rule that Traefik cannot resolve — deployment fails.

## The One-Host Replacement Semantics

This task establishes a **four-step atomic pattern** to prevent collisions:

### Step 1: Dry-Run Detects Collision (Task 07)
The renderer checks for duplicate hosts:
- Collects all legacy central route hostnames from live Traefik config
- For each generated route, checks if its hostname exists in legacy routes
- **Fails dry-run** if collision found AND no `intendedReplacement` flag matches

```
If duplicate host AND no intendedReplacement → FAIL DRY-RUN
If duplicate host AND intendedReplacement matches → ALLOW DRY-RUN
```

### Step 2: Migration Task Marks Intended Replacement (Tasks 15-20)
A migration task may pass exactly one `intendedReplacement` host:
- Signals: "I know this host exists in central config, I'm replacing it"
- Allows renderer to pass dry-run validation
- **Only one host per migration task** (enforced in Task 07 validation)

### Step 3: Atomic Live Deployment (Tasks 15-20)
Live publish happens as a **single deployment unit**:
1. Remove the legacy central route
2. Add the generated route

This prevents any moment where both exist in the live system.

### Step 4: Post-Deployment Validation (Tasks 15-20, Task 21)
Re-run reconciler and confirm:
- No duplicate hosts reported
- No pending changes (complete no-op)
- All route, DNS, cert, and auth behaviors correct

## File Dependency Map

```
03-cutover-semantics.md (POLICY DEFINITION)
  ↓
decisions.md (Decision 5: Traefik Runtime Split)
  ├─ one-host replacement is explicit
  ├─ live publish removes central + adds generated as same unit
  └─ generated routes checked against both sources
  ↓
07-traefik-renderer.md (IMPLEMENTATION OF DETECTION & VALIDATION)
  ├─ checks for duplicate hosts
  ├─ enforces intendedReplacement semantics
  ├─ fails if collision without flag
  └─ fails if multiple flags in one manifest
  ↓
15-migrate-authentik.md (FIRST USE OF WORKFLOW)
17-migrate-grafana.md   (ESTABLISHES PATTERN)
16-migrate-harbor.md
18-migrate-portainer.md
19-migrate-netbox.md    (CONTINUES PATTERN)
20-migrate-traefik-dashboard.md (LAST USE OF PATTERN)
  ├─ each marks one intended replacement host
  ├─ each validates dry-run finds no collision
  ├─ each removes central route in same deployment unit
  └─ each confirms reconciler no-op after deploy
  ↓
21-final-cutover-cleanup.md (VALIDATES NO COLLISIONS REMAIN)
  ├─ verifies NO intendedReplacement flags left (all migrations done)
  ├─ verifies NO duplicate hosts between generated and central
  ├─ verifies central config has no per-service routes
  └─ confirms full stack-owned model achieved
```

## Validation Across Tasks

Each migration task (15-20) must validate:
1. **Dry-run validation** (Task 07 responsibility):
   - Renderer finds the intended replacement host
   - Renderer finds no accidental duplicates
   - Dry-run succeeds (pre-deployment gate)

2. **Deployment validation** (Migration task responsibility):
   - Central route removed + generated route added atomically
   - DNS resolves correctly
   - HTTPS returns correct service
   - Auth behavior matches requirements
   - Re-run reconciler shows no-op

3. **Final validation** (Task 21 responsibility):
   - All six services migrated (no intendedReplacement flags remain)
   - No duplicate hosts between generated and central
   - Central config contains only runtime/shared config
   - All six services accessible via browser hostnames
   - Second reconciler run is complete no-op
   - Rollback from previous snapshot tested

## Stop Conditions Across Tasks

Task 03 establishes the framework; each implementation task enforces:

- **Task 07**: Stop if generated route would shadow live central route without explicit intendedReplacement flag
- **Task 07**: Stop if more than one intendedReplacement host is set in a single manifest
- **Tasks 15-20**: Stop if migration requires more than one host replacement
- **Task 21**: Stop if any route, DNS record, certificate, or auth behavior regresses

## Expected Outcomes

After Task 03 is complete, the codebase should:

1. **Document the policy clearly** in `decisions.md` (Decision 5 pattern)
2. **Define the contract** for how manifests signal intended replacement
3. **Guide Task 07 implementation** with clear duplicate-host detection rules
4. **Enable Tasks 15-20** to follow a consistent, safe migration workflow
5. **Enable Task 21** to validate the complete cutover with explicit no-collision checks

## Implementation Checklist for Task 03

- [ ] **decisions.md**: Verify Decision 5 clearly describes one-host replacement semantics
- [ ] **07-traefik-renderer.md**: Verify duplicate-host detection rules are specified
- [ ] **15-migrate-authentik.md**: Verify it establishes the exact one-host replacement workflow
- [ ] **16-migrate-harbor.md through 20-migrate-traefik-dashboard.md**: Verify each follows the same pattern
- [ ] **21-final-cutover-cleanup.md**: Verify it does NOT imply broad route removal before migrations complete
- [ ] **Validation**: Run `rg -n "intended replacement|same deployment unit|duplicate host" docs/provisioning-refactor` to confirm language consistency
