# Task 03: Cutover Semantics - Complete Documentation Index

This is the complete documentation suite for Task 03 (Define One-Host Route Cutover Semantics). All files together define the safety contract for migrating browser routes from legacy central Traefik configuration to stack-owned manifests.

## Core Task Definition

- **[03-cutover-semantics.md](03-cutover-semantics.md)** - The official task definition from the work order
  - Objective: Fix generated-vs-legacy route collision semantics
  - Preconditions, operations, postconditions, validation, and stop conditions
  - References to all dependent tasks (07, 15-20, 21)

## Problem & Solution Explanation

- **[03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md)** - Executive overview
  - The legacy vs. new model
  - The collision risk during migration
  - The four-step atomic pattern
  - File dependency map
  - Validation across tasks

## Implementation Contracts

- **[03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md)** - Full specification of what must be implemented
  - Manifest format with `intendedReplacement` field (Contract 1)
  - Renderer duplicate-detection algorithm (Contract 2)
  - Deployment unit atomicity definition (Contract 3)
  - Reconciler behavior during cutover (Contract 4)
  - Unit test cases
  - Error message templates

## State Machine & Validation Workflow

- **[03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md)** - Detailed state machine
  - Initial state (before migration)
  - Migration state N (during each task)
  - Intermediate states (between migrations)
  - Final state (after Task 21)
  - Expected renderer and reconciler outputs at each stage
  - Integration points between tasks
  - Stop conditions mapped to outputs

## Practical Implementation Guidance

- **[03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md)** - Quick reference for implementers
  - What Task 07 must implement (with code examples)
  - What Tasks 15-20 must do (step-by-step workflow)
  - What Task 21 must verify
  - Parallel safety (NO - one service per task)
  - Debugging guide for common issues
  - Implementation checklist

## Validation & Testing Commands

- **[03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md)** - Exact commands to run
  - Pre-migration setup (safety checks)
  - Task 07 validation commands (unit and integration tests)
  - Tasks 15-20 validation commands (by phase)
  - Task 21 validation commands (8 detailed steps)
  - Troubleshooting commands
  - Quick validation script for Task 21

## Related Core Documents

These documents define the context and policy for this task:

- **[decisions.md](../decisions.md#decision-5-traefik-runtime-split)** - Decision 5: Traefik Runtime Split
  - The one-host replacement principle
  - Central vs. generated route ownership model
  - Live publish atomicity requirement
  - Generated route validation rules

- **[03-cutover-semantics.md](03-cutover-semantics.md)** - Original task work order
  - Establishes the four-step operational pattern
  - References all dependent tasks

## Dependent Implementation Tasks

These tasks implement the contract defined by Task 03:

- **[07-traefik-renderer.md](07-traefik-renderer.md)** - Renderer implementation
  - Implements duplicate-host detection (from Contract 2)
  - Validates `intendedReplacement` field (from Contract 1)
  - Enforces one-flag-per-manifest limit
  - Provides clear error messages for three failure scenarios

- **[15-migrate-authentik.md](15-migrate-authentik.md)** - First migration (establishes pattern)
  - Uses the one-host workflow for Authentik
  - Validates dry-run finds no collision
  - Atomic deployment: remove central + add generated
  - Confirms reconciler no-op after cleanup

- **[16-migrate-harbor.md](16-migrate-harbor.md)** - Harbor migration
  - Follows same one-host replacement workflow as Task 15

- **[17-migrate-grafana.md](17-migrate-grafana.md)** - Grafana migration
  - Follows same one-host replacement workflow as Task 15

- **[18-migrate-portainer.md](18-migrate-portainer.md)** - Portainer migration
  - Follows same one-host replacement workflow as Task 15

- **[19-migrate-netbox.md](19-migrate-netbox.md)** - NetBox migration
  - Follows same one-host replacement workflow as Task 15

- **[20-migrate-traefik-dashboard.md](20-migrate-traefik-dashboard.md)** - Last migration
  - Uses same workflow but with `api@internal`
  - Last service before cleanup

- **[21-final-cutover-cleanup.md](21-final-cutover-cleanup.md)** - Cleanup & validation
  - Verifies all six migrations complete (no flags remain)
  - Confirms no collision hosts between generated and central
  - Validates central config contains no per-service routes
  - Final reconciler dry-run is complete no-op
  - Tests rollback procedure

## Reading Paths

### For Task 07 Implementer (Renderer)
1. Start: [03-cutover-semantics.md](03-cutover-semantics.md)
2. Understand: [03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md)
3. Implement: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md) (Contract 2)
4. Reference: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-07-traefik-renderer)
5. Test: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-07-traefik-renderer-validation)

### For Tasks 15-20 Implementer (Service Migration)
1. Start: [03-cutover-semantics.md](03-cutover-semantics.md)
2. Understand: [03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md)
3. Learn contract: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md) (Contract 1 & 3)
4. Review state machine: [03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#migration-state-n-during-task-15n)
5. Reference: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-tasks-15-20-service-migrations)
6. Follow task: [15-migrate-authentik.md](15-migrate-authentik.md) (first, establishes pattern)
7. Test: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#tasks-15-20-service-migrations-validation)

### For Task 21 Implementer (Cleanup)
1. Start: [03-cutover-semantics.md](03-cutover-semantics.md)
2. Understand: [03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md)
3. Review state machine: [03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#final-state-after-task-21)
4. Reference: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-21-final-cutover-cleanup)
5. Run validation: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-21-final-cutover-cleanup-validation)
6. Follow task: [21-final-cutover-cleanup.md](21-final-cutover-cleanup.md)

## Key Concepts

### The One-Host Replacement Semantics

**Four-step atomic pattern:**

1. **Dry-run detects collision** (Task 07 renderer)
   - Fails if generated route shadows central route without flag
   - Allows if `intendedReplacement` flag matches hostname

2. **Migration task marks intended replacement** (Tasks 15-20)
   - Adds `intendedReplacement` field with hostname
   - Signals "I know this host exists, I'm replacing it"
   - Only one host per migration task

3. **Atomic live deployment** (Tasks 15-20)
   - Remove central route + add generated route in same unit
   - Never a state where both exist
   - Trigger Traefik reload

4. **Post-deployment cleanup** (Tasks 15-20)
   - Remove `intendedReplacement` flag from manifest
   - Reconciler dry-run shows no-op
   - Commit manifest with flag removed

### Collision Detection Algorithm

```
For each generated hostname:
  if hostname exists in central config:
    if intendedReplacement matches this hostname:
      → ALLOW (expected migration)
    else:
      → FAIL (unexpected collision)
```

### Atomicity Definition

"Same deployment unit" means all of these happen together:
- Remove legacy central route definition
- Add generated route file
- Trigger Traefik reload
- Update DNS record

Never split into separate steps or deployments.

### No-Op Validation

After migration completes and flag is removed, reconciler should report:
- Pending changes: ZERO
- Duplicate hosts: ZERO
- Migrations in progress: ZERO
- Status: COMPLETE NO-OP

## Success Criteria

### Task 03 is complete when:
- All documentation files created (this index + supporting docs)
- Manifest format with `intendedReplacement` defined
- Renderer duplicate-detection algorithm specified
- Deployment unit atomicity defined
- Reconciler behavior documented
- Error messages and test cases provided
- Validation commands created
- All downstream tasks have clear requirements

### Task 07 is complete when:
- Renderer implements duplicate detection algorithm
- Manifest validation enforces one-flag-per-manifest
- Error messages match specifications
- All unit tests pass
- Integration tests pass
- Dry-run fails on unintended collisions
- Dry-run succeeds on approved collisions

### Tasks 15-20 are complete when (for each service):
- Manifest created with `intendedReplacement` field
- Renderer dry-run succeeds
- Deployment atomic (central removed + generated added together)
- Route accessible and working
- Reconciler shows no-op after cleanup
- Flag removed from manifest

### Task 21 is complete when:
- All six services migrated (no flags remain)
- No collisions detected
- Central config has only runtime config
- Reconciler shows complete no-op
- All six routes working correctly
- Rollback tested and documented

## File Structure Summary

```
docs/provisioning-refactor/
├── tasks/
│   ├── 03-cutover-semantics.md                    (core task definition)
│   ├── 03-cutover-semantics-SUMMARY.md            (overview)
│   ├── 03-CUTOVER-CONTRACT.md                     (implementation contract)
│   ├── 03-CUTOVER-STATE-TRANSITIONS.md            (state machine)
│   ├── 03-CUTOVER-QUICK-REFERENCE.md              (practical guide)
│   ├── 03-CUTOVER-VALIDATION-COMMANDS.md          (test commands)
│   ├── 03-CUTOVER-INDEX.md                        (this file)
│   ├── 07-traefik-renderer.md                     (dependent: renderer)
│   ├── 15-migrate-authentik.md                    (dependent: first migration)
│   ├── 16-migrate-harbor.md                       (dependent: migration)
│   ├── 17-migrate-grafana.md                      (dependent: migration)
│   ├── 18-migrate-portainer.md                    (dependent: migration)
│   ├── 19-migrate-netbox.md                       (dependent: migration)
│   ├── 20-migrate-traefik-dashboard.md            (dependent: last migration)
│   └── 21-final-cutover-cleanup.md                (dependent: cleanup)
├── decisions.md                                    (Decision 5: Traefik Runtime Split)
└── ... other tasks ...
```

## Cross-References by Category

### Manifest & Contract
- Manifest schema: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-1-manifest-format---intendedReplacement-field)
- Field semantics: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#constraints)
- Example manifests: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#example-manifest-structure-for-task-15-authentik)

### Renderer Implementation
- Algorithm: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-2-renderer-implementation)
- Error messages: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#renderer-error-messages)
- Unit tests: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#testing-the-contract-before-task-07-implementation)
- Validation: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-07-traefik-renderer-validation)

### Deployment & Atomicity
- Definition: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-3-deployment-unit-atomicity)
- Ansible example: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#implementation-in-ansible)
- Workflow: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#phase-3-deployment)

### State & Transitions
- Initial state: [03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#initial-state-before-any-migration)
- Migration state: [03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#migration-state-n-during-task-15n)
- Final state: [03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#final-state-after-task-21)

### Validation & Testing
- Full commands: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md)
- Quick script: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#quick-validation-script)
- Success criteria: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#success-criteria-checklist)

## Next Steps After Task 03

1. **Task 07**: Implement renderer with duplicate detection
   - Review [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-2-renderer-implementation)
   - Use [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-07-traefik-renderer)
   - Test with [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-07-traefik-renderer-validation)

2. **Tasks 15-20**: Perform service migrations
   - First: Follow [15-migrate-authentik.md](15-migrate-authentik.md) exactly
   - Next: Use [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-tasks-15-20-service-migrations)
   - Test: Use [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#tasks-15-20-service-migrations-validation)

3. **Task 21**: Final cleanup and validation
   - Reference: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-21-final-cutover-cleanup)
   - Test: Use [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-21-final-cutover-cleanup-validation)
   - Execute: [21-final-cutover-cleanup.md](21-final-cutover-cleanup.md)

---

**Document Version:** 2026-04-20
**Task:** 03 - Define One-Host Route Cutover Semantics
**Status:** Complete (documentation suite)
**Next Phase:** Task 07 - Traefik Renderer Implementation
