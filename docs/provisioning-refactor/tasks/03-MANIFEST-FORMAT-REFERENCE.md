# Task 03: Manifest Format Reference & Examples

Quick reference for the exact YAML format needed during migration.

---

## Manifest YAML Structure

### Complete Template (During Migration)

```yaml
# terraform/lxc/stacks/authentik-stack/edge.yaml

apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
  namespace: stacks
  labels:
    stack: authentik
    phase: migration

spec:
  # ===== ROUTES (always required) =====
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      path: /
      auth:
        mode: none  # No Traefik middleware for Authentik itself
      backend:
        url: http://authentik:9000  # Direct to service port
      middleware: []

    # Additional routes for this stack if any
    - hostname: authentik-admin.lab.gibbsgreatly.xyz  # Example: admin panel
      path: /admin/
      auth:
        mode: none
      backend:
        url: http://authentik:9000/admin/

  # ===== INTENDED REPLACEMENT (only during migration) =====
  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "2026-04-20T14:30:00Z"
      notes: "First service migration - establishes pattern"

  # ===== OTHER OPTIONAL FIELDS =====
  certificates:
    wildcard: "*.lab.gibbsgreatly.xyz"

  dns:
    managed: true
    zone: lab.gibbsgreatly.xyz
```

---

## Manifest Evolution by Phase

### BEFORE MIGRATION (No intendedReplacement)

```yaml
# Does not exist yet
# Service routes live only in central Traefik config
```

### DURING MIGRATION TASK (With intendedReplacement)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      auth:
        mode: none
      backend:
        url: http://authentik:9000

  intendedReplacement:  # ← FLAG ADDED (signals: this is a migration)
    - hostname: authentik.lab.gibbsgreatly.xyz
```

### AFTER MIGRATION (intendedReplacement removed)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      auth:
        mode: none
      backend:
        url: http://authentik:9000

  # intendedReplacement removed entirely
```

---

## Service-Specific Examples

### Task 15: Authentik (none mode)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
  namespace: stacks
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      auth:
        mode: none  # No Traefik middleware
      backend:
        url: http://authentik:9000

  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Task 16: Harbor (native mode)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: harbor-stack
  namespace: stacks
spec:
  routes:
    - hostname: harbor.lab.gibbsgreatly.xyz
      auth:
        mode: native  # Harbor handles auth natively
      backend:
        url: https://harbor:8443
      # No Traefik forward-auth middleware

  intendedReplacement:
    - hostname: harbor.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Task 17: Grafana (forwardAuth mode)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: grafana-stack
  namespace: stacks
spec:
  routes:
    - hostname: grafana.lab.gibbsgreatly.xyz
      auth:
        mode: forwardAuth  # Traefik forward-auth to Authentik
      backend:
        url: http://grafana:3000
      # Traefik will add the shared authentik middleware

  intendedReplacement:
    - hostname: grafana.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Task 18: Portainer (forwardAuth mode)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: portainer-stack
  namespace: stacks
spec:
  routes:
    - hostname: portainer.lab.gibbsgreatly.xyz
      auth:
        mode: forwardAuth  # Traefik forward-auth to Authentik
      backend:
        url: http://portainer:9000

  intendedReplacement:
    - hostname: portainer.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Task 19: NetBox (forwardAuth mode)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: netbox-stack
  namespace: stacks
spec:
  routes:
    - hostname: netbox.lab.gibbsgreatly.xyz
      auth:
        mode: forwardAuth  # Traefik forward-auth to Authentik
      backend:
        url: http://netbox:8001

  intendedReplacement:
    - hostname: netbox.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### Task 20: Traefik Dashboard (api@internal)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: proxy-stack
  namespace: stacks
spec:
  routes:
    - hostname: traefik.lab.gibbsgreatly.xyz
      path: /dashboard/
      auth:
        mode: forwardAuth  # Traefik forward-auth to Authentik
      backend:
        traefikService: api@internal  # Special: use Traefik's internal API

  intendedReplacement:
    - hostname: traefik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

---

## Auth Mode Field Reference

Each route specifies an auth mode:

| Mode | Meaning | Example | Middleware |
| --- | --- | --- | --- |
| `none` | No auth layer | Authentik (self-contained) | None added |
| `forwardAuth` | Traefik forward-auth | Grafana, Portainer | Traefik adds shared middleware |
| `native` | Service handles auth | Harbor (registry API) | None added |
| `oidc` | OIDC against Authentik | Service with native OIDC | None added |

---

## Backend Field Reference

Each route specifies a backend:

### Type 1: HTTP/HTTPS URL (most common)
```yaml
routes:
  - hostname: authentik.lab.gibbsgreatly.xyz
    backend:
      url: http://authentik:9000  # Direct service
```

### Type 2: Traefik Service Reference (special)
```yaml
routes:
  - hostname: traefik.lab.gibbsgreatly.xyz
    backend:
      traefikService: api@internal  # Traefik's internal API
```

---

## File Locations

```
terraform/lxc/stacks/
├── authentik-stack/
│   └── edge.yaml           # Task 15
├── harbor-stack/
│   └── edge.yaml           # Task 16
├── grafana-stack/
│   └── edge.yaml           # Task 17
├── portainer-stack/
│   └── edge.yaml           # Task 18
├── netbox-stack/
│   └── edge.yaml           # Task 19
└── proxy-stack/
    └── edge.yaml           # Task 20 (Traefik dashboard)
```

---

## intendedReplacement Field Semantics

### What It Means

```yaml
intendedReplacement:
  - hostname: authentik.lab.gibbsgreatly.xyz
    reason: "Migrating from central Traefik config"
    startedAt: "2026-04-20T14:30:00Z"
```

**Translation:**
"This manifest replaces an existing route from the central Traefik configuration. The hostname `authentik.lab.gibbsgreatly.xyz` exists in both the generated manifest AND the central config. This is expected during migration and is approved."

### What It Does

1. **Allows collision during dry-run** (Task 07 renderer)
   - Without flag: dry-run FAILS
   - With flag: dry-run SUCCEEDS

2. **Signals migration in-progress** (Tasks 15-20)
   - To the reconciler: "don't consider this a duplicate error"
   - To future readers: "this migration is not yet complete"

3. **Must be removed after deployment** (Tasks 15-20)
   - After route is stable and working
   - Before committing manifest
   - Signals: "migration complete, route now fully generated"

### When to Add

Add `intendedReplacement` when:
- [ ] Creating the manifest for the first time
- [ ] For a hostname that EXISTS in central Traefik config
- [ ] As part of a one-service migration task
- [ ] Before running the first dry-run

### When to Remove

Remove `intendedReplacement` when:
- [ ] Deployment succeeds
- [ ] Service is accessible via the new route
- [ ] Post-deployment validation passes
- [ ] Reconciler dry-run shows no-op
- [ ] Before committing the manifest to git

---

## Before & After: Complete Example

### BEFORE: Central Traefik Config Only

File: `terraform/lxc/central-traefik-config.yml`
```yaml
dynamic:
  routers:
    # ... other routers ...

    authentik-route:
      rule: "Host(`authentik.lab.gibbsgreatly.xyz`)"
      service: authentik-service
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt

    # ... other per-service routes ...

  services:
    authentik-service:
      loadBalancer:
        servers:
          - url: http://authentik:9000
```

No `terraform/lxc/stacks/authentik-stack/edge.yaml` file exists.

### DURING MIGRATION: Both Exist (With Flag)

File: `terraform/lxc/central-traefik-config.yml` (unchanged)
```yaml
  # Central config still has authentik route
```

File: `terraform/lxc/stacks/authentik-stack/edge.yaml` (created)
```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      auth:
        mode: none
      backend:
        url: http://authentik:9000

  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
```

Generated file: `/opt/proxy-stack/dynamic/stacks/authentik-stack.yml`
```yaml
routers:
  authentik-route:
    rule: "Host(`authentik.lab.gibbsgreatly.xyz`)"
    service: authentik-service

services:
  authentik-service:
    loadBalancer:
      servers:
        - url: http://authentik:9000
```

### AFTER MIGRATION: Generated Only (Flag Removed)

File: `terraform/lxc/central-traefik-config.yml` (UPDATED)
```yaml
dynamic:
  routers:
    # ... other routers ...
    # authentik-route REMOVED
    # ... other routes remain ...
```

File: `terraform/lxc/stacks/authentik-stack/edge.yaml` (UPDATED)
```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: authentik-stack
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
      auth:
        mode: none
      backend:
        url: http://authentik:9000

  # intendedReplacement field REMOVED
```

Generated file: `/opt/proxy-stack/dynamic/stacks/authentik-stack.yml` (unchanged)
```yaml
routers:
  authentik-route:
    rule: "Host(`authentik.lab.gibbsgreatly.xyz`)"
    service: authentik-service

services:
  authentik-service:
    loadBalancer:
      servers:
        - url: http://authentik:9000
```

---

## Validation Checklist for Each Manifest

Before deploying, verify:

- [ ] **File location correct**: `terraform/lxc/stacks/<stack>/edge.yaml`
- [ ] **API version correct**: `homelab.gibbsgreatly.xyz/v1alpha1`
- [ ] **Kind correct**: `EdgeManifest`
- [ ] **Metadata present**: name, namespace, labels
- [ ] **Routes defined**: at least one route
- [ ] **Hostname correct**: `*.lab.gibbsgreatly.xyz` format
- [ ] **Auth mode set**: one of `none`, `forwardAuth`, `native`, `oidc`
- [ ] **Backend defined**: either `url` or `traefikService`
- [ ] **intendedReplacement present**: only during migration
- [ ] **Hostname matches**: intendedReplacement matches a generated route
- [ ] **Single hostname**: only one intendedReplacement entry

Quick validation command:
```bash
# Check manifest syntax
yq -e '.spec.routes[].hostname' terraform/lxc/stacks/authentik-stack/edge.yaml

# Check intendedReplacement present
grep "intendedReplacement:" terraform/lxc/stacks/authentik-stack/edge.yaml

# Check exactly one hostname in intendedReplacement
grep -A2 "intendedReplacement:" terraform/lxc/stacks/authentik-stack/edge.yaml | \
  grep "hostname:" | wc -l
# Should output: 1
```

---

## Common Mistakes & How to Fix

### Mistake 1: intendedReplacement doesn't match any route

```yaml
# ✗ WRONG
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
  intendedReplacement:
    - hostname: admin.lab.gibbsgreatly.xyz  # Different!

# ✓ CORRECT
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz  # Matches route
```

### Mistake 2: Multiple intendedReplacement entries

```yaml
# ✗ WRONG
intendedReplacement:
  - hostname: authentik.lab.gibbsgreatly.xyz
  - hostname: admin.lab.gibbsgreatly.xyz

# ✓ CORRECT (for single migration)
intendedReplacement:
  - hostname: authentik.lab.gibbsgreatly.xyz

# If you need both:
# Split into separate migration tasks (Task 15 and Task 15b)
```

### Mistake 3: Leaving intendedReplacement after migration

```yaml
# ✗ WRONG (after deployment)
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
  intendedReplacement:  # ← Still here after migration!
    - hostname: authentik.lab.gibbsgreatly.xyz

# ✓ CORRECT (after deployment)
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
  # intendedReplacement removed
```

### Mistake 4: Wrong hostname format

```yaml
# ✗ WRONG (legacy format)
hostname: authentik.gibbsgreatly.xyz  # Missing 'lab' subdomain

# ✓ CORRECT (Decision 1 format)
hostname: authentik.lab.gibbsgreatly.xyz  # Includes 'lab'
```

### Mistake 5: Auth mode not set

```yaml
# ✗ WRONG
routes:
  - hostname: authentik.lab.gibbsgreatly.xyz
    backend:
      url: http://authentik:9000

# ✓ CORRECT
routes:
  - hostname: authentik.lab.gibbsgreatly.xyz
    auth:
      mode: none
    backend:
      url: http://authentik:9000
```

---

## Quick Copy-Paste Templates

### For forwardAuth (most services)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: SERVICE-stack
  namespace: stacks
spec:
  routes:
    - hostname: SERVICE.lab.gibbsgreatly.xyz
      auth:
        mode: forwardAuth
      backend:
        url: http://SERVICE:PORT
  intendedReplacement:
    - hostname: SERVICE.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### For native auth (Harbor)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: SERVICE-stack
  namespace: stacks
spec:
  routes:
    - hostname: SERVICE.lab.gibbsgreatly.xyz
      auth:
        mode: native
      backend:
        url: https://SERVICE:SECURE_PORT
  intendedReplacement:
    - hostname: SERVICE.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### For none mode (Authentik)

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: SERVICE-stack
  namespace: stacks
spec:
  routes:
    - hostname: SERVICE.lab.gibbsgreatly.xyz
      auth:
        mode: none
      backend:
        url: http://SERVICE:PORT
  intendedReplacement:
    - hostname: SERVICE.lab.gibbsgreatly.xyz
      reason: "Migrating from central Traefik config"
      startedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

---

## After Migration: Manifest Cleanup

After deployment succeeds and route is stable:

```bash
# For Authentik (Task 15):
sed -i '/intendedReplacement:/,+3d' \
  terraform/lxc/stacks/authentik-stack/edge.yaml

# Or manually edit and remove:
# Lines containing:
#   intendedReplacement:
#   - hostname: ...
#   reason: ...
#   startedAt: ...

# Verify removed:
grep -i "intendedReplacement" \
  terraform/lxc/stacks/authentik-stack/edge.yaml
# Should output nothing

# Commit manifest
git add terraform/lxc/stacks/authentik-stack/edge.yaml
git commit -m "Finalize Authentik migration: remove intendedReplacement flag"
```

---

## References

- [Task 03 Core Definition](03-cutover-semantics.md)
- [Complete Contract](03-CUTOVER-CONTRACT.md#contract-1-manifest-format---intendedReplacement-field)
- [Manifest Schema](04-edge-manifest-contract.md)
- [Manifest Validator](05-manifest-validator.md)
