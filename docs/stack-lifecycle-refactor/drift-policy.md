# Drift Policy

## Goal

Provide a clear operational model for day-2 drift handling.

## Drift Classes

### Managed

- Ansible is authoritative.
- Drift should be detected and normally corrected by reconcile.
- Unknown drift in these areas should be reported and may require operator approval before overwrite.

### Observed

- Drift should be reported but not automatically corrected.
- Useful for audit-sensitive or transitional areas.

### Adoptable

- Manual changes may be intentionally made and later incorporated into managed configuration.
- The workflow should support operator review before adoption.

## Recommended Default

### Essential Infrastructure Stacks

- default to `managed`
- low tolerance for manual in-container tuning

### Future General Application Stacks

- allow more `adoptable` areas where iterative tuning is likely

## Early Adoption Target

- Docker and compose-level service reconfiguration is the first likely candidate for an adoption workflow.

## Open Questions

- exact paths and settings per stack that belong in each class
- how drift should be surfaced to the operator
- whether the first implementation is reporting-only before enforcement
