# Task 02: Implement Manifest Validator

## Type

Development

## Objective

Implement a local validator for stack-owned `edge.yaml` manifests.

## Scope

- Add code and tests for validation only.
- Read manifests from `terraform/lxc/stacks/*/edge.yaml`.
- Do not render Traefik, DNS, or Authentik state.
- Do not deploy anything.

## Inputs

- Contract from Task 01.
- Fixtures from Task 01.
- Existing Python/YAML repo patterns.

## Steps

1. Add manifest discovery for `terraform/lxc/stacks/*/edge.yaml`.
2. Parse YAML with structured validation.
3. Validate per-manifest schema.
4. Validate cross-manifest uniqueness:
   - hostnames
   - router names
5. Validate pve-test hostname suffix.
6. Validate backend/auth/TLS/DNS policy.
7. Add human-readable and machine-readable output.
8. Add focused tests using valid and invalid fixtures.

## Validation

- Valid fixtures pass.
- Invalid fixtures fail with expected error codes.
- Duplicate hostnames across two manifests fail.
- Running validator without manifests produces a clear no-manifest result.

## Done When

- Renderer and reconciler tasks can call the validator before doing any work.

## Stop Conditions

- Stop if the Task 01 contract is ambiguous. Update the contract in a separate
  docs task before continuing.
