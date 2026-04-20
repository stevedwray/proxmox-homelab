# Teardown/Deploy Test Task Sequence

Each task is intended for one short-lived branch/session. Tasks 05 and later
contain destructive or live deployment operations and require explicit operator
approval at their gates.

| Step | Task | Type | Preconditions | Postconditions |
|---:|---|---|---|---|
| 00 | [Normalize completion state](tasks/00-normalize-completion-state.md) | Documentation | None | Existing refactor task status and generated-artifact warnings are clean enough for a rebuild test. |
| 01 | [Answer test variables](tasks/01-answer-test-variables.md) | Documentation | 00 | `variables.md` has no unresolved destructive-gate `TBD` values. |
| 02 | [Inventory scope and dependency order](tasks/02-inventory-scope-and-order.md) | Documentation | 01 | Platform stack list, exclusions, and rebuild order are explicit. |
| 03 | [Backup and restore readiness](tasks/03-backup-restore-readiness.md) | Operational planning | 02 | Persistent data policy is approved before destroy. |
| 04 | [Source and edge preflight](tasks/04-source-edge-preflight.md) | Validation | 03 | Clean working tree, known commit, generated edge artifacts refreshed, dry-runs pass. |
| 05 | [Destroy rehearsal execution](tasks/05-destroy-rehearsal.md) | Destructive execution | 04 and operator approval | Selected pve-test LXCs are destroyed and absence is verified. |
| 06 | [Foundation redeploy](tasks/06-foundation-redeploy.md) | Deployment | 05 | Stage 1/2 foundation services are running and validated. |
| 07 | [Edge foundation redeploy](tasks/07-edge-foundation-redeploy.md) | Deployment | 06 | CoreDNS, Traefik, step-ca, and Authentik direct/API bootstrap are healthy. |
| 08 | [Edge reconciliation activation](tasks/08-edge-reconciliation-activation.md) | Deployment | 07 | Generated DNS/Traefik/Auth state is published from fresh artifacts. |
| 09 | [Remaining platform redeploy](tasks/09-remaining-platform-redeploy.md) | Deployment | 08 | Monitoring, NetBox, and other selected Stage 3b stacks are running. |
| 10 | [End-to-end validation](tasks/10-end-to-end-validation.md) | Validation | 09 | DNS, HTTPS, auth, registry, API, and reconciler no-op checks pass. |
| 11 | [Evidence and follow-up closeout](tasks/11-evidence-closeout.md) | Documentation | 10 | Test report is complete and follow-up work is identified. |
