# Stage 3 — Exemplar Scope

## Selected Exemplars

- apt-cacher-stack
- harbor-stack

## In Scope

- Lock the exemplar pair for Stage 3 implementation: `apt-cacher-stack` and `harbor-stack`.
- Capture exact in-scope implementation boundaries for the two stacks and the minimal validation evidence required to claim success.
- Author the Stage 3 artifacts and the associated handoff note into the project docs.

## Out Of Scope

- Any Terraform, Ansible, or scripts/ command execution as part of this Stage.
- Branch creation, pushes, or PR workflows.

## Stack-Specific Risks And Dependencies

- apt-cacher-stack: requires accessible storage for cache persistence and network reachability from target clients.
- harbor-stack: requires certificate provisioning and sufficient node resources; depends on registry connectivity for verification steps.
- Cross-stack: ensure ingress/egress network policies do not prevent validation checks.

## Expected Validation Evidence

- Presence of this document with required sections committed to the branch.
- A short checklist mapping the minimal verification commands and files that will be used by Stage 4 (document-only in Stage 3).
- Reference to the prior bootstrap report used as input: `.git/ai/sessions/slr-03-bootstrap-01-report.md`.

## Deferred Candidates

- netbox-stack — recorded as a deferred candidate for Stage 4 consideration.
