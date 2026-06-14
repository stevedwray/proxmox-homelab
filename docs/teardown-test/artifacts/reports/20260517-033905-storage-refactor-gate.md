# Storage Refactor Gate Closeout (20260517-033905)

## Execution Summary

- Branch: work/storage-refactor-plan
- Final commit at gate run: 9e3766b (`fix: make storage check messages null-safe`)
- Evidence stamp: 20260517-033905
- Evidence path: docs/teardown-test/evidence/20260517-033905/ (gitignored)
- Approval packet: docs/teardown-test/evidence/20260517-033905/approval-packet-op06.md
- Harness command: `./scripts/teardown-deploy-test.sh cycle --execute --stamp 20260517-033905`
- End time: 2026-05-17T04:27:21Z
- Exit code: 0

## Gate Result

**✅ PASSED** — The full teardown + redeploy validation cycle succeeded.

## Phase Results

All phases in the cycle completed successfully:

- approval-preflight: Passed (exit=0)
  - Clean tree, branch/commit capture, all source and live preflight checks passed
- destroy: Passed (exit=0)
  - All 10 in-scope stacks destroyed cleanly in order; each VMID absence verified
- deploy-foundation: Passed (exit=0)
  - apt-cacher-stack (VMID 142) and ci-runner-01 (VMID 141) applied, provisioned, and smoke-checked
- deploy-edge: Passed (exit=0)
  - dns-stack (151), step-ca-stack (152), proxy-stack (153), authentik-stack (150) applied and provisioned
- activate-edge: Passed (exit=0)
  - Edge renders, Authentik reconcile, CoreDNS/Traefik publish, post-activate reconcile all passed
- deploy-platform: Passed (exit=0)
  - harbor-stack (121), monitoring-stack (154), netbox-stack (143), portainer-stack (120) applied and provisioned
- final-validation: Passed (exit=0)
  - DNS authoritative + delegated assertions for primary and `-bg` FQDNs passed
  - HTTPS routes and direct service health checks passed
  - final-reconcile-edge-dry-run passed with no pending changes

## Storage Refactor Regressions Fixed

Two targeted regressions in the refactor were exposed and fixed during the gate:

### Regression 1: Conditional Type Mismatch in storage_manifest Local
**File:** [terraform/lxc/main.tf](terraform/lxc/main.tf)

**Issue:** The conditional expression `storage_manifest_exists ? yamldecode(...) : {}` produced type mismatch because the true branch returns a decoded YAML object with fields like `defaults`, while the false branch returns an empty object `{}` without those fields. OpenTofu/Terraform type inference failed on the mismatch.

**Fix:** Commit 9315add — Changed to `try(yamldecode(file(...)), {})` to use consistent error-handling instead of a conditional, ensuring both paths return compatible empty-dict types.

### Regression 2: Null-Unsafe Error Messages in Checks
**File:** [terraform/lxc/main.tf](terraform/lxc/main.tf)

**Issue:** Three check blocks had error messages that interpolated potentially-null locals:
- `legacy_rootfs_storage_mapping_exists` — interpolated `local.legacy_rootfs_storage` (can be null)
- `legacy_extra_mount_storage_mapping_exists` — interpolated `local.legacy_extra_mount_storage` (can be null)
- `extra_mount_backend_supports_required_content` — interpolated `local.resolved_extra_mount_storage` (can be null)

OpenTofu/Terraform cannot interpolate null values in string templates, causing evaluation failures during destroy state refresh.

**Fix:** Commit 9e3766b — Wrapped null-prone variables with `coalesce(..., "<unset>")` to ensure all interpolations are string-safe:
- `"Legacy rootfs_storage '${coalesce(local.legacy_rootfs_storage, "<unset>")}' is not mapped..."`
- `"Legacy extra_mount_storage '${coalesce(local.legacy_extra_mount_storage, "<unset>")}' is not mapped..."`
- `"Resolved extra mount backend '${coalesce(local.resolved_extra_mount_storage, "<unset>")}' does not advertise..."`

## Promotion Status

This successful cycle satisfies the `baseline/teardown-validated` promotion gate for branch `work/storage-refactor-plan`.

**Gate Requirements Met:**
- ✅ Full teardown validation: all stacks destroyed cleanly in order
- ✅ Full redeploy validation: all stacks redeployed, provisioned, and healthy
- ✅ Final validation: DNS, HTTPS routes, direct service checks, and reconcile all passed
- ✅ Storage-refactor-caused regressions identified and fixed
- ✅ No unrelated churn or environmental pre-existing failures

## Branch Readiness

The branch is ready for merge to `baseline/teardown-validated` because:

1. The manifest-driven storage refactor model is complete and validated.
2. Stack files use intent fields (`storage_profile`, `template_name`, `extra_mount_profile`) instead of hardcoded physical backend names.
3. The Terraform root layer resolves storage configuration before module invocation.
4. Storage validation is integrated into the preflight harness and passes for both source-only and live modes.
5. The full destructive gate proves the refactor works end-to-end on a live, rebuildable environment.

## Remaining Work

None blocking promotion. However, operators should note:

- Backup evidence for this cycle was marked advisory-only (pve-test is fully disposable).
- Post-merge, the planning docs and this closeout report can be kept in the reference hierarchy under `docs/teardown-test/reports/`.
