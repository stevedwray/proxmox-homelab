# Handoff 01: Credential Controls

## Objective

Design and, if appropriate for the session, implement the first safe slice of
production credential controls for AI-operated workflows.

## Branch

- `work/productionize-01-credential-controls`

## Primary Source

- [Task 01: Production Credential Controls](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md:1)

## Scope

In scope:

- tighten the production credential control design
- document the control model
- optionally implement a first bounded code slice if it is safe and coherent

Out of scope:

- production network intent
- production storage manifest
- migrating real services

## Files To Read First

- [with-secrets](/home/steve/git/proxmox-homelab/with-secrets:1)
- [docs/productionize-refactor/tasks/01-credential-controls.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md:1)
- [docs/productionize-refactor/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:1)

## Files Most Likely To Change

- `with-secrets`
- potentially new `with-secrets-prod`
- docs under `docs/productionize-refactor/`
- secret-file naming docs only; do not populate real production secrets

## Constraints

- keep `pve-test` as the safe default path
- do not broaden production access casually
- prefer separating production flows rather than weakening current safeguards
- do not add real production secrets

## Done When

- the production credential control model is documented clearly
- the default wrapper still refuses non-`pve-test` unless explicitly overridden
- if a production wrapper is introduced, it is clearly more restrictive than
  the dev path
- read-only vs mutating production access is explicitly distinguished

## Validation

- default dev path remains safe
- production access is non-default
- mutation requires an extra gate beyond simply setting `ALLOW_PVE=true`

## Suggested Copilot Brief

```text
Work on Task 01 in docs/productionize-refactor/tasks/01-credential-controls.md.
Keep the scope tight: production credential controls only.
Read with-secrets and the productionize refactor docs first.
Preserve pve-test as the default-safe workflow.
Do not add real production secrets.
Prefer separate production paths over weakening the existing wrapper.
When done, update the relevant docs and summarize exactly what changed and what still remains.
```
