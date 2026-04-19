# Task 03: Complete Documentation Suite - Summary

You've requested Task 03 (Define One-Host Route Cutover Semantics). Here's the complete documentation suite that's been created.

---

## 📋 Files Created

| File | Purpose | Audience |
| --- | --- | --- |
| **03-cutover-semantics.md** | Official task definition | Everyone (start here) |
| **03-CUTOVER-INDEX.md** | Master index & navigation | Everyone |
| **03-cutover-semantics-SUMMARY.md** | Executive overview | Architects, PMs |
| **03-CUTOVER-CONTRACT.md** | Full implementation spec | Task 07, 15-20, 21 implementers |
| **03-CUTOVER-STATE-TRANSITIONS.md** | State machine & outputs | Task 07, 21 implementers |
| **03-CUTOVER-QUICK-REFERENCE.md** | Quick guide by task | All implementers |
| **03-CUTOVER-VALIDATION-COMMANDS.md** | Exact test commands | All implementers |
| **03-MANIFEST-FORMAT-REFERENCE.md** | YAML format & examples | Tasks 15-20 implementers |

---

## 🎯 Quick Navigation

### I want to understand what Task 03 is about
1. Read: [03-cutover-semantics.md](03-cutover-semantics.md) (2 min)
2. Then: [03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md) (5 min)

### I'm implementing Task 07 (Traefik Renderer)
1. Read: [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-2-renderer-implementation) - Renderer Algorithm
2. Review: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-07-traefik-renderer)
3. Test: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-07-traefik-renderer-validation)

### I'm implementing Tasks 15-20 (Service Migrations)
1. Study: [03-MANIFEST-FORMAT-REFERENCE.md](03-MANIFEST-FORMAT-REFERENCE.md)
2. Learn: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-tasks-15-20-service-migrations)
3. Follow: [15-migrate-authentik.md](15-migrate-authentik.md) (first)
4. Test: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#tasks-15-20-service-migrations-validation)

### I'm implementing Task 21 (Cleanup)
1. Review: [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-21-final-cutover-cleanup)
2. Understand: [03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#final-state-after-task-21)
3. Execute: [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-21-final-cutover-cleanup-validation)

---

## 🔍 What Each Document Contains

### 03-cutover-semantics.md
- **Type**: Core Task Definition
- **Length**: 1 page
- **Content**: Objective, files, preconditions, operations, postconditions, validation, stop conditions
- **Use**: Reference for task scope

### 03-CUTOVER-INDEX.md
- **Type**: Master Index & Navigation
- **Length**: 5 pages
- **Content**: Complete file listing, reading paths by role, cross-references, success criteria
- **Use**: Find what you need quickly

### 03-cutover-semantics-SUMMARY.md
- **Type**: Executive Overview
- **Length**: 3 pages
- **Content**: Problem statement, one-host pattern, file dependencies, validation across tasks
- **Use**: Understand the big picture

### 03-CUTOVER-CONTRACT.md
- **Type**: Implementation Specification
- **Length**: 8 pages
- **Content**: 4 contracts (manifest format, renderer algorithm, atomicity, reconciler behavior)
- **Use**: Implementation reference

### 03-CUTOVER-STATE-TRANSITIONS.md
- **Type**: State Machine Documentation
- **Length**: 7 pages
- **Content**: State transitions, expected outputs at each stage, validation commands, stop conditions
- **Use**: Understand what outputs to expect

### 03-CUTOVER-QUICK-REFERENCE.md
- **Type**: Quick Implementation Guide
- **Length**: 6 pages
- **Content**: What Task 07, 15-20, 21 must do; debugging guide; checklist
- **Use**: Quick lookup during implementation

### 03-CUTOVER-VALIDATION-COMMANDS.md
- **Type**: Test & Validation Commands
- **Length**: 10 pages
- **Content**: Exact commands for each phase; shell scripts; success criteria
- **Use**: Validate work at each stage

### 03-MANIFEST-FORMAT-REFERENCE.md
- **Type**: YAML Format Reference
- **Length**: 6 pages
- **Content**: Manifest structure, service examples, auth modes, before/after, templates
- **Use**: Create and validate manifests

---

## 🧠 Key Concepts Explained

### The One-Host Replacement Semantics

**Problem**: During migration from central config to stack-owned manifests, both legacy and generated routes exist for the same service, creating duplicate hosts that Traefik can't resolve.

**Solution**: Four-step atomic pattern:

1. **Dry-run detects collision** (Task 07)
   - Renderer fails if generated route shadows central route without approval

2. **Migration task marks intended replacement** (Tasks 15-20)
   - Add `intendedReplacement` field to manifest
   - Signals "I know this host exists, I'm replacing it"

3. **Atomic live deployment** (Tasks 15-20)
   - Remove central route AND add generated route in same deployment unit
   - Never a state where both exist

4. **Post-deployment cleanup** (Tasks 15-20)
   - Remove `intendedReplacement` flag
   - Reconciler shows no-op (complete)

### Deployment Unit Atomicity

"Same deployment unit" means ALL of these happen together:
- Remove legacy central route definition
- Add generated route file
- Trigger Traefik reload
- Update DNS record

Never split into separate steps or deployments.

### The intendedReplacement Field

```yaml
intendedReplacement:
  - hostname: authentik.lab.gibbsgreatly.xyz
    reason: "Migrating from central Traefik config"
    startedAt: "2026-04-20T14:30:00Z"
```

**When to add**: Before first deployment (signals migration in-progress)
**When to remove**: After deployment succeeds (signals migration complete)
**Constraints**: Exactly one hostname, must match a generated route

---

## 📊 Documentation Relationships

```
Task 03: Define Cutover Semantics (POLICY)
  ↓
  ├─→ decisions.md (Decision 5)
  │    (Traefik Runtime Split principle)
  │
  ├─→ 03-CUTOVER-INDEX.md (NAVIGATION)
  │    (Links to all documents)
  │
  ├─→ 03-cutover-semantics-SUMMARY.md (OVERVIEW)
  │    (Big picture explanation)
  │
  ├─→ 03-CUTOVER-CONTRACT.md (SPECIFICATION)
  │    ├─ Contract 1: Manifest format
  │    ├─ Contract 2: Renderer algorithm
  │    ├─ Contract 3: Atomicity
  │    └─ Contract 4: Reconciler behavior
  │
  ├─→ 03-CUTOVER-STATE-TRANSITIONS.md (STATE MACHINE)
  │    (Expected outputs at each stage)
  │
  ├─→ 03-MANIFEST-FORMAT-REFERENCE.md (YAML GUIDE)
  │    (Format & examples)
  │
  ├─→ 03-CUTOVER-QUICK-REFERENCE.md (QUICK GUIDE)
  │    ├─ For Task 07
  │    ├─ For Tasks 15-20
  │    └─ For Task 21
  │
  └─→ 03-CUTOVER-VALIDATION-COMMANDS.md (TEST COMMANDS)
       ├─ Task 07 validation
       ├─ Tasks 15-20 validation
       └─ Task 21 validation

   ↓

IMPLEMENTATION TASKS
  ├─ Task 07: Traefik Renderer (implements Contract 2)
  ├─ Tasks 15-20: Service Migrations (use Contract 1 & 3)
  └─ Task 21: Final Cleanup (validates Contract 4)
```

---

## ✅ Checklist: Task 03 Complete When

- [x] Core task definition created
- [x] Master index created
- [x] Executive overview created
- [x] Implementation contract specified
- [x] State machine documented
- [x] Quick reference guide created
- [x] Validation commands provided
- [x] Manifest format examples provided
- [x] Collision detection algorithm documented
- [x] Atomic deployment pattern defined
- [x] Error messages specified
- [x] Unit test cases defined
- [x] All downstream tasks have clear requirements
- [x] Navigation/reading paths created for each role

---

## 🎓 Reading Recommendations

### For First-Time Readers
1. **[03-cutover-semantics.md](03-cutover-semantics.md)** (2 min) - What is Task 03?
2. **[03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md)** (5 min) - How does it work?
3. **[03-CUTOVER-INDEX.md](03-CUTOVER-INDEX.md)** (5 min) - Where do I go next?

### For Task 07 Implementer
1. **[03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-2-renderer-implementation)** (15 min)
2. **[03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#duplicate-host-detection-phase)** (10 min)
3. **[03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-07-traefik-renderer)** (5 min)
4. **[03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-07-traefik-renderer-validation)** (10 min)

### For Tasks 15-20 Implementer (repeated 6 times)
1. **[03-MANIFEST-FORMAT-REFERENCE.md](03-MANIFEST-FORMAT-REFERENCE.md)** (10 min)
2. **[03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-tasks-15-20-service-migrations)** (5 min)
3. **[15-migrate-authentik.md](15-migrate-authentik.md)** (for first task, then similar pattern)
4. **[03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#tasks-15-20-service-migrations-validation)** (during execution)

### For Task 21 Implementer
1. **[03-CUTOVER-STATE-TRANSITIONS.md](03-CUTOVER-STATE-TRANSITIONS.md#final-state-after-task-21)** (5 min)
2. **[03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-task-21-final-cutover-cleanup)** (5 min)
3. **[03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-21-final-cutover-cleanup-validation)** (15 min)

---

## 📁 File Locations

All files are in: `docs/provisioning-refactor/tasks/`

```
03-cutover-semantics.md                    ← Core task definition
03-CUTOVER-INDEX.md                        ← Master navigation (start here)
03-cutover-semantics-SUMMARY.md            ← Overview
03-CUTOVER-CONTRACT.md                     ← Implementation spec
03-CUTOVER-STATE-TRANSITIONS.md            ← State machine
03-CUTOVER-QUICK-REFERENCE.md              ← Quick guide
03-CUTOVER-VALIDATION-COMMANDS.md          ← Test commands
03-MANIFEST-FORMAT-REFERENCE.md            ← YAML guide
```

Related files referenced:
- `decisions.md` - Decision 5 (policy)
- `07-traefik-renderer.md` - Implementation task
- `15-migrate-authentik.md` through `20-migrate-traefik-dashboard.md` - Service migrations
- `21-final-cutover-cleanup.md` - Cleanup task

---

## 🚀 Next Steps

### For Team Lead / Architect
1. Read [03-cutover-semantics-SUMMARY.md](03-cutover-semantics-SUMMARY.md)
2. Review [03-CUTOVER-INDEX.md](03-CUTOVER-INDEX.md) for task assignments
3. Assign Task 07 to primary implementer
4. Ensure Tasks 15-20 are sequenced (one at a time)
5. Assign Task 21 to final validator

### For Task 07 Implementer
1. Read [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#contract-2-renderer-implementation)
2. Review test cases in [03-CUTOVER-CONTRACT.md](03-CUTOVER-CONTRACT.md#testing-the-contract-before-task-07-implementation)
3. Implement duplicate-detection algorithm
4. Run validation commands from [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-07-traefik-renderer-validation)

### For Tasks 15-20 Implementers
1. Copy manifest template from [03-MANIFEST-FORMAT-REFERENCE.md](03-MANIFEST-FORMAT-REFERENCE.md)
2. Follow workflow from [03-CUTOVER-QUICK-REFERENCE.md](03-CUTOVER-QUICK-REFERENCE.md#for-tasks-15-20-service-migrations)
3. Run validation at each phase from [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#tasks-15-20-service-migrations-validation)
4. One service per task (no parallel migrations)

### For Task 21 Implementer
1. Verify all six migrations complete (no flags remain)
2. Run final validation from [03-CUTOVER-VALIDATION-COMMANDS.md](03-CUTOVER-VALIDATION-COMMANDS.md#task-21-final-cutover-cleanup-validation)
3. Test rollback procedure
4. Document completion

---

## 💡 Key Insights

### Why One Host Per Task?
- Multiple migrations = multiple `intendedReplacement` flags = collision detection fails
- Single migration per task = clearer validation = safer deployment
- Sequential approach = each migration is independent and testable

### Why Atomic Deployment?
- Traefik can't have duplicate hosts
- Without atomicity: window where both central and generated exist = duplicate error
- With atomicity: route switches from central to generated in one step

### Why Post-Deployment Flag Removal?
- Flag signals "migration in progress"
- Removing flag signals "migration complete"
- Second reconciler run (no-op) confirms success
- Provides clear checkpoint for completion

### Why Central Config Only Runtime?
- Central config should contain shared runtime settings
- Per-service routes move to generated files (stack-owned)
- Clean separation of concerns
- Easier to manage and scale

---

## 📞 Questions? Refer To:

| Question | Document | Section |
| --- | --- | --- |
| What is Task 03? | 03-cutover-semantics.md | Objective |
| How does it work? | 03-cutover-semantics-SUMMARY.md | The One-Host Replacement Semantics |
| What's the algorithm? | 03-CUTOVER-CONTRACT.md | Contract 2 |
| What format for manifest? | 03-MANIFEST-FORMAT-REFERENCE.md | Manifest Structure |
| What should I expect? | 03-CUTOVER-STATE-TRANSITIONS.md | Appropriate state |
| How do I test? | 03-CUTOVER-VALIDATION-COMMANDS.md | Appropriate phase |
| What are stop conditions? | 03-CUTOVER-QUICK-REFERENCE.md | Stop Conditions |
| What's next? | 03-CUTOVER-INDEX.md | Next Steps After Task 03 |

---

**Version**: 2026-04-20
**Status**: Complete Documentation Suite
**Ready for**: Task 07 Implementation

Next: Task 07 (Traefik Renderer Implementation)
