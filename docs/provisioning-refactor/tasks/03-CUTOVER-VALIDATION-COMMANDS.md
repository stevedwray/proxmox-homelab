# Task 03 Cutover Semantics: Validation Commands Reference

This document provides the exact commands each task should run to validate the one-host replacement workflow.

---

## Pre-Migration Setup (All Tasks)

### Verify pve-test targeting (safety check)
```bash
# BEFORE ANY DEPLOYMENT - verify you're targeting test, not production
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

# Must output: pve-test
# If output is anything else, STOP - you're targeting wrong host
```

### Verify environment is clean
```bash
# No uncommitted terraform changes
terraform -chdir=terraform/lxc plan | grep "No changes"

# Expected output contains "No changes"
# If not, clean up or commit first
```

---

## Task 07 (Traefik Renderer) Validation

### Unit test: Duplicate detection without flag (should FAIL)
```bash
./tests/renderer-tests.py \
  test_duplicate_detected_without_flag

# Expected: PASS (test passes, proving renderer fails as expected)
```

### Unit test: Duplicate detection with matching flag (should PASS)
```bash
./tests/renderer-tests.py \
  test_duplicate_allowed_with_matching_flag

# Expected: PASS (test passes, proving renderer succeeds as expected)
```

### Unit test: Multiple intendedReplacement (should FAIL)
```bash
./tests/renderer-tests.py \
  test_multiple_intendedReplacement_rejected

# Expected: PASS (test passes, proving validator rejects multiple)
```

### Unit test: intendedReplacement mismatch (should FAIL)
```bash
./tests/renderer-tests.py \
  test_intendedReplacement_mismatch_rejected

# Expected: PASS (test passes, proving validator catches mismatch)
```

### Integration test: Dry-run finds accidental collision
```bash
# Create test manifest with collision but no intendedReplacement
cat > /tmp/test-collision.yaml <<EOF
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: test-stack
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz  # This exists in central!
EOF

# Run renderer on test manifest
terraform -chdir=terraform/lxc \
  render-edge-traefik \
  --manifest /tmp/test-collision.yaml \
  --dry-run

# Expected output should contain error:
# "Generated route collides with central route
#  without intendedReplacement flag"
# Exit code: non-zero (FAIL)
```

### Integration test: Dry-run accepts collision with flag
```bash
# Same manifest but WITH intendedReplacement
cat > /tmp/test-collision-approved.yaml <<EOF
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: test-stack
spec:
  routes:
    - hostname: authentik.lab.gibbsgreatly.xyz
  intendedReplacement:
    - hostname: authentik.lab.gibbsgreatly.xyz
      reason: "Test migration"
EOF

# Run renderer on test manifest
terraform -chdir=terraform/lxc \
  render-edge-traefik \
  --manifest /tmp/test-collision-approved.yaml \
  --dry-run

# Expected: SUCCESS
# Exit code: 0
# Should NOT contain error message
```

### Validation: Dashboard renders without collision
```bash
# Traefik dashboard uses api@internal, must not create
# a generated load-balancer service that shadows central route

terraform -chdir=terraform/lxc \
  render-edge-traefik \
  --manifest terraform/lxc/stacks/proxy-stack/edge.yaml \
  --dry-run

# Should contain:
#   api@internal routing configured
# Should NOT contain:
#   duplicate service definition for traefik dashboard
#   intendedReplacement field in output
```

---

## Tasks 15-20 (Service Migrations) Validation

### Phase 1: Pre-deployment manifest validation
```bash
# Verify manifest exists
test -f terraform/lxc/stacks/authentik-stack/edge.yaml
echo "Manifest exists: $?"  # Must output 0

# Verify intendedReplacement field exists
grep -q "intendedReplacement:" \
  terraform/lxc/stacks/authentik-stack/edge.yaml
echo "Flag present: $?"  # Must output 0

# Verify hostname matches generated route
SERVICE_HOSTNAME=$(grep -A1 "intendedReplacement:" \
  terraform/lxc/stacks/authentik-stack/edge.yaml | \
  grep "hostname:" | awk '{print $NF}')
echo "Service hostname: $SERVICE_HOSTNAME"
# Expected: authentik.lab.gibbsgreatly.xyz

# Verify hostname matches a route in the manifest
grep -q "hostname: $SERVICE_HOSTNAME" \
  terraform/lxc/stacks/authentik-stack/edge.yaml | \
  grep -v intendedReplacement
echo "Route exists: $?"  # Must output 0
```

### Phase 2: Pre-deployment renderer dry-run
```bash
# Run renderer with pve-test target
./with-secrets terraform -chdir=terraform/lxc \
  render-edge-traefik \
  --manifest terraform/lxc/stacks/authentik-stack/edge.yaml \
  --dry-run

# Expected output:
#   Status: PASS
#   No collision errors
#   Exits with code 0

# If FAIL - check error message for remediation
```

### Phase 3: Pre-deployment reconciler dry-run
```bash
# Verify reconciler can process manifest
./with-secrets terraform -chdir=terraform/lxc \
  edge-reconciler \
  --manifest terraform/lxc/stacks/authentik-stack/edge.yaml \
  --dry-run

# Expected: Lists pending changes (manifest not yet deployed)
# Looking for:
#   Central route to remove: authentik.lab.gibbsgreatly.xyz
#   Generated route to add: authentik.lab.gibbsgreatly.xyz
#   DNS record updates: authentik.lab.gibbsgreatly.xyz
```

### Phase 4: Post-deployment DNS validation
```bash
# Check DNS resolves to edge IP (10.57.2.10)
dig @10.57.1.1 authentik.lab.gibbsgreatly.xyz +short
# Expected output: 10.57.2.10

# Or from external:
dig authentik.lab.gibbsgreatly.xyz +short
# Expected: Should resolve (CoreDNS or external DNS)
```

### Phase 5: Post-deployment HTTPS validation
```bash
# Check service is accessible via HTTPS
curl -kI https://authentik.lab.gibbsgreatly.xyz/

# Expected:
#   HTTP/1.1 200 OK (or 302 redirect, or 401 auth required)
#   Not: Connection refused, timeout, or 502 Bad Gateway

# Try actual service endpoints:
curl -kI https://authentik.lab.gibbsgreatly.xyz/api/
# Expected: service-specific response
```

### Phase 6: Post-deployment auth validation
```bash
# Verify NO infinite auth loop for Authentik itself
curl -kI https://authentik.lab.gibbsgreatly.xyz/ \
  | head -20

# Expected: Authentik server response, NOT redirect to itself

# For services with forward-auth, verify middleware works:
curl -kI https://harbor.lab.gibbsgreatly.xyz/
# Expected: redirect to Authentik login (Traefik forward-auth)
```

### Phase 7: Reconciler no-op validation (after cleanup)
```bash
# Remove intendedReplacement flag first
sed -i '/intendedReplacement:/,+2d' \
  terraform/lxc/stacks/authentik-stack/edge.yaml

# Re-run reconciler - should show no-op
./with-secrets terraform -chdir=terraform/lxc \
  edge-reconciler \
  --manifest terraform/lxc/stacks/authentik-stack/edge.yaml \
  --dry-run

# Expected output:
#   Pending changes: 0
#   Duplicates found: 0
#   Status: NO-OP ✓

# If not no-op, check what's still pending:
# - Central route still present?
# - Generated file missing or stale?
# - DNS record not updated?
```

### Phase 8: Service-specific validation
```bash
# For Authentik: No self-auth loop
curl -kv https://authentik.lab.gibbsgreatly.xyz/api/v3/system/info/ \
  2>&1 | grep -E "HTTP|Authentik"

# For Harbor: Registry client can login
docker login -u admin -p password harbor.lab.gibbsgreatly.xyz
# Expected: Login successful

# For Grafana: Access dashboard
curl -kI https://grafana.lab.gibbsgreatly.xyz/login
# Expected: 200 OK or redirect to Authentik

# For Portainer: Access UI
curl -kI https://portainer.lab.gibbsgreatly.xyz/
# Expected: service-specific response

# For NetBox: Access API
curl -kI https://netbox.lab.gibbsgreatly.xyz/api/
# Expected: 200 OK or auth challenge

# For Traefik: Dashboard accessible
curl -kI https://traefik.lab.gibbsgreatly.xyz/dashboard/
# Expected: 302 redirect (auth required)
```

---

## Task 21 (Final Cutover Cleanup) Validation

### Step 1: Verify all migrations complete
```bash
# Check all six manifests exist
for stack in authentik-stack harbor-stack grafana-stack \
             portainer-stack netbox-stack proxy-stack; do
  test -f terraform/lxc/stacks/$stack/edge.yaml && \
    echo "✓ $stack exists" || \
    echo "✗ $stack MISSING"
done

# Expected: 6 checkmarks (all present)
```

### Step 2: Verify no intendedReplacement flags remain
```bash
# Search across all stacks for flags
grep -r "intendedReplacement:" terraform/lxc/stacks/

# Expected output: EMPTY (no matches)
# If matches found, remove them before proceeding
```

### Step 3: Verify renderer finds no collisions
```bash
# Run renderer on all manifests
./with-secrets terraform -chdir=terraform/lxc \
  render-edge-traefik \
  --all-manifests \
  --dry-run

# Expected output:
#   Manifests processed: 6
#   Generated routes: 6
#   Collisions detected: 0
#   Status: PASS ✓
```

### Step 4: Verify central config is runtime-only
```bash
# Check central config contains no per-service routes
grep -E "authentik|harbor|grafana|portainer|netbox|traefik" \
  terraform/lxc/central-traefik-config.yml

# Expected output: EMPTY (no matches)
# Central should only have:
grep -E "entryPoints|certificateResolvers|middleware|defaultCertificate" \
  terraform/lxc/central-traefik-config.yml

# Expected: Several matches (runtime config)
```

### Step 5: Verify reconciler complete no-op
```bash
# Final reconciler dry-run with all manifests
./with-secrets terraform -chdir=terraform/lxc \
  edge-reconciler \
  --all-manifests \
  --dry-run

# Expected output:
#   Processing 6 manifests...
#   Pending changes: 0
#   Duplicate hosts: 0
#   Migrations in progress: 0
#   Status: COMPLETE NO-OP ✓
```

### Step 6: Validate all six routes are accessible
```bash
# Function to test each route
test_route() {
  local hostname=$1
  local expected_status=$2

  http_code=$(curl -sk -o /dev/null -w "%{http_code}" \
    https://$hostname/ 2>/dev/null)

  if [[ $http_code == $expected_status ]] || [[ $http_code == "302" ]] || [[ $http_code == "401" ]]; then
    echo "✓ $hostname responds with $http_code"
    return 0
  else
    echo "✗ $hostname responds with $http_code (expected $expected_status)"
    return 1
  fi
}

# Test all routes
test_route "authentik.lab.gibbsgreatly.xyz" "200"
test_route "harbor.lab.gibbsgreatly.xyz" "200"
test_route "grafana.lab.gibbsgreatly.xyz" "200"
test_route "portainer.lab.gibbsgreatly.xyz" "200"
test_route "netbox.lab.gibbsgreatly.xyz" "200"
test_route "traefik.lab.gibbsgreatly.xyz" "302"  # Dashboard requires auth

# All should show ✓
```

### Step 7: Verify DNS for all routes
```bash
# Function to verify DNS
verify_dns() {
  local hostname=$1
  local ip=$(dig +short $hostname @10.57.1.1)

  if [[ $ip == "10.57.2.10" ]]; then
    echo "✓ $hostname → $ip (Traefik edge)"
    return 0
  else
    echo "✗ $hostname → $ip (expected 10.57.2.10)"
    return 1
  fi
}

# Verify all DNS records
verify_dns "authentik.lab.gibbsgreatly.xyz"
verify_dns "harbor.lab.gibbsgreatly.xyz"
verify_dns "grafana.lab.gibbsgreatly.xyz"
verify_dns "portainer.lab.gibbsgreatly.xyz"
verify_dns "netbox.lab.gibbsgreatly.xyz"
verify_dns "traefik.lab.gibbsgreatly.xyz"

# All should show ✓
```

### Step 8: Verify certificates are valid
```bash
# Check all routes have valid certificates
check_cert() {
  local hostname=$1
  echo | openssl s_client -connect $hostname:443 -servername $hostname 2>/dev/null | \
    grep "subject=\|notBefore\|notAfter"
}

for host in authentik harbor grafana portainer netbox traefik; do
  echo "=== $host.lab.gibbsgreatly.xyz ==="
  check_cert "$host.lab.gibbsgreatly.xyz"
done

# All should show valid certificates for *.lab.gibbsgreatly.xyz
```

### Step 9: Test rollback procedure
```bash
# Snapshot current generated state
cp -r /opt/proxy-stack/dynamic/stacks \
  /opt/proxy-stack/dynamic/stacks.backup.pre-cutover-cleanup

# Simulate a rollback (e.g., restore from git)
git -C terraform/lxc checkout HEAD~1 -- terraform/lxc/central-traefik-config.yml

# Run reconciler to revert changes
./with-secrets terraform -chdir=terraform/lxc \
  edge-reconciler \
  --apply

# Verify routes still work with central config restored
test_route "authentik.lab.gibbsgreatly.xyz" "200"

# Rollback complete - restore current state
git -C terraform/lxc checkout HEAD -- terraform/lxc/central-traefik-config.yml

echo "Rollback test complete ✓"
```

---

## Troubleshooting Commands

### Show current state of a service
```bash
# For a specific service (e.g., Authentik)
SERVICE=authentik

echo "=== Manifest Status ==="
test -f terraform/lxc/stacks/${SERVICE}-stack/edge.yaml && echo "Manifest exists" || echo "Manifest missing"
grep "intendedReplacement:" terraform/lxc/stacks/${SERVICE}-stack/edge.yaml && echo "Migration flag present" || echo "Migration flag absent"

echo "=== Central Config ==="
grep "$SERVICE" terraform/lxc/central-traefik-config.yml && echo "Central route exists" || echo "Central route removed"

echo "=== Generated Files ==="
ls -la /opt/proxy-stack/dynamic/stacks/${SERVICE}-*.yml

echo "=== DNS Status ==="
dig +short ${SERVICE}.lab.gibbsgreatly.xyz @10.57.1.1

echo "=== HTTPS Status ==="
curl -sk -o /dev/null -w "HTTP %{http_code}\n" https://${SERVICE}.lab.gibbsgreatly.xyz/
```

### Show all pending changes
```bash
./with-secrets terraform -chdir=terraform/lxc \
  edge-reconciler \
  --all-manifests \
  --dry-run \
  --verbose

# Shows exactly what would change if applied
```

### Find collision sources
```bash
# List all hostnames in central config
echo "=== Central Routes ==="
grep "hostname:" terraform/lxc/central-traefik-config.yml | sort -u

# List all hostnames in generated manifests
echo "=== Generated Routes ==="
grep "hostname:" terraform/lxc/stacks/*/edge.yaml | \
  grep -v "intendedReplacement:" | \
  awk -F: '{print $NF}' | sort -u

# Find intersection (collisions)
echo "=== Collisions ==="
comm -12 <(grep "hostname:" terraform/lxc/central-traefik-config.yml | \
            awk '{print $NF}' | sort -u) \
         <(grep "hostname:" terraform/lxc/stacks/*/edge.yaml | \
            grep -v intendedReplacement: | \
            awk '{print $NF}' | sort -u)

# Should output NOTHING in Task 21
```

---

## Quick Validation Script

```bash
#!/bin/bash
# Full validation suite for Task 21

set -e

echo "=== Task 21 Final Cutover Validation ==="
echo ""

echo "1. Checking all manifests exist..."
for stack in authentik-stack harbor-stack grafana-stack \
             portainer-stack netbox-stack proxy-stack; do
  test -f "terraform/lxc/stacks/$stack/edge.yaml" && \
    echo "  ✓ $stack" || echo "  ✗ $stack MISSING"
done

echo ""
echo "2. Checking for remaining intendedReplacement flags..."
FLAGS=$(grep -r "intendedReplacement:" terraform/lxc/stacks/ 2>/dev/null || echo "")
if [ -z "$FLAGS" ]; then
  echo "  ✓ No flags found"
else
  echo "  ✗ Flags found:"
  echo "$FLAGS"
fi

echo ""
echo "3. Running renderer dry-run..."
./with-secrets terraform -chdir=terraform/lxc \
  render-edge-traefik --all-manifests --dry-run | head -5

echo ""
echo "4. Checking for collisions..."
COLLISIONS=$(comm -12 \
  <(grep "hostname:" terraform/lxc/central-traefik-config.yml | \
    awk '{print $NF}' | sort -u) \
  <(grep "hostname:" terraform/lxc/stacks/*/edge.yaml | \
    grep -v intendedReplacement: | \
    awk '{print $NF}' | sort -u) || echo "")
if [ -z "$COLLISIONS" ]; then
  echo "  ✓ No collisions found"
else
  echo "  ✗ Collisions found:"
  echo "$COLLISIONS"
fi

echo ""
echo "5. Running reconciler final dry-run..."
./with-secrets terraform -chdir=terraform/lxc \
  edge-reconciler --all-manifests --dry-run | grep -E "Pending|Duplicates|Status"

echo ""
echo "=== Validation Complete ==="
```

Save as `validate-task-21.sh` and run:
```bash
chmod +x validate-task-21.sh
./validate-task-21.sh
```

---

## Success Criteria Checklist

### Task 07 Success:
- [ ] All four unit tests pass
- [ ] Collision detection catches unintended duplicates
- [ ] intendedReplacement validation enforces one-per-manifest
- [ ] Error messages are clear and actionable
- [ ] Renderer output is stripped of intendedReplacement field

### Tasks 15-20 Success (for each):
- [ ] Manifest has intendedReplacement field before deployment
- [ ] Renderer dry-run succeeds
- [ ] Deployment atomic (central removed + generated added together)
- [ ] Route accessible via HTTPS
- [ ] DNS resolves to 10.57.2.10
- [ ] Auth behavior correct for service
- [ ] Reconciler shows no-op after cleanup

### Task 21 Success:
- [ ] All six manifests exist
- [ ] No intendedReplacement flags remain
- [ ] Renderer reports zero collisions
- [ ] Central config contains only runtime config
- [ ] Reconciler shows complete no-op
- [ ] All six routes accessible and working
- [ ] All six DNS records resolve correctly
- [ ] All six certificates valid
- [ ] Rollback procedure tested
