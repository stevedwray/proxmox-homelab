# Stage 4 — Exemplar Scaffolding

## Exemplars

- apt-cacher-stack
- harbor-stack

## Goals

- add the minimum shared scaffolding required for the exemplar pair
- preserve existing deployment behavior where practical
- keep changes narrow enough for a follow-on closeout session

## In Scope

- define the Stage 4 implementation checklist for shared contract rendering, generated inventory or vars handoff, and day-2 reconcile entrypoint expectations
- map the exact docs and code touchpoints to be changed in Stage 4 main-work
- define the minimal validation artifacts to collect in Stage 5

## Out Of Scope

- running Terraform, Ansible, or deployment scripts
- broad stack migrations beyond apt-cacher-stack and harbor-stack
- promotion or merge operations

## Stage 4 Implementation Checklist

- identify contract parsing and rendering surfaces used by both exemplars
- identify generated inventory or vars handoff surfaces required by both exemplars
- identify day-2 reconcile entrypoint updates needed for approval-aware execution
- define file-level change list for the Stage 4 main-work session
- define expected evidence artifacts for Stage 5 validation

## Expected Outputs

- this Stage 4 scope document
- updated handoff note referencing Stage 4 kickoff and next Stage 4 main-work objective
