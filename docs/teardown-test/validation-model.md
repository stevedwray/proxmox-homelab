# Hard Validation Model

This document defines the highest-confidence validation path for the integrated
platform on `pve-test-vm`.

Use it when the question is not "does one change look reasonable?" but
"can the environment be torn down, rebuilt, reprovisioned, reconciled, and
validated end to end from repo state?"

## Purpose

The teardown/deploy process is the repo's hardest validation proof. It exists
to catch problems that incremental deploys can hide:

- hidden second-pass assumptions
- missing bootstrap ordering
- stale generated state
- edge reconciliation gaps
- cross-stack dependencies that only fail on a fresh rebuild

This is the operator-facing authority for that proof.

## Validation Layers

### Layer 1: preflight confidence

Before destructive work:

- clean working tree
- known commit
- target guard confirms `pve-test-vm`
- backup / restore expectations are approved
- generated edge artifacts refreshed
- dry-run validation passes where applicable

Primary docs:

- [variables.md](variables.md)
- [decisions.md](decisions.md)
- [runbook.md](runbook.md)
- [operations-plan.md](operations-plan.md)

### Layer 2: destructive rebuild proof

Destroy the approved stack scope and confirm absence before redeploy.

This validates:

- scope discipline
- ordering discipline
- rollback gates
- approval handling

Primary docs:

- [operations-plan.md](operations-plan.md)
- [task-sequence.md](task-sequence.md)

### Layer 3: foundation redeploy proof

Rebuild the foundational services in documented order and validate direct
health before edge/browser reconciliation becomes authoritative.

This validates:

- Stage 1 / Stage 2 bootstrap assumptions
- Stage 3a edge foundation readiness
- service health without hidden post-hoc repair

Primary docs:

- [operations-plan.md](operations-plan.md)
- [inventory.md](inventory.md)
- [runbook.md](runbook.md)

### Layer 4: edge reconciliation proof

Publish generated DNS, Traefik, and Authentik state only after the edge
foundation is healthy.

This is where the teardown-test story depends directly on the current
provisioning-refactor source of truth.

Provisioning-refactor documents:

- [../provisioning-refactor/README.md](../provisioning-refactor/README.md)
- [../provisioning-refactor/task-sequence.md](../provisioning-refactor/task-sequence.md)
- [../provisioning-refactor/runbook.md](../provisioning-refactor/runbook.md)

Teardown-test documents:

- [operations-plan.md](operations-plan.md)
- [runbook.md](runbook.md)

### Layer 5: integrated end-to-end proof

After redeploy and reconciliation, validate the integrated platform contract:

- DNS
- HTTPS / certificates
- browser routes
- auth behavior
- registry / API reachability
- reconciler no-op or expected-state behavior

Primary docs:

- [operations-plan.md](operations-plan.md)
- [runbook.md](runbook.md)
- [lessons-learned.md](lessons-learned.md)

## Relationship To Provisioning Refactor

`docs/provisioning-refactor/` remains the source of truth for stack-owned edge
bootstrap, render, reconcile, and migration mechanics.

`docs/teardown-test/` is the source of truth for the full hard-validation
process that proves those mechanics work inside a fresh integrated rebuild.

In practice:

- provisioning-refactor defines how edge state should work
- teardown-test proves that it does work in the real rebuild path

## Trusted Reading Order

For a new hard-validation session, read in this order:

1. [README.md](README.md)
2. this document
3. [variables.md](variables.md)
4. [decisions.md](decisions.md)
5. [operations-plan.md](operations-plan.md)
6. [runbook.md](runbook.md)
7. relevant provisioning-refactor docs when the session reaches edge
   reconciliation or edge-owned browser route validation

## What Should Stay Tracked Here

Keep tracked:

- validation rules
- execution order
- restore / rollback expectations
- durable lessons learned
- current operator flow

Do not keep tracked:

- raw evidence bundles
- transient handoffs
- prompts
- scratch execution logs

Those belong under the ignored local `artifacts/` workspace pattern.
