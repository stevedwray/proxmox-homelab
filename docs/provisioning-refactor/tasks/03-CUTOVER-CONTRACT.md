# Cutover Semantics: Implementation Contract

## Decision 5 → Manifest Contract Mapping

### Decision 5 Text (from decisions.md)

> One-host replacement is explicit: a migration task may allow exactly the host it
> is replacing while it validates generated output, but live publish must remove
> the central route and add the generated route as the same deployment unit.

### Implementation Requirements

This decision creates THREE implementation contracts:

---

## Contract 1: Manifest Format - `intendedReplacement` Field

### Location
```
terraform/lxc/stacks/<stack>/edge.yaml
```

### YAML Schema
```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
  namespace: stacks
spec:
  # ... other fields ...

  # ONLY DURING MIGRATION - REMOVED AFTER CUTOVER
  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "2026-04-20T14:30:00Z"
```

### Constraints
1. **Field is optional**: omitted in normal state, present only during migration
2. **Array format**: allows exactly one hostname during migration
3. **Max one entry**: validator enforces `len(intendedReplacement) <= 1`
4. **Must match generated route**: `intendedReplacement[0].hostname` must match exactly one generated route hostname
5. **Must match central route**: `intendedReplacement[0].hostname` must exist in central Traefik config at time of dry-run
6. **Removed after deployment**: Once deployment succeeds and route is stable, this field is removed

### Valid Examples

**During Migration (Task 15):**
```yaml
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      backend: ...

  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "2026-04-20T14:30:00Z"
```

**After Migration (cleaned up):**
```yaml
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      backend: ...

  # intendedReplacement field removed entirely
```

### Invalid Examples

**Multiple hosts (REJECTED):**
```yaml
intendedReplacement:
  - hostname: authentik.lab.gibbsgreatly.xyz
  - hostname: harbor.lab.gibbsgreatly.xyz
# ERROR: Only one hostname allowed
```

**Mismatch with generated routes (REJECTED):**
```yaml
intendedReplacement:
  - hostname: authentik.lab.gibbsgreatly.xyz

routes:
  - hostname: harbor.lab.gibbsgreatly.xyz  # Different!
# ERROR: intendedReplacement must match one generated route
```

**Without matching central route (REJECTED at dry-run):**
```yaml
intendedReplacement:
  - hostname: unknown.lab.gibbsgreatly.xyz

# ERROR: This hostname not found in central Traefik config
```

---

## Contract 2: Renderer Implementation - Duplicate Detection & Validation

### Pre-Render Phase: Manifest Validation
```
Input: manifests/<stack>/edge.yaml

1. Parse manifest
2. Extract intendedReplacement field (if present)
3. If present:
   a. Validate: len(intendedReplacement) == 1
      → FAIL if > 1
   b. Extract hostname: intended_hostname
   c. Validate: intended_hostname matches exactly one route in manifest
      → FAIL if 0 or > 1 match
4. Proceed to duplicate-host check
```

### Duplicate-Host Detection Phase

```
Input:
  - Generated manifests (with optional intendedReplacement)
  - Central Traefik config routes

Algorithm:

1. Load central config, extract all route hostnames
   central_hosts = { "authentik.lab...", "harbor.lab...", ... }

2. Load generated manifests, extract all route hostnames
   generated_hosts = { "authentik.lab...", "grafana.lab...", ... }

3. For each manifest with intendedReplacement:
   intended_host = manifest.intendedReplacement[0].hostname

4. Find collisions:
   collisions = generated_hosts ∩ central_hosts

5. For each collision:
   hostname = collision

   if hostname == intended_host:
      # This collision is ALLOWED by the migration flag
      → ALLOW
   else:
      # This collision is UNEXPECTED
      → FAIL with error:
         "Generated route collides with central route
          without intendedReplacement flag:

          Hostname: {hostname}

          If this is intentional, add to manifest:
          intendedReplacement:
            - hostname: {hostname}

          Otherwise, rename the route or remove central
          entry first."

6. After all collisions checked:
   if any_collision_without_flag:
      → DRY-RUN FAILS
   else:
      → DRY-RUN SUCCEEDS
```

### Output Phase
```
Generated file: /opt/proxy-stack/dynamic/stacks/<stack>.yml

Before writing:
  - Strip intendedReplacement field (not rendered)
  - Generate only the actual routes

File should NOT contain:
  - intendedReplacement field
  - Migration metadata
  - Debugging hints
```

### Renderer Error Messages

**Collision without flag:**
```
ERROR: Renderer dry-run failed

Generated route collides with central Traefik config
without explicit intendedReplacement flag.

Collision Details:
  Hostname: authentik.lab.gibbsgreatly.xyz
  Found in: central Traefik config
  Found in: generated manifests/authentik-stack/edge.yaml
  Flag set: NO

Resolution:
  Option 1 (if this is a migration):
    Add to manifests/authentik-stack/edge.yaml:

    spec:
      intendedReplacement:
        - hostname: authentik.lab.gibbsgreatly.xyz
          reason: "Migrating from central Traefik config"
          startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  Option 2 (if this is not a migration):
    Rename the generated route or remove the central route first.

  Option 3 (if this is expected and safe):
    This decision requires human review. Do not proceed.
```

**Multiple intendedReplacement hosts:**
```
ERROR: Manifest validation failed

manifests/authentik-stack/edge.yaml contains multiple
intendedReplacement entries. Only one hostname may be
replaced per migration task.

Found:
  - authentik.lab.gibbsgreatly.xyz
  - admin.lab.gibbsgreatly.xyz

Resolution:
  Split into separate migration tasks or remove hosts
  that are not part of this migration.
```

---

## Contract 3: Deployment Unit Atomicity

### What "Same Deployment Unit" Means

A single `terraform apply` (or equivalent Ansible run) must:

1. **Pre-apply validation**
   ```
   Renderer dry-run succeeds (no collision error)
   Manifest validation passes (intendedReplacement valid)
   ```

2. **Deployment executes as atomic unit**
   ```
   UNIT START:

   a. Remove central route definition
      (from terraform/lxc/central-traefik-config.yml or equivalent)

   b. Add generated route file
      (to /opt/proxy-stack/dynamic/stacks/<stack>.yml)

   c. Trigger Traefik reload (if live)

   d. Update DNS record (if needed)

   UNIT END:

   Result: Route is either BOTH present or BOTH absent
           Never a state where one is present and one is not
   ```

3. **Post-apply validation**
   ```
   Live service is accessible via new route
   No 404 or timeout from old route (because it's removed)
   Reconciler dry-run shows no pending changes
   ```

### Implementation in Ansible

**Example from `deploy-proxy-stack.yml`:**

```yaml
- name: "Atomic route migration: {{ service_hostname }}"
  block:
    - name: "Pre-deploy validation"
      command: >
        terraform -chdir=terraform/lxc
        validate-edge-manifest
        --manifest {{ service }}/edge.yaml
      register: manifest_validation

    - name: "Fail if validation error"
      fail:
        msg: "{{ manifest_validation.stderr }}"
      when: manifest_validation.rc != 0

    - name: "Remove central route (if exists)"
      block:
        - name: "Find route in central config"
          xml:
            path: terraform/lxc/central-traefik-config.yml
            xpath: /traefik/services/[hostname='{{ service_hostname }}']
            state: absent
          register: central_route_removed

    - name: "Add generated route"
      copy:
        src: "/tmp/render-dry-run/{{ service }}.yml"
        dest: "/opt/proxy-stack/dynamic/stacks/{{ service }}.yml"
        mode: '0644'
      register: generated_route_added

    - name: "Reload Traefik"
      command: systemctl reload traefik

    - name: "Post-deploy validation"
      uri:
        url: "https://{{ service_hostname }}"
        method: GET
        validate_certs: no
        status_code: [200, 302, 401]  # Accept auth redirects
      retries: 5
      delay: 2

  rescue:
    - name: "Rollback on failure"
      block:
        - name: "Restore central route"
          # ... restore from backup
        - name: "Remove generated route"
          file:
            path: "/opt/proxy-stack/dynamic/stacks/{{ service }}.yml"
            state: absent
        - name: "Reload Traefik"
          command: systemctl reload traefik
        - name: "Fail deployment"
          fail:
            msg: "Atomic migration failed and was rolled back"
```

---

## Contract 4: Reconciler Behavior During Cutover

### Input: Manifest with `intendedReplacement` flag

```
Dry-run mode:

Step 1: Check if intendedReplacement is set
        → YES, means migration is in-progress

Step 2: Collision check
        hostname in both central and generated
        intendedReplacement matches: YES
        → COLLISION ALLOWED (expected during migration)

Step 3: Report pending changes
        - Remove central route: ✓
        - Add generated route: ✓
        - Update DNS: ✓
        (if not already deployed)

Step 4: If deployed, flag next step
        "Migration pending cleanup:
         Remove intendedReplacement field from manifest
         after confirming route is stable"

Output:
  Pending changes: 1+ items
  Reason: Migration in-progress
```

### Input: Manifest without `intendedReplacement` flag (after cleanup)

```
Dry-run mode:

Step 1: Check if intendedReplacement is set
        → NO, means migration is complete

Step 2: Collision check
        hostname in generated only (central removed)
        → NO COLLISION (correct state)

Step 3: Report no pending changes
        (assuming deployment already done)

Output:
  Pending changes: ZERO
  Reason: Route fully migrated and stable
  Status: NO-OP ✓
```

---

## Validation Checklist for Task 03

- [ ] **Manifest schema**: `intendedReplacement` field documented in apiVersion spec
- [ ] **Renderer contract**: Duplicate-detection algorithm documented
- [ ] **Renderer validation**: Three error cases defined (collision, multiple hosts, mismatch)
- [ ] **Atomicity**: Deployment unit defined (remove central + add generated)
- [ ] **Error messages**: All four error scenarios have clear, actionable messages
- [ ] **Reconciler behavior**: Both during-migration and post-migration states documented
- [ ] **Integration points**: Task 07, Tasks 15-20, Task 21 all reference this contract

---

## Testing the Contract (Before Task 07 Implementation)

### Unit Test Cases for Duplicate Detection

```python
def test_duplicate_detected_without_flag():
    """Should FAIL dry-run if collision has no intendedReplacement"""
    central = {"authentik.lab...": True}
    generated = {"authentik.lab...": True}
    intended = None

    assert renderer_dry_run(central, generated, intended) == "FAIL"

def test_duplicate_allowed_with_matching_flag():
    """Should PASS dry-run if collision matches intendedReplacement"""
    central = {"authentik.lab...": True}
    generated = {"authentik.lab...": True}
    intended = "authentik.lab..."

    assert renderer_dry_run(central, generated, intended) == "PASS"

def test_multiple_intendedReplacement_rejected():
    """Should FAIL if manifest has multiple intendedReplacement entries"""
    manifest = {
        "intendedReplacement": [
            "authentik.lab...",
            "harbor.lab..."
        ]
    }

    assert manifest_validator(manifest) == "FAIL"
    assert error_message.contains("Only one hostname")

def test_intendedReplacement_mismatch_rejected():
    """Should FAIL if intendedReplacement doesn't match generated route"""
    manifest = {
        "routes": [{"hostname": "authentik.lab..."}],
        "intendedReplacement": ["harbor.lab..."]  # Different!
    }

    assert manifest_validator(manifest) == "FAIL"
    assert error_message.contains("must match one generated route")

def test_no_collision_when_all_migrated():
    """Should show NO-OP after all services migrated (all flags removed)"""
    central = {}  # Empty - all routes migrated
    generated = {
        "authentik.lab...": True,
        "harbor.lab...": True,
        "grafana.lab...": True,
        "portainer.lab...": True,
        "netbox.lab...": True,
        "traefik.lab...": True
    }
    intended = None  # All flags removed

    assert renderer_dry_run(central, generated, intended) == "PASS"
    assert reconciler_pending_changes == 0
```

---

## References Back to Decisions

| Decision | Contract Impact | Implementation Task |
| --- | --- | --- |
| Decision 5 | Entire contract | Task 03 (this task) |
| Decision 4 | Manifest API version field | Task 04 |
| Decision 6 | Auth modes in manifest | Task 04 |
| Decision 3 | Stack manifest path | Tasks 15-20 |
| Decision 2 | Generated DNS records | Task 08 |
| Decision 1 | Hostname format *.lab... | Tasks 15-20 |
