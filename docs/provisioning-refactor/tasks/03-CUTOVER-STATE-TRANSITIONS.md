# Cutover Semantics: State Transitions & Validation Artifacts

## State Machine: Route Cutover Progression

### Initial State (Before Any Migration)

**What exists:**
- Legacy central Traefik config has all six per-service routes
- Stack manifests do NOT exist yet (or exist without `intendedReplacement`)

**Renderer behavior:**
```
Dry-run PASSES:
  Generated routes: EMPTY (no manifests)
  Central routes: all six services
  Collisions: NONE

Output: "No generated routes found. Central config is live."
```

**Reconciler behavior:**
```
Dry-run: NO-OP
  Reason: No generated manifests to deploy
  Pending changes: ZERO
  Duplicates: NONE
```

---

### Migration State N (During Task 15+N)

**What exists:**
- Legacy central routes: all six (still)
- Generated routes: (N-1) services from completed migrations
- Current migration: manifest with `intendedReplacement` set

**Example: Task 15 (Authentik Migration)**

**Renderer behavior (dry-run):**
```
Checking: authentik.lab.gibbsgreatly.xyz
  Exists in generated manifest: YES
  Exists in central config: YES
  intendedReplacement flag: YES (matches this hostname)

Collision check:
  Collision detected: YES
  Flag matches hostname: YES ✓
  → ALLOW (this is the intended migration)

Generated output: /tmp/dry-run-task-15/authentik-stack.yml
Central config check: OK
Manifest validation: PASS

Result: DRY-RUN SUCCEEDS
```

**Reconciler behavior (dry-run, before deployment):**
```
Manifests with intendedReplacement:
  - authentik-stack/edge.yaml (authentik.lab.gibbsgreatly.xyz)

Checking manifest validity:
  - authentik-stack manifests: VALID

Collision check:
  - authentik.lab.gibbsgreatly.xyz in both central & generated
  - Flag allows this collision: YES
  - → COLLISION ALLOWED (migration in progress)

Pending changes:
  - Generated files to write: 1 (authentik-stack.yml)
  - Central routes to remove: 1 (authentik entry)
  - DNS records to update: 1
  - Certificate store updates: 1

Result: DRY-RUN LISTS PENDING CHANGES
```

**After deployment (live apply):**
```
Applied changes:
  - Removed authentik.lab... from central Traefik config
  - Added authentik-stack.yml to generated directory
  - Updated DNS record for authentik.lab... → 10.57.2.10
  - Certificate resolver updated for *.lab...

Central config now contains:
  - Shared runtime config: YES
  - Authentik per-service route: NO
  - Five other per-service routes: YES
```

**Reconciler behavior (dry-run, after deployment):**
```
Manifests with intendedReplacement:
  - authentik-stack/edge.yaml (still marked, not yet removed)

Collision check:
  - authentik.lab.gibbsgreatly.xyz in generated only: YES
  - Central no longer has this route: YES
  - intendedReplacement flag still present: YES

Pending changes:
  - Manifest cleanup: remove intendedReplacement flag

Result: DRY-RUN LISTS ONE PENDING CHANGE
  (removal of intendedReplacement flag)
```

**After cleanup (remove intendedReplacement flag):**
```
Result: DRY-RUN SHOWS NO-OP
  Reason: intendedReplacement flag removed, all routes generated
  Manifests with flags: ZERO
  Pending changes: ZERO
  Duplicates: NONE
```

---

### Intermediate State (After Task 15, During Task 16)

**What exists:**
- Legacy central routes: five services (Authentik removed)
- Generated routes: one (Authentik) from completed Task 15
- Current migration: Harbor with `intendedReplacement` set

**Renderer behavior (dry-run for Task 16):**
```
Checking: harbor.lab.gibbsgreatly.xyz
  Exists in central config: YES (still there)
  Exists in generated manifests: YES (new from Task 16)
  intendedReplacement flag: YES (marked in Task 16 manifest)

Collision check:
  harbor.lab collision: YES
  Flag matches: YES ✓
  → ALLOW (this is the intended migration)

Check authentik.lab (already migrated):
  Exists in generated only: YES
  intendedReplacement flag: NO (already removed)
  Collision: NONE ✓

Result: DRY-RUN SUCCEEDS for Task 16
```

---

### Final State (After Task 21)

**What exists:**
- Legacy central routes: NONE (runtime/shared config only)
- Generated routes: all six services
- All `intendedReplacement` flags: REMOVED

**Renderer behavior (final dry-run):**
```
Generated manifests: 6 (all with no intendedReplacement)
Central config: only shared runtime settings

Collision check:
  - authentik.lab: generated only ✓
  - harbor.lab: generated only ✓
  - grafana.lab: generated only ✓
  - portainer.lab: generated only ✓
  - netbox.lab: generated only ✓
  - traefik.lab: generated only ✓

Duplicates found: ZERO
Manifests with intendedReplacement: ZERO

Result: DRY-RUN SUCCEEDS
  All routes are generated and clean
  No collisions, no flags, no migrations in progress
```

**Reconciler behavior (final dry-run):**
```
Manifests with intendedReplacement: ZERO

Generated routes validation: PASS (6 routes)
Central config validation: PASS (runtime only)

Collision check: NONE

Pending changes: ZERO
  Reason: all generated routes match live state

Result: COMPLETE NO-OP
  All service routes are now stack-owned
  Central config contains only shared runtime config
  Migration completed successfully
  All flags removed
```

---

## Validation Commands by Phase

### After Each Migration Task (15-20)

```bash
# Step 1: Dry-run validation (before deployment)
terraform apply -dry-run  # Should SUCCEED with intendedReplacement flag

# Step 2: Deployment
terraform apply  # Removes central route, adds generated

# Step 3: Post-deployment validation
./edge-reconciler --dry-run  # Should show ONE pending change (flag removal)

# Step 4: Cleanup
# Remove intendedReplacement flag from manifest

# Step 5: Final validation
./edge-reconciler --dry-run  # Should show NO-OP
```

### Before Task 21 Final Validation

```bash
# Verify all six manifests exist
ls -la terraform/lxc/stacks/*/edge.yaml

# Verify no intendedReplacement flags remain
grep -r "intendedReplacement" terraform/lxc/stacks/

# Should find: NOTHING (zero matches)
```

### During Task 21

```bash
# Final dry-run
terraform plan -dry-run

# Should show:
#   Generated routes: 6 (all matched to live state)
#   Pending changes: ZERO
#   Collisions: ZERO
#   intendedReplacement flags: ZERO

# Verify central config has no per-service routes
grep -E "authentik|harbor|grafana|portainer|netbox|traefik" \
  terraform/lxc/central-traefik-config.yml

# Should find: NOTHING (only runtime/shared config)
```

---

## Integration Points Between Tasks

### Task 07 → Tasks 15-20

**Task 07 must implement:**
- Duplicate-host detection algorithm
- `intendedReplacement` flag parsing
- Fail condition: collision without flag
- Fail condition: multiple flags in one manifest

**Tasks 15-20 use:**
- Task 07 renderer for validation
- `intendedReplacement` flag to signal allowed collision
- Atomic deployment pattern (remove + add in same unit)
- Post-deployment flag cleanup

### Tasks 15-20 → Task 21

**Each task (15-20) must:**
- Remove `intendedReplacement` flag after successful deployment
- Leave manifest in place for the next reconciler run
- Document that post-cleanup dry-run shows no-op

**Task 21 verifies:**
- All flags are removed
- No migrations are in-progress
- All routes are generated and stable
- Final dry-run is complete no-op

---

## Stop Conditions Mapped to Output

| Stop Condition | Renderer Output | Reconciler Output | Action |
| --- | --- | --- | --- |
| Accidental collision detected (no flag) | DRY-RUN FAILS | N/A | Fix manifest or add flag |
| Multiple intendedReplacement flags | DRY-RUN FAILS | N/A | Keep only one flag |
| Flag removal missed after deploy | DRY-RUN SUCCEEDS | Shows 1 pending change | Remove flag manually |
| Central per-service route not removed | DRY-RUN SUCCEEDS | Shows pending changes | Check deployment log |
| Duplicate hosts remain after cleanup | DRY-RUN SUCCEEDS | Lists collisions | Investigate live config |
| Reconciler not no-op after migration | DRY-RUN SUCCEEDS | Shows pending changes | Validation failed |
