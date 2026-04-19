# Task 00: Normalize Planning Docs

## Type

Documentation

## Objective

Make `docs/provisioning-refactor/` the explicit source of truth for the
stack-owned DNS, Traefik, and Authentik provisioning refactor.

## Scope

- Add or update documentation only.
- Do not modify Terraform, Ansible, scripts, or stack runtime files.
- Do not deploy anything.

## Steps

1. Review older Phase 04 browser-ingress docs and prompts.
2. Add notes that those docs are legacy context for this refactor.
3. Confirm this directory states:
   - pve-test hostnames use `*.lab.gibbsgreatly.xyz`
   - CoreDNS owns `lab.gibbsgreatly.xyz` records
   - MikroTik remains resolver and conditional forwarder
   - stack manifests live at `terraform/lxc/stacks/<stack>/edge.yaml`
4. Ensure no task points agents at apex `*.gibbsgreatly.xyz` for pve-test.

## Validation

- Search docs for browser ingress references and verify old conflicts are either
  resolved or explicitly marked legacy.
- Confirm no functional files changed.

## Done When

- Future agents can identify this directory as the refactor source of truth.
- Legacy docs no longer look like competing instructions.

## Stop Conditions

- Stop if resolving the conflict would require changing functional code.
