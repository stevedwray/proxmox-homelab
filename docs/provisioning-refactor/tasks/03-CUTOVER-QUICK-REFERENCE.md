# Task 03 Cutover Semantics: Quick Reference for Implementers

This guide explains what Task 03 (cutover semantics) requires from each downstream task.

---

## For Task 07 (Traefik Renderer)

**Task 03 requires you to implement:**

### 1. Manifest Validation
```
Input: manifests/<stack>/edge.yaml

Before rendering, validate:
□ If intendedReplacement exists, it has exactly 1 hostname
□ That hostname matches exactly 1 generated route in the manifest
□ Return clear error if validation fails
```

### 2. Duplicate-Host Detection Algorithm
```
For each generated hostname:
  □ Check if it exists in the live central Traefik config
  □ If YES and intendedReplacement matches this hostname → ALLOW
  □ If YES and NO intendedReplacement flag → FAIL with clear error
  □ If NO → OK (not a collision)

After checking all hostnames:
□ Fail if ANY unapproved collision found
□ Succeed if all collisions are approved OR no collisions exist
```

### 3. Error Messages
```
Provide THREE error scenarios:

□ Collision without flag:
  "Generated route {hostname} collides with central route
   without intendedReplacement flag. Add flag or rename route."

□ Multiple intendedReplacement hosts:
  "Manifest contains {N} intendedReplacement entries.
   Only one migration per task allowed."

□ intendedReplacement hostname mismatch:
  "intendedReplacement hostname does not match any generated
   route. Check manifest routes and intended replacement."
```

### 4. Generated Output
```
□ Stripped of intendedReplacement field (NOT rendered)
□ Contains only actual routes, services, middleware
□ Valid Traefik dynamic config YAML
□ Deterministic (same input → same output)
```

### 5. Dry-Run Output Format
```
Success case:
  Generated routes: 1 (or N for multiple)
  Duplicates checked: ✓
  Intended replacement: authentik.lab... (if present)
  Status: PASS - Ready for deployment

Failure case:
  Status: FAIL - {error message}
  {helpful remediation steps}
```

---

## For Tasks 15-20 (Service Migrations: Authentik, Harbor, Grafana, Portainer, NetBox, Traefik)

**Task 03 requires each of you to follow this workflow:**

### Phase 1: Preparation
```
□ Create terraform/lxc/stacks/<service>/edge.yaml
□ Add intendedReplacement field with your service's hostname
□ Document the reason for migration
□ Verify pve-test targeting (never pve production!)
```

### Phase 2: Validation (Pre-Deployment)
```
□ Run edge reconciler dry-run
  Expected output: lists pending changes (migration phase)
  Expected: NO collision error messages

□ Run manifest validator
  Expected: manifest passes all validation checks

□ Run renderer dry-run
  Expected: SUCCESS (not a FAILURE)
```

### Phase 3: Deployment
```
□ Apply generated DNS records
□ Apply generated Traefik routes
□ Remove central route for this service (SAME deployment unit)
□ Reload Traefik

Note: "Same deployment unit" means all these happen together,
      not one now and one later.
```

### Phase 4: Post-Deployment Validation
```
□ DNS resolves to 10.57.2.10
□ HTTPS returns correct service response
□ Auth behavior matches requirements
□ Service-specific functional tests pass
```

### Phase 5: Cleanup & Confirmation
```
□ Remove intendedReplacement field from manifest
  (migration phase is complete)

□ Run edge reconciler dry-run again
  Expected: shows NO-OP (no pending changes)
  Expected: no duplicate host warnings

□ Commit manifest (with flag removed)
□ Document validation results in task completion notes
```

### Example manifest structure for Task 15 (Authentik):
```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
  namespace: stacks
spec:
  # Your route definitions here
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      auth:
        mode: none
      backend:
        url: http://authentik:9000

  # ONLY during migration - remove after deployment succeeds
  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Parallel Safe? NO
```
⚠️  Do NOT run multiple service migrations in parallel
⚠️  Do NOT combine multiple services in one task

Each task migrates exactly ONE service:
  Task 15 → Authentik only
  Task 16 → Harbor only
  Task 17 → Grafana only
  Task 18 → Portainer only
  Task 19 → NetBox only
  Task 20 → Traefik only

Reason: One-host-per-task constraint prevents collision errors
        and makes validation simpler.
```

---

## For Task 21 (Final Cutover Cleanup)

**Task 03 requires you to verify:**

### 1. All Migrations Complete
```
□ All six manifests exist
  □ terraform/lxc/stacks/authentik-stack/edge.yaml
  □ terraform/lxc/stacks/harbor-stack/edge.yaml
  □ terraform/lxc/stacks/grafana-stack/edge.yaml
  □ terraform/lxc/stacks/portainer-stack/edge.yaml
  □ terraform/lxc/stacks/netbox-stack/edge.yaml
  □ terraform/lxc/stacks/proxy-stack/edge.yaml

□ No intendedReplacement flags remain
  grep -r "intendedReplacement" terraform/lxc/stacks/
  Expected output: NONE (empty)
```

### 2. No Collisions Remain
```
□ Run renderer dry-run (all manifests)
  Expected: PASS
  Expected: NO collision warnings
  Expected: NO intendedReplacement flags found

□ Check central config
  Should contain ONLY:
    - Entrypoints
    - Certificate resolvers
    - Shared middleware definitions
    - Default certificate store

  Should NOT contain:
    - authentik route
    - harbor route
    - grafana route
    - portainer route
    - netbox route
    - traefik dashboard route
```

### 3. Reconciler Shows No-Op
```
□ Run edge reconciler dry-run
  Expected: COMPLETE NO-OP
  Expected: "no pending changes"
  Expected: "no duplicate hosts"

This proves the migration is complete and stable.
```

### 4. Functionality Validated
```
□ All six DNS records resolve to 10.57.2.10
□ All six routes accessible via HTTPS
□ All six auth behaviors correct
□ All six service functionalities working
□ Certificate handling working for all
```

### 5. Rollback Tested
```
□ Snapshot previous generated state
□ Test rollback procedure
□ Verify all routes still accessible after rollback
□ Document rollback procedure in runbook.md
```

---

## Integration Table: What Each Task Requires

| Task | Requires Task 03 to define | Must implement | Must validate |
| --- | --- | --- | --- |
| 07 Renderer | Duplicate detection algorithm | Collision detection | Dry-run errors |
| 15 Authentik | One-host workflow | Add intendedReplacement | Route accessible |
| 16 Harbor | Same workflow | Add intendedReplacement | Route accessible |
| 17 Grafana | Same workflow | Add intendedReplacement | Route accessible |
| 18 Portainer | Same workflow | Add intendedReplacement | Route accessible |
| 19 NetBox | Same workflow | Add intendedReplacement | Route accessible |
| 20 Traefik | Same workflow | Add intendedReplacement | Route accessible |
| 21 Cleanup | No-op validation | Verify all flags removed | All routes working |

---

## Stop Conditions: When to Stop and Escalate

### Task 07 Should Stop If:
- Generated route would shadow live central route without intendedReplacement flag
- More than one intendedReplacement hostname set in single manifest
- Rendered output contains intendedReplacement field (should be stripped)

### Tasks 15-20 Should Stop If:
- Migration requires more than one host replacement in one task
- Dry-run fails with collision error
- Central route not removed in same deployment unit as generated add
- Route not accessible after deployment
- Reconciler dry-run shows pending changes (not no-op)

### Task 21 Should Stop If:
- Any intendedReplacement flags remain (migration not complete)
- Any duplicate hosts between generated and central (collision exists)
- Central config contains per-service routes (migration incomplete)
- Any route, DNS, cert, or auth behavior regresses
- Reconciler second run is not complete no-op

---

## Debugging Guide

### "Dry-run shows collision error"
```
Check:
1. Does this hostname exist in central Traefik config?
   grep "hostname:" terraform/lxc/central-traefik-config.yml

2. Did you add intendedReplacement to manifest?
   cat terraform/lxc/stacks/<service>/edge.yaml | grep -A2 intendedReplacement

3. Does intendedReplacement hostname match the generated route?
   Must be EXACT match

Fix:
- Add intendedReplacement field if missing
- Verify exact hostname match
- Retry dry-run
```

### "Reconciler shows pending changes instead of no-op"
```
Check:
1. Was intendedReplacement flag removed?
   Should not exist in committed manifest

2. Is central route still present?
   grep "service-hostname:" terraform/lxc/central-traefik-config.yml

3. Are generated files present?
   ls -la /opt/proxy-stack/dynamic/stacks/

Fix:
- Remove intendedReplacement flag
- Remove central route if still there
- Verify generated file exists and is current
- Retry reconciler dry-run
```

### "Multiple services need migration"
```
This violates the one-host-per-task constraint.

Solution:
Split into separate tasks/branches. Each task does exactly ONE service.

Reason:
Multiple migrations = multiple intendedReplacement flags
                  = collision detection fails
                  = deployment blocked
```

---

## Quick Checklist for Success

### Before Implementing Task 07:
- [ ] Read and understand Decision 5 in decisions.md
- [ ] Read 03-CUTOVER-CONTRACT.md (full contract)
- [ ] Understand duplicate-host detection algorithm
- [ ] Plan error messages for three failure scenarios

### Before Starting Tasks 15-20:
- [ ] Read Task 15 (Authentik) to understand workflow
- [ ] Create edge.yaml with intendedReplacement field
- [ ] Run dry-run validation BEFORE deployment
- [ ] Remove flag AFTER deployment succeeds
- [ ] Confirm reconciler no-op AFTER cleanup

### Before Starting Task 21:
- [ ] Verify Tasks 15-20 all completed
- [ ] Verify NO intendedReplacement flags remain
- [ ] Run final renderer dry-run (all manifests)
- [ ] Verify central config has no per-service routes
- [ ] Confirm reconciler complete no-op
- [ ] Test rollback procedure

---

## References

- [Task 03: Cutover Semantics](03-cutover-semantics.md)
- [Decision 5 in decisions.md](../decisions.md#decision-5-traefik-runtime-split)
- [State Transitions Guide](03-CUTOVER-STATE-TRANSITIONS.md)
- [Full Contract Specification](03-CUTOVER-CONTRACT.md)
- [Task 07: Traefik Renderer](07-traefik-renderer.md)
- [Task 15: Migrate Authentik](15-migrate-authentik.md)
- [Task 21: Final Cutover Cleanup](21-final-cutover-cleanup.md)
