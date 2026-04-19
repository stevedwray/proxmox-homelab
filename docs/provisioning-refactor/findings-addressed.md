# Findings Addressed

This document maps the review findings to the current bootstrap-aware
provisioning refactor plan.

## Finding 1: DNS Ownership Was Split

Resolution: CoreDNS is the record authority for `lab.gibbsgreatly.xyz`.
MikroTik remains resolver, conditional forwarder, and network policy point.

Task impact:

- Task 02 defines the seed/generated DNS transition.
- Task 08 renders CoreDNS zone output.
- Task 12 wires CoreDNS publish/reload behavior.

## Finding 2: Bootstrap Order Was Missing

Resolution: Stage 3a is now documented as CoreDNS seed zone -> Traefik runtime
-> step-ca -> Authentik direct first boot/API token -> edge reconciler.

Task impact:

- Task 01 documents Stage 3a in `docs/design/bootstrap.md`.
- Edge apply mode is unavailable until the foundation is healthy.

## Finding 3: Terraform Two-Pass Detection Was Risky

Resolution: Terraform provisions LXCs only. Edge reconciliation is an explicit,
dry-run-first operator command.

Task impact:

- Task 11 implements the edge reconciler.
- Apply mode requires explicit operator intent and health preflight.

## Finding 4: Generated Routes Collided With Legacy Central Routes

Resolution: Migration uses an explicit one-host intended-replacement workflow.

Task impact:

- Task 03 documents cutover semantics.
- Task 06 inventories legacy routes.
- Task 07 enforces renderer collision rules.
- Tasks 15 through 20 replace one service route at a time.

## Finding 5: Authentik Automation Was Too Broad

Resolution: Authentik work stays split into read-only discovery and
create/update-only reconciliation.

Task impact:

- Task 09 is read-only discovery.
- Task 10 is create/update reconciliation only.
- Deletes remain out of scope.

## Finding 6: Manifest Location Was Ambiguous

Resolution: `terraform/lxc/stacks/<stack>/edge.yaml` is the only manifest path.

Task impact:

- Task 04 documents the contract.
- Task 05 discovers only that path.
